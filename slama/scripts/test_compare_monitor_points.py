"""Tests for compare_monitor_points.py — parse_range and expand_smax."""
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent))
from compare_monitor_points import parse_range, expand_smax


# ---------------------------------------------------------------------------
# parse_range
# ---------------------------------------------------------------------------

class TestParseRange:
    def test_simple_range(self):
        assert parse_range("1-8") == ["1", "2", "3", "4", "5", "6", "7", "8"]

    def test_single_value(self):
        assert parse_range("5") == ["5"]

    def test_comma_list(self):
        assert parse_range("1,3,5") == ["1", "3", "5"]

    def test_mixed_range_and_values(self):
        assert parse_range("1-3,5,7-9") == ["1", "2", "3", "5", "7", "8", "9"]

    def test_zero_padded_range(self):
        assert parse_range("01-08") == ["01", "02", "03", "04", "05", "06", "07", "08"]

    def test_zero_padded_multi_segment(self):
        result = parse_range("01-02,11-12")
        assert result == ["01", "02", "11", "12"]

    def test_string_literal_in_comma_list(self):
        # Comma-separated string literals (no '-') pass through as-is
        assert parse_range("acc1,acc2,acc3") == ["acc1", "acc2", "acc3"]


# ---------------------------------------------------------------------------
# expand_smax — __each__ with prefix field
# ---------------------------------------------------------------------------

class TestExpandSmaxPrefix:
    def test_each_with_alpha_prefix(self):
        """acc1-acc8 style: prefix='acc', over='1-8'."""
        obj = {
            "__each__": {
                "over": "1-8",
                "prefix": "acc",
                "template": {
                    "FOO_F": {"smax_type": "float", "size": "1"}
                }
            }
        }
        names = expand_smax(obj, "RM")
        assert "RM:acc1:FOO_F" in names
        assert "RM:acc8:FOO_F" in names
        # Should NOT contain bare-index form
        assert "RM:1:FOO_F" not in names

    def test_each_with_zero_padded_range_and_prefix(self):
        """roach2-01 style: prefix='roach2-', over='01-08'."""
        obj = {
            "__each__": {
                "over": "01-08",
                "prefix": "roach2-",
                "template": {
                    "mmcm_cal": {"smax_type": "int", "size": "1"}
                }
            }
        }
        names = expand_smax(obj, "DSM")
        assert "DSM:roach2-01:mmcm_cal" in names
        assert "DSM:roach2-08:mmcm_cal" in names
        assert "DSM:roach2-1:mmcm_cal" not in names
        assert "DSM:1:mmcm_cal" not in names

    def test_each_without_prefix_unchanged(self):
        """Original antenna-style __each__ with no prefix still works."""
        obj = {
            "__each__": {
                "over": "1-3",
                "template": {
                    "temperature": {"smax_type": "float", "size": "1"}
                }
            }
        }
        names = expand_smax(obj, "antenna")
        assert "antenna:1:temperature" in names
        assert "antenna:3:temperature" in names

    def test_each_multi_segment_range_with_prefix(self):
        """over='01-08,11-18' with prefix='roach2-' produces correct names."""
        obj = {
            "__each__": {
                "over": "01-08,11-18",
                "prefix": "roach2-",
                "template": {
                    "load": {"smax_type": "float", "size": "1"}
                }
            }
        }
        names = expand_smax(obj, "DSM")
        assert "DSM:roach2-01:load" in names
        assert "DSM:roach2-08:load" in names
        assert "DSM:roach2-11:load" in names
        assert "DSM:roach2-18:load" in names
        assert len([n for n in names if "load" in n]) == 16  # 8 + 8

    def test_each_nested_struct_with_prefix(self):
        """Template with nested struct under __each__ with prefix."""
        obj = {
            "__each__": {
                "over": "01-02",
                "prefix": "roach2-",
                "template": {
                    "SMAINIT_REPORT_X": {
                        "PRG_NAMES_V24_C24": {"smax_type": "string", "size": "24"}
                    }
                }
            }
        }
        names = expand_smax(obj, "DSM")
        assert "DSM:roach2-01:SMAINIT_REPORT_X:PRG_NAMES_V24_C24" in names
        assert "DSM:roach2-02:SMAINIT_REPORT_X:PRG_NAMES_V24_C24" in names
