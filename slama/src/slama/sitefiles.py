"""Parsers for the observatory site files under ``/global/configFiles``.

Each parser ports one C reader and keeps its quirks, so SLAMA reaches
the same conclusions as the curses monitor from the same file. Paths
are spelled exactly as in the C headers and resolved through
:func:`slama.site_paths.site_path`, so the same code reads the live
files on-site and the ``site/`` mirror offsite.

A parser returns ``None`` (after logging a warning) when its file is
missing; the caller decides whether that is fatal. Antenna numbers are
the 1-based SMA numbers 1-8 throughout.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import IntEnum

from slama.site_paths import site_path


logger = logging.getLogger(__name__)


SMA_N_ANTENNAS: int = 8
"""``smaglobal.h`` ``SMA_N_ANTENNAS``."""

RXTYPE_CONFIG_FILE: str = "/global/configFiles/rxtype.conf"
"""``rxtype.h`` ``RXTYPE_CONFIG_FILE``."""

LOADTYPE_CONFIG_FILE: str = "/global/configFiles/loadtype.conf"
"""``loadtype.h`` ``LOADTYPE_CONFIG_FILE``."""

DEWAR_SENSORS_FILE: str = "/global/configFiles/dewarTemp.conf"
"""``dewarpage.c`` ``DEWAR_SENSORS_FILE``."""

WSMA_SELECT_FILE: str = "/global/configFiles/wselect.conf"
"""``wsma.h`` ``WSMA_SELECT_FILE``."""

SMOKE_IGNORE_FILE: str = "/global/configFiles/fire/ignoreAntSmoking.txt"
"""``arrayMonitor.c`` ``SMOKE_FILE``."""

WSMA_SELECTOR_POSITIONS: int = 4
"""``wsma.c:21`` ``WSMA_SELECTOR_POSITIONS``: selector wheel positions 1-4."""

WSMA_SELECTIONS: str = "LHGD"
"""``wsma.h`` ``WSMA_SELECT_{LO,HI,GRID,DIPLEX}``: valid ``wselect.conf`` codes."""

DEWAR_TEMP_77K_CHANNEL: int = 1
"""``antMonitor.h`` ``DEWAR_TEMP_77K_CHANNEL`` (0) as a 1-based channel."""

DEWAR_TEMP_12K_CHANNEL: int = 2
"""``antMonitor.h`` ``DEWAR_TEMP_12K_CHANNEL`` (1) as a 1-based channel."""

DEWAR_TEMP_4K_CHANNEL: int = 3
"""``antMonitor.h`` ``DEWAR_TEMP_4K_CHANNEL`` (2) as a 1-based channel."""

DEWAR_TEMP_DEFAULT_4K_LIMIT: float = 5.2
"""``antMonitor.h`` ``DEWAR_TEMP_DEFAULT_4K_LIMIT`` in K."""

DEWAR_N_CHANNELS: int = 16
"""Lakeshore channels per antenna (two 8-channel units)."""


N_RX_TYPES: int = 2
"""``rxtype.h`` ``N_RX_TYPES`` (= ``loadtype.h`` ``N_LOAD_TYPES``): type codes >= this are rejected."""


class RxType(IntEnum):
    """Receiver / ambient-load assembly type.

    One enum serves both files: ``rxtype.h`` ``enum rx_type`` and
    ``loadtype.h`` ``enum load_type`` have identical values.
    """

    NONE = -1
    TUNE6 = 0
    WSMA = 1


@dataclass(frozen=True)
class DewarSensors:
    """One antenna's ``dewarTemp.conf`` row, with the C defaults applied.

    Attributes
    ----------
    ch77, ch12, ch4 : int
        1-based Lakeshore channels (1-16) of the 77K, 12K and 4K stages.
    limit4k : float
        4K-stage alarm limit in K.
    """

    ch77: int = DEWAR_TEMP_77K_CHANNEL
    ch12: int = DEWAR_TEMP_12K_CHANNEL
    ch4: int = DEWAR_TEMP_4K_CHANNEL
    limit4k: float = DEWAR_TEMP_DEFAULT_4K_LIMIT

    @property
    def ch4_index(self) -> int:
        """0-based index of the 4K stage in ``RM_DEWAR_TEMPS_V16_F``."""
        return self.ch4 - 1


def _read_lines(c_path: str) -> list[tuple[int, str]] | None:
    """Return ``(line_number, stripped_line)`` for every data line.

    Blank lines and lines whose first non-blank character is ``#`` are
    dropped, as every site-file reader in the C does.

    Parameters
    ----------
    c_path : str
        Absolute C path, resolved with :func:`site_path`.

    Returns
    -------
    list of (int, str) or None
        ``None`` (with a warning) if the file can't be opened.
    """
    path = site_path(c_path)
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            raw = f.readlines()
    except OSError as exc:
        logger.warning("cannot open %s: %s", path, exc)
        return None
    lines = []
    for n, line in enumerate(raw, start=1):
        s = line.strip()
        if s and not s.startswith("#"):
            lines.append((n, s))
    return lines


def _leading_ints(s: str, count: int) -> list[int]:
    """Parse up to ``count`` leading whitespace-separated integers.

    Stops at the first token that isn't an integer, the way a run of
    ``sscanf("%d")`` conversions does.
    """
    out = []
    for tok in s.split()[:count]:
        try:
            out.append(int(tok))
        except ValueError:
            break
    return out


def _read_type_file(c_path: str) -> dict[int, RxType] | None:
    """Shared reader for ``rxtype.conf`` and ``loadtype.conf``.

    Ports ``smaGetRxTypes()`` (``rxtype.c:56-104``), which
    ``smaGetLoadTypes()`` (``loadtype.c``) duplicates line for line:

    * every antenna starts at ``0`` (``memset``), so **an antenna
      missing from the file is TUNE6**, not NONE;
    * a line is ``ant type [comment...]``; fewer than two integers, an
      antenna outside 1-8, or a type >= 2 is warned about and skipped;
    * negative types are accepted. The C stores them as-is; any
      negative value behaves as NONE (matches neither TUNE6 nor WSMA),
      so it is stored as :attr:`RxType.NONE`.

    Parameters
    ----------
    c_path : str
        :data:`RXTYPE_CONFIG_FILE` or :data:`LOADTYPE_CONFIG_FILE`.

    Returns
    -------
    dict of int to RxType or None
        Antennas 1-8 to their type; ``None`` if the file is missing.
    """
    lines = _read_lines(c_path)
    if lines is None:
        return None
    types = {ant: RxType.TUNE6 for ant in range(1, SMA_N_ANTENNAS + 1)}
    for n, line in lines:
        vals = _leading_ints(line, 2)
        if len(vals) < 2:
            logger.warning("%s:%d: invalid line", c_path, n)
            continue
        ant, code = vals
        if not 1 <= ant <= SMA_N_ANTENNAS:
            logger.warning("%s:%d: invalid antenna number: %d", c_path, n, ant)
            continue
        if code >= N_RX_TYPES:
            logger.warning("%s:%d: invalid type: %d", c_path, n, code)
            continue
        types[ant] = RxType(code) if code >= 0 else RxType.NONE
    return types


def read_rxtypes() -> dict[int, RxType] | None:
    """Receiver type per antenna, from ``/global/configFiles/rxtype.conf``.

    Returns
    -------
    dict of int to RxType or None
        See :func:`_read_type_file`.
    """
    return _read_type_file(RXTYPE_CONFIG_FILE)


def read_loadtypes() -> dict[int, RxType] | None:
    """Ambient-load assembly type per antenna, from ``loadtype.conf``.

    Returns
    -------
    dict of int to RxType or None
        See :func:`_read_type_file`.
    """
    return _read_type_file(LOADTYPE_CONFIG_FILE)


def read_dewar_sensors() -> dict[int, DewarSensors] | None:
    """Dewar sensor channels and 4K limit per antenna, from ``dewarTemp.conf``.

    Ports ``updateDewarTempConfig()`` / ``getDewar4KSensor()`` /
    ``getDewar4KLimit()`` (``dewarpage.c:52-104``):

    * a line is ``ant ch77 ch12 ch4 limit4K``; it needs at least the
      antenna and one more number, and missing trailing fields keep
      their defaults;
    * a channel outside 1-16, or a limit <= 0, is ignored (default
      kept);
    * an antenna with no line gets every default.

    Not ported: ``getDewar12KSensor()``/``getDewar77KSensor()`` test the
    4K entry instead of their own, which only matters for a file that
    sets 12K/77K but not 4K.

    Returns
    -------
    dict of int to DewarSensors or None
        Antennas 1-8; ``None`` if the file is missing.
    """
    lines = _read_lines(DEWAR_SENSORS_FILE)
    if lines is None:
        return None
    sensors = {ant: DewarSensors() for ant in range(1, SMA_N_ANTENNAS + 1)}
    for _n, line in lines:
        toks = line.split()
        vals = _leading_ints(line, 4)
        if len(vals) < 2 or not 1 <= vals[0] <= SMA_N_ANTENNAS:
            continue
        ant, chans = vals[0], vals[1:]
        d = DewarSensors()
        ch = [c if 0 < c <= DEWAR_N_CHANNELS else default
              for c, default in zip(chans, (d.ch77, d.ch12, d.ch4))]
        ch += [d.ch77, d.ch12, d.ch4][len(ch):]
        limit = d.limit4k
        if len(vals) == 4 and len(toks) > 4:
            try:
                t = float(toks[4])
            except ValueError:
                t = 0.0
            if t > 0.0:
                limit = t
        sensors[ant] = DewarSensors(ch77=ch[0], ch12=ch[1], ch4=ch[2], limit4k=limit)
    return sensors


def read_wsma_selection() -> dict[int, dict[int, str]] | None:
    """wSMA selector-wheel mode per position, from ``wselect.conf``.

    Ports ``readSelection()`` (``wsma.c:49-90``): a line is
    ``ant c1 c2 c3 c4`` where each code is one of ``L H G D``
    (case-insensitive). A line with fewer than five fields or an
    antenna outside 1-8 is skipped; an invalid code leaves that
    position unset.

    Returns
    -------
    dict of int to dict of int to str, or None
        ``{ant: {position: mode}}`` for each antenna in the file
        (antennas absent from the file are absent here, as their C
        entries stay empty); ``None`` if the file is missing.
    """
    lines = _read_lines(WSMA_SELECT_FILE)
    if lines is None:
        return None
    selection: dict[int, dict[int, str]] = {}
    for n, line in lines:
        toks = line.split()
        vals = _leading_ints(line, 1)
        if not vals or len(toks) < 1 + WSMA_SELECTOR_POSITIONS:
            logger.warning("%s:%d: invalid line", WSMA_SELECT_FILE, n)
            continue
        ant = vals[0]
        if not 1 <= ant <= SMA_N_ANTENNAS:
            logger.warning("%s:%d: invalid antenna number: %d", WSMA_SELECT_FILE, n, ant)
            continue
        modes = {}
        for pos, tok in enumerate(toks[1:1 + WSMA_SELECTOR_POSITIONS], start=1):
            code = tok[0].upper()
            if code in WSMA_SELECTIONS:
                modes[pos] = code
            else:
                logger.warning("%s:%d: ant %d, invalid pos[%d]: %r",
                               WSMA_SELECT_FILE, n, ant, pos, tok[0])
        selection[ant] = modes
    return selection


_TYPE_READERS = {"rxtype": (read_rxtypes, RXTYPE_CONFIG_FILE),
                 "loadtype": (read_loadtypes, LOADTYPE_CONFIG_FILE)}


def antenna_set(selector: str) -> list[int]:
    """Antennas of one receiver or load type, for ``__each__`` ``"over"``.

    Parameters
    ----------
    selector : str
        ``"<file>:<type>"`` or ``"<file>:!<type>"``, with ``<file>`` one
        of ``rxtype``, ``loadtype`` and ``<type>`` one of ``tune6``,
        ``wsma``, ``none`` (case-insensitive). ``!`` negates, e.g.
        ``"rxtype:!wsma"``.

        The C always branches as ``if(type == WSMA) ... else ...``
        (``arrayMonitor.c:491, 508, 2336``), so its Tune6 code also
        runs for NONE antennas. Use ``!wsma``, not ``tune6``, to port
        an ``else`` branch.

    Returns
    -------
    list of int
        Matching antennas in ascending order (possibly empty).

    Raises
    ------
    ValueError
        Malformed selector, or the file is missing: a compute config
        that depends on it must not load with antennas silently dropped.
    """
    kind, _, type_name = selector.lower().partition(":")
    negate = type_name.startswith("!")
    type_name = type_name.lstrip("!")
    if kind not in _TYPE_READERS or type_name not in ("tune6", "wsma", "none"):
        raise ValueError(
            f"bad antenna-set selector {selector!r}: expected "
            f"'rxtype|loadtype:[!]tune6|wsma|none'"
        )
    reader, c_path = _TYPE_READERS[kind]
    types = reader()
    if types is None:
        raise ValueError(
            f"antenna-set selector {selector!r} needs {site_path(c_path)}, "
            f"which cannot be read"
        )
    want = RxType[type_name.upper()]
    return [ant for ant, t in sorted(types.items()) if (t is want) != negate]


def dewar_param(ant: int, field_name: str) -> int | float:
    """One ``dewarTemp.conf`` value for a compute-config param token.

    Parameters
    ----------
    ant : int
        Antenna number 1-8.
    field_name : str
        A :class:`DewarSensors` attribute: ``ch77``, ``ch12``, ``ch4``,
        ``limit4k`` or ``ch4_index``.

    Returns
    -------
    int or float
        The value, with the C defaults applied.

    Raises
    ------
    ValueError
        Unknown field, antenna outside 1-8, or the file is missing.
    """
    if field_name not in ("ch77", "ch12", "ch4", "limit4k", "ch4_index"):
        raise ValueError(f"unknown dewarTemp field {field_name!r}")
    sensors = read_dewar_sensors()
    if sensors is None:
        raise ValueError(f"{site_path(DEWAR_SENSORS_FILE)} cannot be read")
    if ant not in sensors:
        raise ValueError(f"antenna {ant} out of range 1-{SMA_N_ANTENNAS}")
    return getattr(sensors[ant], field_name)


def wselect_param(ant: int) -> dict[str, str]:
    """One antenna's ``wselect.conf`` row for a compute-config param token.

    Parameters
    ----------
    ant : int
        Antenna number 1-8.

    Returns
    -------
    dict of str to str
        Selector-wheel position (``"1"``-``"4"``, as strings so the
        param survives JSON round-trips) to mode letter. Empty if the
        antenna has no line, so every position is unknown, as for an
        unset ``rxsel`` row in ``wsma.c``.

    Raises
    ------
    ValueError
        Antenna outside 1-8, or the file is missing.
    """
    if not 1 <= ant <= SMA_N_ANTENNAS:
        raise ValueError(f"antenna {ant} out of range 1-{SMA_N_ANTENNAS}")
    selection = read_wsma_selection()
    if selection is None:
        raise ValueError(f"{site_path(WSMA_SELECT_FILE)} cannot be read")
    return {str(pos): mode for pos, mode in selection.get(ant, {}).items()}


def read_smoke_ignore() -> dict[int, bool] | None:
    """Per-antenna smoke-alarm ignore flags, from ``fire/ignoreAntSmoking.txt``.

    Ports ``arrayMonitor.c:219-228``: ``fscanf("%d %d %d %d %d %d %d
    %d")`` into ``ignoreSmoking[1..8]``. The values are the first eight
    whitespace-separated integers, on one line or several; reading stops
    at the first token that isn't an integer, and antennas without a
    value are not ignored. A nonzero value means "ignore".

    Returns
    -------
    dict of int to bool or None
        Antennas 1-8 to their ignore flag; ``None`` (with a warning) if
        the file can't be opened.
    """
    path = site_path(SMOKE_IGNORE_FILE)
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        logger.warning("cannot open %s: %s", path, exc)
        return None
    values = _leading_ints(text, SMA_N_ANTENNAS)
    return {ant: (ant <= len(values) and values[ant - 1] != 0)
            for ant in range(1, SMA_N_ANTENNAS + 1)}


def smoke_ignore_param(ant: int) -> bool:
    """One antenna's smoke-ignore flag, for a compute-config param token.

    **Unlike the other site-file tokens, a missing file does not fail
    config load.** As in the C (``arrayMonitor.c:220-222``), it logs a
    warning and ignores nothing, so every smoke sensor still alarms:
    the safe default for a fire alarm.

    Parameters
    ----------
    ant : int
        Antenna number 1-8.

    Returns
    -------
    bool
        ``True`` if the antenna's smoke alarm is to be ignored.

    Raises
    ------
    ValueError
        Antenna outside 1-8.
    """
    if not 1 <= ant <= SMA_N_ANTENNAS:
        raise ValueError(f"antenna {ant} out of range 1-{SMA_N_ANTENNAS}")
    flags = read_smoke_ignore()
    return False if flags is None else flags[ant]
