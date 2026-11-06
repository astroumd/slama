"""Unit tests for FaultSystem: verdict, DAG walking, debounce, ignore, dedup."""
from datetime import datetime, timezone

import pytest

from slama.fault.faultconfig import HEARTBEAT_NAME, FaultConfig
from slama.fault.faultnode import FaultEvent
from slama.fault.faultsystem import FaultSystem
from slama.monitor.monitorpoint import Validity


# ---------------------------------------------------------------------------
# Fakes — avoid needing a real SmaxRedisClient or MonitorSystem.
# ---------------------------------------------------------------------------

PREFIX = "monitorsystem:test:"
WALL_NOW = 1_700_000_000.0


def n(short):
    """Canonical name for a short test node name (fault nodes must be monitorsystem:*)."""
    return PREFIX + short


def short(names):
    """Strip :data:`PREFIX` from canonical names, for readable assertions."""
    return [x[len(PREFIX):] if x.startswith(PREFIX) else x for x in names]


class FakeResult(float):
    """Stand-in for an ``SmaxFloat``: a value with a ``.timestamp`` datetime."""

    def __new__(cls, value, epoch):
        obj = super().__new__(cls, value)
        obj.timestamp = datetime.fromtimestamp(epoch, tz=timezone.utc)
        return obj


class FakeMP:
    """A computed point: its value (with timestamp) and its pushed validity."""

    def __init__(self, canonical_name, validity=Validity.VALID_GOOD,
                 value=1.0, written_at=WALL_NOW, present=True):
        self.canonical_name = canonical_name
        self.pushed = validity
        self._value = value
        self.written_at = written_at
        self.present = present

    @property
    def value(self):
        if not self.present:
            return None
        return FakeResult(self._value, self.written_at)

    def set_validity(self, v):
        self.pushed = v


class FakeMonitorSystem:
    """Stand-in MonitorSystem that records which names each tick reads."""

    def __init__(self, mps):
        self._mps = {mp.canonical_name: mp for mp in mps}
        self.reads = []

    def get_monitor_point(self, name):
        if name not in self._mps:
            raise KeyError(name)
        return self._mps[name]

    def read(self, canonical_names, client):
        self.reads.append(tuple(canonical_names))

    def read_all(self, client):
        # The fault loop must read only its watched points (#55).
        raise AssertionError("FaultSystem must not call read_all")


class FakeClient:
    """Serves each FakeMP's pushed validity as ``validity`` metadata."""

    def __init__(self, ms):
        self.ms = ms
        self.meta_pulls = []
        self.shares = []

    def smax_share(self, table, key, value):
        self.shares.append((f"{table}:{key}", value))

    def smax_pull_meta(self, meta, name):
        self.meta_pulls.append((meta, name))
        mp = self.ms._mps.get(name)
        if mp is None or not mp.present or mp.pushed is None:
            return None
        return str(int(mp.pushed))


class FakeClock:
    def __init__(self, start=1000.0):
        self.t = start

    def advance(self, dt):
        self.t += dt

    def __call__(self):
        return self.t


class RecordingAction:
    def __init__(self):
        self.events = []

    def fire(self, event: FaultEvent):
        self.events.append(event)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

NODE_KEYS = ("transient_filter_s", "no_data_filter_s", "computed_max_age_s",
             "onset_s")


def _build_system(nodes, mps, action_map=None, clock=None, wall_clock=None,
                  tmp_path=None, client=True, defaults=None, heartbeat=None):
    """Build a FaultSystem from node dicts with short names, bypassing JSON.

    Short names are prefixed with :data:`PREFIX`. A GOOD heartbeat node and
    point are added unless the test supplies its own (``heartbeat`` = a
    FakeMP for :data:`HEARTBEAT_NAME`). Defaults are all-zero filters and
    ``computed_max_age_s`` 0 (points are written at the wall clock), so the
    old single-filter tests keep their meaning. ``client=False`` builds
    without a client.
    """
    action_map = action_map or {"rec": RecordingAction()}
    placeholder = "/tmp/slama-fault-test.log"
    raw_actions = {k: {"type": "log_file", "path": placeholder}
                   for k in action_map}
    # onset_s 0 keeps the heartbeat's detection time at its filter, so the
    # parent-lag check does not force every test to set long filters.
    raw_faults = [{"canonical_name": HEARTBEAT_NAME, "onset_s": 0,
                   "actions": list(action_map.keys())}]
    for node in nodes:
        entry = {"canonical_name": n(node["canonical_name"]),
                 "parents": [n(p) for p in node.get("parents", [])],
                 "context": [n(c) for c in node.get("context", [])],
                 "actions": list(action_map.keys())}
        entry.update({k: node[k] for k in NODE_KEYS if k in node})
        raw_faults.append(entry)
    raw = {
        "defaults": {"transient_filter_s": 0, "no_data_filter_s": 0,
                     "computed_max_age_s": 0, "interval_s": 1,
                     **(defaults or {})},
        "actions": raw_actions,
        "faults": raw_faults,
    }
    cfg = FaultConfig.from_dict(raw)
    cfg.actions = dict(action_map)

    for mp in mps:
        if not mp.canonical_name.startswith("monitorsystem:"):
            mp.canonical_name = n(mp.canonical_name)
    hb = heartbeat or FakeMP(HEARTBEAT_NAME)
    ms = FakeMonitorSystem([hb, *mps])
    system = FaultSystem(
        cfg, ms, client=FakeClient(ms) if client else None,
        clock=clock or FakeClock(),
        wall_clock=wall_clock or (lambda: WALL_NOW),
    )
    return system


def names(events):
    return short(e.canonical_name for e in events)


# ---------------------------------------------------------------------------
# Root-fault detection
# ---------------------------------------------------------------------------

class TestRootFault:
    def test_single_faulted_node_is_root(self):
        mp = FakeMP("a", Validity.VALID_ERROR)
        rec = RecordingAction()
        system = _build_system(
            [{"canonical_name": "a"}], [mp], {"rec": rec},
        )
        events = system.tick()
        assert names(events) == ["a"]

    def test_chain_only_upstream_root_fires(self):
        # A -> B -> C (A is upstream). All three faulted => only A is root.
        mps = [
            FakeMP("a", Validity.VALID_ERROR),
            FakeMP("b", Validity.VALID_ERROR),
            FakeMP("c", Validity.VALID_ERROR),
        ]
        rec = RecordingAction()
        system = _build_system(
            [
                {"canonical_name": "a"},
                {"canonical_name": "b", "parents": ["a"]},
                {"canonical_name": "c", "parents": ["b"]},
            ],
            mps, {"rec": rec},
        )
        events = system.tick()
        assert names(events) == ["a"]

    def test_root_flips_when_upstream_recovers(self):
        a = FakeMP("a", Validity.VALID_ERROR)
        b = FakeMP("b", Validity.VALID_ERROR)
        rec = RecordingAction()
        system = _build_system(
            [{"canonical_name": "a"}, {"canonical_name": "b", "parents": ["a"]}],
            [a, b], {"rec": rec},
        )
        system.tick()  # fires for a
        a.set_validity(Validity.VALID_GOOD)
        events = system.tick()
        assert names(events) == ["b"]

    def test_non_fault_validities_do_not_trigger(self):
        mps = [
            FakeMP("warn", Validity.VALID_WARNING_HIGH),
            FakeMP("good", Validity.VALID_GOOD),
            FakeMP("nc", Validity.VALID_NOT_CHECKED),
        ]
        system = _build_system(
            [{"canonical_name": m.canonical_name} for m in mps], mps,
        )
        events = system.tick()
        assert events == []


# ---------------------------------------------------------------------------
# Debounce (transient_filter_s)
# ---------------------------------------------------------------------------

class TestDebounce:
    def test_fault_suppressed_until_filter_elapses(self):
        mp = FakeMP("a", Validity.VALID_ERROR)
        clock = FakeClock()
        rec = RecordingAction()
        system = _build_system(
            [{"canonical_name": "a", "transient_filter_s": 10}],
            [mp], {"rec": rec}, clock=clock,
        )

        assert system.tick() == []       # first-seen, starts timer
        clock.advance(5)
        assert system.tick() == []       # still within window
        clock.advance(6)                 # now > 10s since first fault
        events = system.tick()
        assert names(events) == ["a"]

    def test_brief_blip_does_not_fire(self):
        mp = FakeMP("a", Validity.VALID_ERROR)
        clock = FakeClock()
        system = _build_system(
            [{"canonical_name": "a", "transient_filter_s": 10}],
            [mp], clock=clock,
        )
        system.tick()
        clock.advance(2)
        mp.set_validity(Validity.VALID_GOOD)
        clock.advance(1)
        assert system.tick() == []        # recovered before window elapsed
        # Subsequent fault should restart the timer, not inherit the old one.
        mp.set_validity(Validity.VALID_ERROR)
        clock.advance(3)
        assert system.tick() == []        # timer just restarted


# ---------------------------------------------------------------------------
# Dedup across ticks
# ---------------------------------------------------------------------------

class TestDedup:
    def test_same_validity_does_not_re_fire(self):
        mp = FakeMP("a", Validity.VALID_ERROR)
        rec = RecordingAction()
        system = _build_system(
            [{"canonical_name": "a"}], [mp], {"rec": rec},
        )
        system.tick()
        system.tick()
        system.tick()
        assert len(rec.events) == 1

    def test_validity_change_refires(self):
        mp = FakeMP("a", Validity.VALID_ERROR_HIGH)
        rec = RecordingAction()
        system = _build_system(
            [{"canonical_name": "a"}], [mp], {"rec": rec},
        )
        system.tick()
        mp.set_validity(Validity.INVALID_HW_BAD)
        system.tick()
        assert len(rec.events) == 2
        assert rec.events[0].validity == Validity.VALID_ERROR_HIGH
        assert rec.events[1].validity == Validity.INVALID_HW_BAD

    def test_clear_then_refault_fires_again(self):
        mp = FakeMP("a", Validity.VALID_ERROR)
        rec = RecordingAction()
        system = _build_system(
            [{"canonical_name": "a"}], [mp], {"rec": rec},
        )
        system.tick()
        mp.set_validity(Validity.VALID_GOOD)
        system.tick()
        mp.set_validity(Validity.VALID_ERROR)
        system.tick()
        assert len(rec.events) == 2


# ---------------------------------------------------------------------------
# Ignore API
# ---------------------------------------------------------------------------

class TestIgnore:
    def test_pattern_suppresses_matching_events(self):
        a = FakeMP("antenna:1:heater", Validity.VALID_ERROR)
        b = FakeMP("antenna:2:heater", Validity.VALID_ERROR)
        rec = RecordingAction()
        system = _build_system(
            [
                {"canonical_name": "antenna:1:heater"},
                {"canonical_name": "antenna:2:heater"},
            ],
            [a, b], {"rec": rec},
        )
        system.ignore(n("antenna:1:*"))
        events = system.tick()
        assert names(events) == ["antenna:2:heater"]

    def test_ttl_expires(self):
        mp = FakeMP("a", Validity.VALID_ERROR)
        clock = FakeClock()
        rec = RecordingAction()
        system = _build_system(
            [{"canonical_name": "a"}], [mp], {"rec": rec}, clock=clock,
        )
        system.ignore(n("a"), seconds=5)
        assert system.tick() == []
        clock.advance(10)
        events = system.tick()
        assert names(events) == ["a"]

    def test_seconds_zero_means_indefinite(self):
        mp = FakeMP("a", Validity.VALID_ERROR)
        clock = FakeClock()
        rec = RecordingAction()
        system = _build_system(
            [{"canonical_name": "a"}], [mp], {"rec": rec}, clock=clock,
        )
        system.ignore(n("a"), seconds=0)
        clock.advance(10_000_000)
        assert system.tick() == []

    def test_unignore_clears_pattern(self):
        mp = FakeMP("a", Validity.VALID_ERROR)
        rec = RecordingAction()
        system = _build_system(
            [{"canonical_name": "a"}], [mp], {"rec": rec},
        )
        system.ignore(n("a"))
        assert system.tick() == []
        system.unignore(n("a"))
        events = system.tick()
        assert names(events) == ["a"]

    def test_ignore_does_not_affect_root_detection(self):
        # A is root and ignored; B depends on A. Since A is physically
        # faulted, B is NOT a root — it's still downstream.
        a = FakeMP("a", Validity.VALID_ERROR)
        b = FakeMP("b", Validity.VALID_ERROR)
        rec = RecordingAction()
        system = _build_system(
            [
                {"canonical_name": "a"},
                {"canonical_name": "b", "parents": ["a"]},
            ],
            [a, b], {"rec": rec},
        )
        system.ignore(n("a"))
        assert system.tick() == []       # A suppressed; B is downstream


# ---------------------------------------------------------------------------
# set_interval
# ---------------------------------------------------------------------------

class TestSetInterval:
    def test_updates_interval(self):
        system = _build_system(
            [{"canonical_name": "a"}], [FakeMP("a")],
        )
        system.set_interval(12.5)
        assert system.interval_s == 12.5

    def test_rejects_non_positive(self):
        system = _build_system(
            [{"canonical_name": "a"}], [FakeMP("a")],
        )
        with pytest.raises(ValueError):
            system.set_interval(0)
        with pytest.raises(ValueError):
            system.set_interval(-1)


# ---------------------------------------------------------------------------
# reload_config preserves ignores
# ---------------------------------------------------------------------------

def _file_config(tmp_path, short_names):
    """Write a minimal valid faults.json (heartbeat + the given nodes)."""
    import json
    cfg = {
        "defaults": {"transient_filter_s": 0, "no_data_filter_s": 0,
                     "computed_max_age_s": 0, "interval_s": 1},
        "actions": {
            "log": {"type": "log_file", "path": str(tmp_path / "f.log")},
        },
        "faults": [{"canonical_name": HEARTBEAT_NAME, "actions": ["log"]}]
        + [{"canonical_name": n(s), "actions": ["log"]} for s in short_names],
    }
    path = tmp_path / "faults.json"
    path.write_text(json.dumps(cfg))
    return path


class TestReloadConfig:
    def test_reload_keeps_ignores(self, tmp_path):
        mp = FakeMP("a", Validity.VALID_ERROR)
        rec = RecordingAction()
        system = _build_system(
            [{"canonical_name": "a"}], [mp], {"rec": rec},
        )
        system.ignore(n("a"))
        system.reload_config(_file_config(tmp_path, ["a", "b"]))

        # "a" still ignored; the original RecordingAction is replaced by
        # the new LogFileAction, so we just check the tick returns no event
        # for 'a' because of the still-active ignore.
        events = system.tick()
        assert "a" not in names(events)


# ---------------------------------------------------------------------------
# Watched-point reads (#55)
# ---------------------------------------------------------------------------

class TestWatchedRead:
    def test_tick_reads_only_node_names(self):
        mps = [FakeMP("a"), FakeMP("b"), FakeMP("unwatched")]
        system = _build_system(
            [{"canonical_name": "a"}, {"canonical_name": "b"}], mps,
        )
        system.tick()
        assert system._monitor_system.reads == [(HEARTBEAT_NAME, n("a"), n("b"))]
        assert system.watched_names == (HEARTBEAT_NAME, n("a"), n("b"))

    def test_context_points_are_watched_once(self):
        mps = [FakeMP("a"), FakeMP("b"), FakeMP("ctx")]
        system = _build_system(
            [{"canonical_name": "a", "context": ["ctx"]},
             {"canonical_name": "b", "context": ["ctx"]}], mps,
        )
        assert system.watched_names == (HEARTBEAT_NAME, n("a"), n("b"), n("ctx"))

    def test_meta_pulled_for_nodes_not_context(self):
        mps = [FakeMP("a"), FakeMP("ctx")]
        system = _build_system(
            [{"canonical_name": "a", "context": ["ctx"]}], mps,
        )
        system.tick()
        pulled = [name for _, name in system._client.meta_pulls]
        assert pulled == [HEARTBEAT_NAME, n("a")]

    def test_no_client_means_no_read_and_no_data(self):
        system = _build_system([{"canonical_name": "a"}], [FakeMP("a")],
                               client=False)
        events = system.tick()
        assert system._monitor_system.reads == []
        # Without a client nothing can be verified: every node is NO_DATA,
        # and the heartbeat (their parent) is the one root.
        assert [(e.canonical_name, e.validity) for e in events] == [
            (HEARTBEAT_NAME, Validity.INVALID_NO_DATA)]

    def test_reload_changes_watched_set(self, tmp_path):
        mps = [FakeMP("a"), FakeMP("b")]
        system = _build_system([{"canonical_name": "a"}], mps)
        system.reload_config(_file_config(tmp_path, ["b"]))
        system.tick()
        assert system.watched_names == (HEARTBEAT_NAME, n("b"))
        assert system._monitor_system.reads == [(HEARTBEAT_NAME, n("b"))]

    def test_unknown_node_warns_once_at_load(self, caplog):
        with caplog.at_level("WARNING", logger="slama.fault.faultsystem"):
            system = _build_system(
                [{"canonical_name": "a"}, {"canonical_name": "typo"}],
                [FakeMP("a")],
            )
        warnings = [r for r in caplog.records if r.levelname == "WARNING"]
        assert len(warnings) == 1
        assert "typo" in warnings[0].getMessage()
        assert n("a") + "," not in warnings[0].getMessage()
        # The unknown node reads as NO_DATA.
        events = system.tick()
        assert [(e.canonical_name, e.validity) for e in events] == [
            (n("typo"), Validity.INVALID_NO_DATA)]

    def test_all_known_nodes_no_warning(self, caplog):
        with caplog.at_level("WARNING", logger="slama.fault.faultsystem"):
            _build_system([{"canonical_name": "a"}], [FakeMP("a")])
        assert not [r for r in caplog.records if r.levelname == "WARNING"]


# ---------------------------------------------------------------------------
# Verdict: pushed validity gated on timestamp age (#56)
# ---------------------------------------------------------------------------

class TestVerdict:
    def test_pushed_validity_is_the_verdict(self):
        mp = FakeMP("a", Validity.VALID_ERROR_HIGH)
        system = _build_system([{"canonical_name": "a"}], [mp])
        assert [(e.validity) for e in system.tick()] == [Validity.VALID_ERROR_HIGH]

    def test_point_absent_from_redis_faults(self):
        """The old path left an absent point VALID_NOT_CHECKED forever."""
        mp = FakeMP("a", present=False)
        system = _build_system([{"canonical_name": "a"}], [mp])
        events = system.tick()
        assert [(e.canonical_name, e.validity) for e in events] == [
            (n("a"), Validity.INVALID_NO_DATA)]

    def test_missing_metadata_is_no_data(self):
        mp = FakeMP("a", validity=None)
        system = _build_system([{"canonical_name": "a"}], [mp])
        assert [e.validity for e in system.tick()] == [Validity.INVALID_NO_DATA]

    def test_stale_point_is_no_data_even_if_last_verdict_good(self):
        mp = FakeMP("a", Validity.VALID_GOOD, written_at=WALL_NOW - 60)
        system = _build_system([{"canonical_name": "a"}], [mp],
                               defaults={"computed_max_age_s": 6})
        assert [(e.canonical_name, e.validity) for e in system.tick()] == [
            (n("a"), Validity.INVALID_NO_DATA)]

    def test_per_node_max_age(self):
        mp = FakeMP("a", Validity.VALID_GOOD, written_at=WALL_NOW - 60)
        system = _build_system(
            [{"canonical_name": "a", "computed_max_age_s": 120}], [mp],
            defaults={"computed_max_age_s": 6})
        assert system.tick() == []

    def test_staleness_uses_injected_wall_clock(self):
        """--as-of replay: snapshot points are fresh relative to the as-of time."""
        as_of = WALL_NOW - 86_400 * 60
        hb = FakeMP(HEARTBEAT_NAME, written_at=as_of)
        mp = FakeMP("a", Validity.VALID_GOOD, written_at=as_of - 1)
        system = _build_system([{"canonical_name": "a"}], [mp],
                               defaults={"computed_max_age_s": 6},
                               wall_clock=lambda: as_of, heartbeat=hb)
        assert system.tick() == []

    def test_non_fault_verdicts_do_not_fault(self):
        mps = [FakeMP("nc", Validity.VALID_NOT_CHECKED),
               FakeMP("warn", Validity.VALID_WARNING)]
        system = _build_system(
            [{"canonical_name": "nc"}, {"canonical_name": "warn"}], mps)
        assert system.tick() == []


# ---------------------------------------------------------------------------
# Debounce by verdict and parent lag (#56)
# ---------------------------------------------------------------------------

class TestVerdictFilters:
    def _system(self, mp, clock):
        return _build_system(
            [{"canonical_name": "a", "transient_filter_s": 5,
              "no_data_filter_s": 15}],
            [mp], clock=clock)

    def test_error_uses_short_filter(self):
        mp = FakeMP("a", Validity.VALID_ERROR)
        clock = FakeClock()
        system = self._system(mp, clock)
        assert system.tick() == []
        clock.advance(5)
        assert names(system.tick()) == ["a"]

    def test_no_data_waits_long_filter(self):
        mp = FakeMP("a", present=False)
        clock = FakeClock()
        system = self._system(mp, clock)
        system.tick()
        clock.advance(10)
        assert system.tick() == []
        clock.advance(5)
        events = system.tick()
        assert [(e.canonical_name, e.validity, e.transient_filter_s) for e in events] == [
            (n("a"), Validity.INVALID_NO_DATA, 15.0)]

    def test_error_then_no_data_keeps_episode_but_uses_long_filter(self):
        mp = FakeMP("a", Validity.VALID_ERROR)
        clock = FakeClock()
        system = self._system(mp, clock)
        system.tick()                       # episode starts at t=0
        clock.advance(3)
        mp.present = False                  # NO_DATA from t=3
        assert system.tick() == []
        clock.advance(9)                    # t=12 < 15
        assert system.tick() == []
        clock.advance(3)                    # t=15, measured from t=0
        assert names(system.tick()) == ["a"]

    def test_no_data_then_error_debounces_immediately(self):
        mp = FakeMP("a", present=False)
        clock = FakeClock()
        system = self._system(mp, clock)
        system.tick()                       # NO_DATA episode starts at t=0
        clock.advance(10)
        mp.present = True
        mp.set_validity(Validity.VALID_ERROR)
        assert names(system.tick()) == ["a"]   # 10 >= 5


class TestParentLag:
    def test_faulted_parent_hides_child_before_parent_debounces(self):
        parent = FakeMP("p", Validity.VALID_ERROR)
        child = FakeMP("c", Validity.VALID_ERROR)
        clock = FakeClock()
        system = _build_system(
            [{"canonical_name": "p", "transient_filter_s": 30},
             {"canonical_name": "c", "parents": ["p"], "transient_filter_s": 1,
              "no_data_filter_s": 40}],
            [parent, child], clock=clock)
        system.tick()
        clock.advance(2)
        assert system.tick() == []          # child debounced, parent only faulted
        clock.advance(30)
        assert names(system.tick()) == ["p"]

    def test_heartbeat_outage_is_one_root(self):
        hb = FakeMP(HEARTBEAT_NAME, written_at=WALL_NOW - 60)
        mps = [FakeMP(x, written_at=WALL_NOW - 60) for x in ("a", "b", "c")]
        clock = FakeClock()
        system = _build_system(
            [{"canonical_name": x} for x in ("a", "b", "c")], mps,
            defaults={"computed_max_age_s": 6, "no_data_filter_s": 6},
            heartbeat=hb, clock=clock)
        assert system.tick() == []
        clock.advance(6)
        assert [e.canonical_name for e in system.tick()] == [HEARTBEAT_NAME]

    def test_host_down_hides_stale_children_and_frozen_lock(self):
        """acc{i} dies: drive goes NO_DATA in seconds, yig1 freezes GOOD,
        gunn1 goes NO_DATA; only host-down reports, once report_age errs."""
        host = FakeMP("host", Validity.VALID_GOOD)
        yig1 = FakeMP("yig1", Validity.VALID_GOOD)       # frozen GOOD
        drive = FakeMP("drive", present=False)            # stale input
        gunn1 = FakeMP("gunn1", present=False)
        clock = FakeClock()
        system = _build_system(
            [{"canonical_name": "host", "onset_s": 70, "transient_filter_s": 5,
              "no_data_filter_s": 15},
             {"canonical_name": "drive", "parents": ["host"], "no_data_filter_s": 100},
             {"canonical_name": "yig1", "parents": ["host"], "no_data_filter_s": 100},
             {"canonical_name": "gunn1", "parents": ["yig1", "host"],
              "no_data_filter_s": 110}],
            [host, yig1, drive, gunn1], clock=clock)
        reported = []
        for t in range(0, 120, 2):
            if t == 70:
                host.set_validity(Validity.VALID_ERROR_HIGH)
            reported += names(system.tick())
            clock.advance(2)
        assert reported == ["host"]

    def test_real_unlock_alerts_on_short_filter(self):
        host = FakeMP("host", Validity.VALID_GOOD)
        yig1 = FakeMP("yig1", Validity.VALID_ERROR)
        clock = FakeClock()
        system = _build_system(
            [{"canonical_name": "host", "onset_s": 70, "transient_filter_s": 5,
              "no_data_filter_s": 15},
             {"canonical_name": "yig1", "parents": ["host"], "transient_filter_s": 5,
              "no_data_filter_s": 100}],
            [host, yig1], clock=clock)
        system.tick()
        clock.advance(6)
        assert names(system.tick()) == ["yig1"]


# ---------------------------------------------------------------------------
# FaultEvent value and context
# ---------------------------------------------------------------------------

class TestEventContext:
    def test_event_carries_value_and_context(self):
        gunn = FakeMP("gunn1", Validity.VALID_ERROR, value=0.0)
        ifp = FakeMP("ifpower", value=12.5)
        missing = "absent_ctx"
        system = _build_system(
            [{"canonical_name": "gunn1", "context": ["ifpower", missing]}],
            [gunn, ifp])
        (event,) = system.tick()
        assert event.value == 0.0
        assert event.context == {n("ifpower"): 12.5, n(missing): None}


# ---------------------------------------------------------------------------
# Recovery: a parent clears while children are still stale
# ---------------------------------------------------------------------------

class TestRecovery:
    def test_engine_restart_does_not_flood(self):
        """The engine writes the heartbeat first, then ~1 s of other outputs."""
        hb = FakeMP(HEARTBEAT_NAME, written_at=WALL_NOW - 60)
        kids = [FakeMP(x, written_at=WALL_NOW - 60) for x in ("a", "b", "c")]
        clock = FakeClock()
        system = _build_system(
            [{"canonical_name": x} for x in ("a", "b", "c")], kids,
            defaults={"computed_max_age_s": 6, "transient_filter_s": 5,
                      "no_data_filter_s": 15},
            heartbeat=hb, clock=clock)
        system.tick()
        clock.advance(200)
        assert [e.canonical_name for e in system.tick()] == [HEARTBEAT_NAME]
        hb.written_at = WALL_NOW            # engine back; children not yet rewritten
        clock.advance(2)
        assert system.tick() == []

    def test_host_recovery_with_lagging_child(self):
        host = FakeMP("host", Validity.VALID_ERROR_HIGH)
        drive = FakeMP("drive", present=False)
        clock = FakeClock()
        system = _build_system(
            [{"canonical_name": "host", "onset_s": 70, "transient_filter_s": 5,
              "no_data_filter_s": 15},
             {"canonical_name": "drive", "parents": ["host"],
              "no_data_filter_s": 100}],
            [host, drive], clock=clock)
        system.tick()
        clock.advance(200)
        assert names(system.tick()) == ["host"]
        host.set_validity(Validity.VALID_GOOD)   # host reports again
        clock.advance(2)
        assert system.tick() == []               # drive's inputs one tick behind

    def test_child_with_own_fault_reports_a_full_filter_after_parent_clears(self):
        host = FakeMP("host", Validity.VALID_ERROR_HIGH)
        drive = FakeMP("drive", Validity.VALID_ERROR)     # a real, separate fault
        clock = FakeClock()
        system = _build_system(
            [{"canonical_name": "host", "onset_s": 70, "transient_filter_s": 5,
              "no_data_filter_s": 15},
             {"canonical_name": "drive", "parents": ["host"], "transient_filter_s": 5,
              "no_data_filter_s": 100}],
            [host, drive], clock=clock)
        system.tick()
        clock.advance(200)
        assert names(system.tick()) == ["host"]
        host.set_validity(Validity.VALID_GOOD)
        clock.advance(2)
        assert system.tick() == []               # clock restarted at the last hidden tick
        clock.advance(4)                         # 6 s since last hidden >= 5
        assert names(system.tick()) == ["drive"]

    def test_reported_child_does_not_refire_after_parent_episode(self):
        parent = FakeMP("p", Validity.VALID_GOOD)
        child = FakeMP("c", Validity.VALID_ERROR)
        clock = FakeClock()
        system = _build_system(
            [{"canonical_name": "p"},
             {"canonical_name": "c", "parents": ["p"]}],
            [parent, child], clock=clock)
        assert names(system.tick()) == ["c"]     # reported on its own
        parent.set_validity(Validity.VALID_ERROR)
        assert names(system.tick()) == ["p"]     # c hidden, clock reset
        parent.set_validity(Validity.VALID_GOOD)
        assert system.tick() == []               # same validity: dedup holds



# ---------------------------------------------------------------------------
# Published state (phase 5)
# ---------------------------------------------------------------------------

class TestPublishedState:
    def _states(self, system):
        return {short([k])[0]: v["state"]
                for k, v in system.last_snapshot["nodes"].items()
                if k != HEARTBEAT_NAME}

    def test_snapshot_published_then_heartbeat(self):
        import json
        mp = FakeMP("a", Validity.VALID_ERROR)
        system = _build_system([{"canonical_name": "a"}], [mp])
        system.tick()
        shares = system._client.shares
        assert [name for name, _ in shares] == ["faultsystem:state", "faultsystem:heartbeat"]
        snapshot = json.loads(shares[0][1])
        assert snapshot == system.last_snapshot
        assert shares[1][1] == WALL_NOW
        assert snapshot["nodes"][n("a")] == {
            "state": "root", "validity": "VALID_ERROR", "since": WALL_NOW}

    def test_states_through_an_episode(self):
        parent = FakeMP("p", Validity.VALID_GOOD)
        child = FakeMP("c", Validity.VALID_ERROR)
        clock = FakeClock()
        system = _build_system(
            [{"canonical_name": "p", "transient_filter_s": 5},
             {"canonical_name": "c", "parents": ["p"], "transient_filter_s": 5,
              "no_data_filter_s": 10}],
            [parent, child], clock=clock)
        system.tick()
        assert self._states(system) == {"p": "ok", "c": "debouncing"}
        clock.advance(6)
        system.tick()
        assert self._states(system) == {"p": "ok", "c": "root"}
        system.tick()                                   # deduped, still root
        assert self._states(system) == {"p": "ok", "c": "root"}
        parent.set_validity(Validity.VALID_ERROR)
        system.tick()
        assert self._states(system) == {"p": "debouncing", "c": "consequence"}
        assert system.last_snapshot["nodes"][n("c")]["hidden_by"] == [n("p")]

    def test_since_survives_hidden_ticks_and_clears_on_recovery(self):
        parent = FakeMP("p", Validity.VALID_ERROR)
        child = FakeMP("c", Validity.VALID_ERROR)
        wall = [WALL_NOW]
        system = _build_system(
            [{"canonical_name": "p", "onset_s": 0},
             {"canonical_name": "c", "parents": ["p"]}],
            [parent, child], wall_clock=lambda: wall[0],
            # points are written at WALL_NOW; keep them fresh as wall advances
            defaults={"computed_max_age_s": 1000})
        system.tick()
        wall[0] += 100
        system.tick()                   # c hidden: debounce clock reset, since kept
        assert system.last_snapshot["nodes"][n("c")]["since"] == WALL_NOW
        child.set_validity(Validity.VALID_GOOD)
        system.tick()
        assert system.last_snapshot["nodes"][n("c")]["since"] is None

    def test_ignored_root(self):
        mp = FakeMP("a", Validity.VALID_ERROR)
        system = _build_system([{"canonical_name": "a"}], [mp])
        system.ignore(n("a"))
        system.tick()
        assert self._states(system) == {"a": "ignored"}

    def test_every_node_in_config_order(self):
        mps = [FakeMP(x) for x in ("b", "a", "c")]
        system = _build_system([{"canonical_name": x} for x in ("b", "a", "c")], mps)
        system.tick()
        assert list(system.last_snapshot["nodes"]) == [
            HEARTBEAT_NAME, n("b"), n("a"), n("c")]

    def test_publish_failure_is_logged_not_raised(self, caplog):
        mp = FakeMP("a", Validity.VALID_ERROR)
        rec = RecordingAction()
        system = _build_system([{"canonical_name": "a"}], [mp], {"rec": rec})

        def boom(*args):
            raise ConnectionError("valkey down")
        system._client.smax_share = boom
        with caplog.at_level("ERROR", logger="slama.fault.faultsystem"):
            events = system.tick()
        assert names(events) == ["a"] and len(rec.events) == 1
        assert any("publishing faultsystem:state failed" in r.getMessage()
                   for r in caplog.records)

    def test_no_client_builds_but_does_not_publish(self):
        system = _build_system([{"canonical_name": "a"}], [FakeMP("a")], client=False)
        system.tick()
        assert system.last_snapshot["nodes"][n("a")]["validity"] == "INVALID_NO_DATA"
