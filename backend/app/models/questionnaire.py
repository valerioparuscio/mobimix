"""Answer bands of the questionnaire (data/questionnaire.yaml).

Numeric questions are answered with an exact value, a band or "I don't know" (brief
section 4). A band is a labelled range; choosing one sends a `NumericAnswer` range to the
backend. Bands that translate words into numbers ("rarely", "often") are modelling
assumptions, so they live in data and can be flagged as placeholders.
"""

from typing import Self

from pydantic import Field, model_validator

from .base import DomainModel


class Band(DomainModel):
    id: str
    label: str = Field(description="Text shown to the user (Italian).")
    low: float
    high: float

    @model_validator(mode="after")
    def _check_order(self) -> Self:
        if self.low > self.high:
            raise ValueError(f"band {self.id}: low must not exceed high")
        return self


class BandGroup(DomainModel):
    """The bands offered for one question. A band with low == high is an exact answer."""

    description: str | None = None
    unit: str | None = None
    placeholder: bool = False
    notes: str | None = None
    bands: list[Band] = Field(min_length=2)

    @model_validator(mode="after")
    def _check_bands(self) -> Self:
        ids = [band.id for band in self.bands]
        if len(ids) != len(set(ids)):
            raise ValueError("band ids must be unique within a group")
        lows = [band.low for band in self.bands]
        if lows != sorted(lows):
            raise ValueError("bands must be listed in ascending order")
        return self


class QuestionnaireConfig(DomainModel):
    groups: dict[str, BandGroup]
