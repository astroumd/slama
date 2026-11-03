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
from slama.monitor.monitorpoint import Validity
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


@pytest.mark.parametrize("amps, expected", [
    (49.9, "ok"), (50.0, "Motor"), (99.9, "Motor"), (100.0, "Motor!"),
])
def test_motor_alarm_uses_smax_thresholds(monitor_system, amps, expected):
    """``motor_alarm``'s levels come from the raw points' smax.json thresholds."""
    from slama.monitor.compute.computenode import ResolvedInput
    from slama.monitor.compute.engine import _wrap
    from slama.monitor.compute.functions import motor_alarm

    resolved = {}
    for role, rm in (("az1", "RM_AZ1_MOT_CUR_AMP_F"), ("az2", "RM_AZ2_MOT_CUR_AMP_F")):
        name = f"RM:acc3:{rm}"
        mp = monitor_system.get_monitor_point(name)
        mp.update(_wrap(amps if role == "az1" else 0.0, 1_790_000_000.0))
        resolved[role] = ResolvedInput(name, mp.value, mp.validity)
    assert motor_alarm(resolved, None) == expected


@pytest.mark.parametrize("name, value, expected", [
    # The C flags > 0.02"; SLAMA's warn_high fires at >= 0.02.
    ("monitorsystem:array:pointing_offset_spread_arcsec", 0.0199, Validity.VALID_GOOD),
    ("monitorsystem:array:pointing_offset_spread_arcsec", 0.02, Validity.VALID_WARNING_HIGH),
    # |offset| >= 10000" is the C's standout wacko.
    ("monitorsystem:array:ra_offset_arcsec", 9999.9, Validity.VALID_GOOD),
    ("monitorsystem:array:ra_offset_arcsec", 10000.0, Validity.VALID_WARNING_HIGH),
    ("monitorsystem:array:dec_offset_arcsec", -10000.0, Validity.VALID_WARNING_LOW),
    ("monitorsystem:array:dec_offset_arcsec", -9999.9, Validity.VALID_GOOD),
])
def test_pointing_offset_smax_thresholds(monitor_system, name, value, expected):
    """The offset levels are defined only in smax.json."""
    from slama.monitor.compute.engine import _wrap

    mp = monitor_system.get_monitor_point(name)
    mp.update(_wrap(value, 1_790_000_000.0))
    assert mp.validity is expected


@pytest.mark.parametrize("name, value, expected", [
    # ser7.dat age (Marc, 2026-10-22): <= 10 d GOOD, 10-15 d WARNING, > 15 d ERROR.
    ("monitorsystem:array:polar_file_age_s", 10 * 86400 - 1, Validity.VALID_GOOD),
    ("monitorsystem:array:polar_file_age_s", 10 * 86400, Validity.VALID_WARNING_HIGH),
    ("monitorsystem:array:polar_file_age_s", 15 * 86400 - 1, Validity.VALID_WARNING_HIGH),
    ("monitorsystem:array:polar_file_age_s", 15 * 86400, Validity.VALID_ERROR_HIGH),
    # The C's "N days old" when > 2.
    ("monitorsystem:array:polar_days_old", 2, Validity.VALID_GOOD),
    ("monitorsystem:array:polar_days_old", 3, Validity.VALID_WARNING_HIGH),
    # The C's DUT wacko.
    ("monitorsystem:array:polar_dut_s", 99999.0, Validity.VALID_GOOD),
    ("monitorsystem:array:polar_dut_s", -100000.0, Validity.VALID_WARNING_LOW),
])
def test_polar_smax_thresholds(monitor_system, name, value, expected):
    """The polar levels are defined only in smax.json."""
    from slama.monitor.compute.engine import _wrap

    mp = monitor_system.get_monitor_point(name)
    mp.update(_wrap(value, 1_790_000_000.0))
    assert mp.validity is expected


@pytest.mark.parametrize("name, value, expected", [
    # The C's on-source limit is 1"; SLAMA's err_high fires at >= 1.0.
    ("RM:acc3:RM_TRACKING_ERROR_ARCSEC_F", 0.9999, Validity.VALID_GOOD),
    ("RM:acc3:RM_TRACKING_ERROR_ARCSEC_F", 1.0, Validity.VALID_ERROR_HIGH),
    # dewar 4K wacko floor (the C's "wac"), and the dewarTemp.conf limit.
    ("monitorsystem:antenna:3:dewar_4k_temp", 2.0, Validity.VALID_ERROR_LOW),
    ("monitorsystem:antenna:3:dewar_4k_temp", 2.1, Validity.VALID_GOOD),
    # hour_angle's wacko: |HA| >= 100 h, tested on the RA input.
    ("RM:acc3:RM_RA_APP_HR_D", 99.9, Validity.VALID_GOOD),
    ("RM:acc3:RM_RA_APP_HR_D", 100.0, Validity.VALID_ERROR_HIGH),
    # scan age wacko: >= 100 days, or below -100 s.
    ("monitorsystem:array:scan_age_s", 8639999.0, Validity.VALID_GOOD),
    ("monitorsystem:array:scan_age_s", 8640000.0, Validity.VALID_ERROR_HIGH),
    ("monitorsystem:array:scan_age_s", -100.0, Validity.VALID_ERROR_LOW),
    ("monitorsystem:array:scan_age_s", -99.0, Validity.VALID_GOOD),
    # wind: 150 mph = 67.056 m/s is the wacko limit; direction wacko is (-99, 400].
    ("monitorsystem:weather:wind_speed", 67.05, Validity.VALID_WARNING_HIGH),
    ("monitorsystem:weather:wind_speed", 67.056, Validity.VALID_ERROR_HIGH),
    ("monitorsystem:weather:wind_speed", 5.0, Validity.VALID_GOOD),
    ("monitorsystem:weather:wind_direction", -99.0, Validity.VALID_ERROR_LOW),
    ("monitorsystem:weather:wind_direction", 399.9, Validity.VALID_GOOD),
    ("monitorsystem:weather:wind_direction", 400.0, Validity.VALID_ERROR_HIGH),
])
def test_moved_validity_thresholds(monitor_system, name, value, expected):
    """Levels that used to be constants in functions.py are defined only in smax.json."""
    from slama.monitor.compute.engine import _wrap

    mp = monitor_system.get_monitor_point(name)
    mp.update(_wrap(value, 1_790_000_000.0))
    assert mp.validity is expected


# ---------------------------------------------------------------------------
# Fault-system computed points (phase 3)
# ---------------------------------------------------------------------------

SMAINIT_HOSTS = ["hal9000", *(f"acc{i}" for i in range(1, 9)), "newdds", "corcon", "m5", "colossus"]


def _outputs(monitor_system):
    cfg = ComputeConfig.from_file(CONF / "computations.json", monitor_system)
    return {n for node in cfg.nodes for n in node.output_names}


def test_fault_points_are_computed(monitor_system):
    outs = _outputs(monitor_system)
    for i in range(1, 9):
        for leaf in ("drive_fault", "yig1_lock_fault", "gunn1_lock_fault", "gunn2_lock_fault",
                     "gunn1_pll_ifpower", "gunn2_pll_ifpower", "gunn1_pll_noise", "gunn2_pll_noise"):
            assert f"monitorsystem:antenna:{i}:{leaf}" in outs
        assert f"monitorsystem:antenna:{i}:yig2_lock_fault" not in outs  # the C never requires YIG2
    for h in SMAINIT_HOSTS:
        assert f"monitorsystem:smainit:{h}:report_age" in outs
        for j in range(24):
            assert f"monitorsystem:smainit:{h}:slot:{j}:status" in outs
            assert f"monitorsystem:smainit:{h}:slot:{j}:name" in outs
    assert not any(":crate" in n for n in outs)  # absent hosts (#56-3)


def test_engine_heartbeat_declared(monitor_system):
    from slama.monitor.compute.engine import HEARTBEAT_NAME
    mp = monitor_system.get_monitor_point(HEARTBEAT_NAME)  # KeyError if undeclared
    assert mp.canonical_name == HEARTBEAT_NAME


@pytest.mark.parametrize("name", [
    "antenna:{i}:receiver:L:lo_plate:mixer:1:pll:BPF",
    "antenna:{i}:receiver:L:lo_plate:mixer:2:pll:NF",
    "antenna:{i}:receiver:H:lo_plate:mixer:1:pll:BPF",
    "antenna:{i}:receiver:H:lo_plate:mixer:1:pll:NF",
    "antenna:{i}:receiver:L:lo_plate:mixer:2:vco:is_enabled",
    "antenna:{i}:receiver:H:lo_plate:mixer:1:vco:is_enabled",
])
def test_wsma_lo_inputs_declared(monitor_system, name):
    for i in (1, 7, 8):
        monitor_system.get_monitor_point(name.format(i=i))


@pytest.mark.parametrize("name, value, expected", [
    # smainitMonitor.c 126: a report more than 70 s old means the host is down.
    ("monitorsystem:smainit:acc3:report_age", 69.9, Validity.VALID_GOOD),
    ("monitorsystem:smainit:acc3:report_age", 70.0, Validity.VALID_ERROR_HIGH),
    # ... and labs(): a report more than 70 s in the future is not reporting either.
    ("monitorsystem:smainit:acc3:report_age", -69.9, Validity.VALID_GOOD),
    ("monitorsystem:smainit:acc3:report_age", -70.0, Validity.VALID_ERROR_LOW),
    # receiverMonitor.c wacko (printDisabled, red): IF power outside +/-1e6, noise outside +/-10.
    ("monitorsystem:antenna:4:gunn1_pll_ifpower", 0.5, Validity.VALID_GOOD),
    ("monitorsystem:antenna:4:gunn1_pll_ifpower", -1.4e29, Validity.VALID_ERROR_LOW),
    ("monitorsystem:antenna:4:gunn2_pll_noise", 9.9, Validity.VALID_GOOD),
    ("monitorsystem:antenna:4:gunn2_pll_noise", 9.8e33, Validity.VALID_ERROR_HIGH),
])
def test_fault_point_levels(monitor_system, name, value, expected):
    """Fault-point levels are defined only in smax.json."""
    from slama.monitor.compute.engine import _wrap

    mp = monitor_system.get_monitor_point(name)
    mp.update(_wrap(value, 1_790_000_000.0))
    assert mp.validity is expected


@pytest.mark.parametrize("label, expected", [
    ("running", Validity.VALID_GOOD),          # setEnabled, green
    ("terminated", Validity.VALID_ERROR),      # setDisabled, red
    ("quit", Validity.VALID_ERROR),
    ("suspended", Validity.VALID_ERROR),
    ("?", Validity.VALID_ERROR),               # unknown_state
])
def test_smainit_status_state_validity(monitor_system, label, expected):
    from slama.monitor.compute.engine import _wrap

    mp = monitor_system.get_monitor_point("monitorsystem:smainit:acc3:slot:8:status")
    mp.update(_wrap(label, 1_790_000_000.0))
    assert mp.validity is expected
