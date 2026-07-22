"""Unit tests for display_config.py (no SMAX server required)."""
import json

import pytest

from slama.web.display_config import (
    MatrixBlock,
    TableBlock,
    _resolve_elements,
    _resolve_labels,
    load_display_config,
)


# ---------------------------------------------------------------------------
# _resolve_elements
# ---------------------------------------------------------------------------

class TestResolveElements:
    def test_none_uses_default_count(self):
        assert _resolve_elements(None, default_count=4) == [0, 1, 2, 3]

    def test_none_without_default_count_raises(self):
        with pytest.raises(ValueError):
            _resolve_elements(None)

    def test_explicit_list_arbitrary_skip(self):
        assert _resolve_elements([1, 2, 4, 7, 8]) == [1, 2, 4, 7, 8]

    def test_slice_dict_exclusive_stop(self):
        assert _resolve_elements({"start": 2, "stop": 9}) == [2, 3, 4, 5, 6, 7, 8]

    def test_slice_dict_with_step(self):
        assert _resolve_elements({"start": 0, "stop": 8, "step": 2}) == [0, 2, 4, 6]

    def test_slice_dict_default_start(self):
        assert _resolve_elements({"stop": 3}) == [0, 1, 2]

    def test_invalid_type_raises(self):
        with pytest.raises(ValueError):
            _resolve_elements("bogus")


# ---------------------------------------------------------------------------
# _resolve_labels
# ---------------------------------------------------------------------------

class TestResolveLabels:
    def test_literal_list(self):
        assert _resolve_labels(["A", "B"], [0, 1]) == ["A", "B"]

    def test_literal_list_length_mismatch_raises(self):
        with pytest.raises(ValueError):
            _resolve_labels(["A"], [0, 1])

    def test_prefix_with_index_offset_zero(self):
        # "Antenna{index}"
        assert _resolve_labels({"prefix": "Antenna"}, [1, 2, 3]) == \
            ["Antenna1", "Antenna2", "Antenna3"]

    def test_prefix_with_negative_index_offset(self):
        # "Chassis{index-1}"
        assert _resolve_labels({"prefix": "Chassis", "index_offset": -1}, [1, 2]) == \
            ["Chassis0", "Chassis1"]

    def test_prefix_with_positive_index_offset(self):
        # "Foobar{index+3}"
        assert _resolve_labels({"prefix": "Foobar", "index_offset": 3}, [0, 1, 2]) == \
            ["Foobar3", "Foobar4", "Foobar5"]

    def test_prefix_with_start_is_sequential_positional(self):
        assert _resolve_labels({"prefix": "Ant", "start": 1}, [5, 6, 7]) == \
            ["Ant1", "Ant2", "Ant3"]

    def test_invalid_type_raises(self):
        with pytest.raises(ValueError):
            _resolve_labels(42, [0, 1])


# ---------------------------------------------------------------------------
# Loading a table block with a vector row
# ---------------------------------------------------------------------------

def _write_config(tmp_path, layout):
    path = tmp_path / "test_display.json"
    path.write_text(json.dumps({
        "name": "Test",
        "description": "",
        "update_interval": 2,
        "layout": layout,
    }))
    return path


class TestVectorTableRow:
    def test_vector_row_all_elements(self, tmp_path):
        path = _write_config(tmp_path, [{
            "type": "table",
            "title": "T",
            "columns": {"labels": ["A1", "A2"], "var": "ant", "values": [1, 2]},
            "rows": [
                {"label": "Vec", "vector_point": "DSM:x:V2_F"},
            ],
        }])
        config = load_display_config(path)
        block = config.layout[0]
        assert isinstance(block, TableBlock)
        row = block.rows[0]
        assert row["vector_point"] == "DSM:x:V2_F"
        assert row["vector_elements"] == [0, 1]
        assert row["points"] == ["DSM:x:V2_F.0", "DSM:x:V2_F.1"]

    def test_vector_row_explicit_elements_skip_middle(self, tmp_path):
        path = _write_config(tmp_path, [{
            "type": "table",
            "title": "T",
            "columns": {"labels": ["A", "B", "C"], "var": "ant", "values": [1, 2, 3]},
            "rows": [
                {"label": "Vec", "vector_point": "DSM:x:V_F", "elements": [1, 2, 4]},
            ],
        }])
        config = load_display_config(path)
        row = config.layout[0].rows[0]
        assert row["vector_elements"] == [1, 2, 4]
        assert row["points"] == ["DSM:x:V_F.1", "DSM:x:V_F.2", "DSM:x:V_F.4"]

    def test_vector_row_element_count_mismatch_raises(self, tmp_path):
        path = _write_config(tmp_path, [{
            "type": "table",
            "title": "T",
            "columns": {"labels": ["A", "B"], "var": "ant", "values": [1, 2]},
            "rows": [
                {"label": "Vec", "vector_point": "DSM:x:V_F", "elements": [0, 1, 2]},
            ],
        }])
        with pytest.raises(ValueError):
            load_display_config(path)

    def test_scalar_and_vector_rows_can_mix(self, tmp_path):
        path = _write_config(tmp_path, [{
            "type": "table",
            "title": "T",
            "columns": {"labels": ["A1", "A2"], "var": "ant", "values": [1, 2]},
            "rows": [
                {"label": "Scalar", "points": "RM:acc{ant}:X"},
                {"label": "Vector", "vector_point": "DSM:x:V_F"},
            ],
        }])
        config = load_display_config(path)
        block = config.layout[0]
        assert block.rows[0]["vector_point"] is None
        assert block.rows[0]["points"] == ["RM:acc1:X", "RM:acc2:X"]
        assert block.rows[1]["vector_point"] == "DSM:x:V_F"


# ---------------------------------------------------------------------------
# Loading a matrix block
# ---------------------------------------------------------------------------

class TestMatrixBlock:
    def test_matrix_block_defaults(self, tmp_path):
        path = _write_config(tmp_path, [{
            "type": "matrix",
            "title": "BDC Temps",
            "point": "DSM:x:TEMP_V2_V8_F",
            "shape": [2, 8],
            "row_labels": {"prefix": "Chassis"},
            "column_labels": {"prefix": "Antenna", "index_offset": 1},
        }])
        config = load_display_config(path)
        block = config.layout[0]
        assert isinstance(block, MatrixBlock)
        assert block.row_elements == [0, 1]
        assert block.column_elements == list(range(8))
        assert block.row_labels == ["Chassis0", "Chassis1"]
        assert block.column_labels == [f"Antenna{i+1}" for i in range(8)]
        assert block.cell_points[0] == "DSM:x:TEMP_V2_V8_F.0.0"
        assert len(block.cell_points) == 16

    def test_matrix_block_element_subset(self, tmp_path):
        path = _write_config(tmp_path, [{
            "type": "matrix",
            "title": "BDC Temps",
            "point": "DSM:x:TEMP_V2_V8_F",
            "shape": [2, 8],
            "row_elements": [0],
            "column_elements": {"start": 1, "stop": 9},
            "row_labels": ["Chassis0"],
            "column_labels": {"prefix": "Antenna", "index_offset": 0},
        }])
        config = load_display_config(path)
        block = config.layout[0]
        assert block.row_elements == [0]
        assert block.column_elements == list(range(1, 9))
        assert len(block.cell_points) == 8

    def test_all_canonical_names_includes_matrix_cells(self, tmp_path):
        path = _write_config(tmp_path, [{
            "type": "matrix",
            "title": "BDC Temps",
            "point": "DSM:x:TEMP_V2_V8_F",
            "shape": [2, 2],
        }])
        config = load_display_config(path)
        names = config.all_canonical_names()
        assert set(names) == {
            "DSM:x:TEMP_V2_V8_F.0.0", "DSM:x:TEMP_V2_V8_F.0.1",
            "DSM:x:TEMP_V2_V8_F.1.0", "DSM:x:TEMP_V2_V8_F.1.1",
        }
