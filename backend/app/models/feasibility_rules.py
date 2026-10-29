"""Categorical rules of the feasibility check (data/feasibility_rules.yaml).

Which means are for the occasional trip only, which cannot carry children, which are not in
service at night, which a person with a given constraint cannot use. The numeric thresholds
live with the other model parameters (`feasibility.*` in model_parameters.yaml).
"""

from pydantic import Field

from .base import DomainModel
from .enums import AccessibilityConstraint, Mode, OptionType, TimeBand


class FeasibilityRules(DomainModel):
    occasional_only_types: list[OptionType] = Field(default_factory=list)
    modes_not_with_children: list[Mode] = Field(default_factory=list)
    unavailable_time_bands: dict[Mode, list[TimeBand]] = Field(default_factory=dict)
    accessibility_exclusions: dict[AccessibilityConstraint, list[Mode]] = Field(
        default_factory=dict
    )
    placeholder: bool = Field(
        default=False,
        description="True if the rules are a stand-in the developer has not reviewed.",
    )
