"""Mobility needs (brief sections 3 and 10).

A `MobilityMission` is a recurring or occasional *need*, independent of the mode that will
serve it. Annual demand is a list of missions, never just "annual km": 1,000 km of
commuting and 1,000 km of family holidays are different needs.

Distance convention: `distance_km_one_way` is the length of one leg; one occurrence of a
mission is `legs_per_occurrence` legs (2 for a round trip, e.g. a commute day or a weekend
away). Annual km = occurrences x legs x distance.
"""

from pydantic import Field

from .base import DomainModel
from .enums import (
    AccessibilityConstraint,
    Level,
    LuggageLevel,
    Purpose,
    ServiceKind,
    TimeBand,
)
from .provenance import Confidence, Estimated, ValueSource


class MobilityMission(DomainModel):
    id: str
    person_id: str | None = Field(
        default=None, description="None for household-level missions (a family weekend)."
    )
    purpose: Purpose
    occurrences_per_year: Estimated
    distance_km_one_way: Estimated
    legs_per_occurrence: int = Field(default=2, ge=1)
    days_away: float = Field(
        default=0.0,
        ge=0,
        description="Days the travellers stay at the destination; drives rental/holiday logic.",
    )
    passengers: int = Field(default=1, ge=1, description="People travelling together.")
    children: int = Field(default=0, ge=0, description="Of which children.")
    luggage: LuggageLevel = LuggageLevel.NONE
    time_critical: bool = False
    start_time_window: TimeBand = TimeBand.ANY
    destination_car_cost: Estimated | None = Field(
        default=None,
        description="What a car arriving at the destination pays for one occurrence (EUR): "
        "parking, Area C. None when the mission has no such cost or nothing is known.",
    )
    duration_tolerance: Level = Level.MEDIUM
    weather_sensitivity: Level = Level.MEDIUM
    accessibility_requirements: list[AccessibilityConstraint] = Field(default_factory=list)

    @property
    def annual_legs(self) -> float:
        return self.occurrences_per_year.value * self.legs_per_occurrence

    @property
    def annual_km(self) -> float:
        return self.annual_legs * self.distance_km_one_way.value


class ServiceUsage(DomainModel):
    """Declared or estimated current usage of a pay-per-use service in a year.

    This is NOT extra demand: a taxi trip serves a need that is already among the missions.
    It records how the household serves its needs today, and feeds the cost of the current
    portfolio and the baseline mode assignment.
    """

    service: ServiceKind
    annual_amount: Estimated
    unit: str = Field(pattern="^(trips|days)$")


class EstimationNote(DomainModel):
    """Something the estimator had to estimate or assume, and how far to trust it.

    `subject` and `field` are stable identifiers (e.g. "p1", "commute_distance_km") so later
    steps can tell which missing answer would improve the result most.
    """

    subject: str
    field: str
    source: ValueSource
    confidence: Confidence
    message: str = Field(description="Plain-language explanation, in Italian.")


class MobilityDemand(DomainModel):
    """The household's annual mobility needs, as produced by a `DemandEstimator`."""

    profile_id: str
    missions: list[MobilityMission]
    simultaneous_car_need_days: Estimated | None = Field(
        default=None,
        description="Days per year on which two household members need a car at the same "
        "time. MVP stand-in for explicit schedules.",
    )
    current_service_usage: list[ServiceUsage] = Field(default_factory=list)
    assumptions: list[EstimationNote] = Field(
        default_factory=list,
        description="What was estimated or defaulted instead of declared, and why.",
    )
    random_seed: int | None = Field(
        default=None, description="Seed used by any stochastic estimation, for reproducibility."
    )

    @property
    def total_annual_km(self) -> float:
        return sum(mission.annual_km for mission in self.missions)

    def annual_km_by_purpose(self) -> dict[Purpose, float]:
        totals: dict[Purpose, float] = {}
        for mission in self.missions:
            totals[mission.purpose] = totals.get(mission.purpose, 0.0) + mission.annual_km
        return totals
