"""Current portfolio and its cost (step 6), on the five demo households."""

import pytest
from fastapi.testclient import TestClient

from app.data.loader import Catalog, load_demo_households
from app.main import app
from app.models import (
    Confidence,
    CostCategory,
    CurrentCostResult,
    HeldSubscription,
    NumericAnswer,
    PortfolioOrigin,
    UserProfile,
)
from app.services.costs import CurrentCostEstimator
from app.services.demand import RuleBasedDemandEstimator


@pytest.fixture(scope="module")
def demand_estimator(catalog: Catalog) -> RuleBasedDemandEstimator:
    return RuleBasedDemandEstimator(catalog)


@pytest.fixture(scope="module")
def estimator(catalog: Catalog) -> CurrentCostEstimator:
    return CurrentCostEstimator(catalog)


@pytest.fixture(scope="module")
def households(catalog: Catalog) -> dict[str, UserProfile]:
    return load_demo_households(catalog)


@pytest.fixture
def run(estimator, demand_estimator, households):
    """run(name, edit) -> CurrentCostResult for a private copy of a demo household."""

    def _run(name: str, edit=None) -> CurrentCostResult:
        profile = households[name].model_copy(deep=True)
        if edit:
            edit(profile)
        return estimator.estimate(profile, demand_estimator.estimate(profile))

    return _run


def option_ids(result: CurrentCostResult) -> list[str]:
    return [item.option_id for item in result.portfolio.items]


class TestCurrentPortfolio:
    def test_it_is_the_baseline_portfolio(self, run):
        result = run("urban_single")
        assert result.portfolio.origin is PortfolioOrigin.CURRENT
        assert result.portfolio.id == "current"

    def test_holds_what_the_household_owns_and_holds(self, run):
        result = run("urban_couple")
        assert "car_medium_petrol" in option_ids(result)
        assert "pt_annual_urban_milano" in option_ids(result)
        assert "walking" in option_ids(result)
        car = next(i for i in result.portfolio.items if i.option_id == "car_medium_petrol")
        assert car.profile_ref == "car1"
        assert car.holder_id == "p1"

    def test_declared_services_become_portfolio_items(self, run):
        ids = option_ids(run("car_free_household"))
        assert {"taxi_milano", "car_sharing_free2move_milano", "air_domestic"} <= set(ids)

    def test_a_service_declared_as_never_used_is_left_out(self, run):
        def never_taxi(profile):
            profile.other_mobility.taxi_trips_per_year = NumericAnswer.of(0)

        assert "taxi_milano" not in option_ids(run("car_free_household", never_taxi))

    def test_micro_sharing_is_covered_by_a_bike_sharing_pass(self, run):
        assert "kick_scooter_sharing" in option_ids(run("urban_single"))

        def with_bikemi(profile):
            profile.subscriptions.append(
                HeldSubscription(id="sub9", option_id="bikemi_annual", holder_id="p1")
            )

        ids = option_ids(run("urban_single", with_bikemi))
        assert "bikemi_annual" in ids
        assert "kick_scooter_sharing" not in ids

    def test_every_item_has_a_priced_result(self, run):
        result = run("family_two_cars")
        assert len(result.cost.items) == len(result.portfolio.items)
        assert all(item.result.total.expected >= 0 for item in result.cost.items)


class TestCosts:
    # Regression values on the current data (placeholders included): update deliberately when the
    # catalogue or the defaults change. Hand-checked components are in the tests below.
    EXPECTED = {
        "urban_single": 4_764,
        "urban_couple": 5_506,
        "family_two_cars": 8_332,
        "peripheral_family": 5_593,
        "car_free_household": 1_791,
    }

    @pytest.mark.parametrize("name", list(EXPECTED))
    def test_annual_cost(self, run, name):
        assert run(name).cost.total.expected == pytest.approx(self.EXPECTED[name], rel=0.02)

    def test_categories_add_up_to_the_total(self, run):
        for name in self.EXPECTED:
            cost = run(name).cost
            assert sum(r.expected for r in cost.by_category.values()) == pytest.approx(
                cost.total.expected
            ), name

    def test_ownership_subscriptions_and_usage_are_told_apart(self, run, catalog):
        cost = run("car_free_household").cost
        fee = catalog.option("pt_annual_urban_milano").fixed_cost_year.value
        assert cost.by_category[CostCategory.SUBSCRIPTIONS].expected == pytest.approx(2 * fee)
        assert cost.by_category[CostCategory.OWNERSHIP].expected < 300  # only two bicycles
        assert cost.by_category[CostCategory.USAGE].expected > 600  # taxi, sharing, rail, flights

    def test_car_free_services_match_a_hand_calculation(self, run):
        cost = run("car_free_household").cost
        by_option = {item.item.option_id: item.result.total.expected for item in cost.items}
        # 15 taxi rides: 4.10 base + 6 km x 1.50 each
        assert by_option["taxi_milano"] == pytest.approx(15 * (4.10 + 6 * 1.50))
        # 12 car-sharing rentals of 60 minutes: the 9.99 hourly package beats 60 x 0.23
        assert by_option["car_sharing_free2move_milano"] == pytest.approx(12 * 9.99)
        # 10 rail trips of 120 km at 0.15 EUR/km
        assert by_option["rail_regional_ticket"] == pytest.approx(10 * 120 * 0.15)
        # 2 flights at 90 EUR
        assert by_option["air_domestic"] == pytest.approx(180)

    def test_a_declared_subscription_price_overrides_the_catalogue(self, run):
        def paid_less(profile):
            profile.subscriptions[0].annual_cost = NumericAnswer.of(200)

        cost = run("urban_couple", paid_less).cost
        assert cost.by_category[CostCategory.SUBSCRIPTIONS].expected == 200

    def test_unknown_car_km_uses_the_area_default_for_the_first_and_second_car(self, run):
        def forget_km(profile):
            for vehicle in profile.vehicles:
                vehicle.annual_km = NumericAnswer()

        result = run("family_two_cars", forget_km)
        # SUBURBAN defaults: 12,000 km for the first car, 7,500 for the second
        cars = [i for i in result.cost.items if i.item.profile_ref in ("car1", "car2")]
        assert result.car_km_check.cars_km.expected == pytest.approx(12_000 + 7_500)
        assert len(cars) == 2
        assert {n.subject for n in result.cost.notes if n.field == "annual_km"} == {"car1", "car2"}


class TestUncertaintyAndConfidence:
    def test_ranges_bracket_the_expected_cost_and_are_usable(self, run):
        for name in TestCosts.EXPECTED:
            total = run(name).cost.total
            assert total.low <= total.expected <= total.high, name
            assert total.high < 1.6 * total.expected, name  # not the useless worst case
            assert total.low > 0.6 * total.expected, name

    def test_unknown_value_of_an_owned_car_makes_confidence_low(self, run):
        assert run("urban_single").cost.confidence is Confidence.LOW

    def test_exact_answers_about_the_car_make_confidence_high(self, run):
        def know_everything(profile):
            car = profile.vehicles[0]
            car.annual_km = NumericAnswer.of(6_000)
            car.parking_cost_year = NumericAnswer.of(1_800)
            car.current_value = NumericAnswer.of(5_000)

        result = run("urban_single", know_everything)
        assert result.cost.confidence is Confidence.HIGH

    def test_a_precise_answer_narrows_the_range(self, run):
        vague = run("urban_single").cost.total

        def know_value(profile):
            profile.vehicles[0].current_value = NumericAnswer.of(5_000)

        precise = run("urban_single", know_value).cost.total
        assert precise.width < vague.width

    def test_small_uncertain_items_do_not_drag_confidence_down(self, run):
        def know_everything(profile):
            car = profile.vehicles[0]
            car.annual_km = NumericAnswer.of(6_000)
            car.parking_cost_year = NumericAnswer.of(1_800)
            car.current_value = NumericAnswer.of(5_000)

        cost = run("urban_single", know_everything).cost
        low_items = [i for i in cost.items if i.confidence is Confidence.LOW]
        assert low_items, "the defaulted services are low confidence..."
        assert cost.confidence is Confidence.HIGH  # ...but they are a small part of the cost


class TestAccuracyHints:
    def test_the_value_of_the_car_is_the_first_thing_to_ask(self, run):
        hints = run("family_two_cars").cost.accuracy_hints
        assert hints[0].field.endswith("current_value")
        assert hints[0].reduction_eur > 500
        assert "vale oggi" in hints[0].message

    def test_hints_are_few_and_sorted(self, run):
        hints = run("urban_single").cost.accuracy_hints
        assert 1 <= len(hints) <= 3
        assert [h.reduction_eur for h in hints] == sorted(
            (h.reduction_eur for h in hints), reverse=True
        )

    def test_a_known_value_stops_being_suggested(self, run):
        def know_value(profile):
            for vehicle in profile.vehicles:
                vehicle.current_value = NumericAnswer.of(5_000)

        fields = [h.field for h in run("family_two_cars", know_value).cost.accuracy_hints]
        assert not any(f.endswith("current_value") for f in fields)


class TestCarKmCheck:
    def test_declared_km_in_line_with_the_needs_raise_no_note(self, run):
        result = run("family_two_cars")  # 21,000 km declared vs 21,740 estimated
        assert result.car_km_check.all_declared
        assert result.car_km_check.ratio == pytest.approx(0.97, abs=0.02)
        assert not [n for n in result.cost.notes if n.field == "car_km_vs_needs"]

    def test_far_more_km_than_needs_is_reported(self, run):
        def drives_a_lot(profile):
            profile.vehicles[0].annual_km = NumericAnswer.of(40_000)

        notes = [
            n for n in run("urban_single", drives_a_lot).cost.notes if n.field == "car_km_vs_needs"
        ]
        assert len(notes) == 1
        assert "mancano" in notes[0].message

    def test_far_fewer_km_than_needs_is_reported(self, run):
        def drives_little(profile):
            profile.vehicles[0].annual_km = NumericAnswer.of(500)

        notes = [
            n for n in run("urban_single", drives_little).cost.notes if n.field == "car_km_vs_needs"
        ]
        assert len(notes) == 1
        assert "altri mezzi" in notes[0].message

    def test_no_note_when_the_km_are_estimated_not_declared(self, run):
        def forget_km(profile):
            profile.vehicles[0].annual_km = NumericAnswer()

        result = run("urban_single", forget_km)
        assert not result.car_km_check.all_declared
        assert not [n for n in result.cost.notes if n.field == "car_km_vs_needs"]

    def test_households_without_cars_have_no_check(self, run):
        assert run("car_free_household").car_km_check is None


def test_estimation_is_deterministic(estimator, demand_estimator, households):
    profile = households["peripheral_family"]
    demand = demand_estimator.estimate(profile)
    assert estimator.estimate(profile, demand) == estimator.estimate(profile, demand)


def test_current_cost_endpoint(households):
    with TestClient(app) as client:
        response = client.post(
            "/api/profile/current-cost", json=households["urban_single"].model_dump(mode="json")
        )
        assert response.status_code == 200
        body = response.json()
        assert body["portfolio"]["origin"] == "CURRENT"
        total = body["cost"]["total"]
        assert total["low"] < total["expected"] < total["high"]
        assert set(body["cost"]["by_category"]) == {"OWNERSHIP", "SUBSCRIPTIONS", "USAGE"}
        assert body["cost"]["accuracy_hints"]

        broken = households["urban_single"].model_dump(mode="json")
        broken["vehicles"][0]["option_id"] = "flying_car"
        assert client.post("/api/profile/current-cost", json=broken).status_code == 422
