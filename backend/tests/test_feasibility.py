"""Feasibility check (step 8): which portfolios can serve the household's needs at all.

Most tests build the demand and the portfolio by hand, so each rule is tested alone; the demo
households check the rules together (their current setup must always be feasible).
"""

from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from app.data.loader import Catalog, load_demo_households
from app.main import app
from app.models import (
    AccessibilityConstraint,
    AreaType,
    Confidence,
    Estimated,
    FeasibilityIssueCode,
    FeasibilityResult,
    Frequency,
    LuggageLevel,
    MobilityDemand,
    MobilityMission,
    NumericAnswer,
    Portfolio,
    PortfolioItem,
    Purpose,
    Severity,
    TimeBand,
    UserProfile,
    ValueSource,
    WorkPattern,
)
from app.services.costs import CurrentCostEstimator
from app.services.demand import RuleBasedDemandEstimator
from app.services.feasibility import RuleBasedFeasibilityChecker
from app.services.portfolios import RuleBasedPortfolioGenerator, with_service_layer


@pytest.fixture(scope="module")
def households(catalog: Catalog) -> dict[str, UserProfile]:
    return load_demo_households(catalog)


@pytest.fixture
def couple(households) -> UserProfile:
    """Two licensed adults, p1 and p2, no children, in an urban area."""
    return households["urban_couple"].model_copy(deep=True)


def mission(
    mission_id: str = "m",
    *,
    purpose: Purpose = Purpose.WEEKEND,
    times: float = 10,
    km: float = 20,
    person_id: str | None = None,
    passengers: int = 1,
    children: int = 0,
    luggage: LuggageLevel = LuggageLevel.NONE,
    window: TimeBand = TimeBand.ANY,
    requirements: tuple[AccessibilityConstraint, ...] = (),
) -> MobilityMission:
    return MobilityMission(
        id=mission_id,
        person_id=person_id,
        purpose=purpose,
        occurrences_per_year=Estimated.exact(times),
        distance_km_one_way=Estimated.exact(km),
        passengers=passengers,
        children=children,
        luggage=luggage,
        start_time_window=window,
        accessibility_requirements=list(requirements),
    )


def need_days(days: float, low: float | None = None, high: float | None = None) -> Estimated:
    return Estimated(
        value=days,
        low=low,
        high=high,
        source=ValueSource.DECLARED_APPROXIMATE,
        confidence=Confidence.MEDIUM,
    )


def demand_of(*missions: MobilityMission, simultaneous: Estimated | None = None) -> MobilityDemand:
    return MobilityDemand(
        profile_id="test", missions=list(missions), simultaneous_car_need_days=simultaneous
    )


def portfolio_of(*option_ids: str, holder: str | None = None) -> Portfolio:
    """A portfolio of the given options; `holder` is the person any subscription belongs to."""
    return Portfolio(
        id="test",
        name="test",
        items=[PortfolioItem(option_id=option_id, holder_id=holder) for option_id in option_ids],
    )


def run(
    catalog: Catalog, profile: UserProfile, demand: MobilityDemand, portfolio: Portfolio
) -> FeasibilityResult:
    return RuleBasedFeasibilityChecker(catalog).check(portfolio, demand, profile)


def codes(result: FeasibilityResult, severity: Severity | None = None) -> list:
    return [i.code for i in result.issues if severity is None or i.severity is severity]


def with_parameter(catalog: Catalog, parameter_id: str, value: float) -> Catalog:
    parameter = catalog.parameters[parameter_id].model_copy(update={"value": value})
    return replace(catalog, parameters={**catalog.parameters, parameter_id: parameter})


@pytest.fixture(scope="module")
def checked(catalog, households):
    """name -> (profile, demand, current portfolio with services, its feasibility)."""
    result = {}
    for name, profile in households.items():
        demand = RuleBasedDemandEstimator(catalog).estimate(profile)
        current = CurrentCostEstimator(catalog).estimate(profile, demand).portfolio
        current = with_service_layer(current, catalog, profile, demand)
        result[name] = (profile, demand, current, run(catalog, profile, demand, current))
    return result


class TestDemoHouseholds:
    @pytest.mark.parametrize(
        "name",
        ["urban_single", "urban_couple", "family_two_cars", "peripheral_family"]
        + ["car_free_household"],
    )
    def test_what_a_household_does_today_is_always_feasible(self, checked, name):
        # a rule that rejects the setup people actually live with is a wrong rule
        assert checked[name][3].is_feasible, [i.message for i in checked[name][3].issues]

    def test_every_mission_has_an_entry_and_only_uses_options_of_the_portfolio(self, checked):
        for name, (_, demand, portfolio, result) in checked.items():
            assert set(result.options_by_mission) == {m.id for m in demand.missions}, name
            in_portfolio = {item.option_id for item in portfolio.items}
            for options in result.options_by_mission.values():
                assert set(options) <= in_portfolio, name

    def test_candidates_with_fewer_cars_than_the_household_needs_together_are_rejected(
        self, catalog, households
    ):
        profile = households["family_two_cars"]  # declares two cars needed "often"
        demand = RuleBasedDemandEstimator(catalog).estimate(profile)
        candidates = RuleBasedPortfolioGenerator(catalog).generate(profile, demand)
        checker = RuleBasedFeasibilityChecker(catalog)
        verdicts = {c.id: checker.check(c, demand, profile).is_feasible for c in candidates}
        assert verdicts["keep-car1-car2+e_bike"]
        assert not verdicts["keep-car1+e_bike"]
        assert not verdicts["car-free+pt"]

    def test_the_result_does_not_depend_on_the_order_of_the_run(self, catalog, households):
        profile = households["urban_couple"]
        demand = RuleBasedDemandEstimator(catalog).estimate(profile)
        candidate = RuleBasedPortfolioGenerator(catalog).generate(profile, demand)[0]
        first = run(catalog, profile, demand, candidate)
        assert run(catalog, profile, demand, candidate) == first


class TestDistance:
    def test_a_bicycle_cannot_do_a_long_trip(self, catalog, couple):
        demand = demand_of(
            mission("commute", purpose=Purpose.COMMUTE, times=200, km=5, person_id="p1"),
            mission("weekend", km=180),
        )
        result = run(catalog, couple, demand, portfolio_of("bicycle", "e_bike", "walking"))
        assert not result.is_feasible
        assert result.options_by_mission["commute"] == ["bicycle", "e_bike"]
        assert result.options_by_mission["weekend"] == []
        (issue,) = result.issues
        assert (issue.mission_id, issue.code) == ("weekend", FeasibilityIssueCode.NO_OPTION)
        assert issue.severity is Severity.BLOCKING
        assert "180 km" in issue.message and "distanza" in issue.message

    def test_a_flight_or_a_fast_train_is_not_an_option_for_a_short_trip(self, catalog, couple):
        result = run(
            catalog,
            couple,
            demand_of(mission(km=8)),
            portfolio_of("rail_high_speed_ticket", "air_domestic", "walking"),
        )
        assert result.options_by_mission["m"] == []

    def test_a_daily_rental_is_not_an_option_for_an_errand(self, catalog, couple):
        short = run(catalog, couple, demand_of(mission(km=5)), portfolio_of("car_rental_daily"))
        far = run(catalog, couple, demand_of(mission(km=100)), portfolio_of("car_rental_daily"))
        assert short.options_by_mission["m"] == []
        assert far.options_by_mission["m"] == ["car_rental_daily"]


class TestFamilyLongTrip:
    """CLAUDE.md section 6: a family travelling 180 km with children and luggage."""

    @staticmethod
    def trip(**overrides) -> MobilityDemand:
        fields = dict(km=180, passengers=4, children=2, luggage=LuggageLevel.LARGE, times=10)
        return demand_of(mission(**{**fields, **overrides}))

    def test_cheap_light_vehicles_cannot_serve_it(self, catalog, couple):
        result = run(
            catalog,
            couple,
            self.trip(),
            portfolio_of("bicycle", "e_bike", "scooter_125", "walking"),
        )
        assert not result.is_feasible

    def test_a_family_car_serves_it(self, catalog, couple):
        result = run(catalog, couple, self.trip(), portfolio_of("car_medium_petrol"))
        assert result.is_feasible
        assert result.options_by_mission["m"] == ["car_medium_petrol"]

    def test_so_do_rental_and_the_fast_train(self, catalog, couple):
        result = run(
            catalog, couple, self.trip(), portfolio_of("car_rental_daily", "rail_high_speed_ticket")
        )
        assert result.options_by_mission["m"] == ["car_rental_daily", "rail_high_speed_ticket"]

    def test_a_small_car_is_accepted_with_the_default_luggage_tolerance(self, catalog, couple):
        # families do go on holiday in a small car; refusing it would bias against owning one
        result = run(catalog, couple, self.trip(), portfolio_of("car_small_petrol"))
        assert result.options_by_mission["m"] == ["car_small_petrol"]

    def test_but_not_if_the_tolerance_is_set_to_zero(self, catalog, couple):
        strict = with_parameter(catalog, "feasibility.luggage_tolerance_levels", 0)
        result = run(strict, couple, self.trip(), portfolio_of("car_small_petrol"))
        assert result.options_by_mission["m"] == []
        assert "bagaglio" in result.issues[0].message

    def test_six_people_do_not_fit_in_one_car_but_fit_in_two(self, catalog, couple):
        demand = self.trip(passengers=6, children=4)
        one = run(catalog, couple, demand, portfolio_of("car_medium_petrol"))
        two = run(catalog, couple, demand, portfolio_of("car_medium_petrol", "car_small_petrol"))
        assert one.options_by_mission["m"] == []
        assert "posti" in one.issues[0].message
        assert two.options_by_mission["m"] == ["car_medium_petrol", "car_small_petrol"]

    def test_services_are_not_limited_in_units(self, catalog, couple):
        # two taxis or two rental cars can be taken
        demand = self.trip(passengers=8, children=4, km=60, luggage=LuggageLevel.SMALL)
        result = run(catalog, couple, demand, portfolio_of("taxi_milano", "car_rental_daily"))
        assert result.options_by_mission["m"] == ["taxi_milano", "car_rental_daily"]


class TestTravellers:
    def test_nobody_with_a_licence_means_no_car_and_no_rental(self, catalog, couple):
        for adult in couple.household.adults:
            adult.has_license = False
        demand = demand_of(mission(km=250, times=3))
        result = run(
            catalog,
            couple,
            demand,
            portfolio_of("car_small_petrol", "car_rental_daily", "rail_high_speed_ticket"),
        )
        assert result.options_by_mission["m"] == ["rail_high_speed_ticket"]

    def test_a_personal_mission_needs_the_licence_of_that_person(self, catalog, couple):
        couple.household.adults[0].has_license = False  # p1
        demand = demand_of(
            mission("m1", purpose=Purpose.COMMUTE, times=200, km=8, person_id="p1"),
            mission("m2", purpose=Purpose.COMMUTE, times=200, km=8, person_id="p2"),
        )
        result = run(catalog, couple, demand, portfolio_of("car_small_petrol", "e_bike"))
        assert result.options_by_mission["m1"] == ["e_bike"]
        assert result.options_by_mission["m2"] == ["car_small_petrol", "e_bike"]

    def test_a_household_mission_needs_one_licensed_adult(self, catalog, couple):
        couple.household.adults[0].has_license = False
        result = run(catalog, couple, demand_of(mission()), portfolio_of("car_small_petrol"))
        assert result.options_by_mission["m"] == ["car_small_petrol"]

    def test_a_pass_belongs_to_whoever_holds_it(self, catalog, couple):
        demand = demand_of(
            mission("m1", purpose=Purpose.COMMUTE, times=200, km=8, person_id="p1"),
            mission("m2", purpose=Purpose.COMMUTE, times=200, km=8, person_id="p2"),
        )
        portfolio = Portfolio(
            id="test",
            name="test",
            items=[
                PortfolioItem(option_id="pt_annual_urban_milano", holder_id="p1"),
                PortfolioItem(option_id="pt_ticket_urban_milano"),
            ],
        )
        result = run(catalog, couple, demand, portfolio)
        assert result.options_by_mission["m1"] == [
            "pt_annual_urban_milano",
            "pt_ticket_urban_milano",
        ]
        assert result.options_by_mission["m2"] == ["pt_ticket_urban_milano"]

    def test_a_wheelchair_user_cannot_walk_or_ride(self, catalog, couple):
        couple.household.adults[0].accessibility_constraints = [AccessibilityConstraint.WHEELCHAIR]
        demand = demand_of(mission(purpose=Purpose.COMMUTE, times=200, km=2, person_id="p1"))
        result = run(
            catalog, couple, demand, portfolio_of("walking", "e_bike", "pt_ticket_urban_milano")
        )
        assert result.options_by_mission["m"] == ["pt_ticket_urban_milano"]

    def test_someone_who_cannot_cycle_rules_out_bikes_for_their_own_trips_only(
        self, catalog, couple
    ):
        couple.household.adults[0].accessibility_constraints = [
            AccessibilityConstraint.CANNOT_CYCLE
        ]
        demand = demand_of(
            mission("m1", purpose=Purpose.COMMUTE, times=200, km=8, person_id="p1"),
            mission("m2", purpose=Purpose.COMMUTE, times=200, km=8, person_id="p2"),
        )
        result = run(catalog, couple, demand, portfolio_of("e_bike", "bicycle"))
        assert result.options_by_mission["m1"] == []
        assert result.options_by_mission["m2"] == ["e_bike", "bicycle"]

    def test_a_trip_of_the_whole_household_takes_everyones_constraints(self, catalog, couple):
        couple.household.adults[1].accessibility_constraints = [
            AccessibilityConstraint.CANNOT_CYCLE
        ]
        result = run(catalog, couple, demand_of(mission(km=5)), portfolio_of("e_bike", "walking"))
        assert result.options_by_mission["m"] == []  # walking is too far, the e-bike is ruled out

    def test_children_do_not_ride_a_scooter(self, catalog, couple):
        alone = demand_of(mission(purpose=Purpose.SCHOOL_ESCORT, times=150, km=5))
        escort = demand_of(
            mission(purpose=Purpose.SCHOOL_ESCORT, times=150, km=5, passengers=2, children=1)
        )
        assert run(catalog, couple, alone, portfolio_of("scooter_125")).is_feasible
        assert not run(catalog, couple, escort, portfolio_of("scooter_125")).is_feasible

    def test_public_transport_does_not_run_at_night(self, catalog, couple):
        demand = demand_of(mission(km=8, window=TimeBand.NIGHT, times=20))
        result = run(
            catalog, couple, demand, portfolio_of("pt_ticket_urban_milano", "car_small_petrol")
        )
        assert result.options_by_mission["m"] == ["car_small_petrol"]

    def test_a_shift_worker_at_night_is_followed_from_the_profile_to_the_demand(
        self, catalog, couple
    ):
        couple.household.adults[0].work_or_study = WorkPattern(
            one_way_distance_km=NumericAnswer.of(8),
            days_per_week=NumericAnswer.of(5),
            typical_start=TimeBand.NIGHT,
        )
        demand = RuleBasedDemandEstimator(catalog).estimate(couple)
        result = run(
            catalog, couple, demand, portfolio_of("pt_ticket_urban_milano", "car_small_petrol")
        )
        assert result.options_by_mission["commute_p1"] == ["car_small_petrol"]


class TestRegularMissions:
    def test_a_daily_commute_by_taxi_alone_is_not_reasonable(self, catalog, couple):
        demand = demand_of(mission(purpose=Purpose.COMMUTE, times=220, km=8, person_id="p1"))
        result = run(catalog, couple, demand, portfolio_of("taxi_milano", "walking"))
        assert not result.is_feasible
        (issue,) = result.issues
        assert issue.code is FeasibilityIssueCode.NO_REGULAR_OPTION
        assert "taxi" in issue.message and "220" in issue.message
        assert result.options_by_mission["m"] == []

    def test_the_same_taxi_is_fine_for_an_occasional_trip(self, catalog, couple):
        result = run(
            catalog, couple, demand_of(mission(times=15, km=8)), portfolio_of("taxi_milano")
        )
        assert result.is_feasible
        assert result.options_by_mission["m"] == ["taxi_milano"]

    def test_regular_means_regular_whatever_the_purpose(self, catalog, couple):
        demand = demand_of(mission(purpose=Purpose.SHOPPING, times=120, km=8))
        result = run(catalog, couple, demand, portfolio_of("taxi_milano", "pt_ticket_urban_milano"))
        assert result.options_by_mission["m"] == ["pt_ticket_urban_milano"]

    def test_the_threshold_is_a_parameter(self, catalog, couple):
        demand = demand_of(mission(times=15, km=8))
        lenient = run(catalog, couple, demand, portfolio_of("taxi_milano"))
        strict = with_parameter(catalog, "feasibility.regular_min_occurrences_per_year", 10)
        assert lenient.is_feasible
        assert not run(strict, couple, demand, portfolio_of("taxi_milano")).is_feasible

    def test_a_regular_mission_with_nothing_at_all_is_a_plain_no_option(self, catalog, couple):
        demand = demand_of(mission(times=220, km=30))
        result = run(catalog, couple, demand, portfolio_of("walking"))
        assert codes(result) == [FeasibilityIssueCode.NO_OPTION]


class TestRareMissions:
    def test_a_rare_trip_nobody_can_do_is_a_warning_not_a_rejection(self, catalog, couple):
        demand = demand_of(mission("rare", times=1, km=5000))
        result = run(catalog, couple, demand, portfolio_of("car_small_petrol", "walking"))
        assert result.is_feasible
        (issue,) = result.issues
        assert issue.severity is Severity.WARNING
        assert issue.code is FeasibilityIssueCode.NO_OPTION
        assert "raramente" in issue.message

    def test_a_trip_a_few_times_a_year_is_not_rare(self, catalog, couple):
        demand = demand_of(mission("often", times=3, km=5000))
        result = run(catalog, couple, demand, portfolio_of("car_small_petrol", "walking"))
        assert not result.is_feasible

    def test_missions_that_never_happen_are_not_checked(self, catalog, couple):
        demand = demand_of(mission("never", times=0, km=5000))
        result = run(catalog, couple, demand, portfolio_of("walking"))
        assert result.is_feasible
        assert result.options_by_mission == {}


class TestSimultaneousCarNeed:
    one_trip = mission(km=10)

    def check(self, catalog, couple, *option_ids, days: float | None = 100):
        simultaneous = None if days is None else need_days(days, days * 0.6, days * 1.5)
        demand = demand_of(self.one_trip, simultaneous=simultaneous)
        return run(catalog, couple, demand, portfolio_of(*option_ids))

    def test_two_cars_cover_the_need_by_themselves(self, catalog, couple):
        result = self.check(catalog, couple, "car_small_petrol", "car_medium_petrol")
        assert result.issues == []

    def test_nothing_to_check_if_the_household_never_needs_two_cars(self, catalog, couple):
        assert self.check(catalog, couple, "car_small_petrol", days=None).issues == []
        assert self.check(catalog, couple, "car_small_petrol", days=0).issues == []

    def test_one_car_and_only_taxi_or_rental_is_not_enough_if_the_need_is_frequent(
        self, catalog, couple
    ):
        result = self.check(catalog, couple, "car_small_petrol", "taxi_milano", "car_rental_daily")
        assert not result.is_feasible
        (issue,) = result.issues
        assert issue.code is FeasibilityIssueCode.SIMULTANEOUS_CAR_NEED
        assert issue.mission_id is None
        assert "100 giorni l'anno (tra 60 e 150)" in issue.message
        assert "taxi" in issue.message and "una sola auto" in issue.message

    def test_car_sharing_makes_the_same_need_manageable(self, catalog, couple):
        result = self.check(
            catalog, couple, "car_small_petrol", "taxi_milano", "car_sharing_free2move_milano"
        )
        assert result.is_feasible
        (issue,) = result.issues
        assert issue.severity is Severity.WARNING
        assert "car sharing" in issue.message

    def test_a_less_frequent_need_is_covered_by_taxi_and_rental(self, catalog, couple):
        result = self.check(catalog, couple, "car_small_petrol", "taxi_milano", days=40)
        assert result.is_feasible
        assert codes(result, Severity.WARNING) == [FeasibilityIssueCode.SIMULTANEOUS_CAR_NEED]

    def test_without_any_service_the_need_blocks_unless_it_is_almost_never(self, catalog, couple):
        assert not self.check(catalog, couple, "car_small_petrol", days=10).is_feasible
        assert self.check(catalog, couple, "car_small_petrol", days=1).is_feasible

    def test_no_licence_means_no_rental_or_car_sharing_to_fall_back_on(self, catalog, couple):
        for adult in couple.household.adults:
            adult.has_license = False
        result = self.check(catalog, couple, "car_rental_daily", days=40)
        assert not result.is_feasible

    def test_a_car_free_portfolio_is_described_as_such(self, catalog, couple):
        result = self.check(catalog, couple, "taxi_milano", "car_rental_daily")
        assert "non ha auto" in result.issues[0].message

    def test_the_family_with_two_cars_keeps_both_in_a_suburb_but_may_sell_one_in_the_centre(
        self, catalog, households
    ):
        # same household, same declared need ("often"): car sharing exists only in the centre
        def candidates(area: AreaType):
            profile = households["family_two_cars"].model_copy(deep=True)
            profile.household.location.area_type = area
            profile.household.simultaneous_car_need = Frequency.OFTEN
            demand = RuleBasedDemandEstimator(catalog).estimate(profile)
            generated = RuleBasedPortfolioGenerator(catalog).generate(profile, demand)
            checker = RuleBasedFeasibilityChecker(catalog)
            return {c.id: checker.check(c, demand, profile).is_feasible for c in generated}

        assert not candidates(AreaType.SUBURBAN)["keep-car1+e_bike"]
        assert candidates(AreaType.CITY_CENTER)["keep-car1+e_bike"]


class TestEndpoint:
    client = TestClient(app)

    def test_the_current_setup_comes_first_then_the_candidates(self, households):
        response = self.client.post(
            "/api/portfolios/feasibility", json=households["urban_single"].model_dump(mode="json")
        )
        assert response.status_code == 200
        body = response.json()
        assert [entry["portfolio"]["id"] for entry in body][0] == "current"
        assert len(body) == 7
        assert body[0]["feasibility"]["is_feasible"] is True
        assert all(
            entry["feasibility"]["portfolio_id"] == entry["portfolio"]["id"] for entry in body
        )

    def test_infeasible_candidates_are_returned_with_their_reason(self, households):
        response = self.client.post(
            "/api/portfolios/feasibility",
            json=households["family_two_cars"].model_dump(mode="json"),
        )
        rejected = [e for e in response.json() if not e["feasibility"]["is_feasible"]]
        assert rejected
        assert all(e["feasibility"]["issues"][0]["message"] for e in rejected)

    def test_an_unknown_vehicle_is_a_422(self, households):
        payload = households["urban_single"].model_dump(mode="json")
        payload["vehicles"][0]["option_id"] = "flying_carpet"
        response = self.client.post("/api/portfolios/feasibility", json=payload)
        assert response.status_code == 422
