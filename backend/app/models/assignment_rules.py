"""Tables of the mode assignment (data/assignment_rules.yaml).

How long a traveller stays at the destination for each kind of mission, how much the weather
weighs on a mission of each sensitivity, and which trips are made in the rush hours and which
modes the traffic slows down. The numeric tunables (scale of the choice, discomfort weight,
bad-weather share, speed in the rush hours) live with the other model parameters (`assignment.*`).
"""

from typing import Self

from pydantic import Field, model_validator

from .base import DomainModel
from .enums import Level, Mode, Purpose, TimeBand


class AssignmentRules(DomainModel):
    stay_hours_by_purpose: dict[Purpose, float]
    weather_factor: dict[Level, float]
    peak_windows: list[TimeBand] = Field(
        default_factory=list,
        description="Start times of the trips that meet the rush-hour traffic.",
    )
    congestion_exposure: dict[Mode, float] = Field(
        default_factory=dict,
        description="Share (0-1) of the rush-hour slowdown a mode suffers; a mode that is not "
        "listed is not slowed down.",
    )
    placeholder: bool = Field(
        default=False,
        description="True if the rules are a stand-in the developer has not reviewed.",
    )

    @model_validator(mode="after")
    def _complete_and_sensible(self) -> Self:
        missing = set(Purpose) - self.stay_hours_by_purpose.keys()
        if missing:
            raise ValueError(f"stay_hours_by_purpose: missing purposes {sorted(missing)}")
        missing_levels = set(Level) - self.weather_factor.keys()
        if missing_levels:
            raise ValueError(f"weather_factor: missing levels {sorted(missing_levels)}")
        if any(hours < 0 for hours in self.stay_hours_by_purpose.values()):
            raise ValueError("stay_hours_by_purpose: hours cannot be negative")
        if any(factor < 0 for factor in self.weather_factor.values()):
            raise ValueError("weather_factor: factors cannot be negative")
        if any(not 0.0 <= share <= 1.0 for share in self.congestion_exposure.values()):
            raise ValueError("congestion_exposure: shares must be between 0 and 1")
        return self
