"""Tests for the generated Processes page (``slama.web.process_page``).

No SMAX server: names come from a fake client, statuses from a fake
``fetch_cell``, and templates are rendered directly with Jinja.
"""
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from slama.monitor.compute.engine import HEARTBEAT_NAME
from slama.monitor.monitorsystem import _parse_index_set
from slama.web import server
from slama.web.data_bridge import CellData
from slama.web.fault_page import HeartbeatStatus
from slama.web.process_page import (
    ENGINE_BANNER,
    GroupData,
    HeartbeatGroup,
    HeartbeatProcess,
    HostCard,
    ProcessConfig,
    ProcessPage,
    ProcessPageData,
    ProcessPageReader,
    ProgramRow,
    SmainitGroup,
    heartbeat_view,
)

CONF = Path(__file__).resolve().parents[2] / "conf"
NOW = 1_800_000_000.0
P = "monitorsystem:smainit"


# ----------------------------------------------------------------------
# Fakes and builders
# ----------------------------------------------------------------------

class _Str(str):
    """String with a ``timestamp``, like an SMAX string pull."""

    def __new__(cls, value, ts=NOW):
        obj = super().__new__(cls, value)
        obj.timestamp = datetime.fromtimestamp(ts, tz=timezone.utc)
        return obj


class _Num(float):
    """Float with a ``timestamp``, like an SMAX numeric pull."""

    def __new__(cls, value, ts=NOW):
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


class FakeCells:
    """``fetch_cell`` from a dict of canonical name to ``(value, css)``."""

    def __init__(self, cells):
        self.cells = cells
        self.fetched = []

    def __call__(self, name):
        self.fetched.append(name)
        value, css = self.cells.get(name, ("---", "cell-nodata"))
        return CellData(name, value, css, "cell-x")


class Clock:
    """Settable wall clock."""

    def __init__(self, t=NOW):
        self.t = t

    def __call__(self):
        return self.t


def _config(hosts="hal9000,acc1", slots="0-2", refresh=60):
    return ProcessConfig.from_dict({
        "name": "Processes", "description": "d", "update_interval": 3,
        "names_refresh_s": refresh,
        "groups": [
            {"title": "SLAMA", "type": "heartbeat", "processes": [
                {"label": "Compute engine", "point": HEARTBEAT_NAME},
                {"label": "Fault system", "point": "faultsystem:heartbeat"}]},
            {"title": "smainit", "type": "smainit", "hosts": hosts, "slots": slots},
        ],
    })


def _names(**per_host):
    """Name-point values: ``hal9000=["watchdog", "", "dsm"]`` fills slots 0..n-1."""
    values = {}
    for host, names in per_host.items():
        for j, name in enumerate(names):
            values[f"{P}:{host}:slot:{j}:name"] = _Str(name)
    return values


def _hb_values(engine_age=1.0, fault_age=1.0):
    return {HEARTBEAT_NAME: _Num(1.0, NOW - engine_age),
            "faultsystem:heartbeat": _Num(1.0, NOW - fault_age)}


def _reader(client, cells, clock=None, max_age=6.0):
    return ProcessPageReader(lambda: client, cells, max_age, clock=clock or Clock())


# ----------------------------------------------------------------------
# Config
# ----------------------------------------------------------------------

def _find(tree, key):
    """First value of ``key`` anywhere in a nested dict."""
    if isinstance(tree, dict):
        if key in tree:
            return tree[key]
        for v in tree.values():
            found = _find(v, key)
            if found is not None:
                return found
    return None


class TestConfig:
    def test_shipped_file_loads(self):
        cfg = ProcessConfig.from_file(CONF / "processes.json")
        assert cfg.update_interval == 2 and cfg.names_refresh_s == 60
        hb, sm = cfg.groups
        assert isinstance(hb, HeartbeatGroup) and isinstance(sm, SmainitGroup)
        assert [p.point for p in hb.processes] == [HEARTBEAT_NAME, "faultsystem:heartbeat"]
        assert sm.slots == list(range(24))

    def test_hosts_match_smax_json(self):
        cfg = ProcessConfig.from_file(CONF / "processes.json")
        smainit = _find(json.loads((CONF / "smax.json").read_text()), "smainit")
        assert cfg.groups[1].hosts == _parse_index_set(smainit["__each__"]["over"])

    def test_slots_match_smax_json(self):
        cfg = ProcessConfig.from_file(CONF / "processes.json")
        smainit = _find(json.loads((CONF / "smax.json").read_text()), "smainit")
        slot = smainit["__each__"]["template"]["slot"]["__each__"]["over"]
        assert cfg.groups[1].slots == [int(s) for s in _parse_index_set(slot)]

    @pytest.mark.parametrize("group, match", [
        ({"title": "x", "type": "nope"}, "unknown type 'nope'"),
        ({"title": "x", "type": "smainit", "hosts": "", "slots": "0-1"}, "group 0 \\('x'\\)"),
        ({"title": "x", "type": "smainit", "hosts": "a", "slots": "a-b"}, "non-integer"),
        ({"title": "x", "type": "heartbeat", "processes": []}, "'processes'"),
        ({"title": "x", "type": "heartbeat", "processes": [{"label": "a"}]}, "'point'"),
        ({"type": "heartbeat"}, "'title'"),
    ])
    def test_bad_group_raises(self, group, match):
        with pytest.raises(ValueError, match=match):
            ProcessConfig.from_dict({"groups": [group]})

    def test_bad_top_level(self):
        with pytest.raises(ValueError, match="'groups'"):
            ProcessConfig.from_dict({"groups": []})
        with pytest.raises(ValueError, match="'update_interval'"):
            ProcessConfig.from_dict({"update_interval": 0,
                                     "groups": [{"title": "x", "type": "heartbeat",
                                                 "processes": [{"label": "a", "point": "b:c"}]}]})

    def test_bad_json_file(self, tmp_path):
        path = tmp_path / "p.json"
        path.write_text("{")
        with pytest.raises(ValueError, match="p.json"):
            ProcessConfig.from_file(path)


# ----------------------------------------------------------------------
# Reader
# ----------------------------------------------------------------------

class TestReader:
    def test_reads_named_slots_only(self):
        client = FakeClient({**_hb_values(), **_names(hal9000=["watchdog", "", "dsm"])})
        cells = FakeCells({f"{P}:hal9000:slot:0:status": ("running", "cell-good"),
                           f"{P}:hal9000:slot:2:status": ("terminated", "cell-error"),
                           f"{P}:hal9000:report_age": ("0.5000", "cell-good")})
        data = _reader(client, cells).read(_config())
        hal, acc1 = data.groups[1].hosts
        assert [(p.slot, p.name, p.status, p.css) for p in hal.programs] == [
            (0, "watchdog", "running", "cell-good"), (2, "dsm", "terminated", "cell-error")]
        assert acc1.programs == [] and acc1.report_css == "cell-nodata"
        assert f"{P}:hal9000:slot:1:status" not in cells.fetched
        # each refresh: one report_age per host plus one status per named slot
        assert len(cells.fetched) == 2 + 2

    def test_names_pulled_once_then_after_refresh(self):
        client = FakeClient({**_hb_values(), **_names(hal9000=["watchdog"])})
        clock = Clock()
        reader = _reader(client, FakeCells({}), clock=clock)
        cfg = _config()
        n_names = 2 * 3  # hosts x slots
        reader.read(cfg)
        assert len(client.pulls) == n_names + 2
        clock.t += 59
        reader.read(cfg)
        assert len(client.pulls) == n_names + 2 + 2   # heartbeats only
        client.values[f"{P}:acc1:slot:1:name"] = _Str("servo")
        clock.t += 1
        data = reader.read(cfg)
        assert len(client.pulls) == 2 * n_names + 6
        assert [p.name for p in data.groups[1].hosts[1].programs] == ["servo"]

    def test_names_whitespace_dropped(self):
        client = FakeClient(_names(hal9000=["  ", " dsm "]))
        data = _reader(client, FakeCells({})).read(_config())
        assert [(p.slot, p.name) for p in data.groups[1].hosts[0].programs] == [(1, "dsm")]

    def test_failed_names_read_is_retried(self):
        client = FakeClient(_hb_values())   # no name points at all
        reader = _reader(client, FakeCells({}))
        reader.read(_config())
        client.values.update(_names(hal9000=["dsm"]))
        data = reader.read(_config())   # same clock: retried, not cached
        assert [p.name for p in data.groups[1].hosts[0].programs] == ["dsm"]

    @pytest.mark.parametrize("engine_age, max_age, fresh", [
        (1.0, 6.0, True), (100.0, 6.0, False), (1e6, float("inf"), True)])
    def test_heartbeat_freshness(self, engine_age, max_age, fresh):
        client = FakeClient(_hb_values(engine_age=engine_age))
        data = _reader(client, FakeCells({}), max_age=max_age).read(_config())
        hb = data.groups[0].heartbeats[0]
        assert hb.fresh is fresh and hb.age_s == pytest.approx(engine_age)

    def test_missing_heartbeat(self):
        data = _reader(FakeClient({}), FakeCells({})).read(_config())
        assert all(hb.age_s is None and not hb.fresh for hb in data.groups[0].heartbeats)

    def test_no_client(self):
        cells = FakeCells({})
        data = _reader(None, cells).read(_config())
        assert data.error == "SMAX server unreachable"
        assert all(hb.age_s is None for hb in data.groups[0].heartbeats)
        assert [c.header_text for c in data.groups[1].hosts] == ["no data", "no data"]

    def test_stale_report_age(self):
        cells = FakeCells({f"{P}:hal9000:report_age": ("10800.0000", "cell-error")})
        data = _reader(FakeClient({}), cells).read(_config())
        card = data.groups[1].hosts[0]
        assert card.report_age_s == 10800.0
        assert card.header_text == "no report for 3h" and card.header_css == "cell-error"


# ----------------------------------------------------------------------
# Views
# ----------------------------------------------------------------------

def _card(css="cell-good", age=0.5, programs=()):
    return HostCard("hal9000", f"{P}:hal9000:report_age", css, age,
                    [ProgramRow(j, n, f"{P}:hal9000:slot:{j}:status", s, c)
                     for j, (n, s, c) in enumerate(programs)])


def _data(engine_fresh=True, cards=(), error=None):
    cfg = _config()
    hb = HeartbeatStatus("Compute engine", HEARTBEAT_NAME, engine_fresh, 1.0 if engine_fresh else 180.0)
    return ProcessPageData([GroupData(cfg.groups[0], heartbeats=[hb]),
                            GroupData(cfg.groups[1], hosts=list(cards))], error)


class TestViews:
    @pytest.mark.parametrize("hb, css, text", [
        (HeartbeatStatus("a", "a:b", True, 1.0), "cell-good", "running"),
        (HeartbeatStatus("a", "a:b", False, 180.0), "cell-error", "stopped 3m"),
        (HeartbeatStatus("a", "a:b", False, None), "cell-error", "missing"),
    ])
    def test_heartbeat_view(self, hb, css, text):
        cell = heartbeat_view(hb)
        assert (cell.css, cell.text) == (css, text)

    @pytest.mark.parametrize("css, age, text", [
        ("cell-good", 0.5, ""),
        ("cell-error", 7756043.0, "no report for 89d"),
        ("cell-error", -200.0, "report 3m ahead"),
        ("cell-error", None, "no report"),
        ("cell-nodata", None, "no data"),
    ])
    def test_host_header(self, css, age, text):
        card = _card(css, age)
        assert card.header_text == text
        assert card.header_css == (css if text else "")

    def test_counts(self):
        cards = [_card(programs=[("a", "running", "cell-good"), ("b", "terminated", "cell-error"),
                                 ("c", "running", "cell-unchecked"), ("d", "---", "cell-nodata"),
                                 ("e", "quit", "cell-warning")])]
        assert _data(cards=cards).counts == {"running": 1, "not running": 2,
                                             "not checked": 1, "no data": 1}

    def test_engine_banner(self):
        assert _data().banners() == []
        assert _data(engine_fresh=False).banners() == [ENGINE_BANNER]
        assert _data(engine_fresh=False, error="x").banners() == ["x", ENGINE_BANNER]

    def test_no_engine_banner_without_smainit_group(self):
        group = HeartbeatGroup("SLAMA", [HeartbeatProcess("Compute engine", HEARTBEAT_NAME)])
        hb = HeartbeatStatus("Compute engine", HEARTBEAT_NAME, False, 100.0)
        assert ProcessPageData([GroupData(group, heartbeats=[hb])]).banners() == []


# ----------------------------------------------------------------------
# Rendering and server
# ----------------------------------------------------------------------

class _StaticReader:
    """Reader returning fixed data."""

    def __init__(self, data):
        self.data = data

    def read(self, config):
        return self.data


def _page(tmp_path, data):
    path = tmp_path / "processes.json"
    path.write_text(json.dumps({
        "name": "Processes", "description": "Whether each critical process is running",
        "update_interval": 3, "names_refresh_s": 60,
        "groups": [{"title": "SLAMA", "type": "heartbeat",
                    "processes": [{"label": "Compute engine", "point": HEARTBEAT_NAME}]},
                   {"title": "smainit", "type": "smainit", "hosts": "hal9000", "slots": "0-2"}],
    }))
    return ProcessPage(path, _StaticReader(data))


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


class TestRendering:
    def test_body_renders(self, tmp_path):
        cards = [_card(programs=[("watchdog", "running", "cell-good"),
                                 ("tune6", "terminated", "cell-error")]),
                 HostCard("newdds", f"{P}:newdds:report_age", "cell-error", 7756043.0,
                          [ProgramRow(0, "dsm", f"{P}:newdds:slot:0:status", "running",
                                      "cell-unchecked")]),
                 HostCard("m5", f"{P}:m5:report_age", "cell-good", 1.0, [])]
        page = _page(tmp_path, _data(cards=cards))
        assert page.update_interval == 3.0
        html = server._render_generated(page, page.read())
        assert 'id="page-body" hx-swap-oob="innerHTML"' in html
        assert "running 1" in html and "not running 1" in html and "not checked 1" in html
        assert "no data 0" not in html
        assert '<td class="fault-cell cell-error">terminated</td>' in html
        assert "no report for 89d" in html
        assert "no programs reported" in html
        assert f'title="slot 1: {P}:hal9000:slot:1:status"' in html
        assert ">running</span>" in html   # the engine heartbeat

    def test_engine_banner_renders(self, tmp_path):
        page = _page(tmp_path, _data(engine_fresh=False))
        html = server._render_generated(page, page.read())
        assert ENGINE_BANNER in html and "stopped 3m" in html

    def test_load_error(self, tmp_path):
        page = ProcessPage(tmp_path / "missing.json", _StaticReader(None))
        assert page.config is None and "Could not load" in page.load_error
        assert page.read() is None and page.unavailable("x") is None
        assert "Could not load" in server._render_generated(page, None)

    def test_full_page(self, tmp_path, monkeypatch):
        page = _page(tmp_path, _data())
        monkeypatch.setitem(server.GENERATED_PAGES, "processes", page)
        html = asyncio.run(server.display_page("processes"))
        assert 'ws-connect="/ws/display/processes"' in html
        assert 'id="page-body"' in html and "<h1>Processes</h1>" in html

    def test_full_page_when_read_fails(self, tmp_path, monkeypatch):
        page = _page(tmp_path, None)

        def boom():
            raise RuntimeError("down")
        page.read = boom
        monkeypatch.setitem(server.GENERATED_PAGES, "processes", page)
        html = asyncio.run(server.display_page("processes"))
        assert server.READ_FAILED in html


class TestWebSocketPush:
    def test_pushes_body(self, tmp_path):
        page = _page(tmp_path, _data(cards=[_card(programs=[("dsm", "running", "cell-good")])]))
        page.update_interval = 0.01
        ws = _FakeWebSocket(n=2)
        asyncio.run(server._ws_generated(ws, page))
        assert len(ws.sent) == 2
        assert all('id="page-body" hx-swap-oob="innerHTML"' in m and ">dsm<" in m
                   for m in ws.sent)

    def test_read_error_becomes_banner(self, tmp_path):
        page = _page(tmp_path, None)
        page.update_interval = 0.01

        def boom():
            raise RuntimeError("down")
        page.read = boom
        ws = _FakeWebSocket(n=1)
        asyncio.run(server._ws_generated(ws, page))
        assert server.READ_FAILED in ws.sent[0]


class TestServer:
    def test_registered(self):
        page = server.GENERATED_PAGES["processes"]
        assert page.load_error is None and page.filename == "processes"
        assert page.name == "Processes"

    def test_index_lists_both_generated_pages_first(self):
        html = asyncio.run(server.index())
        faults = html.index('href="/display/faults"')
        procs = html.index('href="/display/processes"')
        assert faults < procs < html.index('href="/display/tracking"')
