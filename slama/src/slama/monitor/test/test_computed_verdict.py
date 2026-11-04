"""Unit tests for slama.monitor.computed_verdict (no SMAX required)."""
from datetime import datetime, timezone

import pytest

from slama.monitor.computed_verdict import computed_validity
from slama.monitor.monitorpoint import Validity

NOW = 1_790_000_000.0


class FakeResult(float):
    """Stand-in for an ``SmaxFloat``: a value with a ``.timestamp`` datetime."""

    def __new__(cls, value, epoch):
        obj = super().__new__(cls, value)
        obj.timestamp = (None if epoch is None
                         else datetime.fromtimestamp(epoch, tz=timezone.utc))
        return obj


ERROR = str(int(Validity.VALID_ERROR))


class TestComputedValidity:
    def test_fresh_point_returns_pushed_validity(self):
        assert computed_validity(FakeResult(1.0, NOW - 1), ERROR, NOW, 6.0) \
            == Validity.VALID_ERROR

    def test_integer_metadata_accepted(self):
        assert computed_validity(FakeResult(1.0, NOW), int(Validity.VALID_GOOD),
                                 NOW, 6.0) == Validity.VALID_GOOD

    def test_stale_point_is_no_data(self):
        assert computed_validity(FakeResult(1.0, NOW - 7), ERROR, NOW, 6.0) \
            == Validity.INVALID_NO_DATA

    def test_age_exactly_max_is_fresh(self):
        assert computed_validity(FakeResult(1.0, NOW - 6), ERROR, NOW, 6.0) \
            == Validity.VALID_ERROR

    def test_future_timestamp_is_fresh(self):
        """--as-of replay: points written after the as-of time are not stale."""
        assert computed_validity(FakeResult(1.0, NOW + 86_400), ERROR, NOW, 6.0) \
            == Validity.VALID_ERROR

    def test_never_pulled_is_no_data(self):
        assert computed_validity(None, ERROR, NOW, 6.0) == Validity.INVALID_NO_DATA

    def test_missing_timestamp_is_no_data(self):
        assert computed_validity(FakeResult(1.0, None), ERROR, NOW, 6.0) \
            == Validity.INVALID_NO_DATA

    @pytest.mark.parametrize("raw", [None, "", "garbage", "999"])
    def test_missing_or_bad_metadata_is_no_data(self, raw):
        assert computed_validity(FakeResult(1.0, NOW), raw, NOW, 6.0) \
            == Validity.INVALID_NO_DATA
