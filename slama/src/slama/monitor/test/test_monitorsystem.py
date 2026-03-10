"""Unit tests for MonitorSystem (no SMAX server required)."""
import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, call
from slama.monitor.monitorpoint import MonitorPoint
from slama.monitor.monitorsystem import MonitorSystem, MonitorSubsystem

# Path to the small fixture JSON bundled with this test directory
FIXTURE = Path(__file__).parent / "fixture_smax.json"

# Path to the full production config (for smoke tests)
SMAX_JSON = Path(__file__).parents[2] / "conf" / "smax.json"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def ms():
    """MonitorSystem built from the small fixture JSON."""
    return MonitorSystem(FIXTURE)


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------

class TestConstruction:
    def test_builds_without_error(self, ms):
        assert ms is not None

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            MonitorSystem(tmp_path / "nonexistent.json")

    def test_root_node_exists(self, ms):
        assert ms.get_node("root") is not None

    def test_root_data_is_subsystem(self, ms):
        assert isinstance(ms.get_node("root").data, MonitorSubsystem)

    def test_correct_monitor_point_count(self, ms):
        # fixture has 4 leaf monitor points
        assert len(ms.all_monitor_points()) == 4

    def test_branch_nodes_are_subsystems(self, ms):
        branch_nodes = [
            n for n in ms.all_nodes_itr()
            if not ms.get_node(n.identifier).is_leaf()
        ]
        for node in branch_nodes:
            assert isinstance(node.data, MonitorSubsystem)

    def test_leaf_nodes_are_monitor_points(self, ms):
        for node in ms.leaves():
            assert isinstance(node.data, MonitorPoint)


# ---------------------------------------------------------------------------
# Canonical names and tree structure
# ---------------------------------------------------------------------------

class TestCanonicalNames:
    def test_sensor1_canonical_name(self, ms):
        mp = ms.get_monitor_point("subsystem_a:sensor1")
        assert mp.canonical_name == "subsystem_a:sensor1"

    def test_sensor1_table_and_key(self, ms):
        mp = ms.get_monitor_point("subsystem_a:sensor1")
        assert mp.table == "subsystem_a"
        assert mp.key == "sensor1"

    def test_deep_nested_canonical_name(self, ms):
        mp = ms.get_monitor_point("subsystem_a:nested:deep_value")
        assert mp.canonical_name == "subsystem_a:nested:deep_value"
        assert mp.table == "subsystem_a:nested"
        assert mp.key == "deep_value"

    def test_subsystem_b_flag(self, ms):
        mp = ms.get_monitor_point("subsystem_b:flag")
        assert mp.table == "subsystem_b"
        assert mp.key == "flag"

    def test_all_canonical_names(self, ms):
        names = {mp.canonical_name for mp in ms.all_monitor_points()}
        assert names == {
            "subsystem_a:sensor1",
            "subsystem_a:sensor2",
            "subsystem_a:nested:deep_value",
            "subsystem_b:flag",
        }


# ---------------------------------------------------------------------------
# Monitor point metadata from JSON
# ---------------------------------------------------------------------------

class TestMonitorPointMetadata:
    def test_description(self, ms):
        mp = ms.get_monitor_point("subsystem_a:sensor1")
        assert mp.description == "Temperature sensor"

    def test_unit(self, ms):
        mp = ms.get_monitor_point("subsystem_a:sensor1")
        assert mp.unit == "C"

    def test_deep_value_unit(self, ms):
        mp = ms.get_monitor_point("subsystem_a:nested:deep_value")
        assert mp.unit == "V"

    def test_no_unit_stored_as_none_string(self, ms):
        mp = ms.get_monitor_point("subsystem_a:sensor2")
        # smax.json entries without 'unit' produce unit="None"
        assert mp.unit == "None"

    def test_value_initially_none(self, ms):
        mp = ms.get_monitor_point("subsystem_a:sensor1")
        assert mp.value is None


# ---------------------------------------------------------------------------
# get_monitor_point
# ---------------------------------------------------------------------------

class TestGetMonitorPoint:
    def test_returns_monitor_point(self, ms):
        mp = ms.get_monitor_point("subsystem_a:sensor1")
        assert isinstance(mp, MonitorPoint)

    def test_missing_raises_key_error(self, ms):
        with pytest.raises(KeyError):
            ms.get_monitor_point("does:not:exist")

    def test_branch_node_raises_key_error(self, ms):
        # "subsystem_a" is a branch, not a MonitorPoint
        with pytest.raises(KeyError):
            ms.get_monitor_point("subsystem_a")


# ---------------------------------------------------------------------------
# SMAX I/O (mocked client)
# ---------------------------------------------------------------------------

class TestReadAll:
    def test_read_all_calls_smax_pull_for_each_mp(self, ms):
        client = MagicMock()
        client.smax_pull.return_value = 42.0
        ms.read_all(client)
        mps = ms.all_monitor_points()
        assert client.smax_pull.call_count == len(mps)

    def test_read_all_pulls_correct_table_and_key(self, ms):
        client = MagicMock()
        client.smax_pull.return_value = 1.0
        ms.read_all(client)
        expected_calls = [
            call("subsystem_a", "sensor1"),
            call("subsystem_a", "sensor2"),
            call("subsystem_a:nested", "deep_value"),
            call("subsystem_b", "flag"),
        ]
        actual_calls = client.smax_pull.call_args_list
        assert sorted(actual_calls, key=str) == sorted(expected_calls, key=str)

    def test_read_all_updates_mp_values(self, ms):
        client = MagicMock()
        client.smax_pull.return_value = 99.9
        ms.read_all(client)
        for mp in ms.all_monitor_points():
            assert mp.value == 99.9


class TestWrite:
    def test_write_calls_smax_share(self, ms):
        client = MagicMock()
        ms.write("subsystem_a:sensor1", 25.0, client)
        client.smax_share.assert_called_once_with("subsystem_a", "sensor1", 25.0)

    def test_write_deep_node(self, ms):
        client = MagicMock()
        ms.write("subsystem_a:nested:deep_value", 3.3, client)
        client.smax_share.assert_called_once_with("subsystem_a:nested", "deep_value", 3.3)

    def test_write_missing_canonical_raises(self, ms):
        client = MagicMock()
        with pytest.raises(KeyError):
            ms.write("no:such:point", 0, client)


# ---------------------------------------------------------------------------
# Display methods (smoke tests — just verify no exceptions)
# ---------------------------------------------------------------------------

class TestDisplay:
    def test_summary_runs(self, ms, capsys):
        ms.summary()
        out = capsys.readouterr().out
        assert len(out) > 0

    def test_details_runs(self, ms, capsys):
        ms.details()
        out = capsys.readouterr().out
        assert len(out) > 0


# ---------------------------------------------------------------------------
# Smoke test against full smax.json
# ---------------------------------------------------------------------------

class TestFullSmaxJson:
    def test_builds_from_full_config(self):
        ms = MonitorSystem(SMAX_JSON)
        mps = ms.all_monitor_points()
        assert len(mps) > 100  # smax.json has hundreds of monitor points

    def test_antenna_temperature_reachable(self):
        ms = MonitorSystem(SMAX_JSON)
        mp = ms.get_monitor_point("antenna:1:air:temperature")
        assert mp.table == "antenna:1:air"
        assert mp.key == "temperature"
