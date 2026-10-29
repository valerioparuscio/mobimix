"""Default characteristics of each kind of mission (data/mission_templates.yaml)."""

from pydantic import Field

from .base import DomainModel
from .enums import Level, LuggageLevel, PassengerRule, TimeBand
from .provenance import Param


class MissionTemplate(DomainModel):
    """What a mission of a given purpose typically looks like. The demand estimator combines
    it with the user's answers and the statistical defaults."""

    legs_per_occurrence: int = Field(ge=1)
    passengers: PassengerRule
    luggage: LuggageLevel
    time_critical: bool = False
    start_time_window: TimeBand = TimeBand.ANY
    duration_tolerance: Level
    weather_sensitivity: Level
    days_away: Param | None = Field(
        default=None, description="Days spent at the destination (0 for day trips)."
    )
    placeholder: bool = Field(
        default=False, description="True if these characteristics are a stand-in to confirm."
    )
    notes: str | None = None
