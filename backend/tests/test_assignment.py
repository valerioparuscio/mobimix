"""Mode assignment (step 9): which option of a feasible portfolio serves each mission.

Most tests build the demand and the portfolio by hand so that each rule is tested alone; the
demo households check the rules together.
"""

from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from app.data.loader import Catalog, load_demo_households
from app.main import app
from app.models import (
    AllocationReason,
    CheckedPortfolio,
    Confidence,
    Estimated,
    Level,
    LuggageLevel,
    MissionAllocation,
    MobilityDemand,
    MobilityMission,
    ModeAssignment,
    OptionUsage,
    Ownership,
    ParameterValue,
    Portfolio,
    PortfolioItem,
    Purpose,
    Range,
    UserProfile,
    ValueSource,
)
from app.services.costs import CurrentCostEstimator
from app.services.costs.model import TcoCostModel
from app.services.demand import RuleBasedDemandEstimator
from app.services.feasibility import RuleBasedFeasibilityChecker
from app.services.optimizer import GeneralizedCost, GeneralizedCostAssigner, TripCalculator
from app.services.portfolios import with_service_layer

# --- building blocks -----------------------------------------------------------------------


@pytest.fixture(scope="module")
def households(catalog: Catalog) -> dict[str, UserProfile]:
    return load_demo_households(catalog)


@pytest.fixture
def couple(households) -> UserProfile:
    """Two licensed adults, p1 and p2, no children."""
    return households["urban_couple"].model_copy(deep=True)


def mission(
    mission_id: str = "m",
    *,
    purpose: Purpose = Purpose.COMMUTE,
    times: float = 100,
    km: float = 8,
    person_id: str | None = "p1",
    passengers: int = 1,
    legs: int = 2,
    days_away: float = 0,
    luggage: LuggageLevel = LuggageLevel.NONE,
    weather: Level = Level.MEDIUM,
) -> MobilityMission:
    return MobilityMission(
        id=mission_id,
        person_id=person_id,
        purpose=purpose,
        occurrences_per_year=Estimated.exact(times),
        distance_km_one_way=Estimated.exact(km),
        legs_per_occurrence=legs,
        days_away=days_away,
        passengers=passengers,
        luggage=luggage,
        weather_sensitivity=weather,
    )


def demand_of(*missions: MobilityMission, simultaneous_days: float | None = None) -> MobilityDemand:
    need = (
        Estimated(
            value=simultaneous_days,
            source=ValueSource.DECLARED_APPROXIMATE,
            confidence=Confidence.MEDIUM,
        )
        if simultaneous_days is not None
        else None
    )
    return MobilityDemand(
        profile_id="test", missions=list(missions), simultaneous_car_need_days=need
    )


def portfolio_of(*entries: str | tuple[str, str | None], quantity: int = 1) -> Portfolio:
    """Items given as an option id, or as (option id, holder id)."""
    items = []
    for entry in entries:
        option_id, holder = (entry, None) if isinstance(entry, str) else entry
        items.append(PortfolioItem(option_id=option_id, holder_id=holder, quantity=quantity))
    return Portfolio(id="test", name="test", items=items)


def assign(
    catalog: Catalog, profile: UserProfile, demand: MobilityDemand, portfolio: Portfolio
) -> ModeAssignment:
    feasibility = RuleBasedFeasibilityChecker(catalog).check(portfolio, demand, profile)
    checked = CheckedPortfolio(portfolio=portfolio, feasibility=feasibility)
    return GeneralizedCostAssigner(catalog).assign(checked, demand, profile)


def shares(assignment: ModeAssignment, mission_id: str) -> dict[str, float]:
    return {a.option_id: a.share for a in assignment.allocations if a.mission_id == mission_id}


def with_parameter(catalog: Catalog, parameter_id: str, value: float) -> Catalog:
    parameter = catalog.parameters[parameter_id].model_copy(update={"value": value})
    return replace(catalog, parameters={**catalog.parameters, parameter_id: parameter})


# --- trips: time, units, usage -------------------------------------------------------------


def _speed(value: float) -> ParameterValue:
    return ParameterValue(value=value)


class TestTrips:
    def test_a_leg_takes_distance_over_speed_plus_the_fixed_time(self, catalog):
        car = catalog.option("car_medium_petrol")  # 22 km/h in town, 8 minutes to park
        hours = TripCalculator(catalog).leg_hours(car, 8)
        assert hours == pytest.approx(8 / 22 + 8 / 60)

    def test_a_band_without_a_speed_uses_the_nearest_band_the_option_has(self, catalog):
        ticket = catalog.option("rail_high_speed_ticket")  # only LONG
        assert set(ticket.average_speed_kmh) == {"LONG"}
        # a 100 km leg is REGIONAL, which the ticket does not define
        assert TripCalculator(catalog).leg_hours(ticket, 100) == pytest.approx(100 / 150 + 35 / 60)

    def test_two_equally_near_bands_take_the_slower_speed(self, catalog):
        option = catalog.option("car_medium_petrol").model_copy(
            update={"average_speed_kmh": {"URBAN": _speed(20), "LONG": _speed(100)}}
        )
        hours = TripCalculator(catalog).leg_hours(option, 50)  # REGIONAL: URBAN and LONG tie
        assert hours == pytest.approx(50 / 20 + 8 / 60)

    @pytest.mark.parametrize(
        ("option_id", "passengers", "units"),
        [
            ("car_medium_petrol", 4, 1),  # one car carries four
            ("car_medium_petrol", 6, 2),  # six need two cars
            ("taxi_milano", 5, 2),
            ("pt_ticket_urban_milano", 3, 3),  # no seats: one ticket each
            ("bicycle", 2, 2),  # one bicycle each
        ],
    )
    def test_units_follow_the_seats_of_the_vehicle(self, catalog, option_id, passengers, units):
        trip = TripCalculator(catalog).trip(
            mission(passengers=passengers, km=5), catalog.option(option_id)
        )
        assert trip.units == units

    def test_person_hours_count_every_traveller(self, catalog):
        calculator = TripCalculator(catalog)
        car = catalog.option("car_medium_petrol")
        alone = calculator.trip(mission(passengers=1), car)
        family = calculator.trip(mission(passengers=4), car)
        assert family.leg_hours == alone.leg_hours
        assert family.person_hours == pytest.approx(4 * alone.person_hours)

    def test_a_car_drives_the_distance_of_every_leg_once(self, catalog):
        trip = TripCalculator(catalog).trip(
            mission(km=8, legs=2), catalog.option("car_medium_petrol")
        )
        assert trip.usage.annual_km.expected == pytest.approx(16)
        two_cars = TripCalculator(catalog).trip(
            mission(km=8, legs=2, passengers=6), catalog.option("car_medium_petrol")
        )
        assert two_cars.usage.annual_km.expected == pytest.approx(32)

    def test_car_sharing_is_kept_for_the_journey_and_the_stay(self, catalog):
        calculator = TripCalculator(catalog)
        option = catalog.option("car_sharing_free2move_milano")
        commute = calculator.trip(mission(purpose=Purpose.COMMUTE, km=8), option)
        shopping = calculator.trip(mission(purpose=Purpose.SHOPPING, km=8), option)
        assert commute.usage.annual_trips.expected == 1  # one rental
        stay = catalog.assignment_rules.stay_hours_by_purpose
        extra = (stay[Purpose.COMMUTE] - stay[Purpose.SHOPPING]) * 60
        assert commute.usage.annual_minutes.expected - shopping.usage.annual_minutes.expected == (
            pytest.approx(extra)
        )

    def test_a_stay_overnight_replaces_the_hours_of_the_table(self, catalog):
        calculator = TripCalculator(catalog)
        assert calculator.stay_hours(mission(days_away=3)) == 72
        assert (
            calculator.stay_hours(mission(purpose=Purpose.SHOPPING))
            == (catalog.assignment_rules.stay_hours_by_purpose[Purpose.SHOPPING])
        )

    def test_rental_is_billed_by_the_day_rounded_up_at_least_one(self, catalog):
        calculator = TripCalculator(catalog)
        rental = catalog.option("car_rental_daily")
        assert calculator.trip(mission(km=60, days_away=0), rental).usage.annual_days.expected == 1
        assert (
            calculator.trip(mission(km=60, days_away=2.2), rental).usage.annual_days.expected == 3
        )

    def test_a_trip_priced_per_leg_counts_a_trip_for_every_leg_and_passenger(self, catalog):
        trip = TripCalculator(catalog).trip(
            mission(passengers=2, legs=2), catalog.option("pt_ticket_urban_milano")
        )
        assert trip.usage.annual_trips.expected == 4
        assert trip.usage_cost == pytest.approx(
            4 * catalog.option("pt_ticket_urban_milano").cost_per_trip.value
        )


# --- the cost on the margin ----------------------------------------------------------------


class TestUsageCost:
    def test_an_owned_car_costs_fuel_and_wear_not_its_fixed_costs(self, catalog):
        model = TcoCostModel(catalog)
        car = catalog.option("car_medium_petrol")
        usage = OptionUsage(annual_km=Range.point(100))
        expected = 100 * (
            car.energy.consumption_per_100km.value / 100 * catalog.value("energy.petrol_eur_per_l")
            + car.cost_per_km.value
        )
        assert model.usage_cost(car, usage) == pytest.approx(expected)

    def test_it_is_the_total_cost_without_the_fixed_components(self, catalog):
        model = TcoCostModel(catalog)
        car = catalog.option("car_medium_petrol")
        usage = OptionUsage(annual_km=Range.point(5000), parking_cost_year=Range.point(900))
        fixed = {"depreciation", "insurance", "tax", "maintenance", "parking", "financing"}
        total = model.calculate(car, usage)
        usage_lines = sum(line.amount.expected for line in total.lines if line.label not in fixed)
        assert model.usage_cost(car, usage) == pytest.approx(usage_lines)

    def test_a_pass_already_paid_costs_nothing_to_use_a_ticket_costs_its_fare(self, catalog):
        model = TcoCostModel(catalog)
        usage = OptionUsage(annual_trips=Range.point(4), annual_km=Range.point(30))
        assert model.usage_cost(catalog.option("pt_annual_urban_milano"), usage) == 0
        assert model.usage_cost(catalog.option("pt_ticket_urban_milano"), usage) == (
            pytest.approx(4 * catalog.option("pt_ticket_urban_milano").cost_per_trip.value)
        )

    def test_a_multi_day_car_sharing_rental_pays_every_started_day(self, catalog):
        # a flat day rate would charge a ten-day holiday as one day
        model = TcoCostModel(catalog)
        option = catalog.option("car_sharing_free2move_milano")
        day = option.cost_per_day.value

        def rental(hours: float) -> float:
            usage = OptionUsage(annual_trips=Range.point(1), annual_minutes=Range.point(hours * 60))
            return model.usage_cost(option, usage)

        assert rental(10) == pytest.approx(day)  # within one day
        assert rental(30) == pytest.approx(2 * day)  # a day and a half
        assert rental(240) == pytest.approx(10 * day)


# --- tolls and getting around at the destination --------------------------------------------


class TestTollsAndDestination:
    def test_in_town_there_are_no_tolls_on_a_long_trip_most_of_it_is_motorway(self, catalog):
        calculator = TripCalculator(catalog)
        car = catalog.option("car_medium_petrol")
        town = calculator.trip(mission(km=8), car)
        regional = calculator.trip(mission(km=60), car)
        far = calculator.trip(mission(km=450), car)
        assert town.usage.annual_toll_km.expected == 0
        assert regional.usage.annual_toll_km.expected == pytest.approx(
            2 * 60 * catalog.value("usage.motorway_share.regional")
        )
        assert far.usage.annual_toll_km.expected == pytest.approx(
            2 * 450 * catalog.value("usage.motorway_share.long")
        )

    def test_a_toll_is_paid_by_road_vehicles_only(self, catalog):
        calculator = TripCalculator(catalog)
        long_trip = mission(km=450)
        for option_id in ("car_medium_petrol", "car_rental_daily", "taxi_milano"):
            trip = calculator.trip(long_trip, catalog.option(option_id))
            assert trip.usage.annual_toll_km.expected > 0, option_id
        for option_id in ("rail_high_speed_ticket", "air_domestic", "bicycle"):
            trip = calculator.trip(long_trip, catalog.option(option_id))
            assert trip.usage.annual_toll_km.expected == 0, option_id

    def test_the_toll_is_charged_at_the_average_rate(self, catalog):
        model = TcoCostModel(catalog)
        car = catalog.option("car_medium_petrol")
        with_toll = OptionUsage(annual_km=Range.point(100), annual_toll_km=Range.point(80))
        without = OptionUsage(annual_km=Range.point(100))
        extra = model.usage_cost(car, with_toll) - model.usage_cost(car, without)
        assert extra == pytest.approx(80 * catalog.value("usage.motorway_toll_eur_per_km"))
        # a bicycle has no toll even if the usage said so
        bike = catalog.option("bicycle")
        assert model.usage_cost(bike, with_toll) == model.usage_cost(bike, without)

    def test_a_stay_by_train_costs_getting_around_a_stay_by_car_does_not(self, catalog):
        calculator = TripCalculator(catalog)
        holiday = mission(purpose=Purpose.HOLIDAY, km=450, days_away=10, passengers=2)
        train = calculator.trip(holiday, catalog.option("rail_high_speed_ticket"))
        car = calculator.trip(holiday, catalog.option("car_medium_petrol"))
        assert train.usage.annual_destination_days.expected == 10
        assert car.usage.annual_destination_days.expected == 0
        model = TcoCostModel(catalog)
        per_day = catalog.value("usage.destination_mobility_eur_per_day")
        no_stay = train.usage.model_copy(update={"annual_destination_days": Range.point(0)})
        assert train.usage_cost - model.usage_cost(
            catalog.option("rail_high_speed_ticket"), no_stay
        ) == pytest.approx(10 * per_day)

    def test_a_day_trip_by_train_has_nowhere_to_get_around(self, catalog):
        trip = TripCalculator(catalog).trip(
            mission(purpose=Purpose.WEEKEND, km=60, days_away=0),
            catalog.option("rail_regional_ticket"),
        )
        assert trip.usage.annual_destination_days.expected == 0

    def test_tolls_and_the_stay_move_long_trips_from_the_train_to_the_car(self, catalog, couple):
        # without them a car owner goes by train; with them the car wins the 250 km weekend
        demand = demand_of(
            mission(
                "w",
                purpose=Purpose.LONG_DISTANCE,
                km=250,
                times=3,
                days_away=3,
                passengers=2,
                person_id=None,
                luggage=LuggageLevel.MEDIUM,
            )
        )
        portfolio = portfolio_of(("car_medium_petrol", "p1"), "rail_high_speed_ticket")
        plain = with_parameter(
            with_parameter(catalog, "usage.motorway_toll_eur_per_km", 0.0),
            "usage.destination_mobility_eur_per_day",
            0.0,
        )
        car_share = lambda c: shares(assign(c, couple, demand, portfolio), "w").get(  # noqa: E731
            "car_medium_petrol", 0.0
        )
        assert car_share(catalog) > car_share(plain)


# --- the generalized cost ------------------------------------------------------------------


class TestGeneralizedCost:
    def test_perceived_time_goes_from_one_at_full_comfort_to_the_multiplier_at_none(self, catalog):
        cost = GeneralizedCost(catalog)
        multiplier = catalog.value("assignment.perceived_time_multiplier_at_zero_comfort")
        assert cost.time_weight(10) == 1
        assert cost.time_weight(0) == pytest.approx(multiplier)
        assert cost.time_weight(5) == pytest.approx((1 + multiplier) / 2)

    def test_it_is_money_plus_valued_perceived_hours(self, catalog):
        calculator, cost = TripCalculator(catalog), GeneralizedCost(catalog)
        trip = calculator.trip(mission(km=8), catalog.option("pt_ticket_urban_milano"))
        value = catalog.value("valuation.value_of_time_eur_per_hour")
        expected = trip.usage_cost + value * trip.person_hours * cost.time_weight(trip.comfort)
        assert cost.of(trip) == pytest.approx(expected)

    def test_a_more_comfortable_means_wins_a_tie_on_money_and_time(self, catalog):
        calculator, cost = TripCalculator(catalog), GeneralizedCost(catalog)
        car = catalog.option("car_medium_petrol")
        worse = car.model_copy(
            update={"comfort_score": car.comfort_score.model_copy(update={"value": 4})}
        )
        trip, worse_trip = calculator.trip(mission(), car), calculator.trip(mission(), worse)
        assert cost.of(trip) < cost.of(worse_trip)


# --- the assignment ------------------------------------------------------------------------


class TestShares:
    def test_the_shares_of_a_mission_add_up_to_one_and_stay_within_the_feasible_options(
        self, catalog, couple
    ):
        demand = demand_of(mission("a", km=8), mission("b", km=3, person_id="p2"))
        portfolio = portfolio_of(
            "car_medium_petrol", "pt_ticket_urban_milano", "bicycle", "walking"
        )
        feasibility = RuleBasedFeasibilityChecker(catalog).check(portfolio, demand, couple)
        result = assign(catalog, couple, demand, portfolio)
        for mission_id, allowed in feasibility.options_by_mission.items():
            mine = shares(result, mission_id)
            assert sum(mine.values()) == pytest.approx(1)
            assert set(mine) <= set(allowed)

    def test_a_mission_with_one_option_gives_it_everything(self, catalog, couple):
        demand = demand_of(mission("holiday", purpose=Purpose.HOLIDAY, km=450, times=2))
        result = assign(catalog, couple, demand, portfolio_of("rail_high_speed_ticket"))
        (only,) = result.allocations
        assert only.option_id == "rail_high_speed_ticket"
        assert only.share == pytest.approx(1)
        assert only.reason is AllocationReason.ONLY_OPTION

    def test_a_mission_nothing_serves_is_reported_not_invented(self, catalog, couple):
        # a 450 km holiday trip a few times a year with nothing but walking is only a warning
        demand = demand_of(mission("holiday", purpose=Purpose.HOLIDAY, km=450, times=1))
        result = assign(catalog, couple, demand, portfolio_of("walking"))
        assert result.unserved_mission_ids == ["holiday"]
        assert result.allocations == []

    def test_the_assignment_is_deterministic(self, catalog, couple):
        demand = demand_of(mission("a"), mission("b", km=3, person_id="p2"))
        portfolio = portfolio_of("car_medium_petrol", "pt_ticket_urban_milano", "bicycle")
        assert assign(catalog, couple, demand, portfolio) == assign(
            catalog, couple, demand, portfolio
        )

    def test_the_cheapest_way_into_a_mode_is_the_only_one_that_competes(self, catalog, couple):
        # the household holds the pass: it does not also buy tickets for the same trips
        demand = demand_of(mission("a", km=8))
        portfolio = portfolio_of(("pt_annual_urban_milano", "p1"), "pt_ticket_urban_milano")
        assert set(shares(assign(catalog, couple, demand, portfolio), "a")) == {
            "pt_annual_urban_milano"
        }

    def test_the_car_in_the_garage_beats_car_sharing_for_the_same_trip(self, catalog, couple):
        demand = demand_of(mission("a", km=8))
        portfolio = portfolio_of(("car_medium_petrol", "p1"), "car_sharing_free2move_milano")
        assert set(shares(assign(catalog, couple, demand, portfolio), "a")) == {"car_medium_petrol"}

    def test_a_clear_winner_takes_almost_everything_and_a_near_tie_is_shared(self, catalog, couple):
        demand = demand_of(mission("short", km=1.5, passengers=1))
        # walking vs a ticket for 1.5 km: close - both are used
        close = assign(catalog, couple, demand, portfolio_of("walking", "pt_ticket_urban_milano"))
        assert min(shares(close, "short").values()) > 0.2
        # a 450 km holiday for two: the car clearly beats the flight
        far = demand_of(mission("far", purpose=Purpose.HOLIDAY, km=450, times=2, passengers=2))
        winner = assign(
            catalog, couple, far, portfolio_of(("car_medium_petrol", "p1"), "air_domestic")
        )
        assert max(shares(winner, "far").values()) > 0.99

    def test_a_sharper_choice_concentrates_the_shares(self, catalog, couple):
        demand = demand_of(mission("a", km=8))
        portfolio = portfolio_of(("car_medium_petrol", "p1"), ("pt_annual_urban_milano", "p1"))

        def best_share(scale: float) -> float:
            sharper = with_parameter(catalog, "assignment.logit_scale_per_eur", scale)
            return max(shares(assign(sharper, couple, demand, portfolio), "a").values())

        assert best_share(0.05) < best_share(0.25) < best_share(2.0)
        assert best_share(50.0) == pytest.approx(1)

    def test_small_shares_are_dropped_and_the_rest_renormalised(self, catalog, couple):
        demand = demand_of(mission("a", km=8))
        portfolio = portfolio_of(("car_medium_petrol", "p1"), "pt_ticket_urban_milano", "bicycle")
        loose = with_parameter(catalog, "assignment.min_share", 0.0)
        strict = with_parameter(catalog, "assignment.min_share", 0.30)
        many = shares(assign(loose, couple, demand, portfolio), "a")
        few = shares(assign(strict, couple, demand, portfolio), "a")
        assert len(few) < len(many)
        assert sum(few.values()) == pytest.approx(1)
        assert all(share >= 0.30 for share in few.values())

    def test_passengers_change_the_choice(self, catalog, couple):
        # alone a ticket is fine; a family of four pays four tickets each way: the car wins
        portfolio = portfolio_of(("car_medium_petrol", "p1"), "pt_ticket_urban_milano")
        alone = assign(catalog, couple, demand_of(mission("a", km=4, person_id=None)), portfolio)
        family = assign(
            catalog, couple, demand_of(mission("a", km=4, person_id=None, passengers=4)), portfolio
        )
        assert shares(family, "a")["car_medium_petrol"] > shares(alone, "a")["car_medium_petrol"]


# --- weather -------------------------------------------------------------------------------


class TestWeather:
    PORTFOLIO = (("bicycle", "p1"), ("pt_annual_urban_milano", "p1"))

    def test_on_bad_weather_days_an_exposed_means_gives_way(self, catalog, couple):
        demand = demand_of(mission("a", km=4))
        dry = with_parameter(catalog, "assignment.bad_weather_share", 0.0)
        wet = with_parameter(catalog, "assignment.bad_weather_share", 0.20)
        portfolio = portfolio_of(*self.PORTFOLIO)
        bike_dry = shares(assign(dry, couple, demand, portfolio), "a")["bicycle"]
        bike_wet = shares(assign(wet, couple, demand, portfolio), "a")["bicycle"]
        assert bike_wet == pytest.approx(0.80 * bike_dry)

    def test_the_means_that_takes_over_is_marked_as_the_weather_one(self, catalog, couple):
        demand = demand_of(mission("a", km=4))
        wet = with_parameter(catalog, "assignment.bad_weather_share", 0.40)
        result = assign(wet, couple, demand, portfolio_of(*self.PORTFOLIO))
        reasons = {a.option_id: a.reason for a in result.allocations}
        assert reasons["pt_annual_urban_milano"] is AllocationReason.WEATHER

    def test_a_mission_the_weather_does_not_touch_is_left_alone(self, catalog, couple):
        demand = demand_of(mission("a", km=4, weather=Level.LOW))
        wet = with_parameter(catalog, "assignment.bad_weather_share", 0.40)
        dry = with_parameter(catalog, "assignment.bad_weather_share", 0.0)
        portfolio = portfolio_of(*self.PORTFOLIO)
        assert shares(assign(wet, couple, demand, portfolio), "a") == pytest.approx(
            shares(assign(dry, couple, demand, portfolio), "a")
        )

    def test_without_an_alternative_the_exposed_means_is_used_whatever_the_weather(
        self, catalog, couple
    ):
        demand = demand_of(mission("a", km=4))
        wet = with_parameter(catalog, "assignment.bad_weather_share", 0.40)
        result = assign(wet, couple, demand, portfolio_of(("bicycle", "p1")))
        assert shares(result, "a") == {"bicycle": pytest.approx(1)}


# --- the car two people need ---------------------------------------------------------------


class TestCarBusy:
    @staticmethod
    def household(*, driver: str | None = "p1"):
        return portfolio_of(
            ("car_medium_petrol", driver), "pt_ticket_urban_milano", "rail_regional_ticket"
        )

    @staticmethod
    def commutes(**kwargs):
        return demand_of(
            mission("c1", km=8, times=200, person_id="p1"),
            mission("c2", km=12, times=176, person_id="p2"),
            **kwargs,
        )

    def test_the_other_member_loses_the_car_on_the_days_both_need_one(self, catalog, couple):
        free = assign(catalog, couple, self.commutes(), self.household())
        busy = assign(catalog, couple, self.commutes(simultaneous_days=88), self.household())
        assert shares(free, "c2")["car_medium_petrol"] > 0.5
        # half of the occurrences of c2 (88 of 176) cannot use the car
        assert shares(busy, "c2")["car_medium_petrol"] <= 0.5 + 1e-9

    def test_the_driver_keeps_the_car(self, catalog, couple):
        free = assign(catalog, couple, self.commutes(), self.household())
        busy = assign(catalog, couple, self.commutes(simultaneous_days=88), self.household())
        assert shares(busy, "c1") == pytest.approx(shares(free, "c1"))

    def test_the_replacing_means_are_marked(self, catalog, couple):
        busy = assign(catalog, couple, self.commutes(simultaneous_days=88), self.household())
        reasons = {a.reason for a in busy.allocations if a.mission_id == "c2"}
        assert AllocationReason.CAR_BUSY in reasons
        assert all(
            a.reason is not AllocationReason.CAR_BUSY
            for a in busy.allocations
            if a.mission_id == "c1"
        )

    def test_if_it_is_needed_more_days_than_the_member_commutes_the_car_is_never_theirs(
        self, catalog, couple
    ):
        busy = assign(catalog, couple, self.commutes(simultaneous_days=1000), self.household())
        assert "car_medium_petrol" not in shares(busy, "c2")

    def test_two_cars_have_no_such_conflict(self, catalog, couple):
        two = portfolio_of(
            ("car_medium_petrol", "p1"), ("car_small_petrol", "p2"), "pt_ticket_urban_milano"
        )
        busy = assign(catalog, couple, self.commutes(simultaneous_days=88), two)
        assert all(a.reason is not AllocationReason.CAR_BUSY for a in busy.allocations)

    def test_it_is_the_declared_driver_who_keeps_the_car_not_the_first_adult(self, catalog, couple):
        busy = assign(
            catalog, couple, self.commutes(simultaneous_days=88), self.household(driver="p2")
        )
        free = assign(catalog, couple, self.commutes(), self.household(driver="p2"))
        assert shares(busy, "c2") == pytest.approx(shares(free, "c2"))
        assert shares(busy, "c1")["car_medium_petrol"] < shares(free, "c1")["car_medium_petrol"]

    def test_with_nobody_else_to_take_the_car_from_the_need_is_reported(self, catalog, couple):
        demand = demand_of(mission("c1", km=8, person_id="p1"), simultaneous_days=40)
        result = assign(catalog, couple, demand, self.household())
        assert any("due auto insieme" in note for note in result.notes)


# --- vehicles that serve one person at a time -----------------------------------------------


class TestSharedVehicles:
    @staticmethod
    def commutes():
        return demand_of(
            mission("c1", km=8, times=200, person_id="p1"),
            mission("c2", km=6, times=150, person_id="p2"),
        )

    def test_whoever_holds_a_car_uses_their_own(self, catalog, couple):
        portfolio = portfolio_of(("car_medium_petrol", "p1"), ("car_small_petrol", "p2"))
        result = assign(catalog, couple, self.commutes(), portfolio)
        assert "car_small_petrol" not in shares(result, "c1")
        assert "car_medium_petrol" not in shares(result, "c2")

    def test_for_a_trip_of_the_whole_household_the_best_car_is_chosen(self, catalog, couple):
        trip = demand_of(
            mission(
                "holiday",
                purpose=Purpose.HOLIDAY,
                km=450,
                times=2,
                person_id=None,
                passengers=2,
                luggage=LuggageLevel.LARGE,
            )
        )
        portfolio = portfolio_of(("car_medium_petrol", "p1"), ("car_small_petrol", "p2"))
        result = assign(catalog, couple, trip, portfolio)
        assert shares(result, "holiday") == {"car_medium_petrol": pytest.approx(1)}

    def test_a_vehicle_held_by_one_person_serves_nobody_else(self, catalog, couple):
        portfolio = portfolio_of(("e_bike", "p1"), "pt_ticket_urban_milano")
        result = assign(catalog, couple, self.commutes(), portfolio)
        assert "e_bike" in shares(result, "c1")
        assert "e_bike" not in shares(result, "c2")

    def test_one_household_bicycle_serves_one_person_the_one_who_would_ride_it_most(
        self, catalog, couple
    ):
        portfolio = portfolio_of("e_bike", "pt_ticket_urban_milano")
        result = assign(catalog, couple, self.commutes(), portfolio)
        users = {m for m in ("c1", "c2") if "e_bike" in shares(result, m)}
        assert users == {"c1"}  # 200 x 8 km against 150 x 6 km
        assert any("è uno solo" in note for note in result.notes)

    def test_two_bicycles_serve_two_people(self, catalog, couple):
        portfolio = Portfolio(
            id="test",
            name="test",
            items=[
                PortfolioItem(option_id="e_bike", quantity=2),
                PortfolioItem(option_id="pt_ticket_urban_milano"),
            ],
        )
        result = assign(catalog, couple, self.commutes(), portfolio)
        assert all("e_bike" in shares(result, m) for m in ("c1", "c2"))
        assert result.notes == []

    def test_a_household_trip_is_not_limited_by_who_holds_the_bicycle(self, catalog, couple):
        errand = demand_of(mission("shop", purpose=Purpose.SHOPPING, km=2, person_id=None))
        result = assign(catalog, couple, errand, portfolio_of(("e_bike", "p1"), "walking"))
        assert "e_bike" in shares(result, "shop")


# --- the demo households -------------------------------------------------------------------


@pytest.fixture(scope="module")
def assigned(catalog, households):
    """name -> (profile, demand, current portfolio with services, feasibility, assignment)."""
    result = {}
    for name, profile in households.items():
        demand = RuleBasedDemandEstimator(catalog).estimate(profile)
        current = CurrentCostEstimator(catalog).estimate(profile, demand).portfolio
        current = with_service_layer(current, catalog, profile, demand)
        feasibility = RuleBasedFeasibilityChecker(catalog).check(current, demand, profile)
        checked = CheckedPortfolio(portfolio=current, feasibility=feasibility)
        assignment = GeneralizedCostAssigner(catalog).assign(checked, demand, profile)
        result[name] = (profile, demand, current, feasibility, assignment)
    return result


NAMES = ["urban_single", "urban_couple", "family_two_cars", "peripheral_family"] + [
    "car_free_household"
]


class TestDemoHouseholds:
    @pytest.mark.parametrize("name", NAMES)
    def test_every_mission_is_served_and_its_shares_add_up_to_one(self, assigned, name):
        _, demand, portfolio, _, assignment = assigned[name]
        assert assignment.unserved_mission_ids == []
        in_portfolio = {item.option_id for item in portfolio.items}
        for mission_ in demand.missions:
            mine = shares(assignment, mission_.id)
            assert sum(mine.values()) == pytest.approx(1), (name, mission_.id)
            assert set(mine) <= in_portfolio

    @pytest.mark.parametrize("name", NAMES)
    def test_shares_are_valid_probabilities(self, assigned, name):
        for allocation in assigned[name][4].allocations:
            assert isinstance(allocation, MissionAllocation)
            assert 0 < allocation.share <= 1

    def test_a_family_with_children_takes_the_car_where_nothing_else_can_carry_them(self, assigned):
        assignment = assigned["family_two_cars"][4]
        assert shares(assignment, "school_escort") == {"car_medium_petrol": pytest.approx(1)}
        assert shares(assignment, "holiday") == {"car_medium_petrol": pytest.approx(1)}

    def test_a_household_without_a_car_uses_what_it_has(self, assigned):
        assignment = assigned["car_free_household"][4]
        used = {a.option_id for a in assignment.allocations}
        assert {"bicycle", "pt_annual_urban_milano"} <= used
        assert not any(o.startswith("car_") and o != "car_sharing_free2move_milano" for o in used)

    @pytest.mark.parametrize("name", ["urban_single", "urban_couple", "family_two_cars"])
    def test_the_modelled_car_mileage_is_of_the_order_of_the_declared_one(
        self, catalog, assigned, name
    ):
        # not a calibration: a guard against an assignment that drops the car or overuses it
        profile, demand, _, _, assignment = assigned[name]
        calculator = TripCalculator(catalog)
        by_id = {m.id: m for m in demand.missions}
        modelled = sum(
            by_id[a.mission_id].occurrences_per_year.value
            * a.share
            * calculator.trip(
                by_id[a.mission_id], catalog.option(a.option_id)
            ).usage.annual_km.expected
            for a in assignment.allocations
            if catalog.option(a.option_id).ownership is Ownership.OWNED
            and catalog.option(a.option_id).mode == "CAR"
        )
        declared = sum(_midpoint(v.annual_km) for v in profile.vehicles if "car" in v.option_id)
        assert 0.4 * declared < modelled < 1.6 * declared, (modelled, declared)


def _midpoint(answer) -> float:
    if answer.kind == "exact":
        return answer.exact
    return (answer.low + answer.high) / 2


# --- the endpoint --------------------------------------------------------------------------


class TestEndpoint:
    client = TestClient(app)

    def test_the_current_setup_comes_first_and_is_always_assigned(self, households):
        response = self.client.post(
            "/api/portfolios/assignment", json=households["urban_single"].model_dump(mode="json")
        )
        assert response.status_code == 200
        entries = response.json()
        assert entries[0]["portfolio"]["id"] == "current"
        assert entries[0]["assignment"] is not None
        assert len(entries) == 7

    def test_a_candidate_the_check_rejects_has_no_assignment(self, households):
        response = self.client.post(
            "/api/portfolios/assignment", json=households["family_two_cars"].model_dump(mode="json")
        )
        for entry in response.json():
            assert (entry["assignment"] is None) == (
                not entry["feasibility"]["is_feasible"] and entry["portfolio"]["id"] != "current"
            )
        assert any(entry["assignment"] is None for entry in response.json())

    def test_an_unknown_option_is_a_422(self, households):
        profile = households["urban_single"].model_dump(mode="json")
        profile["vehicles"][0]["option_id"] = "hoverboard"
        response = self.client.post("/api/portfolios/assignment", json=profile)
        assert response.status_code == 422
        assert "hoverboard" in response.json()["detail"]
