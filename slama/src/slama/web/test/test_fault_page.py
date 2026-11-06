"""Tests for the generated Fault System page (``slama.web.fault_page``).

No SMAX server: the reader gets a fake client, and templates are rendered
directly with Jinja (``httpx`` is not a dev dependency, so no TestClient).
"""
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from slama.fault.faultconfig import FaultConfig
from slama.fault.publish import FAULT_HEARTBEAT_NAME, STATE_NAME
from slama.monitor.compute.engine import HEARTBEAT_NAME
from slama.web import server
from slama.web.fault_page import (
    FaultPage,
    FaultPageData,
    FaultPageReader,
    HeartbeatStatus,
    build_fault_layout,
    cell_view,
    format_duration,
    slot_summary,
)

CONF = Path(__file__).resolve().parents[2] / "conf"
NOW = 1_800_000_000.0
TICK = 1_790_094_623.0  # replayed epoch: far older than NOW


# ----------------------------------------------------------------------
# Fakes and builders
# ----------------------------------------------------------------------

class _Str(str):
    """String with a ``timestamp``, like an SMAX string pull."""

    def __new__(cls, value, ts):
        obj = super().__new__(cls, value)
        obj.timestamp = datetime.fromtimestamp(ts, tz=timezone.utc)
        return obj


class _Num(float):
    """Float with a ``timestamp``, like an SMAX numeric pull."""

    def __new__(cls, value, ts):
        obj = super().__new__(cls, value)
        obj.timestamp = datetime.fromtimestamp(ts, tz=timezone.utc)
        return obj


class FakeClient:
    """``smax_pull`` from a dict of canonical name to value; records pulls."""

    def __init__(self, values):
        self.values = values
        self.pulls = []

    def smax_pull(self, table, key):
        name = f"{table}:{key}"
        self.pulls.append(name)
        if name not in self.values:
            raise KeyError(name)
        return self.values[name]


def _config(extra=()):
    """A small FaultConfig: heartbeat, two antennas, two hosts, ``extra`` nodes."""
    faults = [{"canonical_name": HEARTBEAT_NAME, "onset_s": 0}]
    for i in (1, 2):
        faults.append({"canonical_name": f"monitorsystem:smainit:acc{i}:report_age", "onset_s": 0})
        faults.append({"canonical_name": f"monitorsystem:antenna:{i}:drive_fault"})
    faults.append({"canonical_name": "monitorsystem:antenna:1:yig1_lock_fault"})
    faults.append({"canonical_name": "monitorsystem:smainit:hal9000:report_age", "onset_s": 0})
    for j in (1, 2):
        faults.append({
            "canonical_name": f"monitorsystem:smainit:hal9000:slot:{j}:status",
            "parents": ["monitorsystem:smainit:hal9000:report_age"],
            "context": [f"monitorsystem:smainit:hal9000:slot:{j}:name"],
        })
    faults.extend({"canonical_name": n} for n in extra)
    return FaultConfig.from_dict({
        "defaults": {"transient_filter_s": 0, "no_data_filter_s": 0,
                     "computed_max_age_s": 0},
        "actions": {},
        "faults": faults,
    })


def _snapshot(states=None, names=()):
    """A snapshot with every node in ``names`` ok, except those in ``states``."""
    nodes = {}
    for name in names:
        nodes[name] = {"state": "ok", "validity": "VALID_GOOD", "since": None}
    for name, entry in (states or {}).items():
        nodes[name] = entry
    return {"version": 1, "tick": TICK, "interval_s": 2.0, "nodes": nodes}


def _data(snapshot, fault_fresh=True, engine_fresh=True, online=None, error=None):
    return FaultPageData(
        snapshot, error,
        HeartbeatStatus("Fault system", FAULT_HEARTBEAT_NAME, fault_fresh, 1.0),
        HeartbeatStatus("Compute engine", HEARTBEAT_NAME, engine_fresh, 1.0),
        online=online or {},
    )


def _values(snapshot, hb_age=1.0, engine_age=1.0, extra=None):
    """SMAX values for a reader test: state, heartbeats (value = replayed tick)."""
    values = {
        STATE_NAME: _Str(json.dumps(snapshot), NOW - hb_age),
        FAULT_HEARTBEAT_NAME: _Num(TICK, NOW - hb_age),
        HEARTBEAT_NAME: _Num(TICK, NOW - engine_age),
    }
    values.update(extra or {})
    return values


def _reader(client, max_age=6.0):
    return FaultPageReader(lambda: client, max_age, clock=lambda: NOW)


# ----------------------------------------------------------------------
# Layout
# ----------------------------------------------------------------------

class TestShippedLayout:
    @pytest.fixture(scope="class")
    def config(self):
        return FaultConfig.from_file(CONF / "faults.json")

    @pytest.fixture(scope="class")
    def layout(self, config):
        return build_fault_layout(config)

    def test_every_node_owned_exactly_once(self, config, layout):
        owned = [n for names in layout.owned().values() for n in names]
        assert len(owned) == len(set(owned))
        assert set(owned) == set(config.nodes)

    def test_antenna_grid(self, layout):
        assert layout.antennas.antennas == list(range(1, 9))
        assert [label for label, _ in layout.antennas.rows] == [
            "Host", "Servo", "Tune6", "Drive", "YIG1", "Gunn1", "Gunn2"]
        assert all(all(names) for _, names in layout.antennas.rows)

    def test_hosts(self, layout):
        assert len(layout.hosts) == 13
        assert all(row.report_age for row in layout.hosts)
        acc1 = next(r for r in layout.hosts if r.host == "acc1")
        assert acc1.slots and all(s.name_point.endswith(":name") for s in acc1.slots)

    def test_other_is_empty_and_heartbeat_in_status(self, layout):
        assert layout.other == []
        assert layout.heartbeat == HEARTBEAT_NAME


class TestSyntheticLayout:
    def test_missing_antenna_node_is_blank(self):
        layout = build_fault_layout(_config())
        yig = dict(layout.antennas.rows)["YIG1"]
        assert yig == ["monitorsystem:antenna:1:yig1_lock_fault", None]

    def test_unmatched_node_goes_to_other_by_prefix(self):
        layout = build_fault_layout(_config(extra=["monitorsystem:array:foo"]))
        assert [(g.prefix, g.names) for g in layout.other] == [
            ("array:foo", ["monitorsystem:array:foo"])]

    def test_unknown_antenna_key_gets_derived_label(self):
        layout = build_fault_layout(_config(extra=["monitorsystem:antenna:2:cryo_fault"]))
        assert dict(layout.antennas.rows)["Cryo"] == [None, "monitorsystem:antenna:2:cryo_fault"]

    def test_owned_covers_synthetic_config(self):
        cfg = _config(extra=["monitorsystem:array:foo"])
        owned = [n for v in build_fault_layout(cfg).owned().values() for n in v]
        assert sorted(owned) == sorted(cfg.nodes)


# ----------------------------------------------------------------------
# Reader
# ----------------------------------------------------------------------

class TestReader:
    layout = build_fault_layout(_config())
    names = list(_config().nodes)

    def test_fresh(self):
        client = FakeClient(_values(_snapshot(names=self.names)))
        data = _reader(client).read(self.layout)
        assert data.error is None and data.usable
        assert data.fault_hb.fresh and data.engine_hb.fresh
        assert data.banners() == []

    def test_heartbeat_gated_on_write_time_not_value(self):
        # The heartbeat values are the replayed TICK, months before NOW;
        # a fresh write timestamp still counts as running.
        client = FakeClient(_values(_snapshot(names=self.names)))
        assert _reader(client).read(self.layout).fault_hb.fresh

    def test_stale_fault_heartbeat(self):
        client = FakeClient(_values(_snapshot(names=self.names), hb_age=60))
        data = _reader(client).read(self.layout)
        assert not data.usable
        assert data.banners()[0].startswith("Fault system not running; states as of 2026-09-22")
        assert cell_view(self.names[1], data).text == "---"

    def test_stale_engine_heartbeat_keeps_cells(self):
        client = FakeClient(_values(_snapshot(names=self.names), engine_age=60))
        data = _reader(client).read(self.layout)
        assert data.usable
        assert data.banners() == ["Compute engine not running"]

    def test_inf_max_age(self):
        client = FakeClient(_values(_snapshot(names=self.names), hb_age=1e6, engine_age=1e6))
        data = _reader(client, max_age=float("inf")).read(self.layout)
        assert data.usable and data.banners() == []

    def test_missing_state(self):
        values = _values(_snapshot())
        del values[STATE_NAME]
        data = _reader(FakeClient(values)).read(self.layout)
        assert data.snapshot is None and "not found" in data.error
        assert data.banners()[0] == data.error

    def test_bad_json(self):
        values = _values(_snapshot())
        values[STATE_NAME] = _Str("{nope", NOW)
        data = _reader(FakeClient(values)).read(self.layout)
        assert data.snapshot is None and "not JSON" in data.error

    def test_wrong_version(self):
        snap = _snapshot()
        snap["version"] = 99
        data = _reader(FakeClient(_values(snap))).read(self.layout)
        assert data.snapshot is None and "version 99" in data.error

    def test_no_client(self):
        data = FaultPageReader(lambda: None, 6.0, clock=lambda: NOW).read(self.layout)
        assert not data.usable and data.error == "SMAX server unreachable"

    def test_online(self):
        extra = {
            "monitorsystem:antenna:1:online": _Num(1, NOW),
            "monitorsystem:antenna:2:online": _Num(0, NOW),
        }
        data = _reader(FakeClient(_values(_snapshot(names=self.names), extra=extra))).read(self.layout)
        assert data.online == {1: True, 2: False}

    def test_non_numeric_online_is_unknown(self):
        extra = {"monitorsystem:antenna:1:online": _Str("yes", NOW)}
        data = _reader(FakeClient(_values(_snapshot(names=self.names), extra=extra))).read(self.layout)
        assert data.online[1] is None

    def test_stale_online_is_unknown(self):
        extra = {"monitorsystem:antenna:1:online": _Num(0, NOW - 60)}
        data = _reader(FakeClient(_values(_snapshot(names=self.names), extra=extra))).read(self.layout)
        assert data.online == {1: None, 2: None}

    def test_names_pulled_only_for_faulted_slots(self):
        slot1 = "monitorsystem:smainit:hal9000:slot:1:status"
        snap = _snapshot({slot1: {"state": "root", "validity": "VALID_ERROR", "since": TICK - 30}},
                         names=self.names)
        extra = {"monitorsystem:smainit:hal9000:slot:1:name": _Str("tune6", NOW),
                 "monitorsystem:smainit:hal9000:slot:2:name": _Str("servo", NOW)}
        client = FakeClient(_values(snap, extra=extra))
        data = _reader(client).read(self.layout)
        assert data.slot_names == {slot1: "tune6"}
        assert "monitorsystem:smainit:hal9000:slot:2:name" not in client.pulls

    def test_pull_count_when_all_ok(self):
        client = FakeClient(_values(_snapshot(names=self.names)))
        _reader(client).read(self.layout)
        # state + 2 heartbeats + 2 online, no names
        assert len(client.pulls) == 5


# ----------------------------------------------------------------------
# Views
# ----------------------------------------------------------------------

NODE = "monitorsystem:antenna:1:drive_fault"


class TestCellView:
    @pytest.mark.parametrize("state, css, text", [
        ("root", "cell-error fault-root", "2m"),
        ("consequence", "fault-consequence", "2m"),
        ("debouncing", "cell-warning fault-debouncing", "2m"),
        ("ignored", "fault-ignored", "ign"),
    ])
    def test_fault_states(self, state, css, text):
        snap = _snapshot({NODE: {"state": state, "validity": "VALID_ERROR", "since": TICK - 150}})
        cell = cell_view(NODE, _data(snap))
        assert (cell.css, cell.text, cell.state) == (css, text, state)

    @pytest.mark.parametrize("validity, css", [
        ("VALID_GOOD", "cell-good"), ("VALID_NOT_CHECKED", "cell-unchecked"),
        ("VALID_WARNING", "cell-warning"), ("BOGUS", "cell-nodata"),
    ])
    def test_ok_coloured_by_validity(self, validity, css):
        snap = _snapshot({NODE: {"state": "ok", "validity": validity, "since": None}})
        cell = cell_view(NODE, _data(snap))
        assert (cell.css, cell.text) == (css, "")

    def test_duration_uses_snapshot_tick_not_now(self):
        # since is 45 s before the (replayed) tick; NOW is months later.
        snap = _snapshot({NODE: {"state": "root", "validity": "VALID_ERROR", "since": TICK - 45}})
        assert cell_view(NODE, _data(snap)).text == "45s"

    def test_tooltip_lists_hidden_by(self):
        parent = "monitorsystem:smainit:acc1:report_age"
        snap = _snapshot({NODE: {"state": "consequence", "validity": "INVALID_NO_DATA",
                                 "since": TICK, "hidden_by": [parent]}})
        title = cell_view(NODE, _data(snap)).title
        assert NODE in title and "consequence (INVALID_NO_DATA)" in title
        assert f"hidden by {parent}" in title and "since 2026-09-22" in title

    def test_offarray_dims(self):
        snap = _snapshot({NODE: {"state": "ok", "validity": "VALID_NOT_CHECKED", "since": None}})
        assert cell_view(NODE, _data(snap), offarray=True).css == "cell-unchecked fault-offarray"

    def test_unusable_is_nodata(self):
        snap = _snapshot({NODE: {"state": "root", "validity": "VALID_ERROR", "since": TICK}})
        cell = cell_view(NODE, _data(snap, fault_fresh=False))
        assert (cell.css, cell.text, cell.state) == ("cell-nodata", "---", None)

    def test_node_missing_from_snapshot_is_nodata(self):
        cell = cell_view(NODE, _data(_snapshot()))
        assert cell.text == "---" and cell.state is None

    def test_empty_position(self):
        assert cell_view(None, _data(_snapshot())).css == "fault-empty"


@pytest.mark.parametrize("seconds, text", [
    (None, ""), (-3, "0s"), (45, "45s"), (119, "119s"), (120, "2m"),
    (7199, "119m"), (7200, "2h"), (172799, "47h"), (172800, "2d"),
])
def test_format_duration(seconds, text):
    assert format_duration(seconds) == text


class TestSlotSummary:
    layout = build_fault_layout(_config())
    hal = next(r for r in layout.hosts if r.host == "hal9000")

    def test_all_ok(self):
        cell, faulted = slot_summary(self.hal, _data(_snapshot(names=_config().nodes)))
        assert (cell.text, cell.css, faulted) == ("", "cell-good", [])

    def test_counts_and_worst_state(self):
        s1, s2 = (f"monitorsystem:smainit:hal9000:slot:{j}:status" for j in (1, 2))
        snap = _snapshot({
            s1: {"state": "debouncing", "validity": "VALID_ERROR", "since": TICK},
            s2: {"state": "root", "validity": "VALID_ERROR", "since": TICK - 300},
        })
        data = _data(snap)
        data.slot_names = {s2: "tune6"}
        cell, faulted = slot_summary(self.hal, data)
        assert cell.text == "2" and cell.state == "root"
        assert [(f["slot"], f["name"]) for f in faulted] == [(1, ""), (2, "tune6")]

    def test_unusable(self):
        cell, faulted = slot_summary(self.hal, _data(_snapshot(), fault_fresh=False))
        assert (cell.text, faulted) == ("---", [])


# ----------------------------------------------------------------------
# Rendering and server wiring
# ----------------------------------------------------------------------

class _StaticReader:
    """Reader returning fixed data."""

    def __init__(self, data):
        self.data = data

    def read(self, layout):
        return self.data


def _page(tmp_path, data):
    path = tmp_path / "faults.json"
    path.write_text(json.dumps({
        "defaults": {"interval_s": 3, "transient_filter_s": 0, "no_data_filter_s": 0,
                     "computed_max_age_s": 0},
        "actions": {},
        "faults": [{"canonical_name": HEARTBEAT_NAME, "onset_s": 0},
                   {"canonical_name": NODE},
                   {"canonical_name": "monitorsystem:array:foo"}],
    }))
    return FaultPage(path, _StaticReader(data))


class TestRendering:
    def test_sections_render(self, tmp_path):
        snap = _snapshot({NODE: {"state": "root", "validity": "VALID_ERROR", "since": TICK - 45}},
                         names=[HEARTBEAT_NAME, "monitorsystem:array:foo"])
        page = _page(tmp_path, _data(snap, online={1: False}))
        assert page.update_interval == 3.0
        html = server._render_generated(page, page.read())
        assert 'id="fault-body" hx-swap-oob="innerHTML"' in html
        assert "fault-root" in html and ">45s<" in html
        assert "fault-offarray" in html
        assert "Other faults" in html and "monitorsystem:array:foo" in html
        assert "root 1" in html

    def test_banner_when_fault_system_stale(self, tmp_path):
        page = _page(tmp_path, _data(_snapshot(), fault_fresh=False))
        html = server._render_generated(page, page.read())
        assert "Fault system not running" in html and "fault-banner" in html

    def test_error_banner(self, tmp_path):
        page = _page(tmp_path, _data(None, error="faultsystem:state version 2; ..."))
        html = server._render_generated(page, page.read())
        assert "faultsystem:state version 2" in html

    def test_load_error(self, tmp_path):
        page = FaultPage(tmp_path / "missing.json", _StaticReader(None))
        assert page.layout is None and "Could not load" in page.load_error
        assert page.read() is None
        assert "Could not load" in server._render_generated(page, None)

    def test_full_page(self, tmp_path, monkeypatch):
        snap = _snapshot(names=[HEARTBEAT_NAME, NODE, "monitorsystem:array:foo"])
        page = _page(tmp_path, _data(snap))
        monkeypatch.setitem(server.GENERATED_PAGES, "faults", page)
        html = asyncio.run(server.display_page("faults"))
        assert 'ws-connect="/ws/display/faults"' in html
        assert 'id="fault-body"' in html and "<h1>Fault System</h1>" in html

    def test_full_page_when_read_fails(self, tmp_path, monkeypatch):
        page = _page(tmp_path, None)

        def boom():
            raise RuntimeError("down")
        page.read = boom
        monkeypatch.setitem(server.GENERATED_PAGES, "faults", page)
        html = asyncio.run(server.display_page("faults"))
        assert "Could not read the fault state from SMAX" in html


class _FakeWebSocket:
    """Records sends; disconnects after ``n`` of them; never receives."""

    def __init__(self, n=1):
        self.sent = []
        self.n = n

    async def send_text(self, text):
        self.sent.append(text)
        if len(self.sent) >= self.n:
            from fastapi import WebSocketDisconnect
            raise WebSocketDisconnect()

    async def receive_text(self):
        await asyncio.Event().wait()


class TestWebSocketPush:
    def test_pushes_body_then_stops_on_disconnect(self, tmp_path):
        page = _page(tmp_path, _data(_snapshot(names=[HEARTBEAT_NAME, NODE])))
        page.update_interval = 0.01
        ws = _FakeWebSocket(n=2)
        asyncio.run(server._ws_generated(ws, page))
        assert len(ws.sent) == 2
        assert all('id="fault-body" hx-swap-oob="innerHTML"' in m for m in ws.sent)

    def test_read_error_becomes_banner(self, tmp_path):
        page = _page(tmp_path, None)
        page.update_interval = 0.01

        def boom():
            raise RuntimeError("down")
        page.read = boom
        ws = _FakeWebSocket(n=1)
        asyncio.run(server._ws_generated(ws, page))
        assert "Could not read the fault state from SMAX" in ws.sent[0]


class TestServer:
    def test_fault_page_registered(self):
        page = server.GENERATED_PAGES["faults"]
        assert page.load_error is None and page.filename == "faults"

    def test_index_lists_fault_page_first(self, tmp_path, monkeypatch):
        page = _page(tmp_path, None)
        monkeypatch.setitem(server.GENERATED_PAGES, "faults", page)
        html = asyncio.run(server.index())
        assert html.index('href="/display/faults"') < html.index('href="/display/tracking"')
