# Display system

The display system serves live telemetry to browsers. Everything is Python on
the server: FastAPI for routing and WebSockets, Jinja2 for HTML, HTMX for
swapping HTML fragments into the page. The team has little JavaScript
experience by design; the only hand-written JS is a few lines for the
settings controls and the Plotly plot.

## How a page is defined

One JSON file per page in `src/slama/conf/displays/`. The server discovers
the files at request time, so **adding a file adds a page** with no code
change. A page has a `name`, `description`, `update_interval` and a `layout`
of blocks rendered top to bottom:

`table`
:   Rows by columns. `columns.var`/`columns.values` expand a placeholder in
    each row's `points`: `RM:acc{ant}:RM_TRACK_EL_F` with `ant=1..8` becomes
    eight canonical names, one per column.

`grid`
:   Label and value pairs in an N-column CSS grid.

`cells`
:   Free-standing cells in a horizontal row, for singletons like the source
    name or LST.

A row or cell may carry a `format` string to override the default four
decimal places.

## Request flow

```text
GET  /                       index of all display configs
GET  /display/{name}         full page, rendered with initial values
WS   /ws/display/{name}      server pushes HTML fragments; client sends settings
GET  /api/history/{name}     JSON time series for the click-to-plot feature
```

1. **Page load.** `display_config` loads the JSON and expands templates.
   {py:meth}`DataBridge.fetch_all <slama.web.data_bridge.DataBridge.fetch_all>` pulls each value from SMAX inside
   `asyncio.to_thread` (the SMAX client is synchronous) under a 5 s timeout.
   If SMAX is down the page still renders, with `---` cells.
2. **Live updates.** The page opens the WebSocket via HTMX's `ws` extension.
   The handler runs two concurrent tasks sharing a per-connection `state`:
   a sender that sleeps `state["interval"]`, refetches, renders each block
   as a fragment with `hx-swap-oob`, and a receiver that applies client
   settings (`{"interval": 5.0, "hidden_rows": [...]}`). HTMX swaps fragments
   by element id.
3. **Plots.** Clicking a numeric cell calls `/api/history/{name}` and draws a
   Plotly time series with the thresholds overlaid.

## DataBridge and cell colours

`slama.web.data_bridge.DataBridge` turns a canonical name into a {py:class}`CellData <slama.web.data_bridge.CellData>`
(formatted value, CSS class, HTML-safe id). Two different paths decide the
class:

Source points
:   Judged from the **value** against the thresholds loaded from `smax.json`
    at start-up. Strings are checked against `valid_strings` (unchecked if
    the point has none); a numeric point with no thresholds is `cell-good`.

Computed points (`monitorsystem:` prefix)
:   Judged from the validity the compute engine pushed into the `validity`
    metadata, because that verdict can express things a value alone cannot.
    That verdict is only trusted while the point's SMAX timestamp is younger
    than `computed_max_age_s` (default **6 s**, three engine ticks). Older
    than that, the engine has probably stopped, and the cell is grey rather
    than showing a stale green.

The classes are `cell-good`, `cell-warning`, `cell-error`, `cell-nodata`
and `cell-unchecked`; `static/style.css` holds the dark observatory theme.

{py:class}`DataBridge <slama.web.data_bridge.DataBridge>` keeps a per-point ring buffer (`deque(maxlen=1800)`, about an
hour at 2 s) that feeds the history plots. The SMAX connection is created
lazily on first use so the server starts even when SMAX is down.

## Pointing the server at SMAX

`server.py` builds one module-level {py:class}`DataBridge <slama.web.data_bridge.DataBridge>` from `SMAX_HOST` and
`SMAX_PORT` (defaults `localhost` and `6380`). Set them in the environment
before starting uvicorn, or start it with `python -m slama.web.server
--smax-host H --smax-port P --web-port W`, which sets them for you.

## Adding a page

1. Find canonical names in `smax.json` (or `docs/all_monitor_points.txt`).
2. Copy a similar file in `conf/displays/` and edit.
3. Reload `http://localhost:8000/`; the new page appears in the index.

If a point belongs in a rollup, add it to `computations.json` and
`smax.json` instead and show the `monitorsystem:` name. When converting an old
curses page, every point the C reads must still feed the page, but the page
shows what the C *shows* (a derived value replaces the raw ones it was
derived from).

## Where to read more

- [](web_display_design.md): the current design (modules, templates, validity
  colouring, plots, known limitations); [](history/web_display_phases.md) is the
  implementation log it replaces.
- {py:mod}`slama.web.server`, {py:mod}`slama.web.data_bridge`,
  {py:mod}`slama.web.display_config`.
