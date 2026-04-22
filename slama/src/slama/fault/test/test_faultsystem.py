"""Unit tests for FaultSystem: DAG walking, debounce, ignore, dedup."""
import pytest

from slama.fault.faultconfig import FaultConfig
from slama.fault.faultnode import FaultEvent
from slama.fault.faultsystem import FaultSystem
from slama.monitor.monitorpoint import Validity


# ---------------------------------------------------------------------------
# Fakes — avoid needing a real SmaxRedisClient or MonitorSystem.
# ---------------------------------------------------------------------------

class FakeMP:
    def __init__(self, canonical_name, validity=Validity.VALID_GOOD):
        self.canonical_name = canonical_name
        self._validity = validity

    @property
    def validity(self):
        return self._validity

    def set_validity(self, v):
        self._validity = v


class FakeMonitorSystem:
    def __init__(self, mps):
        self._mps = {mp.canonical_name: mp for mp in mps}

    def get_monitor_point(self, name):
        if name not in self._mps:
            raise KeyError(name)
        return self._mps[name]

    def read_all(self, client):
        pass


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

def _build_system(nodes, mps, action_map=None, clock=None, wall_clock=None,
                  tmp_path=None):
    """Build a FaultSystem directly from a list of node dicts, bypassing
    JSON. `action_map` maps action-key -> Action instance."""
    action_map = action_map or {"rec": RecordingAction()}
    # The config loader validates action names against the declared
    # actions dict, so declare throwaway log_file specs — we replace them
    # with the real (fake) Action instances below.
    placeholder = "/tmp/slama-fault-test.log"
    raw_actions = {k: {"type": "log_file", "path": placeholder}
                   for k in action_map}
    raw_faults = [
        {"canonical_name": n["canonical_name"],
         "parents": n.get("parents", []),
         "transient_filter_s": n.get("transient_filter_s", 0),
         "actions": list(action_map.keys())}
        for n in nodes
    ]
    raw = {
        "defaults": {"transient_filter_s": 0, "interval_s": 1},
        "actions": raw_actions,
        "faults": raw_faults,
    }
    cfg = FaultConfig.from_dict(raw)
    cfg.actions = dict(action_map)

    ms = FakeMonitorSystem(mps)
    system = FaultSystem(
        cfg, ms, client=None,
        clock=clock or FakeClock(),
        wall_clock=wall_clock or (lambda: 1700000000.0),
    )
    return system


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
        assert [e.canonical_name for e in events] == ["a"]

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
        assert [e.canonical_name for e in events] == ["a"]

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
        assert [e.canonical_name for e in events] == ["b"]

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
        assert [e.canonical_name for e in events] == ["a"]

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
        system.ignore("antenna:1:*")
        events = system.tick()
        assert [e.canonical_name for e in events] == ["antenna:2:heater"]

    def test_ttl_expires(self):
        mp = FakeMP("a", Validity.VALID_ERROR)
        clock = FakeClock()
        rec = RecordingAction()
        system = _build_system(
            [{"canonical_name": "a"}], [mp], {"rec": rec}, clock=clock,
        )
        system.ignore("a", seconds=5)
        assert system.tick() == []
        clock.advance(10)
        events = system.tick()
        assert [e.canonical_name for e in events] == ["a"]

    def test_seconds_zero_means_indefinite(self):
        mp = FakeMP("a", Validity.VALID_ERROR)
        clock = FakeClock()
        rec = RecordingAction()
        system = _build_system(
            [{"canonical_name": "a"}], [mp], {"rec": rec}, clock=clock,
        )
        system.ignore("a", seconds=0)
        clock.advance(10_000_000)
        assert system.tick() == []

    def test_unignore_clears_pattern(self):
        mp = FakeMP("a", Validity.VALID_ERROR)
        rec = RecordingAction()
        system = _build_system(
            [{"canonical_name": "a"}], [mp], {"rec": rec},
        )
        system.ignore("a")
        assert system.tick() == []
        system.unignore("a")
        events = system.tick()
        assert [e.canonical_name for e in events] == ["a"]

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
        system.ignore("a")
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

class TestReloadConfig:
    def test_reload_keeps_ignores(self, tmp_path):
        import json
        mp = FakeMP("a", Validity.VALID_ERROR)
        rec = RecordingAction()
        system = _build_system(
            [{"canonical_name": "a"}], [mp], {"rec": rec},
        )
        system.ignore("a")

        new_cfg = {
            "defaults": {"transient_filter_s": 0, "interval_s": 1},
            "actions": {
                "log": {"type": "log_file", "path": str(tmp_path / "f.log")},
            },
            "faults": [
                {"canonical_name": "a", "actions": ["log"]},
                {"canonical_name": "b", "actions": ["log"]},
            ],
        }
        path = tmp_path / "faults.json"
        path.write_text(json.dumps(new_cfg))
        system.reload_config(path)

        # "a" still ignored; the original RecordingAction is replaced by
        # the new LogFileAction, so we just check the tick returns no event
        # for 'a' because of the still-active ignore.
        events = system.tick()
        assert all(e.canonical_name != "a" for e in events)
