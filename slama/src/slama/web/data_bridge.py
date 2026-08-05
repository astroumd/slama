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
                 smax_path: Path = None):
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
        """
        self._host = host
        self._port = port
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
            SMAX canonical name (e.g., ``RM:acc1:RM_TRACK_EL_F``), or a
            synthetic per-element vector/matrix cell key (e.g.,
            ``RM:acc1:RM_TRACK_EL_F.3``).

        Returns
        -------
        str
            HTML-safe element id (e.g., ``cell-RM-acc1-RM-TRACK-EL-F``).
        """
        return "cell-" + canonical_name.replace(":", "-").replace(".", "-")

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

        return CellData(
            canonical_name=canonical_name,
            value=self._format_value(raw_value, fmt),
            css_class=self._compute_css_class(canonical_name, raw_value),
            cell_id=self._make_cell_id(canonical_name),
            is_numeric=isinstance(raw_value, Number) and not isinstance(raw_value, bool),
        )

    def _pull_array(self, canonical_name: str):
        """Pull an array-valued point from SMAX, preserving its shape.

        Parameters
        ----------
        canonical_name : str
            SMAX canonical name of an array-valued monitor point.

        Returns
        -------
        array-like or None
            The pulled array (e.g. a ``SmaxArray``/``numpy.ndarray``, or a
            nested list), indexable per its declared shape — SMAX reshapes
            multi-dimensional array pulls using its dimensionality
            metadata before returning them, so no manual reshape is
            needed here. None if SMAX is unreachable or the pull fails.
        """
        client = self._get_client()
        if client is None:
            return None
        table, key = canonical_name.rsplit(":", 1)
        try:
            return client.smax_pull(table, key)
        except Exception:
            logger.debug("Failed to fetch array %s", canonical_name, exc_info=True)
            return None

    @staticmethod
    def _normalize_element(value):
        """Normalize one pulled array element to a native float or str.

        Numeric SMAX array elements come back as numpy scalar types
        (e.g. ``np.float32``); string array elements (``SmaxStrArray``)
        come back as native ``str`` already. This gives callers a single
        type to branch on downstream, mirroring how ``fetch_cell`` already
        handles a scalar pull.

        Parameters
        ----------
        value : object
            One element indexed out of a pulled array-like value.

        Returns
        -------
        float or str
            The element as a native Python float or str.

        Raises
        ------
        TypeError, ValueError
            If ``value`` is neither a string nor convertible to float.
        """
        if isinstance(value, str):
            return value
        return float(value)

    def _slice_cell(self, key: str, canonical_name: str, raw_value,
                     fmt: str, display_min: float, display_max: float) -> CellData:
        """Build one ``CellData`` for a single sliced array element.

        Parameters
        ----------
        key : str
            Synthetic per-element cell key, e.g. ``"{point}.3"``.
        canonical_name : str
            Parent SMAX canonical name, used for threshold lookup.
        raw_value : float or str
            The element's value.
        fmt : str or None
            Python format string.
        display_min : float or None
            If set, numeric values strictly below this are shown as
            no-data. Ignored for string values.
        display_max : float or None
            If set, numeric values strictly above this are shown as
            no-data. Ignored for string values.

        Returns
        -------
        CellData
            Rendered cell, or a no-data cell if outside
            ``[display_min, display_max]``.
        """
        is_numeric = isinstance(raw_value, Number) and not isinstance(raw_value, bool)

        if is_numeric:
            if (display_min is not None and raw_value < display_min) or \
               (display_max is not None and raw_value > display_max):
                return self._nodata_cell(key)
            self._record_history(key, raw_value)

        return CellData(
            canonical_name=key,
            value=self._format_value(raw_value, fmt),
            css_class=self._compute_css_class(canonical_name, raw_value),
            cell_id=self._make_cell_id(key),
            is_numeric=is_numeric,
        )

    def fetch_vector_row_cells(self, vector_point: str, elements: list[int],
                                vector_index: int = None,
                                fmt: str = None, display_min: float = None,
                                display_max: float = None) -> dict[str, CellData]:
        """Fetch one array-valued point and slice it into a table row's cells.

        Pulls the array once (not once per displayed element), then indexes
        into it. For a plain 1D vector, ``elements`` indexes the pulled
        array directly. For a 2D array, ``vector_index`` selects which outer
        row to use first — SMAX already returns multi-dimensional pulls
        correctly shaped (per its own dimensionality metadata), so no
        manual reshape is needed here.

        Parameters
        ----------
        vector_point : str
            SMAX canonical name of the array-valued monitor point.
        elements : list of int
            Raw array indices to display, one per table column, in order.
        vector_index : int or None, optional
            For a 2D array, which outer index (axis 0) to slice before
            indexing with ``elements``. None for a 1D vector.
        fmt : str or None, optional
            Python format string applied to every cell.
        display_min : float or None, optional
            If set, values strictly below this are shown as no-data.
        display_max : float or None, optional
            If set, values strictly above this are shown as no-data.

        Returns
        -------
        dict of str to CellData
            Keyed by synthetic cell key ``"{vector_point}.{index}"``, one
            entry per entry in ``elements``.
        """
        keys = [f"{vector_point}.{idx}" for idx in elements]
        pulled = self._pull_array(vector_point)
        if pulled is None:
            return {key: self._nodata_cell(key) for key in keys}

        row = pulled[vector_index] if vector_index is not None else pulled

        cells = {}
        for key, idx in zip(keys, elements):
            try:
                raw_value = self._normalize_element(row[idx])
            except (IndexError, TypeError, ValueError):
                cells[key] = self._nodata_cell(key)
                continue
            cells[key] = self._slice_cell(
                key, vector_point, raw_value, fmt, display_min, display_max
            )
        return cells

    def fetch_matrix_cells(self, point: str, row_elements: list[int],
                            column_elements: list[int],
                            fmt: str = None, display_min: float = None,
                            display_max: float = None) -> dict[str, CellData]:
        """Fetch a 2D array-valued point and slice it into a matrix block's cells.

        Pulls the array once, then indexes every selected (row, column)
        pair. SMAX already returns 2D pulls correctly shaped, so no manual
        reshape is needed here.

        Parameters
        ----------
        point : str
            SMAX canonical name of the 2D array-valued monitor point.
        row_elements : list of int
            Raw array indices along axis 0 to display, in row order.
        column_elements : list of int
            Raw array indices along axis 1 to display, in column order.
        fmt : str or None, optional
            Python format string applied to every cell.
        display_min : float or None, optional
            If set, values strictly below this are shown as no-data.
        display_max : float or None, optional
            If set, values strictly above this are shown as no-data.

        Returns
        -------
        dict of str to CellData
            Keyed by synthetic cell key ``"{point}.{row}.{col}"``.
        """
        keys = [
            f"{point}.{r}.{c}" for r in row_elements for c in column_elements
        ]
        arr = self._pull_array(point)
        if arr is None:
            return {key: self._nodata_cell(key) for key in keys}

        cells = {}
        for r in row_elements:
            for c in column_elements:
                key = f"{point}.{r}.{c}"
                try:
                    raw_value = self._normalize_element(arr[r][c])
                except (IndexError, TypeError, ValueError):
                    cells[key] = self._nodata_cell(key)
                    continue
                cells[key] = self._slice_cell(
                    key, point, raw_value, fmt, display_min, display_max
                )
        return cells

    def fetch_indexed_cell(self, canonical_name: str, element_index: list[int],
                            fmt: str = None, display_min: float = None,
                            display_max: float = None) -> CellData:
        """Fetch an array-valued point and reduce it to one scalar cell.

        Used for a table row where each column is a *different* canonical
        name (e.g. one per antenna, via column templating) and each of
        those is itself multi-dimensional — the reverse of a vector row,
        which has one canonical name spread across many columns. Every
        entry in ``element_index`` is applied as successive indexing
        (``arr[i0][i1]...``) to reduce the pulled array to a scalar.

        Parameters
        ----------
        canonical_name : str
            SMAX canonical name of the array-valued monitor point.
        element_index : list of int
            Fixed indices to apply, one per array axis, in order.
        fmt : str or None, optional
            Python format string.
        display_min : float or None, optional
            If set, numeric values strictly below this are shown as
            no-data.
        display_max : float or None, optional
            If set, numeric values strictly above this are shown as
            no-data.

        Returns
        -------
        CellData
            Keyed by synthetic cell key
            ``"{canonical_name}.{i0}.{i1}..."``.
        """
        key = f"{canonical_name}." + ".".join(str(i) for i in element_index)
        pulled = self._pull_array(canonical_name)
        if pulled is None:
            return self._nodata_cell(key)

        value = pulled
        try:
            for idx in element_index:
                value = value[idx]
            raw_value = self._normalize_element(value)
        except (IndexError, TypeError, ValueError):
            return self._nodata_cell(key)

        return self._slice_cell(key, canonical_name, raw_value, fmt, display_min, display_max)

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
        from .display_config import TableBlock, MatrixBlock, GridBlock, CellsBlock

        cells = {}
        for block in config.layout:
            if isinstance(block, TableBlock):
                for row in block.rows:
                    fmt = row.get("format")
                    dmin = row.get("display_min")
                    dmax = row.get("display_max")
                    if row.get("vector_point"):
                        cells.update(self.fetch_vector_row_cells(
                            row["vector_point"], row["vector_elements"],
                            row.get("vector_index"),
                            fmt, dmin, dmax,
                        ))
                    elif row.get("element_index") is not None:
                        for base_point, point in zip(row["element_base_points"], row["points"]):
                            cells[point] = self.fetch_indexed_cell(
                                base_point, row["element_index"], fmt, dmin, dmax
                            )
                    else:
                        for point in row["points"]:
                            cells[point] = self.fetch_cell(point, fmt, dmin, dmax)
            elif isinstance(block, MatrixBlock):
                cells.update(self.fetch_matrix_cells(
                    block.point, block.row_elements, block.column_elements,
                    block.format, block.display_min, block.display_max,
                ))
            elif isinstance(block, (GridBlock, CellsBlock)):
                for cell_def in block.cells:
                    fmt = cell_def.get("format")
                    dmin = cell_def.get("display_min")
                    dmax = cell_def.get("display_max")
                    element_index = cell_def.get("element_index")
                    if element_index is not None:
                        cells[cell_def["key"]] = self.fetch_indexed_cell(
                            cell_def["point"], element_index, fmt, dmin, dmax
                        )
                    else:
                        cells[cell_def["key"]] = self.fetch_cell(
                            cell_def["point"], fmt, dmin, dmax
                        )
        return cells
