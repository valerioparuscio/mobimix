"""What-if scenarios (step 13): a few assumptions changed, the analysis rerun.

Each control is tested against what it must do to the numbers, computed here from the data; the
neutral scenario must be the analysis itself, and nothing may be changed in place.
"""

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.data.loader import Catalog, load_demo_households
from app.main import app
from app.models import NumericAnswer, Scenario, UserProfile
from app.services.demand import RuleBasedDemandEstimator
from app.services.pipeline import analyze
from app.services.scenarios import apply_scenario


@pytest.fixture(scope="module")
def households(catalog: Catalog) -> dict[str, UserProfile]:
    return load_demo_households(catalog)


@pytest.fixture(scope="module")
def single(households) -> UserProfile:
    return households["urban_single"]


@pytest.fixture(scope="module")
def base(catalog, single):
    return analyze(catalog, single)


def candidate(result, portfolio_id: str):
    return next(e for e in result.evaluations if e.portfolio_id == portfolio_id)


class TestTheScenario:
    def test_it_is_neutral_by_default(self):
        assert Scenario().is_neutral
        assert not Scenario(fuel_price_change=0.1).is_neutral

    @pytest.mark.parametrize(
        "bad",
        [
            {"extra_remote_days_per_week": -1},
            {"extra_remote_days_per_week": 5},
            {"fuel_price_change": -0.6},
            {"fuel_price_change": 1.5},
            {"parking_cost_change": -1.5},
            {"car_km_change": 2},
            {"ebike_subsidy_eur": -1},
            {"ebike_subsidy_eur": 3000},
        ],
    )
    def test_it_stays_within_what_the_model_is_meant_to_be_asked(self, bad):
        with pytest.raises(ValidationError):
            Scenario(**bad)

    def test_a_typo_is_an_error(self):
        with pytest.raises(ValidationError):
            Scenario(fuel_price=0.1)


class TestNothingIsChangedInPlace:
    def test_the_neutral_scenario_is_the_analysis_itself(self, catalog, single, base):
        again = analyze(catalog, single, Scenario())
        assert again == base
        assert again.scenario is None

    def test_the_profile_and_the_catalogue_come_back_as_copies(self, catalog, single):
        before = single.model_dump()
        parameters_before = {k: v.model_dump() for k, v in catalog.parameters.items()}
        scenario = Scenario(
            extra_remote_days_per_week=2,
            fuel_price_change=0.3,
            parking_cost_change=0.5,
            car_km_change=0.2,
            ebike_subsidy_eur=500,
        )
        changed_catalog, changed_profile = apply_scenario(catalog, single, scenario)
        assert single.model_dump() == before
        assert {k: v.model_dump() for k, v in catalog.parameters.items()} == parameters_before
        assert changed_profile is not single and changed_catalog is not catalog

    def test_the_same_scenario_gives_the_same_answer(self, catalog, single):
        scenario = Scenario(fuel_price_change=0.2, car_km_change=-0.1)
        assert analyze(catalog, single, scenario) == analyze(catalog, single, scenario)

    def test_the_result_says_what_it_was_run_with(self, catalog, single):
        scenario = Scenario(fuel_price_change=0.2)
        assert analyze(catalog, single, scenario).scenario == scenario


class TestFuelPrice:
    def test_dearer_fuel_makes_the_car_dearer(self, catalog, single, base):
        dearer = analyze(catalog, single, Scenario(fuel_price_change=0.5))
        assert dearer.current.annual_cost.expected > base.current.annual_cost.expected

    def test_the_prices_scale_value_and_range(self, catalog, single):
        changed, _ = apply_scenario(catalog, single, Scenario(fuel_price_change=0.5))
        before = catalog.parameter("energy.petrol_eur_per_l")
        after = changed.parameter("energy.petrol_eur_per_l")
        assert after.value == pytest.approx(1.5 * before.value)
        assert after.high == pytest.approx(1.5 * before.high)
        assert after.low == pytest.approx(1.5 * before.low)

    def test_the_cost_rises_by_half_of_what_fuel_costs_today(self, catalog, single, base):
        # +50% on the price: half of today's energy cost, the car and the rental car alike
        energy_today = sum(
            line.amount.expected for line in base.current.cost_lines if line.label == "energy"
        )
        dearer = analyze(catalog, single, Scenario(fuel_price_change=0.5))
        assert energy_today > 0
        assert dearer.current.annual_cost.expected - base.current.annual_cost.expected == (
            pytest.approx(0.5 * energy_today, rel=1e-6)
        )

    def test_it_makes_giving_up_the_car_pay_more(self, catalog, single, base):
        dearer = analyze(catalog, single, Scenario(fuel_price_change=0.5))
        before = candidate(base, "car-free+pt").delta.cost.expected
        after = candidate(dearer, "car-free+pt").delta.cost.expected
        assert after < before < 0  # a bigger saving

    def test_electricity_is_left_alone(self, catalog, single):
        changed, _ = apply_scenario(catalog, single, Scenario(fuel_price_change=0.5))
        for parameter_id in (
            "energy.electricity_home_eur_per_kwh",
            "energy.electricity_public_ac_eur_per_kwh",
        ):
            assert changed.value(parameter_id) == catalog.value(parameter_id)


class TestParking:
    def test_free_parking_removes_what_the_car_costs_to_park(self, catalog, single, base):
        free = analyze(catalog, single, Scenario(parking_cost_change=-1))
        default = catalog.defaults_for(single.household.location.area_type).values[
            "parking_cost_year_per_car"
        ]
        assert base.current.annual_cost.expected - free.current.annual_cost.expected == (
            pytest.approx(default.value)
        )

    def test_a_declared_cost_is_scaled_and_an_unknown_one_stays_unknown(self, catalog, households):
        couple = households["family_two_cars"].model_copy(deep=True)
        couple.vehicles[1].parking_cost_year = NumericAnswer()  # not declared
        _, changed = apply_scenario(catalog, couple, Scenario(parking_cost_change=0.5))
        assert changed.vehicles[0].parking_cost_year.exact == pytest.approx(250 * 1.5)
        assert changed.vehicles[1].parking_cost_year.kind == "unknown"

    def test_the_default_for_an_unknown_cost_and_for_a_new_car_changes(self, catalog, single):
        changed, _ = apply_scenario(catalog, single, Scenario(parking_cost_change=1.0))
        for area, defaults in catalog.area_defaults.items():
            before = defaults.values["parking_cost_year_per_car"].value
            assert changed.defaults_for(area).values["parking_cost_year_per_car"].value == (
                pytest.approx(2 * before)
            )

    def test_it_changes_what_buying_a_car_costs(self, catalog, households):
        free_household = households["car_free_household"]
        base = analyze(catalog, free_household)
        dearer = analyze(catalog, free_household, Scenario(parking_cost_change=1.0))
        buy = "buy-car_small_petrol+cars_only"
        assert (
            candidate(dearer, buy).annual_cost.expected > candidate(base, buy).annual_cost.expected
        )

    def test_only_cars_are_parked(self, catalog, households):
        household = households["urban_couple"].model_copy(deep=True)
        _, changed = apply_scenario(catalog, household, Scenario(parking_cost_change=1.0))
        assert [v.option_id for v in changed.vehicles] == [v.option_id for v in household.vehicles]


class TestCarKilometres:
    def test_driving_more_costs_more(self, catalog, single, base):
        more = analyze(catalog, single, Scenario(car_km_change=0.5))
        assert more.current.annual_cost.expected > base.current.annual_cost.expected

    def test_the_declared_range_scales(self, catalog, single):
        _, changed = apply_scenario(catalog, single, Scenario(car_km_change=0.5))
        before = single.vehicles[0].annual_km
        assert changed.vehicles[0].annual_km.low == pytest.approx(before.low * 1.5)
        assert changed.vehicles[0].annual_km.high == pytest.approx(before.high * 1.5)

    def test_the_trips_the_household_needs_do_not_change(self, catalog, single):
        changed_catalog, changed = apply_scenario(catalog, single, Scenario(car_km_change=0.5))
        before = RuleBasedDemandEstimator(catalog).estimate(single)
        after = RuleBasedDemandEstimator(changed_catalog).estimate(changed)
        assert after.total_annual_km == pytest.approx(before.total_annual_km)

    def test_the_defaults_for_a_car_with_no_declared_mileage_change(self, catalog, single):
        changed, _ = apply_scenario(catalog, single, Scenario(car_km_change=-0.5))
        for area, defaults in catalog.area_defaults.items():
            for key in ("car_annual_km_first", "car_annual_km_second"):
                assert changed.defaults_for(area).values[key].value == pytest.approx(
                    0.5 * defaults.values[key].value
                )


class TestRemoteWork:
    def test_working_from_home_removes_commuting_trips(self, catalog, single, base):
        remote = analyze(catalog, single, Scenario(extra_remote_days_per_week=2))
        assert (
            remote.current.annual_travel_hours.expected < base.current.annual_travel_hours.expected
        )

    def test_an_unknown_number_of_remote_days_counts_as_none(self, catalog, single):
        household = single.model_copy(deep=True)
        household.household.adults[0].work_or_study.remote_days_per_week = NumericAnswer()
        household.household.adults[0].work_or_study.days_per_week = NumericAnswer.of(5)
        _, changed = apply_scenario(catalog, household, Scenario(extra_remote_days_per_week=2))
        assert changed.household.adults[0].work_or_study.remote_days_per_week.exact == 2

    def test_it_adds_to_what_was_declared(self, catalog, households):
        family = households["family_two_cars"]  # p1 works 5 days, 1 remote; p2 4 days, none
        _, changed = apply_scenario(catalog, family, Scenario(extra_remote_days_per_week=2))
        remote = [a.work_or_study.remote_days_per_week.exact for a in changed.household.adults]
        assert remote == [3, 2]

    def test_nobody_works_from_home_more_days_than_they_work(self, catalog, households):
        family = households["family_two_cars"].model_copy(deep=True)
        family.household.adults[1].work_or_study.remote_days_per_week = NumericAnswer.of(2)
        _, changed = apply_scenario(catalog, family, Scenario(extra_remote_days_per_week=4))
        # p1: 5 days, 1 remote + 4 = 5; p2: 4 days, 2 remote + 4 = 6, capped at 4
        assert [a.work_or_study.remote_days_per_week.exact for a in changed.household.adults] == [
            5,
            4,
        ]

    def test_nothing_is_left_to_commute_when_everybody_is_at_home(self, catalog, households):
        family = households["family_two_cars"]
        changed_catalog, changed = apply_scenario(
            catalog, family, Scenario(extra_remote_days_per_week=4)
        )
        demand = RuleBasedDemandEstimator(changed_catalog).estimate(changed)
        assert not [m for m in demand.missions if m.purpose == "COMMUTE"]

    def test_someone_who_does_not_commute_is_not_touched(self, catalog, households):
        household = households["urban_single"].model_copy(deep=True)
        household.household.adults[0].work_or_study = None
        _, changed = apply_scenario(catalog, household, Scenario(extra_remote_days_per_week=2))
        assert changed.household.adults[0].work_or_study is None

    def test_commuting_by_car_less_can_change_the_answer(self, catalog, single, base):
        remote = analyze(catalog, single, Scenario(extra_remote_days_per_week=2))
        assert (
            remote.recommendations.headline_portfolio_id
            != base.recommendations.headline_portfolio_id
        )


class TestEbikeSubsidy:
    def test_the_depreciation_of_a_new_ebike_falls_by_the_subsidy_over_its_life(
        self, catalog, single, base
    ):
        ebike = catalog.option("e_bike")
        subsidised = analyze(catalog, single, Scenario(ebike_subsidy_eur=600))
        before = candidate(base, "keep-car1+e_bike").annual_cost.expected
        after = candidate(subsidised, "keep-car1+e_bike").annual_cost.expected
        assert before - after == pytest.approx(600 / ebike.expected_lifetime_years.value)

    def test_it_never_takes_the_price_below_the_resale_value(self, catalog, single):
        changed, _ = apply_scenario(catalog, single, Scenario(ebike_subsidy_eur=2000))
        ebike = changed.option("e_bike")
        assert ebike.purchase_price.value == pytest.approx(ebike.residual_value.value)

    def test_only_the_ebike_the_generator_buys_is_touched(self, catalog, single):
        changed, _ = apply_scenario(catalog, single, Scenario(ebike_subsidy_eur=800))
        assert (
            changed.option("scooter_125").purchase_price
            == catalog.option("scooter_125").purchase_price
        )
        assert changed.option("bicycle").purchase_price == catalog.option("bicycle").purchase_price

    def test_an_ebike_already_owned_is_not_paid_back(self, catalog, households):
        # the subsidy lowers what a NEW one costs; the cost of one the household has is the
        # declared one and its present value
        household = households["car_free_household"]
        base = analyze(catalog, household)
        subsidised = analyze(catalog, household, Scenario(ebike_subsidy_eur=800))
        assert subsidised.current.annual_cost.expected == pytest.approx(
            base.current.annual_cost.expected
        )


class TestSeveralAtOnce:
    def test_controls_do_not_interfere(self, catalog, single, base):
        together = analyze(
            catalog,
            single,
            Scenario(fuel_price_change=0.5, parking_cost_change=-1, ebike_subsidy_eur=800),
        )
        fuel = analyze(catalog, single, Scenario(fuel_price_change=0.5))
        parking = analyze(catalog, single, Scenario(parking_cost_change=-1))
        expected = (
            base.current.annual_cost.expected
            + (fuel.current.annual_cost.expected - base.current.annual_cost.expected)
            + (parking.current.annual_cost.expected - base.current.annual_cost.expected)
        )
        assert together.current.annual_cost.expected == pytest.approx(expected, rel=0.01)


class TestEndpoint:
    client = TestClient(app)

    def body(self, profile: UserProfile, **scenario):
        return {"profile": profile.model_dump(mode="json"), "scenario": scenario}

    def test_it_answers_with_the_whole_analysis_and_the_scenario(self, single):
        response = self.client.post(
            "/api/scenario", json=self.body(single, fuel_price_change=0.5, ebike_subsidy_eur=500)
        )
        assert response.status_code == 200
        result = response.json()
        assert result["scenario"]["fuel_price_change"] == 0.5
        assert result["recommendations"]["headline_portfolio_id"]
        assert result["current"]["portfolio_id"] == "current"

    def test_a_neutral_scenario_is_the_plain_analysis(self, single):
        scenario = self.client.post("/api/scenario", json=self.body(single)).json()
        plain = self.client.post("/api/analyze", json=single.model_dump(mode="json")).json()
        assert scenario == plain

    def test_a_scenario_outside_the_bounds_is_refused(self, single):
        response = self.client.post("/api/scenario", json=self.body(single, fuel_price_change=5))
        assert response.status_code == 422

    def test_an_unknown_option_is_a_422(self, single):
        body = self.body(single, fuel_price_change=0.1)
        body["profile"]["vehicles"][0]["option_id"] = "hoverboard"
        assert self.client.post("/api/scenario", json=body).status_code == 422
