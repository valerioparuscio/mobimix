"""The reference data under data/ must load, be internally consistent, and stay plausible."""

import shutil

import pytest

from app.config import DEFAULT_DATA_DIR
from app.data.audit import build_report
from app.data.loader import (
    REQUIRED_DEFAULT_KEYS,
    Catalog,
    CatalogError,
    iter_catalog_values,
    load_catalog,
)
from app.models import AreaType, Confidence, EnergyCarrier, Mode, OptionType, Ownership, TripBand


class TestLoading:
    def test_loads_without_errors(self, catalog: Catalog):
        assert catalog.options
        assert catalog.parameters
        assert len(catalog.version) == 12

    def test_every_option_type_of_the_brief_is_covered(self, catalog: Catalog):
        present = {option.type for option in catalog.options.values()}
        assert present == set(OptionType)

    def test_every_option_has_scores(self, catalog: Catalog):
        for option in catalog.options.values():
            assert option.comfort_score is not None, option.id
            assert option.flexibility_score is not None, option.id
            assert option.reliability_score is not None, option.id

    def test_every_area_type_has_all_defaults(self, catalog: Catalog):
        for area_type in AreaType:
            assert set(REQUIRED_DEFAULT_KEYS) <= catalog.defaults_for(area_type).values.keys()

    def test_trip_bands(self, catalog: Catalog):
        assert catalog.trip_band(5) is TripBand.URBAN
        assert catalog.trip_band(60) is TripBand.REGIONAL
        assert catalog.trip_band(450) is TripBand.LONG

    def test_unknown_ids_give_a_clear_error(self, catalog: Catalog):
        with pytest.raises(KeyError, match="no_such_option"):
            catalog.option("no_such_option")
        with pytest.raises(KeyError, match="no.such.parameter"):
            catalog.parameter("no.such.parameter")


class TestProvenance:
    def test_every_source_reference_resolves(self, catalog: Catalog):
        for owner, path, value in iter_catalog_values(catalog):
            if value.source is not None:
                assert value.source in catalog.sources, f"{owner} {path}"

    def test_high_confidence_values_are_sourced_or_standard_constants(self, catalog: Catalog):
        # A HIGH-confidence number without a source is allowed only for the standard
        # combustion factors and for structural zeros (no marginal cost, no overhead, day trip).
        standard_constants = {
            "parameter:emissions.petrol_kg_co2_per_l",
            "parameter:emissions.diesel_kg_co2_per_l",
        }
        structural_zero_paths = {"cost_per_trip", "fixed_time_min_per_trip", "days_away"}
        offenders = [
            f"{owner} {path}".strip()
            for owner, path, value in iter_catalog_values(catalog)
            if value.confidence is Confidence.HIGH
            and value.source is None
            and owner not in standard_constants
            and not (path in structural_zero_paths and value.value == 0)
        ]
        assert not offenders

    def test_placeholders_are_reported_by_the_audit(self, catalog: Catalog):
        report = build_report(catalog)
        assert "valuation.value_of_time_eur_per_hour" in report
        assert "Placeholders" in report


class TestOptionCoherence:
    def test_free_and_pay_per_use_options_have_no_purchase_price(self, catalog: Catalog):
        for option in catalog.options.values():
            if option.ownership is not Ownership.OWNED:
                assert option.purchase_price is None, option.id

    def test_owned_assets_have_complete_depreciation_inputs(self, catalog: Catalog):
        for option in catalog.options.values():
            if option.ownership is Ownership.OWNED:
                assert option.purchase_price and option.residual_value, option.id
                assert option.expected_lifetime_years, option.id

    def test_every_option_has_a_speed_in_at_least_one_band(self, catalog: Catalog):
        for option in catalog.options.values():
            assert option.average_speed_kmh, option.id

    def test_speed_bands_are_consistent_with_practical_distance(self, catalog: Catalog):
        # An option limited to short legs must not declare speeds only for long legs.
        for option in catalog.options.values():
            limit = option.max_practical_distance_km
            if limit is not None and limit.value <= catalog.value("bands.urban_max_km"):
                assert TripBand.URBAN in option.average_speed_kmh, option.id

    def test_the_shortest_practical_leg_is_below_the_longest(self, catalog: Catalog):
        for option in catalog.options.values():
            shortest, longest = option.min_practical_distance_km, option.max_practical_distance_km
            if shortest is not None:
                assert longest is not None, option.id
                assert shortest.value < longest.value, option.id

    def test_feasibility_rules_only_name_modes_and_types_of_the_catalogue(self, catalog: Catalog):
        rules = catalog.feasibility_rules
        assert set(rules.occasional_only_types) <= {o.type for o in catalog.options.values()}
        used_modes = {o.mode for o in catalog.options.values()}
        assert set(rules.modes_not_with_children) <= used_modes
        assert set(rules.unavailable_time_bands) <= used_modes
        for modes in rules.accessibility_exclusions.values():
            assert set(modes) <= used_modes

    def test_every_road_vehicle_that_can_take_a_motorway_pays_tolls(self, catalog: Catalog):
        for option in catalog.options.values():
            if option.mode is Mode.CAR or option.type in (OptionType.MOTORCYCLE, OptionType.TAXI):
                assert option.uses_motorways, option.id
            if option.type in (OptionType.BICYCLE, OptionType.E_BIKE, OptionType.SCOOTER):
                assert not option.uses_motorways, option.id

    def test_whoever_arrives_by_rail_or_air_has_no_vehicle_at_the_destination(
        self, catalog: Catalog
    ):
        for option in catalog.options.values():
            assert option.no_vehicle_at_destination == (option.mode in (Mode.RAIL, Mode.AIR)), (
                option.id
            )

    def test_regional_rail_needs_ten_kilometres(self, catalog: Catalog):
        # at 5-10 km it took a quarter of urban commutes, as nobody knows how far the station is
        for option_id in ("rail_regional_ticket", "rail_annual_lombardia"):
            assert catalog.option(option_id).min_practical_distance_km.value >= 10

    def test_energy_carriers_have_a_price_parameter(self, catalog: Catalog):
        prices = {
            EnergyCarrier.PETROL: "energy.petrol_eur_per_l",
            EnergyCarrier.DIESEL: "energy.diesel_eur_per_l",
            EnergyCarrier.ELECTRICITY: "energy.electricity_home_eur_per_kwh",
        }
        for option in catalog.options.values():
            if option.energy is not None:
                assert catalog.parameter(prices[option.energy.carrier]), option.id

    def test_motorised_private_options_need_a_license(self, catalog: Catalog):
        for option in catalog.options.values():
            if option.mode in (Mode.CAR, Mode.MOTORCYCLE) and option.ownership is Ownership.OWNED:
                assert option.requires_license, option.id

    def test_age_limited_options_are_the_discounted_pt_passes(self, catalog: Catalog):
        limited = {
            option.id for option in catalog.options.values() if option.min_age or option.max_age
        }
        assert limited == {"pt_annual_urban_milano_under27", "pt_annual_urban_milano_senior"}


class TestCarCostSanity:
    """Cross-check the data against published total-cost figures (ISFORT, sum.money)."""

    def test_small_petrol_car_matches_the_isfort_range(self, catalog: Catalog, naive_annual_cost):
        sanity = catalog.parameter("statistics.car_cost_sanity_eur_per_year")
        km = catalog.value("statistics.car_annual_km_italy_avg")
        cost = naive_annual_cost(catalog, "car_small_petrol", km)
        assert sanity.lo <= cost <= sanity.hi, cost

    def test_medium_petrol_car_is_close_to_the_simulator_figure(
        self, catalog: Catalog, naive_annual_cost
    ):
        # sum.money: ~5,200 EUR/year for a 25,000 EUR sedan.
        cost = naive_annual_cost(catalog, "car_medium_petrol", 10_700)
        assert 4_500 <= cost <= 6_500, cost

    def test_ordering_of_cars_is_plausible(self, catalog: Catalog, naive_annual_cost):
        small = naive_annual_cost(catalog, "car_small_petrol", 10_700)
        medium = naive_annual_cost(catalog, "car_medium_petrol", 10_700)
        assert small < medium

    def test_electric_car_is_cheaper_to_run_but_not_absurdly_cheaper_to_own(
        self, catalog: Catalog, naive_annual_cost
    ):
        electric = naive_annual_cost(catalog, "car_electric", 10_700)
        medium = naive_annual_cost(catalog, "car_medium_petrol", 10_700)
        assert 0.6 * medium <= electric <= 1.1 * medium, (electric, medium)

    def test_pt_annual_pass_breaks_even_against_tickets_at_a_plausible_use(self, catalog: Catalog):
        annual = catalog.option("pt_annual_urban_milano").fixed_cost_year
        ticket = catalog.option("pt_ticket_urban_milano").cost_per_trip
        assert annual and ticket
        break_even_trips = annual.value / ticket.value
        # 360 / 2.30 = 157 trips: about 78 commuting days, well below a full working year
        assert 120 <= break_even_trips <= 200


class TestFailsLoudly:
    @pytest.fixture
    def broken_copy(self, tmp_path):
        target = tmp_path / "data"
        shutil.copytree(DEFAULT_DATA_DIR, target)
        return target

    def test_unknown_source_is_reported(self, broken_copy):
        path = broken_copy / "model_parameters.yaml"
        path.write_text(
            path.read_text(encoding="utf-8").replace(
                "source: mimit_carburanti_2026_10", "source: not_a_real_source", 1
            ),
            encoding="utf-8",
        )
        with pytest.raises(CatalogError, match="unknown source 'not_a_real_source'"):
            load_catalog(broken_copy)

    def test_missing_required_parameter_is_reported(self, broken_copy):
        path = broken_copy / "model_parameters.yaml"
        path.write_text(
            path.read_text(encoding="utf-8").replace(
                "id: valuation.value_of_time_eur_per_hour", "id: valuation.renamed", 1
            ),
            encoding="utf-8",
        )
        with pytest.raises(CatalogError, match="value_of_time_eur_per_hour"):
            load_catalog(broken_copy)

    def test_option_without_scores_is_reported(self, broken_copy):
        path = broken_copy / "comfort_scores.yaml"
        path.write_text(
            path.read_text(encoding="utf-8").replace("  walking:", "  _walking:", 1),
            encoding="utf-8",
        )
        with pytest.raises(CatalogError, match="comfort_scores.yaml"):
            load_catalog(broken_copy)

    def test_portfolio_rules_must_name_existing_options(self, broken_copy):
        path = broken_copy / "portfolio_rules.yaml"
        path.write_text(
            path.read_text(encoding="utf-8").replace("car_small_petrol", "car_unknown", 1),
            encoding="utf-8",
        )
        with pytest.raises(CatalogError, match="car_unknown"):
            load_catalog(broken_copy)

    def test_portfolio_rules_new_vehicles_must_be_of_the_right_kind(self, broken_copy):
        path = broken_copy / "portfolio_rules.yaml"
        path.write_text(
            path.read_text(encoding="utf-8").replace("e_bike: e_bike", "e_bike: bicycle", 1),
            encoding="utf-8",
        )
        with pytest.raises(CatalogError, match="new_vehicles.e_bike"):
            load_catalog(broken_copy)

    def test_the_service_layer_holds_pay_per_use_options_only(self, broken_copy):
        path = broken_copy / "portfolio_rules.yaml"
        path.write_text(
            path.read_text(encoding="utf-8").replace(
                "  - taxi_milano", "  - pt_annual_urban_milano", 1
            ),
            encoding="utf-8",
        )
        with pytest.raises(CatalogError, match="service_layer"):
            load_catalog(broken_copy)

    def test_feasibility_rules_reject_an_unknown_mode(self, broken_copy):
        path = broken_copy / "feasibility_rules.yaml"
        path.write_text(
            path.read_text(encoding="utf-8").replace("[BICYCLE, E_BIKE]", "[BICYCLE, E_SKATE]", 1),
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="E_SKATE"):
            load_catalog(broken_copy)

    def test_a_missing_feasibility_threshold_is_reported(self, broken_copy):
        path = broken_copy / "model_parameters.yaml"
        path.write_text(
            path.read_text(encoding="utf-8").replace(
                "id: feasibility.rare_max_occurrences_per_year", "id: feasibility.renamed", 1
            ),
            encoding="utf-8",
        )
        with pytest.raises(CatalogError, match="rare_max_occurrences_per_year"):
            load_catalog(broken_copy)

    def test_assignment_rules_must_cover_every_purpose(self, broken_copy):
        path = broken_copy / "assignment_rules.yaml"
        path.write_text(
            path.read_text(encoding="utf-8").replace("  OTHER: 2\n", "", 1), encoding="utf-8"
        )
        with pytest.raises(ValueError, match="OTHER"):
            load_catalog(broken_copy)

    def test_assignment_rules_must_cover_every_weather_level(self, broken_copy):
        path = broken_copy / "assignment_rules.yaml"
        path.write_text(
            path.read_text(encoding="utf-8").replace("  HIGH: 1.5\n", "", 1), encoding="utf-8"
        )
        with pytest.raises(ValueError, match="HIGH"):
            load_catalog(broken_copy)

    def test_a_missing_assignment_parameter_is_reported(self, broken_copy):
        path = broken_copy / "model_parameters.yaml"
        path.write_text(
            path.read_text(encoding="utf-8").replace(
                "id: assignment.logit_scale_per_eur", "id: assignment.renamed", 1
            ),
            encoding="utf-8",
        )
        with pytest.raises(CatalogError, match="logit_scale_per_eur"):
            load_catalog(broken_copy)

    def test_typo_in_an_option_field_is_rejected(self, broken_copy):
        path = broken_copy / "mobility_options.yaml"
        path.write_text(
            path.read_text(encoding="utf-8").replace(
                "maintenance_cost_year:", "maintainance_cost_year:", 1
            ),
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="maintainance_cost_year"):
            load_catalog(broken_copy)
