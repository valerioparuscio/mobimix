"""Building `Estimated` values with honest provenance (brief section 8, CLAUDE.md section 11).

Rules, in one place so they are easy to inspect and change:

* A value the user gave is DECLARED_EXACT (HIGH confidence) or DECLARED_APPROXIMATE (a range
  or band, MEDIUM); the midpoint is the value, the ends are the range.
* A missing value falls back to a statistical default: STATISTICAL_ESTIMATE, with the default's
  own confidence - and LOW whenever the default is still a placeholder.
* A value computed from others is INFERRED if every ingredient is declared or inferred;
  otherwise it inherits the weakest ingredient's source. Its confidence is the lowest of its
  ingredients', including the model constants it uses (calendar, shares...).
* Ranges propagate by interval arithmetic on non-negative quantities.
"""

from collections.abc import Iterable, Sequence

from app.models import (
    AreaType,
    Confidence,
    Estimated,
    NumericAnswer,
    ParameterValue,
    ValueSource,
)

# Wording used in user-facing notes.
AREA_NAMES = {
    AreaType.CITY_CENTER: "il centro città",
    AreaType.URBAN: "la città",
    AreaType.SUBURBAN: "la cintura",
    AreaType.PERIPHERAL: "la periferia o la campagna",
}
CONFIDENCE_WORDS = {
    Confidence.LOW: "bassa",
    Confidence.MEDIUM: "media",
    Confidence.HIGH: "alta",
}

_CONFIDENCE_RANK = {Confidence.LOW: 0, Confidence.MEDIUM: 1, Confidence.HIGH: 2}

# Strongest first.
_SOURCE_RANK = {
    ValueSource.OBSERVED: 0,
    ValueSource.DECLARED_EXACT: 1,
    ValueSource.DECLARED_APPROXIMATE: 2,
    ValueSource.INFERRED: 3,
    ValueSource.STATISTICAL_ESTIMATE: 4,
    ValueSource.DEFAULT: 5,
}
_DERIVABLE_SOURCES = {
    ValueSource.OBSERVED,
    ValueSource.DECLARED_EXACT,
    ValueSource.DECLARED_APPROXIMATE,
    ValueSource.INFERRED,
}


def weakest_confidence(values: Iterable[Confidence]) -> Confidence:
    return min(values, key=_CONFIDENCE_RANK.__getitem__, default=Confidence.LOW)


def constant_confidence(parameter: ParameterValue) -> Confidence:
    """A placeholder is never trusted, whatever confidence it was filed under."""
    return Confidence.LOW if parameter.placeholder else parameter.confidence


def _estimated(
    value: float, low: float, high: float, source: ValueSource, confidence: Confidence
) -> Estimated:
    # Guard against float rounding pushing the value just outside its own range.
    return Estimated(
        value=value,
        low=min(low, value),
        high=max(high, value),
        source=source,
        confidence=confidence,
    )


def from_answer(
    answer: NumericAnswer,
    fallback: ParameterValue,
    fallback_source: ValueSource = ValueSource.STATISTICAL_ESTIMATE,
) -> Estimated:
    """The user's answer if there is one, otherwise the fallback default."""
    if answer.exact is not None:
        return _estimated(
            answer.exact, answer.exact, answer.exact, ValueSource.DECLARED_EXACT, Confidence.HIGH
        )
    if answer.low is not None and answer.high is not None:
        return _estimated(
            (answer.low + answer.high) / 2,
            answer.low,
            answer.high,
            ValueSource.DECLARED_APPROXIMATE,
            Confidence.MEDIUM,
        )
    return from_parameter(fallback, fallback_source)


def from_parameter(
    parameter: ParameterValue,
    source: ValueSource,
    confidence: Confidence | None = None,
) -> Estimated:
    """A model parameter used as an estimate of the household's own quantity."""
    return _estimated(
        parameter.value,
        parameter.lo,
        parameter.hi,
        source,
        confidence or constant_confidence(parameter),
    )


def derive(
    value: float,
    low: float,
    high: float,
    parts: Sequence[Estimated],
    constants: Sequence[ParameterValue] = (),
) -> Estimated:
    """An estimate computed from other estimates (`parts`) and model constants."""
    sources = [part.source for part in parts]
    if not sources:
        source = ValueSource.DEFAULT
    elif all(item in _DERIVABLE_SOURCES for item in sources):
        source = ValueSource.INFERRED
    else:
        source = max(sources, key=_SOURCE_RANK.__getitem__)
    confidence = weakest_confidence(
        [part.confidence for part in parts] + [constant_confidence(c) for c in constants]
    )
    return _estimated(value, low, high, source, confidence)


def times(a: Estimated, b: Estimated) -> Estimated:
    """a x b for non-negative quantities."""
    return derive(a.value * b.value, a.low * b.low, a.high * b.high, [a, b])


def scaled(a: Estimated, factor: ParameterValue) -> Estimated:
    """a x a model constant, with the constant's own range."""
    return derive(
        a.value * factor.value, a.low * factor.lo, a.high * factor.hi, [a], constants=[factor]
    )


def minus_clipped(a: Estimated, b: Estimated) -> Estimated:
    """a - b, never below zero (days worked minus days worked remotely)."""
    return derive(
        max(0.0, a.value - b.value),
        max(0.0, a.low - b.high),
        max(0.0, a.high - b.low),
        [a, b],
    )


# --- operations on model parameters ------------------------------------------------------


def divided(parameter: ParameterValue, divisor: float) -> ParameterValue:
    return parameter.model_copy(
        update={
            "value": parameter.value / divisor,
            "low": parameter.lo / divisor,
            "high": parameter.hi / divisor,
        }
    )


def multiplied(parameter: ParameterValue, factor: float) -> ParameterValue:
    return parameter.model_copy(
        update={
            "value": parameter.value * factor,
            "low": parameter.lo * factor,
            "high": parameter.hi * factor,
        }
    )


def complement(share: ParameterValue) -> ParameterValue:
    """1 - share, for a share between 0 and 1 (the range ends swap)."""
    return share.model_copy(
        update={"value": 1 - share.value, "low": 1 - share.hi, "high": 1 - share.lo}
    )
