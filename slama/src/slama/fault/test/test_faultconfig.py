"""Unit tests for FaultConfig (no SMAX required)."""
import json
import pytest

from slama.fault.faultconfig import HEARTBEAT_NAME, FaultConfig, _expand_entry

M = "monitorsystem:"
HB = {"canonical_name": HEARTBEAT_NAME, "onset_s": 0, "actions": []}
"""Heartbeat entry every config must declare; onset 0 keeps its detection
time at its filters so small test configs pass the parent-lag check."""


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
            "defaults": {"transient_filter_s": 7, "no_data_filter_s": 20,
                         "computed_max_age_s": 4, "interval_s": 3},
            "actions": {
                "log": {"type": "log_file", "path": str(tmp_path / "f.log")},
            },
            "faults": [HB, {"canonical_name": M + "a:b", "actions": ["log"]}],
        }
        cfg = FaultConfig.from_dict(raw)
        assert cfg.default_interval_s == 3
        node = cfg.nodes[M + "a:b"]
        assert node.transient_filter_s == 7.0
        assert node.no_data_filter_s == 20.0
        assert node.computed_max_age_s == 4.0
        assert node.onset_s == 4.0          # defaults to computed_max_age_s
        assert node.context == []

    def test_no_data_filter_defaults_to_transient(self):
        raw = {"defaults": {"transient_filter_s": 9}, "faults": [HB]}
        assert FaultConfig.from_dict(raw).nodes[HEARTBEAT_NAME].no_data_filter_s == 9.0

    def test_per_entry_overrides_default(self, tmp_path):
        raw = {
            "defaults": {"transient_filter_s": 5, "no_data_filter_s": 50},
            "faults": [
                HB,
                {"canonical_name": M + "a", "transient_filter_s": 20,
                 "no_data_filter_s": 60, "computed_max_age_s": 10,
                 "onset_s": 70, "context": [M + "ctx"]},
                {"canonical_name": M + "b"},
            ],
        }
        cfg = FaultConfig.from_dict(raw)
        a, b = cfg.nodes[M + "a"], cfg.nodes[M + "b"]
        assert (a.transient_filter_s, a.no_data_filter_s,
                a.computed_max_age_s, a.onset_s) == (20.0, 60.0, 10.0, 70.0)
        assert a.context == [M + "ctx"]
        assert a.detection_s == 70.0 + 60.0
        assert b.transient_filter_s == 5.0

    def test_unknown_action_rejected(self, tmp_path):
        raw = {
            "actions": {
                "log": {"type": "log_file", "path": str(tmp_path / "f.log")},
            },
            "faults": [HB, {"canonical_name": M + "a", "actions": ["missing"]}],
        }
        with pytest.raises(ValueError, match="unknown action"):
            FaultConfig.from_dict(raw)

    def test_unknown_parent_rejected(self):
        raw = {"faults": [HB, {"canonical_name": M + "child",
                               "parents": [M + "ghost"]}]}
        with pytest.raises(ValueError, match="unknown parent"):
            FaultConfig.from_dict(raw)

    def test_duplicate_canonical_name_rejected(self):
        raw = {"faults": [HB, {"canonical_name": M + "a"},
                          {"canonical_name": M + "a"}]}
        with pytest.raises(ValueError, match="duplicate"):
            FaultConfig.from_dict(raw)

    @pytest.mark.parametrize("entry", [
        {"canonical_name": "RM:acc1:RM_GUNN_LOCK_S"},
        {"canonical_name": M + "a", "context": ["RM:acc1:RM_GUNN_PLL_IFPOWER_F"]},
    ])
    def test_non_computed_point_rejected(self, entry):
        with pytest.raises(ValueError, match="not a monitorsystem"):
            FaultConfig.from_dict({"faults": [HB, entry]})

    def test_empty_config_needs_no_heartbeat(self):
        assert FaultConfig.from_dict({"faults": []}).nodes == {}

    def test_missing_heartbeat_rejected(self):
        with pytest.raises(ValueError, match="must declare"):
            FaultConfig.from_dict({"faults": [{"canonical_name": M + "a"}]})

    def test_heartbeat_is_implicit_parent_of_every_other_node(self):
        raw = {"defaults": {"computed_max_age_s": 0},
               "faults": [HB, {"canonical_name": M + "a"},
                          {"canonical_name": M + "b", "parents": [M + "a"]}]}
        nodes = FaultConfig.from_dict(raw).nodes
        assert nodes[HEARTBEAT_NAME].parents == []
        assert nodes[M + "a"].parents == [HEARTBEAT_NAME]
        assert nodes[M + "b"].parents == [M + "a", HEARTBEAT_NAME]

    def test_parent_lag_rejects_short_child_no_data_filter(self):
        raw = {
            "defaults": {"transient_filter_s": 5, "no_data_filter_s": 15},
            "faults": [
                HB,
                {"canonical_name": M + "host", "onset_s": 70},
                {"canonical_name": M + "drive", "parents": [M + "host"],
                 "no_data_filter_s": 84},
            ],
        }
        with pytest.raises(ValueError, match="parent lag.*drive.*detection 85"):
            FaultConfig.from_dict(raw)

    def test_parent_lag_accepts_long_enough_filter(self):
        raw = {
            "defaults": {"transient_filter_s": 5, "no_data_filter_s": 15},
            "faults": [
                HB,
                {"canonical_name": M + "host", "onset_s": 70},
                {"canonical_name": M + "drive", "parents": [M + "host"],
                 "no_data_filter_s": 85},
            ],
        }
        assert M + "drive" in FaultConfig.from_dict(raw).nodes

    def test_parent_lag_includes_heartbeat(self):
        raw = {
            "defaults": {"transient_filter_s": 5, "no_data_filter_s": 5,
                         "computed_max_age_s": 6},
            "faults": [{"canonical_name": HEARTBEAT_NAME},
                       {"canonical_name": M + "a"}],
        }
        with pytest.raises(ValueError, match="heartbeat' detection 11"):
            FaultConfig.from_dict(raw)

    def test_each_produces_expected_dag(self, tmp_path):
        raw = {
            "defaults": {"transient_filter_s": 0},
            "actions": {
                "log": {"type": "log_file", "path": str(tmp_path / "f.log")},
            },
            "faults": [
                HB,
                {
                    "__each__": {
                        "over": "1-2",
                        "template": {
                            "canonical_name": M + "ant:{i}:power",
                            "actions": ["log"],
                        },
                    }
                },
                {
                    "__each__": {
                        "over": "1-2",
                        "template": {
                            "canonical_name": M + "ant:{i}:heater",
                            "parents": [M + "ant:{i}:power"],
                            "actions": ["log"],
                        },
                    }
                },
            ],
        }
        raw["defaults"]["computed_max_age_s"] = 0
        cfg = FaultConfig.from_dict(raw)
        assert set(cfg.nodes) - {HEARTBEAT_NAME} == {
            M + "ant:1:power", M + "ant:2:power",
            M + "ant:1:heater", M + "ant:2:heater",
        }
        assert cfg.nodes[M + "ant:1:heater"].parents == [M + "ant:1:power", HEARTBEAT_NAME]

    def test_nested_each_expands_host_by_slot(self):
        raw = {
            "defaults": {"computed_max_age_s": 0},
            "faults": [HB, {
                "__each__": {"over": "acc1,acc2", "as": "h", "template": {
                    "__each__": {"over": "0-1", "as": "j", "template": {
                        "canonical_name": M + "smainit:{h}:slot:{j}:status",
                        "context": [M + "smainit:{h}:slot:{j}:name"],
                    }},
                }},
            }],
        }
        nodes = FaultConfig.from_dict(raw).nodes
        assert [x for x in nodes if x != HEARTBEAT_NAME] == [
            M + "smainit:acc1:slot:0:status", M + "smainit:acc1:slot:1:status",
            M + "smainit:acc2:slot:0:status", M + "smainit:acc2:slot:1:status",
        ]
        assert nodes[M + "smainit:acc2:slot:1:status"].context == [
            M + "smainit:acc2:slot:1:name"]


class TestFromFile:
    def test_loads_from_json_file(self, tmp_path):
        raw = {
            "actions": {
                "log": {"type": "log_file", "path": str(tmp_path / "f.log")},
            },
            "faults": [HB, {"canonical_name": M + "x:y", "actions": ["log"]}],
        }
        cfg_path = tmp_path / "faults.json"
        cfg_path.write_text(json.dumps(raw))
        cfg = FaultConfig.from_file(cfg_path)
        assert M + "x:y" in cfg.nodes

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            FaultConfig.from_file(tmp_path / "nope.json")
