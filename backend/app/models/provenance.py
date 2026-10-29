"""Value provenance and uncertainty (brief sections 8, 9 and 23).

Three layers, from the outside in:

* `NumericAnswer`   - what the user told us (exact value, approximate range, or "I don't know").
* `Estimated`       - a model input after reconstruction: value + range + source + confidence.
* `Range`           - a model output: low / expected / high.

`ParameterValue`, `ModelParameter` and `DataSourceMetadata` describe the numbers in the
editable data files under `data/`.
"""

import math
from collections.abc import Iterable
from datetime import date
from enum import StrEnum
from typing import Annotated, Any, Literal, Self

from pydantic import BeforeValidator, model_validator

from .base import DomainModel


class ValueSource(StrEnum):
    DECLARED_EXACT = "DECLARED_EXACT"
    DECLARED_APPROXIMATE = "DECLARED_APPROXIMATE"
    INFERRED = "INFERRED"  # derived from other answers
    STATISTICAL_ESTIMATE = "STATISTICAL_ESTIMATE"
    DEFAULT = "DEFAULT"
    OBSERVED = "OBSERVED"  # future: odometer, receipts, traces


class Confidence(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class NumericAnswer(DomainModel):
    """A numeric questionnaire answer: an exact value, an approximate range, or unknown.

    An empty answer means "I don't know" and triggers statistical estimation.
    """

    exact: float | None = None
    low: float | None = None
    high: float | None = None

    @model_validator(mode="after")
    def _check_shape(self) -> Self:
        has_range = self.low is not None or self.high is not None
        if self.exact is not None and has_range:
            raise ValueError("give either an exact value or a range, not both")
        if has_range:
            if self.low is None or self.high is None:
                raise ValueError("a range needs both low and high")
            if self.low > self.high:
                raise ValueError("range low must not exceed high")
        return self

    @property
    def kind(self) -> Literal["exact", "range", "unknown"]:
        if self.exact is not None:
            return "exact"
        if self.low is not None:
            return "range"
        return "unknown"

    @property
    def midpoint(self) -> float | None:
        if self.exact is not None:
            return self.exact
        if self.low is not None and self.high is not None:
            return (self.low + self.high) / 2
        return None

    @classmethod
    def of(cls, value: float) -> Self:
        return cls(exact=value)

    @classmethod
    def between(cls, low: float, high: float) -> Self:
        return cls(low=low, high=high)


class Estimated(DomainModel):
    """A model input with provenance: `value`, a plausible `low`..`high` range, where it
    came from, and how far to trust it. The system must never present a statistical
    estimate as a precise observation."""

    value: float
    low: float | None = None
    high: float | None = None
    source: ValueSource
    confidence: Confidence
    notes: str | None = None

    @model_validator(mode="after")
    def _normalise_range(self) -> Self:
        if self.low is None:
            self.low = self.value
        if self.high is None:
            self.high = self.value
        if not self.low <= self.value <= self.high:
            raise ValueError("expected low <= value <= high")
        return self

    @classmethod
    def exact(cls, value: float, notes: str | None = None) -> Self:
        return cls(
            value=value,
            source=ValueSource.DECLARED_EXACT,
            confidence=Confidence.HIGH,
            notes=notes,
        )


class Range(DomainModel):
    """A model output with uncertainty: `expected` between `low` and `high`.

    The MVP propagates uncertainty with simple interval arithmetic: every input
    contributes its low/high and the outputs are computed at the three points.
    """

    low: float
    expected: float
    high: float

    @model_validator(mode="after")
    def _check_order(self) -> Self:
        if not self.low <= self.expected <= self.high:
            raise ValueError("expected low <= expected <= high")
        return self

    @classmethod
    def point(cls, value: float) -> Self:
        return cls(low=value, expected=value, high=value)

    def __add__(self, other: "Range") -> "Range":
        return Range(
            low=self.low + other.low,
            expected=self.expected + other.expected,
            high=self.high + other.high,
        )

    def __sub__(self, other: "Range") -> "Range":
        """Conservative interval difference (worst case on both ends). Used for deltas
        against the current portfolio, e.g. the annual saving range."""
        return Range(
            low=self.low - other.high,
            expected=self.expected - other.expected,
            high=self.high - other.low,
        )

    @classmethod
    def sum_independent(cls, ranges: "Iterable[Range]", *, non_negative: bool = True) -> "Range":
        """Sum of quantities whose errors are independent: the expected values add, the
        distances to the ends combine as a root sum of squares (not linearly, as in `+`).
        `non_negative=False` for sums that may be negative (differences, savings)."""
        items = list(ranges)
        expected = sum(r.expected for r in items)
        down = math.sqrt(sum((r.expected - r.low) ** 2 for r in items))
        up = math.sqrt(sum((r.high - r.expected) ** 2 for r in items))
        low = max(0.0, expected - down) if non_negative else expected - down
        return cls(low=low, expected=expected, high=expected + up)

    def negated(self) -> "Range":
        return Range(low=-self.high, expected=-self.expected, high=-self.low)

    def minus_independent(self, other: "Range") -> "Range":
        """Difference of two quantities whose errors are independent: the expected values
        subtract, the distances to the ends combine as a root sum of squares. Narrower than `-`,
        which takes the worst case on both ends; the result may be negative (a saving)."""
        expected = self.expected - other.expected
        down = math.hypot(self.expected - self.low, other.high - other.expected)
        up = math.hypot(self.high - self.expected, other.expected - other.low)
        return Range(low=expected - down, expected=expected, high=expected + up)

    @property
    def width(self) -> float:
        return self.high - self.low

    def times(self, other: "Range") -> "Range":
        """Product of two non-negative ranges."""
        if self.low < 0 or other.low < 0:
            raise ValueError("times() is defined for non-negative ranges")
        return Range(
            low=self.low * other.low,
            expected=self.expected * other.expected,
            high=self.high * other.high,
        )

    def times_independent(self, other: "Range") -> "Range":
        """Product of two non-negative quantities whose errors are independent (number of uses x
        size of one use): first-order propagation, the two relative errors add in quadrature.
        Narrower than `times`, which multiplies the worst cases."""
        if self.low < 0 or other.low < 0:
            raise ValueError("times_independent() is defined for non-negative ranges")
        expected = self.expected * other.expected
        down = math.hypot(
            other.expected * (self.expected - self.low),
            self.expected * (other.expected - other.low),
        )
        up = math.hypot(
            other.expected * (self.high - self.expected),
            self.expected * (other.high - other.expected),
        )
        return Range(low=max(0.0, expected - down), expected=expected, high=expected + up)

    def scale_signed(self, factor: float) -> "Range":
        """Multiply by any scalar; a negative one swaps the ends."""
        return self.scale(factor) if factor >= 0 else self.negated().scale(-factor)

    def scale(self, factor: float) -> "Range":
        """Multiply by a non-negative scalar."""
        if factor < 0:
            raise ValueError("scale factor must be non-negative")
        return Range(
            low=self.low * factor,
            expected=self.expected * factor,
            high=self.high * factor,
        )


# --- editable data files -------------------------------------------------------------


class DataSourceMetadata(DomainModel):
    """A bibliographic source, referenced by `source_id` from parameters and options."""

    id: str
    name: str
    publisher: str | None = None
    url: str | None = None
    retrieved_on: date | None = None
    notes: str | None = None


class ParameterValue(DomainModel):
    """One number of the model with its provenance (brief section 9, CLAUDE.md section 17).

    `source` is the id of an entry in `data/sources.yaml`. `placeholder=True` marks a
    value that is a stand-in to be replaced (or confirmed) later; placeholders and
    unsourced values are listed by `python -m app.data.audit`.

    A bare number in a YAML file is accepted as shorthand and means: value only, LOW
    confidence, no source - i.e. an unsourced assumption.
    """

    value: float
    low: float | None = None
    high: float | None = None
    confidence: Confidence = Confidence.LOW
    source: str | None = None
    placeholder: bool = False
    notes: str | None = None

    @model_validator(mode="after")
    def _check_range(self) -> Self:
        if self.low is not None and self.low > self.value:
            raise ValueError("low must not exceed value")
        if self.high is not None and self.high < self.value:
            raise ValueError("high must not exceed value")
        return self

    @property
    def lo(self) -> float:
        return self.value if self.low is None else self.low

    @property
    def hi(self) -> float:
        return self.value if self.high is None else self.high

    def as_range(self) -> Range:
        return Range(low=self.lo, expected=self.value, high=self.hi)


def _coerce_param(raw: Any) -> Any:
    """Accept a bare number as shorthand for `ParameterValue(value=number)`."""
    if isinstance(raw, int | float) and not isinstance(raw, bool):
        return {"value": raw}
    return raw


Param = Annotated[ParameterValue, BeforeValidator(_coerce_param)]
"""A `ParameterValue` that may be written as a bare number in the data files."""


class ModelParameter(ParameterValue):
    """A named, global model parameter (fuel prices, statistical defaults, ...)."""

    id: str
    description: str | None = None
    unit: str | None = None
    geographic_scope: str = "IT"
    valid_from: date | None = None
    valid_to: date | None = None
