"""Load and validate JSON display configurations.

Each display config is a JSON file in conf/displays/ that describes
a page layout: tables, grids, and free-standing cells of monitor data.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class TableBlock:
    """A rows x columns table of monitor points (e.g., antenna tracking)."""
    title: str
    column_labels: list[str]
    rows: list[dict]  # each: {"label": str, "points": list[str]}
    block_type: str = "table"


@dataclass
class GridBlock:
    """Label: Value pairs arranged in a multi-column grid."""
    title: str
    columns: int
    cells: list[dict]  # each: {"label": str, "point": str}
    block_type: str = "grid"


@dataclass
class CellsBlock:
    """Free-standing cells in a horizontal row."""
    title: str
    cells: list[dict]  # each: {"label": str, "point": str}
    block_type: str = "cells"


@dataclass
class DisplayConfig:
    """A complete display page definition."""
    name: str
    description: str
    update_interval: float
    layout: list  # list of TableBlock, GridBlock, or CellsBlock
    filename: str = ""

    def all_canonical_names(self) -> list[str]:
        """Return all SMAX canonical names referenced by this display."""
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
    """Expand a template string like 'RM:acc{ant}:FOO' into a list."""
    return [template.replace(f"{{{var}}}", str(v)) for v in values]


def _parse_block(raw: dict, index: int) -> TableBlock | GridBlock | CellsBlock:
    """Parse a single layout block from JSON."""
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
    """Load a single display config from a JSON file."""
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
    """Load all display configs from a directory."""
    config_dir = Path(config_dir)
    configs = []
    for path in sorted(config_dir.glob("*.json")):
        configs.append(load_display_config(path))
    return configs
