"""Unit tests for DataBridge (no SMAX server required)."""
import pytest
from pathlib import Path
from slama.web.data_bridge import (
    DataBridge, CSS_GOOD, CSS_WARNING, CSS_ERROR, CSS_NODATA, CSS_UNCHECKED,
)

SMAX_JSON = Path(__file__).parents[1] / "conf" / "smax.json"


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
