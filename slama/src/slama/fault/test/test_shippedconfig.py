"""Checks on the shipped ``conf/faults.json`` against the other real configs.

No SMAX/valkey connection: :class:`MonitorSystem` is built from
``smax.json`` and :class:`ComputeConfig` from ``computations.json``.
"""
from pathlib import Path

import pytest

from slama.fault.faultconfig import HEARTBEAT_NAME, FaultConfig
from slama.monitor.compute.computeconfig import ComputeConfig
from slama.monitor.monitorpoint import Validity
from slama.monitor.monitorsystem import MonitorSystem

CONF = Path(__file__).parents[2] / "conf"
HOSTS = ["hal9000", *(f"acc{i}" for i in range(1, 9)),
         "newdds", "corcon", "m5", "colossus"]


@pytest.fixture(scope="module")
def monitor_system():
    return MonitorSystem(CONF / "smax.json")


@pytest.fixture(scope="module")
def faults():
    return FaultConfig.from_file(CONF / "faults.json")


@pytest.fixture(scope="module")
def computed_outputs(monitor_system):
    cfg = ComputeConfig.from_file(CONF / "computations.json", monitor_system)
    return {name for node in cfg.nodes for name in node.output_names}


def test_shipped_faults_load(faults):
    # heartbeat + 13 hosts + 13 x 24 slots + 16 processes + 32 antenna nodes
    assert len(faults.nodes) == 1 + 13 + 312 + 16 + 32


def test_every_watched_name_is_declared_and_computed(faults, monitor_system,
                                                     computed_outputs):
    """A typo would read NO_DATA forever; an uncomputed point the same."""
    watched = set(faults.nodes)
    for node in faults.nodes.values():
        watched.update(node.context)
    for name in sorted(watched):
        monitor_system.get_monitor_point(name)          # KeyError if undeclared
        # The engine writes the heartbeat itself, not from a config entry.
        assert name in computed_outputs | {HEARTBEAT_NAME}, \
            f"{name} is not a compute-engine output"


@pytest.mark.parametrize("host", HOSTS)
def test_host_down_onset_matches_smax_json(faults, monitor_system, host):
    """onset_s duplicates smax.json's host-down age; keep them in step."""
    name = f"monitorsystem:smainit:{host}:report_age"
    mp = monitor_system.get_monitor_point(name)
    assert faults.nodes[name].onset_s == mp.err_high == -mp.err_low


def test_heartbeat_parents_everything(faults):
    for name, node in faults.nodes.items():
        if name != HEARTBEAT_NAME:
            assert HEARTBEAT_NAME in node.parents, name


@pytest.mark.parametrize("i", range(1, 9))
def test_antenna_edges(faults, i):
    acc = f"monitorsystem:smainit:acc{i}"
    ant = f"monitorsystem:antenna:{i}"
    assert set(faults.nodes[f"{ant}:drive_fault"].parents) == {
        f"{acc}:report_age", f"{acc}:process:servo", HEARTBEAT_NAME}
    for gunn in ("gunn1", "gunn2"):
        node = faults.nodes[f"{ant}:{gunn}_lock_fault"]
        # report_age and tune6 directly: hiding is not transitive through a
        # yig1 that is not faulted (frozen GOOD when acc{i} dies).
        assert set(node.parents) >= {f"{ant}:yig1_lock_fault",
                                     f"{acc}:report_age", f"{acc}:process:tune6"}
        assert node.context == [f"{ant}:{gunn}_pll_ifpower", f"{ant}:{gunn}_pll_noise"]


@pytest.mark.parametrize("label, expected", [
    ("running", Validity.VALID_GOOD),
    ("terminated", Validity.VALID_ERROR),
    ("absent", Validity.VALID_NOT_CHECKED),
    ("?", Validity.VALID_ERROR),
])
def test_process_state_validity(monitor_system, label, expected):
    from slama.monitor.compute.engine import _wrap

    mp = monitor_system.get_monitor_point("monitorsystem:smainit:acc4:process:tune6")
    mp.update(_wrap(label, 1_790_000_000.0))
    assert mp.validity is expected


def test_faultsystem_points_declared(monitor_system):
    from slama.fault.publish import FAULT_HEARTBEAT_NAME as FS_HEARTBEAT, STATE_NAME
    assert monitor_system.get_monitor_point(STATE_NAME).table == "faultsystem"
    assert monitor_system.get_monitor_point(FS_HEARTBEAT).key == "heartbeat"


def test_shipped_snapshot_size(faults):
    """Worst case (every node hidden, with hidden_by) is about 75 KB.

    Redis allows 512 MB strings; the bound only catches an accidental
    blow-up of the format. A typical tick (mostly ok) is about 40 KB.
    """
    import json

    from slama.fault.publish import build_snapshot

    names = set(faults.nodes)
    snapshot = build_snapshot(
        faults.nodes, validities={n: Validity.INVALID_NO_DATA for n in names},
        faulted=names, debounced=names, hidden=names - {HEARTBEAT_NAME},
        is_ignored=lambda n: False, tick=1_790_094_623.123456, interval_s=2.0)
    assert len(json.dumps(snapshot, separators=(",", ":"))) < 128 * 1024
