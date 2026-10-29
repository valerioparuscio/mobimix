"""Recommendation engine (step 11): which portfolios to show, whether to change, and why.

The rules (strength, penalties, roles, balance) are tested on evaluations written by hand, so that
each number is the one the test says; the demo households check them together.
"""

import re

import pytest
from fastapi.testclient import TestClient

from app.data.loader import Catalog, load_demo_households
from app.main import app
from app.models import (
    ChangeKind,
    Confidence,
    CurrentCostResult,
    EvaluatedPortfolio,
    ExplanationFact,
    FeasibilityResult,
    MobilityDemand,
    Portfolio,
    PortfolioChange,
    PortfolioDelta,
    PortfolioEvaluation,
    PortfolioItem,
    PortfolioOrigin,
    Preferences,
    Range,
    RecommendationCategory,
    RecommendationRole,
    RecommendationStrength,
    UserProfile,
)
from app.services.costs import CurrentCostEstimator
from app.services.demand import RuleBasedDemandEstimator
from app.services.pipeline import analyze
from app.services.recommendations import RuleBasedRecommendationEngine, wording

# --- evaluations written by hand ------------------------------------------------------------

BASE_COST, BASE_HOURS, BASE_PERCEIVED = 5000.0, 500.0, 600.0
BASE_COMFORT, BASE_FLEX, BASE_CAR_KM, BASE_CO2 = 7.0, 7.0, 8000.0, 1500.0

KEEP, SMALL = RecommendationStrength.KEEP_CURRENT, RecommendationStrength.SMALL_IMPROVEMENT
CONSIDER, STRONG = (
    RecommendationStrength.CONSIDER_CHANGE,
    RecommendationStrength.STRONG_OPPORTUNITY,
)


@pytest.fixture(scope="module")
def households(catalog: Catalog) -> dict[str, UserProfile]:
    return load_demo_households(catalog)


@pytest.fixture(scope="module")
def profile(households) -> UserProfile:
    return households["urban_single"]


@pytest.fixture(scope="module")
def current_cost(catalog, profile) -> CurrentCostResult:
    demand = RuleBasedDemandEstimator(catalog).estimate(profile)
    return CurrentCostEstimator(catalog).estimate(profile, demand)


@pytest.fixture(scope="module")
def demand(catalog, profile) -> MobilityDemand:
    return RuleBasedDemandEstimator(catalog).estimate(profile)


def _evaluation(pid: str, **values) -> PortfolioEvaluation:
    fields = {
        "portfolio_id": pid,
        "annual_cost": Range.point(BASE_COST),
        "annual_travel_hours": Range.point(BASE_HOURS),
        "perceived_hours": Range.point(BASE_PERCEIVED),
        "comfort": Range.point(BASE_COMFORT),
        "flexibility": Range.point(BASE_FLEX),
        "car_km_per_year": Range.point(BASE_CAR_KM),
        "co2_kg_per_year": Range.point(BASE_CO2),
        "private_vehicles_owned": 1,
        "confidence": Confidence.MEDIUM,
    }
    fields.update(values)
    return PortfolioEvaluation(**fields)


def current_entry(items=None) -> EvaluatedPortfolio:
    portfolio = Portfolio(
        id="current",
        name="Situazione attuale",
        origin=PortfolioOrigin.CURRENT,
        items=items or [PortfolioItem(option_id="walking")],
    )
    return EvaluatedPortfolio(
        portfolio=portfolio,
        feasibility=FeasibilityResult(portfolio_id="current", is_feasible=True),
        evaluation=_evaluation("current"),
    )


def candidate(
    pid: str,
    *,
    saving: float = 0.0,
    saving_low: float | None = None,
    saving_high: float | None = None,
    extra_hours: float = 0.0,
    extra_perceived: float | None = None,
    comfort: float = BASE_COMFORT,
    flexibility: float = BASE_FLEX,
    car_km: float = BASE_CAR_KM,
    co2: float = BASE_CO2,
    changes: tuple[ChangeKind, ...] = (),
    items=None,
    uses: dict[str, float] | None = None,
    description: str | None = None,
) -> EvaluatedPortfolio:
    perceived = extra_hours if extra_perceived is None else extra_perceived
    low = saving if saving_low is None else saving_low
    high = saving if saving_high is None else saving_high
    portfolio = Portfolio(
        id=pid,
        name=pid,
        description=description or f"Cambio {pid}",
        items=items or [PortfolioItem(option_id="walking")],
        changes=[PortfolioChange(kind=kind, option_id="e_bike") for kind in changes],
    )
    delta = PortfolioDelta(
        cost=Range(low=-high, expected=-saving, high=-low),
        travel_hours=Range.point(extra_hours),
        perceived_hours=Range.point(perceived),
        comfort=Range.point(comfort - BASE_COMFORT),
        flexibility=Range.point(flexibility - BASE_FLEX),
        car_km=Range.point(car_km - BASE_CAR_KM),
        co2_kg=Range.point(co2 - BASE_CO2),
        saving_per_extra_hour=saving / extra_hours if saving > 0 and extra_hours > 1 else None,
    )
    evaluation = _evaluation(
        pid,
        annual_cost=Range.point(BASE_COST - saving),
        annual_travel_hours=Range.point(BASE_HOURS + extra_hours),
        perceived_hours=Range.point(BASE_PERCEIVED + perceived),
        comfort=Range.point(comfort),
        flexibility=Range.point(flexibility),
        car_km_per_year=Range.point(car_km),
        co2_kg_per_year=Range.point(co2),
        uses_by_option=uses or {},
        delta=delta,
    )
    return EvaluatedPortfolio(
        portfolio=portfolio,
        feasibility=FeasibilityResult(portfolio_id=pid, is_feasible=True),
        evaluation=evaluation,
    )


def recommend(catalog, profile, demand, current_cost, *entries, current=None, preferences=None):
    if preferences is not None:
        profile = profile.model_copy(update={"preferences": preferences})
    evaluated = [current or current_entry(), *entries]
    return RuleBasedRecommendationEngine(catalog).recommend(
        evaluated, demand, current_cost, profile
    )


def by_id(result, portfolio_id):
    return next(r for r in result.recommendations if r.portfolio_id == portfolio_id)


# --- strength --------------------------------------------------------------------------------


class TestStrength:
    @pytest.mark.parametrize(
        ("saving", "strength"),
        [
            (0, KEEP),
            (149, KEEP),
            (150, SMALL),
            (499, SMALL),
            (500, CONSIDER),
            (999, CONSIDER),
            (1000, STRONG),
            (5000, STRONG),
        ],
    )
    def test_the_net_benefit_sets_the_strength(
        self, catalog, profile, demand, current_cost, saving, strength
    ):
        result = recommend(catalog, profile, demand, current_cost, candidate("x", saving=saving))
        assert by_id(result, "x").strength is strength

    def test_a_strong_opportunity_must_hold_even_in_the_pessimistic_case(
        self, catalog, profile, demand, current_cost
    ):
        sure = candidate("sure", saving=1200, saving_low=1100, saving_high=1300)
        shaky = candidate("shaky", saving=1200, saving_low=50, saving_high=2350)
        result = recommend(catalog, profile, demand, current_cost, sure, shaky)
        assert by_id(result, "sure").strength is STRONG
        assert by_id(result, "shaky").strength is CONSIDER  # it could be worth under 150

    def test_a_portfolio_that_is_worse_on_everything_is_not_shown(
        self, catalog, profile, demand, current_cost
    ):
        worse = candidate("worse", saving=-300, extra_hours=20, comfort=6.0, flexibility=6.0)
        result = recommend(catalog, profile, demand, current_cost, worse)
        assert [r.portfolio_id for r in result.recommendations] == ["current"]

    def test_a_cheaper_portfolio_that_is_not_worth_it_is_shown_for_what_it_is(
        self, catalog, profile, demand, current_cost
    ):
        # the cheapest of the lot, but the hours it costs eat the saving: shown, not recommended
        cheap = candidate("cheap", saving=200, extra_hours=100, comfort=6.0)
        result = recommend(catalog, profile, demand, current_cost, cheap)
        assert RecommendationRole.CHEAPEST in by_id(result, "cheap").roles
        assert by_id(result, "cheap").strength is KEEP

    def test_the_current_setup_is_never_a_change(self, catalog, profile, demand, current_cost):
        result = recommend(catalog, profile, demand, current_cost, candidate("x", saving=900))
        current = by_id(result, "current")
        assert current.strength is KEEP
        assert current.category is RecommendationCategory.KEEP_CURRENT
        assert current.delta is None and current.net_benefit is None


class TestNetBenefit:
    def test_time_is_valued_at_ten_euro_an_hour(self, catalog, profile, demand, current_cost):
        # 1,000 EUR saved, 100 more hours: the hours are worth exactly the saving
        result = recommend(
            catalog,
            profile,
            demand,
            current_cost,
            candidate("x", saving=1000, extra_hours=100),
        )
        assert by_id(result, "x").net_benefit.expected == pytest.approx(0)
        assert by_id(result, "x").strength is KEEP

    def test_time_saved_counts_in_favour(self, catalog, profile, demand, current_cost):
        result = recommend(
            catalog, profile, demand, current_cost, candidate("x", saving=0, extra_hours=-50)
        )
        assert by_id(result, "x").net_benefit.expected == pytest.approx(500)

    def test_discomfort_makes_an_hour_cost_more_than_ten_euro(
        self, catalog, profile, demand, current_cost
    ):
        # same 100 hours, but they feel like 150: 500 EUR more of cost
        result = recommend(
            catalog,
            profile,
            demand,
            current_cost,
            candidate("x", saving=1000, extra_hours=100, extra_perceived=150),
        )
        assert by_id(result, "x").net_benefit.expected == pytest.approx(1000 - 1500)

    def test_the_parts_of_the_explanation_add_up_to_the_net_benefit(
        self, catalog, profile, demand, current_cost
    ):
        result = recommend(
            catalog,
            profile,
            demand,
            current_cost,
            candidate(
                "x",
                saving=2000,
                extra_hours=60,
                extra_perceived=100,
                changes=(ChangeKind.SELL_VEHICLE, ChangeKind.START_SUBSCRIPTION),
            ),
        )
        fact = next(f for f in by_id(result, "x").facts if f.code == "net_benefit")
        values = fact.values
        assert 2000 + values["time_eur"] + values["comfort_eur"] - values["penalty_eur"] == (
            pytest.approx(values["eur"])
        )
        assert values["time_eur"] == pytest.approx(-600)
        assert values["comfort_eur"] == pytest.approx(-400)


class TestChangePenalty:
    @pytest.mark.parametrize(
        ("changes", "penalty"),
        [
            ((ChangeKind.SELL_VEHICLE,), 400),
            ((ChangeKind.BUY_VEHICLE,), 250),
            ((ChangeKind.CANCEL_SUBSCRIPTION,), 50),
            ((ChangeKind.START_SUBSCRIPTION,), 50),
            ((ChangeKind.SELL_VEHICLE, ChangeKind.BUY_VEHICLE, ChangeKind.START_SUBSCRIPTION), 700),
            ((ChangeKind.SELL_VEHICLE, ChangeKind.SELL_VEHICLE), 800),
            ((), 0),
        ],
    )
    def test_each_change_has_its_price(
        self, catalog, profile, demand, current_cost, changes, penalty
    ):
        result = recommend(
            catalog, profile, demand, current_cost, candidate("x", saving=900, changes=changes)
        )
        recommendation = by_id(result, "x")
        assert recommendation.change_penalty == penalty
        assert recommendation.net_benefit.expected == pytest.approx(900 - penalty)

    def test_a_small_saving_that_needs_big_changes_is_not_recommended(
        self, catalog, profile, demand, current_cost
    ):
        # CLAUDE.md section 22: 350 EUR a year for selling a car and buying an e-bike
        result = recommend(
            catalog,
            profile,
            demand,
            current_cost,
            candidate("x", saving=350, changes=(ChangeKind.SELL_VEHICLE, ChangeKind.BUY_VEHICLE)),
        )
        assert by_id(result, "x").strength is KEEP
        assert result.headline_portfolio_id == "current"

    def test_a_large_saving_with_a_light_change_is_recommended(
        self, catalog, profile, demand, current_cost
    ):
        result = recommend(
            catalog,
            profile,
            demand,
            current_cost,
            candidate("x", saving=1500, changes=(ChangeKind.CANCEL_SUBSCRIPTION,)),
        )
        assert by_id(result, "x").strength is STRONG
        assert result.headline_portfolio_id == "x"

    SHARING = "car_sharing_free2move_milano"

    def test_relying_on_car_sharing_costs_a_penalty(self, catalog, profile, demand, current_cost):
        result = recommend(
            catalog,
            profile,
            demand,
            current_cost,
            candidate("x", saving=900, uses={self.SHARING: 20}),
            candidate("rare", saving=900, uses={self.SHARING: 5}),
        )
        assert by_id(result, "x").change_penalty == 150
        assert (
            by_id(result, "rare").change_penalty == 0
        )  # a couple of rentals a year is not reliance

    def test_a_household_that_already_relies_on_it_is_not_penalised(
        self, catalog, profile, demand, current_cost
    ):
        current = current_entry()
        current.evaluation.uses_by_option[self.SHARING] = 30
        result = recommend(
            catalog,
            profile,
            demand,
            current_cost,
            candidate("x", saving=900, uses={self.SHARING: 20}),
            current=current,
        )
        assert by_id(result, "x").change_penalty == 0


# --- category -------------------------------------------------------------------------------


def _two_cars():
    return [
        PortfolioItem(option_id="car_small_petrol", profile_ref="car1"),
        PortfolioItem(option_id="car_medium_petrol", profile_ref="car2"),
    ]


class TestCategory:
    def category(self, catalog, profile, demand, current_cost, changes, items, current_items):
        result = recommend(
            catalog,
            profile,
            demand,
            current_cost,
            candidate("x", saving=900, changes=changes, items=items),
            current=current_entry(current_items),
        )
        return by_id(result, "x").category

    @pytest.mark.parametrize(
        ("changes", "items", "expected"),
        [
            (
                (ChangeKind.CANCEL_SUBSCRIPTION,),
                _two_cars(),
                RecommendationCategory.CHANGE_SUBSCRIPTION,
            ),
            (
                (ChangeKind.START_SUBSCRIPTION,),
                _two_cars(),
                RecommendationCategory.CHANGE_SUBSCRIPTION,
            ),
            ((ChangeKind.BUY_VEHICLE,), _two_cars(), RecommendationCategory.ADD_ASSET),
            (
                (ChangeKind.BUY_VEHICLE, ChangeKind.START_SUBSCRIPTION),
                _two_cars(),
                RecommendationCategory.ADD_ASSET,
            ),
            ((ChangeKind.SELL_VEHICLE,), _two_cars()[:1], RecommendationCategory.REDUCE_VEHICLES),
            (
                (ChangeKind.SELL_VEHICLE, ChangeKind.BUY_VEHICLE),
                _two_cars()[:1],
                RecommendationCategory.REPLACE_VEHICLE,
            ),
            (
                (ChangeKind.SELL_VEHICLE, ChangeKind.SELL_VEHICLE),
                [],
                RecommendationCategory.CHANGE_PORTFOLIO,
            ),
            ((), _two_cars(), RecommendationCategory.OPTIMIZE_USAGE),
        ],
    )
    def test_the_kind_of_change_names_the_category(
        self, catalog, profile, demand, current_cost, changes, items, expected
    ):
        assert (
            self.category(catalog, profile, demand, current_cost, changes, items, _two_cars())
            is expected
        )

    def test_buying_a_first_car_is_a_change_of_portfolio(
        self, catalog, profile, demand, current_cost
    ):
        category = self.category(
            catalog,
            profile,
            demand,
            current_cost,
            (ChangeKind.BUY_VEHICLE,),
            _two_cars()[:1],
            [PortfolioItem(option_id="walking")],
        )
        assert category is RecommendationCategory.CHANGE_PORTFOLIO


# --- which portfolios are shown --------------------------------------------------------------


class TestRoles:
    def entries(self):
        return (
            candidate("cheap", saving=1500, extra_hours=120, comfort=5.5, flexibility=5.0),
            candidate("fast", saving=-300, extra_hours=-60, comfort=7.2, flexibility=7.5),
            candidate("cosy", saving=-800, extra_hours=-10, comfort=9.0, flexibility=8.0),
        )

    def holders(self, result):
        return {role: r.portfolio_id for r in result.recommendations for role in r.roles}

    def test_each_extreme_goes_to_the_portfolio_that_holds_it(
        self, catalog, profile, demand, current_cost
    ):
        result = recommend(catalog, profile, demand, current_cost, *self.entries())
        holders = self.holders(result)
        assert holders[RecommendationRole.CURRENT] == "current"
        assert holders[RecommendationRole.CHEAPEST] == "cheap"
        assert holders[RecommendationRole.FASTEST] == "fast"
        assert holders[RecommendationRole.MOST_COMFORTABLE] == "cosy"

    def test_the_current_setup_comes_first_and_every_portfolio_once(
        self, catalog, profile, demand, current_cost
    ):
        result = recommend(catalog, profile, demand, current_cost, *self.entries())
        ids = [r.portfolio_id for r in result.recommendations]
        assert ids[0] == "current"
        assert len(ids) == len(set(ids))

    def test_one_portfolio_holding_several_roles_is_shown_once_with_all_of_them(
        self, catalog, profile, demand, current_cost
    ):
        everything = candidate("best", saving=1500, extra_hours=-40, comfort=8.0, flexibility=8.0)
        result = recommend(catalog, profile, demand, current_cost, everything)
        best = by_id(result, "best")
        assert {
            RecommendationRole.CHEAPEST,
            RecommendationRole.FASTEST,
            RecommendationRole.MOST_COMFORTABLE,
        } <= set(best.roles)
        assert len(result.recommendations) == 2

    def test_if_the_current_setup_is_already_the_best_it_says_so(
        self, catalog, profile, demand, current_cost
    ):
        worse = candidate("worse", saving=-500, extra_hours=30, comfort=6.0, flexibility=6.0)
        result = recommend(catalog, profile, demand, current_cost, worse)
        current = by_id(result, "current")
        assert {
            RecommendationRole.CHEAPEST,
            RecommendationRole.FASTEST,
            RecommendationRole.MOST_COMFORTABLE,
            RecommendationRole.BALANCED,
        } <= set(current.roles)
        assert result.headline_portfolio_id == "current"
        assert any("già la più economica" in line for line in current.explanation)

    def test_a_dominated_portfolio_is_not_efficient(self, catalog, profile, demand, current_cost):
        dominated = candidate(
            "dominated", saving=-200, extra_hours=20, comfort=6.0, flexibility=6.0
        )
        result = recommend(catalog, profile, demand, current_cost, dominated, *self.entries())
        assert "dominated" not in result.pareto_portfolio_ids
        assert {"cheap", "fast", "cosy"} <= set(result.pareto_portfolio_ids)

    def test_the_headline_is_the_best_net_benefit_even_if_it_holds_no_role(
        self, catalog, profile, demand, current_cost
    ):
        # "mid" is not the cheapest, fastest or most comfortable, but it is the best deal
        mid = candidate("mid", saving=1200, extra_hours=-5, comfort=7.0, flexibility=7.0)
        extreme = candidate("extreme", saving=2000, extra_hours=250, comfort=4.0, flexibility=4.0)
        quick = candidate("quick", saving=-100, extra_hours=-80, comfort=7.5, flexibility=7.5)
        cosy = candidate("cosy", saving=-500, extra_hours=-10, comfort=9.5, flexibility=8.5)
        result = recommend(catalog, profile, demand, current_cost, mid, extreme, quick, cosy)
        assert result.headline_portfolio_id == "mid"
        assert "mid" in [r.portfolio_id for r in result.recommendations]

    def test_with_nothing_to_compare_only_the_current_setup_is_returned(
        self, catalog, profile, demand, current_cost
    ):
        result = recommend(catalog, profile, demand, current_cost)
        assert [r.portfolio_id for r in result.recommendations] == ["current"]
        assert result.headline_portfolio_id == "current"

    def test_rejected_candidates_are_ignored(self, catalog, profile, demand, current_cost):
        rejected = candidate("no", saving=3000)
        rejected = rejected.model_copy(update={"evaluation": None})
        result = recommend(catalog, profile, demand, current_cost, rejected)
        assert [r.portfolio_id for r in result.recommendations] == ["current"]


class TestBalanced:
    def pair(self):
        thrifty = candidate("thrifty", saving=1200, extra_hours=40, comfort=6.0, flexibility=6.0)
        cosy = candidate("cosy", saving=-300, extra_hours=-10, comfort=8.5, flexibility=8.5)
        return thrifty, cosy

    def balanced(self, catalog, profile, demand, current_cost, preferences):
        result = recommend(
            catalog, profile, demand, current_cost, *self.pair(), preferences=preferences
        )
        return next(
            r.portfolio_id for r in result.recommendations if RecommendationRole.BALANCED in r.roles
        )

    def test_whoever_cares_about_money_gets_the_cheaper_compromise(
        self, catalog, profile, demand, current_cost
    ):
        money = Preferences(save_money=5, reduce_travel_time=1, comfort=1, flexibility=1)
        assert self.balanced(catalog, profile, demand, current_cost, money) == "thrifty"

    def test_whoever_cares_about_comfort_gets_the_comfortable_one(
        self, catalog, profile, demand, current_cost
    ):
        comfort = Preferences(save_money=1, reduce_travel_time=1, comfort=5, flexibility=5)
        assert self.balanced(catalog, profile, demand, current_cost, comfort) == "cosy"

    def test_a_household_that_only_cares_about_what_would_get_worse_keeps_what_it_has(
        self, catalog, profile, demand, current_cost
    ):
        # the thrifty option is cheaper but less comfortable and flexible; money has no weight
        only_thrifty = recommend(
            catalog,
            profile,
            demand,
            current_cost,
            self.pair()[0],
            preferences=Preferences(save_money=0, reduce_travel_time=0, comfort=5, flexibility=5),
        )
        assert RecommendationRole.BALANCED in by_id(only_thrifty, "current").roles

    def test_car_dependence_and_co2_count_only_if_asked(
        self, catalog, profile, demand, current_cost
    ):
        green = candidate("green", saving=-200, extra_hours=5, car_km=1000, co2=300)
        neutral = Preferences(save_money=3, reduce_travel_time=3, comfort=3, flexibility=3)
        caring = Preferences(
            save_money=3,
            reduce_travel_time=3,
            comfort=3,
            flexibility=3,
            reduce_car_dependence=5,
            sustainability=5,
        )
        plain = recommend(catalog, profile, demand, current_cost, green, preferences=neutral)
        asked = recommend(catalog, profile, demand, current_cost, green, preferences=caring)
        assert RecommendationRole.BALANCED in by_id(plain, "current").roles
        assert RecommendationRole.BALANCED in by_id(asked, "green").roles

    def test_a_tie_goes_to_what_the_household_already_has(
        self, catalog, profile, demand, current_cost
    ):
        # a portfolio equal to the current one on every criterion is not a reason to change
        twin = candidate("zz-twin", saving=0)
        result = recommend(catalog, profile, demand, current_cost, twin)
        assert RecommendationRole.BALANCED in by_id(result, "current").roles

    def test_the_change_penalty_counts_in_the_compromise(
        self, catalog, profile, demand, current_cost
    ):
        # the same saving, but one needs a vehicle sold and one a pass cancelled
        heavy = candidate("heavy", saving=800, extra_hours=10, changes=(ChangeKind.SELL_VEHICLE,))
        light = candidate(
            "light", saving=800, extra_hours=10, changes=(ChangeKind.CANCEL_SUBSCRIPTION,)
        )
        result = recommend(catalog, profile, demand, current_cost, heavy, light)
        holder = next(
            r.portfolio_id for r in result.recommendations if RecommendationRole.BALANCED in r.roles
        )
        assert holder == "light"

    def test_without_any_weight_the_four_main_criteria_count_equally(
        self, catalog, profile, demand, current_cost
    ):
        nothing = Preferences(
            save_money=0,
            reduce_travel_time=0,
            comfort=0,
            flexibility=0,
            reduce_car_dependence=0,
            sustainability=0,
        )
        assert self.balanced(catalog, profile, demand, current_cost, nothing) in {
            "thrifty",
            "cosy",
            "current",
        }


# --- the explanation ------------------------------------------------------------------------


class TestWording:
    def test_money_is_rounded_to_what_the_estimate_supports(self):
        assert wording.eur(3537) == "3.550 €"
        assert wording.eur(442) == "440 €"
        assert wording.eur(64) == "65 €"
        assert wording.eur(7) == "7 €"
        assert wording.eur(-1850) == "1.850 €"  # the sentence says whether it is a cost

    def test_an_hourly_amount_keeps_its_decimal_when_small(self):
        assert wording.eur_per_hour(58.4) == "58 €"
        assert wording.eur_per_hour(1.9) == "1,9 €"

    def test_a_range_shows_its_minus_sign_and_the_unit_once(self):
        assert wording.eur_range(-95, 160) == "tra -95 e 160 €"
        assert wording.eur_range(2900, 4550) == "tra 2.900 e 4.550 €"

    def test_brand_names_keep_their_capitals(self):
        assert wording.lower_first("Taxi") == "taxi"
        assert wording.lower_first("BikeMi giornaliero") == "BikeMi giornaliero"
        assert wording.lower_first("Car sharing free-floating (Free2move)") == (
            "car sharing free-floating (Free2move)"
        )

    def test_hours_agree_in_number(self):
        assert wording.hours(1) == "1 ora"
        assert wording.hours(36.4) == "36 ore"
        assert wording.hours(612) == "610 ore"

    def test_a_saving_and_an_extra_cost_read_differently(self):
        saving = ExplanationFact(code="saving", values={"eur": 3537, "low": 2900, "high": 4550})
        cost = ExplanationFact(code="saving", values={"eur": -610, "low": -1000, "high": -250})
        assert wording.render([saving]) == ["Risparmi circa 3.550 € l'anno (tra 2.900 e 4.550 €)."]
        assert wording.render([cost]) == [
            "Spenderesti circa 610 € l'anno in più (tra 250 e 1.000 €)."
        ]

    def test_a_fact_nobody_can_word_is_an_error(self):
        with pytest.raises(ValueError, match="invented"):
            wording.render([ExplanationFact(code="invented")])

    def test_the_text_comes_from_the_facts_and_from_nothing_else(
        self, catalog, profile, demand, current_cost
    ):
        result = recommend(
            catalog,
            profile,
            demand,
            current_cost,
            candidate("x", saving=1500, extra_hours=30, changes=(ChangeKind.SELL_VEHICLE,)),
        )
        for recommendation in result.recommendations:
            assert recommendation.explanation == wording.render(recommendation.facts)
            assert recommendation.facts


class TestFacts:
    def codes(self, recommendation):
        return [fact.code for fact in recommendation.facts]

    def test_a_candidate_is_explained_in_a_fixed_order(
        self, catalog, profile, demand, current_cost
    ):
        result = recommend(
            catalog,
            profile,
            demand,
            current_cost,
            candidate("x", saving=1500, extra_hours=30),
        )
        codes = self.codes(by_id(result, "x"))
        order = ["verdict", "changes", "saving", "extra_time", "comfort", "saving_per_extra_hour"]
        assert [c for c in codes if c in order] == order
        assert codes[-2:] == ["environment", "confidence"]

    def test_a_saving_that_does_not_pay_for_the_time_says_so(
        self, catalog, profile, demand, current_cost
    ):
        result = recommend(
            catalog,
            profile,
            demand,
            current_cost,
            candidate("x", saving=1100, extra_hours=600, extra_perceived=800),
        )
        recommendation = by_id(result, "x")
        assert "not_worth_the_time" in self.codes(recommendation)
        assert any("non compensa il tempo" in line for line in recommendation.explanation)

    def test_a_gain_under_the_threshold_says_so(self, catalog, profile, demand, current_cost):
        result = recommend(catalog, profile, demand, current_cost, candidate("x", saving=100))
        assert "tiny_gain" in self.codes(by_id(result, "x"))

    def test_the_second_car_fact_comes_from_the_declared_simultaneous_need(
        self, catalog, profile, demand, current_cost, households
    ):
        two_cars = households["family_two_cars"]
        family_demand = RuleBasedDemandEstimator(catalog).estimate(two_cars)
        family_cost = CurrentCostEstimator(catalog).estimate(two_cars, family_demand)
        result = recommend(
            catalog,
            two_cars,
            family_demand,
            family_cost,
            candidate("x", saving=2000, changes=(ChangeKind.SELL_VEHICLE,), items=_two_cars()[:1]),
            current=current_entry(_two_cars()),
        )
        facts = {f.code: f.values for f in by_id(result, "x").facts}
        need = family_demand.simultaneous_car_need_days
        assert facts["second_car_needed"]["days"] == need.value
        assert any("seconda auto" in line for line in by_id(result, "x").explanation)

    def test_the_cost_of_what_is_sold_is_the_declared_one(
        self, catalog, profile, demand, current_cost
    ):
        # no car among the kept items: the declared cost of the car is the "dropped" fact
        result = recommend(
            catalog,
            profile,
            demand,
            current_cost,
            candidate("x", saving=3000, changes=(ChangeKind.SELL_VEHICLE,)),
        )
        dropped = [f for f in by_id(result, "x").facts if f.code == "dropped_item_cost"]
        car = next(i for i in current_cost.cost.items if i.item.option_id == "car_small_petrol")
        assert any(f.values["eur"] == pytest.approx(car.result.total.expected) for f in dropped)

    def test_the_current_setup_points_to_the_alternative_worth_a_look(
        self, catalog, profile, demand, current_cost
    ):
        result = recommend(
            catalog,
            profile,
            demand,
            current_cost,
            candidate("x", saving=1500, description="Disdire «Abbonamento»."),
        )
        current = by_id(result, "current")
        assert "headline" in self.codes(current)
        assert any("disdire «Abbonamento»" in line for line in current.explanation)

    def test_the_hints_for_a_better_estimate_are_passed_on(
        self, catalog, profile, demand, current_cost
    ):
        result = recommend(catalog, profile, demand, current_cost)
        assert result.accuracy_hints == current_cost.cost.accuracy_hints


# --- the demo households --------------------------------------------------------------------


@pytest.fixture(scope="module")
def analyses(catalog, households):
    return {name: analyze(catalog, profile) for name, profile in households.items()}


NAMES = ["urban_single", "urban_couple", "family_two_cars", "peripheral_family"] + [
    "car_free_household"
]


class TestDemoHouseholds:
    @pytest.mark.parametrize("name", NAMES)
    def test_the_result_is_well_formed(self, analyses, name):
        result = analyses[name]
        recommendations = result.recommendations.recommendations
        ids = [r.portfolio_id for r in recommendations]
        assert ids[0] == "current" and len(ids) == len(set(ids))
        assert result.recommendations.headline_portfolio_id in ids
        known = {p.id for p in result.portfolios}
        assert set(ids) <= known
        assert {r.portfolio_id for r in result.rejected}.isdisjoint(known)
        for recommendation in recommendations:
            assert recommendation.explanation == wording.render(recommendation.facts)
            assert recommendation.confidence in set(Confidence)

    @pytest.mark.parametrize("name", NAMES)
    def test_the_explanations_do_not_pretend_to_cents(self, analyses, name):
        for recommendation in analyses[name].recommendations.recommendations:
            for line in recommendation.explanation:
                assert not re.search(r"\d,\d{2}\b", line), line

    def test_a_family_that_needs_two_cars_is_not_told_to_sell_one(self, analyses):
        result = analyses["family_two_cars"]
        assert result.recommendations.headline_portfolio_id == "current"
        assert result.rejected  # the one-car and car-free setups cannot serve the household
        for recommendation in result.recommendations.recommendations:
            assert recommendation.strength is KEEP

    def test_a_cheap_setup_that_costs_hundreds_of_hours_is_not_recommended(self, analyses):
        result = analyses["peripheral_family"]
        cheapest = next(
            r
            for r in result.recommendations.recommendations
            if RecommendationRole.CHEAPEST in r.roles
        )
        assert cheapest.portfolio_id.startswith("car-free")
        assert cheapest.delta.cost.expected < 0  # it does save money
        assert cheapest.delta.travel_hours.expected > 300
        assert cheapest.strength is KEEP
        assert result.recommendations.headline_portfolio_id == "current"

    def test_a_single_who_barely_uses_the_car_is_told_to_consider_giving_it_up(self, analyses):
        result = analyses["urban_single"]
        headline = by_id(result.recommendations, result.recommendations.headline_portfolio_id)
        assert headline.strength is STRONG
        assert headline.category is RecommendationCategory.CHANGE_PORTFOLIO
        assert headline.delta.cost.expected < -2000

    def test_a_car_free_household_is_not_pushed_into_buying_a_car(self, analyses):
        result = analyses["car_free_household"]
        assert result.recommendations.headline_portfolio_id == "current"
        buys = [
            r for r in result.recommendations.recommendations if r.portfolio_id.startswith("buy-")
        ]
        assert buys and all(r.strength is KEEP for r in buys)

    def test_the_current_cost_is_the_declared_one(self, catalog, households, analyses):
        for name, profile in households.items():
            demand = RuleBasedDemandEstimator(catalog).estimate(profile)
            declared = CurrentCostEstimator(catalog).estimate(profile, demand).cost.total
            assert analyses[name].current.annual_cost.expected == pytest.approx(declared.expected)

    def test_sliders_can_change_the_balanced_choice(self, catalog, households):
        profile = households["urban_single"]
        money = profile.model_copy(
            update={
                "preferences": Preferences(
                    save_money=5, reduce_travel_time=1, comfort=0, flexibility=0
                )
            }
        )
        cosy = profile.model_copy(
            update={
                "preferences": Preferences(
                    save_money=0, reduce_travel_time=0, comfort=5, flexibility=5
                )
            }
        )

        def balanced(p):
            result = analyze(catalog, p).recommendations
            return next(
                r.portfolio_id
                for r in result.recommendations
                if RecommendationRole.BALANCED in r.roles
            )

        assert balanced(money).startswith("car-free")
        assert balanced(cosy) == "current"

    def test_the_analysis_is_deterministic(self, catalog, households):
        profile = households["urban_couple"]
        assert analyze(catalog, profile) == analyze(catalog, profile)


class TestEndpoint:
    client = TestClient(app)

    def test_the_whole_analysis_comes_back_in_one_call(self, households):
        profile = households["family_two_cars"].model_dump(mode="json")
        response = self.client.post("/api/analyze", json=profile)
        assert response.status_code == 200
        body = response.json()
        assert body["rejected"] and all(r["issues"] for r in body["rejected"])
        assert body["rejected"][0]["name"]
        first = body["recommendations"]["recommendations"][0]
        assert first["portfolio_id"] == "current" and first["explanation"]
        assert len(body["portfolios"]) == len(body["evaluations"]) + 1

    def test_an_unknown_option_is_a_422(self, households):
        profile = households["urban_single"].model_dump(mode="json")
        profile["vehicles"][0]["option_id"] = "hoverboard"
        assert self.client.post("/api/analyze", json=profile).status_code == 422
