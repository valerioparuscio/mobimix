"""Rush-hour traffic and the cost of taking a car to the destination (docs/methodology.md, 11).

A car in town is slower when the trip starts in the morning or evening rush, and the car left at
the workplace (or at the shops) pays for parking and Area C. Both belong to the use of the car,
and both were missing: the model made the car look faster and cheaper than the pass it was
compared with, so a city commuter was told to give the pass up.
"""

import pytest

from app.data.loader import Catalog, load_demo_households
from app.models import (
    AreaType,
    AssignmentRules,
    Confidence,
    Estimated,
    MobilityMission,
    Mode,
    Occupation,
    Purpose,
    Scenario,
    TimeBand,
    UserProfile,
    ValueSource,
)
from app.services.costs.model import FIXED_COMPONENTS, USAGE_COMPONENTS, TcoCostModel
from app.services.demand import RuleBasedDemandEstimator
from app.services.optimizer import TripCalculator
from app.services.scenarios import apply_scenario


def mission(
    *,
    purpose: Purpose = Purpose.COMMUTE,
    km: float = 8,
    window: TimeBand = TimeBand.ANY,
    car_cost: float | None = None,
    passengers: int = 1,
) -> MobilityMission:
    return MobilityMission(
        id="m",
        person_id="p1",
        purpose=purpose,
        occurrences_per_year=Estimated.exact(100),
        distance_km_one_way=Estimated.exact(km),
        passengers=passengers,
        start_time_window=window,
        destination_car_cost=None if car_cost is None else Estimated.exact(car_cost),
    )


@pytest.fixture(scope="module")
def households(catalog: Catalog) -> dict[str, UserProfile]:
    return load_demo_households(catalog)


# --- the rush hours ------------------------------------------------------------------------


class TestRushHour:
    def test_a_car_in_town_is_slower_in_the_rush_hours(self, catalog):
        calculator = TripCalculator(catalog)
        car = catalog.option("car_medium_petrol")
        factor = catalog.value("assignment.peak_speed_factor.urban")
        normal = calculator.leg_hours(car, 8, TimeBand.MIDDAY)
        peak = calculator.leg_hours(car, 8, TimeBand.MORNING_PEAK)
        overhead = car.fixed_time_min_per_trip.value / 60
        assert normal == pytest.approx(8 / 22 + overhead)
        assert peak == pytest.approx(8 / (22 * factor) + overhead)
        assert peak > normal

    def test_both_rushes_count_and_no_other_hour(self, catalog):
        calculator = TripCalculator(catalog)
        car = catalog.option("car_medium_petrol")
        peak = calculator.leg_hours(car, 8, TimeBand.MORNING_PEAK)
        assert calculator.leg_hours(car, 8, TimeBand.EVENING_PEAK) == peak
        for window in (TimeBand.ANY, TimeBand.MIDDAY, TimeBand.AFTERNOON, TimeBand.NIGHT):
            assert calculator.leg_hours(car, 8, window) < peak

    def test_a_trip_without_a_start_time_is_not_slowed_down(self, catalog):
        car = catalog.option("car_medium_petrol")
        assert TripCalculator(catalog).leg_hours(car, 8) == TripCalculator(catalog).leg_hours(
            car, 8, TimeBand.ANY
        )

    @pytest.mark.parametrize(
        "option_id", ["pt_annual_urban_milano", "bicycle", "e_bike", "rail_regional_ticket"]
    )
    def test_what_does_not_queue_in_traffic_keeps_its_speed(self, catalog, option_id):
        calculator = TripCalculator(catalog)
        option = catalog.option(option_id)
        assert calculator.leg_hours(option, 12, TimeBand.MORNING_PEAK) == (
            calculator.leg_hours(option, 12, TimeBand.MIDDAY)
        )

    def test_a_taxi_stands_in_the_same_queue_as_a_car(self, catalog):
        calculator = TripCalculator(catalog)
        taxi = catalog.option("taxi_milano")
        assert taxi.mode is Mode.TAXI
        assert calculator.leg_hours(taxi, 8, TimeBand.MORNING_PEAK) > calculator.leg_hours(
            taxi, 8, TimeBand.MIDDAY
        )

    def test_a_motorcycle_loses_only_the_share_the_table_gives_it(self, catalog):
        calculator = TripCalculator(catalog)
        moto = catalog.option("motorcycle")
        exposure = catalog.assignment_rules.congestion_exposure[Mode.MOTORCYCLE]
        factor = catalog.value("assignment.peak_speed_factor.urban")
        speed = moto.average_speed_kmh["URBAN"].value
        overhead = moto.fixed_time_min_per_trip.value / 60 if moto.fixed_time_min_per_trip else 0
        assert 0 < exposure < 1
        assert calculator.leg_hours(moto, 8, TimeBand.MORNING_PEAK) == pytest.approx(
            8 / (speed * (1 - exposure * (1 - factor))) + overhead
        )

    def test_a_long_trip_is_not_slowed_down_and_a_regional_one_less_than_a_town_one(self, catalog):
        calculator = TripCalculator(catalog)
        car = catalog.option("car_medium_petrol")
        assert calculator.leg_hours(car, 300, TimeBand.MORNING_PEAK) == (
            calculator.leg_hours(car, 300, TimeBand.MIDDAY)
        )
        regional = catalog.value("assignment.peak_speed_factor.regional")
        urban = catalog.value("assignment.peak_speed_factor.urban")
        assert urban < regional <= 1

    def test_a_car_at_the_morning_peak_is_not_faster_than_the_pass_in_the_city(self, catalog):
        """The case that prompted it: an 8 km commute in Milan at 8 o'clock."""
        calculator = TripCalculator(catalog)
        car = catalog.option("car_medium_petrol")
        pass_ = catalog.option("pt_annual_urban_milano")
        assert calculator.leg_hours(car, 8, TimeBand.MIDDAY) < calculator.leg_hours(
            pass_, 8, TimeBand.MIDDAY
        )  # off the peak the car wins on time
        assert calculator.leg_hours(car, 8, TimeBand.MORNING_PEAK) >= (
            0.95 * calculator.leg_hours(pass_, 8, TimeBand.MORNING_PEAK)
        )  # at the peak it no longer does, give or take the placeholders

    def test_the_commute_of_a_demo_household_starts_in_the_rush(self, catalog, households):
        demand = RuleBasedDemandEstimator(catalog).estimate(households["urban_couple"])
        commutes = [m for m in demand.missions if m.purpose is Purpose.COMMUTE]
        assert commutes
        assert all(m.start_time_window in catalog.assignment_rules.peak_windows for m in commutes)

    def test_the_assignment_rules_refuse_a_share_above_one(self, catalog):
        rules = catalog.assignment_rules.model_dump()
        rules["congestion_exposure"] = {Mode.CAR: 1.5}
        with pytest.raises(ValueError, match="between 0 and 1"):
            AssignmentRules.model_validate(rules)


# --- the car at the destination ------------------------------------------------------------


class TestDestinationCharges:
    def charges(self, catalog, option_id, **kwargs):
        trip = TripCalculator(catalog).trip(
            mission(car_cost=kwargs.pop("car_cost", 6.0), **kwargs), catalog.option(option_id)
        )
        return trip.usage.annual_destination_charges.expected

    @pytest.mark.parametrize("option_id", ["car_small_petrol", "car_diesel", "car_rental_daily"])
    def test_a_car_pays_it_once_per_occurrence(self, catalog, option_id):
        assert self.charges(catalog, option_id) == pytest.approx(6.0)

    def test_two_cars_pay_twice(self, catalog):
        assert self.charges(catalog, "car_medium_petrol", passengers=6) == pytest.approx(12.0)

    @pytest.mark.parametrize(
        "option_id",
        [
            "car_sharing_free2move_milano",  # parks free in town, enters Area C free
            "taxi_milano",
            "motorcycle",
            "scooter_125",
            "pt_annual_urban_milano",
            "bicycle",
            "rail_regional_ticket",
        ],
    )
    def test_the_others_do_not(self, catalog, option_id):
        assert self.charges(catalog, option_id) == 0.0

    def test_a_mission_without_the_cost_has_none(self, catalog):
        trip = TripCalculator(catalog).trip(mission(), catalog.option("car_medium_petrol"))
        assert trip.usage.annual_destination_charges.expected == 0.0

    def test_the_range_of_the_cost_is_kept(self, catalog):
        cost = Estimated(
            value=5,
            low=0,
            high=15,
            source=ValueSource.STATISTICAL_ESTIMATE,
            confidence=Confidence.LOW,
        )
        one = mission(car_cost=5).model_copy(update={"destination_car_cost": cost})
        trip = TripCalculator(catalog).trip(one, catalog.option("car_medium_petrol"))
        charges = trip.usage.annual_destination_charges
        assert (charges.low, charges.expected, charges.high) == (0, 5, 15)

    def test_it_is_a_cost_of_using_the_car_not_of_owning_it(self, catalog):
        car = catalog.option("car_medium_petrol")
        trip = TripCalculator(catalog).trip(mission(car_cost=6.0), car)
        model = TcoCostModel(catalog)
        assert "destination_charges" in USAGE_COMPONENTS
        assert "destination_charges" not in FIXED_COMPONENTS
        used = model.calculate(car, trip.usage, only=USAGE_COMPONENTS)
        held = model.calculate(car, trip.usage, only=FIXED_COMPONENTS)
        assert any(line.label == "destination_charges" for line in used.lines)
        assert all(line.label != "destination_charges" for line in held.lines)

    def test_it_raises_the_cost_of_a_trip_by_exactly_its_amount(self, catalog):
        calculator = TripCalculator(catalog)
        car = catalog.option("car_medium_petrol")
        without = calculator.trip(mission(), car).usage_cost
        with_charge = calculator.trip(mission(car_cost=6.0), car).usage_cost
        assert with_charge - without == pytest.approx(6.0)

    def test_an_option_that_does_not_park_ignores_the_amount_in_the_cost_model(self, catalog):
        taxi = catalog.option("taxi_milano")
        trip = TripCalculator(catalog).trip(mission(car_cost=6.0), taxi)
        assert TripCalculator(catalog).trip(mission(), taxi).usage_cost == pytest.approx(
            trip.usage_cost
        )


# --- the demand that carries it ------------------------------------------------------------


class TestEstimatedCosts:
    def estimate(self, catalog, profile):
        return RuleBasedDemandEstimator(catalog).estimate(profile)

    def test_a_worker_gets_the_typical_cost_of_the_area(self, catalog, households):
        profile = households["urban_couple"]
        area = profile.household.location.area_type
        typical = catalog.defaults_for(area).values["workplace_car_cost_per_day"]
        demand = self.estimate(catalog, profile)
        for commute in (m for m in demand.missions if m.purpose is Purpose.COMMUTE):
            cost = commute.destination_car_cost
            assert cost is not None
            assert (cost.value, cost.low, cost.high) == (typical.value, typical.lo, typical.hi)
            assert cost.source is ValueSource.STATISTICAL_ESTIMATE
            assert cost.confidence is Confidence.LOW

    def test_it_is_told_to_the_user(self, catalog, households):
        demand = self.estimate(catalog, households["urban_couple"])
        notes = [n for n in demand.assumptions if n.field == "workplace_car_cost"]
        assert {n.subject for n in notes} == {"p1", "p2"}
        assert all("Area C" in n.message and "affidabilità bassa" in n.message for n in notes)

    def test_a_student_pays_nothing_at_school(self, catalog, households):
        profile = households["urban_couple"].model_copy(deep=True)
        profile.household.adults[0].occupation = Occupation.STUDENT
        demand = self.estimate(catalog, profile)
        study = next(m for m in demand.missions if m.purpose is Purpose.STUDY)
        assert study.destination_car_cost is None

    def test_shopping_and_leisure_in_town_pay_for_parking_too(self, catalog, households):
        demand = self.estimate(catalog, households["urban_couple"])
        local = [
            m for m in demand.missions if m.purpose in (Purpose.SHOPPING, Purpose.LOCAL_LEISURE)
        ]
        assert len(local) == 2
        typical = catalog.defaults_for(AreaType.URBAN).values["local_trip_car_cost"]
        assert all(m.destination_car_cost.value == typical.value for m in local)

    def test_a_weekend_away_pays_nothing_at_the_destination(self, catalog, households):
        demand = self.estimate(catalog, households["urban_couple"])
        away = [
            m
            for m in demand.missions
            if m.purpose in (Purpose.WEEKEND, Purpose.LONG_DISTANCE, Purpose.HOLIDAY)
        ]
        assert away
        assert all(m.destination_car_cost is None for m in away)

    def test_the_further_from_the_centre_the_less_it_costs(self, catalog):
        by_area = {
            area: catalog.defaults_for(area).values["workplace_car_cost_per_day"].value
            for area in (
                AreaType.CITY_CENTER,
                AreaType.URBAN,
                AreaType.SUBURBAN,
                AreaType.PERIPHERAL,
            )
        }
        values = list(by_area.values())
        assert values == sorted(values, reverse=True)
        assert by_area[AreaType.PERIPHERAL] == 0

    def test_nothing_is_said_where_there_is_nothing_to_pay(self, catalog, households):
        profile = households["peripheral_family"]
        demand = self.estimate(catalog, profile)
        assert not [n for n in demand.assumptions if n.field == "workplace_car_cost"]

    def test_the_ranges_are_ordered(self, catalog):
        for area in AreaType:
            for key in ("workplace_car_cost_per_day", "local_trip_car_cost"):
                parameter = catalog.defaults_for(area).values[key]
                assert 0 <= parameter.lo <= parameter.value <= parameter.hi


# --- the parking what-if moves them too ----------------------------------------------------


class TestParkingScenario:
    def test_free_parking_is_free_at_the_destination_too(self, catalog, households):
        changed, profile = apply_scenario(
            catalog, households["urban_couple"], Scenario(parking_cost_change=-1.0)
        )
        demand = RuleBasedDemandEstimator(changed).estimate(profile)
        costs = [m.destination_car_cost for m in demand.missions if m.destination_car_cost]
        assert costs
        assert all(cost.value == 0 for cost in costs)

    def test_dearer_parking_scales_them(self, catalog, households):
        profile = households["urban_couple"]
        changed, scenario_profile = apply_scenario(
            catalog, profile, Scenario(parking_cost_change=0.5)
        )
        before = RuleBasedDemandEstimator(catalog).estimate(profile)
        after = RuleBasedDemandEstimator(changed).estimate(scenario_profile)
        for old, new in zip(before.missions, after.missions, strict=True):
            if old.destination_car_cost:
                assert new.destination_car_cost.value == pytest.approx(
                    1.5 * old.destination_car_cost.value
                )
