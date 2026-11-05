"""Tests for the fault-system computed points (fault-system phase 3).

Covers :func:`fault_gate`, :func:`lo_lock_faults`, :func:`write_age` and
:func:`smainit_slots`, plus the helpers they share. No SMAX needed.
"""
import numpy as np
import pytest

from slama.monitor.compute.computenode import ComputeContext, ResolvedInput
from slama.monitor.compute.functions import (
    HI_LO_FREQ_CUTOFF_HZ,
    PHASE_LOCK_IS_STALE_S,
    _is_on,
    _tune6_busy,
    _wsma_chain_units,
    fault_gate,
    lo_lock_faults,
    smainit_slots,
    write_age,
)
from slama.monitor.monitorpoint import Validity

# The compute test directory is not a package, so these mirror the
# helpers of the same names in test_functions.py.
WALL_NOW = 1_790_000_000.0
WSELECT_GHDL = {"1": "G", "2": "H", "3": "D", "4": "L"}
"""Live wselect.conf row for antennas 1, 7, 8 (2026-10-20)."""


def ri(name, value, validity=Validity.VALID_GOOD):
    return ResolvedInput(name, value, validity)


def ctx(params=None):
    return ComputeContext(clock=lambda: 0.0, state={}, params=params or {},
                          wall_clock=lambda: WALL_NOW)


def wsma_inputs(pos, locks=None, cart_a=None, mix_a=None, cart_b=None, mix_b=None, **extra):
    """wSMA-shape inputs; ``locks`` maps role (``lock_L1``...) -> value, others None."""
    locks = locks or {}
    vals = {"selector": pos, "cart_a": cart_a, "mix_a": mix_a, "cart_b": cart_b, "mix_b": mix_b,
            **{r: locks.get(r) for r in ("lock_L1", "lock_L2", "lock_H1")}, **extra}
    return {k: ri(k, v) for k, v in vals.items()}


GOOD, ERROR = Validity.VALID_GOOD, Validity.VALID_ERROR
NC, NO_DATA = Validity.VALID_NOT_CHECKED, Validity.INVALID_NO_DATA
LOW, HIGH = 230e9, 690e9


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class TestTune6Busy:
    @pytest.mark.parametrize("code", [1, 4, 12, 12.0, np.int16(3)])
    def test_valid_codes_are_busy(self, code):
        assert _tune6_busy(code)

    @pytest.mark.parametrize("code", [0, 13, -702, 30334, 24668, -8224, 2.5, None, "x"])
    def test_idle_garbage_and_missing_are_not_busy(self, code):
        assert not _tune6_busy(code)


class TestIsOn:
    @pytest.mark.parametrize("v, expected", [(1, True), (2, True), (0, False), (0.0, False),
                                             (None, True), ("junk", True)])
    def test_only_a_readable_zero_is_off(self, v, expected):
        assert _is_on(v) is expected


class TestWsmaChainUnits:
    def test_h_band_forces_unit_1(self):
        units = _wsma_chain_units(wsma_inputs(2), ctx(params={"wselect": WSELECT_GHDL}))
        assert units == [("H", 1), ("H", 1)]

    def test_l_mode_uses_both_mixers(self):
        units = _wsma_chain_units(wsma_inputs(4), ctx(params={"wselect": WSELECT_GHDL}))
        assert units == [("L", 1), ("L", 2)]


# ---------------------------------------------------------------------------
# fault_gate (drive_fault)
# ---------------------------------------------------------------------------

class TestFaultGate:
    def test_online_passes_verdict_through(self):
        out = fault_gate({"subject": ri("d", "ESTOP", ERROR), "online": ri("o", True)}, ctx())
        assert out == ("ESTOP", ERROR)

    def test_offline_is_not_checked(self):
        out = fault_gate({"subject": ri("d", "ESTOP", ERROR), "online": ri("o", False)}, ctx())
        assert out == ("ESTOP", NC)

    def test_offline_with_no_drive_data_is_not_checked(self):
        # hangar antenna, servo off or acc down: drive_status is NO_DATA
        out = fault_gate({"subject": ri("d", None, NO_DATA), "online": ri("o", False)}, ctx())
        assert out == (None, NC)

    def test_online_with_no_drive_data_is_no_data(self):
        out = fault_gate({"subject": ri("d", None, NO_DATA), "online": ri("o", True)}, ctx())
        assert out == (None, NO_DATA)


# ---------------------------------------------------------------------------
# lo_lock_faults
# ---------------------------------------------------------------------------

def tune6(g1=1, g2=1, y1=1, rest=LOW, age=10.0, online=True, **opt):
    """Tune6-shape inputs; ``opt`` adds optional roles (busy, gunnN_on, ...)."""
    inputs = {
        "online": ri("o", online), "yig1": ri("y1", y1),
        "gunn1": ri("g1", g1), "gunn2": ri("g2", g2),
        "gunn1_ts": ri("t", WALL_NOW - age),
        "rest_freq": ri("f", np.array([rest, rest])),
    }
    inputs.update({k: ri(k, v) for k, v in opt.items()})
    return lo_lock_faults(inputs, ctx())


def verdicts(out):
    return out["yig1"][1], out["gunn1"][1], out["gunn2"][1]


class TestLoLockFaultsTune6:
    def test_all_locked_unneeded_chain_is_not_checked(self):
        # low band: gunn2 is "don't care" even when locked
        assert verdicts(tune6()) == (GOOD, GOOD, NC)
        assert verdicts(tune6(rest=HIGH)) == (GOOD, NC, GOOD)

    def test_low_band_needs_only_gunn1(self):
        assert verdicts(tune6(g2=0)) == (GOOD, GOOD, NC)
        assert verdicts(tune6(g1=0)) == (GOOD, ERROR, NC)

    def test_high_band_needs_only_gunn2(self):
        assert verdicts(tune6(g1=0, rest=HIGH)) == (GOOD, NC, GOOD)
        assert verdicts(tune6(g2=0, rest=HIGH)) == (GOOD, NC, ERROR)

    def test_exactly_at_cutoff_needs_both(self):
        # lo_lock_ok: neither > nor < the cutoff, so only "all locked" passes
        assert verdicts(tune6(g2=0, rest=HI_LO_FREQ_CUTOFF_HZ)) == (GOOD, GOOD, ERROR)

    def test_yig1_unlocked_is_error_not_warning(self):
        # yig_locked says WARNING; the fault view must say ERROR
        out = tune6(y1=0)
        assert out["yig1"] == (False, ERROR)

    def test_offline_is_not_checked_everywhere(self):
        assert verdicts(tune6(g1=0, y1=0, online=False)) == (NC, NC, NC)

    @pytest.mark.parametrize("busy", [1, 12])
    def test_valid_busy_code_is_good(self, busy):
        assert verdicts(tune6(g1=0, y1=0, busy=busy)) == (GOOD, GOOD, GOOD)

    def test_busy_latched_with_stale_heartbeat_is_not_trusted(self):
        # tune6 died mid-tune: busy keeps its last code, the heartbeat ages
        out = tune6(g1=0, y1=0, busy=1, age=PHASE_LOCK_IS_STALE_S + 1)
        assert out["gunn1"] == (False, NO_DATA)
        assert out["yig1"] == (False, ERROR)
        assert verdicts(tune6(busy=1, age=PHASE_LOCK_IS_STALE_S + 1)) == (GOOD, NO_DATA, NC)

    @pytest.mark.parametrize("busy", [0, 30334, -702, None])
    def test_idle_or_garbage_busy_still_alerts(self, busy):
        assert verdicts(tune6(g1=0, busy=busy))[1] == ERROR

    def test_gunn_off_is_not_checked(self):
        assert verdicts(tune6(g1=0, gunn1_on=0)) == (GOOD, NC, NC)

    def test_missing_on_flag_counts_as_on(self):
        assert verdicts(tune6(g1=0, gunn1_on=None))[1] == ERROR

    def test_stale_heartbeat_is_no_data_not_error(self):
        out = tune6(age=PHASE_LOCK_IS_STALE_S + 1)
        assert out["gunn1"] == (True, NO_DATA)
        assert out["yig1"][1] == GOOD

    def test_stale_heartbeat_on_unneeded_chain_is_not_checked(self):
        assert verdicts(tune6(age=PHASE_LOCK_IS_STALE_S + 1, rest=HIGH))[1] == NC

    def test_pll_context_values(self):
        out = tune6(gunn1_ifpower=0.25, gunn2_ifpower=0.5, gunn1_noise=0.01, gunn2_noise=None)
        assert out["gunn1_ifpower"] == 0.25 and out["gunn2_ifpower"] == 0.5
        assert out["gunn1_noise"] == 0.01
        assert out["gunn2_noise"] == (None, NO_DATA)

    @pytest.mark.parametrize("bad", ["garbage", "", np.array([1.0, 2.0]), object()])
    def test_bad_pll_value_keeps_the_lock_verdicts(self, bad):
        out = tune6(g1=0, gunn1_ifpower=bad, gunn1_noise=np.array([0.5]))
        assert out["gunn1_ifpower"] == (None, NO_DATA)
        assert out["gunn1_noise"] == 0.5
        assert verdicts(out) == (GOOD, ERROR, NC)

    def test_returns_exactly_the_declared_roles(self):
        assert set(tune6()) == {"yig1", "gunn1", "gunn2", "gunn1_ifpower", "gunn2_ifpower",
                                "gunn1_noise", "gunn2_noise"}


class TestLoLockFaultsWsma:
    def _run(self, pos, locks, rest=LOW, online=True, **extra):
        inputs = wsma_inputs(pos, locks, yig1=1, rest_freq=np.array([rest, rest]),
                             online=online, **extra)
        return lo_lock_faults(inputs, ctx(params={"wselect": WSELECT_GHDL}))

    def test_l_mode_locked(self):
        assert verdicts(self._run(4, {"lock_L1": 1, "lock_L2": 1})) == (GOOD, GOOD, NC)
        assert verdicts(self._run(4, {"lock_L1": 1, "lock_L2": 1}, rest=HI_LO_FREQ_CUTOFF_HZ)) \
            == (GOOD, GOOD, GOOD)

    def test_l_mode_needed_chain_unlocked(self):
        assert verdicts(self._run(4, {"lock_L2": 1})) == (GOOD, ERROR, NC)

    def test_no_heartbeat_and_no_busy(self):
        # no gunn1_ts and no busy inputs exist on the wSMA shape
        assert verdicts(self._run(2, {"lock_H1": 1}, rest=HIGH)) == (GOOD, NC, GOOD)

    def test_vco_off_for_selected_unit_is_not_checked(self):
        # pos 4 = L: RxA uses L1, RxB uses L2
        out = self._run(4, {}, vco_L1=0, vco_L2=1)
        assert verdicts(out)[1] == NC

    def test_pll_context_from_selected_unit(self):
        out = self._run(1, {}, bpf_H1=0.3, nf_H1=0.02, bpf_L2=0.7, nf_L2=0.04)
        # pos 1 = G: RxA high (H1), RxB low (L2)
        assert out["gunn1_ifpower"] == 0.3 and out["gunn1_noise"] == 0.02
        assert out["gunn2_ifpower"] == 0.7 and out["gunn2_noise"] == 0.04

    def test_unknown_selector_gives_no_context(self):
        out = self._run(-1, {})
        assert out["gunn1_ifpower"] == (None, NO_DATA)


# ---------------------------------------------------------------------------
# smainit
# ---------------------------------------------------------------------------

class TestWriteAge:
    def test_age_from_write_timestamp(self):
        assert write_age({"report": ResolvedInput("r", [0], GOOD, WALL_NOW - 42)}, ctx()) == 42

    def test_no_timestamp_is_no_data(self):
        assert write_age({"report": ResolvedInput("r", [0], GOOD, None)}, ctx()) == (None, NO_DATA)


def slots(statuses, names, age_validity=GOOD, normally_dead=("int_control", "c1DCInit"), flat=False):
    """Run smainit_slots with up to 24 statuses/names, padding the rest as empty."""
    rows = np.zeros((24, 6), dtype=np.int32)
    for j, s in enumerate(statuses):
        rows[j][0] = s
    padded = list(names) + [""] * (24 - len(names))
    inputs = {
        "status": ri("s", rows.reshape(-1) if flat else rows),
        "names": ri("n", padded),
        "age": ri("a", 5.0, age_validity),
    }
    return smainit_slots(inputs, ctx(params={"normally_dead": list(normally_dead)}))


class TestSmainitSlots:
    def test_running_and_dead_labels(self):
        out = slots([0, 2, 1], ["dsm", "servo", "tune6"])
        # bare labels: the output's state_validity in smax.json colours them
        assert out["status_0"] == "running"
        assert out["status_1"] == "terminated"
        assert out["status_2"] == "quit"
        assert out["name_1"] == ("servo", NC)

    def test_empty_slot_is_not_checked(self):
        out = slots([0], ["dsm"])
        assert out["status_5"] == ("running", NC)
        assert out["name_5"] == ("", NC)

    def test_normally_dead_program_is_not_checked(self):
        assert slots([0, 1], ["dsm", "int_control"])["status_1"] == ("quit", NC)

    @pytest.mark.parametrize("age_validity", [Validity.VALID_ERROR_HIGH, ERROR])
    def test_stale_host_makes_every_slot_not_checked(self, age_validity):
        out = slots([0, 2], ["dsm", "servo"], age_validity=age_validity)
        assert out["status_1"] == ("terminated", NC)

    def test_out_of_range_code_is_unknown_label(self):
        assert slots([99], ["dsm"])["status_0"] == "?"

    def test_flat_144_vector_accepted(self):
        assert slots([0, 2], ["dsm", "servo"], flat=True)["status_1"] == "terminated"

    def test_bytes_and_nul_padded_names(self):
        out = slots([0], [b"dsm\x00\x00"])
        assert out["name_0"] == ("dsm", NC)

    def test_bad_shape_raises(self):
        with pytest.raises(ValueError):
            smainit_slots({"status": ri("s", [0, 1, 2]), "names": ri("n", ["a"]),
                           "age": ri("a", 1.0)}, ctx())

    def test_returns_48_roles(self):
        assert len(slots([], [])) == 48
