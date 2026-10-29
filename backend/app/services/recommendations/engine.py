"""Recommendation engine (step 11, CLAUDE.md sections 9, 22-24; docs/methodology.md, section 13).

Given the evaluated portfolios (the current one first), it answers: which of them to show, and
whether the household should change.

Net benefit of a candidate, in EUR a year, against the current portfolio:

    net = saving - value of time x extra perceived hours - change penalty

The extra perceived hours are the extra hours of travel, each weighted by its discomfort (the
same weight the assignment uses), so time and comfort are priced together: an extra hour in a
crowded bus costs more than one in a car. The change penalty is the effort of changing - a car
sold, a vehicle bought, a subscription cancelled or started, a new reliance on car sharing -
which stops the engine from recommending a big change for a small gain.

Strength of a recommendation (thresholds in `recommendation.net_benefit.*`):

    net < keep_below                     KEEP_CURRENT
    net < consider_from                  SMALL_IMPROVEMENT
    net < strong_from                    CONSIDER_CHANGE
    net >= strong_from                   STRONG_OPPORTUNITY, only if even the pessimistic end of
                                         the range reaches keep_below

Which portfolios are shown (CLAUDE.md section 9), deduplicated when one holds several roles:

    CURRENT          the baseline, always
    CHEAPEST         lowest annual cost of all the feasible portfolios, the current one included
    FASTEST          fewest hours of travel
    MOST_COMFORTABLE highest comfort
    BALANCED         the best compromise *for this household*: of the Pareto-efficient portfolios
                     (none is better on cost, time, comfort and flexibility together - and on car
                     km and CO2, if the household weighs them) the one that improves most on
                     today, by the household's own priorities (`Preferences`, 0-5). Every
                     criterion is the relative change against the current portfolio (cost -30% =
                     +0.3, comfort -10% = -0.1, clipped to +-1), weighted and averaged; the
                     current portfolio scores 0, so it is chosen unless something improves on it.
                     The cost counts the change penalty, so the compromise is not an upheaval.
                     Car dependence and CO2 enter only if the household gave them a weight.

The extremes are by definition one-sided, and the strength says whether they are worth it: the
cheapest portfolio of a family that would lose 600 hours a year to save 1,100 EUR is KEEP_CURRENT.
`headline_portfolio_id` is the answer to "should I change?": the candidate with the highest net
benefit if it reaches `keep_below`, else the current portfolio.

Explanations are structured facts (`ExplanationFact`) produced here from the numbers of the
evaluation; the Italian sentences are rendered from the facts alone (`wording.render`).
"""

from collections.abc import Callable
from dataclasses import dataclass

from app.data.loader import Catalog
from app.models import (
    ChangeKind,
    CurrentCostResult,
    EvaluatedPortfolio,
    ExplanationFact,
    MobilityDemand,
    Mode,
    Ownership,
    Portfolio,
    PortfolioEvaluation,
    Preferences,
    Range,
    Recommendation,
    RecommendationCategory,
    RecommendationRole,
    RecommendationSet,
    RecommendationStrength,
    ServiceKind,
    UserProfile,
)
from app.services.recommendations import wording

# tolerances under which two portfolios are not told apart (dominance, ties)
_EPS_COST, _EPS_HOURS, _EPS_SCORE, _EPS_KM, _EPS_CO2 = 1.0, 0.5, 0.01, 10.0, 5.0
_ROLE_ORDER = (
    RecommendationRole.CURRENT,
    RecommendationRole.CHEAPEST,
    RecommendationRole.BALANCED,
    RecommendationRole.FASTEST,
    RecommendationRole.MOST_COMFORTABLE,
)
_ALREADY = {
    RecommendationRole.CHEAPEST: "la più economica",
    RecommendationRole.FASTEST: "la più veloce",
    RecommendationRole.MOST_COMFORTABLE: "la più comoda",
}


@dataclass(frozen=True)
class _Appraisal:
    """A candidate with the numbers that decide its place."""

    entry: EvaluatedPortfolio
    evaluation: PortfolioEvaluation
    penalty: float
    saving: Range
    time_eur: float  # signed: positive if the candidate saves time
    comfort_eur: float  # signed: positive if it is more comfortable
    net: Range
    strength: RecommendationStrength
    category: RecommendationCategory

    @property
    def portfolio(self) -> Portfolio:
        return self.entry.portfolio


class RuleBasedRecommendationEngine:
    def __init__(self, catalog: Catalog) -> None:
        self._catalog = catalog
        value = catalog.value
        self._penalties = {
            ChangeKind.SELL_VEHICLE: value("recommendation.penalty.sell_vehicle"),
            ChangeKind.BUY_VEHICLE: value("recommendation.penalty.buy_vehicle"),
            ChangeKind.CANCEL_SUBSCRIPTION: value("recommendation.penalty.cancel_subscription"),
            ChangeKind.START_SUBSCRIPTION: value("recommendation.penalty.start_subscription"),
        }
        self._sharing_penalty = value("recommendation.penalty.car_sharing_dependence")
        self._sharing_min_uses = value("recommendation.car_sharing_dependence_min_uses_per_year")
        self._keep_below = value("recommendation.net_benefit.keep_below")
        self._consider_from = value("recommendation.net_benefit.consider_from")
        self._strong_from = value("recommendation.net_benefit.strong_from")
        self._value_of_time = value("valuation.value_of_time_eur_per_hour")

    def recommend(
        self,
        evaluated: list[EvaluatedPortfolio],
        demand: MobilityDemand,
        current_cost: CurrentCostResult,
        profile: UserProfile,
    ) -> RecommendationSet:
        """`evaluated[0]` is the current portfolio; candidates rejected by the feasibility check
        (no evaluation) are ignored here, they are reported by the caller."""
        current = evaluated[0]
        assert current.evaluation is not None, "the current portfolio is always evaluated"
        candidates = [
            self._appraise(entry, current)
            for entry in evaluated[1:]
            if entry.evaluation is not None and entry.evaluation.delta is not None
        ]
        everything = [current, *(a.entry for a in candidates)]

        pareto = self._pareto(everything, profile.preferences)
        roles = self._roles(everything, pareto, profile.preferences)
        best = max(candidates, key=lambda a: (a.net.expected, a.portfolio.id), default=None)
        headline = best if best and best.net.expected >= self._keep_below else None
        headline_id = headline.portfolio.id if headline else current.portfolio.id

        by_id = {a.portfolio.id: a for a in candidates}
        shown = [current.portfolio.id]
        for role in _ROLE_ORDER[1:]:
            holder = next((pid for pid, held in roles.items() if role in held), None)
            if holder is not None and holder not in shown:
                shown.append(holder)
        if headline_id not in shown:
            shown.append(headline_id)

        recommendations = []
        for portfolio_id in shown:
            held = [role for role in _ROLE_ORDER if role in roles.get(portfolio_id, [])]
            if portfolio_id == current.portfolio.id:
                recommendations.append(
                    self._current(current, held, best, headline_id, demand, current_cost)
                )
            else:
                recommendations.append(
                    self._candidate(by_id[portfolio_id], held, current, demand, current_cost)
                )
        return RecommendationSet(
            recommendations=recommendations,
            headline_portfolio_id=headline_id,
            pareto_portfolio_ids=[e.portfolio.id for e in pareto],
            accuracy_hints=current_cost.cost.accuracy_hints,
        )

    # --- net benefit, strength, category ------------------------------------------------------

    def _appraise(self, entry: EvaluatedPortfolio, current: EvaluatedPortfolio) -> _Appraisal:
        evaluation = entry.evaluation
        assert evaluation is not None and evaluation.delta is not None
        delta = evaluation.delta
        penalty = self._penalty(entry.portfolio, evaluation, current.evaluation)

        saving = delta.cost.negated()
        extra = self._value_of_time * delta.perceived_hours.expected
        net = Range.sum_independent(
            [
                saving,
                delta.perceived_hours.negated().scale(self._value_of_time),
                Range.point(-penalty),
            ],
            non_negative=False,
        )
        return _Appraisal(
            entry=entry,
            evaluation=evaluation,
            penalty=penalty,
            saving=saving,
            time_eur=-self._value_of_time * delta.travel_hours.expected,
            comfort_eur=-(extra - self._value_of_time * delta.travel_hours.expected),
            net=net,
            strength=self._strength(net),
            category=self._category(entry.portfolio, current.portfolio),
        )

    def _penalty(
        self,
        portfolio: Portfolio,
        evaluation: PortfolioEvaluation,
        current: PortfolioEvaluation | None,
    ) -> float:
        total = sum(self._penalties[change.kind] for change in portfolio.changes)
        assert current is not None
        mine, theirs = self._sharing_uses(evaluation), self._sharing_uses(current)
        if mine >= self._sharing_min_uses and mine > theirs:
            total += self._sharing_penalty
        return total

    def _sharing_uses(self, evaluation: PortfolioEvaluation) -> float:
        return sum(
            uses
            for option_id, uses in evaluation.uses_by_option.items()
            if self._catalog.option(option_id).service_kind is ServiceKind.CAR_SHARING
        )

    def _strength(self, net: Range) -> RecommendationStrength:
        if net.expected < self._keep_below:
            return RecommendationStrength.KEEP_CURRENT
        if net.expected < self._consider_from:
            return RecommendationStrength.SMALL_IMPROVEMENT
        if net.expected < self._strong_from or net.low < self._keep_below:
            return RecommendationStrength.CONSIDER_CHANGE
        return RecommendationStrength.STRONG_OPPORTUNITY

    def _cars(self, portfolio: Portfolio) -> int:
        return sum(
            item.quantity
            for item in portfolio.items
            if self._catalog.option(item.option_id).mode is Mode.CAR
            and self._catalog.option(item.option_id).ownership is Ownership.OWNED
        )

    def _category(self, portfolio: Portfolio, current: Portfolio) -> RecommendationCategory:
        kinds = [change.kind for change in portfolio.changes]
        sells, buys = kinds.count(ChangeKind.SELL_VEHICLE), kinds.count(ChangeKind.BUY_VEHICLE)
        cars_before, cars_after = self._cars(current), self._cars(portfolio)
        if (cars_before > 0) != (cars_after > 0):  # the last car goes, or the first one comes
            return RecommendationCategory.CHANGE_PORTFOLIO
        if sells and buys:
            return RecommendationCategory.REPLACE_VEHICLE
        if sells:
            return RecommendationCategory.REDUCE_VEHICLES
        if buys:
            return RecommendationCategory.ADD_ASSET
        if kinds:
            return RecommendationCategory.CHANGE_SUBSCRIPTION
        return RecommendationCategory.OPTIMIZE_USAGE

    # --- which portfolios are shown -----------------------------------------------------------

    @staticmethod
    def _dimensions(preferences: Preferences) -> list[tuple[Callable, bool, float]]:
        """The criteria that decide whether a portfolio is efficient: cost, time, comfort and
        flexibility always, car km and CO2 only if the household gave them a weight. Each is
        (value, whether more is better, difference too small to count)."""

        def co2(e: PortfolioEvaluation) -> float:
            return e.co2_kg_per_year.expected if e.co2_kg_per_year else 0.0

        dimensions: list[tuple[Callable, bool, float]] = [
            (lambda e: e.annual_cost.expected, False, _EPS_COST),
            (lambda e: e.annual_travel_hours.expected, False, _EPS_HOURS),
            (lambda e: e.comfort.expected, True, _EPS_SCORE),
            (lambda e: e.flexibility.expected, True, _EPS_SCORE),
        ]
        if preferences.reduce_car_dependence:
            dimensions.append((lambda e: e.car_km_per_year.expected, False, _EPS_KM))
        if preferences.sustainability:
            dimensions.append((co2, False, _EPS_CO2))
        return dimensions

    @staticmethod
    def _dominates(a: PortfolioEvaluation, b: PortfolioEvaluation, dimensions) -> bool:
        """`a` is no worse than `b` on every criterion, and better on at least one."""
        no_worse, better = True, False
        for value, higher_is_better, tolerance in dimensions:
            gain = (value(a) - value(b)) if higher_is_better else (value(b) - value(a))
            if gain < -tolerance:
                no_worse = False
            if gain > tolerance:
                better = True
        return no_worse and better

    def _pareto(
        self, entries: list[EvaluatedPortfolio], preferences: Preferences
    ) -> list[EvaluatedPortfolio]:
        dimensions = self._dimensions(preferences)
        return [
            entry
            for entry in entries
            if not any(
                self._dominates(other.evaluation, entry.evaluation, dimensions)  # type: ignore[arg-type]
                for other in entries
                if other is not entry
            )
        ]

    def _roles(
        self,
        entries: list[EvaluatedPortfolio],
        pareto: list[EvaluatedPortfolio],
        preferences: Preferences,
    ) -> dict[str, list[RecommendationRole]]:
        def ev(entry: EvaluatedPortfolio) -> PortfolioEvaluation:
            assert entry.evaluation is not None
            return entry.evaluation

        def tie(entry: EvaluatedPortfolio):
            return entry.portfolio.id

        roles: dict[str, list[RecommendationRole]] = {entries[0].portfolio.id: []}
        roles[entries[0].portfolio.id].append(RecommendationRole.CURRENT)

        def give(role: RecommendationRole, entry: EvaluatedPortfolio) -> None:
            roles.setdefault(entry.portfolio.id, []).append(role)

        give(
            RecommendationRole.CHEAPEST,
            min(
                entries,
                key=lambda e: (
                    ev(e).annual_cost.expected,
                    ev(e).annual_travel_hours.expected,
                    tie(e),
                ),
            ),
        )
        give(
            RecommendationRole.FASTEST,
            min(
                entries,
                key=lambda e: (
                    ev(e).annual_travel_hours.expected,
                    ev(e).annual_cost.expected,
                    tie(e),
                ),
            ),
        )
        give(
            RecommendationRole.MOST_COMFORTABLE,
            max(
                entries,
                key=lambda e: (ev(e).comfort.expected, -ev(e).annual_cost.expected, tie(e)),
            ),
        )
        give(RecommendationRole.BALANCED, self._balanced(entries, pareto, preferences))
        return roles

    def _balanced(
        self,
        entries: list[EvaluatedPortfolio],
        pareto: list[EvaluatedPortfolio],
        preferences: Preferences,
    ) -> EvaluatedPortfolio:
        """The efficient portfolio that improves most on today, by the household's priorities."""
        current = entries[0]
        reference = current.evaluation
        assert reference is not None
        penalties = {
            entry.portfolio.id: self._penalty(entry.portfolio, entry.evaluation, reference)  # type: ignore[arg-type]
            for entry in entries[1:]
        }
        penalties[current.portfolio.id] = 0.0

        def cost(e: PortfolioEvaluation) -> float:
            return e.annual_cost.expected + penalties[e.portfolio_id]

        def co2(e: PortfolioEvaluation) -> float:
            return e.co2_kg_per_year.expected if e.co2_kg_per_year else 0.0

        # (value of a portfolio, whether more is better, weight)
        criteria = [
            (cost, False, preferences.save_money),
            (lambda e: e.annual_travel_hours.expected, False, preferences.reduce_travel_time),
            (lambda e: e.comfort.expected, True, preferences.comfort),
            (lambda e: e.flexibility.expected, True, preferences.flexibility),
            (lambda e: e.car_km_per_year.expected, False, preferences.reduce_car_dependence),
            (co2, False, preferences.sustainability),
        ]
        if not any(weight for _, _, weight in criteria):
            criteria = [(value, better, 1) for value, better, _ in criteria[:4]]
        total_weight = sum(weight for _, _, weight in criteria)

        def improvement(entry: EvaluatedPortfolio) -> float:
            evaluation = entry.evaluation
            assert evaluation is not None
            score = 0.0
            for value, higher_is_better, weight in criteria:
                before, after = value(reference), value(evaluation)
                change = (after - before) if higher_is_better else (before - after)
                relative = change / max(abs(before), 1e-9)
                score += weight * max(-1.0, min(1.0, relative))
            return score / total_weight

        def key(entry: EvaluatedPortfolio):
            is_current = entry.portfolio.id == current.portfolio.id
            return (round(improvement(entry), 9), is_current, entry.portfolio.id)

        return max(pareto, key=key)

    # --- the recommendations ------------------------------------------------------------------

    def _current(
        self,
        current: EvaluatedPortfolio,
        roles: list[RecommendationRole],
        best: _Appraisal | None,
        headline_id: str,
        demand: MobilityDemand,
        current_cost: CurrentCostResult,
    ) -> Recommendation:
        evaluation = current.evaluation
        assert evaluation is not None
        facts = []
        if headline_id == current.portfolio.id:
            facts.append(ExplanationFact(code="verdict_current"))
        cost = evaluation.annual_cost
        facts.append(
            ExplanationFact(
                code="current_cost",
                values={
                    "eur": cost.expected,
                    "low": cost.low,
                    "high": cost.high,
                    "hours": evaluation.annual_travel_hours.expected,
                },
            )
        )
        for role, what in _ALREADY.items():
            if role in roles:
                facts.append(ExplanationFact(code="already", values={"what": what}))
        if best is not None and best.net.expected > 0:
            facts.append(
                ExplanationFact(
                    code="best_alternative" if headline_id == current.portfolio.id else "headline",
                    values={
                        "name": best.portfolio.name,
                        "text": best.portfolio.description or best.portfolio.name,
                        "net_eur": best.net.expected,
                    },
                )
            )
        facts.append(ExplanationFact(code="confidence", values={"level": evaluation.confidence}))
        return Recommendation(
            portfolio_id=current.portfolio.id,
            roles=roles,
            category=RecommendationCategory.KEEP_CURRENT,
            strength=RecommendationStrength.KEEP_CURRENT,
            facts=facts,
            explanation=wording.render(facts),
            confidence=evaluation.confidence,
        )

    def _candidate(
        self,
        appraisal: _Appraisal,
        roles: list[RecommendationRole],
        current: EvaluatedPortfolio,
        demand: MobilityDemand,
        current_cost: CurrentCostResult,
    ) -> Recommendation:
        facts = self._facts(appraisal, current, demand, current_cost)
        return Recommendation(
            portfolio_id=appraisal.portfolio.id,
            roles=roles,
            category=appraisal.category,
            strength=appraisal.strength,
            delta=appraisal.evaluation.delta,
            change_penalty=appraisal.penalty,
            net_benefit=appraisal.net,
            facts=facts,
            explanation=wording.render(facts),
            confidence=appraisal.evaluation.confidence,
        )

    def _facts(
        self,
        appraisal: _Appraisal,
        current: EvaluatedPortfolio,
        demand: MobilityDemand,
        current_cost: CurrentCostResult,
    ) -> list[ExplanationFact]:
        evaluation, portfolio = appraisal.evaluation, appraisal.portfolio
        delta, base = evaluation.delta, current.evaluation
        assert delta is not None and base is not None
        facts = [
            ExplanationFact(code="verdict", values={"strength": appraisal.strength}),
            ExplanationFact(
                code="changes", values={"text": portfolio.description or portfolio.name}
            ),
            ExplanationFact(
                code="saving",
                values={
                    "eur": appraisal.saving.expected,
                    "low": appraisal.saving.low,
                    "high": appraisal.saving.high,
                },
            ),
        ]

        kept = {(i.option_id, i.holder_id, i.profile_ref) for i in portfolio.items}
        for declared in current_cost.cost.items:
            item = declared.item
            option = self._catalog.option(item.option_id)
            dropped = (item.option_id, item.holder_id, item.profile_ref) not in kept
            if (
                dropped
                and declared.result.total.expected >= 100
                and option.ownership is not Ownership.FREE
            ):
                facts.append(
                    ExplanationFact(
                        code="dropped_item_cost",
                        values={"name": option.name, "eur": declared.result.total.expected},
                    )
                )

        sold = any(c.kind is ChangeKind.SELL_VEHICLE for c in portfolio.changes)
        need = demand.simultaneous_car_need_days
        cars_before, cars_after = self._cars(current.portfolio), self._cars(portfolio)
        if sold and need is not None and cars_before >= 2 and cars_after < cars_before:
            facts.append(
                ExplanationFact(
                    code="second_car_needed",
                    values={
                        "days": need.value,
                        "low": need.low or need.value,
                        "high": need.high or need.value,
                    },
                )
            )
        if sold:
            services = self._services_cost(evaluation)
            if services is not None:
                facts.append(services)

        from_hours, to_hours = (
            base.annual_travel_hours.expected,
            evaluation.annual_travel_hours.expected,
        )
        facts.append(
            ExplanationFact(
                code="extra_time",
                values={
                    "hours": delta.travel_hours.expected,
                    "low": delta.travel_hours.low,
                    "high": delta.travel_hours.high,
                    "from_hours": from_hours,
                    "to_hours": to_hours,
                },
            )
        )
        facts.append(
            ExplanationFact(
                code="comfort",
                values={
                    "from_score": base.comfort.expected,
                    "to_score": evaluation.comfort.expected,
                },
            )
        )

        per_hour = delta.saving_per_extra_hour
        if per_hour is not None:
            facts.append(
                ExplanationFact(code="saving_per_extra_hour", values={"eur_per_hour": per_hour})
            )
        facts.append(
            ExplanationFact(
                code="net_benefit",
                values={
                    "eur": appraisal.net.expected,
                    "low": appraisal.net.low,
                    "high": appraisal.net.high,
                    "time_eur": appraisal.time_eur,
                    "comfort_eur": appraisal.comfort_eur,
                    "penalty_eur": appraisal.penalty,
                    "value_of_time": self._value_of_time,
                },
            )
        )
        if appraisal.strength is RecommendationStrength.KEEP_CURRENT:
            if per_hour is not None and per_hour < self._value_of_time:
                facts.append(
                    ExplanationFact(
                        code="not_worth_the_time",
                        values={"eur_per_hour": per_hour, "value_of_time": self._value_of_time},
                    )
                )
            elif appraisal.net.expected > 0:
                facts.append(
                    ExplanationFact(
                        code="tiny_gain",
                        values={"eur": appraisal.net.expected, "threshold": self._keep_below},
                    )
                )
        facts.append(
            ExplanationFact(
                code="environment",
                values={
                    "car_km_from": base.car_km_per_year.expected,
                    "car_km_to": evaluation.car_km_per_year.expected,
                    "co2_from": base.co2_kg_per_year.expected if base.co2_kg_per_year else 0.0,
                    "co2_to": evaluation.co2_kg_per_year.expected
                    if evaluation.co2_kg_per_year
                    else 0.0,
                },
            )
        )
        facts.append(ExplanationFact(code="confidence", values={"level": evaluation.confidence}))
        return facts

    def _services_cost(self, evaluation: PortfolioEvaluation) -> ExplanationFact | None:
        """What the candidate would spend on pay-per-use services to replace the vehicle sold."""
        by_option: dict[str, float] = {}
        for line in evaluation.cost_lines:
            option = self._catalog.option(line.option_id or "")
            if option.ownership is Ownership.PAY_PER_USE and line.label in (
                "usage",
                "usage_change",
            ):
                by_option[option.id] = by_option.get(option.id, 0.0) + line.amount.expected
        total = sum(amount for amount in by_option.values() if amount > 0)
        if total < 50:
            return None
        names = [
            self._catalog.option(option_id).name
            for option_id, amount in sorted(by_option.items(), key=lambda kv: -kv[1])
            if amount >= 0.1 * total
        ][:3]
        lowered = [wording.lower_first(name) for name in names]
        text = ", ".join(lowered[:-1]) + " e " + lowered[-1] if len(lowered) > 1 else lowered[0]
        return ExplanationFact(code="services_cost", values={"eur": total, "names": text})
