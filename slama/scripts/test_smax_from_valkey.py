"""Tests for smax_from_valkey.py — all tests use mocked SMAX queries."""
import sys
import math
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any
import pytest

sys.path.insert(0, str(Path(__file__).parent))
from smax_from_valkey import (
    filter_input,
    detect_each_group,
    indices_to_over_spec,
    dim_to_size,
    build_subtree,
    EachGroup,
)


# ---------------------------------------------------------------------------
# Mock SMAX variable
# ---------------------------------------------------------------------------

@dataclass
class MockSmaxVar:
    type: str
    dim: Any = 1
    description: str = None
    unit: str = None


def mock_query_factory(type_map: dict):
    """Return a query function that maps 'table:key' to MockSmaxVar."""
    def query(table, key):
        full = f"{table}:{key}"
        if full in type_map:
            return type_map[full]
        # fall back to suffix-based type inference
        if key.endswith("_F"):
            return MockSmaxVar(type="float32", dim=1)
        if key.endswith("_D"):
            return MockSmaxVar(type="float64", dim=1)
        if key.endswith("_L"):
            return MockSmaxVar(type="int64", dim=1)
        if key.endswith("_S"):
            return MockSmaxVar(type="int16", dim=1)
        return MockSmaxVar(type="string", dim=1)
    return query


# ---------------------------------------------------------------------------
# filter_input
# ---------------------------------------------------------------------------

class TestFilterInput:
    def test_skips_blank_lines(self):
        assert filter_input(["", "  ", "\t"]) == []

    def test_skips_comment_lines(self):
        assert filter_input(["# comment", "# In Valkey..."]) == []

    def test_skips_non_hierarchical(self):
        assert filter_input(["JCMT_METEOROLOGY_X", "DSM_PROJECT_ID_L"]) == []

    def test_skips_rm_acc9(self):
        lines = ["RM:acc9:RM_TRACK_EL_F", "RM:acc1:RM_TRACK_EL_F"]
        result = filter_input(lines)
        assert "RM:acc9:RM_TRACK_EL_F" not in result
        assert "RM:acc1:RM_TRACK_EL_F" in result

    def test_keeps_hierarchical_entries(self):
        lines = ["DSM:acc1:UPS_DATA_X:ACTIVE_ALARMS_L", "RM:acc1:RM_TRACK_EL_F"]
        assert filter_input(lines) == lines

    def test_strips_whitespace_from_lines(self):
        result = filter_input(["  DSM:acc1:FOO_F  "])
        assert result == ["DSM:acc1:FOO_F"]


# ---------------------------------------------------------------------------
# detect_each_group
# ---------------------------------------------------------------------------

class TestDetectEachGroup:
    def test_alpha_prefix_numeric_suffix_group(self):
        group, singles = detect_each_group(["acc1", "acc2", "acc3"])
        assert group is not None
        assert group.prefix == "acc"
        assert sorted(group.indices) == ["1", "2", "3"]
        assert singles == []

    def test_group_with_singletons(self):
        group, singles = detect_each_group(["acc1", "acc2", "obscon", "colossus"])
        assert group is not None
        assert group.prefix == "acc"
        assert sorted(group.indices) == ["1", "2"]
        assert sorted(singles) == ["colossus", "obscon"]

    def test_pure_numeric_keys(self):
        group, singles = detect_each_group(["1", "2", "3", "4"])
        assert group is not None
        assert group.prefix == ""
        assert sorted(group.indices) == ["1", "2", "3", "4"]
        assert singles == []

    def test_no_group_all_singletons(self):
        group, singles = detect_each_group(["obscon", "colossus", "hal9000"])
        assert group is None
        assert sorted(singles) == ["colossus", "hal9000", "obscon"]

    def test_zero_padded_prefix(self):
        keys = [f"roach2-{i:02d}" for i in list(range(1,9)) + list(range(11,19))]
        group, singles = detect_each_group(keys)
        assert group is not None
        assert group.prefix == "roach2-"
        assert "01" in group.indices
        assert "18" in group.indices
        assert singles == []

    def test_single_key_no_group(self):
        group, singles = detect_each_group(["acc1"])
        assert group is None
        assert singles == ["acc1"]


# ---------------------------------------------------------------------------
# indices_to_over_spec
# ---------------------------------------------------------------------------

class TestIndicesToOverSpec:
    def test_contiguous_range(self):
        assert indices_to_over_spec(["1", "2", "3", "4", "5", "6", "7", "8"]) == "1-8"

    def test_zero_padded_contiguous(self):
        assert indices_to_over_spec(["01", "02", "03", "04", "05", "06", "07", "08"]) == "01-08"

    def test_multi_segment_zero_padded(self):
        indices = [f"{i:02d}" for i in list(range(1,9)) + list(range(11,19))]
        result = indices_to_over_spec(indices)
        assert result == "01-08,11-18"

    def test_single_value(self):
        assert indices_to_over_spec(["5"]) == "5"

    def test_non_contiguous_unpadded(self):
        result = indices_to_over_spec(["1", "3", "5"])
        assert result == "1,3,5"

    def test_roach2_full_range(self):
        indices = [f"{i:02d}" for grp in range(0, 6) for i in range(grp*10+1, grp*10+9)]
        result = indices_to_over_spec(indices)
        assert result == "01-08,11-18,21-28,31-38,41-48,51-58"


# ---------------------------------------------------------------------------
# dim_to_size
# ---------------------------------------------------------------------------

class TestDimToSize:
    def test_scalar_int(self):
        assert dim_to_size(1) == "1"

    def test_array_int(self):
        assert dim_to_size(8) == "8"

    def test_1d_tuple(self):
        assert dim_to_size((8,)) == "8"

    def test_2d_tuple(self):
        assert dim_to_size((24, 6)) == "144"

    def test_3d_tuple(self):
        assert dim_to_size((2, 4, 17)) == "136"


# ---------------------------------------------------------------------------
# build_subtree
# ---------------------------------------------------------------------------

class TestBuildSubtreeLeaves:
    def test_single_leaf(self):
        query = mock_query_factory({"SYS:TEMP_F": MockSmaxVar("float32", 1)})
        result = build_subtree("SYS", ["TEMP_F"], query)
        assert result["TEMP_F"]["smax_type"] == "float32"
        assert result["TEMP_F"]["size"] == "1"

    def test_description_included_when_present(self):
        query = mock_query_factory({
            "SYS:TEMP_F": MockSmaxVar("float32", 1, description="Temperature")
        })
        result = build_subtree("SYS", ["TEMP_F"], query)
        assert result["TEMP_F"]["description"] == "Temperature"

    def test_description_omitted_when_none(self):
        query = mock_query_factory({"SYS:TEMP_F": MockSmaxVar("float32", 1)})
        result = build_subtree("SYS", ["TEMP_F"], query)
        assert "description" not in result["TEMP_F"]

    def test_unit_included_when_present(self):
        query = mock_query_factory({
            "SYS:TEMP_F": MockSmaxVar("float32", 1, unit="K")
        })
        result = build_subtree("SYS", ["TEMP_F"], query)
        assert result["TEMP_F"]["unit"] == "K"

    def test_unit_omitted_when_none(self):
        query = mock_query_factory({"SYS:TEMP_F": MockSmaxVar("float32", 1)})
        result = build_subtree("SYS", ["TEMP_F"], query)
        assert "unit" not in result["TEMP_F"]

    def test_array_size(self):
        query = mock_query_factory({"SYS:VEC_F": MockSmaxVar("float32", 8)})
        result = build_subtree("SYS", ["VEC_F"], query)
        assert result["VEC_F"]["size"] == "8"


class TestBuildSubtreeErrors:
    def test_failed_leaf_omitted_from_output(self):
        def bad_query(table, key):
            raise RuntimeError("not found")
        errors = []
        result = build_subtree("SYS", ["TEMP_F"], bad_query, errors)
        assert "TEMP_F" not in result

    def test_failed_leaf_appended_to_errors(self):
        def bad_query(table, key):
            raise RuntimeError("not found")
        errors = []
        build_subtree("SYS", ["TEMP_F"], bad_query, errors)
        assert errors == ["SYS:TEMP_F"]

    def test_successful_leaf_not_in_errors(self):
        query = mock_query_factory({"SYS:TEMP_F": MockSmaxVar("float32", 1)})
        errors = []
        build_subtree("SYS", ["TEMP_F"], query, errors)
        assert errors == []

    def test_partial_failure_keeps_successful_leaves(self):
        def selective_query(table, key):
            if key == "BAD_F":
                raise RuntimeError("missing")
            return MockSmaxVar("float32", 1)
        errors = []
        result = build_subtree("SYS", ["GOOD_F", "BAD_F"], selective_query, errors)
        assert "GOOD_F" in result
        assert "BAD_F" not in result
        assert errors == ["SYS:BAD_F"]

    def test_no_error_field_in_output(self):
        def bad_query(table, key):
            raise RuntimeError("not found")
        errors = []
        result = build_subtree("SYS", ["TEMP_F", "PRESS_F"], bad_query, errors)
        for val in result.values():
            assert "_error" not in val


class TestBuildSubtreeEachGroup:
    def test_generates_each_block(self):
        # acc1 and acc2 both have FOO_F
        query = mock_query_factory({
            "DSM:acc1:FOO_F": MockSmaxVar("float32", 1),
        })
        paths = ["acc1:FOO_F", "acc2:FOO_F"]
        result = build_subtree("DSM", paths, query)
        assert "__each__" in result
        assert result["__each__"]["prefix"] == "acc"
        assert "FOO_F" in result["__each__"]["template"]

    def test_each_block_omits_prefix_when_empty(self):
        # Pure numeric indices like "1", "2"
        query = mock_query_factory({"ANT:1:ELEV_F": MockSmaxVar("float32", 1)})
        paths = ["1:ELEV_F", "2:ELEV_F"]
        result = build_subtree("ANT", paths, query)
        assert "__each__" in result
        assert "prefix" not in result["__each__"]

    def test_singleton_alongside_each(self):
        query = mock_query_factory({
            "DSM:acc1:FOO_F": MockSmaxVar("float32", 1),
            "DSM:obscon:BAR_L": MockSmaxVar("int64", 1),
        })
        paths = ["acc1:FOO_F", "acc2:FOO_F", "obscon:BAR_L"]
        result = build_subtree("DSM", paths, query)
        assert "__each__" in result
        assert "obscon" in result
        assert result["obscon"]["BAR_L"]["smax_type"] == "int64"

    def test_nested_subtree(self):
        # acc1:UPS_DATA_X:ACTIVE_ALARMS_L — UPS_DATA_X is an intermediate node
        query = mock_query_factory({
            "DSM:acc1:UPS_DATA_X:ACTIVE_ALARMS_L": MockSmaxVar("int64", 1),
        })
        paths = ["acc1:UPS_DATA_X:ACTIVE_ALARMS_L", "acc2:UPS_DATA_X:ACTIVE_ALARMS_L"]
        result = build_subtree("DSM", paths, query)
        template = result["__each__"]["template"]
        assert "UPS_DATA_X" in template
        assert "ACTIVE_ALARMS_L" in template["UPS_DATA_X"]
