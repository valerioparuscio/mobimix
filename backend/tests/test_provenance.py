import pytest
from pydantic import ValidationError

from app.models import (
    Confidence,
    Estimated,
    NumericAnswer,
    ParameterValue,
    Range,
    ValueSource,
)
from app.models.options import MobilityOption


class TestNumericAnswer:
    def test_unknown_by_default(self):
        answer = NumericAnswer()
        assert answer.kind == "unknown"
        assert answer.midpoint is None

    def test_exact(self):
        answer = NumericAnswer.of(12000)
        assert answer.kind == "exact"
        assert answer.midpoint == 12000

    def test_range_midpoint(self):
        answer = NumericAnswer.between(8000, 12000)
        assert answer.kind == "range"
        assert answer.midpoint == 10000

    def test_exact_and_range_are_mutually_exclusive(self):
        with pytest.raises(ValidationError):
            NumericAnswer(exact=5, low=1, high=9)

    def test_range_needs_both_ends(self):
        with pytest.raises(ValidationError):
            NumericAnswer(low=1)

    def test_range_must_be_ordered(self):
        with pytest.raises(ValidationError):
            NumericAnswer(low=9, high=1)


class TestEstimated:
    def test_range_defaults_to_value(self):
        estimate = Estimated(value=10, source=ValueSource.DEFAULT, confidence=Confidence.LOW)
        assert (estimate.low, estimate.high) == (10, 10)

    def test_value_must_lie_within_range(self):
        with pytest.raises(ValidationError):
            Estimated(
                value=10, low=11, high=20, source=ValueSource.DEFAULT, confidence=Confidence.LOW
            )

    def test_exact_helper_is_high_confidence(self):
        estimate = Estimated.exact(5)
        assert estimate.source is ValueSource.DECLARED_EXACT
        assert estimate.confidence is Confidence.HIGH


class TestRange:
    def test_addition_is_componentwise(self):
        total = Range(low=1, expected=2, high=4) + Range(low=10, expected=20, high=30)
        assert (total.low, total.expected, total.high) == (11, 22, 34)

    def test_subtraction_is_conservative(self):
        # candidate 4-6k vs current 8-10k: the saving is at least 2k and at most 6k
        delta = Range(low=4000, expected=5000, high=6000) - Range(
            low=8000, expected=9000, high=10000
        )
        assert (delta.low, delta.expected, delta.high) == (-6000, -4000, -2000)

    def test_independent_difference_is_narrower_than_the_worst_case_and_may_be_negative(self):
        candidate = Range(low=4000, expected=5000, high=6000)
        current = Range(low=8000, expected=9000, high=10000)
        delta = candidate.minus_independent(current)
        assert delta.expected == -4000
        assert delta.low == pytest.approx(-4000 - (1000**2 + 1000**2) ** 0.5)
        assert delta.high == pytest.approx(-4000 + (1000**2 + 1000**2) ** 0.5)
        worst_case = candidate - current
        assert worst_case.low < delta.low and delta.high < worst_case.high

    def test_the_difference_of_two_exact_values_is_exact(self):
        delta = Range.point(5).minus_independent(Range.point(8))
        assert (delta.low, delta.expected, delta.high) == (-3, -3, -3)

    def test_negation_swaps_the_ends(self):
        negated = Range(low=1, expected=2, high=5).negated()
        assert (negated.low, negated.expected, negated.high) == (-5, -2, -1)

    def test_a_signed_scale_swaps_the_ends_when_negative(self):
        scaled = Range(low=1, expected=2, high=5).scale_signed(-2)
        assert (scaled.low, scaled.expected, scaled.high) == (-10, -4, -2)
        same = Range(low=1, expected=2, high=5).scale_signed(2)
        assert (same.low, same.expected, same.high) == (2, 4, 10)

    def test_a_sum_of_signed_ranges_needs_to_say_so(self):
        parts = [Range(low=-300, expected=-200, high=-100), Range(low=-60, expected=-50, high=-40)]
        signed = Range.sum_independent(parts, non_negative=False)
        assert signed.expected == -250 and signed.low < -250 < signed.high < 0
        with pytest.raises(ValueError):  # the default is for non-negative quantities
            Range.sum_independent(parts)

    def test_scale_rejects_negative_factor(self):
        with pytest.raises(ValueError):
            Range.point(1).scale(-1)

    def test_must_be_ordered(self):
        with pytest.raises(ValidationError):
            Range(low=5, expected=1, high=9)


class TestParameterValue:
    def test_bare_number_is_a_low_confidence_unsourced_assumption(self):
        option = MobilityOption.model_validate(
            {
                "id": "x",
                "name": "x",
                "type": "WALKING",
                "mode": "WALK",
                "ownership": "FREE",
                "fixed_time_min_per_trip": 3,
            }
        )
        value = option.fixed_time_min_per_trip
        assert value is not None
        assert value.value == 3
        assert value.confidence is Confidence.LOW
        assert value.source is None
        assert value.placeholder is False

    def test_range_helpers(self):
        value = ParameterValue(value=5, low=3, high=8)
        assert (value.lo, value.hi) == (3, 8)
        assert value.as_range() == Range(low=3, expected=5, high=8)
        assert (ParameterValue(value=5).lo, ParameterValue(value=5).hi) == (5, 5)

    def test_low_above_value_is_rejected(self):
        with pytest.raises(ValidationError):
            ParameterValue(value=5, low=6)
