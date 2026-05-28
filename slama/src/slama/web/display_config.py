"""Load and validate JSON display configurations.

Each display config is a JSON file in conf/displays/ that describes
a page layout: tables, grids, and free-standing cells of monitor data.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class TableBlock:
    """A rows x columns table of monitor points (e.g., antenna tracking).

    Attributes
    ----------
    title : str
        Block heading displayed above the table.
    column_labels : list of str
        Header labels for each column (e.g., ``["Ant 1", ..., "Ant 8"]``).
    rows : list of dict
        Each dict has keys ``"label"`` (str), ``"points"`` (list of str
        canonical names), optionally ``"format"`` (str or None), and
        optionally ``"display_min"`` / ``"display_max"`` (float or None).
        Values outside ``[display_min, display_max]`` are shown as
        no-data rather than formatted.
    block_type : str
        Always ``"table"``.
    """
    title: str
    column_labels: list[str]
    rows: list[dict]
    block_type: str = "table"


@dataclass
class GridBlock:
    """Label: Value pairs arranged in a multi-column CSS grid.

    Attributes
    ----------
    title : str
        Block heading displayed above the grid.
    columns : int
        Number of label-value column pairs in the grid layout.
    cells : list of dict
        Each dict has keys ``"label"`` (str), ``"point"`` (str canonical
        name), and optionally ``"format"`` (str or None).
    block_type : str
        Always ``"grid"``.
    """
    title: str
    columns: int
    cells: list[dict]
    block_type: str = "grid"


@dataclass
class CellsBlock:
    """Free-standing cells in a horizontal row.

    Attributes
    ----------
    title : str
        Block heading displayed above the cells.
    cells : list of dict
        Each dict has keys ``"label"`` (str), ``"point"`` (str canonical
        name), and optionally ``"format"`` (str or None).
    block_type : str
        Always ``"cells"``.
    """
    title: str
    cells: list[dict]
    block_type: str = "cells"


@dataclass
class DisplayConfig:
    """A complete display page definition.

    Attributes
    ----------
    name : str
        Human-readable display name (e.g., ``"Antenna Tracking"``).
    description : str
        Short description shown below the page title.
    update_interval : float
        Default WebSocket update interval in seconds.
    layout : list of TableBlock, GridBlock, or CellsBlock
        Ordered list of layout blocks rendered top-to-bottom.
    filename : str
        Stem of the JSON config file (e.g., ``"tracking"``), used
        for URL routing.
    """
    name: str
    description: str
    update_interval: float
    layout: list
    filename: str = ""

    def all_canonical_names(self) -> list[str]:
        """Return all SMAX canonical names referenced by this display.

        Returns
        -------
        list of str
            Canonical names from all layout blocks, in block order.
        """
        names = []
        for block in self.layout:
            if isinstance(block, TableBlock):
                for row in block.rows:
                    names.extend(row["points"])
            elif isinstance(block, (GridBlock, CellsBlock)):
                for cell in block.cells:
                    names.append(cell["point"])
        return names


def _expand_template(template: str, var: str, values: list) -> list[str]:
    """Expand a template string by substituting a variable placeholder.

    Parameters
    ----------
    template : str
        Template string containing a ``{var}`` placeholder
        (e.g., ``"RM:acc{ant}:RM_TRACK_EL_F"``).
    var : str
        Variable name to substitute (e.g., ``"ant"``).
    values : list
        Values to substitute, one per expansion
        (e.g., ``[1, 2, 3, 4, 5, 6, 7, 8]``).

    Returns
    -------
    list of str
        Expanded canonical names, one per value.
    """
    return [template.replace(f"{{{var}}}", str(v)) for v in values]


def _parse_block(raw: dict, index: int) -> TableBlock | GridBlock | CellsBlock:
    """Parse a single layout block from a JSON config dict.

    Parameters
    ----------
    raw : dict
        Raw JSON dict for one block, with at least a ``"type"`` key.
    index : int
        Zero-based block index, used for default titles.

    Returns
    -------
    TableBlock, GridBlock, or CellsBlock
        Parsed block dataclass.

    Raises
    ------
    ValueError
        If ``raw["type"]`` is not one of ``"table"``, ``"grid"``,
        or ``"cells"``.
    """
    block_type = raw["type"]

    if block_type == "table":
        col_def = raw["columns"]
        column_labels = col_def["labels"]
        var = col_def["var"]
        values = col_def["values"]

        rows = []
        for row_def in raw["rows"]:
            expanded = _expand_template(row_def["points"], var, values)
            rows.append({
                "label": row_def["label"],
                "points": expanded,
                "format": row_def.get("format"),
                "display_min": row_def.get("display_min"),
                "display_max": row_def.get("display_max"),
            })
        return TableBlock(
            title=raw.get("title", f"Table {index}"),
            column_labels=column_labels,
            rows=rows,
        )

    elif block_type == "grid":
        return GridBlock(
            title=raw.get("title", f"Grid {index}"),
            columns=raw.get("columns", 3),
            cells=raw["cells"],
        )

    elif block_type == "cells":
        return CellsBlock(
            title=raw.get("title", f"Cells {index}"),
            cells=raw["cells"],
        )

    else:
        raise ValueError(f"Unknown block type: {block_type}")


def load_display_config(path: Path) -> DisplayConfig:
    """Load a single display configuration from a JSON file.

    Parameters
    ----------
    path : Path
        Path to the JSON config file (e.g.,
        ``conf/displays/tracking.json``).

    Returns
    -------
    DisplayConfig
        Parsed display configuration with expanded template variables.
    """
    path = Path(path)
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    blocks = [_parse_block(b, i) for i, b in enumerate(raw["layout"])]

    return DisplayConfig(
        name=raw["name"],
        description=raw.get("description", ""),
        update_interval=raw.get("update_interval", 2),
        layout=blocks,
        filename=path.stem,
    )


def list_display_configs(config_dir: Path) -> list[DisplayConfig]:
    """Load all display configurations from a directory.

    Parameters
    ----------
    config_dir : Path
        Directory containing ``*.json`` display config files.

    Returns
    -------
    list of DisplayConfig
        Parsed configurations, sorted alphabetically by filename.
    """
    config_dir = Path(config_dir)
    configs = []
    for path in sorted(config_dir.glob("*.json")):
        configs.append(load_display_config(path))
    return configs
