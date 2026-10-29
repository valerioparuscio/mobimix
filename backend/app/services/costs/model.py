"""Cost model (step 6): annual cost of one mobility option for a given usage.

Total cost of ownership for owned assets, tariff cost for services (brief section 12). Every
constant comes from data/ (CLAUDE.md section 16); nothing is hard-coded here.

Components, as `CostLine` labels (EUR/year, all optional):

    depreciation      owned assets, see below
    financing         option.financing_cost_year
    insurance, tax, maintenance        option.*_cost_year
    parking           usage.parking_cost_year, else option.parking_cost_year
    subscription_fee  usage.fixed_cost_override, else option.fixed_cost_year
                      (x months_held / 12 for passes that can be bought month by month)
    energy            consumption / 100 x km x energy price
    distance_charge   cost_per_km x km
    time_charge       trips x min(minutes x per-minute, ceil(hours) x per-hour,
                                  ceil(days) x per-day)
    trip_charge       cost_per_trip x trips
    day_charge        cost_per_day x days   (options without a per-minute tariff)
    tolls             toll per km x km on toll motorways   (road vehicles)
    destination_mobility   cost per day x days of stay at a destination reached without a
                      vehicle (rail, flights)
    destination_charges    parking and access charges (Area C) paid at the destination by a car
                      left there: `usage.annual_destination_charges`, already in EUR

Fixed components are multiplied by `usage.quantity`.

Depreciation
    new purchase:         (purchase_price - residual_value) / lifetime  (linear, as in the brief)
    owned, value known:   current_value x r,  r = 1 - (residual / purchase) ^ (1 / lifetime)
    owned, value unknown: expected = value at the average age of the Italian fleet
                          (P x (1-r)^age) x r;  low = 0;  high = linear
    The unknown-value case matters: most cars on the road are old, and charging them the
    depreciation of a new car would bias the baseline against car ownership.

Uncertainty (first-order, independent inputs)
    The result is evaluated at the expected value of every input. Then each uncertain input in
    turn is moved to the low end and to the high end of its range, the others staying at their
    expected value; this gives the effect of that one input. The effects of different inputs are
    combined as a root sum of squares, on each side. The `Range` is therefore a *plausible* range
    - what happens if inputs err independently - not the worst case, in which every input is at
    its unfavourable end at once (which is practically impossible and would make ranges useless,
    e.g. 3,000-11,000 EUR for a cost of about 4,800). Inputs shared by different items (the fuel
    price) are treated as independent between items: a small underestimate of the range.

Known limitations: financing is not modelled for lack of data; tolls are charged only when the
usage says how many km are on toll motorways (the trip calculator of step 9 does; the current
portfolio of step 6 does not, as nobody declares them); per-use prices are the Milan ones;
car-sharing hourly packages are billed per started hour.
"""

import math
from typing import Literal

from app.data.loader import Catalog
from app.models import (
    CostLine,
    CostResult,
    EnergyCarrier,
    MobilityOption,
    Mode,
    OptionUsage,
    ParameterValue,
    Range,
)

End = Literal["low", "high"]

# The components that grow with use. Everything else (depreciation, insurance, tax, maintenance,
# parking, the subscription fee) is paid whether the option is used or not.
USAGE_COMPONENTS = (
    "energy",
    "distance_charge",
    "time_charge",
    "trip_charge",
    "day_charge",
    "tolls",
    "destination_mobility",
    "destination_charges",
)
FIXED_COMPONENTS = (
    "depreciation",
    "financing",
    "insurance",
    "tax",
    "maintenance",
    "parking",
    "subscription_fee",
)

MINUTES_PER_DAY = 24 * 60


class _Probe:
    """Reads the model inputs at their expected value, except for one input (`key`) that is
    pushed to one end of its range. `end` is the end of the *cost*: "low" is the end that
    lowers the cost, whatever the input (for a residual value that is its high value).

    With `seen`, it records the keys of the inputs that actually have a range."""

    def __init__(
        self, key: str | None = None, end: End | None = None, seen: set[str] | None = None
    ) -> None:
        self._key = key
        self._end = end
        self._seen = seen

    def _record(self, key: str, width: float) -> None:
        if self._seen is not None and width > 0:
            self._seen.add(key)

    def up(self, key: str, parameter: ParameterValue | None) -> float:
        """An input that raises the cost as it grows."""
        if parameter is None:
            return 0.0
        self._record(key, parameter.hi - parameter.lo)
        if key == self._key:
            return parameter.lo if self._end == "low" else parameter.hi
        return parameter.value

    def down(self, key: str, parameter: ParameterValue | None) -> float:
        """An input that lowers the cost as it grows (residual value, lifetime...)."""
        if parameter is None:
            return 0.0
        self._record(key, parameter.hi - parameter.lo)
        if key == self._key:
            return parameter.hi if self._end == "low" else parameter.lo
        return parameter.value

    def at(self, key: str, value: Range | None) -> float:
        """A usage quantity that raises the cost as it grows."""
        if value is None:
            return 0.0
        self._record(key, value.width)
        if key == self._key:
            return value.low if self._end == "low" else value.high
        return value.expected

    def choice(self, key: str, low: float, expected: float, high: float) -> float:
        """An input known only through three scenarios (cost-lowering, expected, cost-raising)."""
        self._record(key, high - low)
        if key == self._key:
            return low if self._end == "low" else high
        return expected


def _decay_rate(price: float, residual: float, lifetime: float) -> float:
    """Yearly geometric depreciation rate implied by purchase price, residual value, lifetime."""
    if price <= 0 or lifetime <= 0:
        return 0.0
    ratio = min(1.0, max(residual, 0.0) / price)
    return 1.0 - ratio ** (1.0 / lifetime)


class TcoCostModel:
    def __init__(self, catalog: Catalog) -> None:
        self._catalog = catalog

    def calculate(
        self, option: MobilityOption, usage: OptionUsage, only: tuple[str, ...] | None = None
    ) -> CostResult:
        """`only` restricts the result to some components (`FIXED_COMPONENTS`, `USAGE_COMPONENTS`):
        what an option costs to hold, or what using it costs."""
        seen: set[str] = set()
        expected = self._components(option, usage, _Probe(seen=seen))
        if only is not None:
            expected = {label: value for label, value in expected.items() if label in only}

        # Effect of each uncertain input alone, on every component.
        effects: list[tuple[dict[str, float], dict[str, float]]] = []
        for key in sorted(seen):
            low = self._components(option, usage, _Probe(key, "low"))
            high = self._components(option, usage, _Probe(key, "high"))
            effects.append(
                (
                    {label: min(0.0, low[label] - expected[label]) for label in expected},
                    {label: max(0.0, high[label] - expected[label]) for label in expected},
                )
            )

        def band(labels: list[str], centre: float) -> Range:
            down = math.sqrt(sum(sum(low[name] for name in labels) ** 2 for low, _ in effects))
            up = math.sqrt(sum(sum(high[name] for name in labels) ** 2 for _, high in effects))
            return Range(low=max(0.0, centre - down), expected=centre, high=centre + up)

        lines = [
            CostLine(label=label, option_id=option.id, amount=band([label], value))
            for label, value in expected.items()
            if abs(value) > 1e-12 or band([label], value).width > 1e-12
        ]
        total = band(list(expected), sum(expected.values()))
        return CostResult(option_id=option.id, total=total, lines=lines)

    def usage_cost(self, option: MobilityOption, usage: OptionUsage) -> float:
        """What using the option costs, on top of what it costs to own or hold it (EUR, at the
        expected value of every input). This is what a household that already has the option
        weighs when it decides whether to use it for a trip: the car's depreciation, insurance
        and parking are paid anyway, its fuel is not."""
        components = self._components(option, usage, _Probe())
        return sum(components[name] for name in USAGE_COMPONENTS)

    def expected_current_value(self, option: MobilityOption) -> float | None:
        """Market value of an owned asset of unknown age, at the average fleet age."""
        if option.purchase_price is None:
            return None
        price = option.purchase_price.value
        rate = _decay_rate(
            price,
            option.residual_value.value if option.residual_value else 0.0,
            option.expected_lifetime_years.value if option.expected_lifetime_years else 1.0,
        )
        return price * (1.0 - rate) ** self._catalog.value("statistics.car_fleet_avg_age_years")

    # --- components -------------------------------------------------------------------------

    def _components(
        self, option: MobilityOption, usage: OptionUsage, probe: _Probe
    ) -> dict[str, float]:
        quantity = usage.quantity
        km = probe.at("km", usage.annual_km)
        trips = probe.at("trips", usage.annual_trips)
        minutes = probe.at("minutes", usage.annual_minutes)
        days = probe.at("days", usage.annual_days)

        parking = (
            probe.at("parking", usage.parking_cost_year)
            if usage.parking_cost_year is not None
            else probe.up("parking_option", option.parking_cost_year)
        )
        fee = (
            probe.at("fee", usage.fixed_cost_override)
            if usage.fixed_cost_override is not None
            else probe.up("fee_option", option.fixed_cost_year)
        )
        if option.prorata_monthly:
            fee *= usage.months_held / 12.0

        return {
            "depreciation": quantity * self._depreciation(option, usage, probe),
            "financing": quantity * probe.up("financing", option.financing_cost_year),
            "insurance": quantity * probe.up("insurance", option.insurance_cost_year),
            "tax": quantity * probe.up("tax", option.tax_cost_year),
            "maintenance": quantity * probe.up("maintenance", option.maintenance_cost_year),
            "parking": quantity * parking,
            "subscription_fee": quantity * fee,
            "energy": self._energy(option, km, probe),
            "distance_charge": probe.up("cost_per_km", option.cost_per_km) * km,
            "time_charge": self._time_charge(option, trips, minutes, probe),
            "trip_charge": probe.up("cost_per_trip", option.cost_per_trip) * trips,
            "day_charge": 0.0
            if option.cost_per_minute is not None
            else probe.up("cost_per_day", option.cost_per_day) * days,
            "tolls": self._toll(option, probe.at("toll_km", usage.annual_toll_km), probe),
            "destination_mobility": self._destination_mobility(
                option, probe.at("destination_days", usage.annual_destination_days), probe
            ),
            "destination_charges": probe.at("destination_charges", usage.annual_destination_charges)
            if option.parks_at_destination
            else 0.0,
        }

    def _toll(self, option: MobilityOption, toll_km: float, probe: _Probe) -> float:
        if not option.uses_motorways:
            return 0.0
        return toll_km * probe.up(
            "toll_rate", self._catalog.parameter("usage.motorway_toll_eur_per_km")
        )

    def _destination_mobility(self, option: MobilityOption, days: float, probe: _Probe) -> float:
        if not option.no_vehicle_at_destination:
            return 0.0
        rate = self._catalog.parameter("usage.destination_mobility_eur_per_day")
        return days * probe.up("destination_mobility_rate", rate)

    def _depreciation(self, option: MobilityOption, usage: OptionUsage, probe: _Probe) -> float:
        if option.purchase_price is None:
            return 0.0
        price = probe.up("price", option.purchase_price)
        residual = probe.down("residual", option.residual_value)
        lifetime = max(probe.down("lifetime", option.expected_lifetime_years), 1e-9)
        linear = max(0.0, price - residual) / lifetime
        if not usage.existing_asset:
            return linear

        rate = _decay_rate(price, residual, lifetime)
        if usage.current_value is not None:
            return probe.at("current_value", usage.current_value) * rate
        # Already owned, value and age unknown: the prior is the average age of the fleet.
        age = self._catalog.value("statistics.car_fleet_avg_age_years")
        return probe.choice(
            "current_value_unknown", 0.0, price * (1.0 - rate) ** age * rate, linear
        )

    def _energy(self, option: MobilityOption, km: float, probe: _Probe) -> float:
        if option.energy is None:
            return 0.0
        units = probe.up("consumption", option.energy.consumption_per_100km) / 100.0 * km
        return units * self._energy_price(option, probe)

    def _energy_price(self, option: MobilityOption, probe: _Probe) -> float:
        parameter = self._catalog.parameter
        carrier = option.energy.carrier if option.energy else None
        if carrier is EnergyCarrier.PETROL:
            return probe.up("price:petrol", parameter("energy.petrol_eur_per_l"))
        if carrier is EnergyCarrier.DIESEL:
            return probe.up("price:diesel", parameter("energy.diesel_eur_per_l"))
        home = probe.up("price:home_kwh", parameter("energy.electricity_home_eur_per_kwh"))
        if option.mode is Mode.E_BIKE:
            return home  # charged at home
        # Electric car: blend of home and public charging. More home charging is cheaper;
        # more DC fast charging is dearer.
        home_share = probe.down("ev_home_share", parameter("energy.ev_home_charging_share"))
        dc_share = probe.up("ev_dc_share", parameter("energy.ev_public_dc_share"))
        dc = probe.up("price:dc_kwh", parameter("energy.electricity_public_dc_eur_per_kwh"))
        ac = probe.up("price:ac_kwh", parameter("energy.electricity_public_ac_eur_per_kwh"))
        public = dc_share * dc + (1.0 - dc_share) * ac
        return home_share * home + (1.0 - home_share) * public

    def _time_charge(
        self, option: MobilityOption, trips: float, minutes: float, probe: _Probe
    ) -> float:
        """Per-minute tariffs with hourly and daily packages: each trip pays the cheapest."""
        if option.cost_per_minute is None:
            return 0.0
        per_minute = probe.up("cost_per_minute", option.cost_per_minute)
        if trips <= 0:
            return per_minute * minutes
        duration = minutes / trips
        candidates = [per_minute * duration]
        if option.cost_per_hour is not None:
            candidates.append(
                math.ceil(duration / 60.0) * probe.up("cost_per_hour", option.cost_per_hour)
            )
        if option.cost_per_day is not None:
            candidates.append(
                max(1, math.ceil(duration / MINUTES_PER_DAY))
                * probe.up("cost_per_day", option.cost_per_day)
            )
        return trips * min(candidates)
