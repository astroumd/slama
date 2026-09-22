"""Bridge between SMAX backend and web display.

Fetches monitor point values from SMAX and computes validity states
for CSS color coding, using threshold definitions from smax.json.
"""

import logging
import time
from collections import deque
from dataclasses import dataclass
from numbers import Number
from pathlib import Path

from smax import SmaxRedisClient

logger = logging.getLogger(__name__)

# CSS class names for validity states
CSS_GOOD = "cell-good"
CSS_WARNING = "cell-warning"
CSS_ERROR = "cell-error"
CSS_NODATA = "cell-nodata"
CSS_UNCHECKED = "cell-unchecked"

# Maximum history entries per canonical name (~1 hour at 2s interval)
_HISTORY_MAXLEN = 1800

# Canonical-name prefix of points written by slama.monitor.compute.
COMPUTED_PREFIX = "monitorsystem:"

# Default age limit for a computed point before its pushed validity is
# distrusted: 3 x the 2 s default ComputeEngine interval.
DEFAULT_COMPUTED_MAX_AGE_S = 6.0


def validity_to_css(validity) -> str:
    """Map a :class:`~slama.monitor.monitorpoint.Validity` to a cell CSS class.

    Parameters
    ----------
    validity : Validity
        A validity state, e.g. as pushed by the compute engine.

    Returns
    -------
    str
        ``CSS_NODATA`` for any ``INVALID_*`` state, ``CSS_ERROR`` /
        ``CSS_WARNING`` for any ``VALID_ERROR*`` / ``VALID_WARNING*``
        state, ``CSS_UNCHECKED`` for ``VALID_NOT_CHECKED``, and
        ``CSS_GOOD`` for ``VALID`` / ``VALID_GOOD``.
    """
    name = validity.name
    if name.startswith("INVALID"):
        return CSS_NODATA
    if name.startswith("VALID_ERROR"):
        return CSS_ERROR
    if name.startswith("VALID_WARNING"):
        return CSS_WARNING
    if name == "VALID_NOT_CHECKED":
        return CSS_UNCHECKED
    if name in ("VALID", "VALID_GOOD"):
        return CSS_GOOD
    return CSS_UNCHECKED


@dataclass
class CellData:
    """Rendered data for one display cell.

    Attributes
    ----------
    canonical_name : str
        SMAX canonical name (e.g., ``RM:acc1:RM_TRACK_EL_F``).
    value : str
        Formatted display string for the cell.
    css_class : str
        Validity CSS class name (e.g., ``cell-good``, ``cell-error``).
    cell_id : str
        HTML element id derived from the canonical name with safe chars.
    is_numeric : bool
        True if the underlying value is numeric (eligible for time series
        plots). Default is False.
    """
    canonical_name: str
    value: str
    css_class: str
    cell_id: str
    is_numeric: bool = False


class DataBridge:
    """Fetches SMAX data and computes validity for web display cells."""

    def __init__(self, host: str = "localhost", port: int = 6380,
                 smax_path: Path = None,
                 computed_max_age_s: float = DEFAULT_COMPUTED_MAX_AGE_S):
        """Initialize the DataBridge.

        Parameters
        ----------
        host : str, optional
            SMAX/Redis server hostname. Default is ``"localhost"``.
        port : int, optional
            SMAX/Redis server port. Default is ``6380``.
        smax_path : Path or None, optional
            Path to ``smax.json`` for loading validity thresholds from the
            MonitorSystem hierarchy. If None, no thresholds are loaded and
            all numeric values receive ``cell-good``.
        computed_max_age_s : float, optional
            For ``monitorsystem:`` (compute-engine) points only: the
            maximum age, in seconds, of the point's SMAX timestamp for
            its pushed ``<validity>`` metadata to be trusted. The engine
            re-writes every output each tick, so an older timestamp
            means the engine has stopped or the computation is failing,
            and the cell is shown as no-data. Default is
            :data:`DEFAULT_COMPUTED_MAX_AGE_S`.
        """
        self._host = host
        self._port = port
        self._computed_max_age_s = computed_max_age_s
        self._client = None  # lazy connection
        self._thresholds: dict[str, dict] = {}
        self._history: dict[str, deque] = {}  # canonical_name → deque of (timestamp, value)
        if smax_path is not None:
            self._load_thresholds(smax_path)

    def _get_client(self) -> SmaxRedisClient | None:
        """Lazy connection to SMAX — only connects when first needed.

        Returns
        -------
        SmaxRedisClient or None
            Connected client, or None if the connection failed.
        """
        if self._client is None:
            try:
                self._client = SmaxRedisClient(self._host, redis_port=self._port)
            except Exception:
                logger.warning("Cannot connect to SMAX at %s:%d", self._host, self._port)
                return None
        return self._client

    def _load_thresholds(self, path: Path) -> None:
        """Load threshold definitions from smax.json via MonitorSystem.

        Only monitor points that have at least one non-None threshold field
        (``warn_low``, ``warn_high``, ``err_low``, ``err_high``, or
        ``valid_strings``) are stored in ``_thresholds``.

        Parameters
        ----------
        path : Path
            Path to ``smax.json``.
        """
        from slama.monitor.monitorsystem import MonitorSystem
        ms = MonitorSystem(path)
        for mp in ms.all_monitor_points():
            entry = {}
            for field in ("warn_low", "warn_high", "err_low", "err_high"):
                val = getattr(mp, field)
                if val is not None:
                    entry[field] = val
            if mp._valid_strings is not None:
                entry["valid_strings"] = mp._valid_strings
            if entry:
                self._thresholds[mp.canonical_name] = entry

    @staticmethod
    def _make_cell_id(canonical_name: str) -> str:
        """Convert canonical name to a valid HTML id.

        Parameters
        ----------
        canonical_name : str
            SMAX canonical name (e.g., ``RM:acc1:RM_TRACK_EL_F``).

        Returns
        -------
        str
            HTML-safe element id (e.g., ``cell-RM-acc1-RM-TRACK-EL-F``).
        """
        return "cell-" + canonical_name.replace(":", "-")

    def _format_value(self, value, fmt: str = None) -> str:
        """Format a value for display.

        Parameters
        ----------
        value : float, str, or None
            Raw value from SMAX.
        fmt : str or None, optional
            Python format string (e.g., ``"{:.2f}"``). If None, floats
            default to 4 decimal places.

        Returns
        -------
        str
            Formatted display string, or ``"---"`` if value is None.
        """
        if value is None:
            return "---"
        if fmt:
            try:
                return fmt.format(value)
            except (ValueError, TypeError):
                pass
        if isinstance(value, float):
            return f"{value:.4f}"
        return str(value)

    def _compute_css_class(self, canonical_name: str, value) -> str:
        """Compute the CSS class based on value and thresholds.

        Parameters
        ----------
        canonical_name : str
            SMAX canonical name used to look up thresholds.
        value : float, str, bool, or None
            Raw value from SMAX.

        Returns
        -------
        str
            One of ``CSS_GOOD``, ``CSS_WARNING``, ``CSS_ERROR``,
            ``CSS_NODATA``, or ``CSS_UNCHECKED``.
        """
        if value is None:
            return CSS_NODATA

        thresholds = self._thresholds.get(canonical_name, {})

        # String validity: check valid_strings list
        if isinstance(value, str):
            valid_strings = thresholds.get("valid_strings")
            if valid_strings is not None:
                return CSS_GOOD if value in valid_strings else CSS_ERROR
            return CSS_UNCHECKED

        # Boolean: unchecked
        if isinstance(value, bool):
            return CSS_UNCHECKED

        # Numeric validity: check thresholds
        if isinstance(value, Number):
            err_high = thresholds.get("err_high")
            err_low = thresholds.get("err_low")
            warn_high = thresholds.get("warn_high")
            warn_low = thresholds.get("warn_low")

            if err_high is not None and value >= err_high:
                return CSS_ERROR
            if err_low is not None and value <= err_low:
                return CSS_ERROR
            if warn_high is not None and value >= warn_high:
                return CSS_WARNING
            if warn_low is not None and value <= warn_low:
                return CSS_WARNING
            return CSS_GOOD

        return CSS_UNCHECKED

    def _computed_css_class(self, client, canonical_name: str, result,
                            now: float = None) -> str:
        """CSS class for a compute-engine point, from its pushed validity.

        Engine outputs carry their verdict in the ``<validity>``
        metadata hash, which can express things the output's value alone
        cannot (a stale heartbeat input, a function-asserted
        ``(value, Validity)``). That verdict is only as current as the
        engine, though: ``<validity>`` is never cleared, so a stopped
        engine would leave its last verdict on screen indefinitely. The
        point's own SMAX timestamp, refreshed by the engine every tick,
        gates it.

        Parameters
        ----------
        client : SmaxRedisClient
            Connected client, used to pull the ``validity`` metadata.
        canonical_name : str
            ``monitorsystem:...`` canonical name.
        result : SmaxVarBase
            The value just pulled for ``canonical_name``; its
            ``.timestamp`` (a ``datetime``) is the engine's last write.
        now : float or None, optional
            Epoch seconds to compare against; defaults to
            :func:`time.time`. Injectable for tests.

        Returns
        -------
        str
            ``CSS_NODATA`` if the timestamp is missing or older than
            ``computed_max_age_s``, or the metadata is missing or
            unparseable; otherwise :func:`validity_to_css` of the pushed
            validity.
        """
        from slama.monitor.monitorpoint import Validity

        now = time.time() if now is None else now
        ts = getattr(result, "timestamp", None)
        if ts is None or now - ts.timestamp() > self._computed_max_age_s:
            return CSS_NODATA
        raw = client.smax_pull_meta("validity", canonical_name)
        try:
            validity = Validity(int(raw))
        except (TypeError, ValueError):
            return CSS_NODATA
        return validity_to_css(validity)

    def _record_history(self, canonical_name: str, raw_value) -> None:
        """Append a numeric value to the history ring buffer.

        Non-numeric values (strings, booleans) are silently skipped.

        Parameters
        ----------
        canonical_name : str
            SMAX canonical name.
        raw_value : float, str, bool, or None
            Raw value from SMAX. Only numeric (non-bool) values are
            recorded.
        """
        if not isinstance(raw_value, Number) or isinstance(raw_value, bool):
            return
        if canonical_name not in self._history:
            self._history[canonical_name] = deque(maxlen=_HISTORY_MAXLEN)
        self._history[canonical_name].append((time.time(), float(raw_value)))

    def get_history(self, canonical_name: str) -> dict:
        """Return time series history for a canonical name.

        Parameters
        ----------
        canonical_name : str
            SMAX canonical name.

        Returns
        -------
        dict
            Dictionary with keys ``"canonical_name"`` (str),
            ``"times"`` (list of float epoch timestamps),
            ``"values"`` (list of float), and ``"thresholds"``
            (dict with optional keys ``warn_low``, ``warn_high``,
            ``err_low``, ``err_high``). Returns empty lists if no
            history is available.
        """
        buf = self._history.get(canonical_name, deque())
        times = [t for t, _ in buf]
        values = [v for _, v in buf]

        thresholds = {}
        mp_def = self._thresholds.get(canonical_name, {})
        for key in ("warn_low", "warn_high", "err_low", "err_high"):
            val = mp_def.get(key)
            if val is not None:
                thresholds[key] = val

        return {
            "canonical_name": canonical_name,
            "times": times,
            "values": values,
            "thresholds": thresholds,
        }

    def has_history(self, canonical_name: str) -> bool:
        """Check whether numeric history exists for a canonical name.

        Parameters
        ----------
        canonical_name : str
            SMAX canonical name.

        Returns
        -------
        bool
            True if at least one numeric data point has been recorded.
        """
        return canonical_name in self._history

    def _nodata_cell(self, canonical_name: str) -> CellData:
        """Return a placeholder cell when data is unavailable.

        Parameters
        ----------
        canonical_name : str
            SMAX canonical name.

        Returns
        -------
        CellData
            Cell with value ``"---"`` and CSS class ``cell-nodata``.
        """
        return CellData(
            canonical_name=canonical_name,
            value="---",
            css_class=CSS_NODATA,
            cell_id=self._make_cell_id(canonical_name),
        )

    def fetch_cell(self, canonical_name: str, fmt: str = None,
                   display_min: float = None, display_max: float = None) -> CellData:
        """Fetch a single monitor point value from SMAX.

        Pulls the current value, records it in the history buffer (if
        numeric), and returns a ``CellData`` with formatted value and
        validity CSS class.

        Parameters
        ----------
        canonical_name : str
            SMAX canonical name (e.g., ``RM:acc1:RM_TRACK_EL_F``).
        fmt : str or None, optional
            Python format string for the display value. If None, floats
            default to 4 decimal places.
        display_min : float or None, optional
            If set, numeric values strictly below this are shown as
            no-data (``---``) rather than formatted.
        display_max : float or None, optional
            If set, numeric values strictly above this are shown as
            no-data (``---``) rather than formatted.

        Returns
        -------
        CellData
            Cell with the current value, validity CSS class, and
            numeric flag. Returns a no-data cell if SMAX is
            unreachable, the key is missing, or the value falls
            outside ``[display_min, display_max]``.
        """
        client = self._get_client()
        if client is None:
            return self._nodata_cell(canonical_name)

        table, key = canonical_name.rsplit(":", 1)
        try:
            result = client.smax_pull(table, key)
            # Extract raw value — SmaxVarBase subclasses extend numeric types
            try:
                raw_value = float(result)
            except (TypeError, ValueError):
                raw_value = str(result)
        except Exception:
            logger.debug("Failed to fetch %s", canonical_name, exc_info=True)
            return self._nodata_cell(canonical_name)

        # Suppress physically implausible values before formatting or history
        if isinstance(raw_value, Number) and not isinstance(raw_value, bool):
            if (display_min is not None and raw_value < display_min) or \
               (display_max is not None and raw_value > display_max):
                return self._nodata_cell(canonical_name)

        self._record_history(canonical_name, raw_value)

        if canonical_name.startswith(COMPUTED_PREFIX):
            try:
                css_class = self._computed_css_class(client, canonical_name, result)
            except Exception:
                logger.debug("Failed to fetch validity for %s", canonical_name,
                             exc_info=True)
                css_class = CSS_NODATA
        else:
            css_class = self._compute_css_class(canonical_name, raw_value)

        return CellData(
            canonical_name=canonical_name,
            value=self._format_value(raw_value, fmt),
            css_class=css_class,
            cell_id=self._make_cell_id(canonical_name),
            is_numeric=isinstance(raw_value, Number) and not isinstance(raw_value, bool),
        )

    def fetch_all(self, config) -> dict[str, CellData]:
        """Fetch all monitor point values for a display configuration.

        Iterates over all layout blocks in the config and fetches each
        referenced canonical name from SMAX.

        Parameters
        ----------
        config : DisplayConfig
            Display configuration whose layout blocks define the
            canonical names to fetch.

        Returns
        -------
        dict of str to CellData
            Mapping of canonical name to its rendered cell data.
        """
        from .display_config import TableBlock, GridBlock, CellsBlock

        cells = {}
        for block in config.layout:
            if isinstance(block, TableBlock):
                for row in block.rows:
                    fmt = row.get("format")
                    dmin = row.get("display_min")
                    dmax = row.get("display_max")
                    for point in row["points"]:
                        cells[point] = self.fetch_cell(point, fmt, dmin, dmax)
            elif isinstance(block, (GridBlock, CellsBlock)):
                for cell_def in block.cells:
                    fmt = cell_def.get("format")
                    dmin = cell_def.get("display_min")
                    dmax = cell_def.get("display_max")
                    cells[cell_def["point"]] = self.fetch_cell(
                        cell_def["point"], fmt, dmin, dmax
                    )
        return cells
