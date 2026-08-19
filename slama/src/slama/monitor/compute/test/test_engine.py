"""Unit tests for ComputeEngine.tick(): input resolution, staleness/invalid
policy, writes, and same-tick DAG ordering (no live SMAX/Valkey required —
see feedback_valkey_test_heads_up)."""
from datetime import datetime, timezone

import pytest

from slama.monitor.compute.computeconfig import ComputeConfig
from slama.monitor.compute.engine import ComputeEngine, _wrap
from slama.monitor.compute.functions import compute_function
from slama.monitor.monitorpoint import MonitorPoint, Validity


@compute_function("_test_bad_multi_output")
def _test_bad_multi_output(inputs, ctx):
    """Test-only function returning the wrong key set (design doc §8.2)."""
    return {"only_one_key": 1.0}


@compute_function("_test_always_raises")
def _test_always_raises(inputs, ctx):
    """Test-only function that always raises, for §8.3 error-isolation tests."""
    raise RuntimeError("boom")


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

class FakeClock:
    def __init__(self, start=1000.0):
        self.t = start

    def advance(self, dt):
        self.t += dt

    def __call__(self):
        return self.t


class FakeMonitorSystem:
    """Wraps real MonitorPoint objects (for real validity/threshold
    behavior) keyed by canonical name, without needing smax.json or a
    SmaxRedisClient."""

    def __init__(self, mps):
        self._mps = {mp.canonical_name: mp for mp in mps}

    def get_monitor_point(self, name):
        if name not in self._mps:
            raise KeyError(name)
        return self._mps[name]

    def all_monitor_points(self):
        return list(self._mps.values())

    def read_all(self, client):
        pass  # tests set values directly on the fake MonitorPoint objects


class FakeSmaxClient:
    """Records smax_share/smax_push_meta calls instead of touching Redis."""

    def __init__(self):
        self.shared: list[tuple[str, str, object]] = []
        self.meta: list[tuple[str, str, str]] = []

    def smax_share(self, table, key, value):
        self.shared.append((table, key, value))

    def smax_push_meta(self, meta, table, value):
        self.meta.append((meta, table, value))


def make_mp(canonical_name, **kwargs):
    return MonitorPoint(name=canonical_name.rsplit(":", 1)[-1],
                         canonical_name=canonical_name, **kwargs)


def set_value(mp, value, ts=None):
    mp.update(_FakeSmaxResult(value, ts or datetime.now(timezone.utc)))


class _FakeSmaxResult:
    """A plain value plus .timestamp, matching what MonitorPoint.update expects."""

    def __init__(self, value, timestamp):
        self._value = value
        self.timestamp = timestamp

    def __eq__(self, other):
        return self._value == other

    def __bool__(self):
        return bool(self._value)

    def __float__(self):
        return float(self._value)

    def __ge__(self, other):
        return self._value >= other

    def __le__(self, other):
        return self._value <= other

    def __repr__(self):
        return repr(self._value)


# ---------------------------------------------------------------------------
# _wrap() must produce something MonitorPoint.time can read back
# ---------------------------------------------------------------------------

class TestWrap:
    def test_wrapped_value_has_a_readable_time(self):
        # Regression: _wrap used to pass the float wall-clock straight
        # through as `timestamp`, but SmaxVarBase.timestamp is typed
        # datetime | None and MonitorPoint.time does
        # Time(self._smax_result.timestamp) -- astropy.time.Time
        # rejects a bare float, so any later staleness check
        # (mp.time.unix) on an engine-computed value would raise and
        # get silently swallowed into a permanent INVALID_NO_DATA.
        mp = make_mp("monitorsystem:array:antennas_online", smax_type="integer")
        mp.update(_wrap(5, 1_700_000_000.0))
        assert mp.value == 5
        assert mp.time is not None
        assert mp.time.unix == pytest.approx(1_700_000_000.0)


# ---------------------------------------------------------------------------
# Basic tick: resolve, compute, write
# ---------------------------------------------------------------------------

class TestBasicTick:
    def test_count_true_writes_value_and_validity(self):
        ants = [make_mp(f"antenna:{i}:is_online", smax_type="boolean") for i in (1, 2, 3)]
        for i, mp in zip((1, 2, 3), ants):
            set_value(mp, i != 2)  # antenna 2 offline

        out = make_mp("monitorsystem:array:antennas_online", smax_type="integer")
        ms = FakeMonitorSystem(ants + [out])
        cfg = ComputeConfig.from_dict({
            "computations": [{
                "output": "monitorsystem:array:antennas_online",
                "function": "count_true",
                "inputs": ["antenna:1-3:is_online"],
            }],
        }, ms)
        client = FakeSmaxClient()
        engine = ComputeEngine(cfg, ms, client=client, wall_clock=lambda: 1_700_000_000.0)

        results = engine.tick()

        assert results[0].value == 2
        assert results[0].validity == Validity.VALID_GOOD  # no thresholds on `out` -> always GOOD
        assert client.shared == [("monitorsystem:array", "antennas_online", 2)]
        assert client.meta == [("validity", "monitorsystem:array:antennas_online",
                                 str(int(results[0].validity)))]
        # the tree's own MonitorPoint was updated in place too
        assert out.value == 2

    def test_no_client_still_computes_but_does_not_write(self):
        ants = [make_mp(f"antenna:{i}:is_online", smax_type="boolean") for i in (1, 2)]
        for mp in ants:
            set_value(mp, True)
        out = make_mp("monitorsystem:array:antennas_online", smax_type="integer")
        ms = FakeMonitorSystem(ants + [out])
        cfg = ComputeConfig.from_dict({
            "computations": [{
                "output": "monitorsystem:array:antennas_online",
                "function": "count_true",
                "inputs": ["antenna:1-2:is_online"],
            }],
        }, ms)
        engine = ComputeEngine(cfg, ms, client=None, wall_clock=lambda: 1_700_000_000.0)

        results = engine.tick()
        assert results[0].value == 2
        assert out.value == 2  # in-memory tree still updated


# ---------------------------------------------------------------------------
# Staleness / missing-input policy
# ---------------------------------------------------------------------------

class TestStalenessPolicy:
    def _setup(self, invalid_inputs="skip", staleness_s=30):
        a = make_mp("antenna:1:is_online", smax_type="boolean")
        b = make_mp("antenna:2:is_online", smax_type="boolean")
        set_value(a, True, ts=datetime.fromtimestamp(1_700_000_000 - 1000, tz=timezone.utc))
        set_value(b, True, ts=datetime.fromtimestamp(1_700_000_000, tz=timezone.utc))
        out = make_mp("monitorsystem:array:antennas_online", smax_type="integer")
        ms = FakeMonitorSystem([a, b, out])
        cfg = ComputeConfig.from_dict({
            "defaults": {"staleness_s": staleness_s, "invalid_inputs": invalid_inputs},
            "computations": [{
                "output": "monitorsystem:array:antennas_online",
                "function": "count_true",
                "inputs": ["antenna:1-2:is_online"],
            }],
        }, ms)
        client = FakeSmaxClient()
        engine = ComputeEngine(cfg, ms, client=client, wall_clock=lambda: 1_700_000_000.0)
        return engine, client

    def test_stale_input_skipped_under_skip_policy(self):
        # antenna 1's reading is 1000s old, staleness_s=30 -> excluded;
        # antenna 2 is fresh -> counted. Result: 1, not 2.
        engine, client = self._setup(invalid_inputs="skip", staleness_s=30)
        results = engine.tick()
        assert results[0].value == 1

    def test_stale_input_propagates_invalid_no_data(self):
        engine, client = self._setup(invalid_inputs="propagate", staleness_s=30)
        results = engine.tick()
        assert results[0].value is None
        assert results[0].validity == Validity.INVALID_NO_DATA
        # no value written, but validity metadata still pushed
        assert client.shared == []
        assert client.meta == [("validity", "monitorsystem:array:antennas_online",
                                 str(int(Validity.INVALID_NO_DATA)))]

    def test_all_inputs_missing_short_circuits_even_under_skip(self):
        a = make_mp("antenna:1:is_online", smax_type="boolean")
        b = make_mp("antenna:2:is_online", smax_type="boolean")
        old_ts = datetime.fromtimestamp(1_700_000_000 - 1000, tz=timezone.utc)
        set_value(a, True, ts=old_ts)
        set_value(b, True, ts=old_ts)
        out = make_mp("monitorsystem:array:antennas_online", smax_type="integer")
        ms = FakeMonitorSystem([a, b, out])
        cfg = ComputeConfig.from_dict({
            "defaults": {"staleness_s": 30, "invalid_inputs": "skip"},
            "computations": [{
                "output": "monitorsystem:array:antennas_online",
                "function": "count_true",
                "inputs": ["antenna:1-2:is_online"],
            }],
        }, ms)
        engine = ComputeEngine(cfg, ms, client=None, wall_clock=lambda: 1_700_000_000.0)
        results = engine.tick()  # both readings are 1000s old, staleness_s=30
        assert results[0].value is None
        assert results[0].validity == Validity.INVALID_NO_DATA


class TestDictInputRequiredPolicy:
    def test_missing_named_input_short_circuits_regardless_of_policy(self):
        state_mp = make_mp("rx:H:tuning_state", smax_type="string")
        # never updated -> value is None -> INVALID_NO_DATA
        out = make_mp("monitorsystem:rx:H:tuning_status", smax_type="string")
        ms = FakeMonitorSystem([state_mp, out])
        cfg = ComputeConfig.from_dict({
            "computations": [{
                "output": "monitorsystem:rx:H:tuning_status",
                "function": "sequence_validity",
                "inputs": {"state": "rx:H:tuning_state"},
                "params": {"stuck_timeout_s": 90},
                "invalid_inputs": "skip",  # irrelevant for dict-form inputs
            }],
        }, ms)
        engine = ComputeEngine(cfg, ms, client=None, wall_clock=lambda: 1_700_000_000.0)
        results = engine.tick()
        assert results[0].validity == Validity.INVALID_NO_DATA


# ---------------------------------------------------------------------------
# Same-tick DAG ordering
# ---------------------------------------------------------------------------

class TestSameTickOrdering:
    def test_downstream_node_sees_this_ticks_upstream_result(self):
        ants = [make_mp(f"antenna:{i}:is_online", smax_type="boolean") for i in (1, 2)]
        for mp in ants:
            set_value(mp, True)
        online = make_mp(
            "monitorsystem:array:antennas_online", smax_type="integer",
            err_low=1,  # <=1 online -> VALID_ERROR_LOW
        )
        # A downstream node that just echoes the worst validity of the
        # already-computed antennas_online point.
        status = make_mp("monitorsystem:array:status", smax_type="integer")
        ms = FakeMonitorSystem(ants + [online, status])
        cfg = ComputeConfig.from_dict({
            "computations": [
                {
                    "output": "monitorsystem:array:antennas_online",
                    "function": "count_true",
                    "inputs": ["antenna:1-2:is_online"],
                },
                {
                    "output": "monitorsystem:array:status",
                    "function": "worst_validity",
                    "inputs": ["monitorsystem:array:antennas_online"],
                },
            ],
        }, ms)
        client = FakeSmaxClient()
        engine = ComputeEngine(cfg, ms, client=client, wall_clock=lambda: 1_700_000_000.0)

        results = engine.tick()
        by_output = {r.canonical_name: r for r in results}

        # antennas_online = 2 (both online), which is VALID_GOOD against
        # err_low=1 -> the downstream worst_validity must see VALID_GOOD
        # from *this tick*, not some stale/absent prior value.
        assert by_output["monitorsystem:array:antennas_online"].value == 2
        assert by_output["monitorsystem:array:status"].validity == Validity.VALID_GOOD

        # Now flip both antennas offline and re-tick: downstream must
        # track the change within the same tick it happens.
        for mp in ants:
            set_value(mp, False)
        results = engine.tick()
        by_output = {r.canonical_name: r for r in results}
        assert by_output["monitorsystem:array:antennas_online"].value == 0
        assert by_output["monitorsystem:array:status"].validity == Validity.VALID_ERROR_LOW


# ---------------------------------------------------------------------------
# Multi-output entries (design doc §8)
# ---------------------------------------------------------------------------

class TestMultiOutputTick:
    def test_min_max_value_writes_both_canonical_names(self):
        stations = [make_mp(f"weather:station:{i}:temperature", smax_type="float") for i in (1, 2)]
        for i, mp in zip((1, 2), stations):
            set_value(mp, float(i * 10))  # 10.0, 20.0
        tmin = make_mp("monitorsystem:weather:temp_min", smax_type="float")
        tmax = make_mp("monitorsystem:weather:temp_max", smax_type="float")
        ms = FakeMonitorSystem(stations + [tmin, tmax])
        cfg = ComputeConfig.from_dict({
            "computations": [{
                "output": {
                    "min": "monitorsystem:weather:temp_min",
                    "max": "monitorsystem:weather:temp_max",
                },
                "function": "min_max_value",
                "inputs": ["weather:station:1-2:temperature"],
            }],
        }, ms)
        client = FakeSmaxClient()
        engine = ComputeEngine(cfg, ms, client=client, wall_clock=lambda: 1_700_000_000.0)

        results = engine.tick()
        by_name = {r.canonical_name: r for r in results}

        assert by_name["monitorsystem:weather:temp_min"].value == 10.0
        assert by_name["monitorsystem:weather:temp_max"].value == 20.0
        assert set(client.shared) == {
            ("monitorsystem:weather", "temp_min", 10.0),
            ("monitorsystem:weather", "temp_max", 20.0),
        }
        assert tmin.value == 10.0 and tmax.value == 20.0  # tree updated in place too

    def test_short_circuited_input_marks_every_role_invalid(self):
        # station never updated -> value is None -> resolution short-circuits
        # -> every declared role must come back INVALID_NO_DATA, not just one.
        station = make_mp("weather:station:1:temperature", smax_type="float")
        tmin = make_mp("monitorsystem:weather:temp_min", smax_type="float")
        tmax = make_mp("monitorsystem:weather:temp_max", smax_type="float")
        ms = FakeMonitorSystem([station, tmin, tmax])
        cfg = ComputeConfig.from_dict({
            "computations": [{
                "output": {
                    "min": "monitorsystem:weather:temp_min",
                    "max": "monitorsystem:weather:temp_max",
                },
                "function": "min_max_value",
                "inputs": ["weather:station:1:temperature"],
                "invalid_inputs": "propagate",
            }],
        }, ms)
        engine = ComputeEngine(cfg, ms, client=None, wall_clock=lambda: 1_700_000_000.0)

        results = engine.tick()
        assert {r.canonical_name for r in results} == {
            "monitorsystem:weather:temp_min", "monitorsystem:weather:temp_max",
        }
        assert all(r.value is None and r.validity == Validity.INVALID_NO_DATA for r in results)

    def test_key_mismatch_isolates_only_that_node(self):
        station = make_mp("weather:station:1:temperature", smax_type="float")
        set_value(station, 5.0)
        tmin = make_mp("monitorsystem:weather:temp_min", smax_type="float")
        tmax = make_mp("monitorsystem:weather:temp_max", smax_type="float")
        ants = [make_mp(f"antenna:{i}:is_online", smax_type="boolean") for i in (1, 2)]
        for mp in ants:
            set_value(mp, True)
        out = make_mp("monitorsystem:array:antennas_online", smax_type="integer")
        ms = FakeMonitorSystem([station, tmin, tmax] + ants + [out])
        cfg = ComputeConfig.from_dict({
            "computations": [
                {
                    "output": {
                        "min": "monitorsystem:weather:temp_min",
                        "max": "monitorsystem:weather:temp_max",
                    },
                    "function": "_test_bad_multi_output",  # returns wrong keys
                    "inputs": ["weather:station:1:temperature"],
                },
                {
                    "output": "monitorsystem:array:antennas_online",
                    "function": "count_true",
                    "inputs": ["antenna:1-2:is_online"],
                },
            ],
        }, ms)
        engine = ComputeEngine(cfg, ms, client=None, wall_clock=lambda: 1_700_000_000.0)

        results = engine.tick()
        by_name = {r.canonical_name: r for r in results}

        assert by_name["monitorsystem:weather:temp_min"].validity == Validity.INVALID_NO_DATA
        assert by_name["monitorsystem:weather:temp_max"].validity == Validity.INVALID_NO_DATA
        # the unrelated node still ran fine -- one node's error didn't
        # abort the tick for the rest of the DAG (design doc §8.3).
        assert by_name["monitorsystem:array:antennas_online"].value == 2


# ---------------------------------------------------------------------------
# Per-node error isolation, single-output case (design doc §8.3 --
# applies to every node, not just multi-output ones)
# ---------------------------------------------------------------------------

class TestErrorIsolation:
    def test_raising_function_isolates_only_that_node(self):
        ants = [make_mp(f"antenna:{i}:is_online", smax_type="boolean") for i in (1, 2)]
        for mp in ants:
            set_value(mp, True)
        broken = make_mp("monitorsystem:weather:temp_min", smax_type="float")
        station = make_mp("weather:station:1:temperature", smax_type="float")
        set_value(station, 5.0)
        out = make_mp("monitorsystem:array:antennas_online", smax_type="integer")
        ms = FakeMonitorSystem(ants + [broken, station, out])
        cfg = ComputeConfig.from_dict({
            "computations": [
                {
                    "output": "monitorsystem:weather:temp_min",
                    "function": "_test_always_raises",
                    "inputs": ["weather:station:1:temperature"],
                },
                {
                    "output": "monitorsystem:array:antennas_online",
                    "function": "count_true",
                    "inputs": ["antenna:1-2:is_online"],
                },
            ],
        }, ms)
        client = FakeSmaxClient()
        engine = ComputeEngine(cfg, ms, client=client, wall_clock=lambda: 1_700_000_000.0)

        results = engine.tick()
        by_name = {r.canonical_name: r for r in results}

        assert by_name["monitorsystem:weather:temp_min"].value is None
        assert by_name["monitorsystem:weather:temp_min"].validity == Validity.INVALID_NO_DATA
        assert by_name["monitorsystem:array:antennas_online"].value == 2
        # no value written for the broken node, but validity metadata still is
        assert ("monitorsystem:weather", "temp_min", 5.0) not in client.shared
        assert ("validity", "monitorsystem:weather:temp_min",
                str(int(Validity.INVALID_NO_DATA))) in client.meta
