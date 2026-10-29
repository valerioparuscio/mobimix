"""What-if scenarios: the profile and the reference data, changed as the scenario says.

    apply_scenario(catalog, profile, scenario) -> (catalog, profile)

Nothing is changed in place: both come back as copies, so the analysis of today and of a scenario
can sit side by side. What each control does:

    extra remote days   each adult who commutes works that many more days from home, never more
                        than the days they work (an unknown number of remote days counts as 0, as
                        in the demand estimator). Fewer commuting occurrences, so fewer trips.
    fuel price          the petrol and diesel prices of the parameters, value and range.
    parking cost        the parking cost a year of every car the household owns, as declared; and
                        the statistical defaults: an undeclared cost, the cost of a car bought,
                        and what a car pays for parking and Area C at the workplace and on a
                        shopping or leisure trip in town.
    car km              the kilometres a year of every car, as declared, and the statistical
                        defaults for an undeclared one. The missions do not change.
    e-bike subsidy      the purchase price of the e-bike the generator proposes; never below its
                        resale value. It lowers the yearly depreciation of a new e-bike by
                        subsidy / lifetime, and nothing for one the household already has.

An answer the household did not give stays unknown (so its confidence is not raised by a what-if);
what changes is the default that stands in for it.
"""

from dataclasses import replace

from app.data.loader import Catalog
from app.models import (
    Mode,
    NumericAnswer,
    ParameterValue,
    Scenario,
    UserProfile,
)

FUEL_PRICE_PARAMETERS = ("energy.petrol_eur_per_l", "energy.diesel_eur_per_l")
_PARKING_DEFAULTS = (
    "parking_cost_year_per_car",
    "workplace_car_cost_per_day",
    "local_trip_car_cost",
)
_CAR_KM_DEFAULTS = ("car_annual_km_first", "car_annual_km_second")


def _scaled[T: ParameterValue](parameter: T, factor: float) -> T:
    return parameter.model_copy(
        update={
            "value": parameter.value * factor,
            "low": None if parameter.low is None else parameter.low * factor,
            "high": None if parameter.high is None else parameter.high * factor,
        }
    )


def _scaled_answer(answer: NumericAnswer, factor: float) -> NumericAnswer:
    """A declared number, changed; "I don't know" stays unknown."""
    if answer.exact is not None:
        return NumericAnswer(exact=answer.exact * factor)
    if answer.low is not None and answer.high is not None:
        return NumericAnswer(low=answer.low * factor, high=answer.high * factor)
    return answer


def apply_scenario(
    catalog: Catalog, profile: UserProfile, scenario: Scenario
) -> tuple[Catalog, UserProfile]:
    profile = profile.model_copy(deep=True)
    parameters = dict(catalog.parameters)
    area_defaults = dict(catalog.area_defaults)
    options = dict(catalog.options)

    if scenario.fuel_price_change:
        for parameter_id in FUEL_PRICE_PARAMETERS:
            parameters[parameter_id] = _scaled(
                parameters[parameter_id], 1 + scenario.fuel_price_change
            )

    parking, kilometres = 1 + scenario.parking_cost_change, 1 + scenario.car_km_change
    if scenario.parking_cost_change or scenario.car_km_change:
        for area, defaults in catalog.area_defaults.items():
            values = dict(defaults.values)
            for key in _PARKING_DEFAULTS:
                values[key] = _scaled(values[key], parking)
            for key in _CAR_KM_DEFAULTS:
                values[key] = _scaled(values[key], kilometres)
            area_defaults[area] = defaults.model_copy(update={"values": values})
        for vehicle in profile.vehicles:
            if catalog.option(vehicle.option_id).mode is Mode.CAR:
                vehicle.parking_cost_year = _scaled_answer(vehicle.parking_cost_year, parking)
                vehicle.annual_km = _scaled_answer(vehicle.annual_km, kilometres)

    if scenario.extra_remote_days_per_week:
        default_days = catalog.defaults_for(profile.household.location.area_type).values[
            "work_days_per_week"
        ]
        for person in profile.household.adults:
            work = person.work_or_study
            if work is None:
                continue
            days = work.days_per_week.midpoint
            remote = work.remote_days_per_week.midpoint
            worked = default_days.value if days is None else days
            work.remote_days_per_week = NumericAnswer.of(
                min(worked, (remote or 0.0) + scenario.extra_remote_days_per_week)
            )

    if scenario.ebike_subsidy_eur:
        option_id = catalog.portfolio_rules.new_vehicles.e_bike
        ebike = options[option_id]
        price, resale = ebike.purchase_price, ebike.residual_value
        if price is not None and resale is not None:
            cut = min(scenario.ebike_subsidy_eur, max(0.0, price.value - resale.value))
            options[option_id] = ebike.model_copy(
                update={
                    "purchase_price": price.model_copy(
                        update={
                            "value": price.value - cut,
                            "low": None if price.low is None else max(0.0, price.low - cut),
                            "high": None if price.high is None else price.high - cut,
                        }
                    )
                }
            )

    return replace(
        catalog, parameters=parameters, area_defaults=area_defaults, options=options
    ), profile
