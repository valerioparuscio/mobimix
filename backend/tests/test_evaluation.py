"""Portfolio evaluation (step 10): cost anchored to the declared one, time, comfort, car km, CO2.

Quantities (time, comfort, km, CO2) are checked on hand-built portfolios against formulas written
out in the test; the cost anchoring on the demo households.
"""

import pytest
from fastapi.testclient import TestClient

from app.data.loader import Catalog, load_demo_households
from app.main import app
from app.models import (
    AllocationReason,
    AssignedPortfolio,
    Confidence,
    Estimated,
    FeasibilityResult,
    LuggageLevel,
    MissionAllocation,
    MobilityDemand,
    MobilityMission,
    ModeAssignment,
    NumericAnswer,
    Portfolio,
    PortfolioItem,
    PortfolioOrigin,
    Purpose,
    UserProfile,
    ValueSource,
)
from app.services.costs import CurrentCostEstimator
from app.services.costs.model import FIXED_COMPONENTS
from app.services.demand import RuleBasedDemandEstimator
from app.services.pipeline import assigned_portfolios, evaluated_portfolios
from app.services.scoring import PortfolioEvaluator

# --- building blocks -----------------------------------------------------------------------


@pytest.fixture(scope="module")
def households(catalog: Catalog) -> dict[str, UserProfile]:
    return load_demo_households(catalog)


def mission(
    mission_id: str = "m",
    *,
    purpose: Purpose = Purpose.COMMUTE,
    times: float = 100,
    km: float = 8,
    person_id: str | None = "p1",
    passengers: int = 1,
    days_away: float = 0,
    luggage: LuggageLevel = LuggageLevel.NONE,
    confidence: Confidence = Confidence.HIGH,
) -> MobilityMission:
    return MobilityMission(
        id=mission_id,
        person_id=person_id,
        purpose=purpose,
        occurrences_per_year=Estimated(
            value=times, source=ValueSource.DECLARED_EXACT, confidence=confidence
        ),
        distance_km_one_way=Estimated.exact(km),
        days_away=days_away,
        passengers=passengers,
        luggage=luggage,
    )


def assigned_of(
    items: list[PortfolioItem], allocations: list[tuple[str, str, float]], *, current: bool = True
) -> AssignedPortfolio:
    """An assigned portfolio built by hand: allocations are (mission, option, share)."""
    portfolio = Portfolio(
        id="current" if current else "candidate",
        name="test",
        origin=PortfolioOrigin.CURRENT if current else PortfolioOrigin.GENERATED,
        items=items,
    )
    assignment = ModeAssignment(
        portfolio_id=portfolio.id,
        allocations=[
            MissionAllocation(mission_id=m, option_id=o, share=share, reason=AllocationReason.BEST)
            for m, o, share in allocations
        ],
    )
    feasibility = FeasibilityResult(portfolio_id=portfolio.id, is_feasible=True)
    return AssignedPortfolio(portfolio=portfolio, feasibility=feasibility, assignment=assignment)


@pytest.fixture(scope="module")
def anchor(catalog, households):
    """Any real step-6 result: the physical quantities do not depend on it."""
    profile = households["urban_couple"]
    demand = RuleBasedDemandEstimator(catalog).estimate(profile)
    return CurrentCostEstimator(catalog).estimate(profile, demand)


def evaluate_by_hand(catalog, anchor, profile, demand, assigned):
    evaluator = PortfolioEvaluator(catalog)
    baseline = evaluator.baseline(assigned, anchor, demand)
    return evaluator.evaluate(assigned, baseline, demand, profile)


def demand_of(*missions: MobilityMission) -> MobilityDemand:
    return MobilityDemand(profile_id="test", missions=list(missions))


def _evaluate(catalog, households, name):
    return evaluated_portfolios(catalog, households[name])[2]


@pytest.fixture(scope="module")
def evaluated(catalog, households):
    """name -> (declared current cost result, evaluated portfolios, current cost result)."""
    result = {}
    for name, profile in households.items():
        demand, current_cost, entries = evaluated_portfolios(catalog, profile)
        result[name] = (demand, current_cost, entries)
    return result


NAMES = ["urban_single", "urban_couple", "family_two_cars", "peripheral_family"] + [
    "car_free_household"
]


# --- time, comfort, km, CO2 ----------------------------------------------------------------


class TestQuantities:
    def test_a_commute_by_car_follows_the_formulas(self, catalog, anchor, households):
        demand = demand_of(mission(times=100, km=8))
        assigned = assigned_of(
            [PortfolioItem(option_id="car_medium_petrol", holder_id="p1")],
            [("m", "car_medium_petrol", 1.0)],
        )
        result = evaluate_by_hand(catalog, anchor, households["urban_couple"], demand, assigned)
        car = catalog.option("car_medium_petrol")

        leg_hours = 8 / 22 + 8 / 60
        assert result.annual_travel_hours.expected == pytest.approx(100 * 2 * leg_hours)
        assert result.car_km_per_year.expected == pytest.approx(100 * 2 * 8)
        litres = 1600 * car.energy.consumption_per_100km.value / 100
        assert result.co2_kg_per_year.expected == pytest.approx(
            litres * catalog.value("emissions.petrol_kg_co2_per_l")
        )
        assert result.comfort.expected == pytest.approx(car.comfort_score.value)
        assert result.flexibility.expected == pytest.approx(car.flexibility_score.value)
        assert result.reliability.expected == pytest.approx(car.reliability_score.value)
        assert result.private_vehicles_owned == 1

    def test_public_transport_counts_passenger_km_and_no_car_km(self, catalog, anchor, households):
        demand = demand_of(mission(times=100, km=8, passengers=2, person_id=None))
        assigned = assigned_of(
            [PortfolioItem(option_id="pt_ticket_urban_milano")],
            [("m", "pt_ticket_urban_milano", 1.0)],
        )
        result = evaluate_by_hand(catalog, anchor, households["urban_couple"], demand, assigned)
        passenger_km = 100 * 2 * 8 * 2
        factor = catalog.option("pt_ticket_urban_milano").emissions.co2_g_per_km.value
        assert result.co2_kg_per_year.expected == pytest.approx(passenger_km * factor / 1000)
        assert result.car_km_per_year.expected == 0
        assert result.private_vehicles_owned == 0

    def test_an_electric_car_emits_by_the_mix_of_the_grid(self, catalog, anchor, households):
        demand = demand_of(mission(times=100, km=8))
        assigned = assigned_of(
            [PortfolioItem(option_id="car_electric", holder_id="p1")],
            [("m", "car_electric", 1.0)],
        )
        result = evaluate_by_hand(catalog, anchor, households["urban_couple"], demand, assigned)
        kwh = 1600 * catalog.option("car_electric").energy.consumption_per_100km.value / 100
        grid = catalog.value("emissions.electricity_g_co2_per_kwh")
        assert result.co2_kg_per_year.expected == pytest.approx(kwh * grid / 1000)

    def test_scores_are_averaged_over_the_hours_spent_with_each_means(
        self, catalog, anchor, households
    ):
        demand = demand_of(mission(times=100, km=8))
        assigned = assigned_of(
            [
                PortfolioItem(option_id="car_medium_petrol", holder_id="p1"),
                PortfolioItem(option_id="pt_ticket_urban_milano"),
            ],
            [("m", "car_medium_petrol", 0.75), ("m", "pt_ticket_urban_milano", 0.25)],
        )
        result = evaluate_by_hand(catalog, anchor, households["urban_couple"], demand, assigned)
        car, pt = catalog.option("car_medium_petrol"), catalog.option("pt_ticket_urban_milano")
        hours_car = 0.75 * 100 * 2 * (8 / 22 + 8 / 60)
        hours_pt = 0.25 * 100 * 2 * (8 / 18 + 12 / 60)
        expected = (hours_car * car.comfort_score.value + hours_pt * pt.comfort_score.value) / (
            hours_car + hours_pt
        )
        assert result.comfort.expected == pytest.approx(expected)
        assert result.annual_travel_hours.expected == pytest.approx(hours_car + hours_pt)

    def test_uncertain_occurrences_widen_the_ranges_and_exact_ones_do_not(
        self, catalog, anchor, households
    ):
        items = [PortfolioItem(option_id="car_medium_petrol", holder_id="p1")]
        allocation = [("m", "car_medium_petrol", 1.0)]
        exact = demand_of(mission(times=100))
        vague_mission = mission(times=100).model_copy(
            update={
                "occurrences_per_year": Estimated(
                    value=100,
                    low=60,
                    high=140,
                    source=ValueSource.STATISTICAL_ESTIMATE,
                    confidence=Confidence.LOW,
                )
            }
        )
        profile = households["urban_couple"]
        sure = evaluate_by_hand(catalog, anchor, profile, exact, assigned_of(items, allocation))
        vague = evaluate_by_hand(
            catalog, anchor, profile, demand_of(vague_mission), assigned_of(items, allocation)
        )
        assert sure.annual_travel_hours.width == pytest.approx(0)
        assert vague.annual_travel_hours.low < vague.annual_travel_hours.expected
        assert vague.annual_travel_hours.expected == pytest.approx(
            sure.annual_travel_hours.expected
        )
        assert vague.car_km_per_year.high > sure.car_km_per_year.high

    def test_the_owned_vehicles_counted_are_cars_and_motorcycles_not_bicycles(
        self, catalog, anchor, households
    ):
        demand = demand_of(mission(times=100, km=8))
        items = [
            PortfolioItem(option_id="car_small_petrol", holder_id="p1"),
            PortfolioItem(option_id="scooter_125"),
            PortfolioItem(option_id="bicycle"),
            PortfolioItem(option_id="e_bike"),
        ]
        assigned = assigned_of(items, [("m", "car_small_petrol", 1.0)])
        result = evaluate_by_hand(catalog, anchor, households["urban_couple"], demand, assigned)
        assert result.private_vehicles_owned == 2

    def test_confidence_is_the_weakest_of_the_cost_and_the_material_missions(
        self, catalog, anchor, households
    ):
        profile = households["urban_couple"]
        items = [PortfolioItem(option_id="car_medium_petrol", holder_id="p1")]
        sure = demand_of(mission("big", times=200, km=10), mission("tiny", times=1, km=1))
        assigned = assigned_of(
            items, [("big", "car_medium_petrol", 1.0), ("tiny", "car_medium_petrol", 1.0)]
        )
        # the real current cost is LOW (no car value declared): force a high one
        high_cost = anchor.model_copy(
            update={"cost": anchor.cost.model_copy(update={"confidence": Confidence.HIGH})}
        )
        assert evaluate_by_hand(catalog, high_cost, profile, sure, assigned).confidence is (
            Confidence.HIGH
        )
        unsure = demand_of(
            mission("big", times=200, km=10, confidence=Confidence.LOW),
            mission("tiny", times=1, km=1),
        )
        assert evaluate_by_hand(catalog, high_cost, profile, unsure, assigned).confidence is (
            Confidence.LOW
        )
        # a tiny uncertain mission does not drag the result down
        tiny_unsure = demand_of(
            mission("big", times=200, km=10),
            mission("tiny", times=1, km=1, confidence=Confidence.LOW),
        )
        assert evaluate_by_hand(catalog, high_cost, profile, tiny_unsure, assigned).confidence is (
            Confidence.HIGH
        )


class TestDelta:
    """The difference from the current portfolio, computed mission by mission."""

    def test_the_current_portfolio_has_no_delta(self, evaluated):
        assert evaluated["urban_couple"][2][0].evaluation.delta is None

    def test_a_copy_of_the_current_portfolio_differs_by_exactly_nothing(self, catalog, households):
        profile = households["urban_couple"]
        demand, current_cost, entries = assigned_portfolios(catalog, profile)
        current = entries[0]
        twin = current.model_copy(
            update={
                "portfolio": current.portfolio.model_copy(
                    update={"id": "twin", "origin": PortfolioOrigin.GENERATED}
                )
            }
        )
        evaluator = PortfolioEvaluator(catalog)
        baseline = evaluator.baseline(current, current_cost, demand)
        delta = evaluator.evaluate(twin, baseline, demand, profile).delta
        for name in ("cost", "travel_hours", "perceived_hours", "car_km", "co2_kg"):
            quantity = getattr(delta, name)
            assert (quantity.low, quantity.expected, quantity.high) == (0, 0, 0), name
        assert delta.comfort.expected == 0 and delta.flexibility.expected == 0
        assert delta.saving_per_extra_hour is None

    @pytest.mark.parametrize("name", NAMES)
    def test_the_delta_is_the_difference_of_the_totals(self, evaluated, name):
        entries = evaluated[name][2]
        current = entries[0].evaluation
        for entry in entries[1:]:
            evaluation = entry.evaluation
            if evaluation is None:
                continue
            delta = evaluation.delta
            assert delta.cost.expected == pytest.approx(
                evaluation.annual_cost.expected - current.annual_cost.expected, abs=0.01
            ), entry.portfolio.id
            assert delta.travel_hours.expected == pytest.approx(
                evaluation.annual_travel_hours.expected - current.annual_travel_hours.expected,
                abs=0.01,
            )
            assert delta.car_km.expected == pytest.approx(
                evaluation.car_km_per_year.expected - current.car_km_per_year.expected, abs=0.1
            )
            assert delta.comfort.expected == pytest.approx(
                evaluation.comfort.expected - current.comfort.expected
            )

    def test_the_uncertainty_the_two_portfolios_share_cancels(self, evaluated):
        # hours of travel rest on uncertain missions that both portfolios have: the range of the
        # difference is far narrower than the range of the hours themselves
        entries = evaluated["urban_couple"][2]
        current = entries[0].evaluation
        added = next(e for e in entries if e.portfolio.id == "keep-car1+e_bike").evaluation
        assert added.delta.travel_hours.width < 0.2 * current.annual_travel_hours.width

    def test_selling_a_car_carries_the_uncertainty_of_its_value_keeping_it_does_not(
        self, evaluated
    ):
        entries = {e.portfolio.id: e.evaluation for e in evaluated["urban_single"][2]}
        sell = entries["car-free+pt"].delta.cost
        keep = entries["keep-car1+pt"].delta.cost
        assert sell.width > 3 * keep.width

    def test_a_saving_per_extra_hour_only_where_it_saves_and_takes_longer(self, evaluated):
        entries = {e.portfolio.id: e.evaluation for e in evaluated["urban_single"][2]}
        sell = entries["car-free+pt"].delta
        assert sell.cost.expected < 0 and sell.travel_hours.expected > 1
        assert sell.saving_per_extra_hour == pytest.approx(
            -sell.cost.expected / sell.travel_hours.expected
        )
        assert entries["keep-car1+e_bike"].delta.saving_per_extra_hour is None  # costs, saves time

    @pytest.mark.parametrize("name", NAMES)
    def test_discomfort_never_shortens_the_hours(self, evaluated, name):
        for entry in evaluated[name][2]:
            if entry.evaluation is not None:
                evaluation = entry.evaluation
                assert (
                    evaluation.perceived_hours.expected >= evaluation.annual_travel_hours.expected
                )

    @pytest.mark.parametrize("name", NAMES)
    def test_the_uses_are_of_the_options_of_the_portfolio(self, evaluated, name):
        for entry in evaluated[name][2]:
            if entry.evaluation is not None:
                options = {item.option_id for item in entry.portfolio.items}
                assert set(entry.evaluation.uses_by_option) <= options
                assert all(uses > 0 for uses in entry.evaluation.uses_by_option.values())


class TestCostFloor:
    def test_a_candidate_cannot_save_the_cost_of_use_nobody_declared(
        self, catalog, anchor, households
    ):
        # the model says the household buys tickets today; none was declared, so a portfolio that
        # no longer needs them does not get a credit for money the declared cost never held
        profile = households["urban_couple"]
        demand = demand_of(mission(times=100, km=4))
        items = [
            PortfolioItem(option_id="pt_ticket_urban_milano"),
            PortfolioItem(option_id="walking"),
        ]
        current = assigned_of(items, [("m", "pt_ticket_urban_milano", 1.0)])
        candidate = assigned_of(items, [("m", "walking", 1.0)], current=False)
        evaluator = PortfolioEvaluator(catalog)
        baseline = evaluator.baseline(current, anchor, demand)
        result = evaluator.evaluate(candidate, baseline, demand, profile)
        assert result.annual_cost.expected == 0
        assert all(line.amount.expected >= 0 for line in result.cost_lines)

    def test_more_use_of_an_undeclared_item_is_charged(self, catalog, anchor, households):
        profile = households["urban_couple"]
        demand = demand_of(mission(times=100, km=4))
        items = [
            PortfolioItem(option_id="pt_ticket_urban_milano"),
            PortfolioItem(option_id="walking"),
        ]
        current = assigned_of(items, [("m", "walking", 1.0)])
        candidate = assigned_of(items, [("m", "pt_ticket_urban_milano", 1.0)], current=False)
        evaluator = PortfolioEvaluator(catalog)
        baseline = evaluator.baseline(current, anchor, demand)
        result = evaluator.evaluate(candidate, baseline, demand, profile)
        assert result.annual_cost.expected == pytest.approx(
            100 * 2 * catalog.option("pt_ticket_urban_milano").cost_per_trip.value
        )


class TestItemAttribution:
    def test_the_use_of_a_car_is_booked_on_the_car_of_the_traveller(
        self, catalog, anchor, households
    ):
        demand = demand_of(mission(times=100, km=8, person_id="p2"))
        items = [
            PortfolioItem(option_id="car_small_petrol", holder_id="p1"),
            PortfolioItem(option_id="car_small_petrol", holder_id="p2"),
        ]
        current = assigned_of(items, [("m", "car_small_petrol", 1.0)])
        baseline = PortfolioEvaluator(catalog).baseline(current, anchor, demand)
        use = baseline.model.use_cost
        assert use[("car_small_petrol", "p2", None)].expected > 0
        assert use[("car_small_petrol", "p1", None)].expected == 0

    def test_without_a_holder_the_use_is_shared_among_the_items(self, catalog, anchor):
        demand = demand_of(mission(times=100, km=8, person_id=None))
        items = [
            PortfolioItem(option_id="car_small_petrol", holder_id="p1"),
            PortfolioItem(option_id="car_small_petrol", holder_id="p2"),
        ]
        current = assigned_of(items, [("m", "car_small_petrol", 1.0)])
        use = PortfolioEvaluator(catalog).baseline(current, anchor, demand).model.use_cost
        assert use[("car_small_petrol", "p1", None)].expected == pytest.approx(
            use[("car_small_petrol", "p2", None)].expected
        )


class TestNotes:
    def test_an_unserved_mission_is_said_not_hidden(self, catalog, anchor, households):
        demand = demand_of(mission("far", purpose=Purpose.HOLIDAY, km=450, times=1))
        assigned = assigned_of([PortfolioItem(option_id="walking")], [])
        assigned.assignment.unserved_mission_ids.append("far")
        result = evaluate_by_hand(catalog, anchor, households["urban_couple"], demand, assigned)
        assert any("le vacanze" in note for note in result.data_quality_notes)

    def test_the_notes_of_the_assignment_are_passed_on(self, catalog, anchor, households):
        demand = demand_of(mission())
        assigned = assigned_of([PortfolioItem(option_id="walking")], [("m", "walking", 1.0)])
        assigned.assignment.notes.append("una nota")
        result = evaluate_by_hand(catalog, anchor, households["urban_couple"], demand, assigned)
        assert "una nota" in result.data_quality_notes

    def test_a_model_that_misses_the_declared_car_use_says_so(self, catalog, households):
        result = _evaluate(catalog, households, "urban_single")
        notes = result[0].evaluation.data_quality_notes
        assert any(
            "6.000 dichiarati" in note and "restano nel costo attuale" in note for note in notes
        )

    def test_a_model_that_overshoots_the_declared_car_use_says_so(self, catalog, households):
        # declaring 8,000 km, far fewer than the model finds for this family
        profile = households["peripheral_family"].model_copy(deep=True)
        profile.vehicles[0].annual_km = NumericAnswer.of(8000)
        notes = _evaluate(catalog, {"f": profile}, "f")[0].evaluation.data_quality_notes
        assert any("più auto di quanta ne usiate" in note for note in notes)


# --- the cost, anchored to the declared one ------------------------------------------------


class TestCostAnchoring:
    @pytest.mark.parametrize("name", NAMES)
    def test_the_current_setup_costs_exactly_what_step_6_found(self, evaluated, name):
        _, current_cost, entries = evaluated[name]
        cost = entries[0].evaluation.annual_cost
        declared = current_cost.cost.total
        assert (cost.low, cost.expected, cost.high) == pytest.approx(
            (declared.low, declared.expected, declared.high)
        )

    @pytest.mark.parametrize("name", NAMES)
    def test_the_lines_and_the_categories_add_up_to_the_total(self, evaluated, name):
        for entry in evaluated[name][2]:
            evaluation = entry.evaluation
            if evaluation is None:
                continue
            assert sum(line.amount.expected for line in evaluation.cost_lines) == pytest.approx(
                evaluation.annual_cost.expected, abs=0.01
            ), (name, entry.portfolio.id)
            assert sum(r.expected for r in evaluation.cost_by_category.values()) == pytest.approx(
                evaluation.annual_cost.expected, abs=0.01
            )

    @pytest.mark.parametrize("name", NAMES)
    def test_no_cost_is_negative(self, evaluated, name):
        for entry in evaluated[name][2]:
            if entry.evaluation is not None:
                assert entry.evaluation.annual_cost.low >= 0, (name, entry.portfolio.id)

    def test_only_feasible_portfolios_and_the_current_one_are_evaluated(self, evaluated):
        for entry in evaluated["family_two_cars"][2]:
            rejected = not entry.feasibility.is_feasible and entry.portfolio.id != "current"
            assert (entry.evaluation is None) == rejected
        assert evaluated["family_two_cars"][2][0].evaluation is not None

    def test_selling_the_car_removes_its_declared_cost_and_adds_the_replacement(self, evaluated):
        demand, current_cost, entries = evaluated["urban_single"]
        sell = next(e for e in entries if e.portfolio.id == "car-free+pt").evaluation
        current = entries[0].evaluation
        car = next(i for i in current_cost.cost.items if i.item.option_id == "car_small_petrol")
        saving = current.annual_cost.expected - sell.annual_cost.expected
        # the whole declared cost of the car goes, less a pass and the tickets that replace it
        assert 0.6 * car.result.total.expected < saving < car.result.total.expected

    def test_a_kept_car_keeps_its_declared_fixed_costs_and_only_use_changes(self, evaluated):
        _, current_cost, entries = evaluated["urban_couple"]
        keep = next(e for e in entries if e.portfolio.id == "keep-car1+e_bike").evaluation
        car_lines = [line for line in keep.cost_lines if line.option_id == "car_medium_petrol"]
        declared = next(
            i for i in current_cost.cost.items if i.item.option_id == "car_medium_petrol"
        )
        declared_lines = {line.label: line.amount.expected for line in declared.result.lines}
        for label in FIXED_COMPONENTS:
            kept = sum(line.amount.expected for line in car_lines if line.label == label)
            assert kept == pytest.approx(declared_lines.get(label, 0.0)), label
        change = [line for line in car_lines if line.label == "usage_change"]
        assert len(change) == 1
        assert change[0].amount.expected < 0  # the e-bike takes some trips from the car

    def test_a_new_car_is_priced_as_a_purchase_with_the_area_parking(
        self, catalog, households, evaluated
    ):
        _, _, entries = evaluated["car_free_household"]
        buy = next(e for e in entries if e.portfolio.id == "buy-car_small_petrol+cars_only")
        lines = {
            line.label: line.amount.expected
            for line in buy.evaluation.cost_lines
            if line.option_id == "car_small_petrol"
        }
        car = catalog.option("car_small_petrol")
        linear = (car.purchase_price.value - car.residual_value.value) / (
            car.expected_lifetime_years.value
        )
        assert lines["depreciation"] == pytest.approx(linear)  # new: not discounted by age
        area = households["car_free_household"].household.location.area_type
        parking = catalog.defaults_for(area).values["parking_cost_year_per_car"]
        assert lines["parking"] == pytest.approx(parking.value)
        assert lines["usage"] > 0

    def test_an_identical_portfolio_costs_the_same_as_the_current_one(self, catalog, households):
        profile = households["urban_couple"]
        demand, current_cost, entries = assigned_portfolios(catalog, profile)
        current = entries[0]
        twin = current.model_copy(
            update={
                "portfolio": current.portfolio.model_copy(
                    update={"id": "twin", "origin": PortfolioOrigin.GENERATED}
                )
            }
        )
        evaluator = PortfolioEvaluator(catalog)
        baseline = evaluator.baseline(current, current_cost, demand)
        result = evaluator.evaluate(twin, baseline, demand, profile)
        assert result.annual_cost.expected == pytest.approx(current_cost.cost.total.expected)

    def test_an_e_bike_costs_its_purchase_less_what_it_saves_not_the_cars_fixed_costs(
        self, evaluated
    ):
        # The car stays: the e-bike saves the fuel and the parking at the workplace of the trips
        # it takes over, not the car's insurance, depreciation or garage (about 2,000 EUR a year,
        # which would put the difference below -1,000).
        _, _, entries = evaluated["urban_couple"]
        ebike = next(e for e in entries if e.portfolio.id == "keep-car1+e_bike").evaluation
        current = entries[0].evaluation
        assert -400 < ebike.annual_cost.expected - current.annual_cost.expected < 600


# --- time and comfort, in the large ---------------------------------------------------------


class TestTradeOffs:
    def test_selling_the_car_saves_money_and_costs_time_and_comfort(self, evaluated):
        entries = evaluated["urban_single"][2]
        current = entries[0].evaluation
        sell = next(e for e in entries if e.portfolio.id == "car-free+pt").evaluation
        assert sell.annual_cost.expected < current.annual_cost.expected
        assert sell.annual_travel_hours.expected > current.annual_travel_hours.expected
        assert sell.comfort.expected < current.comfort.expected
        assert sell.car_km_per_year.expected < current.car_km_per_year.expected
        assert sell.co2_kg_per_year.expected < current.co2_kg_per_year.expected
        assert sell.private_vehicles_owned == 0

    def test_an_e_bike_takes_km_from_the_car(self, evaluated):
        entries = evaluated["urban_couple"][2]
        current = entries[0].evaluation
        added = next(e for e in entries if e.portfolio.id == "keep-car1+e_bike").evaluation
        assert added.car_km_per_year.expected < current.car_km_per_year.expected

    def test_every_evaluation_is_complete(self, evaluated):
        for name in NAMES:
            for entry in evaluated[name][2]:
                evaluation = entry.evaluation
                if evaluation is None:
                    continue
                assert evaluation.annual_travel_hours.expected > 0
                assert 0 <= evaluation.comfort.expected <= 10
                assert 0 <= evaluation.flexibility.expected <= 10
                assert evaluation.co2_kg_per_year.expected >= 0


# --- the endpoint --------------------------------------------------------------------------


class TestEndpoint:
    client = TestClient(app)

    def test_the_current_setup_comes_first_with_the_declared_cost(self, households):
        profile = households["urban_single"].model_dump(mode="json")
        entries = self.client.post("/api/portfolios/evaluate", json=profile).json()
        declared = self.client.post("/api/profile/current-cost", json=profile).json()
        assert entries[0]["portfolio"]["id"] == "current"
        assert entries[0]["evaluation"]["annual_cost"]["expected"] == pytest.approx(
            declared["cost"]["total"]["expected"]
        )
        assert len(entries) == 7

    def test_a_rejected_candidate_has_no_evaluation(self, households):
        profile = households["family_two_cars"].model_dump(mode="json")
        entries = self.client.post("/api/portfolios/evaluate", json=profile).json()
        rejected = [e for e in entries if not e["feasibility"]["is_feasible"]]
        assert rejected and all(e["evaluation"] is None for e in rejected)

    def test_an_unknown_option_is_a_422(self, households):
        profile = households["urban_single"].model_dump(mode="json")
        profile["vehicles"][0]["option_id"] = "hoverboard"
        response = self.client.post("/api/portfolios/evaluate", json=profile)
        assert response.status_code == 422
