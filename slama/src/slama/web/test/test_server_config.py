"""Tests for server-side configuration of the DataBridge (issue #54)."""
from datetime import datetime, timezone

import pytest

from slama.monitor.monitorpoint import Validity
from slama.web.data_bridge import (
    CSS_GOOD,
    DEFAULT_COMPUTED_MAX_AGE_S,
    DataBridge,
)
from slama.web.server import _computed_max_age_from_env

ENV = "SLAMA_COMPUTED_MAX_AGE_S"


class _Result(float):
    """Float with a ``timestamp`` attribute, like an SMAX pull result."""

    def __new__(cls, value, ts):
        obj = super().__new__(cls, value)
        obj.timestamp = datetime.fromtimestamp(ts, tz=timezone.utc)
        return obj


class _Client:
    def smax_pull_meta(self, key, name):
        return Validity.VALID_GOOD.value


class TestComputedMaxAgeFromEnv:
    def test_default_when_unset(self, monkeypatch):
        monkeypatch.delenv(ENV, raising=False)
        assert _computed_max_age_from_env() == DEFAULT_COMPUTED_MAX_AGE_S

    def test_default_when_empty(self, monkeypatch):
        monkeypatch.setenv(ENV, "  ")
        assert _computed_max_age_from_env() == DEFAULT_COMPUTED_MAX_AGE_S

    def test_number(self, monkeypatch):
        monkeypatch.setenv(ENV, "60")
        assert _computed_max_age_from_env() == 60.0

    def test_inf(self, monkeypatch):
        monkeypatch.setenv(ENV, "inf")
        assert _computed_max_age_from_env() == float("inf")

    @pytest.mark.parametrize("bad", ["abc", "-1", "nan"])
    def test_rejects_bad_values(self, monkeypatch, bad):
        monkeypatch.setenv(ENV, bad)
        with pytest.raises(ValueError, match=ENV):
            _computed_max_age_from_env()


def test_infinite_age_trusts_snapshot_day_timestamp():
    """A point written long ago still gets its pushed validity colour."""
    now = 2_000_000_000.0
    old = _Result(1.0, now - 86400 * 30)
    db = DataBridge(computed_max_age_s=float("inf"))
    assert db._computed_css_class(
        _Client(), "monitorsystem:x", old, now=now
    ) == CSS_GOOD
