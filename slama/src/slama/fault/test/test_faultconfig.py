"""Unit tests for FaultConfig (no SMAX required)."""
import json
import pytest

from slama.fault.faultconfig import FaultConfig, _expand_entry


# ---------------------------------------------------------------------------
# __each__ expansion
# ---------------------------------------------------------------------------

class TestExpandEntry:
    def test_plain_entry_passes_through(self):
        entry = {"canonical_name": "foo:bar", "actions": ["log"]}
        result = _expand_entry(entry)
        assert result == [entry]

    def test_each_expands_range(self):
        entry = {
            "__each__": {
                "over": "1-3",
                "template": {
                    "canonical_name": "antenna:{i}:power",
                    "actions": ["log"],
                },
            }
        }
        result = _expand_entry(entry)
        assert [r["canonical_name"] for r in result] == [
            "antenna:1:power", "antenna:2:power", "antenna:3:power",
        ]

    def test_each_with_explicit_as(self):
        entry = {
            "__each__": {
                "over": "H,V",
                "as": "pol",
                "template": {"canonical_name": "rx:{pol}:status"},
            }
        }
        result = _expand_entry(entry)
        assert [r["canonical_name"] for r in result] == [
            "rx:H:status", "rx:V:status",
        ]

    def test_each_substitutes_in_parents_list(self):
        entry = {
            "__each__": {
                "over": "1-2",
                "template": {
                    "canonical_name": "ant:{i}:heater",
                    "parents": ["ant:{i}:power", "site:ac"],
                },
            }
        }
        result = _expand_entry(entry)
        assert result[0]["parents"] == ["ant:1:power", "site:ac"]
        assert result[1]["parents"] == ["ant:2:power", "site:ac"]

    def test_each_requires_over_and_template(self):
        with pytest.raises(ValueError, match="'over' and 'template'"):
            _expand_entry({"__each__": {"over": "1-2"}})
        with pytest.raises(ValueError, match="'over' and 'template'"):
            _expand_entry({"__each__": {"template": {}}})

    def test_each_rejects_sibling_keys(self):
        with pytest.raises(ValueError, match="no sibling keys"):
            _expand_entry({
                "__each__": {"over": "1", "template": {"canonical_name": "x"}},
                "canonical_name": "also",
            })


# ---------------------------------------------------------------------------
# FaultConfig.from_dict
# ---------------------------------------------------------------------------

class TestFromDict:
    def test_loads_simple_config(self, tmp_path):
        raw = {
            "defaults": {"transient_filter_s": 7, "interval_s": 3},
            "actions": {
                "log": {"type": "log_file", "path": str(tmp_path / "f.log")},
            },
            "faults": [
                {"canonical_name": "a:b", "actions": ["log"]},
            ],
        }
        cfg = FaultConfig.from_dict(raw)
        assert cfg.default_interval_s == 3
        assert "a:b" in cfg.nodes
        assert cfg.nodes["a:b"].transient_filter_s == 7.0

    def test_per_entry_transient_overrides_default(self, tmp_path):
        raw = {
            "defaults": {"transient_filter_s": 5},
            "actions": {
                "log": {"type": "log_file", "path": str(tmp_path / "f.log")},
            },
            "faults": [
                {"canonical_name": "a", "transient_filter_s": 20, "actions": ["log"]},
                {"canonical_name": "b", "actions": ["log"]},
            ],
        }
        cfg = FaultConfig.from_dict(raw)
        assert cfg.nodes["a"].transient_filter_s == 20.0
        assert cfg.nodes["b"].transient_filter_s == 5.0

    def test_unknown_action_rejected(self, tmp_path):
        raw = {
            "actions": {
                "log": {"type": "log_file", "path": str(tmp_path / "f.log")},
            },
            "faults": [{"canonical_name": "a", "actions": ["missing"]}],
        }
        with pytest.raises(ValueError, match="unknown action"):
            FaultConfig.from_dict(raw)

    def test_unknown_parent_rejected(self, tmp_path):
        raw = {
            "actions": {
                "log": {"type": "log_file", "path": str(tmp_path / "f.log")},
            },
            "faults": [
                {"canonical_name": "child", "parents": ["ghost"], "actions": []},
            ],
        }
        with pytest.raises(ValueError, match="unknown parent"):
            FaultConfig.from_dict(raw)

    def test_duplicate_canonical_name_rejected(self, tmp_path):
        raw = {
            "actions": {},
            "faults": [
                {"canonical_name": "a", "actions": []},
                {"canonical_name": "a", "actions": []},
            ],
        }
        with pytest.raises(ValueError, match="duplicate"):
            FaultConfig.from_dict(raw)

    def test_each_produces_expected_dag(self, tmp_path):
        raw = {
            "defaults": {"transient_filter_s": 0},
            "actions": {
                "log": {"type": "log_file", "path": str(tmp_path / "f.log")},
            },
            "faults": [
                {
                    "__each__": {
                        "over": "1-2",
                        "template": {
                            "canonical_name": "ant:{i}:power",
                            "actions": ["log"],
                        },
                    }
                },
                {
                    "__each__": {
                        "over": "1-2",
                        "template": {
                            "canonical_name": "ant:{i}:heater",
                            "parents": ["ant:{i}:power"],
                            "actions": ["log"],
                        },
                    }
                },
            ],
        }
        cfg = FaultConfig.from_dict(raw)
        assert set(cfg.nodes) == {
            "ant:1:power", "ant:2:power", "ant:1:heater", "ant:2:heater",
        }
        assert cfg.nodes["ant:1:heater"].parents == ["ant:1:power"]
        assert cfg.nodes["ant:2:heater"].parents == ["ant:2:power"]


class TestFromFile:
    def test_loads_from_json_file(self, tmp_path):
        raw = {
            "actions": {
                "log": {"type": "log_file", "path": str(tmp_path / "f.log")},
            },
            "faults": [{"canonical_name": "x:y", "actions": ["log"]}],
        }
        cfg_path = tmp_path / "faults.json"
        cfg_path.write_text(json.dumps(raw))
        cfg = FaultConfig.from_file(cfg_path)
        assert "x:y" in cfg.nodes

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            FaultConfig.from_file(tmp_path / "nope.json")
