# SMA Web Display — Design

**Status:** Current design; implemented in `slama.web`.
**Earlier notes:** the phase-by-phase implementation log this replaces is kept
in `docs/history/web_display_phases.md`.

## 1. Goal

A web display that replaces the desktop-only PyQt6 monitor and the curses
pages:

- shows SMA monitor data in real time to about 100 concurrent users;
- supports many pages, each showing a different subsystem or collection of
  points;
- makes a new page a configuration change, not a code change;
- colour-codes every cell by validity (good, warning, error, no data);
- lets each client adjust its own update rate and which rows are visible;
- lets a user click any numeric cell for an interactive time series.

## 2. Technology

| Layer        | Choice                         | Why |
|--------------|--------------------------------|-----|
| Backend      | FastAPI + Uvicorn              | Async Python with native WebSocket support |
| Templates    | Jinja2                         | Server-rendered HTML; no Node toolchain |
| Live updates | HTMX + `ws` extension          | HTML fragments pushed over a WebSocket; almost no JavaScript |
| Plots        | Plotly.js (CDN)                | Interactive zoom, pan and hover with no custom code |
| Styling      | Plain CSS                      | Dark observatory theme, monospace, validity colours |
| Data source  | SMAX (Valkey/Redis, port 6380) | The existing monitor backend, via `SmaxRedisClient` |
| Thresholds   | `smax.json` via `MonitorSystem`| Limits live inline with each point's definition |

Everything is Python on the server. The team has little JavaScript experience,
so the page needs only a small script for connection status, the settings
controls and the plot panel. HTMX, its WebSocket extension and Plotly are
loaded from a CDN (`base.html`), so a browser needs internet access.

## 3. Architecture

```
          Browser (HTMX)
   GET /display/tracking ──► full HTML page (Jinja2)
   WS  /ws/display/tracking ◄─► HTML fragments out, JSON settings in
   GET /api/history/{name} ──► JSON time series for the plot panel
               │
               ▼
   FastAPI app (server.py)         per-connection state:
     routes, WebSocket handler       interval, hidden_rows
               │
               ▼
   DataBridge (data_bridge.py)     thresholds from smax.json,
     value → CellData(css class)   history ring buffers
               │
               ▼
   SmaxRedisClient ──► SMAX (Valkey)
```

### 3.1 Page load

1. The browser requests `GET /display/{name}`.
2. `server.py` loads `conf/displays/{name}.json` and expands its templates
   ({py:func}`load_display_config <slama.web.display_config.load_display_config>`).
3. {py:meth}`DataBridge.fetch_all <slama.web.data_bridge.DataBridge.fetch_all>`
   pulls every referenced point inside `asyncio.to_thread` (the SMAX client is
   synchronous) under a 5 s timeout. On a timeout or error every cell is a
   no-data placeholder, so the page still renders.
4. Jinja2 renders the page and the browser opens the WebSocket.

### 3.2 Live updates

`display.html` carries `hx-ext="ws" ws-connect="/ws/display/{name}"`. The
{py:func}`ws_display <slama.web.server.ws_display>` handler runs two
concurrent tasks sharing one per-connection `state` dict:

- **send**: sleep `state["interval"]`, call `fetch_all`, render each layout
  block as an HTML fragment tagged `hx-swap-oob="innerHTML"` with the id
  `block-N`, add a clock fragment, send one message. HTMX swaps each fragment
  into the element with the same id.
- **receive**: parse JSON settings from the client and update `state`.

When either task ends (normally a client disconnect) the other is cancelled.

### 3.3 Client settings

The settings menu (a collapsed `<details>` below the data) sends
`{"interval": 5.0, "hidden_rows": ["Gunn1 Lock"]}` over the same socket.
The server clamps the interval to 0.5 to 30 s (the slider offers 1 to 30 s in
0.5 s steps) and uses it from the next cycle. `hidden_rows` is a set of row
labels; table blocks omit those rows. Settings are per connection and are not
persisted.

### 3.4 Clock

Every WebSocket message includes a clock fragment showing UTC, HST (UTC-10,
no daylight saving) and the server's local time.

## 4. Modules

### 4.1 `display_config.py`

Loads and validates page definitions. Key types:
{py:class}`DisplayConfig <slama.web.display_config.DisplayConfig>` (name,
description, `update_interval`, ordered `layout`, and the file stem used for
routing) and the three block dataclasses
{py:class}`TableBlock <slama.web.display_config.TableBlock>`,
{py:class}`GridBlock <slama.web.display_config.GridBlock>` and
{py:class}`CellsBlock <slama.web.display_config.CellsBlock>`.
{py:func}`list_display_configs <slama.web.display_config.list_display_configs>`
loads every `*.json` in a directory, sorted by filename; the index page and
routing use it at request time, so a new file is picked up without a restart.

### 4.2 `data_bridge.py`

{py:class}`DataBridge <slama.web.data_bridge.DataBridge>` turns canonical names
into {py:class}`CellData <slama.web.data_bridge.CellData>` (formatted value,
CSS class, HTML id, `is_numeric`).

- **Thresholds** are loaded once, when the bridge is constructed, by building a
  `MonitorSystem` from `smax.json`. Only points with at least one threshold or
  a `valid_strings` list are kept, so the lookup stays sparse. The bridge
  applies the threshold logic itself rather than holding `MonitorPoint`
  objects, which keeps the web module decoupled from the SMAX type system.
- **SMAX connection** is created lazily on the first fetch, so the server
  starts when SMAX is down. Any failure (no connection, missing key, pull
  error) returns a no-data cell; the page always renders.
- **Cell ids** are `cell-` plus the canonical name with `:` replaced by `-`,
  which gives the live-plot script a stable way to find a cell.
- **Formatting**: floats default to four decimal places; a row's or cell's
  `format` string overrides that.
- **Display range**: a row or cell may set `display_min` / `display_max`.
  Numeric values outside the range render as no-data and are not recorded in
  history. This suppresses physically implausible sentinel values.

### 4.3 `server.py`

The FastAPI `app` and a single module-level `bridge`. The
bridge reads `SMAX_HOST` and `SMAX_PORT` from the environment at import. Routes:

| Route | Type | Purpose |
|---|---|---|
| `GET /` | HTTP | index of all pages, one card per display config |
| `GET /display/{name}` | HTTP | the rendered page with initial values (404 if the config is missing) |
| `WS /ws/display/{name}` | WebSocket | pushed fragments and received settings (closes with 4004 for a missing config) |
| `GET /api/history/{name}` | HTTP | JSON history for one point |

Running `python -m slama.web.server` provides a small CLI that sets those
environment variables before starting Uvicorn (section 7).

### 4.4 Templates and CSS

`base.html` is the skeleton (nav bar, clock, connection badge, the CDN
scripts). `index.html` lists pages. `display.html` renders the layout blocks
through `components/table.html`, `grid.html` and `cells.html`, then holds the
settings menu, the plot panel and the page script. Table rows whose label is in
`hidden_rows` are skipped. A numeric cell gets the `plotable` class and a
`data-canonical` attribute.

`static/style.css` is a dark theme with monospace type. Validity classes:

| Class | Meaning |
|---|---|
| `cell-good` | within normal range (pale green) |
| `cell-warning` | in a warning range (pale yellow) |
| `cell-error` | in an error range (pale red) |
| `cell-nodata` | no data, stale, or out of display range (grey) |
| `cell-unchecked` | no limits defined (white) |

Data cells ease between colours (`transition: background-color 0.3s`) and table
headers are sticky.

## 5. Display configuration

One JSON file per page in `src/slama/conf/displays/`. The server finds it
automatically; **adding a file adds a page**.

```json
{
  "name": "Antenna Tracking",
  "description": "Real-time antenna positions and receiver status",
  "update_interval": 2,
  "layout": [
    {
      "type": "cells",
      "title": "Current Observation",
      "cells": [{"label": "Source", "point": "RM:acc1:RM_SOURCE_C34"}]
    },
    {
      "type": "table",
      "title": "Antenna Positions",
      "columns": {"labels": ["Ant 1", "Ant 2"], "var": "ant", "values": [1, 2]},
      "rows": [
        {"label": "El (deg)", "points": "RM:acc{ant}:RM_TRACK_EL_F",
         "format": "{:.2f}", "display_min": 0, "display_max": 90}
      ]
    },
    {
      "type": "grid",
      "title": "Weather",
      "columns": 3,
      "cells": [{"label": "RH%", "point": "RM:acc1:RM_WEATHER_HUMIDITY_F"}]
    }
  ]
}
```

Block types:

- **`table`**: rows by columns. `columns.var` and `columns.values` expand the
  `{var}` placeholder in each row's `points` into one canonical name per
  column. Rows may set `format`, `display_min`, `display_max`.
- **`grid`**: label and value pairs in a CSS grid of `columns` (default 3)
  label/value pairs per row. Each cell is `{label, point, format?}`.
- **`cells`**: free-standing cells in a horizontal row, for singletons such as
  source name or LST.

A page may show computed points exactly like hardware points: use their
`monitorsystem:` canonical names. When a curses page is ported, a page shows
what the C **shows** (a derived value replaces the raw ones it was derived
from) while every point the C reads must still feed the page.

## 6. Validity colouring

The bridge picks a cell's CSS class by one of two rules, chosen by the
canonical name's prefix.

**Source points** are judged from the value against the thresholds loaded from
`smax.json`. Numeric: `>= err_high` or `<= err_low` is error, then
`>= warn_high` or `<= warn_low` is warning, otherwise good. A numeric point with no
thresholds is good. Strings are good if in `valid_strings`, error if not, and
unchecked if the point has no list. Any value that converts to a float is
treated as numeric. Thresholds are defined
only in `smax.json`, never in this module.

**Computed points** (prefix `monitorsystem:`) are judged from the validity the
compute engine pushed into the `validity` metadata
({py:func}`validity_to_css <slama.web.data_bridge.validity_to_css>` maps it:
`INVALID_*` is no-data, `VALID_ERROR*` error, `VALID_WARNING*` warning,
`VALID_NOT_CHECKED` unchecked, `VALID` / `VALID_GOOD` good). That verdict can
express things a value alone cannot, such as a stale heartbeat input. It is
trusted only while the point's own SMAX timestamp is younger than
`computed_max_age_s` (default 6 s, three engine ticks); the engine refreshes
the timestamp every tick, so an older one means the engine has stopped, and the
cell is grey rather than showing a frozen verdict.

## 7. Time series plots

Clicking a numeric cell opens a floating, draggable, non-blocking panel with an
interactive Plotly chart of the recent history, so the data page stays usable
while a plot is open.

- **History buffer.** `DataBridge` keeps a ring buffer per canonical name
  (`deque(maxlen=1800)`, about an hour at 2 s) of `(epoch, float)` samples. It
  is filled on every `fetch_cell` for numeric values only; strings, booleans
  and out-of-range values are skipped. There is no persistence: restarting the
  server clears history.
- **Endpoint.** `GET /api/history/{canonical_name:path}` returns
  `{"canonical_name", "times", "values", "thresholds"}`, where `thresholds`
  holds whichever of `warn_low`, `warn_high`, `err_low`, `err_high` the point
  defines. The name is a path parameter so its colons survive. A point with no
  history yet returns empty lists with status 200.
- **Panel.** Event delegation on `document` catches clicks on any `.plotable`
  element, including cells HTMX has swapped in. The chart is a line with
  markers, warning limits as dashed lines and error limits as dotted lines, a
  UTC time axis, and the dark theme. Escape or the close button closes it; clicking another cell
  replaces the chart.
- **Live append.** After each `htmx:wsAfterMessage`, if a plot is open the
  script reads the displayed value from the matching cell id and appends it with
  `Plotly.extendTraces`. The appended point uses the browser clock and the
  value as formatted on screen.

Design choices:

- **Server-side buffer.** It is shared by every connection, so a user opening a
  page sees history from before their session began (up to an hour). A
  client-only buffer would show nothing on first click.
- **HTTP for history.** The fetch is a one-time request with a potentially large
  payload; keeping it off the WebSocket leaves that protocol as HTML fragments
  plus small settings messages.
- **Numeric points only.** Strings have no meaningful numeric series; an event
  log for them is a possible later addition.

## 8. Running

```bash
# plain Uvicorn; host and port come from the environment
SMAX_PORT=6380 uvicorn slama.web.server:app --reload --port 8000

# or the module CLI, which sets the environment for you
python -m slama.web.server --smax-host localhost --smax-port 6380 \
    --web-port 8000 --reload
```

`--site-root` (or `SLAMA_SITE_ROOT`) is also accepted, for the benefit of
anything the process imports that reads site files. On the observatory system
Valkey listens on 6379, so use `--smax-port 6379` or `SMAX_PORT=6379`. Open
`http://localhost:8000/`. Data comes from whatever writes to SMAX: the
observatory feeds, a snapshot database, or the compute engine.

## 9. Known limitations and planned work

- **Each connection polls SMAX itself.** Every WebSocket runs its own
  `fetch_all` per cycle, so SMAX load grows with the number of clients, and
  because history is recorded inside `fetch_cell`, each connected client
  also appends its own sample of each point to the shared buffer. With several
  viewers the buffer holds duplicate samples and spans less than an hour. A
  single shared fetch loop that all connections read from would fix both.
- **No `--as-of` for the server.** Computed points written with a replayed
  clock look stale to the freshness rule in section 6; `computed_max_age_s` is
  not configurable from the command line.
- **Deployment.** A reverse proxy (Nginx), a systemd service and WebSocket
  reconnection logic are not yet implemented.
