"""The generated Fault System display page.

Unlike the hand-written ``conf/displays/*.json`` pages, this page is
generated from :class:`~slama.fault.faultconfig.FaultConfig` and filled
from the fault system's published snapshot (``faultsystem:state``,
:mod:`slama.fault.publish`), not from per-point pulls. A per-point page
would cost about 750 pulls per refresh and would only see validities,
so it could not tell a root fault from a consequence or a fault still
debouncing; those states exist only in the fault system's decisions.

The module has three layers:

- **Layout** (:func:`build_fault_layout`, pure): places every fault node
  in one section: the status line, the antenna grid, the host table, or
  "Other faults".
- **Reading** (:class:`FaultPageReader`): one refresh's SMAX pulls (the
  snapshot, both heartbeats, the eight ``online`` points, and slot names
  for faulted slots only), returned as :class:`FaultPageData`.
- **Views** (:func:`cell_view` and friends, pure): turn a node and the
  data into the CSS classes, text and tooltip a template draws.

:class:`FaultPage` ties them together for :mod:`slama.web.server`.
"""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from slama.fault.faultconfig import FaultConfig
from slama.fault.publish import (
    FAULT_HEARTBEAT_NAME,
    STATE_NAME,
    STATES,
    parse_snapshot,
    state_counts,
)
from slama.monitor.compute.engine import HEARTBEAT_NAME as ENGINE_HEARTBEAT_NAME
from slama.monitor.computed_verdict import computed_validity
from slama.monitor.monitorpoint import Validity

from .data_bridge import CSS_NODATA, validity_to_css

logger = logging.getLogger(__name__)

__all__ = [
    "PAGE_NAME", "AntennaGrid", "HostRow", "SlotRef", "OtherGroup", "FaultLayout",
    "build_fault_layout", "HeartbeatStatus", "FaultPageData", "FaultPageReader",
    "FaultCell", "cell_view", "slot_summary", "format_duration", "FaultPage",
]

PAGE_NAME: str = "faults"
"""str: URL name of the page (``/display/faults``)."""

_ANTENNA_RE = re.compile(r"^monitorsystem:antenna:(\d+):(.+)$")
_ACC_RE = re.compile(r"^monitorsystem:smainit:acc(\d+):(report_age|process:.+)$")
_REPORT_AGE_RE = re.compile(r"^monitorsystem:smainit:([^:]+):report_age$")
_SLOT_RE = re.compile(r"^monitorsystem:smainit:([^:]+):slot:(\d+):status$")

_ROW_LABELS: dict[str, str] = {
    "report_age": "Host",
    "process:servo": "Servo",
    "process:tune6": "Tune6",
    "drive_fault": "Drive",
    "yig1_lock_fault": "YIG1",
    "yig2_lock_fault": "YIG2",
    "gunn1_lock_fault": "Gunn1",
    "gunn2_lock_fault": "Gunn2",
}
"""dict: antenna-grid row key (the name after the antenna part) to label,
in display order. Keys not listed follow in config order, labelled by
:func:`_row_label`."""

_SEVERITY: dict[str, int] = {
    "ok": 0, "ignored": 1, "consequence": 2, "debouncing": 3, "root": 4,
}
"""dict: state to severity, for the worst state of a host's slots."""


# ----------------------------------------------------------------------
# Layout
# ----------------------------------------------------------------------

@dataclass
class AntennaGrid:
    """Antenna-by-row grid of fault nodes.

    Attributes
    ----------
    antennas : list of int
        Column antenna numbers, ascending.
    rows : list of tuple of (str, list of str or None)
        ``(label, names)`` with one canonical name per antenna column,
        ``None`` where that antenna has no such node.
    """
    antennas: list[int] = field(default_factory=list)
    rows: list[tuple[str, list[str | None]]] = field(default_factory=list)


@dataclass
class SlotRef:
    """One smainit slot node in the host table.

    Attributes
    ----------
    slot : int
        Slot number.
    node : str
        The slot's ``...:slot:{j}:status`` fault node.
    name_point : str or None
        The context point holding the program name (``...:slot:{j}:name``),
        or ``None`` if the node declares none.
    """
    slot: int
    node: str
    name_point: str | None


@dataclass
class HostRow:
    """One smainit host in the host table.

    Attributes
    ----------
    host : str
        Host name (``acc1``, ``hal9000``, ...).
    report_age : str or None
        The host's ``report_age`` fault node, if declared.
    slots : list of SlotRef
        The host's slot nodes, in config order.
    """
    host: str
    report_age: str | None
    slots: list[SlotRef] = field(default_factory=list)


@dataclass
class OtherGroup:
    """Nodes not placed elsewhere, sharing a canonical-name prefix.

    Attributes
    ----------
    prefix : str
        Second and third name components (``antenna:3``, ``array:foo``).
    names : list of str
        The nodes, in config order.
    """
    prefix: str
    names: list[str] = field(default_factory=list)


@dataclass
class FaultLayout:
    """Where each fault node is drawn.

    Every node of the config is *owned* by exactly one section. The acc
    ``report_age`` nodes are owned by the antenna grid's Host row and are
    also shown, as a reference, in the host table's state column.

    Attributes
    ----------
    heartbeat : str or None
        The engine heartbeat node (drawn in the status line).
    antennas : AntennaGrid
        The antenna grid.
    hosts : list of HostRow
        The host table, in config order.
    other : list of OtherGroup
        Nodes matched by no rule, grouped by prefix.
    """
    heartbeat: str | None = None
    antennas: AntennaGrid = field(default_factory=AntennaGrid)
    hosts: list[HostRow] = field(default_factory=list)
    other: list[OtherGroup] = field(default_factory=list)

    def owned(self) -> dict[str, list[str]]:
        """Return each section's owned nodes.

        Returns
        -------
        dict of str to list of str
            Keys ``"status"``, ``"antennas"``, ``"hosts"``, ``"other"``.
            A node owned twice, or not at all, is a layout bug; the tests
            check that the union is the config's node set, with no repeats.
        """
        antenna_nodes = [n for _, names in self.antennas.rows for n in names if n]
        acc = set(antenna_nodes)
        host_nodes = []
        for row in self.hosts:
            if row.report_age and row.report_age not in acc:
                host_nodes.append(row.report_age)
            host_nodes.extend(s.node for s in row.slots)
        return {
            "status": [self.heartbeat] if self.heartbeat else [],
            "antennas": antenna_nodes,
            "hosts": host_nodes,
            "other": [n for g in self.other for n in g.names],
        }


def _row_label(key: str) -> str:
    """Label for an antenna-grid row key not in :data:`_ROW_LABELS`.

    Parameters
    ----------
    key : str
        Name after ``monitorsystem:antenna:{i}:`` (or ``smainit:acc{i}:``).

    Returns
    -------
    str
        ``key`` without a ``_lock_fault`` / ``_fault`` suffix or
        ``process:`` prefix, with its first letter capitalised.
    """
    label = re.sub(r"(_lock)?_fault$", "", key).removeprefix("process:")
    return label[:1].upper() + label[1:]


def build_fault_layout(config: FaultConfig) -> FaultLayout:
    """Place every node of ``config`` on the page (pure, no I/O).

    Parameters
    ----------
    config : FaultConfig
        The fault-system config the page draws.

    Returns
    -------
    FaultLayout
        Rules, first match wins:

        1. the engine heartbeat → status line;
        2. ``monitorsystem:antenna:{i}:<key>`` and
           ``monitorsystem:smainit:acc{i}:{report_age,process:*}`` →
           antenna grid, row ``<key>``, column ``i``; rows in
           :data:`_ROW_LABELS` order, then others in config order;
        3. ``monitorsystem:smainit:{h}:slot:{j}:status`` and
           ``monitorsystem:smainit:{h}:report_age`` → host table, one row
           per host in config order (acc hosts included, so each host's
           slots are listed);
        4. anything else → "Other faults", grouped by prefix.
    """
    layout = FaultLayout()
    grid: dict[str, dict[int, str]] = {}
    hosts: dict[str, HostRow] = {}
    other: dict[str, OtherGroup] = {}

    def host_row(host: str) -> HostRow:
        if host not in hosts:
            hosts[host] = HostRow(host=host, report_age=None)
        return hosts[host]

    for name, node in config.nodes.items():
        if name == ENGINE_HEARTBEAT_NAME:
            layout.heartbeat = name
            continue
        m = _ANTENNA_RE.match(name) or _ACC_RE.match(name)
        if m:
            grid.setdefault(m.group(2), {})[int(m.group(1))] = name
            if m.group(2) == "report_age":
                host_row(f"acc{m.group(1)}").report_age = name
            continue
        m = _SLOT_RE.match(name)
        if m:
            name_point = next((c for c in node.context if c.endswith(":name")), None)
            host_row(m.group(1)).slots.append(
                SlotRef(slot=int(m.group(2)), node=name, name_point=name_point))
            continue
        m = _REPORT_AGE_RE.match(name)
        if m:
            host_row(m.group(1)).report_age = name
            continue
        prefix = ":".join(name.split(":")[1:3])
        other.setdefault(prefix, OtherGroup(prefix=prefix)).names.append(name)

    antennas = sorted({i for cols in grid.values() for i in cols})
    keys = [k for k in _ROW_LABELS if k in grid] + [k for k in grid if k not in _ROW_LABELS]
    layout.antennas = AntennaGrid(
        antennas=antennas,
        rows=[(_ROW_LABELS.get(k) or _row_label(k), [grid[k].get(i) for i in antennas])
              for k in keys],
    )
    layout.hosts = list(hosts.values())
    layout.other = list(other.values())
    return layout


# ----------------------------------------------------------------------
# Reading
# ----------------------------------------------------------------------

@dataclass
class HeartbeatStatus:
    """Freshness of one heartbeat point.

    Attributes
    ----------
    label : str
        Display label (``"Fault system"``, ``"Compute engine"``).
    name : str
        Canonical name of the heartbeat point.
    fresh : bool
        Whether its SMAX write timestamp is no older than the page's
        max age.
    age_s : float or None
        Seconds since that write, or ``None`` when the point is missing.
    """
    label: str
    name: str
    fresh: bool
    age_s: float | None


@dataclass
class FaultPageData:
    """Everything one refresh of the page needs.

    Attributes
    ----------
    snapshot : dict or None
        The parsed ``faultsystem:state``, or ``None`` when missing or bad.
    error : str or None
        Why ``snapshot`` is ``None`` (missing key, bad JSON, wrong version).
    fault_hb, engine_hb : HeartbeatStatus
        The two heartbeats.
    online : dict of int to bool or None
        Per antenna: ``True`` / ``False`` from ``monitorsystem:antenna:{i}:online``,
        ``None`` when that point is missing or stale (then the column is
        not dimmed).
    slot_names : dict of str to str
        Program name per faulted slot node, where it could be read.
    """
    snapshot: dict | None
    error: str | None
    fault_hb: HeartbeatStatus
    engine_hb: HeartbeatStatus
    online: dict[int, bool | None] = field(default_factory=dict)
    slot_names: dict[str, str] = field(default_factory=dict)

    @classmethod
    def unavailable(cls, error: str) -> "FaultPageData":
        """Data for a refresh that could not read SMAX at all.

        Parameters
        ----------
        error : str
            Banner text.

        Returns
        -------
        FaultPageData
            No snapshot, both heartbeats missing.
        """
        return cls(None, error,
                   HeartbeatStatus("Fault system", FAULT_HEARTBEAT_NAME, False, None),
                   HeartbeatStatus("Compute engine", ENGINE_HEARTBEAT_NAME, False, None))

    @property
    def usable(self) -> bool:
        """bool: whether cells may show the snapshot (present and fault system fresh)."""
        return self.snapshot is not None and self.fault_hb.fresh

    @property
    def counts(self) -> dict[str, int] | None:
        """dict or None: :func:`~slama.fault.publish.state_counts` of the snapshot."""
        return state_counts(self.snapshot) if self.snapshot is not None else None

    def entry(self, name: str) -> dict | None:
        """Return the snapshot entry of node ``name``, or ``None``.

        Parameters
        ----------
        name : str
            Canonical name of a fault node.

        Returns
        -------
        dict or None
            The node's snapshot entry, or ``None`` when the snapshot is
            missing or does not list the node.
        """
        if self.snapshot is None:
            return None
        return self.snapshot.get("nodes", {}).get(name)

    def banners(self) -> list[str]:
        """Return the page's warning banners, most serious first.

        Returns
        -------
        list of str
            Empty when both processes are running and the snapshot parsed.
        """
        out = []
        if self.error:
            out.append(self.error)
        elif not self.fault_hb.fresh:
            tick = self.snapshot.get("tick") if self.snapshot else None
            when = f"; states as of {_utc(tick)}" if tick is not None else ""
            out.append(f"Fault system not running{when}")
        if not self.engine_hb.fresh:
            out.append("Compute engine not running")
        return out


def _pull(client, name: str):
    """Pull one canonical name; ``None`` on any error.

    Parameters
    ----------
    client : SmaxRedisClient
        Connected client.
    name : str
        ``table:key`` canonical name.

    Returns
    -------
    SmaxVarBase or None
        The pulled value (with ``.timestamp``), or ``None``.
    """
    table, key = name.rsplit(":", 1)
    try:
        return client.smax_pull(table, key)
    except Exception:
        logger.debug("fault page: pull of %s failed", name, exc_info=True)
        return None


class FaultPageReader:
    """Pull one refresh's data for the fault page.

    Parameters
    ----------
    get_client : callable
        Returns a connected ``SmaxRedisClient`` or ``None`` (e.g.
        :meth:`DataBridge._get_client <slama.web.data_bridge.DataBridge._get_client>`,
        so the page shares the web server's lazy connection).
    max_age_s : float
        Maximum age of a heartbeat's (and an ``online`` point's) SMAX
        write timestamp to count as fresh; ``inf`` disables the check.
    clock : callable, optional
        Wall clock, epoch seconds; defaults to :func:`time.time`.
    """

    def __init__(self, get_client: Callable, max_age_s: float,
                 clock: Callable[[], float] = time.time):
        self._get_client = get_client
        self._max_age_s = max_age_s
        self._clock = clock

    def _heartbeat(self, client, label: str, name: str, now: float) -> HeartbeatStatus:
        """Judge one heartbeat by its SMAX write timestamp, not its value.

        Under ``--as-of`` the value is the replayed epoch, so gating on
        it would always read stale; the write timestamp is when the
        process actually ran.
        """
        result = _pull(client, name) if client is not None else None
        ts = getattr(result, "timestamp", None)
        if ts is None:
            return HeartbeatStatus(label, name, False, None)
        age = now - ts.timestamp()
        return HeartbeatStatus(label, name, age <= self._max_age_s, age)

    def read(self, layout: FaultLayout) -> FaultPageData:
        """Pull the snapshot, heartbeats, ``online`` points and slot names.

        Parameters
        ----------
        layout : FaultLayout
            The page layout; supplies the antennas and the slot name points.

        Returns
        -------
        FaultPageData
            Never raises: a missing server, key or bad snapshot becomes
            ``snapshot=None`` with ``error`` set, and stale heartbeats.
        """
        now = self._clock()
        client = self._get_client()
        fault_hb = self._heartbeat(client, "Fault system", FAULT_HEARTBEAT_NAME, now)
        engine_hb = self._heartbeat(client, "Compute engine", ENGINE_HEARTBEAT_NAME, now)
        if client is None:
            return FaultPageData(None, "SMAX server unreachable", fault_hb, engine_hb)

        snapshot, error = None, None
        raw = _pull(client, STATE_NAME)
        if raw is None:
            error = f"{STATE_NAME} not found: has the fault system run?"
        else:
            try:
                snapshot = parse_snapshot(str(raw))
            except ValueError as exc:
                error = str(exc)
        data = FaultPageData(snapshot, error, fault_hb, engine_hb)

        for i in layout.antennas.antennas:
            name = f"monitorsystem:antenna:{i}:online"
            result = _pull(client, name)
            validity = computed_validity(result, Validity.VALID_GOOD.value, now,
                                         self._max_age_s)
            try:
                data.online[i] = (None if validity is Validity.INVALID_NO_DATA
                                  else bool(int(result)))
            except (TypeError, ValueError):
                data.online[i] = None

        if snapshot is not None:
            for row in layout.hosts:
                for slot in row.slots:
                    entry = data.entry(slot.node)
                    if slot.name_point and entry and entry["state"] != "ok":
                        result = _pull(client, slot.name_point)
                        if result is not None:
                            data.slot_names[slot.node] = str(result)
        return data


# ----------------------------------------------------------------------
# Views
# ----------------------------------------------------------------------

@dataclass
class FaultCell:
    """What a template draws for one fault node.

    Attributes
    ----------
    css : str
        Space-separated CSS classes.
    text : str
        Cell text: the fault's duration, ``"ign"``, ``"---"`` or empty.
    title : str
        Tooltip.
    state : str or None
        The node's state, or ``None`` when no data is shown.
    """
    css: str
    text: str
    title: str
    state: str | None


def _utc(epoch: float | None) -> str:
    """Format an epoch as ``YYYY-MM-DD HH:MM:SS UTC`` (``"-"`` for ``None``)."""
    if epoch is None:
        return "-"
    return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def format_duration(seconds: float | None) -> str:
    """Format a fault duration compactly.

    Parameters
    ----------
    seconds : float or None
        Duration; negative values are clamped to zero.

    Returns
    -------
    str
        ``""`` for ``None``; otherwise ``"45s"`` under 2 minutes,
        ``"12m"`` under 2 hours, ``"3h"`` under 2 days, else ``"2d"``.
    """
    if seconds is None:
        return ""
    s = max(0.0, float(seconds))
    if s < 120:
        return f"{int(s)}s"
    if s < 7200:
        return f"{int(s // 60)}m"
    if s < 172800:
        return f"{int(s // 3600)}h"
    return f"{int(s // 86400)}d"


_warned_missing: set[str] = set()


def cell_view(name: str | None, data: FaultPageData,
              offarray: bool = False) -> FaultCell:
    """Build the view of one fault node.

    Parameters
    ----------
    name : str or None
        Canonical name, or ``None`` for an empty grid position.
    data : FaultPageData
        This refresh's data.
    offarray : bool, optional
        Dim the cell (its antenna is not online).

    Returns
    -------
    FaultCell
        - empty position: blank, class ``fault-empty``;
        - snapshot unusable, or node missing from it: ``---``, no-data grey;
        - ``root``: bold red; ``consequence``: dimmed red; ``debouncing``:
          amber; ``ignored``: grey with a red border, text ``ign``; the
          text of the first three is the duration ``tick - since`` (the
          snapshot's clock, so a replay does not show months);
        - ``ok``: coloured by its validity, blank.
    """
    if name is None:
        return FaultCell("fault-empty", "", "", None)
    dim = " fault-offarray" if offarray else ""
    entry = data.entry(name) if data.usable else None
    if entry is None:
        if data.usable and name not in _warned_missing:
            _warned_missing.add(name)
            logger.warning("fault page: %s is not in %s (config mismatch?)",
                           name, STATE_NAME)
        return FaultCell(CSS_NODATA + dim, "---", name, None)

    state = entry.get("state")
    validity = entry.get("validity", "")
    since = entry.get("since")
    tick = data.snapshot.get("tick")
    duration = format_duration(tick - since) if since is not None and tick is not None else ""
    title = f"{name}\n{state} ({validity})"
    if since is not None:
        title += f"\nsince {_utc(since)}"
    if entry.get("hidden_by"):
        title += "\nhidden by " + ", ".join(entry["hidden_by"])

    if state == "root":
        css, text = "cell-error fault-root", duration
    elif state == "consequence":
        css, text = "fault-consequence", duration
    elif state == "debouncing":
        css, text = "cell-warning fault-debouncing", duration
    elif state == "ignored":
        css, text = "fault-ignored", "ign"
    else:
        try:
            css = validity_to_css(Validity[validity])
        except KeyError:
            css = CSS_NODATA
        text = ""
    return FaultCell(css + dim, text, title, state)


def slot_summary(row: HostRow, data: FaultPageData) -> tuple[FaultCell, list[dict]]:
    """Summarise a host's slots: a count cell and the faulted-slot list.

    Parameters
    ----------
    row : HostRow
        The host.
    data : FaultPageData
        This refresh's data.

    Returns
    -------
    tuple of (FaultCell, list of dict)
        The cell's text is the number of slots not ``ok`` (blank when
        none), styled like the worst of them; the list has one dict per
        such slot with keys ``slot``, ``name`` (program name or ``""``)
        and ``cell`` (its :func:`cell_view`).
    """
    if not data.usable:
        return FaultCell(CSS_NODATA, "---", "", None), []
    faulted = []
    for slot in row.slots:
        cell = cell_view(slot.node, data)
        if cell.state not in (None, "ok"):
            faulted.append({"slot": slot.slot, "name": data.slot_names.get(slot.node, ""),
                            "cell": cell})
    if not faulted:
        return FaultCell("cell-good", "", f"{row.host}: {len(row.slots)} slots ok", "ok"), []
    worst = max(faulted, key=lambda f: _SEVERITY.get(f["cell"].state, 0))["cell"]
    css = worst.css
    return FaultCell(css, str(len(faulted)), f"{row.host}: {len(faulted)} slot(s) faulted",
                     worst.state), faulted


# ----------------------------------------------------------------------
# The page
# ----------------------------------------------------------------------

class FaultPage:
    """The fault page as the web server sees it.

    Parameters
    ----------
    faults_json : str or pathlib.Path
        Path to ``faults.json``. A load failure is kept (see
        :attr:`load_error`) rather than raised, so the other pages work.
    reader : FaultPageReader
        Pulls each refresh's data.

    Attributes
    ----------
    name : str
        Card title on the index page.
    description : str
        Card text.
    filename : str
        URL name, :data:`PAGE_NAME`.
    update_interval : float
        Refresh interval, the config's ``interval_s`` (2 s if unloaded).
    layout : FaultLayout or None
        ``None`` when the config failed to load.
    load_error : str or None
        Why the config failed to load.
    """

    name = "Fault System"
    description = "Fault DAG: root faults, consequences and debouncing, by antenna and host"
    filename = PAGE_NAME

    def __init__(self, faults_json: str | Path, reader: FaultPageReader):
        self.reader = reader
        self.layout: FaultLayout | None = None
        self.load_error: str | None = None
        self.update_interval: float = 2.0
        try:
            config = FaultConfig.from_file(faults_json)
        except Exception as exc:
            logger.exception("fault page: loading %s failed", faults_json)
            self.load_error = f"Could not load {faults_json}: {exc}"
            return
        self.layout = build_fault_layout(config)
        self.update_interval = float(config.default_interval_s)

    def read(self) -> FaultPageData | None:
        """Pull one refresh's data (blocking; run it in a thread).

        Returns
        -------
        FaultPageData or None
            ``None`` when the config failed to load.
        """
        if self.layout is None:
            return None
        return self.reader.read(self.layout)

    def context(self, data: FaultPageData | None) -> dict:
        """Template variables for ``fault_page.html`` and its sections.

        Parameters
        ----------
        data : FaultPageData or None
            From :meth:`read`.

        Returns
        -------
        dict
            ``page``, ``layout``, ``data``, ``load_error``, ``states``
            and the view helpers ``cell_view`` and ``slot_summary``.
        """
        return {
            "page": self, "layout": self.layout, "data": data,
            "load_error": self.load_error, "states": STATES,
            "cell_view": cell_view, "slot_summary": slot_summary,
            "format_duration": format_duration, "utc": _utc,
        }
