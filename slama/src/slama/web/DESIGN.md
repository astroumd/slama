# SMA Web Display — Design & Implementation

This document describes the design and implementation of the SLAMA web-based
monitor display system, covering Phase 1 (core infrastructure) and Phase 2
(client controls and styling).

## Goal

Replace the desktop-only PyQt6 monitor display with a web-based system that:

- Displays SMA monitor data in real time to ~100 concurrent users.
- Supports multiple display pages, each showing different subsystems or
  collections of monitor points.
- Makes it easy to create new displays via JSON configuration files.
- Color-codes cells by validity state (good, warning, error, no data).
- Lets individual clients adjust update rate and visible fields.

## Technology Stack

| Layer           | Technology                | Rationale                                           |
|-----------------|---------------------------|-----------------------------------------------------|
| Backend         | FastAPI + Uvicorn         | Async Python, native WebSocket support, proven in the antenna-monitor prototype |
| Templates       | Jinja2                    | Server-rendered HTML, Python-native, no Node.js toolchain needed |
| Live updates    | HTMX + WebSocket extension| Declarative live DOM updates with minimal JavaScript |
| Styling         | Plain CSS                 | Dark observatory theme, monospace fonts, validity colors |
| Data source     | SMAX (Redis/Valkey:6380)  | Existing SMA monitor backend via `SmaxRedisClient`  |
| Thresholds      | `smax.json` (via `MonitorSystem`) | Validity limits (warn/error high/low) inline with each monitor point definition |

The stack was chosen to keep everything in Python. The team has limited
JavaScript experience, so the frontend uses HTMX for live updates (HTML over
WebSocket, no client-side rendering framework) and only ~20 lines of
vanilla JavaScript for the settings controls.

## Architecture Overview

```
                 ┌─────────────────────────────────────────┐
                 │              Browser (HTMX)             │
                 │                                         │
                 │  1. GET /display/tracking                │
                 │     → full HTML page (Jinja2-rendered)  │
                 │                                         │
                 │  2. WebSocket /ws/display/tracking       │
                 │     ← server pushes HTML fragments      │
                 │     → client sends JSON settings        │
                 └───────────┬─────────────┬───────────────┘
                             │             │
                        HTTP GET      WebSocket
                             │             │
                 ┌───────────▼─────────────▼───────────────┐
                 │          FastAPI Server (server.py)      │
                 │                                         │
                 │  Routes:                                │
                 │    GET /              → index page       │
                 │    GET /display/{n}   → display page     │
                 │    WS  /ws/display/{n}→ live updates     │
                 │                                         │
                 │  Per-connection state:                   │
                 │    interval, hidden_rows                 │
                 └───────────────────┬─────────────────────┘
                                    │
                          DataBridge (data_bridge.py)
                                    │
                     ┌──────────────▼──────────────┐
                     │   SmaxRedisClient            │
                     │   localhost:6380              │
                     │   (SMAX / Valkey)             │
                     └─────────────────────────────┘
```

### Data Flow — Initial Page Load

1. Client requests `GET /display/tracking`.
2. Server loads `conf/displays/tracking.json` via `display_config.py`.
3. Template expansion: `RM:acc{ant}:RM_TRACK_EL_F` with `ant=[1..8]` becomes
   8 canonical names.
4. `DataBridge.fetch_all()` pulls each value from SMAX via `smax_pull()`.
   This runs in a thread pool (`asyncio.to_thread`) to avoid blocking the
   async event loop. A 5-second timeout prevents the page from hanging if
   SMAX is down — cells render as "---" with `cell-nodata` styling.
5. For each value, `DataBridge` looks up thresholds loaded from `smax.json`
   at startup (via `MonitorSystem`) and computes a CSS class: `cell-good`,
   `cell-warning`, `cell-error`, `cell-nodata`, or `cell-unchecked`.
6. Jinja2 renders the full HTML page with all layout blocks (tables, grids,
   cells) and sends it to the browser.

### Data Flow — Live Updates

1. The `display.html` template includes `hx-ext="ws"` with
   `ws-connect="/ws/display/tracking"`, which tells HTMX to open a WebSocket
   on page load.
2. The server's `ws_display()` handler runs two concurrent `asyncio` tasks:
   - **`send_updates()`** — sleeps for `state["interval"]` seconds, fetches
     all values from SMAX, renders each layout block as an HTML fragment with
     `hx-swap-oob="innerHTML"`, and sends the combined message.
   - **`receive_messages()`** — listens for JSON messages from the client
     containing interval or row visibility changes, and updates the
     per-connection `state` dict.
3. HTMX receives the HTML fragments and swaps them into the DOM by matching
   element IDs (e.g., `<div id="block-0">` replaces the element with
   `id="block-0"`). The clock element uses `hx-swap-oob` to update
   independently.

### Data Flow — Client Settings

1. The user adjusts the interval slider or toggles row checkboxes.
2. A JavaScript `sendSettings()` function serializes the current slider value
   and unchecked row labels into JSON: `{"interval": 5.0, "hidden_rows": ["Gunn1 Lock"]}`.
3. The message is sent over the same WebSocket connection.
4. The server's `receive_messages()` task parses the JSON and updates
   `state["interval"]` and `state["hidden_rows"]`.
5. On the next update cycle, `send_updates()` uses the new interval and
   passes `hidden_rows` to the table template, which filters out the
   specified rows.

## File Structure

```
src/slama/
├── web/
│   ├── __init__.py
│   ├── server.py              # FastAPI app, routes, WebSocket handler
│   ├── display_config.py      # JSON config loader with template expansion
│   ├── data_bridge.py         # SMAX → CellData with validity CSS classes
│   ├── DESIGN.md              # This document
│   ├── templates/
│   │   ├── base.html          # HTML skeleton: nav bar, clock, HTMX scripts
│   │   ├── index.html         # Display listing page
│   │   ├── display.html       # Display page: blocks + settings + JS
│   │   └── components/
│   │       ├── table.html     # Table block (rows × columns, hidden row support)
│   │       ├── grid.html      # Grid block (label: value pairs)
│   │       └── cells.html     # Cells block (horizontal standalone values)
│   └── static/
│       └── style.css          # Dark theme, validity colors, controls styling
├── conf/
│   ├── smax.json              # Full hierarchical SMAX schema with inline validity thresholds (authoritative)
│   └── displays/
│       └── tracking.json      # Antenna tracking display configuration (one of many)
└── fakeobs.py                 # Simulator (writes test data to SMAX)
```

## Module Details

### `display_config.py` — Configuration Loader

Loads JSON display configurations from `conf/displays/`. Each config defines
a page name, description, default update interval, and a `layout` array of
blocks rendered top-to-bottom.

**Block types:**

- **`table`** — Rows × columns grid. Supports template expansion via a
  `columns.var` / `columns.values` mechanism. For example:
  ```json
  {
    "type": "table",
    "columns": {
      "labels": ["Ant 1", "Ant 2", ...],
      "var": "ant",
      "values": [1, 2, 3, 4, 5, 6, 7, 8]
    },
    "rows": [
      {"label": "El (deg)", "points": "RM:acc{ant}:RM_TRACK_EL_F"}
    ]
  }
  ```
  The `{ant}` placeholder in `points` is expanded into 8 canonical names,
  one per column.

  A row may instead be a **vector row**, spreading a single array-valued
  SMAX point across the table's existing columns:
  ```json
  {"label": "BDC Temp (Chassis 0)", "vector_point": "DSM:...:DSM_BDC_TEMP_V2_V8_F",
   "vector_index": 0, "elements": [1, 2, 3, 4, 5, 6, 7, 8]}
  ```
  `elements` selects which raw array indices populate the row's cells, in
  column order — either an explicit list (for arbitrary/non-contiguous
  picks, e.g. `[1, 2, 4, 7, 8]`) or a slice dict `{"start":, "stop":,
  "step":}` (Python-style, exclusive stop). Defaults to every index up to
  the column count. `vector_index` is only needed when the point is a 2D
  array, to pick which outer row to slice first — no `shape` is needed
  here, since SMAX already returns multi-dimensional array pulls correctly
  shaped (it reshapes using its own dimensionality metadata before
  returning). A vector row can be mixed with ordinary scalar rows in the
  same table, and different vector rows may select different `elements`
  as long as every row selects the same number of elements as there are
  columns.

  A common case is several *separate* 1D array points that should stack as
  rows of one shared table — not one 2D point (that's what `matrix` is
  for; see below). `aCmonitor.json`'s "Digital Rack" block has three
  independent length-9 arrays (`DIGITAL_RACK_RETURN_AIR_TEMP_V9_F`,
  `..._SMOKE_V9_B`, `..._VENT_SETTING_V9_F`) where index 0 is a dummy slot
  and indices 1-8 are the 8 antennas:
  ```json
  {
    "type": "table",
    "title": "Digital Rack",
    "columns": {
      "labels": ["Ant 1", "Ant 2", "Ant 3", "Ant 4", "Ant 5", "Ant 6", "Ant 7", "Ant 8"],
      "var": "ant",
      "values": [1, 2, 3, 4, 5, 6, 7, 8]
    },
    "rows": [
      {"label": "Temp (F)", "vector_point": "DSM:corcon:CORR_PACU_STATUS_X:DIGITAL_RACK_RETURN_AIR_TEMP_V9_F",
       "elements": {"start": 1, "stop": 9}},
      {"label": "Smoke",    "vector_point": "DSM:corcon:CORR_PACU_STATUS_X:DIGITAL_RACK_SMOKE_V9_B",
       "elements": {"start": 1, "stop": 9}, "format": "{:.0f}"},
      {"label": "Vent",     "vector_point": "DSM:corcon:CORR_PACU_STATUS_X:DIGITAL_RACK_VENT_SETTING_V9_F",
       "elements": {"start": 1, "stop": 9}}
    ]
  }
  ```
  Each row is its own point, each `elements: {"start": 1, "stop": 9}` skips
  raw index 0 and selects indices 1-8 (exclusive stop, so 9 is not
  included) — 8 values landing in the table's 8 columns.

- **`matrix`** — A standalone table where every cell comes from slicing one
  array-valued SMAX point along one or two axes (rather than many distinct
  canonical names, as in `table`). Used for multi-axis arrays such as a
  2x8 (devices x antennas) monitor point:
  ```json
  {
    "type": "matrix",
    "point": "DSM:...:DSM_BDC_TEMP_V2_V8_F",
    "shape": [2, 8],
    "row_labels": {"prefix": "Chassis", "index_offset": 0},
    "column_labels": {"prefix": "Antenna", "index_offset": 1},
    "row_elements": [0, 1],
    "column_elements": {"start": 0, "stop": 8}
  }
  ```
  `row_labels`/`column_labels` accept either a literal list of strings, or
  a generator dict: `{"prefix":, "index_offset": 0}` labels each selected
  raw index `idx` as `f"{prefix}{idx + index_offset}"` (e.g. `"Chassis0"`,
  `"Chassis{index-1}"`-style numbering via a negative offset), or
  `{"prefix":, "start":}` labels sequential display position instead of
  the raw index. `row_elements`/`column_elements` use the same
  list-or-slice selection schema as a vector row's `elements`. `shape` here
  is used only to resolve "all elements" defaults at config-load time
  without a live SMAX connection — it is not used to reshape pulled data.

- **`grid`** — Label: Value pairs arranged in a CSS grid with a configurable
  number of columns. Each cell maps to one SMAX canonical name.

- **`cells`** — Free-standing cells in a horizontal row. Used for singleton
  values like source name, LST, frequency.

**Key classes:**
- `DisplayConfig` — Top-level config with `all_canonical_names()` helper.
- `TableBlock`, `MatrixBlock`, `GridBlock`, `CellsBlock` — Dataclasses for
  each block type.
- `load_display_config(path)` — Loads and parses one JSON file.
- `list_display_configs(dir)` — Discovers all configs in a directory.

### `data_bridge.py` — SMAX Data Bridge

Fetches monitor point values from SMAX and computes validity states for CSS
color coding.

**Design decision:** `DataBridge` loads thresholds from `smax.json` at
startup via `MonitorSystem`. Only monitor points with at least one non-`None`
threshold field are stored in `_thresholds`, keeping the dict sparse.
`DataBridge` implements its own CSS validity logic (mirroring
`MonitorPoint._numeric_validity()`) rather than using `MonitorPoint` objects
directly, to keep the web module lightweight and decoupled from the SMAX
type system.

**Key behaviors:**

- **Lazy SMAX connection** — `SmaxRedisClient` is only created on the first
  `fetch_cell()` call. This prevents the web server from blocking at startup
  if SMAX is unavailable.
- **Graceful degradation** — If SMAX is unreachable or a specific key is
  missing, cells return `"---"` with the `cell-nodata` CSS class. The page
  still renders.
- **Validity mapping:**
  - Numeric values are checked against `err_high`, `err_low`, `warn_high`,
    `warn_low` thresholds loaded from `smax.json`.
  - String values are checked against `valid_strings` lists (also from `smax.json`).
  - Booleans and values without thresholds get `cell-unchecked`.
- **Value formatting** — Floats display with 4 decimal places by default.
  A `format` field in the display config can override this per-row.

**Vector/matrix cells:** an array-valued point maps to *many* displayed
cells from a *single* SMAX pull. Each sliced element gets a synthetic cell
key of the form `"{canonical_name}.{index}"` (vector row) or
`"{canonical_name}.{row}.{col}"` (matrix block) — never a bare canonical
name, since one no longer maps to exactly one cell. `fetch_vector_row_cells()`
and `fetch_matrix_cells()` each pull the array once via `_pull_array()` and
index directly into the result — SMAX already returns multi-dimensional
array pulls correctly shaped per its own dimensionality metadata
(`smax_data_types.UserArray.__new__` reshapes before the object is even
constructed), so no manual reshape is needed on this side. Threshold
lookup and history recording still key off the parent canonical name for
thresholds (one threshold set applies to every element) but off the
synthetic per-element key for history, so each antenna/chassis element gets
its own independent time series and plot.

Elements are not required to be numeric — a string-valued array (e.g.
`DSM_BDC_DO_V8_C16`, a vector of switch-position strings) works the same
way, via `_normalize_element()`: string elements pass through unchanged
instead of being forced through `float()`, and `_slice_cell()` skips the
numeric-only `display_min`/`display_max` suppression and history recording
for them, matching how `fetch_cell()` already treats a scalar string pull.
A string row can be mixed into the same table as numeric vector rows.

**Key classes:**
- `CellData` — Dataclass holding `canonical_name` (bare, or a synthetic
  per-element key for vector/matrix cells), formatted `value` string,
  `css_class`, and `cell_id` (HTML-safe ID for HTMX targeting).
- `DataBridge` — Stateful bridge with `fetch_cell()`, `fetch_vector_row_cells()`,
  `fetch_matrix_cells()`, and `fetch_all()`.

### `server.py` — FastAPI Application

The web server with three endpoints:

| Endpoint               | Type      | Description                                |
|------------------------|-----------|--------------------------------------------|
| `GET /`                | HTTP      | Index page listing all display configs     |
| `GET /display/{name}`  | HTTP      | Rendered display page with initial data    |
| `WS /ws/display/{name}`| WebSocket | Bidirectional: pushes updates, receives settings |

**WebSocket handler design:**

The handler creates two concurrent `asyncio` tasks:

```python
send_task = asyncio.create_task(send_updates())
receive_task = asyncio.create_task(receive_messages())

done, pending = await asyncio.wait(
    [send_task, receive_task],
    return_when=asyncio.FIRST_COMPLETED,
)
```

Both tasks share a `state` dict with `interval` and `hidden_rows`. The send
task reads `state["interval"]` each iteration, so interval changes take
effect immediately on the next cycle. When either task completes (typically
due to client disconnect), the other is cancelled.

**SMAX calls in async context:**

`SmaxRedisClient` is synchronous (blocking Redis I/O). All SMAX calls are
wrapped in `asyncio.to_thread()` so they execute in the default thread pool
executor without blocking the event loop. This is critical for supporting
multiple concurrent WebSocket connections.

**Clock:**

Each WebSocket message includes a clock HTML fragment with UTC, HST
(UTC-10), and local server time. The clock element uses
`hx-swap-oob="innerHTML"` to update independently of the layout blocks.

### Templates

**`base.html`** — HTML skeleton shared by all pages. Loads HTMX and its
WebSocket extension from CDN. Contains the nav bar with brand link, clock
placeholder, and connection status badge.

**`display.html`** — The main display page template. Contains:
- Display title and description.
- The `hx-ext="ws" ws-connect="..."` element that initiates the WebSocket.
- Layout blocks rendered via `{% include %}` based on `block_type`.
- A collapsible `<details>` settings menu at the bottom with interval slider
  and row visibility checkboxes.
- ~20 lines of JavaScript for connection status tracking and `sendSettings()`.

**`components/table.html`** — Renders a `TableBlock` as an HTML `<table>`.
Supports row filtering via the `hidden_rows` set: rows whose label appears
in `hidden_rows` are omitted from the rendered HTML. Needs no special-casing
for vector rows — the loader pre-expands them to the same `row.points` list
of cell keys that scalar rows use.

**`components/matrix.html`** — Renders a `MatrixBlock` as an HTML `<table>`
with both row and column headers derived from array indices, looking up
each cell by its synthetic `"{point}.{row}.{col}"` key.

**`components/grid.html`** — Renders a `GridBlock` as a CSS grid with
label/value pairs.

**`components/cells.html`** — Renders a `CellsBlock` as a horizontal flex
row of label/value boxes.

### CSS (`style.css`)

Dark theme designed for observatory control room use (low ambient light).

**Validity colors:**
| CSS Class        | Background | Meaning                    |
|------------------|------------|----------------------------|
| `cell-good`      | Green      | Value within normal range  |
| `cell-warning`   | Yellow     | Value in warning range     |
| `cell-error`     | Red        | Value in error range       |
| `cell-nodata`    | Gray       | No data from SMAX          |
| `cell-unchecked` | White      | No thresholds defined      |

Other notable styles:
- `transition: background-color 0.3s ease` on data cells for smooth color
  changes on updates.
- Sticky table headers (`position: sticky; top: 0`) for scrolling.
- Row hover highlighting via `filter: brightness(1.1)`.

## Display Configuration Format

Each JSON file in `conf/displays/` defines one display page. Example
(`tracking.json`):

```json
{
  "name": "Antenna Tracking",
  "description": "Real-time antenna positions and receiver status",
  "update_interval": 2,
  "layout": [
    {
      "type": "cells",
      "title": "Current Observation",
      "cells": [
        {"label": "Source", "point": "RM:acc1:RM_SOURCE_C34"},
        {"label": "LST (hr)", "point": "RM:acc1:RM_LST_HOURS_F"}
      ]
    },
    {
      "type": "table",
      "title": "Antenna Positions",
      "columns": {
        "labels": ["Ant 1", "Ant 2", ..., "Ant 8"],
        "var": "ant",
        "values": [1, 2, 3, 4, 5, 6, 7, 8]
      },
      "rows": [
        {"label": "El (deg)", "points": "RM:acc{ant}:RM_TRACK_EL_F"},
        {"label": "Tsys (K)", "points": "RM:acc{ant}:RM_TSYS_D"}
      ]
    },
    {
      "type": "grid",
      "title": "Weather",
      "columns": 3,
      "cells": [
        {"label": "T(amb) (C)", "point": "RM:acc1:RM_WEATHER_TEMP_F"},
        {"label": "RH%", "point": "RM:acc1:RM_WEATHER_HUMIDITY_F"}
      ]
    }
  ]
}
```

**To add a new display:** create a new JSON file in `conf/displays/`. The
server discovers it automatically — no code changes required.

## Related Changes to Existing Code

### `conf/smax.json`

- Added a top-level `RM` section for Reflective Memory variables. Uses
  `__each__` over `acc1,acc2,...,acc8` (comma-separated string indices,
  since the SMAX database addresses these as `RM:acc1:VAR` not `RM:1:VAR`).
  152 leaf nodes total (8 antenna computers × 19 variables).
- Validity thresholds (`warn_low`, `warn_high`, `err_low`, `err_high`) and
  `valid_strings` are now inline fields on leaf node dicts throughout the
  file. `MonitorSystem._build_tree` passes all leaf fields via `**value` to
  `MonitorPoint`, so new fields are loaded automatically.
- `mpdefs.json` has been deleted. `smax.json` is now the single source of
  truth for both the SMAX database schema and validity thresholds.

### `MonitorPoint` (`monitor/monitorpoint.py`)

- `smax_type` parameter made optional (defaults to `None`). When `None`,
  the `SmaxVarBase` parent class initialization is skipped.
- Added `units` parameter as an alias for `unit` for compatibility with
  JSON that uses the plural form.
- Removed `MonitorPointList` and `MonitorListUpdater` — these were prototype
  classes that loaded the now-retired `mpdefs.json` flat list format.

### `monitor/__init__.py`

- Exports `MonitorPointUpdater` and `MonitorPointWriter`.
- `MonitorPointList` and `MonitorListUpdater` removed.

### `fakeobs.py`

- Rewritten to use the monitor point API (`MonitorPointWriter` for writes,
  `MonitorPointUpdater` for reads) instead of raw `SmaxRedisClient` calls.
- Added `if __name__ == "__main__"` block.

## Running the Server

```bash
cd src/slama
uvicorn slama.web.server:app --reload --port 8000
```

Then open `http://localhost:8000/`. To generate test data, run `fakeobs.py`
in a separate terminal with SMAX running:

```bash
cd src/slama
uv run fakeobs.py
```

## Phase 3 — Interactive Time Series Plots

### Goal

Let users click any numeric data cell to open an interactive time series plot
showing recent history, with threshold bands overlaid. Non-numeric cells
(strings like Source) are not clickable.

### Architecture

```
  ┌────────────────────────────────────────────────────────┐
  │  Browser                                               │
  │                                                        │
  │  1. User clicks a numeric cell (.plotable)             │
  │  2. JS fetches GET /api/history/RM:acc1:RM_TRACK_EL_F │
  │  3. Response: {times, values, thresholds}              │
  │  4. Plotly.js renders chart in modal overlay           │
  │  5. Each WebSocket update appends point via            │
  │     Plotly.extendTraces()                              │
  └────────────────────┬───────────────────────────────────┘
                       │
              HTTP GET (JSON)
                       │
  ┌────────────────────▼───────────────────────────────────┐
  │  FastAPI Server                                        │
  │                                                        │
  │  /api/history/{canonical_name}                         │
  │    → bridge.get_history(canonical_name)                │
  │    → returns {times, values, thresholds}               │
  │                                                        │
  │  DataBridge._history                                   │
  │    dict[str, deque(maxlen=1800)]                       │
  │    ~216 KB per canonical name                          │
  │    Populated automatically on each fetch_cell() call   │
  └────────────────────────────────────────────────────────┘
```

### Server-Side History Buffer (`data_bridge.py`)

- `DataBridge._history` — `dict[str, deque]` mapping canonical names to ring
  buffers of `(timestamp, float_value)` tuples.
- `_record_history()` — Called from `fetch_cell()` after each SMAX pull.
  Only records numeric values (skips strings and booleans).
- `get_history(canonical_name)` — Returns `{canonical_name, times, values,
  thresholds}` where thresholds are the `warn_low/high`, `err_low/high`
  limits loaded from `smax.json`.
- Ring buffer size: `maxlen=1800` entries (~1 hour at 2-second intervals,
  ~216 KB per canonical name).
- History starts accumulating when the server starts. There is no persistent
  storage — restarting the server clears history.

### CellData.is_numeric Flag

`CellData` gained an `is_numeric: bool` field (default `False`). Set to
`True` in `fetch_cell()` when the raw SMAX value is numeric. Templates use
this flag to add the `plotable` CSS class and `data-canonical` attribute
only to numeric cells.

### API Endpoint (`server.py`)

```
GET /api/history/{canonical_name:path}
```

Returns JSON:
```json
{
  "canonical_name": "RM:acc1:RM_TRACK_EL_F",
  "times": [1742000000.0, 1742000002.0, ...],
  "values": [45.123, 45.125, ...],
  "thresholds": {"warn_low": 10.0, "warn_high": 80.0, "err_low": 5.0, "err_high": 85.0}
}
```

The canonical name is a path parameter (not query parameter) so that colons
are preserved. Returns empty lists with 200 status if no history exists yet.

### Frontend Interaction

**Click handling** — Event delegation on `document` catches clicks on any
`.plotable` element, even after HTMX swaps in new HTML. Reads
`data-canonical` attribute to identify the monitor point.

**Modal** — A fixed-position overlay (`#plot-modal`) with a dark backdrop.
Contains a header with the canonical name and close button, plus a
`#plot-container` div for Plotly. Closes on button click, backdrop click,
or Escape key.

**Plotly.js chart** — Loaded from CDN (`plotly-2.35.2.min.js`). Dark theme
layout matching the observatory CSS (`paper_bgcolor: #16213e`,
`plot_bgcolor: #1a1a2e`, monospace font). Features:
- Line + markers trace in brand color (`#53a8b6`).
- Horizontal dashed lines for warning thresholds (yellow).
- Horizontal dotted lines for error thresholds (red).
- Interactive zoom, pan, and hover tooltips (Plotly built-in).
- X-axis formatted as `%H:%M:%S` (UTC time).

**Live updates** — Listens for `htmx:wsAfterMessage` events. When a plot
is open, reads the current value from the DOM element matching the plotted
canonical name's cell ID and appends it to the Plotly trace via
`Plotly.extendTraces()`.

### CSS Additions (`style.css`)

- `.plotable` — `cursor: pointer` and cyan outline on hover to indicate
  clickability.
- `.plot-modal` — Fixed overlay with semi-transparent black backdrop.
- `.plot-modal-content` — 85% width, max 900px, with surface background
  and accent border.
- `#plot-container` — Fixed 400px height for the Plotly chart.

### Design Decisions

- **Why server-side buffer, not client-side?** — Server buffer is shared
  across all connections. A user opening the page sees history from before
  their session started (up to 1 hour). Client-only accumulation would
  show nothing on initial click.
- **Why HTTP endpoint, not WebSocket?** — The history fetch is a one-time
  request-response (potentially large payload). Using HTTP keeps the
  WebSocket protocol simple (HTML fragments + settings JSON).
- **Why no string plots?** — String values like source name don't have
  meaningful numeric time series. A future enhancement could show an
  event log table for strings.

## Future Phases

- **Phase 4** — Deployment (Nginx reverse proxy, systemd service),
  reconnection logic, additional display configs.
