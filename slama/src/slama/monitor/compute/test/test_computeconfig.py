"""Unit tests for ComputeConfig: __each__ expansion, input/output resolution,
dependency ordering, and load-time validation (no SMAX required)."""
import pytest

from slama.monitor.compute.computeconfig import ComputeConfig, _expand_entry
from slama.monitor.monitorpoint import Validity


# ---------------------------------------------------------------------------
# Fakes — avoid needing a real MonitorSystem/smax.json.
# ---------------------------------------------------------------------------

class FakeMP:
    def __init__(self, canonical_name, validity=Validity.VALID_GOOD):
        self.canonical_name = canonical_name
        self._validity = validity

    @property
    def validity(self):
        return self._validity


class FakeMonitorSystem:
    def __init__(self, names):
        self._mps = {name: FakeMP(name) for name in names}

    def get_monitor_point(self, name):
        if name not in self._mps:
            raise KeyError(name)
        return self._mps[name]

    def all_monitor_points(self):
        return list(self._mps.values())


HARDWARE_POINTS = [
    "antenna:1:is_online", "antenna:2:is_online",
    "antenna:1:air:temperature", "antenna:2:air:temperature",
    "rx:H:tuning_state", "rx:V:tuning_state",
    "antenna:1:cryostat:heaters:4K-plate",
    "weather:station:1:temperature", "weather:station:2:temperature",
    "antenna:1:receiver:tsys", "antenna:2:receiver:tsys",
]
COMPUTED_POINTS = [
    "monitorsystem:array:antennas_online",
    "monitorsystem:array:worst_status",
    "monitorsystem:rx:H:tuning_status",
    "monitorsystem:rx:V:tuning_status",
    "monitorsystem:weather:temp_min", "monitorsystem:weather:temp_max",
    "monitorsystem:antenna:1:tsys_min", "monitorsystem:antenna:1:tsys_max",
    "monitorsystem:antenna:2:tsys_min", "monitorsystem:antenna:2:tsys_max",
]


def make_ms():
    return FakeMonitorSystem(HARDWARE_POINTS + COMPUTED_POINTS)


# ---------------------------------------------------------------------------
# __each__ expansion (mirrors test_faultconfig.py's TestExpandEntry)
# ---------------------------------------------------------------------------

class TestExpandEntry:
    def test_plain_entry_passes_through(self):
        entry = {"output": "foo:bar", "function": "count_true", "inputs": ["x"]}
        assert _expand_entry(entry) == [entry]

    def test_each_expands_range(self):
        entry = {
            "__each__": {
                "over": "1-3",
                "template": {
                    "output": "monitorsystem:antenna:{i}:status",
                    "function": "worst_validity",
                    "inputs": ["antenna:{i}:*"],
                },
            }
        }
        result = _expand_entry(entry)
        assert [r["output"] for r in result] == [
            "monitorsystem:antenna:1:status",
            "monitorsystem:antenna:2:status",
            "monitorsystem:antenna:3:status",
        ]

    def test_each_with_explicit_as(self):
        entry = {
            "__each__": {
                "over": "H,V", "as": "rx",
                "template": {
                    "output": "monitorsystem:rx:{rx}:tuning_status",
                    "function": "sequence_validity",
                    "inputs": {"state": "rx:{rx}:tuning_state"},
                },
            }
        }
        result = _expand_entry(entry)
        assert [r["output"] for r in result] == [
            "monitorsystem:rx:H:tuning_status",
            "monitorsystem:rx:V:tuning_status",
        ]
        assert result[0]["inputs"] == {"state": "rx:H:tuning_state"}


# ---------------------------------------------------------------------------
# List/dict input resolution
# ---------------------------------------------------------------------------

class TestInputResolution:
    def test_list_input_range_expands(self):
        cfg = ComputeConfig.from_dict({
            "computations": [{
                "output": "monitorsystem:array:antennas_online",
                "function": "count_true",
                "inputs": ["antenna:1-2:is_online"],
            }],
        }, make_ms())
        assert cfg.nodes[0].inputs == ["antenna:1:is_online", "antenna:2:is_online"]

    def test_list_input_glob_expands(self):
        cfg = ComputeConfig.from_dict({
            "computations": [{
                "output": "monitorsystem:array:worst_status",
                "function": "worst_validity",
                "inputs": ["antenna:1:*"],
            }],
        }, make_ms())
        assert sorted(cfg.nodes[0].inputs) == [
            "antenna:1:air:temperature",
            "antenna:1:cryostat:heaters:4K-plate",
            "antenna:1:is_online",
            "antenna:1:receiver:tsys",
        ]

    def test_hyphenated_literal_segment_is_not_treated_as_a_range(self):
        # "4K-plate" is a real segment name in smax.json, not a range
        # spec -- _parse_index_set would raise ValueError trying to
        # int("4K"); _resolve_pattern must catch that and treat the
        # whole segment as a literal instead.
        cfg = ComputeConfig.from_dict({
            "computations": [{
                "output": "monitorsystem:array:antennas_online",
                "function": "count_true",
                "inputs": ["antenna:1:cryostat:heaters:4K-plate"],
            }],
        }, make_ms())
        assert cfg.nodes[0].inputs == ["antenna:1:cryostat:heaters:4K-plate"]

    def test_dict_input_resolves_single_names(self):
        cfg = ComputeConfig.from_dict({
            "computations": [{
                "output": "monitorsystem:rx:H:tuning_status",
                "function": "sequence_validity",
                "inputs": {"state": "rx:H:tuning_state"},
                "params": {"stuck_timeout_s": 90},
            }],
        }, make_ms())
        assert cfg.nodes[0].inputs == {"state": "rx:H:tuning_state"}
        assert cfg.nodes[0].params == {"stuck_timeout_s": 90}

    def test_dict_input_must_resolve_to_one_point(self):
        with pytest.raises(ValueError, match="exactly one point"):
            ComputeConfig.from_dict({
                "computations": [{
                    "output": "monitorsystem:rx:H:tuning_status",
                    "function": "sequence_validity",
                    "inputs": {"state": "antenna:1:*"},
                }],
            }, make_ms())

    def test_unresolvable_literal_input_raises(self):
        with pytest.raises(ValueError, match="not a declared point"):
            ComputeConfig.from_dict({
                "computations": [{
                    "output": "monitorsystem:array:antennas_online",
                    "function": "count_true",
                    "inputs": ["antenna:99:is_online"],
                }],
            }, make_ms())

    def test_glob_matching_nothing_raises(self):
        with pytest.raises(ValueError, match="matched no points"):
            ComputeConfig.from_dict({
                "computations": [{
                    "output": "monitorsystem:array:antennas_online",
                    "function": "count_true",
                    "inputs": ["nonexistent:*"],
                }],
            }, make_ms())


# ---------------------------------------------------------------------------
# Load-time validation
# ---------------------------------------------------------------------------

class TestValidation:
    def test_undeclared_output_raises(self):
        with pytest.raises(ValueError, match="not declared"):
            ComputeConfig.from_dict({
                "computations": [{
                    "output": "monitorsystem:does:not:exist",
                    "function": "count_true",
                    "inputs": ["antenna:1:is_online"],
                }],
            }, make_ms())

    def test_unknown_function_raises(self):
        with pytest.raises(ValueError, match="unknown compute function"):
            ComputeConfig.from_dict({
                "computations": [{
                    "output": "monitorsystem:array:antennas_online",
                    "function": "does_not_exist",
                    "inputs": ["antenna:1:is_online"],
                }],
            }, make_ms())

    def test_duplicate_output_raises(self):
        entry = {
            "output": "monitorsystem:array:antennas_online",
            "function": "count_true",
            "inputs": ["antenna:1:is_online"],
        }
        with pytest.raises(ValueError, match="duplicate computation output"):
            ComputeConfig.from_dict({"computations": [entry, dict(entry)]}, make_ms())

    def test_defaults_applied(self):
        cfg = ComputeConfig.from_dict({
            "defaults": {"interval_s": 3, "staleness_s": 60, "invalid_inputs": "propagate"},
            "computations": [{
                "output": "monitorsystem:array:antennas_online",
                "function": "count_true",
                "inputs": ["antenna:1:is_online"],
            }],
        }, make_ms())
        assert cfg.default_interval_s == 3.0
        node = cfg.nodes[0]
        assert node.staleness_s == 60.0
        assert node.invalid_inputs == "propagate"


# ---------------------------------------------------------------------------
# Dependency ordering
# ---------------------------------------------------------------------------

class TestDependencyOrder:
    def test_dependent_node_ordered_after_dependency(self):
        cfg = ComputeConfig.from_dict({
            "computations": [
                {
                    "output": "monitorsystem:array:worst_status",
                    "function": "worst_validity",
                    "inputs": ["monitorsystem:array:antennas_online"],
                },
                {
                    "output": "monitorsystem:array:antennas_online",
                    "function": "count_true",
                    "inputs": ["antenna:1:is_online"],
                },
            ],
        }, make_ms())
        outputs = [n.output for n in cfg.nodes]
        assert outputs.index("monitorsystem:array:antennas_online") < \
            outputs.index("monitorsystem:array:worst_status")

    def test_cycle_raises(self):
        with pytest.raises(ValueError, match="dependency cycle"):
            ComputeConfig.from_dict({
                "computations": [
                    {
                        "output": "monitorsystem:array:antennas_online",
                        "function": "worst_validity",
                        "inputs": ["monitorsystem:array:worst_status"],
                    },
                    {
                        "output": "monitorsystem:array:worst_status",
                        "function": "worst_validity",
                        "inputs": ["monitorsystem:array:antennas_online"],
                    },
                ],
            }, make_ms())


# ---------------------------------------------------------------------------
# Multi-output entries (design doc §8)
# ---------------------------------------------------------------------------

class TestMultiOutput:
    def test_dict_output_parses(self):
        cfg = ComputeConfig.from_dict({
            "computations": [{
                "output": {
                    "min": "monitorsystem:weather:temp_min",
                    "max": "monitorsystem:weather:temp_max",
                },
                "function": "min_max_value",
                "inputs": ["weather:station:1:temperature", "weather:station:2:temperature"],
            }],
        }, make_ms())
        node = cfg.nodes[0]
        assert node.output == {
            "min": "monitorsystem:weather:temp_min",
            "max": "monitorsystem:weather:temp_max",
        }
        assert sorted(node.output_names) == [
            "monitorsystem:weather:temp_max", "monitorsystem:weather:temp_min",
        ]

    def test_empty_output_dict_raises(self):
        with pytest.raises(ValueError, match="must not be empty"):
            ComputeConfig.from_dict({
                "computations": [{
                    "output": {},
                    "function": "min_max_value",
                    "inputs": ["weather:station:1:temperature"],
                }],
            }, make_ms())

    def test_output_wrong_type_raises(self):
        with pytest.raises(ValueError, match="must be a str or dict"):
            ComputeConfig.from_dict({
                "computations": [{
                    "output": 123,
                    "function": "min_max_value",
                    "inputs": ["weather:station:1:temperature"],
                }],
            }, make_ms())

    def test_undeclared_canonical_name_in_output_dict_raises(self):
        with pytest.raises(ValueError, match="not declared"):
            ComputeConfig.from_dict({
                "computations": [{
                    "output": {
                        "min": "monitorsystem:weather:temp_min",
                        "max": "monitorsystem:does:not:exist",
                    },
                    "function": "min_max_value",
                    "inputs": ["weather:station:1:temperature"],
                }],
            }, make_ms())

    def test_output_dict_canonical_name_colliding_with_another_entry_raises(self):
        with pytest.raises(ValueError, match="duplicate computation output"):
            ComputeConfig.from_dict({
                "computations": [
                    {
                        "output": "monitorsystem:weather:temp_min",
                        "function": "min_value",
                        "inputs": ["weather:station:1:temperature"],
                    },
                    {
                        "output": {
                            "min": "monitorsystem:weather:temp_min",
                            "max": "monitorsystem:weather:temp_max",
                        },
                        "function": "min_max_value",
                        "inputs": ["weather:station:1:temperature"],
                    },
                ],
            }, make_ms())

    def test_each_expansion_combined_with_dict_output(self):
        # __each__'s per-index substitution already recurses into nested
        # dicts (_substitute), so role keys ("min"/"max") stay constant
        # across the expansion while only the canonical-name values vary.
        cfg = ComputeConfig.from_dict({
            "computations": [{
                "__each__": {
                    "over": "1-2", "as": "i",
                    "template": {
                        "output": {
                            "min": "monitorsystem:antenna:{i}:tsys_min",
                            "max": "monitorsystem:antenna:{i}:tsys_max",
                        },
                        "function": "min_max_value",
                        "inputs": ["antenna:{i}:receiver:tsys"],
                    },
                },
            }],
        }, make_ms())
        assert [n.output for n in cfg.nodes] == [
            {"min": "monitorsystem:antenna:1:tsys_min", "max": "monitorsystem:antenna:1:tsys_max"},
            {"min": "monitorsystem:antenna:2:tsys_min", "max": "monitorsystem:antenna:2:tsys_max"},
        ]

    def test_downstream_node_may_depend_on_either_multi_output_name(self):
        cfg = ComputeConfig.from_dict({
            "computations": [
                {
                    "output": "monitorsystem:array:worst_status",
                    "function": "worst_validity",
                    "inputs": ["monitorsystem:weather:temp_max"],
                },
                {
                    "output": {
                        "min": "monitorsystem:weather:temp_min",
                        "max": "monitorsystem:weather:temp_max",
                    },
                    "function": "min_max_value",
                    "inputs": ["weather:station:1:temperature"],
                },
            ],
        }, make_ms())
        node_positions = {tuple(sorted(n.output_names)) if isinstance(n.output, dict)
                          else n.output: i for i, n in enumerate(cfg.nodes)}
        multi_pos = node_positions[("monitorsystem:weather:temp_max", "monitorsystem:weather:temp_min")]
        downstream_pos = node_positions["monitorsystem:array:worst_status"]
        assert multi_pos < downstream_pos
