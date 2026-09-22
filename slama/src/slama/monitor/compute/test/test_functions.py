"""Unit tests for the built-in compute functions (no engine/config needed)."""
import numpy as np
import pytest

from slama.monitor.compute.computenode import ComputeContext, ResolvedInput
from slama.monitor.compute.functions import (
    _age_s,
    _array_elem,
    _label,
    _severity_score,
    chopper_status,
    clock_offset,
    deice_status,
    dewar_4k_temp,
    drive_status,
    hotload_position,
    line_name,
    lo_lock_ok,
    lo_status,
    rx_label,
    yig_locked,
    on_source,
    timestamp_age,
    count_true,
    count_valid,
    get_function,
    max_value,
    mean_value,
    median_value,
    min_max_value,
    min_value,
    sequence_validity,
    sun_distance_degrees,
    worst_validity,
)
from slama.monitor.monitorpoint import Validity


class FakeClock:
    def __init__(self, start=1000.0):
        self.t = start

    def advance(self, dt):
        self.t += dt

    def __call__(self):
        return self.t


def ri(name, value, validity=Validity.VALID_GOOD):
    return ResolvedInput(name, value, validity)


WALL_NOW = 1_790_000_000.0


def ctx(clock=None, state=None, params=None, wall=None):
    return ComputeContext(
        clock=clock if clock is not None else FakeClock(),
        state=state if state is not None else {},
        params=params if params is not None else {},
        wall_clock=wall if wall is not None else (lambda: WALL_NOW),
    )


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

class TestHelpers:
    def test_age_uses_wall_clock_not_monotonic(self):
        c = ctx(clock=FakeClock(5.0))
        assert _age_s(WALL_NOW - 2, c) == pytest.approx(2.0)

    def test_age_negative_for_future_timestamp(self):
        assert _age_s(WALL_NOW + 5, ctx()) == pytest.approx(-5.0)

    @pytest.mark.parametrize("code, expected", [
        (1, "on"), (1.0, "on"), (np.int16(0), "off"),
        (7, "?"), (-702, "?"), (1.5, "?"), ("x", "?"), (None, "?"),
    ])
    def test_label(self, code, expected):
        assert _label(code, {0: "off", 1: "on"}) == expected

    def test_label_custom_unknown(self):
        assert _label(9, {0: "off"}, unknown="???") == "???"

    def test_array_elem_numpy_returns_python_scalar(self):
        v = _array_elem(np.array([0.5, 4.2, 3.0], dtype=np.float32), 1)
        assert isinstance(v, float) and v == pytest.approx(4.2)

    def test_array_elem_list(self):
        assert _array_elem(["unknown", "CO"], 1) == "CO"

    def test_array_elem_scalar_index_zero(self):
        assert _array_elem(3.5, 0) == 3.5

    def test_array_elem_scalar_nonzero_index_raises(self):
        with pytest.raises(IndexError):
            _array_elem(3.5, 1)

    def test_array_elem_out_of_range_raises(self):
        with pytest.raises(IndexError):
            _array_elem(np.zeros(2), 5)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

class TestRegistry:
    def test_get_function_known(self):
        assert get_function("count_true") is count_true

    def test_get_function_unknown_raises(self):
        with pytest.raises(ValueError, match="unknown compute function"):
            get_function("nope")


# ---------------------------------------------------------------------------
# worst_validity — severity ordering must NOT be plain int max()
# ---------------------------------------------------------------------------

class TestWorstValidity:
    def test_error_beats_good(self):
        inputs = [ri("a", 1, Validity.VALID_GOOD), ri("b", 2, Validity.VALID_ERROR)]
        value, validity = worst_validity(inputs, ctx())
        assert validity == Validity.VALID_ERROR
        assert value == _severity_score(Validity.VALID_ERROR)

    def test_severity_score_increases_with_severity_not_enum_ordinal(self):
        # Regression: Validity's own IntEnum ordinal is declaration
        # order, not severity -- INVALID_NO_DATA has a LOWER ordinal
        # than VALID_GOOD. The score must not just be int(validity).
        good = _severity_score(Validity.VALID_GOOD)
        warning = _severity_score(Validity.VALID_WARNING)
        error = _severity_score(Validity.VALID_ERROR)
        invalid = _severity_score(Validity.INVALID_NO_DATA)
        assert good < warning < error < invalid
        assert good == 0

    def test_invalid_no_data_beats_error(self):
        # INVALID_NO_DATA has a LOWER int value than VALID_ERROR, so a
        # naive max() over Validity members would get this backwards.
        inputs = [ri("a", 1, Validity.VALID_ERROR), ri("b", None, Validity.INVALID_NO_DATA)]
        value, validity = worst_validity(inputs, ctx())
        assert validity == Validity.INVALID_NO_DATA

    def test_all_good_is_good(self):
        inputs = [ri("a", 1, Validity.VALID_GOOD), ri("b", 2, Validity.VALID_GOOD)]
        _, validity = worst_validity(inputs, ctx())
        assert validity == Validity.VALID_GOOD

    def test_warning_beats_good(self):
        inputs = [ri("a", 1, Validity.VALID_GOOD), ri("b", 2, Validity.VALID_WARNING)]
        _, validity = worst_validity(inputs, ctx())
        assert validity == Validity.VALID_WARNING


# ---------------------------------------------------------------------------
# count_true / count_valid
# ---------------------------------------------------------------------------

class TestCounts:
    def test_count_true(self):
        inputs = [ri("a", True), ri("b", False), ri("c", True)]
        assert count_true(inputs, ctx()) == 2

    def test_count_true_single_vector_input(self):
        # Real deployed shape: one input resolving to an array-valued
        # point (e.g. DSM:hal9000:DSM_ONLINE_ANTENNAS_V11_B, size 11)
        # rather than one scalar point per antenna. A bare `if r.value`
        # would raise ValueError on a multi-element numpy array.
        vector = np.array([1, 0, 1, 1, 0, 0, 0, 0, 0, 0, 0], dtype=np.int8)
        inputs = [ri("DSM:hal9000:DSM_ONLINE_ANTENNAS_V11_B", vector)]
        assert count_true(inputs, ctx()) == 3

    def test_count_true_vector_input_with_indices_param(self):
        # V11 vector: index 0 is a placeholder (here truthy, but must
        # be excluded), 1-8 are the standard antennas, 9/10 (JCMT/CSO)
        # are excluded here too since this entry isn't configured for
        # them.
        vector = np.array([1, 1, 0, 1, 1, 0, 0, 0, 0, 1, 1], dtype=np.int8)
        inputs = [ri("DSM:hal9000:DSM_ONLINE_ANTENNAS_V11_B", vector)]
        params = {"indices": [1, 2, 3, 4, 5, 6, 7, 8]}
        assert count_true(inputs, ctx(params=params)) == 3

    def test_count_true_indices_param_ignored_for_scalar_inputs(self):
        # indices only ever selects within an array-valued input --
        # a scalar input (one point per antenna) is counted as-is.
        inputs = [ri("a", True), ri("b", False)]
        params = {"indices": [0]}
        assert count_true(inputs, ctx(params=params)) == 1

    def test_count_valid_excludes_invalid_family(self):
        inputs = [
            ri("a", 1, Validity.VALID_GOOD),
            ri("b", None, Validity.INVALID_NO_DATA),
            ri("c", 2, Validity.VALID_ERROR),  # counted: ERROR is still "valid data"
        ]
        assert count_valid(inputs, ctx()) == 2


# ---------------------------------------------------------------------------
# Numeric aggregates
# ---------------------------------------------------------------------------

class TestAggregates:
    def setup_method(self):
        self.inputs = [ri("a", 1.0), ri("b", 5.0), ri("c", 3.0)]

    def test_min_value(self):
        assert min_value(self.inputs, ctx()) == 1.0

    def test_max_value(self):
        assert max_value(self.inputs, ctx()) == 5.0

    def test_mean_value(self):
        assert mean_value(self.inputs, ctx()) == 3.0

    def test_median_value(self):
        assert median_value(self.inputs, ctx()) == 3.0

    def test_min_max_value_single_pass(self):
        # design doc §8: pairs with a multi-output entry's
        # "output": {"min": ..., "max": ...} -- role keys, not
        # canonical names.
        assert min_max_value(self.inputs, ctx()) == {"min": 1.0, "max": 5.0}


# ---------------------------------------------------------------------------
# sequence_validity — trajectory / stuck-timeout check
# ---------------------------------------------------------------------------

class TestSequenceValidity:
    def test_good_state_passes_through(self):
        inputs = {"state": ri("rx:H:tuning_state", "tuned", Validity.VALID_GOOD)}
        value, validity = sequence_validity(inputs, ctx(params={"stuck_timeout_s": 90}))
        assert value == "tuned"
        assert validity == Validity.VALID_GOOD

    def test_warning_state_within_timeout_stays_warning(self):
        clock = FakeClock()
        state = {}
        params = {"stuck_timeout_s": 90}
        inputs = {"state": ri("rx:H:tuning_state", "locking", Validity.VALID_WARNING)}
        _, validity = sequence_validity(inputs, ctx(clock, state, params))
        clock.advance(30)
        _, validity = sequence_validity(inputs, ctx(clock, state, params))
        assert validity == Validity.VALID_WARNING

    def test_warning_state_past_timeout_escalates_to_error(self):
        clock = FakeClock()
        state = {}
        params = {"stuck_timeout_s": 90}
        inputs = {"state": ri("rx:H:tuning_state", "locking", Validity.VALID_WARNING)}
        sequence_validity(inputs, ctx(clock, state, params))  # first sighting, starts timer
        clock.advance(91)
        _, validity = sequence_validity(inputs, ctx(clock, state, params))
        assert validity == Validity.VALID_ERROR

    def test_new_state_resets_the_timer(self):
        clock = FakeClock()
        state = {}
        params = {"stuck_timeout_s": 90}
        locking = {"state": ri("rx:H:tuning_state", "locking", Validity.VALID_WARNING)}
        setting_lo = {"state": ri("rx:H:tuning_state", "setting_lo", Validity.VALID_WARNING)}

        sequence_validity(locking, ctx(clock, state, params))
        clock.advance(80)  # not yet stuck
        sequence_validity(setting_lo, ctx(clock, state, params))  # transition resets timer
        clock.advance(80)  # would have been stuck on the old state, but timer reset
        _, validity = sequence_validity(setting_lo, ctx(clock, state, params))
        assert validity == Validity.VALID_WARNING

    def test_error_state_is_not_escalated_further(self):
        inputs = {"state": ri("rx:H:tuning_state", "failed", Validity.VALID_ERROR)}
        _, validity = sequence_validity(inputs, ctx(params={"stuck_timeout_s": 90}))
        assert validity == Validity.VALID_ERROR


# ---------------------------------------------------------------------------
# sun_distance -- one antenna per call, paired with a __each__-expanded
# entry per antenna rather than a single 32-in/8-out multi-output entry
# (see docs/monitorsystem_writer_design.md and conf/computations.json).
# ---------------------------------------------------------------------------

class TestSunDistance:
    def test_elevation_only_offset(self):
        inputs = {
            "sunaz": ri("RM:acc1:RM_SUN_AZ_DEG_F", 100.0),
            "sunel": ri("RM:acc1:RM_SUN_EL_DEG_F", 30.0),
            "antaz": ri("RM:acc1:RM_ACTUAL_AZ_DEG_F", 100.0),
            "antel": ri("RM:acc1:RM_ACTUAL_EL_DEG_F", 35.0),
        }
        distance = sun_distance_degrees(inputs, ctx())
        assert distance == pytest.approx(5.0)

    def test_pointing_directly_at_the_sun_is_zero(self):
        inputs = {
            "sunaz": ri("RM:acc1:RM_SUN_AZ_DEG_F", 210.0),
            "sunel": ri("RM:acc1:RM_SUN_EL_DEG_F", 42.0),
            "antaz": ri("RM:acc1:RM_ACTUAL_AZ_DEG_F", 210.0),
            "antel": ri("RM:acc1:RM_ACTUAL_EL_DEG_F", 42.0),
        }
        distance = sun_distance_degrees(inputs, ctx())
        assert distance == pytest.approx(0.0, abs=1e-9)

    def test_returns_plain_float(self):
        # Bare-value return (not a tuple/dict) -- the engine derives
        # validity from the output point's own warn_low/err_low
        # thresholds (design doc §8's single-output path).
        inputs = {
            "sunaz": ri("RM:acc1:RM_SUN_AZ_DEG_F", 0.0),
            "sunel": ri("RM:acc1:RM_SUN_EL_DEG_F", 0.0),
            "antaz": ri("RM:acc1:RM_ACTUAL_AZ_DEG_F", 10.0),
            "antel": ri("RM:acc1:RM_ACTUAL_EL_DEG_F", 0.0),
        }
        distance = sun_distance_degrees(inputs, ctx())
        assert isinstance(distance, float)


# ---------------------------------------------------------------------------
# arrayMonitor.c port: per-antenna tracking / drive
# ---------------------------------------------------------------------------

class TestTimestampAge:
    def test_age(self):
        assert timestamp_age({"ts": ri("RM:acc1:RM_TRACK_TIMESTAMP_L", int(WALL_NOW) - 2)},
                             ctx()) == pytest.approx(2.0)

    def test_garbage_timestamp_is_huge(self):
        assert timestamp_age({"ts": ri("x", -1274676992)}, ctx()) > 1e9


class TestOnSource:
    def _run(self, err, flag):
        return on_source({"tracking_error": ri("e", err), "refraction_flag": ri("f", flag)}, ctx())

    def test_on_source(self):
        assert self._run(0.4, 1) is True

    def test_threshold_is_exclusive(self):
        assert self._run(1.0, 1) is False

    def test_refraction_flag_off_forces_false(self):
        assert self._run(0.1, 0) is False


class TestDriveStatus:
    BASE = dict(drive=1, fault_state=0, faultword=0, servo_ts=WALL_NOW - 1,
                tracking_error=0.2, enc_az=100.0, enc_el=45.0,
                up_limit=87.46, low_limit=14.32, cw_limit=349.72, ccw_limit=-170.72)

    def _run(self, **over):
        vals = dict(self.BASE, **over)
        return drive_status({k: ri(k, v) for k, v in vals.items()}, ctx())

    def test_on(self):
        assert self._run() == "on"

    def test_off(self):
        assert self._run(drive=0, fault_state=3) == "off"

    def test_fault_state_shifts_code(self):
        # f > 0 and d != 0 -> f + 1: f=1 -> "fault", f=3 -> "one mot"
        assert self._run(fault_state=1) == "fault"
        assert self._run(fault_state=3) == "one mot"

    def test_negative_fault_state_is_unknown_not_undefined(self):
        assert self._run(fault_state=-1) == "???"

    def test_el_limit_only_when_off_source(self):
        assert self._run(enc_el=87.5) == "on"
        assert self._run(enc_el=87.5, tracking_error=5.0) == "EL LMT"
        assert self._run(enc_el=14.0, tracking_error=5.0) == "EL LMT"

    def test_az_limit_wins_over_el(self):
        assert self._run(enc_el=87.5, enc_az=350.0, tracking_error=5.0) == "AZ LMT"

    def test_estop_bit_overrides(self):
        assert self._run(faultword=1 << 21, enc_az=350.0, tracking_error=5.0) == "ESTOP"

    def test_azbrake_only_when_off(self):
        assert self._run(drive=0, faultword=1 << 30) == "AZBRAKE"
        assert self._run(drive=1, faultword=1 << 30) == "on"

    def test_negative_int32_faultword_bits_read_unsigned(self):
        # 0x80200000 as a signed int32: ESTOP bit set, sign bit set
        assert self._run(faultword=-2145386496) == "ESTOP"

    def test_stale_servo(self):
        assert self._run(servo_ts=WALL_NOW - 11) == ("stale", Validity.INVALID_NO_DATA)

    def test_garbage_code(self):
        assert self._run(drive=-702, fault_state=0) == "???"


class TestChopperStatus:
    def _bits(self, p20=0, pos_err=0, update=0):
        b = np.zeros(16, dtype=np.int8)
        b[4], b[5], b[10] = p20, pos_err, update
        return b

    def _run(self, bits, age=1.0):
        return chopper_status({"bits": ri("b", bits), "ts": ri("t", WALL_NOW - age)}, ctx())

    def test_ok_focus_curve(self):
        out = self._run(self._bits(update=1))
        assert out == {"status": ("OK/FC", Validity.VALID_GOOD), "focus_curve": True}

    def test_ok_no_focus_curve_is_warning(self):
        assert self._run(self._bits())["status"] == ("OK/NFC", Validity.VALID_WARNING)

    def test_chopping_only_is_good(self):
        assert self._run(self._bits(p20=2))["status"] == ("---C", Validity.VALID_GOOD)

    def test_position_errors(self):
        assert self._run(self._bits(pos_err=15))["status"] == ("XYZT", Validity.VALID_ERROR)
        assert self._run(self._bits(pos_err=4, p20=2))["status"] == ("-Y-C", Validity.VALID_ERROR)

    def test_stale_invalidates_both_roles(self):
        out = self._run(self._bits(update=1), age=5.0)
        assert out["status"] == ("stale", Validity.INVALID_NO_DATA)
        assert out["focus_curve"] == (True, Validity.INVALID_NO_DATA)


class TestDeiceStatus:
    def _run(self, bits, age=10.0):
        return deice_status({"ts": ri("t", WALL_NOW - age), "bits": ri("b", bits)}, ctx())

    def test_ok(self):
        assert self._run(0) == "ok"

    def test_deicing(self):
        assert self._run(0x2000) == "deicing"
        assert self._run(0x4000) == "deicing"

    def test_fault_bit_as_signed_int32(self):
        assert self._run(-2147483648) == "fault"

    def test_stale_is_fault(self):
        assert self._run(0, age=301) == "fault"


class TestClockOffset:
    def _run(self, utc_hr, ts):
        return clock_offset({"utc_hr": ResolvedInput("u", utc_hr, Validity.VALID_GOOD, ts)}, ctx())

    def test_uses_write_timestamp(self):
        # 1790035200 is 2026-09-22T00:00:00Z
        assert self._run(16.5, 1790035200 + 16.5 * 3600 + 0.08) == pytest.approx(0.08)

    def test_antenna_ahead_is_negative(self):
        assert self._run(10.0 + 0.2 / 3600, 1790035200 + 36000) == pytest.approx(-0.2)

    def test_midnight_wrap(self):
        # antenna still at 23:59:59.9, write time just past midnight
        assert self._run(24 - 0.1 / 3600, 1790035200 + 0.05) == pytest.approx(0.15)

    def test_falls_back_to_wall_clock(self):
        wall_hr = (WALL_NOW % 86400) / 3600
        assert self._run(wall_hr, None) == pytest.approx(0.0, abs=1e-6)


class TestSunDistanceTrackGate:
    def _inputs(self, track_age):
        d = {"sunaz": ri("a", 100.0), "sunel": ri("b", 30.0),
             "antaz": ri("c", 100.0), "antel": ri("d", 60.0)}
        if track_age is not None:
            d["track_ts"] = ri("t", WALL_NOW - track_age)
        return d

    def test_fresh_track_returns_bare_value(self):
        assert sun_distance_degrees(self._inputs(1.0), ctx()) == pytest.approx(30.0)

    def test_stale_track_invalidates(self):
        value, validity = sun_distance_degrees(self._inputs(10.0), ctx())
        assert value == pytest.approx(30.0)
        assert validity == Validity.INVALID_NO_DATA

    def test_track_ts_optional(self):
        assert sun_distance_degrees(self._inputs(None), ctx()) == pytest.approx(30.0)


# ---------------------------------------------------------------------------
# arrayMonitor.c port: receiver / LO
# ---------------------------------------------------------------------------

class TestYigLocked:
    def test_locked(self):
        assert yig_locked({"locked": ri("y", 1)}, ctx()) == (True, Validity.VALID_GOOD)

    def test_garbage_is_unlocked(self):
        assert yig_locked({"locked": ri("y", -2113)}, ctx()) == (False, Validity.VALID_WARNING)


class TestLoStatus:
    def _run(self, busy=0, g1=1, y1=1, g2=1, y2=1):
        vals = {"busy": busy, "gunn1": g1, "yig1": y1, "gunn2": g2, "yig2": y2}
        return lo_status({k: ri(k, v) for k, v in vals.items()}, ctx())

    def test_all_locked(self):
        assert self._run() == ("1-1/1-1", Validity.VALID_GOOD)

    def test_tri_state(self):
        assert self._run(g1=0, g2=-18799) == ("0-1/w-1", Validity.VALID_WARNING)

    @pytest.mark.parametrize("busy, label", [(1, "tuningL"), (2, "tuningH"), (3, "LO adjL"), (4, "LO adjH")])
    def test_whole_field_busy(self, busy, label):
        assert self._run(busy=busy) == (label, Validity.VALID_WARNING)

    def test_iv_and_pb_sides(self):
        assert self._run(busy=6)[0] == "IV/1-1"
        assert self._run(busy=7)[0] == "1-1/IV"
        assert self._run(busy=8)[0] == "PB/1-1"
        assert self._run(busy=9)[0] == "1-1/PB"   # C bug: tested 8 twice

    def test_other_known_busy_shows_locks(self):
        assert self._run(busy=12)[0] == "1-1/1-1"

    def test_garbage_busy(self):
        assert self._run(busy=-702) == ("?", Validity.VALID_ERROR)
        assert self._run(busy=30334) == ("?", Validity.VALID_ERROR)


class TestLoLockOk:
    def _run(self, g1=1, g2=1, y1=1, rest=230e9, age=10.0):
        return lo_lock_ok({
            "gunn1": ri("g1", g1), "gunn2": ri("g2", g2), "yig1": ri("y1", y1),
            "gunn1_ts": ri("t", WALL_NOW - age),
            "rest_freq": ri("f", np.array([rest, rest])),
        }, ctx())

    def test_all_locked(self):
        assert self._run() == (True, Validity.VALID_GOOD)

    def test_low_band_needs_gunn1(self):
        assert self._run(g2=0) == (True, Validity.VALID_GOOD)
        assert self._run(g1=0) == (False, Validity.VALID_ERROR)

    def test_high_band_needs_gunn2(self):
        assert self._run(g1=0, rest=690e9) == (True, Validity.VALID_GOOD)
        assert self._run(g2=0, rest=690e9) == (False, Validity.VALID_ERROR)

    def test_yig1_always_required(self):
        assert self._run(y1=0) == (False, Validity.VALID_ERROR)

    def test_stale_heartbeat_is_error_even_if_locked(self):
        assert self._run(age=91) == (True, Validity.VALID_ERROR)


class TestHotloadPosition:
    def _run(self, status, busy=0, board=None):
        d = {"status": ri("s", status), "busy": ri("b", busy)}
        if board is not None:
            d["optics_board"] = ri("o", board)
        return hotload_position(d, ctx())

    @pytest.mark.parametrize("status, label", [(1, "Sky"), (3, "Sky"), (2, "Amb"), (4, "Amb"), (5, "Mov"), (0, "?"), (-17101, "?")])
    def test_labels(self, status, label):
        assert self._run(status) == label

    def test_linear_load_busy(self):
        assert self._run(1, busy=12) == "LinLoad"

    def test_no_optics_board(self):
        assert self._run(1, board=0) == "NoB"
        assert self._run(1, board=1) == "Sky"


class TestRxLabel:
    @pytest.mark.parametrize("code, label", [("A1", "230"), ("E", "240"), ("B1", "345"), ("C", "400"), ("A2", "A"), ("", "A")])
    def test_labels(self, code, label):
        assert rx_label({"code": ri("c", code)}, ctx(params={"default": "A"})) == label


class TestLineName:
    def _run(self, idx, names=("CO2-1", "unknown"), chunks=(1, 3), mrg=(1, 1)):
        return line_name({"names": ri("n", list(names)), "chunks": ri("c", np.array(chunks)),
                          "mrg_locked": ri("m", np.array(mrg))}, ctx(params={"index": idx}))

    def test_name(self):
        assert self._run(0) == ("CO2-1", Validity.VALID_GOOD)

    def test_chunk_fallback(self):
        assert self._run(1) == ("s03", Validity.VALID_GOOD)

    def test_chunk_out_of_range_is_empty(self):
        assert self._run(1, chunks=(1, 9)) == ("", Validity.VALID_GOOD)

    def test_yig_unlocked(self):
        assert self._run(0, mrg=(0, 1)) == ("YIG Unlkd", Validity.VALID_WARNING)

    def test_truncated_to_12(self):
        assert self._run(0, names=("ABCDEFGHIJKLMNOP", "x"))[0] == "ABCDEFGHIJKL"


class TestDewar4kTemp:
    def _tune6(self, temps, age=5.0, sensor=8):
        return dewar_4k_temp({"temps": ri("t", np.array(temps, dtype=np.float32)),
                              "ts": ri("ts", WALL_NOW - age)}, ctx(params={"sensor": sensor}))

    def test_tune6_sensor_index(self):
        temps = [480, 15.0, 0, 67.8, 1, 1, 1, 1, 3.998, 475, 4.037, 1.4, 1.4, 1.4, 1.4, 1.4]
        assert self._tune6(temps) == pytest.approx(3.998, abs=1e-4)

    def test_stale_lakeshore(self):
        t, v = self._tune6([4.0] * 16, age=61)
        assert v == Validity.INVALID_NO_DATA

    def test_wacko_low(self):
        t, v = self._tune6([1.4] * 16)
        assert v == Validity.VALID_ERROR

    def test_wsma_shape(self):
        assert dewar_4k_temp({"temp": ri("w", 4.076)}, ctx()) == pytest.approx(4.076)
