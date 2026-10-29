"""Demand estimator: formulas, provenance, adaptivity, and plausibility on the demo households."""

import pytest
from fastapi.testclient import TestClient

from app.data.loader import Catalog, load_demo_households
from app.main import app
from app.models import (
    Confidence,
    FamilyLogistic,
    Frequency,
    MobilityDemand,
    MobilityMission,
    NumericAnswer,
    Occupation,
    Purpose,
    ServiceKind,
    UserProfile,
    ValueSource,
)
from app.services.demand import RuleBasedDemandEstimator, UnknownOptionError


@pytest.fixture(scope="module")
def estimator(catalog: Catalog) -> RuleBasedDemandEstimator:
    return RuleBasedDemandEstimator(catalog)


@pytest.fixture(scope="module")
def households(catalog: Catalog) -> dict[str, UserProfile]:
    return load_demo_households(catalog)


def profile_of(households: dict[str, UserProfile], name: str) -> UserProfile:
    """A private copy that tests may modify."""
    return households[name].model_copy(deep=True)


def mission(demand: MobilityDemand, mission_id: str) -> MobilityMission:
    found = [m for m in demand.missions if m.id == mission_id]
    assert found, f"no mission {mission_id!r} in {[m.id for m in demand.missions]}"
    return found[0]


def note_fields(demand: MobilityDemand) -> set[tuple[str, str]]:
    return {(n.subject, n.field) for n in demand.assumptions}


class TestCommute:
    def test_formula_and_provenance_for_declared_answers(self, estimator, households):
        demand = estimator.estimate(profile_of(households, "urban_single"))
        commute = mission(demand, "commute_p1")
        # 5 days - 1 remote = 4 days/week x (220 working days / 5) = 176 days
        assert commute.occurrences_per_year.value == pytest.approx(176)
        assert commute.occurrences_per_year.low == pytest.approx(168)  # calendar range 210-230
        assert commute.occurrences_per_year.high == pytest.approx(184)
        assert commute.occurrences_per_year.source is ValueSource.INFERRED
        assert commute.occurrences_per_year.confidence is Confidence.MEDIUM  # limited by calendar
        assert commute.distance_km_one_way.value == 5
        assert commute.distance_km_one_way.source is ValueSource.DECLARED_EXACT
        assert commute.distance_km_one_way.confidence is Confidence.HIGH
        assert commute.annual_km == pytest.approx(176 * 2 * 5)

    def test_unknown_distance_falls_back_to_the_area_default_and_says_so(
        self, estimator, households
    ):
        profile = profile_of(households, "urban_single")
        profile.household.adults[0].work_or_study.one_way_distance_km = NumericAnswer()
        demand = estimator.estimate(profile)
        distance = mission(demand, "commute_p1").distance_km_one_way
        assert distance.value == 5  # CITY_CENTER default
        assert distance.source is ValueSource.STATISTICAL_ESTIMATE
        assert distance.confidence is Confidence.LOW  # the default is a placeholder
        assert ("p1", "commute_distance_km") in note_fields(demand)

    def test_band_answer_is_approximate_with_its_range(self, estimator, households):
        profile = profile_of(households, "urban_single")
        profile.household.adults[0].work_or_study.one_way_distance_km = NumericAnswer.between(8, 15)
        distance = mission(estimator.estimate(profile), "commute_p1").distance_km_one_way
        assert (distance.low, distance.value, distance.high) == (8, 11.5, 15)
        assert distance.source is ValueSource.DECLARED_APPROXIMATE
        assert distance.confidence is Confidence.MEDIUM

    def test_students_follow_the_school_calendar(self, estimator, households):
        profile = profile_of(households, "urban_single")
        adult = profile.household.adults[0]
        adult.occupation = Occupation.STUDENT
        adult.work_or_study.remote_days_per_week = NumericAnswer.of(0)
        demand = estimator.estimate(profile)
        study = mission(demand, "study_p1")
        assert study.purpose is Purpose.STUDY
        assert study.occurrences_per_year.value == pytest.approx(5 * 200 / 5)

    def test_retired_adults_do_not_commute(self, estimator, households):
        profile = profile_of(households, "urban_single")
        profile.household.adults[0].occupation = Occupation.RETIRED
        demand = estimator.estimate(profile)
        assert not [m for m in demand.missions if m.purpose in (Purpose.COMMUTE, Purpose.STUDY)]

    def test_working_entirely_from_home_means_no_commute(self, estimator, households):
        profile = profile_of(households, "urban_single")
        work = profile.household.adults[0].work_or_study
        work.days_per_week = NumericAnswer.of(3)
        work.remote_days_per_week = NumericAnswer.of(3)
        demand = estimator.estimate(profile)
        assert not [m for m in demand.missions if m.purpose is Purpose.COMMUTE]

    def test_more_remote_days_than_work_days_never_goes_negative(self, estimator, households):
        profile = profile_of(households, "urban_single")
        work = profile.household.adults[0].work_or_study
        work.days_per_week = NumericAnswer.of(2)
        work.remote_days_per_week = NumericAnswer.of(4)
        assert not [m for m in estimator.estimate(profile).missions if m.purpose is Purpose.COMMUTE]

    def test_time_critical_commutes_have_low_duration_tolerance(self, estimator, households):
        demand = estimator.estimate(profile_of(households, "urban_couple"))
        assert mission(demand, "commute_p1").time_critical  # p1 declared time critical
        assert mission(demand, "commute_p1").duration_tolerance.value == "LOW"
        assert not mission(demand, "commute_p2").time_critical

    def test_each_working_adult_gets_their_own_commute(self, estimator, households):
        demand = estimator.estimate(profile_of(households, "urban_couple"))
        assert {m.person_id for m in demand.missions if m.purpose is Purpose.COMMUTE} == {
            "p1",
            "p2",
        }


class TestSchoolEscort:
    def test_no_children_no_escort(self, estimator, households):
        demand = estimator.estimate(profile_of(households, "urban_couple"))
        assert not [m for m in demand.missions if m.purpose is Purpose.SCHOOL_ESCORT]

    def test_declared_escort_uses_every_school_day(self, estimator, households):
        demand = estimator.estimate(profile_of(households, "family_two_cars"))
        escort = mission(demand, "school_escort")
        assert escort.occurrences_per_year.value == pytest.approx(200)
        assert escort.passengers == 3  # one adult + two children
        assert escort.children == 2
        assert escort.time_critical
        assert ("household", "school_escort") not in note_fields(demand)

    def test_undeclared_escort_is_a_wide_low_confidence_default(self, estimator, households):
        profile = profile_of(households, "urban_couple")
        profile.household.n_children = 1
        assert FamilyLogistic.SCHOOL_ESCORT not in profile.household.family_logistics
        demand = estimator.estimate(profile)
        escort = mission(demand, "school_escort")
        assert escort.occurrences_per_year.value == pytest.approx(100)  # half of 200 days
        assert escort.occurrences_per_year.low == pytest.approx(0)
        assert escort.occurrences_per_year.high == pytest.approx(205)
        assert escort.occurrences_per_year.confidence is Confidence.LOW
        assert ("household", "school_escort") in note_fields(demand)


class TestLocalAndOccasionalTrips:
    def test_local_trips_scale_with_adults_and_split_into_shopping_and_leisure(
        self, estimator, households
    ):
        demand = estimator.estimate(profile_of(households, "family_two_cars"))
        shopping = mission(demand, "shopping")
        leisure = mission(demand, "local_leisure")
        # SUBURBAN default 4 trips/week/adult x 2 adults x 48 weeks, split 50/50
        assert shopping.occurrences_per_year.value == pytest.approx(192)
        assert leisure.occurrences_per_year.value == pytest.approx(192)
        assert shopping.passengers == 1
        assert leisure.passengers == 4  # the whole family
        assert shopping.person_id is None

    def test_weekend_and_holiday_use_declared_answers(self, estimator, households):
        demand = estimator.estimate(profile_of(households, "family_two_cars"))
        weekend = mission(demand, "weekend")
        assert weekend.occurrences_per_year.value == 25
        assert weekend.distance_km_one_way.value == 70
        assert weekend.occurrences_per_year.source is ValueSource.DECLARED_EXACT
        assert weekend.days_away == 0
        holiday = mission(demand, "holiday")
        assert holiday.occurrences_per_year.value == 2
        assert holiday.distance_km_one_way.value == 500
        assert holiday.days_away == 10
        assert holiday.luggage.value == "LARGE"
        assert holiday.passengers == 4

    def test_unanswered_occasional_trips_use_defaults_and_are_noted(self, estimator, households):
        profile = profile_of(households, "urban_single")
        demand = estimator.estimate(profile)  # urban_single declares none of these
        long_weekend = mission(demand, "long_weekend")
        assert long_weekend.purpose is Purpose.LONG_DISTANCE
        assert long_weekend.occurrences_per_year.value == 3
        assert long_weekend.occurrences_per_year.source is ValueSource.STATISTICAL_ESTIMATE
        assert ("household", "long_weekends_per_year") in note_fields(demand)

    def test_declaring_none_removes_the_mission_with_high_confidence(self, estimator, households):
        profile = profile_of(households, "family_two_cars")
        profile.other_mobility.holiday_trips_per_year = NumericAnswer.of(0)
        demand = estimator.estimate(profile)
        assert not [m for m in demand.missions if m.purpose is Purpose.HOLIDAY]
        assert ("household", "holiday_trips_per_year") not in note_fields(demand)

    def test_a_band_answer_carries_its_range(self, estimator, households):
        profile = profile_of(households, "urban_single")
        profile.other_mobility.weekend_trips_per_year = NumericAnswer.between(9, 20)
        trips = mission(estimator.estimate(profile), "weekend").occurrences_per_year
        assert (trips.low, trips.value, trips.high) == (9, 14.5, 20)
        assert trips.source is ValueSource.DECLARED_APPROXIMATE


class TestServiceUsage:
    def test_declared_usage_is_reported_not_added_to_demand(self, estimator, households):
        base = estimator.estimate(profile_of(households, "car_free_household"))
        usage = {u.service: u for u in base.current_service_usage}
        assert usage[ServiceKind.TAXI].annual_amount.value == 15
        assert usage[ServiceKind.TAXI].annual_amount.source is ValueSource.DECLARED_EXACT
        assert usage[ServiceKind.CAR_SHARING].annual_amount.value == 12
        assert usage[ServiceKind.AIR].annual_amount.value == 2
        assert usage[ServiceKind.CAR_RENTAL].unit == "days"

        # Doubling the declared taxi trips must not change the missions (no double counting).
        profile = profile_of(households, "car_free_household")
        profile.other_mobility.taxi_trips_per_year = NumericAnswer.of(30)
        more = estimator.estimate(profile)
        assert more.total_annual_km == base.total_annual_km

    def test_all_services_are_always_listed(self, estimator, households):
        demand = estimator.estimate(profile_of(households, "urban_single"))
        assert {u.service for u in demand.current_service_usage} == set(ServiceKind)

    def test_unanswered_usage_is_a_noted_default(self, estimator, households):
        demand = estimator.estimate(profile_of(households, "urban_single"))
        rail = next(u for u in demand.current_service_usage if u.service is ServiceKind.RAIL)
        assert rail.annual_amount.source is ValueSource.STATISTICAL_ESTIMATE
        assert ("household", "rail_trips_per_year") in note_fields(demand)


class TestSimultaneousCarNeed:
    def test_declared_frequency_maps_to_days(self, estimator, households):
        demand = estimator.estimate(profile_of(households, "family_two_cars"))
        days = demand.simultaneous_car_need_days
        assert days is not None
        assert (days.low, days.value, days.high) == (60, 100, 150)
        assert days.source is ValueSource.DECLARED_APPROXIMATE

    @pytest.mark.parametrize(
        ("frequency", "expected"),
        [
            (Frequency.NEVER, 0),
            (Frequency.RARELY, 10),
            (Frequency.SOMETIMES, 40),
            (Frequency.OFTEN, 100),
            (Frequency.ALMOST_DAILY, 200),
        ],
    )
    def test_every_answer_has_a_value(self, estimator, households, frequency, expected):
        profile = profile_of(households, "family_two_cars")
        profile.household.simultaneous_car_need = frequency
        days = estimator.estimate(profile).simultaneous_car_need_days
        assert days is not None
        assert days.value == expected

    def test_two_cars_unanswered_is_a_wide_low_confidence_default(self, estimator, households):
        profile = profile_of(households, "family_two_cars")
        profile.household.simultaneous_car_need = None
        demand = estimator.estimate(profile)
        days = demand.simultaneous_car_need_days
        assert days is not None
        assert (days.low, days.value, days.high) == (10, 40, 100)
        assert days.confidence is Confidence.LOW
        assert ("household", "simultaneous_car_need") in note_fields(demand)

    def test_one_car_and_no_answer_means_unknown(self, estimator, households):
        demand = estimator.estimate(profile_of(households, "urban_single"))
        assert demand.simultaneous_car_need_days is None


class TestDeclaredMissionsAndErrors:
    def test_declared_missions_replace_estimates_of_the_same_purpose(self, estimator, households):
        profile = profile_of(households, "urban_single")
        base = estimator.estimate(profile)
        declared = mission(base, "weekend").model_copy(
            update={"id": "my_weekend", "person_id": None}
        )
        profile.declared_missions = [declared]
        demand = estimator.estimate(profile)
        weekends = [m for m in demand.missions if m.purpose is Purpose.WEEKEND]
        assert [m.id for m in weekends] == ["my_weekend"]
        assert any(n.field == "declared_missions.WEEKEND" for n in demand.assumptions)

    def test_unknown_catalogue_option_is_rejected(self, estimator, households):
        profile = profile_of(households, "urban_single")
        profile.vehicles[0].option_id = "flying_car"
        with pytest.raises(UnknownOptionError, match="flying_car"):
            estimator.estimate(profile)


class TestPlausibility:
    """Regression values on the demo households (CLAUDE.md section 32)."""

    EXPECTED_KM = {
        "urban_single": 7_580,
        "urban_couple": 13_940,
        "family_two_cars": 21_740,
        "peripheral_family": 31_260,
        "car_free_household": 10_148,
    }

    @pytest.mark.parametrize("name", list(EXPECTED_KM))
    def test_total_annual_km(self, estimator, households, name):
        demand = estimator.estimate(profile_of(households, name))
        assert demand.total_annual_km == pytest.approx(self.EXPECTED_KM[name], rel=1e-3)

    def test_family_km_is_in_line_with_what_its_cars_declare(self, estimator, households):
        # family_two_cars declares 17,000-25,000 km across two cars; the estimated needs (21,740)
        # should land in the same range - a sanity check that defaults are not wildly off.
        demand = estimator.estimate(profile_of(households, "family_two_cars"))
        assert 17_000 <= demand.total_annual_km <= 25_000

    def test_commuting_is_not_the_only_need(self, estimator, households):
        demand = estimator.estimate(profile_of(households, "family_two_cars"))
        by_purpose = demand.annual_km_by_purpose()
        assert by_purpose[Purpose.COMMUTE] < demand.total_annual_km
        assert (
            by_purpose[Purpose.HOLIDAY] > 0
        )  # 1,000 km of holidays differ from 1,000 of commuting

    def test_every_estimate_has_a_consistent_range(self, estimator, households):
        for name in households:
            demand = estimator.estimate(profile_of(households, name))
            for item in demand.missions:
                for value in (item.occurrences_per_year, item.distance_km_one_way):
                    assert value.low <= value.value <= value.high, (name, item.id)

    def test_estimation_is_deterministic(self, estimator, households):
        profile = profile_of(households, "peripheral_family")
        assert estimator.estimate(profile) == estimator.estimate(profile)

    def test_a_missing_answer_always_lowers_confidence(self, estimator, households):
        profile = profile_of(households, "family_two_cars")
        declared = mission(estimator.estimate(profile), "weekend")
        profile.other_mobility.weekend_trips_per_year = NumericAnswer()
        guessed = mission(estimator.estimate(profile), "weekend")
        order = {Confidence.LOW: 0, Confidence.MEDIUM: 1, Confidence.HIGH: 2}
        assert (
            order[guessed.occurrences_per_year.confidence]
            < order[declared.occurrences_per_year.confidence]
        )


def test_estimate_demand_endpoint(households):
    with TestClient(app) as client:
        body = client.post(
            "/api/profile/estimate-demand",
            json=households["family_two_cars"].model_dump(mode="json"),
        )
        assert body.status_code == 200
        data = body.json()
        assert data["profile_id"] == "family_two_cars"
        assert {m["purpose"] for m in data["missions"]} >= {"COMMUTE", "HOLIDAY", "SCHOOL_ESCORT"}
        assert data["simultaneous_car_need_days"]["value"] == 100

        broken = households["urban_single"].model_dump(mode="json")
        broken["vehicles"][0]["option_id"] = "flying_car"
        response = client.post("/api/profile/estimate-demand", json=broken)
        assert response.status_code == 422
        assert "flying_car" in response.json()["detail"]
