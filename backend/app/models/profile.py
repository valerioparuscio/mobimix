"""User profile: what the user tells us (brief section 7).

Everything numeric the user may not know is a `NumericAnswer`: exact, approximate range or
unknown. The demand estimator turns these into `Estimated` values with provenance.

Privacy by design (CLAUDE.md section 37): no names, no addresses; age bands and coarse
residential context only. `UserProfile.id` is a random identifier, not an account.
"""

from typing import Self
from uuid import uuid4

from pydantic import Field, model_validator

from .base import DomainModel
from .demand import MobilityMission
from .enums import (
    AccessibilityConstraint,
    AgeRange,
    AreaType,
    FamilyLogistic,
    Frequency,
    IncomeBand,
    Level,
    Occupation,
    ProfileMode,
    TimeBand,
)
from .provenance import NumericAnswer


class Location(DomainModel):
    """Coarse residential context.

    The Car Independence Index is an optional contextual prior, never a deterministic
    rule (brief section 13). Its scale is defined by the dataset that provides it.
    """

    area_type: AreaType
    municipality: str | None = None
    istat_code: str | None = None
    car_independence_index: float | None = None
    pt_quality: Level | None = None
    sharing_availability: Level | None = None


class WorkPattern(DomainModel):
    """Regular work or study trips of one person.

    Physical commuting days per week = `days_per_week` - `remote_days_per_week`.
    """

    one_way_distance_km: NumericAnswer = Field(default_factory=NumericAnswer)
    days_per_week: NumericAnswer = Field(default_factory=NumericAnswer)
    remote_days_per_week: NumericAnswer = Field(default_factory=NumericAnswer)
    time_critical: bool = False
    typical_start: TimeBand = TimeBand.MORNING_PEAK


class Person(DomainModel):
    """An adult member of the household. Children are counted, not modelled individually."""

    id: str
    age_range: AgeRange | None = None
    has_license: bool = True
    occupation: Occupation = Occupation.WORKER
    work_or_study: WorkPattern | None = None
    accessibility_constraints: list[AccessibilityConstraint] = Field(default_factory=list)


class OwnedVehicle(DomainModel):
    """A vehicle the household currently owns, linked to the catalogue by `option_id`."""

    id: str
    option_id: str
    primary_user_id: str | None = None
    annual_km: NumericAnswer = Field(default_factory=NumericAnswer)
    parking_cost_year: NumericAnswer = Field(default_factory=NumericAnswer)
    current_value: NumericAnswer = Field(
        default_factory=NumericAnswer,
        description="Present market value (EUR). Depreciation of a car already owned is "
        "based on this, not on its original price.",
    )


class HeldSubscription(DomainModel):
    """A subscription currently held, linked to the catalogue by `option_id`."""

    id: str
    option_id: str
    holder_id: str | None = None
    annual_cost: NumericAnswer = Field(
        default_factory=NumericAnswer,
        description="What the user actually pays per year, if different from the catalogue.",
    )


class OtherMobility(DomainModel):
    """Everything that is not work/study: approximate and optional."""

    local_non_work_trips_per_week: NumericAnswer = Field(default_factory=NumericAnswer)
    weekend_trips_per_year: NumericAnswer = Field(default_factory=NumericAnswer)
    weekend_trip_distance_km_one_way: NumericAnswer = Field(default_factory=NumericAnswer)
    long_distance_weekends_per_year: NumericAnswer = Field(default_factory=NumericAnswer)
    holiday_trips_per_year: NumericAnswer = Field(default_factory=NumericAnswer)
    holiday_distance_km_one_way: NumericAnswer = Field(default_factory=NumericAnswer)
    rail_trips_per_year: NumericAnswer = Field(default_factory=NumericAnswer)
    flights_per_year: NumericAnswer = Field(default_factory=NumericAnswer)
    taxi_trips_per_year: NumericAnswer = Field(default_factory=NumericAnswer)
    car_sharing_trips_per_year: NumericAnswer = Field(default_factory=NumericAnswer)
    car_rental_days_per_year: NumericAnswer = Field(default_factory=NumericAnswer)
    bike_scooter_sharing_trips_per_year: NumericAnswer = Field(default_factory=NumericAnswer)


class Preferences(DomainModel):
    """How much the user cares about each dimension, 0 (ignore) to 5 (very important).

    The two values-based dimensions default to 0: MobiMix stays neutral unless the user
    explicitly asks for car-dependence or sustainability to count (CLAUDE.md section 7).
    """

    save_money: int = Field(default=3, ge=0, le=5)
    reduce_travel_time: int = Field(default=3, ge=0, le=5)
    comfort: int = Field(default=3, ge=0, le=5)
    flexibility: int = Field(default=3, ge=0, le=5)
    reduce_car_dependence: int = Field(default=0, ge=0, le=5)
    sustainability: int = Field(default=0, ge=0, le=5)


class Household(DomainModel):
    adults: list[Person] = Field(min_length=1)
    n_children: int = Field(default=0, ge=0)
    location: Location
    income_band: IncomeBand | None = None
    family_logistics: list[FamilyLogistic] = Field(default_factory=list)
    simultaneous_car_need: Frequency | None = Field(
        default=None,
        description="How often two household members need a car at the same time. Asked only "
        "when the household owns two or more cars.",
    )

    @property
    def n_adults(self) -> int:
        return len(self.adults)

    @property
    def n_licensed_drivers(self) -> int:
        return sum(1 for person in self.adults if person.has_license)

    @model_validator(mode="after")
    def _unique_person_ids(self) -> Self:
        ids = [person.id for person in self.adults]
        if len(ids) != len(set(ids)):
            raise ValueError("person ids must be unique within a household")
        return self


class UserProfile(DomainModel):
    """The complete, serialisable input of an analysis."""

    schema_version: str = "1"
    id: str = Field(default_factory=lambda: uuid4().hex)
    mode: ProfileMode = ProfileMode.QUICK
    household: Household
    vehicles: list[OwnedVehicle] = Field(default_factory=list)
    subscriptions: list[HeldSubscription] = Field(default_factory=list)
    other_mobility: OtherMobility = Field(default_factory=OtherMobility)
    preferences: Preferences = Field(default_factory=Preferences)
    declared_missions: list[MobilityMission] = Field(
        default_factory=list,
        description="Detailed mode: missions given directly by the user. They take "
        "precedence over missions the estimator would derive for the same purpose.",
    )

    @model_validator(mode="after")
    def _check_references(self) -> Self:
        person_ids = {person.id for person in self.household.adults}
        for vehicle in self.vehicles:
            if vehicle.primary_user_id is not None and vehicle.primary_user_id not in person_ids:
                raise ValueError(f"vehicle {vehicle.id}: unknown primary_user_id")
        for subscription in self.subscriptions:
            if subscription.holder_id is not None and subscription.holder_id not in person_ids:
                raise ValueError(f"subscription {subscription.id}: unknown holder_id")
        for mission in self.declared_missions:
            if mission.person_id is not None and mission.person_id not in person_ids:
                raise ValueError(f"mission {mission.id}: unknown person_id")
        return self
