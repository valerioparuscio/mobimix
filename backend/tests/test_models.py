import pytest
from pydantic import ValidationError

from app.models import (
    AreaType,
    Confidence,
    Estimated,
    Household,
    Location,
    MobilityDemand,
    MobilityMission,
    MobilityOption,
    Person,
    Portfolio,
    PortfolioItem,
    Purpose,
    UserProfile,
    ValueSource,
)


def estimate(value: float) -> Estimated:
    return Estimated(value=value, source=ValueSource.DEFAULT, confidence=Confidence.LOW)


def commute(mission_id: str = "m1", person_id: str | None = "p1") -> MobilityMission:
    return MobilityMission(
        id=mission_id,
        person_id=person_id,
        purpose=Purpose.COMMUTE,
        occurrences_per_year=estimate(180),
        distance_km_one_way=estimate(8),
    )


def household() -> Household:
    return Household(adults=[Person(id="p1")], location=Location(area_type=AreaType.URBAN))


class TestMission:
    def test_annual_km_counts_every_leg(self):
        # 180 commute days x 2 legs x 8 km
        assert commute().annual_km == 2880

    def test_one_way_mission(self):
        mission = commute().model_copy(update={"legs_per_occurrence": 1})
        assert mission.annual_km == 1440


class TestDemand:
    def test_km_by_purpose_separates_needs(self):
        holiday = MobilityMission(
            id="m2",
            purpose=Purpose.HOLIDAY,
            occurrences_per_year=estimate(2),
            distance_km_one_way=estimate(450),
        )
        demand = MobilityDemand(profile_id="x", missions=[commute(), holiday])
        by_purpose = demand.annual_km_by_purpose()
        assert by_purpose[Purpose.COMMUTE] == 2880
        assert by_purpose[Purpose.HOLIDAY] == 1800
        assert demand.total_annual_km == 4680


class TestHousehold:
    def test_needs_at_least_one_adult(self):
        with pytest.raises(ValidationError):
            Household(adults=[], location=Location(area_type=AreaType.URBAN))

    def test_person_ids_must_be_unique(self):
        with pytest.raises(ValidationError):
            Household(
                adults=[Person(id="p1"), Person(id="p1")],
                location=Location(area_type=AreaType.URBAN),
            )

    def test_licensed_drivers_are_derived(self):
        household = Household(
            adults=[Person(id="p1"), Person(id="p2", has_license=False)],
            location=Location(area_type=AreaType.URBAN),
        )
        assert household.n_adults == 2
        assert household.n_licensed_drivers == 1


class TestUserProfile:
    def test_unknown_references_are_rejected(self):
        ghost_car = {"id": "v1", "option_id": "car_small_petrol", "primary_user_id": "ghost"}
        with pytest.raises(ValidationError, match="unknown primary_user_id"):
            UserProfile(household=household(), vehicles=[ghost_car])

    def test_unknown_fields_are_rejected(self):
        with pytest.raises(ValidationError):
            UserProfile(household=household(), annual_km=1000)

    def test_ids_are_random_and_anonymous(self):
        assert UserProfile(household=household()).id != UserProfile(household=household()).id

    def test_roundtrips_through_json(self):
        profile = UserProfile(household=household(), declared_missions=[commute()])
        assert UserProfile.model_validate_json(profile.model_dump_json()) == profile


class TestPortfolio:
    def test_signature_ignores_ids_names_and_item_order(self):
        first = Portfolio(
            id="a",
            name="A",
            items=[PortfolioItem(option_id="car_small_petrol"), PortfolioItem(option_id="e_bike")],
        )
        second = Portfolio(
            id="b",
            name="B",
            items=[PortfolioItem(option_id="e_bike"), PortfolioItem(option_id="car_small_petrol")],
        )
        assert first.signature == second.signature

    def test_different_content_has_different_signature(self):
        one_car = Portfolio(id="a", name="A", items=[PortfolioItem(option_id="car_small_petrol")])
        two_cars = Portfolio(
            id="b", name="B", items=[PortfolioItem(option_id="car_small_petrol", quantity=2)]
        )
        assert one_car.signature != two_cars.signature


class TestMobilityOption:
    BASE = {"id": "x", "name": "x", "type": "CAR_SMALL_PETROL", "mode": "CAR", "ownership": "OWNED"}

    def test_purchase_price_requires_depreciation_inputs(self):
        with pytest.raises(ValidationError, match="requires residual_value"):
            MobilityOption.model_validate({**self.BASE, "purchase_price": 10000})

    def test_residual_cannot_exceed_purchase_price(self):
        with pytest.raises(ValidationError, match="exceeds purchase_price"):
            MobilityOption.model_validate(
                {
                    **self.BASE,
                    "purchase_price": 10000,
                    "residual_value": 12000,
                    "expected_lifetime_years": 8,
                }
            )

    def test_scores_must_be_on_a_zero_to_ten_scale(self):
        with pytest.raises(ValidationError, match="within 0-10"):
            MobilityOption.model_validate({**self.BASE, "comfort_score": 11})
