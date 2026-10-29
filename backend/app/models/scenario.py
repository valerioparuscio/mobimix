"""What-if scenarios (CLAUDE.md section 27): a few assumptions the household can change to see
what would happen, without changing its answers.

Every field is a *change* from today, and zero means "as it is": the neutral scenario is the
analysis itself. Changes are fractions (0.2 is +20%), so the same slider makes sense for every
household whatever its starting point. The bounds are what the screen offers and what the model
is meant to be asked; outside them a result would say more than the model knows.
"""

from pydantic import Field

from .base import DomainModel


class Scenario(DomainModel):
    extra_remote_days_per_week: float = Field(
        default=0.0,
        ge=0,
        le=4,
        description="Days a week more than today that every adult who commutes works from home "
        "(never more than they work). Fewer commuting trips.",
    )
    fuel_price_change: float = Field(
        default=0.0,
        ge=-0.5,
        le=1.0,
        description="Change of the price of petrol and diesel (not electricity).",
    )
    parking_cost_change: float = Field(
        default=0.0,
        ge=-1.0,
        le=2.0,
        description="Change of what a car costs to park, for the cars owned and for one bought. "
        "-1 is free parking.",
    )
    car_km_change: float = Field(
        default=0.0,
        ge=-0.5,
        le=1.0,
        description="Change of the kilometres a year the household's cars drive, declared or "
        "estimated. It changes what the cars cost today and so what selling one saves; the "
        "trips the household needs are not changed.",
    )
    ebike_subsidy_eur: float = Field(
        default=0.0,
        ge=0,
        le=2000,
        description="Incentive on the purchase of a new e-bike, in EUR (never below its resale "
        "value).",
    )

    @property
    def is_neutral(self) -> bool:
        return not any(self.model_dump().values())
