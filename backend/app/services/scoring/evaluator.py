"""Portfolio evaluation (step 10, CLAUDE.md section 10; docs/methodology.md, section 12): what a
portfolio costs per year, how long the household travels, how comfortable it is, how far it
drives, how much CO2 it emits - and how all that differs from the current portfolio.

Everything is computed from the mode assignment (step 9), allocation by allocation: how many
times a year a mission is done with an option, times what one occurrence uses and costs
(`TripCalculator`).

Time, comfort, flexibility, reliability, car km, CO2: modelled from the assignment.
    hours        sum of person-hours of every allocation (all travellers)
    perceived    the same hours, each weighted by its discomfort (`GeneralizedCost`)
    comfort etc. average of the option's score weighted by the hours spent with it
    car km       vehicle-km of options of mode CAR (owned, shared, rented); not taxis
    CO2          fuel or electricity burnt x emission factor; else the option's g/km x km

Uncertainty
    The occurrences and the distances of the missions carry a low/high. All the quantities above
    are linear in them, so each is kept *per mission*: a portfolio's total is the sum over
    missions of (expected value for the mission) x (that mission's relative range), the missions
    adding up independently. A **difference between two portfolios** is computed the same way, on
    the per-mission differences: what the two share - the same uncertain need - cancels, and a
    portfolio compared with itself differs by exactly nothing. (Subtracting two totals instead
    would treat the shared uncertainty as if it were two, and give "+-386 hours" for no change.)
    Prices and speeds are taken at their expected value in the differences; the cost model's own
    ranges (fuel price, car value) remain in the absolute costs.

Cost: anchored to what the household declared (the "pivot")
    The model does not reproduce the household's real use of its vehicles (declared mileage
    against modelled mileage differs by up to 50%), so its absolute cost would not be the cost the
    household recognises. The current cost is therefore the one of step 6, built from what was
    declared, and every other portfolio is the current one *plus the differences the model finds*,
    item by item:

        an item the household has and keeps    its cost today (step 6)
                                               + (modelled use cost in this portfolio
                                                  - modelled use cost today)
        an item the household drops            disappears with its whole cost today
        an item the household adds             its full modelled cost: fixed costs of a new
                                               purchase or pass + modelled use cost

    Fixed costs of a kept item cancel exactly (they are the same), so the uncertainty about the
    value of a car already owned does not blur the saving of a candidate that keeps it. The
    current portfolio itself is its step-6 cost, unchanged. Use costs are the marginal ones:
    the fixed components are paid anyway (`TcoCostModel.usage_cost`).

Confidence: the weakest of the confidence of the current cost and of the missions that make up
at least `costing.material_share` of the kilometres.
"""

from collections import defaultdict
from dataclasses import dataclass

from app.data.loader import Catalog
from app.models import (
    AssignedPortfolio,
    Confidence,
    CostCategory,
    CostLine,
    CurrentCostResult,
    EnergyCarrier,
    MobilityDemand,
    MobilityMission,
    MobilityOption,
    Mode,
    OptionUsage,
    Ownership,
    PortfolioDelta,
    PortfolioEvaluation,
    PortfolioItem,
    PortfolioOrigin,
    Range,
    UserProfile,
)
from app.services.costs.model import FIXED_COMPONENTS, USAGE_COMPONENTS, TcoCostModel
from app.services.costs.portfolio_cost import CATEGORY_BY_OWNERSHIP
from app.services.optimizer.trips import GeneralizedCost, Trip, TripCalculator
from app.services.statistics.estimation import weakest_confidence
from app.services.wording import PURPOSE_NAMES

ItemKey = tuple[str, str | None, str | None]  # option, holder, id in the profile
_MOTORISED_OWNED = {Mode.CAR, Mode.MOTORCYCLE}

# Quantities kept per mission (expected value per year at the expected demand).
HOURS = "hours"
PERCEIVED = "perceived_hours"
COMFORT_HOURS = "comfort_hours"  # hours x comfort score: divided by the hours, the average
FLEXIBILITY_HOURS = "flexibility_hours"
RELIABILITY_HOURS = "reliability_hours"
CAR_KM = "car_km"
OWNED_CAR_KM = "owned_car_km"
CO2_KG = "co2_kg"


def _thousands(value: float) -> str:
    """12345 -> "12.345" (Italian thousands separator)."""
    return f"{value:,.0f}".replace(",", ".")


def item_key(item: PortfolioItem) -> ItemKey:
    return (item.option_id, item.holder_id, item.profile_ref)


@dataclass(frozen=True)
class _Allocation:
    mission: MobilityMission
    option: MobilityOption
    trip: Trip  # one occurrence, at the expected distance
    occurrences: Range  # per year, with the share of the assignment applied
    scale: Range  # occurrences x distance relative to the expected one


@dataclass(frozen=True)
class _Model:
    """What the assignment of one portfolio amounts to: per mission, by item, in total."""

    use_cost: dict[ItemKey, Range]  # absolute, with the cost model's own ranges
    use_by_mission: dict[ItemKey, dict[str, float]]  # expected EUR/year, for the differences
    factors: dict[str, Range]  # mission -> its relative range (expected value 1)
    by_mission: dict[str, dict[str, float]]  # mission -> quantity -> expected per year
    uses_by_option: dict[str, float]

    def total(self, name: str) -> Range:
        parts = [
            self.factors[mission].scale(quantities.get(name, 0.0))
            for mission, quantities in self.by_mission.items()
        ]
        return Range.sum_independent(parts) if parts else Range.point(0.0)

    def difference(self, other: "_Model", name: str) -> Range:
        """This portfolio minus the other, mission by mission."""
        parts = [
            factor.scale_signed(
                self.by_mission.get(mission, {}).get(name, 0.0)
                - other.by_mission.get(mission, {}).get(name, 0.0)
            )
            for mission, factor in self.factors.items()
        ]
        return Range.sum_independent(parts, non_negative=False) if parts else Range.point(0.0)

    def expected(self, name: str) -> float:
        return sum(quantities.get(name, 0.0) for quantities in self.by_mission.values())

    def mean(self, name: str) -> float:
        """Average of a score over the hours of travel."""
        hours = self.expected(HOURS)
        return self.expected(name) / hours if hours > 0 else 0.0


@dataclass(frozen=True)
class Baseline:
    """The current portfolio as the evaluation of every other one needs it: what the household
    declared (step 6) and what the model finds for the same portfolio."""

    cost: CurrentCostResult
    model: _Model


class PortfolioEvaluator:
    def __init__(self, catalog: Catalog, cost_model: TcoCostModel | None = None) -> None:
        self._catalog = catalog
        self._cost_model = cost_model or TcoCostModel(catalog)
        self._calculator = TripCalculator(catalog, self._cost_model)
        self._valuation = GeneralizedCost(catalog)

    # --- public ------------------------------------------------------------------------------

    def baseline(
        self,
        current: AssignedPortfolio,
        current_cost: CurrentCostResult,
        demand: MobilityDemand,
    ) -> Baseline:
        """`current` is the current portfolio with the common service layer, assigned."""
        return Baseline(cost=current_cost, model=self._model(current, demand))

    def evaluate(
        self,
        assigned: AssignedPortfolio,
        baseline: Baseline,
        demand: MobilityDemand,
        profile: UserProfile,
    ) -> PortfolioEvaluation:
        if assigned.assignment is None:
            raise ValueError(f"{assigned.portfolio.id}: a rejected portfolio has no assignment")
        is_current = assigned.portfolio.origin is PortfolioOrigin.CURRENT
        model = baseline.model if is_current else self._model(assigned, demand)
        cost = _Cost(self._catalog, self._cost_model, profile, baseline, assigned, model)
        return PortfolioEvaluation(
            portfolio_id=assigned.portfolio.id,
            annual_cost=cost.total,
            cost_by_category=cost.by_category,
            cost_lines=cost.lines,
            annual_travel_hours=model.total(HOURS),
            perceived_hours=model.total(PERCEIVED),
            comfort=Range.point(model.mean(COMFORT_HOURS)),
            flexibility=Range.point(model.mean(FLEXIBILITY_HOURS)),
            reliability=Range.point(model.mean(RELIABILITY_HOURS)),
            car_km_per_year=model.total(CAR_KM),
            co2_kg_per_year=model.total(CO2_KG),
            private_vehicles_owned=sum(
                item.quantity
                for item in assigned.portfolio.items
                if self._option(item).ownership is Ownership.OWNED
                and self._option(item).mode in _MOTORISED_OWNED
            ),
            uses_by_option=dict(model.uses_by_option),
            delta=None if is_current else self._delta(model, baseline.model, cost),
            confidence=self._confidence(demand, baseline),
            data_quality_notes=cost.notes + self._notes(assigned, baseline, demand),
        )

    @staticmethod
    def _delta(model: _Model, base: _Model, cost: "_Cost") -> PortfolioDelta:
        hours = model.difference(base, HOURS)
        saving = -cost.delta.expected
        return PortfolioDelta(
            cost=cost.delta,
            travel_hours=hours,
            perceived_hours=model.difference(base, PERCEIVED),
            comfort=Range.point(model.mean(COMFORT_HOURS) - base.mean(COMFORT_HOURS)),
            flexibility=Range.point(model.mean(FLEXIBILITY_HOURS) - base.mean(FLEXIBILITY_HOURS)),
            car_km=model.difference(base, CAR_KM),
            co2_kg=model.difference(base, CO2_KG),
            saving_per_extra_hour=(
                saving / hours.expected if saving > 0 and hours.expected > 1.0 else None
            ),
        )

    # --- what the assignment amounts to ---------------------------------------------------------

    def _option(self, item: PortfolioItem) -> MobilityOption:
        return self._catalog.option(item.option_id)

    def _model(self, assigned: AssignedPortfolio, demand: MobilityDemand) -> _Model:
        assignment = assigned.assignment
        assert assignment is not None
        missions = {mission.id: mission for mission in demand.missions}
        allocations = [self._allocation(missions, a) for a in assignment.allocations]

        use_costs: dict[ItemKey, list[Range]] = {item_key(i): [] for i in assigned.portfolio.items}
        use_by_mission: dict[ItemKey, dict[str, float]] = {k: defaultdict(float) for k in use_costs}
        by_mission: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
        uses: dict[str, float] = defaultdict(float)
        for allocation in allocations:
            option, mission_id = allocation.option, allocation.mission.id
            cost = self._cost_model.calculate(
                option, self._usage(allocation), only=USAGE_COMPONENTS
            ).total
            items = self._items_for(assigned, allocation)
            for item in items:
                use_costs[item_key(item)].append(cost.scale(1 / len(items)))
                use_by_mission[item_key(item)][mission_id] += cost.expected / len(items)

            quantities = by_mission[mission_id]
            trip = allocation.trip
            hours = allocation.scale.expected * trip.person_hours
            quantities[HOURS] += hours
            quantities[PERCEIVED] += hours * self._valuation.time_weight(trip.comfort)
            for name, score in (
                (COMFORT_HOURS, option.comfort_score),
                (FLEXIBILITY_HOURS, option.flexibility_score),
                (RELIABILITY_HOURS, option.reliability_score),
            ):
                assert score is not None
                quantities[name] += hours * score.value
            km = allocation.scale.expected * trip.usage.annual_km.expected
            if option.mode is Mode.CAR:
                quantities[CAR_KM] += km
                if option.ownership is Ownership.OWNED:
                    quantities[OWNED_CAR_KM] += km
            quantities[CO2_KG] += self._co2_kg(option, km)
            uses[option.id] += allocation.occurrences.expected

        return _Model(
            use_cost={key: Range.sum_independent(costs) for key, costs in use_costs.items()},
            use_by_mission={key: dict(values) for key, values in use_by_mission.items()},
            factors=self._factors(demand),
            by_mission={mission: dict(values) for mission, values in by_mission.items()},
            uses_by_option=dict(uses),
        )

    @staticmethod
    def _factors(demand: MobilityDemand) -> dict[str, Range]:
        """How far a mission's occurrences and distance may be from their expected value, as a
        range around 1: what every per-mission quantity is multiplied by."""
        factors = {}
        for mission in demand.missions:
            occurrences, distance = mission.occurrences_per_year, mission.distance_km_one_way
            if occurrences.value <= 0:
                continue
            times = Range(
                low=occurrences.low / occurrences.value,  # type: ignore[operator]
                expected=1.0,
                high=occurrences.high / occurrences.value,  # type: ignore[operator]
            )
            length = (
                Range(
                    low=distance.low / distance.value,  # type: ignore[operator]
                    expected=1.0,
                    high=distance.high / distance.value,  # type: ignore[operator]
                )
                if distance.value > 0
                else Range.point(1.0)
            )
            factors[mission.id] = times.times_independent(length)
        return factors

    def _allocation(self, missions: dict[str, MobilityMission], allocation) -> _Allocation:
        mission = missions[allocation.mission_id]
        option = self._catalog.option(allocation.option_id)
        occurrences = mission.occurrences_per_year
        share = allocation.share
        per_year = Range(
            low=occurrences.low * share,  # type: ignore[operator]
            expected=occurrences.value * share,
            high=occurrences.high * share,  # type: ignore[operator]
        )
        distance = mission.distance_km_one_way
        relative = (
            Range(
                low=distance.low / distance.value,  # type: ignore[operator]
                expected=1.0,
                high=distance.high / distance.value,  # type: ignore[operator]
            )
            if distance.value > 0
            else Range.point(1.0)
        )
        return _Allocation(
            mission=mission,
            option=option,
            trip=self._calculator.trip(mission, option),
            occurrences=per_year,
            scale=per_year.times_independent(relative),
        )

    @staticmethod
    def _usage(allocation: _Allocation) -> OptionUsage:
        """A year of one allocation: the usage of one occurrence times the number of times."""
        one = allocation.trip.usage
        times, scale = allocation.occurrences, allocation.scale
        return OptionUsage(
            annual_km=scale.scale(one.annual_km.expected),
            annual_trips=times.scale(one.annual_trips.expected),
            annual_minutes=times.scale(one.annual_minutes.expected),
            annual_days=times.scale(one.annual_days.expected),
            annual_toll_km=scale.scale(one.annual_toll_km.expected),
            annual_destination_days=times.scale(one.annual_destination_days.expected),
        )

    @staticmethod
    def _items_for(assigned: AssignedPortfolio, allocation: _Allocation) -> list[PortfolioItem]:
        """The items the use of an option is booked on: the only one, or the ones of the traveller
        when several items share an option (two identical cars), or all of them."""
        same = [i for i in assigned.portfolio.items if i.option_id == allocation.option.id]
        person = allocation.mission.person_id
        mine = [i for i in same if person is not None and i.holder_id == person]
        return mine or same

    def _co2_kg(self, option: MobilityOption, km: float) -> float:
        """Emissions at the expected value of the factors (their ranges are not propagated)."""
        parameter = self._catalog.value
        if option.energy is not None:
            units = option.energy.consumption_per_100km.value / 100 * km  # litres, or kWh
            carrier = option.energy.carrier
            if carrier is EnergyCarrier.PETROL:
                return units * parameter("emissions.petrol_kg_co2_per_l")
            if carrier is EnergyCarrier.DIESEL:
                return units * parameter("emissions.diesel_kg_co2_per_l")
            return units * parameter("emissions.electricity_g_co2_per_kwh") / 1000
        if option.emissions is not None:
            return km * option.emissions.co2_g_per_km.value / 1000
        return 0.0

    # --- confidence and notes ----------------------------------------------------------------

    def _confidence(self, demand: MobilityDemand, baseline: Baseline) -> Confidence:
        share = self._catalog.value("costing.material_share")
        total_km = demand.total_annual_km
        material = [
            mission
            for mission in demand.missions
            if total_km > 0 and mission.annual_km >= share * total_km
        ]
        confidences = [baseline.cost.cost.confidence]
        for mission in material:
            confidences += [
                mission.occurrences_per_year.confidence,
                mission.distance_km_one_way.confidence,
            ]
        return weakest_confidence(confidences)

    def _notes(
        self, assigned: AssignedPortfolio, baseline: Baseline, demand: MobilityDemand
    ) -> list[str]:
        assignment = assigned.assignment
        assert assignment is not None
        notes = list(assignment.notes)
        missions = {mission.id: mission for mission in demand.missions}
        for mission_id in assignment.unserved_mission_ids:
            label = PURPOSE_NAMES[missions[mission_id].purpose]
            notes.append(
                f"Per {label} questa configurazione non ha un mezzo ragionevole (capita "
                "raramente): non è inclusa nei costi e nei tempi."
            )
        check = baseline.cost.car_km_check
        if assigned.portfolio.origin is PortfolioOrigin.CURRENT and check and check.all_declared:
            modelled = baseline.model.expected(OWNED_CAR_KM)
            declared = check.cars_km.expected
            if declared > 0 and modelled / declared < 0.67:
                notes.append(
                    f"Il modello attribuisce alle vostre auto circa {_thousands(modelled)} km "
                    f"l'anno, contro {_thousands(declared)} dichiarati: i km in più non sono "
                    "legati a nessuno spostamento che conosciamo e restano nel costo attuale."
                )
            elif declared > 0 and modelled / declared > 1.5:
                notes.append(
                    f"Il modello attribuisce alle vostre auto circa {_thousands(modelled)} km "
                    f"l'anno, contro {_thousands(declared)} dichiarati: gli spostamenti stimati "
                    "richiedono più auto di quanta ne usiate, e i confronti potrebbero "
                    "sovrastimare quanto pesa l'auto."
                )
        return notes


class _Cost:
    """The cost of one portfolio, anchored to the declared cost of the current one, and its
    difference from it."""

    def __init__(
        self,
        catalog: Catalog,
        cost_model: TcoCostModel,
        profile: UserProfile,
        baseline: Baseline,
        assigned: AssignedPortfolio,
        model: _Model,
    ) -> None:
        self.catalog = catalog
        self.cost_model = cost_model
        self.defaults = catalog.defaults_for(profile.household.location.area_type).values
        self.declared = {item_key(c.item): c for c in baseline.cost.cost.items}
        self.model = model
        self.base = baseline.model
        self.is_current = assigned.portfolio.origin is PortfolioOrigin.CURRENT
        self.notes: list[str] = []
        self.lines: list[CostLine] = []
        self.changes: list[Range] = []  # signed: what this portfolio adds to the current cost

        totals_by_category: dict[CostCategory, list[Range]] = {c: [] for c in CostCategory}
        all_totals = []
        kept_keys = set()
        for item in assigned.portfolio.items:
            option = catalog.option(item.option_id)
            kept_keys.add(item_key(item))
            total = self._item(item, option)
            all_totals.append(total)
            totals_by_category[CATEGORY_BY_OWNERSHIP[option.ownership]].append(total)
        for key in self.base.use_cost.keys() - kept_keys:  # an item the household drops
            declared = self.declared.get(key)
            if declared is not None:
                self.changes.append(declared.result.total.negated())

        self.total = Range.sum_independent(all_totals)
        self.by_category = {
            category: Range.sum_independent(totals) if totals else Range.point(0.0)
            for category, totals in totals_by_category.items()
        }
        self.delta = Range.sum_independent(self.changes, non_negative=False)

    def _item(self, item: PortfolioItem, option: MobilityOption) -> Range:
        key = item_key(item)
        if key not in self.base.use_cost:  # an item the household adds
            return self._new_item(item, option, self.model.use_cost[key])

        declared = self.declared.get(key)  # services added by the common layer have none
        base = declared.result.total if declared else Range.point(0.0)
        if declared:
            self.lines += declared.result.lines
        if self.is_current:
            return base

        change = self._use_change(key)
        # what the household can stop spending on an item is what it declared of its use: a
        # candidate cannot save the use cost of tickets nobody told us about, nor take a car's
        # cost below its fixed part
        declared_use = sum(
            line.amount.expected
            for line in (declared.result.lines if declared else [])
            if line.label in USAGE_COMPONENTS
        )
        if change.expected < -declared_use:
            shortfall = -declared_use - change.expected
            change = Range(
                low=change.low + shortfall,
                expected=change.expected + shortfall,
                high=change.high + shortfall,
            )
            if declared and shortfall > 1.0:
                self.notes.append(
                    f"Il modello toglie a «{option.name}» più uso di quanto dichiarato: il costo "
                    "non scende sotto la sua parte fissa."
                )
        if abs(change.expected) > 1e-9 or change.width > 1e-9:
            self.lines.append(CostLine(label="usage_change", option_id=option.id, amount=change))
        self.changes.append(change)
        return Range.sum_independent([base, change])

    def _use_change(self, key: ItemKey) -> Range:
        """What a kept item's use costs more (or less) than today, mission by mission."""
        mine = self.model.use_by_mission.get(key, {})
        theirs = self.base.use_by_mission.get(key, {})
        parts = [
            self.model.factors[mission].scale_signed(
                mine.get(mission, 0.0) - theirs.get(mission, 0.0)
            )
            for mission in mine.keys() | theirs.keys()
        ]
        return Range.sum_independent(parts, non_negative=False) if parts else Range.point(0.0)

    def _new_item(self, item: PortfolioItem, option: MobilityOption, use: Range) -> Range:
        usage = OptionUsage(quantity=item.quantity, parking_cost_year=self._parking(option))
        fixed = self.cost_model.calculate(option, usage, only=FIXED_COMPONENTS)
        self.lines += fixed.lines
        if use.expected > 0:
            self.lines.append(CostLine(label="usage", option_id=option.id, amount=use))
        total = Range.sum_independent([fixed.total, use])
        self.changes.append(total)
        return total

    def _parking(self, option: MobilityOption) -> Range | None:
        """A car the household buys is parked like the ones people have in its area."""
        if option.mode is Mode.CAR and option.ownership is Ownership.OWNED:
            return self.defaults["parking_cost_year_per_car"].as_range()
        return None
