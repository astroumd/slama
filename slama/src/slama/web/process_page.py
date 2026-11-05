"""The generated Processes display page.

Shows whether each critical process is running. The page is defined by
``conf/processes.json`` (:class:`ProcessConfig`), a list of groups drawn
in file order. There are two kinds of group:

- ``heartbeat``: processes that write a heartbeat point (the compute
  engine, the fault system), each judged by the point's SMAX write time,
  as on the Fault System page (:func:`~slama.web.fault_page.heartbeat_status`).
- ``smainit``: every program smainit runs on a list of hosts, read from
  the compute engine's ``monitorsystem:smainit:{h}:slot:{j}:status`` and
  ``:name`` points and each host's ``report_age``.

A hand-written ``conf/displays/*.json`` page cannot draw the smainit
group, because slots are positional: which program is in which slot is
only known from the ``name`` points.

The module has three layers, as :mod:`slama.web.fault_page`:

- **Config** (:class:`ProcessConfig`): loads and validates the file.
- **Reading** (:class:`ProcessPageReader`): one refresh's pulls, returned
  as :class:`ProcessPageData`. Program names change only when smainit is
  reconfigured, so they are cached and re-read every ``names_refresh_s``;
  each refresh pulls only the named slots' status (about 350 pulls on
  site rather than about 660).
- **Views** (:func:`heartbeat_view` and the :class:`HostCard` properties,
  pure): the CSS classes and text a template draws.

:class:`ProcessPage` ties them together for :mod:`slama.web.server`.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from slama.monitor.compute.engine import HEARTBEAT_NAME as ENGINE_HEARTBEAT_NAME
from slama.monitor.monitorsystem import _parse_index_set

from .data_bridge import (
    CSS_ERROR,
    CSS_GOOD,
    CSS_NODATA,
    CSS_UNCHECKED,
    CSS_WARNING,
    CellData,
)
from .fault_page import (
    HeartbeatStatus,
    format_duration,
    heartbeat_status,
    pull_or_none,
)

logger = logging.getLogger(__name__)

__all__ = [
    "PAGE_NAME", "SMAINIT_PREFIX", "HeartbeatProcess", "HeartbeatGroup", "SmainitGroup",
    "ProcessConfig", "ProgramRow", "program_row", "HostCard", "GroupData", "ProcessPageData",
    "ProcessPageReader", "ProcessCell", "heartbeat_view", "ProcessPage",
]

PAGE_NAME: str = "processes"
"""str: URL name of the page (``/display/processes``)."""

SMAINIT_PREFIX: str = "monitorsystem:smainit"
"""str: table prefix of the compute engine's smainit points."""

ENGINE_BANNER: str = "Compute engine not running: program states are not being updated"
"""str: banner shown when the engine heartbeat on the page is stale."""

_COUNT_KEYS: dict[str, str] = {
    CSS_GOOD: "running",
    CSS_ERROR: "not running",
    CSS_WARNING: "not running",
    CSS_UNCHECKED: "not checked",
    CSS_NODATA: "unknown",
}
"""dict: a known program cell's CSS class to its count-line category.
Programs whose state is unknown (:attr:`ProgramRow.unknown`) count as
``"unknown"`` whatever their class."""

COUNT_ORDER: tuple[str, ...] = ("running", "not running", "not checked", "unknown")
"""tuple of str: count-line categories, in display order."""

NO_REPORT_TEXT: str = "no report"
"""str: program text when its host has stopped reporting."""

NO_DATA_TEXT: str = "---"
"""str: program text when its status cannot be read (missing point, or the
compute engine stopped)."""


# ----------------------------------------------------------------------
# Config
# ----------------------------------------------------------------------

@dataclass
class HeartbeatProcess:
    """One process judged by its heartbeat point.

    Attributes
    ----------
    label : str
        Display label (``"Compute engine"``).
    point : str
        Canonical name of the heartbeat point.
    """
    label: str
    point: str


@dataclass
class HeartbeatGroup:
    """A ``"type": "heartbeat"`` group.

    Attributes
    ----------
    title : str
        Section heading.
    processes : list of HeartbeatProcess
        In file order.
    """
    title: str
    processes: list[HeartbeatProcess]
    type: str = "heartbeat"


@dataclass
class SmainitGroup:
    """A ``"type": "smainit"`` group.

    Attributes
    ----------
    title : str
        Section heading.
    hosts : list of str
        smainit hosts, in file order (one card each).
    slots : list of int
        Slot numbers read on every host.
    """
    title: str
    hosts: list[str]
    slots: list[int]
    type: str = "smainit"


def _require_str(entry: dict, key: str, where: str) -> str:
    """Return ``entry[key]`` as a non-empty string, else raise.

    Parameters
    ----------
    entry : dict
        A config object.
    key : str
        Required key.
    where : str
        Prefix for the error message.

    Returns
    -------
    str
        The value.

    Raises
    ------
    ValueError
        If the key is missing, or its value is not a non-empty string.
    """
    value = entry.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{where}: {key!r} must be a non-empty string, got {value!r}")
    return value


@dataclass
class ProcessConfig:
    """The Processes page definition, from ``conf/processes.json``.

    Attributes
    ----------
    name : str
        Page title and index-card name.
    description : str
        Index-card text.
    update_interval : float
        Seconds between WebSocket pushes.
    names_refresh_s : float
        Seconds between re-reads of the smainit program names.
    groups : list of HeartbeatGroup or SmainitGroup
        In file order.
    """
    name: str
    description: str
    update_interval: float
    names_refresh_s: float
    groups: list[HeartbeatGroup | SmainitGroup]

    @classmethod
    def from_dict(cls, raw: dict, source: str = "processes.json") -> "ProcessConfig":
        """Build and validate a config from parsed JSON.

        Parameters
        ----------
        raw : dict
            The parsed file.
        source : str, optional
            File name for error messages.

        Returns
        -------
        ProcessConfig
            The config.

        Raises
        ------
        ValueError
            If a field is missing or malformed. Group errors name the
            group by index and title.
        """
        if not isinstance(raw, dict):
            raise ValueError(f"{source}: top level must be an object")
        update_interval = raw.get("update_interval", 2)
        names_refresh_s = raw.get("names_refresh_s", 60)
        for key, value in (("update_interval", update_interval),
                           ("names_refresh_s", names_refresh_s)):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
                raise ValueError(f"{source}: {key!r} must be a positive number, got {value!r}")
        groups_raw = raw.get("groups")
        if not isinstance(groups_raw, list) or not groups_raw:
            raise ValueError(f"{source}: 'groups' must be a non-empty list")

        groups: list[HeartbeatGroup | SmainitGroup] = []
        for k, g in enumerate(groups_raw):
            if not isinstance(g, dict):
                raise ValueError(f"{source}: group {k} must be an object")
            where = f"{source}: group {k} ({g.get('title')!r})"
            title = _require_str(g, "title", where)
            kind = g.get("type")
            if kind == "heartbeat":
                procs = g.get("processes")
                if not isinstance(procs, list) or not procs:
                    raise ValueError(f"{where}: 'processes' must be a non-empty list")
                processes = []
                for p in procs:
                    if not isinstance(p, dict):
                        raise ValueError(f"{where}: each process must be an object, got {p!r}")
                    processes.append(HeartbeatProcess(_require_str(p, "label", where),
                                                      _require_str(p, "point", where)))
                groups.append(HeartbeatGroup(title, processes))
            elif kind == "smainit":
                try:
                    hosts = _parse_index_set(g.get("hosts"))
                    slots = [int(s) for s in _parse_index_set(g.get("slots"))]
                except ValueError as exc:
                    raise ValueError(f"{where}: {exc}") from None
                groups.append(SmainitGroup(title, hosts, slots))
            else:
                raise ValueError(f"{where}: unknown type {kind!r} "
                                 "(expected 'heartbeat' or 'smainit')")
        return cls(
            name=raw.get("name", "Processes"),
            description=raw.get("description", ""),
            update_interval=float(update_interval),
            names_refresh_s=float(names_refresh_s),
            groups=groups,
        )

    @classmethod
    def from_file(cls, path: str | Path) -> "ProcessConfig":
        """Load and validate ``processes.json``.

        Parameters
        ----------
        path : str or pathlib.Path
            The file.

        Returns
        -------
        ProcessConfig
            The config.

        Raises
        ------
        OSError
            If the file cannot be read.
        ValueError
            If it is not valid JSON or fails validation.
        """
        path = Path(path)
        try:
            raw = json.loads(path.read_text())
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path.name}: {exc}") from None
        return cls.from_dict(raw, source=path.name)


# ----------------------------------------------------------------------
# Reading
# ----------------------------------------------------------------------

@dataclass
class ProgramRow:
    """One named smainit slot on a host card.

    Attributes
    ----------
    slot : int
        Slot number.
    name : str
        Program name.
    point : str
        The slot's ``status`` canonical name.
    status : str
        Text to draw: the status label (``running``, ``terminated``, ...)
        while it is current, else :data:`NO_REPORT_TEXT` or
        :data:`NO_DATA_TEXT`.
    css : str
        CSS class to draw it with.
    unknown : bool, optional
        True when the program's current state is unknown: its host has
        stopped reporting, or its status has no data. A stale label must
        never read as "running", so it is replaced.
    last_status : str or None, optional
        For an unknown program, the last label read (for the tooltip), if
        any.
    """
    slot: int
    name: str
    point: str
    status: str
    css: str
    unknown: bool = False
    last_status: str | None = None


def program_row(slot: int, name: str, point: str, cell: CellData,
                host_stale: bool) -> ProgramRow:
    """Build one program's row, replacing a label that is not current.

    Parameters
    ----------
    slot : int
        Slot number.
    name : str
        Program name.
    point : str
        The slot's ``status`` canonical name.
    cell : CellData
        ``fetch_cell(point)``.
    host_stale : bool
        Whether the host's ``report_age`` says it has stopped reporting.

    Returns
    -------
    ProgramRow
        - host stale: :data:`NO_REPORT_TEXT`, grey (not checked), unknown;
        - status no data (point missing, or the compute engine stopped):
          :data:`NO_DATA_TEXT`, no-data grey, unknown;
        - otherwise the label, coloured by its validity.

        An unknown row keeps the label read in ``last_status``.
    """
    last = cell.value if cell.value != NO_DATA_TEXT else None
    if host_stale:
        return ProgramRow(slot, name, point, NO_REPORT_TEXT, CSS_UNCHECKED, True, last)
    if cell.css_class == CSS_NODATA:
        return ProgramRow(slot, name, point, NO_DATA_TEXT, CSS_NODATA, True, last)
    return ProgramRow(slot, name, point, cell.value, cell.css_class)


@dataclass
class HostCard:
    """One smainit host's card.

    Attributes
    ----------
    host : str
        Host name.
    report_point : str
        The host's ``report_age`` canonical name.
    report_css : str
        Validity CSS class of ``report_age``: good while the host reports,
        error when its report is more than 70 s old (or ahead), no-data
        when missing or the engine is stopped.
    report_age_s : float or None
        Seconds since the host's last report, when readable.
    programs : list of ProgramRow
        Named slots, in slot order.
    """
    host: str
    report_point: str
    report_css: str
    report_age_s: float | None
    programs: list[ProgramRow] = field(default_factory=list)

    @property
    def stale(self) -> bool:
        """bool: whether ``report_age`` says the host has stopped reporting.

        No data (missing point, or the compute engine stopped) is not
        stale: whether the host reports is then unknown.
        """
        return self.report_css in (CSS_ERROR, CSS_WARNING)

    @property
    def header_text(self) -> str:
        """str: reporting state beside the host name; blank while reporting."""
        if self.report_css == CSS_NODATA:
            return "no data"
        if self.stale:
            if self.report_age_s is None:
                return "no report"
            if self.report_age_s < 0:
                return f"report {format_duration(-self.report_age_s)} ahead"
            return f"no report for {format_duration(self.report_age_s)}"
        return ""

    @property
    def header_css(self) -> str:
        """str: CSS class of :attr:`header_text` (blank while reporting)."""
        return self.report_css if self.header_text else ""


@dataclass
class GroupData:
    """One group's data for one refresh.

    Attributes
    ----------
    group : HeartbeatGroup or SmainitGroup
        The config group.
    heartbeats : list of HeartbeatStatus
        For a heartbeat group, one per process; else empty.
    hosts : list of HostCard
        For an smainit group, one per host; else empty.
    """
    group: HeartbeatGroup | SmainitGroup
    heartbeats: list[HeartbeatStatus] = field(default_factory=list)
    hosts: list[HostCard] = field(default_factory=list)


@dataclass
class ProcessPageData:
    """Everything one refresh of the page needs.

    Attributes
    ----------
    groups : list of GroupData
        In config order.
    error : str or None
        Banner for a refresh that could not reach SMAX.
    """
    groups: list[GroupData] = field(default_factory=list)
    error: str | None = None

    @property
    def counts(self) -> dict[str, int]:
        """dict of str to int: smainit programs per :data:`COUNT_ORDER` category.

        Unknown programs (stale host, or no data) count as ``"unknown"``,
        never under the label they last showed.
        """
        out = dict.fromkeys(COUNT_ORDER, 0)
        for g in self.groups:
            for card in g.hosts:
                for prog in card.programs:
                    key = "unknown" if prog.unknown else _COUNT_KEYS.get(prog.css, "not checked")
                    out[key] += 1
        return out

    @property
    def hosts_not_reporting(self) -> int:
        """int: smainit hosts whose report is stale (:attr:`HostCard.stale`)."""
        return sum(card.stale for g in self.groups for card in g.hosts)

    @property
    def has_programs(self) -> bool:
        """bool: whether the page has an smainit group (so a count line)."""
        return any(isinstance(g.group, SmainitGroup) for g in self.groups)

    def banners(self) -> list[str]:
        """Return the page's warning banners, most serious first.

        Returns
        -------
        list of str
            ``error`` if set, then :data:`ENGINE_BANNER` when the page has
            an smainit group and the engine heartbeat it shows is stale.
        """
        out = [self.error] if self.error else []
        if self.has_programs:
            for g in self.groups:
                for hb in g.heartbeats:
                    if hb.name == ENGINE_HEARTBEAT_NAME and not hb.fresh:
                        out.append(ENGINE_BANNER)
                        return out
        return out


class ProcessPageReader:
    """Pull one refresh's data for the Processes page.

    Parameters
    ----------
    get_client : callable
        Returns a connected ``SmaxRedisClient`` or ``None`` (the web
        server's :meth:`DataBridge._get_client
        <slama.web.data_bridge.DataBridge._get_client>`).
    fetch_cell : callable
        ``fetch_cell(canonical_name) -> CellData``, normally
        :meth:`DataBridge.fetch_cell
        <slama.web.data_bridge.DataBridge.fetch_cell>`: it applies the
        computed-point gate (pushed validity, trusted only while the
        point's write time is fresh). A program whose status then has no
        data, or whose host has stopped reporting, has its label replaced
        (:func:`program_row`), so a stale "running" is never shown.
    max_age_s : float
        Heartbeat freshness limit, seconds; ``inf`` disables the check.
    clock : callable, optional
        Wall clock, epoch seconds; defaults to :func:`time.time`. Also
        times the names cache.
    """

    def __init__(self, get_client: Callable, fetch_cell: Callable[[str], CellData],
                 max_age_s: float, clock: Callable[[], float] = time.time):
        self._get_client = get_client
        self._fetch_cell = fetch_cell
        self._max_age_s = max_age_s
        self._clock = clock
        self._names: dict[str, dict[int, str]] = {}
        self._names_at: float | None = None

    def _refresh_names(self, client, config: ProcessConfig, now: float) -> None:
        """Re-read every smainit slot's program name, if due.

        Empty names (unused slots) are dropped. The new cache replaces the
        old in one assignment, so concurrent readers (one per viewer) see
        either. A read in which no name point could be pulled at all is
        not cached, so the next refresh tries again.

        Parameters
        ----------
        client : SmaxRedisClient or None
            Connected client; ``None`` skips the refresh.
        config : ProcessConfig
            The page config.
        now : float
            Current wall-clock time, epoch seconds.
        """
        if client is None:
            return
        if self._names_at is not None and now - self._names_at < config.names_refresh_s:
            return
        names: dict[str, dict[int, str]] = {}
        pulled = 0
        for group in config.groups:
            if not isinstance(group, SmainitGroup):
                continue
            for host in group.hosts:
                for slot in group.slots:
                    result = pull_or_none(client, f"{SMAINIT_PREFIX}:{host}:slot:{slot}:name")
                    if result is None:
                        continue
                    pulled += 1
                    name = str(result).strip()
                    if name:
                        names.setdefault(host, {})[slot] = name
        if pulled:
            self._names = names
            self._names_at = now

    def _host_card(self, host: str) -> HostCard:
        """Read one host's ``report_age`` and its named slots' status.

        Parameters
        ----------
        host : str
            smainit host.

        Returns
        -------
        HostCard
            Programs from the names cache, in slot order.
        """
        report_point = f"{SMAINIT_PREFIX}:{host}:report_age"
        report = self._fetch_cell(report_point)
        try:
            age = None if report.css_class == CSS_NODATA else float(report.value)
        except (TypeError, ValueError):
            age = None
        card = HostCard(host, report_point, report.css_class, age)
        for slot, name in sorted(self._names.get(host, {}).items()):
            point = f"{SMAINIT_PREFIX}:{host}:slot:{slot}:status"
            card.programs.append(
                program_row(slot, name, point, self._fetch_cell(point), card.stale))
        return card

    def read(self, config: ProcessConfig) -> ProcessPageData:
        """Pull the heartbeats, host reports and program statuses.

        Parameters
        ----------
        config : ProcessConfig
            The page config.

        Returns
        -------
        ProcessPageData
            Never raises: a missing server or key becomes missing
            heartbeats and no-data cells, with ``error`` set when the
            server is unreachable.
        """
        now = self._clock()
        client = self._get_client()
        self._refresh_names(client, config, now)
        data = ProcessPageData(error=None if client is not None else "SMAX server unreachable")
        for group in config.groups:
            gd = GroupData(group)
            if isinstance(group, HeartbeatGroup):
                gd.heartbeats = [heartbeat_status(client, p.label, p.point, now, self._max_age_s)
                                 for p in group.processes]
            else:
                gd.hosts = [self._host_card(h) for h in group.hosts]
            data.groups.append(gd)
        return data


# ----------------------------------------------------------------------
# Views
# ----------------------------------------------------------------------

@dataclass
class ProcessCell:
    """What a template draws for one heartbeat process.

    Attributes
    ----------
    css : str
        CSS class.
    text : str
        ``running``, ``stopped 3m`` or ``missing``.
    title : str
        Tooltip.
    """
    css: str
    text: str
    title: str


def heartbeat_view(hb: HeartbeatStatus) -> ProcessCell:
    """Build the view of one heartbeat process.

    Parameters
    ----------
    hb : HeartbeatStatus
        From :func:`~slama.web.fault_page.heartbeat_status`.

    Returns
    -------
    ProcessCell
        Green ``running`` while fresh; red ``stopped <age>`` when stale;
        red ``missing`` when the point is absent.
    """
    if hb.age_s is None:
        return ProcessCell(CSS_ERROR, "missing", f"{hb.name}: not found")
    age = format_duration(hb.age_s)
    if hb.fresh:
        return ProcessCell(CSS_GOOD, "running", f"{hb.name}: written {age} ago")
    return ProcessCell(CSS_ERROR, f"stopped {age}", f"{hb.name}: last written {age} ago")


# ----------------------------------------------------------------------
# The page
# ----------------------------------------------------------------------

class ProcessPage:
    """The Processes page as the web server sees it.

    Parameters
    ----------
    processes_json : str or pathlib.Path
        Path to ``processes.json``. A load failure is kept (see
        :attr:`load_error`) rather than raised, so the other pages work.
    reader : ProcessPageReader
        Pulls each refresh's data.

    Attributes
    ----------
    name, description : str
        Index card title and text, from the config.
    filename : str
        URL name, :data:`PAGE_NAME`.
    update_interval : float
        Refresh interval, from the config (2 s if unloaded).
    config : ProcessConfig or None
        ``None`` when the config failed to load.
    load_error : str or None
        Why the config failed to load.
    page_template, body_template : str
        The full-page template and the body fragment pushed over the
        WebSocket (the generated-page interface of :mod:`slama.web.server`).
    """

    filename = PAGE_NAME
    page_template = "process_page.html"
    body_template = "components/process_sections.html"

    def __init__(self, processes_json: str | Path, reader: ProcessPageReader):
        self.reader = reader
        self.config: ProcessConfig | None = None
        self.load_error: str | None = None
        self.name = "Processes"
        self.description = "Whether each critical process is running"
        self.update_interval: float = 2.0
        try:
            self.config = ProcessConfig.from_file(processes_json)
        except Exception as exc:
            logger.exception("process page: loading %s failed", processes_json)
            self.load_error = f"Could not load {processes_json}: {exc}"
            return
        self.name = self.config.name
        self.description = self.config.description
        self.update_interval = self.config.update_interval

    def read(self) -> ProcessPageData | None:
        """Pull one refresh's data (blocking; run it in a thread).

        Returns
        -------
        ProcessPageData or None
            ``None`` when the config failed to load.
        """
        if self.config is None:
            return None
        return self.reader.read(self.config)

    def unavailable(self, message: str) -> ProcessPageData | None:
        """Data to draw when a refresh could not read SMAX at all.

        Parameters
        ----------
        message : str
            Banner text.

        Returns
        -------
        ProcessPageData or None
            ``None`` when the config failed to load (its own banner shows),
            else no groups and ``error=message``.
        """
        if self.load_error is not None:
            return None
        return ProcessPageData(error=message)

    def context(self, data: ProcessPageData | None) -> dict:
        """Template variables for ``process_page.html`` and its sections.

        Parameters
        ----------
        data : ProcessPageData or None
            From :meth:`read` or :meth:`unavailable`.

        Returns
        -------
        dict
            ``page``, ``data``, ``load_error``, ``count_order`` and the
            view helper ``heartbeat_view``.
        """
        return {
            "page": self, "data": data, "load_error": self.load_error,
            "count_order": COUNT_ORDER, "heartbeat_view": heartbeat_view,
        }
