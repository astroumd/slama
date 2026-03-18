"""Bridge between SMAX backend and web display.

Fetches monitor point values from SMAX and computes validity states
for CSS color coding, using threshold definitions from mpdefs.json.
"""

import json
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
    """Rendered data for one display cell."""
    canonical_name: str
    value: str          # formatted display string
    css_class: str      # validity CSS class name
    cell_id: str        # HTML element id (canonical name with safe chars)
    is_numeric: bool = False  # True if value is numeric (eligible for plots)


class DataBridge:
    """Fetches SMAX data and computes validity for web display cells."""

    def __init__(self, host: str = "localhost", port: int = 6380,
                 mpdefs_path: Path = None):
        self._host = host
        self._port = port
        self._client = None  # lazy connection
        self._thresholds: dict[str, dict] = {}
        self._history: dict[str, deque] = {}  # canonical_name → deque of (timestamp, value)
        if mpdefs_path is not None:
            self._load_thresholds(mpdefs_path)

    def _get_client(self) -> SmaxRedisClient | None:
        """Lazy connection to SMAX — only connects when first needed."""
        if self._client is None:
            try:
                self._client = SmaxRedisClient(self._host, redis_port=self._port)
            except Exception:
                logger.warning("Cannot connect to SMAX at %s:%d", self._host, self._port)
                return None
        return self._client

    def _load_thresholds(self, path: Path) -> None:
        """Load threshold definitions from mpdefs.json, keyed by canonical_name."""
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        for mp in data["monitorpoints"]:
            self._thresholds[mp["canonical_name"]] = mp

    @staticmethod
    def _make_cell_id(canonical_name: str) -> str:
        """Convert canonical name to a valid HTML id."""
        return "cell-" + canonical_name.replace(":", "-")

    def _format_value(self, value, fmt: str = None) -> str:
        """Format a value for display."""
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
        """Compute the CSS class based on value and thresholds."""
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
        """Append a numeric value to the history ring buffer."""
        if not isinstance(raw_value, Number) or isinstance(raw_value, bool):
            return
        if canonical_name not in self._history:
            self._history[canonical_name] = deque(maxlen=_HISTORY_MAXLEN)
        self._history[canonical_name].append((time.time(), float(raw_value)))

    def get_history(self, canonical_name: str) -> dict:
        """Return history for a canonical name as {times, values, thresholds}.

        Returns empty lists if no history is available.
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
        """Return True if the canonical name has numeric history data."""
        return canonical_name in self._history

    def _nodata_cell(self, canonical_name: str) -> CellData:
        """Return a no-data cell for a canonical name."""
        return CellData(
            canonical_name=canonical_name,
            value="---",
            css_class=CSS_NODATA,
            cell_id=self._make_cell_id(canonical_name),
        )

    def fetch_cell(self, canonical_name: str, fmt: str = None) -> CellData:
        """Fetch a single monitor point value from SMAX."""
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

        self._record_history(canonical_name, raw_value)

        return CellData(
            canonical_name=canonical_name,
            value=self._format_value(raw_value, fmt),
            css_class=self._compute_css_class(canonical_name, raw_value),
            cell_id=self._make_cell_id(canonical_name),
            is_numeric=isinstance(raw_value, Number) and not isinstance(raw_value, bool),
        )

    def fetch_all(self, config) -> dict[str, CellData]:
        """Fetch all values for a display config.

        Returns a dict of canonical_name → CellData.
        """
        from .display_config import TableBlock, GridBlock, CellsBlock

        cells = {}
        for block in config.layout:
            if isinstance(block, TableBlock):
                for row in block.rows:
                    fmt = row.get("format")
                    for point in row["points"]:
                        cells[point] = self.fetch_cell(point, fmt)
            elif isinstance(block, (GridBlock, CellsBlock)):
                for cell_def in block.cells:
                    fmt = cell_def.get("format")
                    cells[cell_def["point"]] = self.fetch_cell(
                        cell_def["point"], fmt
                    )
        return cells
