"""The five demo households (CLAUDE.md section 32) are regression fixtures: they must stay
loadable, and must describe the situations their names promise."""

import pytest

from app.data.loader import Catalog, load_demo_households
from app.models import AreaType, Frequency, Mode


@pytest.fixture(scope="module")
def households(catalog: Catalog):
    return load_demo_households(catalog)


def test_expected_households_exist(households):
    assert set(households) == {
        "urban_single",
        "urban_couple",
        "family_two_cars",
        "peripheral_family",
        "car_free_household",
    }


def test_ids_match_file_names(households):
    for name, profile in households.items():
        assert profile.id == name


def cars(profile, catalog: Catalog) -> int:
    return sum(1 for v in profile.vehicles if catalog.option(v.option_id).mode is Mode.CAR)


def test_urban_single(households, catalog):
    profile = households["urban_single"]
    assert profile.household.n_adults == 1
    assert profile.household.location.area_type is AreaType.CITY_CENTER
    assert cars(profile, catalog) == 1


def test_urban_couple_has_different_commutes(households, catalog):
    profile = households["urban_couple"]
    distances = {
        person.work_or_study.one_way_distance_km.exact
        for person in profile.household.adults
        if person.work_or_study
    }
    assert len(distances) == 2
    assert cars(profile, catalog) == 1


def test_family_two_cars_needs_simultaneity_answer(households, catalog):
    profile = households["family_two_cars"]
    assert cars(profile, catalog) == 2
    assert profile.household.n_children == 2
    assert profile.household.simultaneous_car_need is Frequency.OFTEN


def test_peripheral_family_has_poor_pt_and_long_commute(households):
    profile = households["peripheral_family"]
    assert profile.household.location.area_type is AreaType.PERIPHERAL
    longest = max(
        person.work_or_study.one_way_distance_km.exact
        for person in profile.household.adults
        if person.work_or_study
    )
    assert longest >= 30


def test_car_free_household_owns_no_car(households, catalog):
    profile = households["car_free_household"]
    assert cars(profile, catalog) == 0
    assert len(profile.subscriptions) == 2
