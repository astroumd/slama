"""Load the real ``conf/smax.json`` + ``conf/computations.json`` together.

No SMAX/valkey connection: :class:`MonitorSystem` is built from JSON
only and :meth:`ComputeConfig.from_file` does all of its load-time
validation (outputs declared under ``monitorsystem``, every input
pattern resolving, functions registered, no dependency cycles) against
the real tree. This is the check that catches a wrong DSM host, an
undeclared output, or a typo in a canonical name before anything is
run against the live system.
"""
from pathlib import Path

import pytest

from slama.monitor.compute.computeconfig import ComputeConfig
from slama.monitor.monitorsystem import MonitorSystem

CONF = Path(__file__).parents[3] / "conf"


@pytest.fixture(scope="module")
def monitor_system():
    return MonitorSystem(CONF / "smax.json")


def test_real_computations_load(monitor_system):
    cfg = ComputeConfig.from_file(CONF / "computations.json", monitor_system)
    assert cfg.nodes, "computations.json produced no nodes"


def test_every_output_is_under_monitorsystem(monitor_system):
    cfg = ComputeConfig.from_file(CONF / "computations.json", monitor_system)
    for node in cfg.nodes:
        for name in node.output_names:
            assert name.startswith("monitorsystem:"), name


@pytest.mark.parametrize("ant", range(1, 9))
def test_active_high_receiver_declared(monitor_system, ant):
    mp = monitor_system.get_monitor_point(f"RM:acc{ant}:RM_ACTIVE_HIGH_RECEIVER_C10")
    assert mp.canonical_name == f"RM:acc{ant}:RM_ACTIVE_HIGH_RECEIVER_C10"
