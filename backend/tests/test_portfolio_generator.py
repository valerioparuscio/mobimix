"""Candidate portfolio generation (step 7), on the five demo households and edited copies."""

from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from app.data.loader import Catalog, load_demo_households
from app.main import app
from app.models import (
    AccessibilityConstraint,
    AgeRange,
    AreaType,
    ChangeKind,
    HeldSubscription,
    NumericAnswer,
    Occupation,
    OptionType,
    OwnedVehicle,
    Ownership,
    Portfolio,
    PortfolioOrigin,
    UserProfile,
)
from app.services.demand import RuleBasedDemandEstimator
from app.services.portfolios import (
    RuleBasedPortfolioGenerator,
    describe_changes,
    portfolio_label,
)

COMMITMENTS = (Ownership.OWNED, Ownership.SUBSCRIPTION)


@pytest.fixture(scope="module")
def households(catalog: Catalog) -> dict[str, UserProfile]:
    return load_demo_households(catalog)


@pytest.fixture
def generate(catalog, households):
    """generate(name, edit=None, catalog=None) -> candidates for a private copy of a household."""

    def _generate(name: str, edit=None, with_catalog: Catalog | None = None) -> list[Portfolio]:
        used = with_catalog or catalog
        profile = households[name].model_copy(deep=True)
        if edit:
            edit(profile)
        demand = RuleBasedDemandEstimator(used).estimate(profile)
        return RuleBasedPortfolioGenerator(used).generate(profile, demand)

    return _generate


def by_id(candidates: list[Portfolio]) -> dict[str, Portfolio]:
    return {candidate.id: candidate for candidate in candidates}


def option_ids(portfolio: Portfolio) -> list[str]:
    return [item.option_id for item in portfolio.items]


def commitments(portfolio: Portfolio, catalog: Catalog):
    """The vehicles and subscriptions of a portfolio, without services and walking."""
    return [i for i in portfolio.items if catalog.option(i.option_id).ownership in COMMITMENTS]


class TestCandidateSet:
    EXPECTED_COUNTS = {  # regression on the current rules: update deliberately
        "urban_single": 6,
        "urban_couple": 7,
        "family_two_cars": 16,
        "peripheral_family": 6,
        "car_free_household": 5,
    }

    @pytest.mark.parametrize("name", list(EXPECTED_COUNTS))
    def test_number_of_candidates(self, generate, name):
        assert len(generate(name)) == self.EXPECTED_COUNTS[name]

    @pytest.mark.parametrize("name", list(EXPECTED_COUNTS))
    def test_the_current_setup_is_never_a_candidate(self, generate, name):
        assert all(candidate.changes for candidate in generate(name))

    @pytest.mark.parametrize("name", list(EXPECTED_COUNTS))
    def test_no_two_candidates_share_a_setup(self, generate, catalog, name):
        keys = [
            frozenset((i.option_id, i.holder_id, i.profile_ref) for i in commitments(c, catalog))
            for c in generate(name)
        ]
        assert len(keys) == len(set(keys))

    @pytest.mark.parametrize("name", list(EXPECTED_COUNTS))
    def test_ids_are_unique_and_every_option_exists(self, generate, catalog, name):
        candidates = generate(name)
        assert len({c.id for c in candidates}) == len(candidates)
        for candidate in candidates:
            assert all(option_id in catalog.options for option_id in option_ids(candidate))
            assert candidate.origin is PortfolioOrigin.GENERATED
            assert candidate.generation_rule

    @pytest.mark.parametrize("name", list(EXPECTED_COUNTS))
    def test_walking_is_always_available(self, generate, name):
        assert all("walking" in option_ids(c) for c in generate(name))

    def test_generation_is_deterministic(self, generate):
        assert generate("family_two_cars") == generate("family_two_cars")

    def test_a_household_with_cars_gets_the_listed_setups(self, generate):
        # CLAUDE.md section 20: fewer cars, car + PT, car + e-bike, car + scooter, car-free + PT
        ids = by_id(generate("urban_single"))
        assert {
            "keep-car1+pt",
            "keep-car1+e_bike",
            "keep-car1+scooter",
            "car-free+pt",
        } <= ids.keys()
        assert "car-free+pt_e_bike" in ids


class TestFleets:
    def test_every_number_of_cars_from_all_to_none_is_tried(self, generate):
        fleets = {c.id.split("+")[0] for c in generate("family_two_cars")}
        assert fleets == {"keep-car1-car2", "keep-car1", "keep-car2", "car-free"}

    def test_two_cars_of_different_models_give_two_one_car_candidates(self, generate, catalog):
        candidates = by_id(generate("family_two_cars"))
        kept_medium = candidates["keep-car1+cars_only"]
        kept_small = candidates["keep-car2+cars_only"]
        assert "car_medium_petrol" in option_ids(kept_medium)
        assert "car_small_petrol" in option_ids(kept_small)

    def test_two_identical_cars_give_one_one_car_candidate(self, generate):
        def same_model(profile):
            profile.vehicles[1].option_id = profile.vehicles[0].option_id

        fleets = {c.id.split("+")[0] for c in generate("family_two_cars", same_model)}
        assert fleets == {"keep-car1-car2", "keep-car1", "car-free"}

    def test_three_cars(self, generate):
        def third_car(profile):
            profile.vehicles.append(
                OwnedVehicle(id="car3", option_id="car_diesel", primary_user_id="p1")
            )

        fleets = {c.id.split("+")[0] for c in generate("family_two_cars", third_car)}
        assert fleets == {
            "keep-car1-car2-car3",
            "keep-car1-car2",
            "keep-car1-car3",
            "keep-car2-car3",
            "keep-car1",
            "keep-car2",
            "keep-car3",
            "car-free",
        }

    def test_a_household_without_cars_may_buy_one_but_not_two(self, generate):
        fleets = {c.id.split("+")[0] for c in generate("car_free_household")}
        assert fleets == {"car-free", "buy-car_small_petrol"}

    def test_a_couple_buys_a_compact_car_and_a_family_buys_a_family_car(self, generate):
        assert "buy-car_small_petrol+cars_only" in by_id(generate("car_free_household"))

        def with_child(profile):
            profile.household.n_children = 1

        assert "buy-car_medium_petrol+cars_only" in by_id(
            generate("car_free_household", with_child)
        )

    def test_nobody_with_a_licence_means_no_car_to_buy(self, generate):
        def no_licence(profile):
            for person in profile.household.adults:
                person.has_license = False

        fleets = {c.id.split("+")[0] for c in generate("car_free_household", no_licence)}
        assert fleets == {"car-free"}

    def test_a_one_car_household_is_not_offered_a_second_car(self, generate, catalog):
        for candidate in generate("urban_single"):
            cars = [
                i
                for i in candidate.items
                if catalog.option(i.option_id).mode.value == "CAR"
                and catalog.option(i.option_id).ownership is Ownership.OWNED
            ]
            assert len(cars) <= 1


class TestWhatIsKeptAndWhatIsNew:
    def test_kept_items_keep_their_profile_reference_and_user(self, generate):
        candidate = by_id(generate("family_two_cars"))["keep-car1+cars_only"]
        car = next(i for i in candidate.items if i.option_id == "car_medium_petrol")
        assert (car.profile_ref, car.holder_id) == ("car1", "p1")

    def test_new_vehicles_belong_to_the_household_and_have_no_reference(self, generate):
        candidate = by_id(generate("urban_single"))["keep-car1+e_bike"]
        e_bike = next(i for i in candidate.items if i.option_id == "e_bike")
        assert (e_bike.profile_ref, e_bike.holder_id) == (None, None)

    def test_bicycles_stay_in_every_candidate(self, generate):
        for candidate in generate("car_free_household"):
            refs = {i.profile_ref for i in candidate.items if i.option_id == "bicycle"}
            assert refs == {"bike1", "bike2"}
            assert not any(c.kind is ChangeKind.SELL_VEHICLE for c in candidate.changes)

    def test_other_subscriptions_stay_in_every_candidate(self, generate):
        def bikemi(profile):
            profile.subscriptions.append(
                HeldSubscription(id="sub9", option_id="bikemi_annual", holder_id="p1")
            )

        for candidate in generate("urban_single", bikemi):
            assert "sub9" in {i.profile_ref for i in candidate.items}
            assert not any(c.profile_ref == "sub9" for c in candidate.changes)


class TestTransitPasses:
    def new_pass(self, candidate: Portfolio):
        return [i for i in candidate.items if i.profile_ref is None and "annual" in i.option_id]

    def test_the_pass_follows_what_the_area_sells(self, generate):
        city = self.new_pass(by_id(generate("urban_single"))["keep-car1+pt"])
        assert [i.option_id for i in city] == ["pt_annual_urban_milano"]
        outskirts = self.new_pass(by_id(generate("peripheral_family"))["keep-car1+pt"])
        assert {i.option_id for i in outskirts} == {"pt_annual_metro_mi1_mi3"}

    @pytest.mark.parametrize(
        ("age", "expected"),
        [
            (AgeRange.A18_24, "pt_annual_urban_milano_under27"),
            (AgeRange.A25_34, "pt_annual_urban_milano"),  # may be 27 or more: no discount assumed
            (AgeRange.A65_74, "pt_annual_urban_milano_senior"),
            (None, "pt_annual_urban_milano"),
        ],
    )
    def test_a_discounted_pass_only_when_the_whole_age_band_qualifies(
        self, generate, age, expected
    ):
        def aged(profile):
            profile.household.adults[0].age_range = age

        candidate = by_id(generate("urban_single", aged))["keep-car1+pt"]
        assert [i.option_id for i in self.new_pass(candidate)] == [expected]

    def test_passes_go_to_people_who_commute(self, generate):
        def second_adult_retired(profile):
            profile.household.adults[1].occupation = Occupation.RETIRED
            profile.household.adults[1].work_or_study = None

        candidate = by_id(generate("family_two_cars", second_adult_retired))["keep-car1-car2+pt"]
        assert [i.holder_id for i in self.new_pass(candidate)] == ["p1"]

    def test_if_nobody_commutes_every_adult_gets_a_pass(self, generate):
        def all_retired(profile):
            for person in profile.household.adults:
                person.occupation = Occupation.RETIRED
                person.work_or_study = None

        candidate = by_id(generate("family_two_cars", all_retired))["keep-car1-car2+pt"]
        assert {i.holder_id for i in self.new_pass(candidate)} == {"p1", "p2"}

    def test_a_pass_already_held_is_kept_and_only_the_missing_one_is_added(
        self, generate, households
    ):
        candidate = by_id(generate("urban_couple"))["keep-car1+pt"]
        held = households["urban_couple"].subscriptions[0]
        assert held.id in {i.profile_ref for i in candidate.items}
        added = self.new_pass(candidate)
        assert len(added) == 1
        assert added[0].holder_id != held.holder_id

    def test_a_pass_can_be_cancelled_only_if_one_is_held(self, generate, households):
        candidates = by_id(generate("urban_couple"))
        changes = candidates["keep-car1+no_transit"].changes
        held = households["urban_couple"].subscriptions[0]
        assert [(c.kind, c.profile_ref) for c in changes] == [
            (ChangeKind.CANCEL_SUBSCRIPTION, held.id)
        ]
        assert not any(c.id.endswith("+no_transit") for c in generate("urban_single"))

    def test_a_cancelled_pass_does_not_stay_in_the_portfolio(self, generate):
        candidate = by_id(generate("urban_couple"))["keep-car1+no_transit"]
        assert not any("annual" in option_id for option_id in option_ids(candidate))

    def test_no_candidate_with_passes_where_none_are_sold(self, generate, catalog):
        no_passes = replace(
            catalog,
            options={
                key: option
                for key, option in catalog.options.items()
                if option.type is not OptionType.PT_ANNUAL
            },
        )
        ids = {c.id for c in generate("urban_single", with_catalog=no_passes)}
        assert ids == {"keep-car1+e_bike", "keep-car1+scooter"}


class TestOtherAddOns:
    def e_bike_ids(self, candidates):
        return [c.id for c in candidates if "e_bike" in c.id]

    def test_no_e_bike_if_nobody_can_ride_a_bicycle(self, generate):
        def nobody_cycles(profile):
            for person in profile.household.adults:
                person.accessibility_constraints = [AccessibilityConstraint.CANNOT_CYCLE]

        assert self.e_bike_ids(generate("urban_couple", nobody_cycles)) == []

    def test_an_e_bike_is_still_offered_if_one_adult_can_ride(self, generate):
        def one_cannot(profile):
            profile.household.adults[0].accessibility_constraints = [
                AccessibilityConstraint.CANNOT_CYCLE
            ]

        assert self.e_bike_ids(generate("urban_couple", one_cannot))

    def test_an_e_bike_already_owned_is_not_bought_again(self, generate):
        def owns_one(profile):
            profile.vehicles.append(OwnedVehicle(id="eb", option_id="e_bike"))

        candidates = generate("urban_single", owns_one)
        assert not any(
            c.kind is ChangeKind.BUY_VEHICLE and c.option_id == "e_bike"
            for candidate in candidates
            for c in candidate.changes
        )

    def test_a_motorcycle_owner_is_not_offered_a_scooter(self, generate):
        def owns_one(profile):
            profile.vehicles.append(OwnedVehicle(id="m1", option_id="motorcycle"))

        assert not [c for c in generate("urban_single", owns_one) if "scooter" in c.id]

    def test_no_scooter_without_a_licence(self, generate):
        def no_licence(profile):
            profile.household.adults[0].has_license = False

        assert not [c for c in generate("urban_single", no_licence) if "scooter" in c.id]


class TestServices:
    def services(self, candidate: Portfolio, catalog: Catalog) -> set[str]:
        return {
            i.option_id
            for i in candidate.items
            if catalog.option(i.option_id).ownership is Ownership.PAY_PER_USE
        }

    def test_every_candidate_of_a_household_has_the_same_services(self, generate, catalog):
        for name in ("urban_single", "family_two_cars"):
            layers = {frozenset(self.services(c, catalog)) for c in generate(name)}
            assert len(layers) == 1

    def test_services_depend_on_what_the_area_offers(self, generate, catalog):
        city = self.services(generate("urban_single")[0], catalog)
        outskirts = self.services(generate("peripheral_family")[0], catalog)
        assert "car_sharing_free2move_milano" in city
        assert "car_sharing_free2move_milano" not in outskirts  # free-floating: city only
        # taxi, tickets and rail are sold everywhere, outskirts included; so is rental
        assert {"taxi_milano", "pt_ticket_urban_milano", "rail_regional_ticket"} <= outskirts
        assert "car_rental_daily" in outskirts

    @pytest.fixture
    def no_taxi_in_outskirts(self, catalog) -> Catalog:
        """The catalogue as it was before taxis were extended to PERIPHERAL areas: the shipped
        data offers every household a taxi, so the two tests below need a catalogue without."""
        taxi = catalog.options["taxi_milano"]
        areas = [a for a in taxi.available_in_area_types if a is not AreaType.PERIPHERAL]
        edited = taxi.model_copy(update={"available_in_area_types": areas})
        return replace(catalog, options={**catalog.options, "taxi_milano": edited})

    def test_a_declared_service_is_available_even_outside_its_area(
        self, generate, no_taxi_in_outskirts
    ):
        def declares_taxi(profile):
            profile.other_mobility.taxi_trips_per_year = NumericAnswer.of(10)

        without = generate("peripheral_family", with_catalog=no_taxi_in_outskirts)
        assert "taxi_milano" not in self.services(without[0], no_taxi_in_outskirts)
        declared = generate("peripheral_family", declares_taxi, no_taxi_in_outskirts)
        assert "taxi_milano" in self.services(declared[0], no_taxi_in_outskirts)

    def test_a_statistical_default_does_not_make_a_service_available(
        self, generate, no_taxi_in_outskirts
    ):
        # peripheral_family declares no taxi trips: the area default of 1 must not add the taxi
        candidates = generate("peripheral_family", with_catalog=no_taxi_in_outskirts)
        assert "taxi_milano" not in self.services(candidates[0], no_taxi_in_outskirts)

    def test_the_placeholder_ride_hailing_service_is_left_out(self, generate, catalog):
        for candidate in generate("urban_single"):
            assert "ride_hailing_ncc" not in option_ids(candidate)


class TestChanges:
    def test_a_change_per_step(self, generate):
        changes = by_id(generate("family_two_cars"))["keep-car1+pt_e_bike"].changes
        kinds = [(c.kind, c.option_id) for c in changes]
        assert kinds == [
            (ChangeKind.SELL_VEHICLE, "car_small_petrol"),
            (ChangeKind.BUY_VEHICLE, "e_bike"),
            (ChangeKind.START_SUBSCRIPTION, "pt_annual_urban_milano"),
            (ChangeKind.START_SUBSCRIPTION, "pt_annual_urban_milano"),
        ]
        assert changes[0].profile_ref == "car2"

    @pytest.mark.parametrize("name", list(TestCandidateSet.EXPECTED_COUNTS))
    def test_changes_turn_the_current_setup_into_the_candidate(
        self, generate, households, catalog, name
    ):
        profile = households[name]
        current_refs = {v.id for v in profile.vehicles} | {s.id for s in profile.subscriptions}
        for candidate in generate(name):
            gone = {
                c.profile_ref
                for c in candidate.changes
                if c.kind in (ChangeKind.SELL_VEHICLE, ChangeKind.CANCEL_SUBSCRIPTION)
            }
            kept = {i.profile_ref for i in candidate.items if i.profile_ref is not None}
            assert kept == current_refs - gone, candidate.id

            new = sorted(
                (i.option_id, i.holder_id)
                for i in commitments(candidate, catalog)
                if i.profile_ref is None
            )
            arrivals = sorted(
                (c.option_id, c.holder_id)
                for c in candidate.changes
                if c.kind in (ChangeKind.BUY_VEHICLE, ChangeKind.START_SUBSCRIPTION)
            )
            assert new == arrivals, candidate.id


class TestLabels:
    def test_names_list_what_the_household_decides(self, generate):
        single = by_id(generate("urban_single"))
        assert single["car-free+pt_e_bike"].name == "Senza auto + 1 abbonamento TP + e-bike"
        assert single["keep-car1+scooter"].name == "Utilitaria a benzina + scooter 125 cc"
        family = by_id(generate("family_two_cars"))
        assert family["keep-car1-car2+pt"].name == (
            "Auto media a benzina + Utilitaria a benzina + 2 abbonamenti TP"
        )

    def test_identical_cars_are_counted(self, generate, catalog):
        def same_model(profile):
            profile.vehicles[1].option_id = profile.vehicles[0].option_id

        candidate = by_id(generate("family_two_cars", same_model))["keep-car1-car2+e_bike"]
        assert candidate.name == "2 × Auto media a benzina + e-bike"

    def test_the_description_is_made_of_the_changes(self, generate, catalog):
        candidate = by_id(generate("family_two_cars"))["keep-car1+pt_e_bike"]
        assert candidate.description == (
            "Vendere «Utilitaria a benzina»; acquistare «E-bike»; "
            "sottoscrivere 2 × «Abbonamento annuale urbano ATM (ordinario)»."
        )
        assert describe_changes(candidate.changes, catalog) == candidate.description
        assert describe_changes([], catalog) == ""

    def test_label_of_an_arbitrary_item_list(self, catalog):
        from app.models import PortfolioItem

        items = [
            PortfolioItem(option_id="bicycle"),
            PortfolioItem(option_id="rail_annual_lombardia"),
        ]
        assert portfolio_label(items, catalog) == "Senza auto + 1 abbonamento treno"


def test_age_bands_are_contiguous():
    bands = sorted((band.bounds for band in AgeRange), key=lambda bounds: bounds[0])
    for (_, previous_high), (low, _) in zip(bands, bands[1:], strict=False):
        assert low == previous_high + 1


def test_every_area_has_at_least_one_candidate_for_a_car_household(generate):
    for area in AreaType:

        def move(profile, area=area):
            profile.household.location.area_type = area

        assert generate("urban_single", move), area


class TestEndpoint:
    def test_generate_portfolios(self, households):
        with TestClient(app) as client:
            response = client.post(
                "/api/portfolios/generate",
                json=households["urban_single"].model_dump(mode="json"),
            )
            assert response.status_code == 200
            body = response.json()
            assert len(body) == TestCandidateSet.EXPECTED_COUNTS["urban_single"]
            assert {"id", "name", "items", "changes", "description"} <= body[0].keys()

            broken = households["urban_single"].model_dump(mode="json")
            broken["vehicles"][0]["option_id"] = "flying_car"
            assert client.post("/api/portfolios/generate", json=broken).status_code == 422
