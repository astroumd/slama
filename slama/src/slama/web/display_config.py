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
        Each dict has keys ``"label"`` (str) and ``"points"`` (list of str
        cell keys, one per column). A row is either:

        - a **scalar row**: ``"points"`` is a list of distinct canonical
          names (one SMAX point per column), or
        - a **vector row**: a single array-valued canonical name
          (``"vector_point"``) is spread across the columns. ``"points"``
          is pre-expanded to synthetic per-element keys of the form
          ``"{vector_point}.{index}"``, and ``"vector_point"``,
          ``"vector_elements"`` (the raw array indices selected, one per
          column), and ``"vector_index"`` (which outer index to slice
          first, for a 2D array; None for a 1D vector) are also present so
          ``DataBridge`` can fetch and slice it. No shape is needed here —
          SMAX returns multi-dimensional array pulls already reshaped
          according to its own dimensionality metadata, or
        - an **indexed row**: like a scalar row, ``"points"`` is a list of
          distinct (usually template-expanded) canonical names, one per
          column, but each one is itself array-valued and gets reduced to
          a scalar by a fixed ``"element_index"`` (list of int) applied to
          every column identically — e.g. ``element_index: [0, 3]`` on a
          row whose per-column points are 2x10 arrays picks band 0, time
          bin 3 out of every column's array. Used when the per-column
          axis (e.g. antenna) is a different canonical name per column,
          but each of those names is itself multi-dimensional — the
          reverse of a vector row, which has one canonical name and many
          columns. ``"points"`` is pre-expanded to synthetic keys of the
          form ``"{base_point}.{i0}.{i1}..."`` and the original
          per-column base names are kept in ``"element_base_points"``.

        Every row dict also has optionally ``"format"`` (str or None), and
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
class MatrixBlock:
    """A standalone table rendered entirely from one array-valued point.

    Unlike ``TableBlock`` (whose columns are populated from many distinct
    canonical names), every cell in a ``MatrixBlock`` comes from slicing a
    single SMAX array-valued point along one or two axes. Used for
    multi-axis arrays such as a 2x8 (devices x antennas) monitor point.

    Attributes
    ----------
    title : str
        Block heading displayed above the table.
    point : str
        SMAX canonical name of the array-valued monitor point.
    shape : tuple of int
        Full shape of the underlying array, e.g. ``(2, 8)``. Required so
        default element selection (when ``row_elements``/``column_elements``
        is omitted, meaning "all indices") can be resolved at config-load
        time, without a live SMAX connection. Not used to reshape pulled
        data — SMAX already returns multi-dimensional array pulls
        correctly shaped.
    row_labels : list of str
        Header label for each displayed row, one per entry in
        ``row_elements``.
    row_elements : list of int
        Raw array indices (along axis 0) selected for display, in row
        order. A 1D array uses a single implicit row (``row_elements ==
        [0]``).
    column_labels : list of str
        Header label for each displayed column, one per entry in
        ``column_elements``.
    column_elements : list of int
        Raw array indices (along axis 1) selected for display, in column
        order.
    format : str or None
        Python format string applied to every cell. If None, floats
        default to 4 decimal places.
    display_min : float or None
        If set, values strictly below this are shown as no-data.
    display_max : float or None
        If set, values strictly above this are shown as no-data.
    block_type : str
        Always ``"matrix"``.
    """
    title: str
    point: str
    shape: tuple
    row_labels: list[str]
    row_elements: list[int]
    column_labels: list[str]
    column_elements: list[int]
    format: str = None
    display_min: float = None
    display_max: float = None
    block_type: str = "matrix"

    @property
    def cell_points(self) -> list[str]:
        """Synthetic per-cell keys for every displayed (row, column) pair.

        Returns
        -------
        list of str
            Keys of the form ``"{point}.{row_index}.{col_index}"``, row
            order major.
        """
        return [
            f"{self.point}.{r}.{c}"
            for r in self.row_elements
            for c in self.column_elements
        ]


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
    layout : list of TableBlock, MatrixBlock, GridBlock, or CellsBlock
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
            elif isinstance(block, MatrixBlock):
                names.extend(block.cell_points)
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


def _resolve_elements(elements_def, default_count: int = None) -> list[int]:
    """Resolve an ``"elements"`` config value into a list of array indices.

    Parameters
    ----------
    elements_def : list of int, dict, or None
        Either an explicit list of indices (e.g. ``[1, 2, 4, 7, 8]``, for
        arbitrary/non-contiguous selection), a slice dict with keys
        ``"start"`` (default 0), ``"stop"`` (required), ``"step"``
        (default 1) using Python's exclusive-stop convention, or None to
        select every index up to ``default_count``.
    default_count : int or None, optional
        Number of elements to select when ``elements_def`` is None.
        Required in that case.

    Returns
    -------
    list of int
        Resolved, ordered list of raw array indices.

    Raises
    ------
    ValueError
        If ``elements_def`` is None and ``default_count`` is not given,
        or if ``elements_def`` is neither a list, dict, nor None.
    """
    if elements_def is None:
        if default_count is None:
            raise ValueError("'elements' not specified and no default count available")
        return list(range(default_count))
    if isinstance(elements_def, list):
        return [int(i) for i in elements_def]
    if isinstance(elements_def, dict):
        start = elements_def.get("start", 0)
        stop = elements_def["stop"]
        step = elements_def.get("step", 1)
        return list(range(start, stop, step))
    raise ValueError(f"Invalid 'elements' definition: {elements_def!r}")


def _resolve_labels(labels_def, elements: list[int]) -> list[str]:
    """Resolve a ``"row_labels"``/``"column_labels"`` value into label strings.

    Parameters
    ----------
    labels_def : list of str or dict
        Either a literal list of labels (must match ``len(elements)``), or
        a structured generator dict with keys ``"prefix"`` (default ``""``)
        and either ``"start"`` (sequential numbering: label for the i-th
        selected element is ``f"{prefix}{start+i}"``, ignoring the raw
        index) or ``"index_offset"`` (default 0; label for a selected raw
        index ``idx`` is ``f"{prefix}{idx + index_offset}"``). ``"start"``
        takes precedence if both are given.
    elements : list of int
        Raw array indices selected for this axis, in display order.

    Returns
    -------
    list of str
        One label per entry in ``elements``.

    Raises
    ------
    ValueError
        If a literal label list's length doesn't match ``elements``, or
        ``labels_def`` is neither a list nor a dict.
    """
    if isinstance(labels_def, list):
        if len(labels_def) != len(elements):
            raise ValueError(
                f"label list length {len(labels_def)} != elements length {len(elements)}"
            )
        return list(labels_def)
    if isinstance(labels_def, dict):
        prefix = labels_def.get("prefix", "")
        if "start" in labels_def:
            start = labels_def["start"]
            return [f"{prefix}{start + i}" for i in range(len(elements))]
        offset = labels_def.get("index_offset", 0)
        return [f"{prefix}{idx + offset}" for idx in elements]
    raise ValueError(f"Invalid label definition: {labels_def!r}")


def _parse_block(raw: dict, index: int) -> TableBlock | GridBlock | CellsBlock | MatrixBlock:
    """Parse a single layout block from a JSON config dict.

    Parameters
    ----------
    raw : dict
        Raw JSON dict for one block, with at least a ``"type"`` key.
    index : int
        Zero-based block index, used for default titles.

    Returns
    -------
    TableBlock, MatrixBlock, GridBlock, or CellsBlock
        Parsed block dataclass.

    Raises
    ------
    ValueError
        If ``raw["type"]`` is not one of ``"table"``, ``"matrix"``,
        ``"grid"``, or ``"cells"``.
    """
    block_type = raw["type"]

    if block_type == "table":
        col_def = raw["columns"]
        column_labels = col_def["labels"]
        var = col_def["var"]
        values = col_def["values"]

        rows = []
        for row_def in raw["rows"]:
            if "vector_point" in row_def:
                vector_point = row_def["vector_point"]
                elements = _resolve_elements(
                    row_def.get("elements"), default_count=len(column_labels)
                )
                if len(elements) != len(column_labels):
                    raise ValueError(
                        f"Row '{row_def.get('label')}' selects {len(elements)} "
                        f"elements but the table has {len(column_labels)} columns"
                    )
                rows.append({
                    "label": row_def["label"],
                    "points": [f"{vector_point}.{idx}" for idx in elements],
                    "format": row_def.get("format"),
                    "display_min": row_def.get("display_min"),
                    "display_max": row_def.get("display_max"),
                    "vector_point": vector_point,
                    "vector_elements": elements,
                    "vector_index": row_def.get("vector_index"),
                })
            elif "element_index" in row_def:
                element_index = [int(i) for i in row_def["element_index"]]
                base_points = _expand_template(row_def["points"], var, values)
                suffix = "." + ".".join(str(i) for i in element_index)
                rows.append({
                    "label": row_def["label"],
                    "points": [f"{p}{suffix}" for p in base_points],
                    "format": row_def.get("format"),
                    "display_min": row_def.get("display_min"),
                    "display_max": row_def.get("display_max"),
                    "vector_point": None,
                    "element_index": element_index,
                    "element_base_points": base_points,
                })
            else:
                expanded = _expand_template(row_def["points"], var, values)
                rows.append({
                    "label": row_def["label"],
                    "points": expanded,
                    "format": row_def.get("format"),
                    "display_min": row_def.get("display_min"),
                    "display_max": row_def.get("display_max"),
                    "vector_point": None,
                })
        return TableBlock(
            title=raw.get("title", f"Table {index}"),
            column_labels=column_labels,
            rows=rows,
        )

    elif block_type == "matrix":
        point = raw["point"]
        shape = tuple(raw["shape"])
        row_elements = _resolve_elements(raw.get("row_elements"), default_count=shape[0])
        column_elements = _resolve_elements(raw.get("column_elements"), default_count=shape[1])
        row_labels = _resolve_labels(raw.get("row_labels", {"prefix": ""}), row_elements)
        column_labels = _resolve_labels(raw.get("column_labels", {"prefix": ""}), column_elements)
        return MatrixBlock(
            title=raw.get("title", f"Matrix {index}"),
            point=point,
            shape=shape,
            row_labels=row_labels,
            row_elements=row_elements,
            column_labels=column_labels,
            column_elements=column_elements,
            format=raw.get("format"),
            display_min=raw.get("display_min"),
            display_max=raw.get("display_max"),
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
