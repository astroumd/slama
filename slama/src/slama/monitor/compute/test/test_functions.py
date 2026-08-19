"""Unit tests for the built-in compute functions (no engine/config needed)."""
import pytest

from slama.monitor.compute.computenode import ComputeContext, ResolvedInput
from slama.monitor.compute.functions import (
    _severity_score,
    count_true,
    count_valid,
    get_function,
    max_value,
    mean_value,
    median_value,
    min_max_value,
    min_value,
    sequence_validity,
    worst_validity,
)
from slama.monitor.monitorpoint import Validity


class FakeClock:
    def __init__(self, start=1000.0):
        self.t = start

    def advance(self, dt):
        self.t += dt

    def __call__(self):
        return self.t


def ri(name, value, validity=Validity.VALID_GOOD):
    return ResolvedInput(name, value, validity)


def ctx(clock=None, state=None, params=None):
    return ComputeContext(
        clock=clock if clock is not None else FakeClock(),
        state=state if state is not None else {},
        params=params if params is not None else {},
    )


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

class TestRegistry:
    def test_get_function_known(self):
        assert get_function("count_true") is count_true

    def test_get_function_unknown_raises(self):
        with pytest.raises(ValueError, match="unknown compute function"):
            get_function("nope")


# ---------------------------------------------------------------------------
# worst_validity — severity ordering must NOT be plain int max()
# ---------------------------------------------------------------------------

class TestWorstValidity:
    def test_error_beats_good(self):
        inputs = [ri("a", 1, Validity.VALID_GOOD), ri("b", 2, Validity.VALID_ERROR)]
        value, validity = worst_validity(inputs, ctx())
        assert validity == Validity.VALID_ERROR
        assert value == _severity_score(Validity.VALID_ERROR)

    def test_severity_score_increases_with_severity_not_enum_ordinal(self):
        # Regression: Validity's own IntEnum ordinal is declaration
        # order, not severity -- INVALID_NO_DATA has a LOWER ordinal
        # than VALID_GOOD. The score must not just be int(validity).
        good = _severity_score(Validity.VALID_GOOD)
        warning = _severity_score(Validity.VALID_WARNING)
        error = _severity_score(Validity.VALID_ERROR)
        invalid = _severity_score(Validity.INVALID_NO_DATA)
        assert good < warning < error < invalid
        assert good == 0

    def test_invalid_no_data_beats_error(self):
        # INVALID_NO_DATA has a LOWER int value than VALID_ERROR, so a
        # naive max() over Validity members would get this backwards.
        inputs = [ri("a", 1, Validity.VALID_ERROR), ri("b", None, Validity.INVALID_NO_DATA)]
        value, validity = worst_validity(inputs, ctx())
        assert validity == Validity.INVALID_NO_DATA

    def test_all_good_is_good(self):
        inputs = [ri("a", 1, Validity.VALID_GOOD), ri("b", 2, Validity.VALID_GOOD)]
        _, validity = worst_validity(inputs, ctx())
        assert validity == Validity.VALID_GOOD

    def test_warning_beats_good(self):
        inputs = [ri("a", 1, Validity.VALID_GOOD), ri("b", 2, Validity.VALID_WARNING)]
        _, validity = worst_validity(inputs, ctx())
        assert validity == Validity.VALID_WARNING


# ---------------------------------------------------------------------------
# count_true / count_valid
# ---------------------------------------------------------------------------

class TestCounts:
    def test_count_true(self):
        inputs = [ri("a", True), ri("b", False), ri("c", True)]
        assert count_true(inputs, ctx()) == 2

    def test_count_valid_excludes_invalid_family(self):
        inputs = [
            ri("a", 1, Validity.VALID_GOOD),
            ri("b", None, Validity.INVALID_NO_DATA),
            ri("c", 2, Validity.VALID_ERROR),  # counted: ERROR is still "valid data"
        ]
        assert count_valid(inputs, ctx()) == 2


# ---------------------------------------------------------------------------
# Numeric aggregates
# ---------------------------------------------------------------------------

class TestAggregates:
    def setup_method(self):
        self.inputs = [ri("a", 1.0), ri("b", 5.0), ri("c", 3.0)]

    def test_min_value(self):
        assert min_value(self.inputs, ctx()) == 1.0

    def test_max_value(self):
        assert max_value(self.inputs, ctx()) == 5.0

    def test_mean_value(self):
        assert mean_value(self.inputs, ctx()) == 3.0

    def test_median_value(self):
        assert median_value(self.inputs, ctx()) == 3.0

    def test_min_max_value_single_pass(self):
        # design doc §8: pairs with a multi-output entry's
        # "output": {"min": ..., "max": ...} -- role keys, not
        # canonical names.
        assert min_max_value(self.inputs, ctx()) == {"min": 1.0, "max": 5.0}


# ---------------------------------------------------------------------------
# sequence_validity — trajectory / stuck-timeout check
# ---------------------------------------------------------------------------

class TestSequenceValidity:
    def test_good_state_passes_through(self):
        inputs = {"state": ri("rx:H:tuning_state", "tuned", Validity.VALID_GOOD)}
        value, validity = sequence_validity(inputs, ctx(params={"stuck_timeout_s": 90}))
        assert value == "tuned"
        assert validity == Validity.VALID_GOOD

    def test_warning_state_within_timeout_stays_warning(self):
        clock = FakeClock()
        state = {}
        params = {"stuck_timeout_s": 90}
        inputs = {"state": ri("rx:H:tuning_state", "locking", Validity.VALID_WARNING)}
        _, validity = sequence_validity(inputs, ctx(clock, state, params))
        clock.advance(30)
        _, validity = sequence_validity(inputs, ctx(clock, state, params))
        assert validity == Validity.VALID_WARNING

    def test_warning_state_past_timeout_escalates_to_error(self):
        clock = FakeClock()
        state = {}
        params = {"stuck_timeout_s": 90}
        inputs = {"state": ri("rx:H:tuning_state", "locking", Validity.VALID_WARNING)}
        sequence_validity(inputs, ctx(clock, state, params))  # first sighting, starts timer
        clock.advance(91)
        _, validity = sequence_validity(inputs, ctx(clock, state, params))
        assert validity == Validity.VALID_ERROR

    def test_new_state_resets_the_timer(self):
        clock = FakeClock()
        state = {}
        params = {"stuck_timeout_s": 90}
        locking = {"state": ri("rx:H:tuning_state", "locking", Validity.VALID_WARNING)}
        setting_lo = {"state": ri("rx:H:tuning_state", "setting_lo", Validity.VALID_WARNING)}

        sequence_validity(locking, ctx(clock, state, params))
        clock.advance(80)  # not yet stuck
        sequence_validity(setting_lo, ctx(clock, state, params))  # transition resets timer
        clock.advance(80)  # would have been stuck on the old state, but timer reset
        _, validity = sequence_validity(setting_lo, ctx(clock, state, params))
        assert validity == Validity.VALID_WARNING

    def test_error_state_is_not_escalated_further(self):
        inputs = {"state": ri("rx:H:tuning_state", "failed", Validity.VALID_ERROR)}
        _, validity = sequence_validity(inputs, ctx(params={"stuck_timeout_s": 90}))
        assert validity == Validity.VALID_ERROR
