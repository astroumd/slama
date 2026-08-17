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
]
COMPUTED_POINTS = [
    "monitorsystem:array:antennas_online",
    "monitorsystem:array:worst_status",
    "monitorsystem:rx:H:tuning_status",
    "monitorsystem:rx:V:tuning_status",
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
            "antenna:1:air:temperature", "antenna:1:is_online",
        ]

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
