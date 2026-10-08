"""Unit tests for DataBridge (no SMAX server required)."""
from datetime import datetime, timezone

import pytest
from pathlib import Path
from slama.monitor.monitorpoint import Validity
from slama.web.data_bridge import (
    DataBridge, CSS_GOOD, CSS_WARNING, CSS_ERROR, CSS_NODATA, CSS_UNCHECKED,
    validity_to_css,
)

SMAX_JSON = Path(__file__).parents[2] / "conf" / "smax.json"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def bridge_with_thresholds(**thresholds):
    """Return a DataBridge with a single monitor point's thresholds injected."""
    db = DataBridge()
    db._thresholds["test:point"] = thresholds
    return db


# ---------------------------------------------------------------------------
# _compute_css_class — numeric thresholds
# ---------------------------------------------------------------------------

class TestComputeCssClassNumeric:
    def test_none_value_is_nodata(self):
        db = bridge_with_thresholds(warn_low=0.0, warn_high=100.0)
        assert db._compute_css_class("test:point", None) == CSS_NODATA

    def test_good_value_in_range(self):
        db = bridge_with_thresholds(warn_low=10.0, warn_high=80.0,
                                    err_low=0.0, err_high=100.0)
        assert db._compute_css_class("test:point", 50.0) == CSS_GOOD

    def test_at_warn_high_is_warning(self):
        db = bridge_with_thresholds(warn_high=80.0)
        assert db._compute_css_class("test:point", 80.0) == CSS_WARNING

    def test_above_warn_high_is_warning(self):
        db = bridge_with_thresholds(warn_high=80.0)
        assert db._compute_css_class("test:point", 85.0) == CSS_WARNING

    def test_at_err_high_is_error(self):
        db = bridge_with_thresholds(err_high=100.0)
        assert db._compute_css_class("test:point", 100.0) == CSS_ERROR

    def test_at_warn_low_is_warning(self):
        db = bridge_with_thresholds(warn_low=10.0)
        assert db._compute_css_class("test:point", 10.0) == CSS_WARNING

    def test_at_err_low_is_error(self):
        db = bridge_with_thresholds(err_low=0.0)
        assert db._compute_css_class("test:point", 0.0) == CSS_ERROR

    def test_no_thresholds_numeric_is_good(self):
        db = DataBridge()
        assert db._compute_css_class("unknown:point", 42.0) == CSS_GOOD

    def test_bool_is_unchecked(self):
        db = DataBridge()
        assert db._compute_css_class("test:point", True) == CSS_UNCHECKED


# ---------------------------------------------------------------------------
# _compute_css_class — string / valid_strings
# ---------------------------------------------------------------------------

class TestComputeCssClassString:
    def test_valid_string_is_good(self):
        db = bridge_with_thresholds(valid_strings=["ok", "idle"])
        assert db._compute_css_class("test:point", "ok") == CSS_GOOD

    def test_invalid_string_is_error(self):
        db = bridge_with_thresholds(valid_strings=["ok", "idle"])
        assert db._compute_css_class("test:point", "fault") == CSS_ERROR

    def test_string_no_valid_strings_is_unchecked(self):
        db = DataBridge()
        assert db._compute_css_class("unknown:point", "anything") == CSS_UNCHECKED


# ---------------------------------------------------------------------------
# get_history — threshold extraction
# ---------------------------------------------------------------------------

class TestGetHistoryThresholds:
    def test_thresholds_included_when_present(self):
        db = bridge_with_thresholds(warn_low=5.0, warn_high=95.0,
                                    err_low=0.0, err_high=100.0)
        result = db.get_history("test:point")
        assert result["thresholds"] == {
            "warn_low": 5.0, "warn_high": 95.0,
            "err_low": 0.0, "err_high": 100.0,
        }

    def test_empty_thresholds_when_unknown(self):
        db = DataBridge()
        result = db.get_history("no:such:point")
        assert result["thresholds"] == {}

    def test_partial_thresholds_only_present_keys(self):
        db = bridge_with_thresholds(warn_high=80.0)
        result = db.get_history("test:point")
        assert result["thresholds"] == {"warn_high": 80.0}


# ---------------------------------------------------------------------------
# Loading thresholds from smax.json via MonitorSystem
# (these tests define the new DataBridge(smax_path=...) API)
# ---------------------------------------------------------------------------

class TestLoadThresholdsFromSmaxJson:
    def test_rm_track_el_thresholds_loaded(self):
        db = DataBridge(smax_path=SMAX_JSON)
        t = db._thresholds.get("RM:acc1:RM_TRACK_EL_F", {})
        assert t.get("warn_low") == 15.0
        assert t.get("warn_high") == 88.0
        assert t.get("err_low") == -1.0
        assert t.get("err_high") == 90

    def test_rm_active_low_receiver_valid_strings_loaded(self):
        db = DataBridge(smax_path=SMAX_JSON)
        t = db._thresholds.get("RM:acc1:RM_ACTIVE_LOW_RECEIVER_C10", {})
        assert t.get("valid_strings") == ["A1", "B1", "C", "E", "A2", "B2", "D", "F"]

    def test_all_rm_accs_have_thresholds(self):
        db = DataBridge(smax_path=SMAX_JSON)
        for n in range(1, 9):
            t = db._thresholds.get(f"RM:acc{n}:RM_TRACK_EL_F", {})
            assert t.get("warn_low") == 15.0, f"Missing threshold for acc{n}"

    def test_point_without_thresholds_absent_from_dict(self):
        # RM_SOURCE_C34 has no validity thresholds — should not be in _thresholds
        # (or if present, all threshold keys should be None/absent)
        db = DataBridge(smax_path=SMAX_JSON)
        t = db._thresholds.get("RM:acc1:RM_SOURCE_C34", {})
        assert t.get("warn_low") is None
        assert t.get("err_high") is None

    def test_correlator_integration_time_thresholds_loaded(self):
        db = DataBridge(smax_path=SMAX_JSON)
        t = db._thresholds.get("correlator:swarm:integration_time", {})
        assert t.get("warn_low") == 0.0
        assert t.get("warn_high") == 9000
        assert t.get("err_low") == -1.0
        assert t.get("err_high") == 10000

    def test_css_class_uses_smax_thresholds(self):
        db = DataBridge(smax_path=SMAX_JSON)
        # RM_TRACK_EL_F warn_low=15.0 — value of 10.0 should be CSS_WARNING
        assert db._compute_css_class("RM:acc1:RM_TRACK_EL_F", 10.0) == CSS_WARNING


# ---------------------------------------------------------------------------
# Compute-engine (monitorsystem:) points — pushed validity, freshness-gated
# ---------------------------------------------------------------------------

class _FakeResult(float):
    """Stand-in for an ``SmaxFloat`` pulled from SMAX: a value with ``.timestamp``."""

    def __new__(cls, value, epoch):
        obj = super().__new__(cls, value)
        obj.timestamp = None if epoch is None else datetime.fromtimestamp(epoch, tz=timezone.utc)
        return obj


class _FakeMetaClient:
    """Minimal client exposing only ``smax_pull_meta`` for validity."""

    def __init__(self, meta):
        self.meta = meta

    def smax_pull_meta(self, meta, table):
        return self.meta.get((meta, table))


NAME = "monitorsystem:antenna:1:drive_status"
NOW = 1_790_000_000.0


class TestValidityToCss:
    @pytest.mark.parametrize("validity, css", [
        (Validity.INVALID_NO_DATA, CSS_NODATA),
        (Validity.INVALID_NO_HW, CSS_NODATA),
        (Validity.VALID_GOOD, CSS_GOOD),
        (Validity.VALID, CSS_GOOD),
        (Validity.VALID_WARNING_HIGH, CSS_WARNING),
        (Validity.VALID_ERROR, CSS_ERROR),
        (Validity.VALID_ERROR_LOW, CSS_ERROR),
        (Validity.VALID_NOT_CHECKED, CSS_UNCHECKED),
    ])
    def test_mapping(self, validity, css):
        assert validity_to_css(validity) == css


class TestComputedCssClass:
    def test_fresh_point_uses_pushed_validity(self):
        client = _FakeMetaClient({("validity", NAME): str(int(Validity.VALID_ERROR))})
        css = DataBridge()._computed_css_class(client, NAME, _FakeResult(1.0, NOW - 1), now=NOW)
        assert css == CSS_ERROR

    def test_stale_point_is_nodata_even_if_last_verdict_good(self):
        """A stopped engine leaves its last verdict in <validity>; the timestamp must gate it."""
        client = _FakeMetaClient({("validity", NAME): str(int(Validity.VALID_GOOD))})
        css = DataBridge()._computed_css_class(client, NAME, _FakeResult(1.0, NOW - 60), now=NOW)
        assert css == CSS_NODATA

    def test_max_age_is_configurable(self):
        client = _FakeMetaClient({("validity", NAME): str(int(Validity.VALID_GOOD))})
        db = DataBridge(computed_max_age_s=120.0)
        assert db._computed_css_class(client, NAME, _FakeResult(1.0, NOW - 60), now=NOW) == CSS_GOOD

    def test_missing_timestamp_is_nodata(self):
        client = _FakeMetaClient({("validity", NAME): str(int(Validity.VALID_GOOD))})
        css = DataBridge()._computed_css_class(client, NAME, _FakeResult(1.0, None), now=NOW)
        assert css == CSS_NODATA

    def test_missing_metadata_is_nodata(self):
        css = DataBridge()._computed_css_class(
            _FakeMetaClient({}), NAME, _FakeResult(1.0, NOW), now=NOW)
        assert css == CSS_NODATA

    def test_garbage_metadata_is_nodata(self):
        client = _FakeMetaClient({("validity", NAME): "banana"})
        css = DataBridge()._computed_css_class(client, NAME, _FakeResult(1.0, NOW), now=NOW)
        assert css == CSS_NODATA
