"""Cost model: formulas checked against hand calculations on the catalogue values."""

import pytest

from app.data.loader import Catalog
from app.models import CostResult, MobilityOption, OptionUsage, Range
from app.services.costs import TcoCostModel


@pytest.fixture(scope="module")
def model(catalog: Catalog) -> TcoCostModel:
    return TcoCostModel(catalog)


def point(value: float) -> Range:
    return Range.point(value)


def line(result: CostResult, label: str):
    found = [item for item in result.lines if item.label == label]
    assert found, f"no line {label!r} in {[item.label for item in result.lines]}"
    return found[0].amount


def decay_rate(price: float, residual: float, lifetime: float) -> float:
    return 1 - (residual / price) ** (1 / lifetime)


class TestOwnedCar:
    def test_new_small_petrol_car_matches_hand_calculation(self, model, catalog):
        option = catalog.option("car_small_petrol")
        result = model.calculate(option, OptionUsage(annual_km=point(10_000)))
        # (17,000 - 7,000) / 8 years
        assert line(result, "depreciation").expected == pytest.approx(1_250)
        assert line(result, "insurance").expected == pytest.approx(560)
        assert line(result, "tax").expected == pytest.approx(150)
        assert line(result, "maintenance").expected == pytest.approx(420)
        assert line(result, "distance_charge").expected == pytest.approx(0.03 * 10_000)
        # 6.0 l/100 km x 10,000 km x 2.022 EUR/l
        assert line(result, "energy").expected == pytest.approx(0.06 * 10_000 * 2.022)
        assert result.total.expected == pytest.approx(
            1_250 + 560 + 150 + 420 + 300 + 0.06 * 10_000 * 2.022
        )

    def test_total_is_the_sum_of_its_lines(self, model, catalog):
        result = model.calculate(
            catalog.option("car_medium_petrol"), OptionUsage(annual_km=point(12_000))
        )
        assert result.total.expected == pytest.approx(
            sum(item.amount.expected for item in result.lines)
        )

    def test_parking_comes_from_the_usage_not_the_catalogue(self, model, catalog):
        option = catalog.option("car_small_petrol")
        usage = OptionUsage(annual_km=point(5_000), parking_cost_year=point(1_800))
        assert line(model.calculate(option, usage), "parking").expected == 1_800

    def test_diesel_and_petrol_use_their_own_price(self, model, catalog):
        diesel = model.calculate(catalog.option("car_diesel"), OptionUsage(annual_km=point(10_000)))
        # 5.8 l/100 km x 10,000 x 2.260
        assert line(diesel, "energy").expected == pytest.approx(0.058 * 10_000 * 2.260)

    def test_electric_car_uses_the_blended_charging_price(self, model, catalog):
        result = model.calculate(
            catalog.option("car_electric"), OptionUsage(annual_km=point(10_000))
        )
        public = 0.4 * 0.74 + 0.6 * 0.63
        price = 0.7 * 0.25 + 0.3 * public
        assert line(result, "energy").expected == pytest.approx(0.16 * 10_000 * price)

    def test_quantity_multiplies_fixed_costs_only(self, model, catalog):
        option = catalog.option("bicycle")
        one = model.calculate(option, OptionUsage(annual_km=point(600)))
        two = model.calculate(option, OptionUsage(annual_km=point(600), quantity=2))
        assert line(two, "insurance").expected == pytest.approx(2 * line(one, "insurance").expected)
        assert line(two, "maintenance").expected == pytest.approx(
            2 * line(one, "maintenance").expected
        )


class TestDepreciationOfAnAssetAlreadyOwned:
    def test_known_value_depreciates_at_the_geometric_rate(self, model, catalog):
        option = catalog.option("car_small_petrol")
        usage = OptionUsage(existing_asset=True, current_value=point(6_000))
        rate = decay_rate(17_000, 7_000, 8)
        assert line(model.calculate(option, usage), "depreciation").expected == pytest.approx(
            6_000 * rate
        )

    def test_unknown_value_assumes_the_average_age_of_the_fleet(self, model, catalog):
        option = catalog.option("car_small_petrol")
        result = model.calculate(option, OptionUsage(existing_asset=True))
        rate = decay_rate(17_000, 7_000, 8)
        expected = 17_000 * (1 - rate) ** 13 * rate  # fleet average age: 13 years
        depreciation = line(result, "depreciation")
        assert depreciation.expected == pytest.approx(expected)
        assert depreciation.expected < 600  # far below the 1,250 of a new car
        assert depreciation.low == 0
        assert depreciation.high >= 1_250  # could still be a recent car

    def test_a_new_purchase_is_charged_the_full_linear_depreciation(self, model, catalog):
        option = catalog.option("car_small_petrol")
        new = model.calculate(option, OptionUsage(existing_asset=False))
        old = model.calculate(option, OptionUsage(existing_asset=True))
        assert line(new, "depreciation").expected > 2 * line(old, "depreciation").expected

    def test_the_implied_value_is_consistent_with_the_expected_depreciation(self, model, catalog):
        option = catalog.option("car_small_petrol")
        value = model.expected_current_value(option)
        assert value is not None
        known = model.calculate(
            option, OptionUsage(existing_asset=True, current_value=point(value))
        )
        unknown = model.calculate(option, OptionUsage(existing_asset=True))
        assert line(known, "depreciation").expected == pytest.approx(
            line(unknown, "depreciation").expected
        )
        assert line(known, "depreciation").width < line(unknown, "depreciation").width


class TestSubscriptionsAndServices:
    def test_annual_pass_costs_its_fee(self, model, catalog):
        result = model.calculate(catalog.option("pt_annual_urban_milano"), OptionUsage())
        assert (
            result.total.expected == catalog.option("pt_annual_urban_milano").fixed_cost_year.value
        )

    def test_declared_price_overrides_the_catalogue(self, model, catalog):
        usage = OptionUsage(fixed_cost_override=point(280))
        result = model.calculate(catalog.option("pt_annual_urban_milano"), usage)
        assert result.total.expected == 280

    def test_monthly_pass_is_charged_per_month_held(self, model, catalog):
        option = catalog.option("pt_monthly_urban_milano")
        assert model.calculate(option, OptionUsage(months_held=12)).total.expected == 468
        assert model.calculate(option, OptionUsage(months_held=6)).total.expected == 234

    def test_pass_has_no_per_trip_cost(self, model, catalog):
        usage = OptionUsage(annual_trips=point(400))
        result = model.calculate(catalog.option("pt_annual_urban_milano"), usage)
        assert (
            result.total.expected == catalog.option("pt_annual_urban_milano").fixed_cost_year.value
        )

    def test_pt_tickets_are_charged_per_trip(self, model, catalog):
        usage = OptionUsage(annual_trips=point(150))
        result = model.calculate(catalog.option("pt_ticket_urban_milano"), usage)
        assert result.total.expected == pytest.approx(
            150 * catalog.option("pt_ticket_urban_milano").cost_per_trip.value
        )

    def test_pass_breaks_even_against_tickets_at_a_plausible_number_of_trips(self, model, catalog):
        fee = catalog.option("pt_annual_urban_milano").fixed_cost_year.value
        fare = catalog.option("pt_ticket_urban_milano").cost_per_trip.value
        trips = fee / fare
        passes = model.calculate(catalog.option("pt_annual_urban_milano"), OptionUsage())
        tickets = model.calculate(
            catalog.option("pt_ticket_urban_milano"), OptionUsage(annual_trips=point(trips))
        )
        assert passes.total.expected == pytest.approx(tickets.total.expected)
        assert 120 <= trips <= 200  # about 75 commuting days: well below a full working year

    def test_taxi_has_a_base_fare_and_a_distance_charge(self, model, catalog):
        usage = OptionUsage(annual_trips=point(10), annual_km=point(60))
        result = model.calculate(catalog.option("taxi_milano"), usage)
        assert result.total.expected == pytest.approx(10 * 4.10 + 60 * 1.50)

    def test_car_sharing_pays_the_cheapest_package_for_each_trip(self, model, catalog):
        option = catalog.option("car_sharing_free2move_milano")
        one_hour = OptionUsage(annual_trips=point(10), annual_minutes=point(600))
        # 60 min: 13.80 per minute vs 9.99 hourly package -> hourly wins
        assert model.calculate(option, one_hour).total.expected == pytest.approx(10 * 9.99)
        five_hours = OptionUsage(annual_trips=point(10), annual_minutes=point(3_000))
        # 300 min: 69.00 per minute vs 49.95 hourly vs 43.33 daily -> daily wins
        assert model.calculate(option, five_hours).total.expected == pytest.approx(10 * 43.33)
        ten_minutes = OptionUsage(annual_trips=point(10), annual_minutes=point(100))
        # 10 min: 2.30 per minute beats the 9.99 hourly package
        assert model.calculate(option, ten_minutes).total.expected == pytest.approx(10 * 2.30)

    def test_rental_pays_days_plus_the_fuel_of_the_renter(self, model, catalog):
        usage = OptionUsage(annual_days=point(3), annual_km=point(180))
        result = model.calculate(catalog.option("car_rental_daily"), usage)
        assert line(result, "day_charge").expected == pytest.approx(3 * 45)
        assert line(result, "energy").expected == pytest.approx(0.06 * 180 * 2.022)

    def test_flights_are_charged_per_flight(self, model, catalog):
        result = model.calculate(catalog.option("air_domestic"), OptionUsage(annual_trips=point(2)))
        assert result.total.expected == pytest.approx(180)

    def test_walking_costs_nothing(self, model, catalog):
        result = model.calculate(catalog.option("walking"), OptionUsage(annual_km=point(500)))
        assert result.total.expected == 0
        assert result.lines == []


class TestUncertainty:
    def test_range_brackets_the_expected_value(self, model, catalog):
        for option_id in ("car_small_petrol", "car_electric", "e_bike", "taxi_milano"):
            result = model.calculate(
                catalog.option(option_id),
                OptionUsage(annual_km=Range(low=4_000, expected=8_000, high=12_000)),
            )
            assert result.total.low <= result.total.expected <= result.total.high, option_id

    def test_a_single_uncertain_input_gives_exactly_its_own_range(self, model):
        option = MobilityOption.model_validate(
            {
                "id": "x",
                "name": "x",
                "type": "TAXI",
                "mode": "TAXI",
                "ownership": "PAY_PER_USE",
                "cost_per_km": 1.0,
            }
        )
        usage = OptionUsage(annual_km=Range(low=80, expected=100, high=130))
        result = model.calculate(option, usage)
        assert (result.total.low, result.total.expected, result.total.high) == (80, 100, 130)

    def test_independent_inputs_combine_in_quadrature_not_linearly(self, model, catalog):
        result = model.calculate(
            catalog.option("car_small_petrol"),
            OptionUsage(annual_km=Range(low=4_000, expected=8_000, high=12_000)),
        )
        # Worst case would stack every line's range; independent errors do not.
        assert result.total.width < sum(item.amount.width for item in result.lines)
        assert result.total.width > max(item.amount.width for item in result.lines)

    def test_the_range_is_useful_not_absurd(self, model, catalog):
        result = model.calculate(
            catalog.option("car_small_petrol"),
            OptionUsage(annual_km=point(10_000), existing_asset=True),
        )
        # With every input at its worst end at once the cost would be ~2.8x the expected one.
        assert result.total.high < 1.6 * result.total.expected

    def test_costs_are_never_negative(self, model, catalog):
        result = model.calculate(
            catalog.option("car_small_petrol"), OptionUsage(existing_asset=True)
        )
        assert result.total.low >= 0
        assert all(item.amount.low >= 0 for item in result.lines)

    def test_a_more_precise_input_narrows_the_range(self, model, catalog):
        option = catalog.option("car_small_petrol")
        vague = model.calculate(
            option, OptionUsage(annual_km=Range(low=4_000, expected=8_000, high=12_000))
        )
        exact = model.calculate(option, OptionUsage(annual_km=point(8_000)))
        assert exact.total.width < vague.total.width
        assert exact.total.expected == pytest.approx(vague.total.expected)


class TestSanityAgainstPublishedFigures:
    """Cross-checks with ISFORT and the sum.money simulator (brief section 12)."""

    def test_small_car_at_national_average_km_is_within_the_isfort_range(self, model, catalog):
        isfort = catalog.parameter("statistics.car_cost_sanity_eur_per_year")
        km = catalog.value("statistics.car_annual_km_italy_avg")
        result = model.calculate(
            catalog.option("car_small_petrol"), OptionUsage(annual_km=point(km))
        )
        assert isfort.lo <= result.total.expected <= isfort.hi

    def test_matches_the_independent_formula(self, model, catalog, naive_annual_cost):
        # conftest.naive_annual_cost computes the same TCO from scratch for a new car.

        for option_id in ("car_small_petrol", "car_medium_petrol", "car_diesel", "car_electric"):
            result = model.calculate(
                catalog.option(option_id), OptionUsage(annual_km=point(10_700))
            )
            assert result.total.expected == pytest.approx(
                naive_annual_cost(catalog, option_id, 10_700), rel=1e-9
            ), option_id
