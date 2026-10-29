"""Who can, and who will, ride a bicycle, an e-bike or a scooter (docs/methodology.md, 10-11).

The model used to give every adult a bicycle and an e-bike, and to drop them on 15% of the days
for the weather, the same for everybody. Not everyone can ride, or wants to, and rain is a reason
to leave the bike at home for some more than for others: an adult says so in the questionnaire
(`NO_TWO_WHEELS`, `weather_tolerance`) and the feasibility check, the portfolio generator and the
assignment take it into account.
"""

from dataclasses import replace

import pytest

from app.data.loader import Catalog, load_demo_households
from app.models import (
    AccessibilityConstraint,
    CheckedPortfolio,
    Estimated,
    Level,
    MobilityDemand,
    MobilityMission,
    ModeAssignment,
    Person,
    Portfolio,
    PortfolioItem,
    Purpose,
    UserProfile,
    WeatherTolerance,
)
from app.services.demand import RuleBasedDemandEstimator
from app.services.feasibility import RuleBasedFeasibilityChecker
from app.services.optimizer import GeneralizedCostAssigner
from app.services.pipeline import analyze
from app.services.portfolios import RuleBasedPortfolioGenerator

NO_TWO_WHEELS = AccessibilityConstraint.NO_TWO_WHEELS
TWO_WHEELERS = ("bicycle", "e_bike", "scooter_125", "motorcycle")


@pytest.fixture(scope="module")
def households(catalog: Catalog) -> dict[str, UserProfile]:
    return load_demo_households(catalog)


@pytest.fixture
def couple(households) -> UserProfile:
    return households["urban_couple"].model_copy(deep=True)


def commute(
    mission_id: str = "m", *, person_id: str | None = "p1", km: float = 4
) -> MobilityMission:
    return MobilityMission(
        id=mission_id,
        person_id=person_id,
        purpose=Purpose.COMMUTE,
        occurrences_per_year=Estimated.exact(100),
        distance_km_one_way=Estimated.exact(km),
        weather_sensitivity=Level.MEDIUM,
    )


def portfolio_of(*option_ids: str) -> Portfolio:
    return Portfolio(id="test", name="test", items=[PortfolioItem(option_id=o) for o in option_ids])


def feasible_options(catalog, profile, missions, portfolio) -> dict[str, list[str]]:
    demand = MobilityDemand(profile_id="test", missions=list(missions))
    return RuleBasedFeasibilityChecker(catalog).check(portfolio, demand, profile).options_by_mission


def bicycle_share(catalog, profile, mission) -> float:
    """Share of the missions the bicycle serves when the household also has a transit pass."""
    portfolio = Portfolio(
        id="test",
        name="test",
        items=[
            PortfolioItem(option_id="bicycle"),
            PortfolioItem(option_id="pt_annual_urban_milano"),
        ],
    )
    demand = MobilityDemand(profile_id="test", missions=[mission])
    feasibility = RuleBasedFeasibilityChecker(catalog).check(portfolio, demand, profile)
    checked = CheckedPortfolio(portfolio=portfolio, feasibility=feasibility)
    result: ModeAssignment = GeneralizedCostAssigner(catalog).assign(checked, demand, profile)
    return {a.option_id: a.share for a in result.allocations}["bicycle"]


def with_parameter(catalog: Catalog, parameter_id: str, value: float) -> Catalog:
    parameter = catalog.parameters[parameter_id].model_copy(update={"value": value})
    return replace(catalog, parameters={**catalog.parameters, parameter_id: parameter})


def person(profile: UserProfile, person_id: str) -> Person:
    return next(p for p in profile.household.adults if p.id == person_id)


# --- who may use a two-wheeler -------------------------------------------------------------


class TestNoTwoWheels:
    def test_rules_out_every_two_wheeler_for_the_persons_own_trips(self, catalog, couple):
        person(couple, "p1").accessibility_constraints = [NO_TWO_WHEELS]
        portfolio = portfolio_of(*TWO_WHEELERS, "pt_ticket_urban_milano")
        options = feasible_options(
            catalog,
            couple,
            [commute("m1", person_id="p1"), commute("m2", person_id="p2")],
            portfolio,
        )
        assert options["m1"] == ["pt_ticket_urban_milano"]
        assert {"bicycle", "e_bike"} <= set(options["m2"])  # the other adult may ride

    def test_a_trip_of_the_whole_household_takes_the_constraint_of_every_adult(
        self, catalog, couple
    ):
        person(couple, "p2").accessibility_constraints = [NO_TWO_WHEELS]
        options = feasible_options(
            catalog,
            couple,
            [commute("m", person_id=None)],
            portfolio_of("bicycle", "e_bike", "pt_ticket_urban_milano"),
        )
        assert options["m"] == ["pt_ticket_urban_milano"]


class TestCandidates:
    @pytest.fixture
    def generate(self, catalog, couple):
        def _generate(edit=None) -> list[Portfolio]:
            profile = couple.model_copy(deep=True)
            if edit:
                edit(profile)
            demand = RuleBasedDemandEstimator(catalog).estimate(profile)
            return RuleBasedPortfolioGenerator(catalog).generate(profile, demand)

        return _generate

    @staticmethod
    def with_addon(candidates, word):
        return [c.id for c in candidates if word in c.id]

    def test_the_couple_is_offered_both_by_default(self, generate):
        candidates = generate()
        assert self.with_addon(candidates, "e_bike")
        assert self.with_addon(candidates, "scooter")

    def test_nobody_who_rides_two_wheels_means_neither_e_bike_nor_scooter(self, generate):
        def nobody_rides(profile):
            for adult in profile.household.adults:
                adult.accessibility_constraints = [NO_TWO_WHEELS]

        candidates = generate(nobody_rides)
        assert self.with_addon(candidates, "e_bike") == []
        assert self.with_addon(candidates, "scooter") == []

    def test_one_adult_who_can_ride_is_enough(self, generate):
        def one_rides(profile):
            profile.household.adults[0].accessibility_constraints = [NO_TWO_WHEELS]

        candidates = generate(one_rides)
        assert self.with_addon(candidates, "e_bike")
        assert self.with_addon(candidates, "scooter")

    def test_a_wheelchair_user_household_is_not_offered_an_e_bike(self, generate):
        def wheelchairs(profile):
            for adult in profile.household.adults:
                adult.accessibility_constraints = [AccessibilityConstraint.WHEELCHAIR]

        assert self.with_addon(generate(wheelchairs), "e_bike") == []

    def test_someone_who_cannot_cycle_may_still_ride_a_scooter(self, generate):
        def nobody_cycles(profile):
            for adult in profile.household.adults:
                adult.accessibility_constraints = [AccessibilityConstraint.CANNOT_CYCLE]

        candidates = generate(nobody_cycles)
        assert self.with_addon(candidates, "e_bike") == []
        assert self.with_addon(candidates, "scooter")


# --- the weather ---------------------------------------------------------------------------


class TestWeatherTolerance:
    def test_a_fair_weather_rider_gives_up_the_bicycle_on_the_bad_weather_days(
        self, catalog, couple
    ):
        dry = with_parameter(catalog, "assignment.bad_weather_share", 0.0)
        wet = with_parameter(catalog, "assignment.bad_weather_share_fair_weather_only", 0.40)
        mission = commute()
        bike_dry = bicycle_share(dry, couple, mission)  # p1 has not answered: no bad weather here
        person(couple, "p1").weather_tolerance = WeatherTolerance.FAIR_WEATHER_ONLY
        assert bicycle_share(wet, couple, mission) == pytest.approx(0.60 * bike_dry)

    def test_the_more_a_person_minds_the_weather_the_less_the_bicycle_is_used(
        self, catalog, couple
    ):
        mission = commute()

        def share(tolerance):
            person(couple, "p1").weather_tolerance = tolerance
            return bicycle_share(catalog, couple, mission)

        any_weather = share(WeatherTolerance.ANY_WEATHER)
        unanswered = share(None)
        fair_only = share(WeatherTolerance.FAIR_WEATHER_ONLY)
        assert any_weather > unanswered > fair_only

    def test_an_unanswered_tolerance_is_the_average_share_of_the_model(self, catalog, couple):
        mission = commute()
        average = with_parameter(catalog, "assignment.bad_weather_share", 0.20)
        person(couple, "p1").weather_tolerance = None
        unanswered = bicycle_share(average, couple, mission)
        same_as_fair = with_parameter(
            average, "assignment.bad_weather_share_fair_weather_only", 0.20
        )
        person(couple, "p1").weather_tolerance = WeatherTolerance.FAIR_WEATHER_ONLY
        assert bicycle_share(same_as_fair, couple, mission) == pytest.approx(unanswered)

    def test_the_tolerance_of_another_adult_does_not_change_my_trips(self, catalog, couple):
        mission = commute(person_id="p1")
        before = bicycle_share(catalog, couple, mission)
        person(couple, "p2").weather_tolerance = WeatherTolerance.FAIR_WEATHER_ONLY
        assert bicycle_share(catalog, couple, mission) == pytest.approx(before)

    def test_a_trip_of_the_household_takes_the_average_of_its_adults(self, catalog, couple):
        mission = commute(person_id=None)
        # p1 never gives the bicycle up, p2 gives it up on 40% of the days: 20% on average
        tuned = with_parameter(catalog, "assignment.bad_weather_share_any_weather", 0.0)
        tuned = with_parameter(tuned, "assignment.bad_weather_share_fair_weather_only", 0.40)
        person(couple, "p1").weather_tolerance = WeatherTolerance.ANY_WEATHER
        person(couple, "p2").weather_tolerance = WeatherTolerance.FAIR_WEATHER_ONLY
        mixed = bicycle_share(tuned, couple, mission)

        everyone = couple.model_copy(deep=True)
        person(everyone, "p1").weather_tolerance = WeatherTolerance.ANY_WEATHER
        person(everyone, "p2").weather_tolerance = WeatherTolerance.ANY_WEATHER
        always = bicycle_share(tuned, everyone, mission)
        assert mixed == pytest.approx(0.80 * always)


# --- the whole analysis --------------------------------------------------------------------


class TestAnalysis:
    @staticmethod
    def proposed_ids(result) -> list[str]:
        return [r.portfolio_id for r in result.recommendations.recommendations]

    def test_nobody_who_rides_means_no_two_wheeler_is_recommended(self, catalog, couple):
        for adult in couple.household.adults:
            adult.accessibility_constraints = [NO_TWO_WHEELS]
        ids = self.proposed_ids(analyze(catalog, couple))
        assert ids
        assert not any("e_bike" in i or "scooter" in i for i in ids)

    def test_the_questionnaire_answer_is_accepted_and_returned_by_the_api(self, couple):
        data = couple.model_dump(mode="json")
        data["household"]["adults"][0]["weather_tolerance"] = "FAIR_WEATHER_ONLY"
        data["household"]["adults"][1]["accessibility_constraints"] = ["NO_TWO_WHEELS"]
        profile = UserProfile.model_validate(data)
        assert profile.household.adults[0].weather_tolerance is WeatherTolerance.FAIR_WEATHER_ONLY
        assert profile.household.adults[1].accessibility_constraints == [NO_TWO_WHEELS]

    def test_an_unknown_tolerance_is_refused(self, couple):
        data = couple.model_dump(mode="json")
        data["household"]["adults"][0]["weather_tolerance"] = "SOMETIMES"
        with pytest.raises(ValueError):
            UserProfile.model_validate(data)
