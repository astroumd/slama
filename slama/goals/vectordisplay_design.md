# Design: Tabular Display of Vector/Array Monitor Points

Status: planning only, not implemented. Companion to `vectordisplay.md` (the
original goal statement); this doc records the design decided on after
discussion with Marc.

## Problem recap

Some SMAX monitor points are arrays rather than scalars: 1D vectors (e.g. one
value per antenna, `DSM:obscon:BDC48_X:DSM_BDC_VVA1_CTRL_READBACK_V8_F`,
length 8) and 2D arrays (e.g. `DSM:obscon:BDC48_X:DSM_BDC_TEMP_V2_V8_F`, 2
devices x 8 antennas). Today the web display treats every monitor point as a
single cell — an array point either fails to format as a float or gets
stringified as a single blob. Variable-name suffixes (`V8_F`, `V2_V8_F`) hint
at shape but cannot be trusted as an authoritative source, so shape and
element selection must come entirely from the JSON display config.

Sometimes only a subset of a vector's elements should be shown (e.g. index 0
is a dummy/ignored slot in
`DSM:corcon:CORR_PACU_STATUS_X:DIGITAL_RACK_RETURN_AIR_TEMP_V9_F`), and
different vectors in the same table may select different subsets as long as
the number of displayed elements is the same across the table.

## Decisions made

1. **Both of the two JSON extensions below ship together** — they solve
   different shapes of the same problem and are not mutually exclusive.
2. **Header labels derived from array index** use a structured generator
   (`prefix` / `start` / `index_offset`), not a free-form expression string
   like `"{index-1}"`. This avoids writing/evaluating a small expression
   language just for integer arithmetic on a label, at the cost of not
   supporting non-linear label patterns (multiplication, conditional text,
   zero-padding) if one is ever needed — none are needed for the known cases
   (`Antenna{index}`, `Chassis{index-1}`, `Foobar{index+3}`).
3. **Element selection** (`"elements"`) supports **both**:
   - an explicit list of indices, e.g. `[1, 2, 4, 7, 8]` — needed for
     arbitrary/non-contiguous skips (a plain slice can't express "skip only
     the middle"), and
   - a slice dict `{"start":, "stop":, "step":}`, Python-style with an
     **exclusive stop** (`{"start": 2, "stop": 9}` → indices 2..8), for the
     common contiguous/strided case. Chosen over a Python slice-string like
     `"2:9"` because the dict form is self-documenting, avoids writing a
     string-slice parser that reproduces Python's slice edge cases (missing
     parts, negative indices/step), and is more readable to whoever edits
     `conf/displays/*.json` without assuming Python fluency.
   Both forms normalize to a `list[int]` at config-load time.
4. **Thresholds/validity CSS** stay exactly as today: one threshold set per
   canonical name (from `smax.json`), applied identically to every displayed
   element of that array. No per-element threshold lookup is needed.

## Shared prerequisite: cell keying

`CellData` and `DataBridge.fetch_cell` currently assume one SMAX point maps
to exactly one display cell, keyed by bare `canonical_name`
(`fetch_cell` even does `float(result)`, so an array value today either
fails to format or falls through to `str(result)` as one blob).

Displaying array elements as separate cells requires:

- A new cell key of the form `f"{canonical_name}#{index}"` (or
  `f"{canonical_name}#{row_index}:{col_index}"` for 2D), distinct from the
  scalar case's bare `canonical_name` key.
- A new `DataBridge.fetch_vector_cell(...)`-style method that pulls the
  array-valued point from SMAX **once** and slices it into N `CellData`
  entries, rather than issuing N redundant SMAX pulls (one per displayed
  element).
- Threshold and history recording logic reused per-element, keyed by the
  parent canonical name (per decision 4 above) but stored/plotted per
  element key so each antenna/chassis gets its own history ring buffer and
  time series plot.

This change is required no matter which of the two block-level extensions
below is used, since both ultimately need many cells derived from one SMAX
pull.

## Extension A: vector row in the existing `table` block

For the common case — spreading a 1D vector across a table whose columns are
already antenna-indexed (e.g. mixing a vector row into `tracking.json`'s
8-antenna table) — extend `TableBlock`'s row definition with an alternative
to `"points"`:

```json
{
  "label": "BDC Temp (Chassis 0)",
  "vector_point": "DSM:obscon:BDC48_X:DSM_BDC_TEMP_V2_V8_F",
  "vector_index": 0,
  "elements": [1, 2, 3, 4, 5, 6, 7, 8]
}
```

- `vector_point` — single canonical name whose SMAX value is an array.
- `vector_index` — for a 2D array, which outer index to slice before
  spreading the remaining axis across the table's columns. Omitted for a
  plain 1D vector.
- `elements` — which raw array indices populate the row's cells, in column
  order (list-or-slice form per decision 3 above). Default: all elements,
  `[0, 1, ..., len(column_labels)-1]`.

Column headers keep coming from the block-level `columns.labels`/`var`/
`values` mechanism that already exists — nothing about that is new. Config
loading validates `len(elements) == len(column_labels)` per row, which is
exactly what allows one row to show all 8 antennas while another row in the
same table shows only 5 selected ones (per the "different elements, same
cell count" requirement).

`_parse_block` (table branch) gains a check: if a row has `vector_point`
instead of `points`, expand it via the new element-selection logic instead of
`_expand_template`. `DataBridge.fetch_all` gains a matching branch that calls
`fetch_vector_cell` instead of `fetch_cell` for such rows. `table.html` needs
no changes — it already just iterates `row.points`; the loader can populate
`row["points"]` with the synthetic `f"{point}#{idx}"` keys so the same
template renders both row kinds unmodified.

## Extension B: new `matrix` block type for standalone 2D arrays

For a genuine 2D array that deserves its own table (both axes coming from
one SMAX point, e.g. `DSM_BDC_TEMP_V2_V8_F` — 2 devices x 8 antennas), add a
new top-level block type:

```json
{
  "type": "matrix",
  "title": "BDC Temperatures",
  "point": "DSM:obscon:BDC48_X:DSM_BDC_TEMP_V2_V8_F",
  "row_labels":    {"prefix": "Chassis", "start": 1, "index_offset": -1},
  "column_labels": {"prefix": "Antenna", "start": 1},
  "row_elements":    [0, 1],
  "column_elements": {"start": 1, "stop": 9},
  "format": "{:.1f}"
}
```

- `row_labels` / `column_labels` — either a literal list of strings, or the
  structured generator `{"prefix":, "start":, "index_offset": 0}`: label for
  displayed position `i` (0-based among the *selected* elements) is
  `f"{prefix}{start + i}"`, and the raw array index used to fetch that
  element is `selected_index + index_offset`. This covers `Antenna{index}`,
  `Chassis{index-1}`, and `Foobar{index+3}` from the original goal doc.
- `row_elements` / `column_elements` — independent element-selection
  (list-or-slice) per axis, same schema as Extension A.
- A 1D vector is the degenerate case of a `matrix` block with one implicit
  axis (a single row or single column) — but for the primary 1D use case,
  Extension A is the natural fit since it reuses an existing antenna table;
  `matrix` with a single row is really there for a 1D array that stands
  alone with its *own* dedicated table rather than joining an existing one.

Requires a new `MatrixBlock` dataclass in `display_config.py`, a new parser
branch in `_parse_block`, a new `DataBridge` fetch path (single SMAX pull,
sliced into a `rows x columns` grid of `CellData`), and a new Jinja template
`components/matrix.html` (structurally similar to `table.html` but with
row *and* column headers both index-derived rather than one axis fixed).

## Open items for implementation planning (not yet decided)

- Exact return type of an array-valued SMAX pull (list vs numpy array vs
  nested list for 2D) — affects how `fetch_vector_cell` indexes into it.
- Whether `all_canonical_names()` (used elsewhere, e.g. for history/plot
  wiring) needs to expose the per-element synthetic keys or just the parent
  canonical name.
- Whether time-series history/plotting for a single array element should
  reuse `get_history(canonical_name)` unchanged (looked up by parent name,
  ignoring index) or needs a new `get_history(canonical_name, index)` —
  likely the latter, since each antenna/chassis element has independent
  history.
- Test coverage plan for `_parse_block` (both new branches) and the new
  `DataBridge` fetch paths, given no pytest suite exists yet for
  `display_config.py`/`data_bridge.py`.

These are implementation-level questions to resolve once Marc is ready to
move from design to code — flagging them here so they aren't lost.
