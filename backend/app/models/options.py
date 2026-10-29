"""Mobility options catalogue (brief section 11).

Every option - an owned car, an annual PT pass, a taxi - shares one schema. Not every
field applies to every option; unused ones stay `None`.

Cost semantics (all EUR, all optional):

* ownership:     `purchase_price`, `residual_value`, `expected_lifetime_years`
                 -> annual depreciation = (purchase_price - residual_value) / lifetime
* fixed / year:  `fixed_cost_year` (subscription fee), `maintenance_cost_year`,
                 `insurance_cost_year`, `tax_cost_year`, `parking_cost_year`,
                 `financing_cost_year`
* variable:      `energy` (consumption x energy price, priced by the cost model),
                 `cost_per_km` (everything else that scales with distance: tyres, wear,
                 or a service's distance tariff), `cost_per_minute`, `cost_per_trip`,
                 `cost_per_day`

Time semantics: door-to-door leg time = distance / `average_speed_kmh[band]`
+ `fixed_time_min_per_trip` (walking to the stop, waiting, unlocking, parking search...).

Quality scores (`comfort_score`, `flexibility_score`, `reliability_score`) are on a 0-10
scale.
"""

from datetime import date

from pydantic import Field, model_validator

from .base import DomainModel
from .enums import (
    AreaType,
    EnergyCarrier,
    Level,
    LuggageLevel,
    Mode,
    OptionType,
    Ownership,
    ServiceKind,
    TripBand,
)
from .provenance import Param


class EnergyUse(DomainModel):
    """Energy consumed per 100 km: litres for PETROL/DIESEL, kWh for ELECTRICITY.

    The price per unit is looked up by the cost model from the global parameters, so that
    what-if scenarios on fuel prices work without touching the catalogue.
    """

    carrier: EnergyCarrier
    consumption_per_100km: Param


class Emissions(DomainModel):
    """Direct CO2 factor, used when it cannot be derived from `energy` (public transport,
    rail, air...). For options with `energy`, CO2 is derived from consumption instead."""

    co2_g_per_km: Param
    basis: str = Field(
        default="passenger_km",
        pattern="^(vehicle_km|passenger_km)$",
        description="Whether the factor is per vehicle-km or per passenger-km.",
    )


class MobilityOption(DomainModel):
    id: str
    name: str
    type: OptionType
    mode: Mode
    ownership: Ownership
    description: str | None = None
    service_kind: ServiceKind | None = Field(
        default=None,
        description="For pay-per-use options: the category of declared usage (taxi trips, "
        "rental days...) this option is used to price.",
    )

    # --- costs (EUR) ---
    purchase_price: Param | None = None
    residual_value: Param | None = None
    expected_lifetime_years: Param | None = None
    fixed_cost_year: Param | None = None
    prorata_monthly: bool = Field(
        default=False,
        description="True if the fixed cost can be bought month by month (monthly PT pass): "
        "`fixed_cost_year` is then the cost of holding it for all 12 months.",
    )
    maintenance_cost_year: Param | None = None
    insurance_cost_year: Param | None = None
    tax_cost_year: Param | None = None
    parking_cost_year: Param | None = None
    financing_cost_year: Param | None = None
    energy: EnergyUse | None = None
    cost_per_km: Param | None = None
    cost_per_minute: Param | None = None
    cost_per_hour: Param | None = Field(
        default=None,
        description="Hourly package price. With cost_per_minute and cost_per_day, the cost "
        "model picks the cheapest applicable tariff (car sharing).",
    )
    cost_per_trip: Param | None = None
    cost_per_day: Param | None = None

    # --- time ---
    average_speed_kmh: dict[TripBand, Param] = Field(default_factory=dict)
    fixed_time_min_per_trip: Param | None = None

    # --- quality (0-10); stored in data/comfort_scores.yaml and merged in by the loader ---
    comfort_score: Param | None = None
    flexibility_score: Param | None = None
    reliability_score: Param | None = None

    # --- capability ---
    capacity: int | None = Field(default=None, ge=1, description="Passengers incl. driver.")
    luggage_capacity: LuggageLevel = LuggageLevel.NONE
    max_practical_distance_km: Param | None = Field(
        default=None, description="Longest one-way leg for which the option is realistic."
    )
    min_practical_distance_km: Param | None = Field(
        default=None,
        description="Shortest one-way leg for which the option is realistic (a flight or a "
        "high-speed train for 8 km is not an option).",
    )
    weather_sensitivity: Level = Level.LOW
    uses_motorways: bool = Field(
        default=False,
        description="True for road vehicles that drive on toll motorways (and pay the toll).",
    )
    parks_at_destination: bool = Field(
        default=False,
        description="True for cars (owned or rented) that are left at the destination and so "
        "pay its parking and access charges (Area C...). Car sharing, taxis and two-wheelers "
        "do not: they park free in the city or do not park at all.",
    )
    no_vehicle_at_destination: bool = Field(
        default=False,
        description="True for rail and flights: the traveller arrives without a vehicle and "
        "has to get around at the destination, which costs money on a stay.",
    )

    # --- availability ---
    geographic_scope: str = "IT"
    available_in_area_types: list[AreaType] = Field(
        default_factory=lambda: list(AreaType),
        description="Residential contexts where the option exists (e.g. car sharing only in "
        "city centres). Placeholder for the richer CII-based availability model.",
    )
    requires_license: bool = False
    min_age: int | None = None
    max_age: int | None = None
    valid_from: date | None = None
    valid_to: date | None = None

    # --- environment ---
    emissions: Emissions | None = None

    notes: str | None = None

    @model_validator(mode="after")
    def _check_consistency(self) -> "MobilityOption":
        has_depreciation_input = self.purchase_price is not None
        if has_depreciation_input and (
            self.residual_value is None or self.expected_lifetime_years is None
        ):
            raise ValueError(
                f"{self.id}: purchase_price requires residual_value and expected_lifetime_years"
            )
        if self.expected_lifetime_years is not None and self.expected_lifetime_years.value <= 0:
            raise ValueError(f"{self.id}: expected_lifetime_years must be positive")
        if (
            self.purchase_price is not None
            and self.residual_value is not None
            and self.residual_value.value > self.purchase_price.value
        ):
            raise ValueError(f"{self.id}: residual_value exceeds purchase_price")
        for name in ("comfort_score", "flexibility_score", "reliability_score"):
            score = getattr(self, name)
            if score is not None and not 0 <= score.value <= 10:
                raise ValueError(f"{self.id}: {name} must be within 0-10")
        if self.min_age is not None and self.max_age is not None and self.min_age > self.max_age:
            raise ValueError(f"{self.id}: min_age exceeds max_age")
        return self

    @property
    def is_owned(self) -> bool:
        return self.ownership is Ownership.OWNED


class OptionScores(DomainModel):
    """Comfort / flexibility / reliability of one option, 0-10 (data/comfort_scores.yaml).

    Kept apart from the catalogue because these scores are subjective modelling choices,
    not measurable prices, and are expected to be revised often.
    """

    comfort: float = Field(ge=0, le=10)
    flexibility: float = Field(ge=0, le=10)
    reliability: float = Field(ge=0, le=10)
    notes: str | None = None
