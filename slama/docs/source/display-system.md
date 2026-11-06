# Display system

The display system serves live telemetry to browsers. Everything is Python on
the server: FastAPI for routing and WebSockets, Jinja2 for HTML, HTMX for
swapping HTML fragments into the page. There is very little JavaScript
by design; the only hand-written JS is a few lines for the
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

Two pages are generated in code instead: the Fault System page (see
[The Fault System page](#the-fault-system-page)) and the Processes page
(see [The Processes page](#the-processes-page)).

## Request flow

```text
GET  /                       index: the generated pages, then all display configs
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

To view a replay against a static snapshot, add `--computed-max-age inf`
(environment variable `SLAMA_COMPUTED_MAX_AGE_S`) so computed cells are not
greyed for being old; see [](replay-as-of.md).

## The Fault System page

`/display/faults` shows every node of the fault DAG and its state. It is
not a `displays/*.json` page: {py:mod}`slama.web.fault_page` builds its
layout from `faults.json` (path from `--faults-json` or
`SLAMA_FAULTS_JSON`, default `conf/faults.json`), and fills it from the
fault system's published snapshot, `faultsystem:state` (see
[](fault-system.md), "Published state"). A page built from per-point pulls
would cost about 750 pulls per refresh and would only see validities, so
it could not tell a root fault from a consequence or a fault still
debouncing.

Sections, top to bottom:

Status line
:   Both heartbeats (fault system and compute engine), the snapshot's tick
    time, the engine heartbeat node, and the count of nodes in each state.

Antennas
:   Rows Host (`smainit:acc{i}:report_age`), Servo, Tune6 (the named-process
    points), Drive, YIG1, Gunn1 and Gunn2; columns Ant 1 to 8. The rows come
    from the nodes `faults.json` declares. A column is dimmed while
    `monitorsystem:antenna:{i}:online` is false.

Hosts (smainit)
:   One row per smainit host: its reporting state, the number of slots not
    `ok` (coloured like the worst of them), and a list of those slots with
    their program names, which expands on click and stays open across
    refreshes.

Other faults
:   Every node no rule above places, grouped by name prefix. Empty for the
    shipped config; it exists so a new `faults.json` node always appears.

| State | Cell |
|---|---|
| `root` | bold red, with how long the fault has lasted |
| `consequence` | dimmed red, with its duration |
| `debouncing` | amber, with its duration |
| `ignored` | grey with a red border, `ign` |
| `ok` | coloured by its validity (green, or white for not checked), blank |

Durations are `tick - since`, both from the snapshot, so a replay does not
show months; under `--as-of` the fault system's wall clock is frozen, so
every duration reads `0s`. Hover a cell for its name, validity, start time
and the parents hiding it. Fault cells have no history plot; verdict history
stays on the `monitorsystem:*` points.

Each refresh pulls the snapshot, the two heartbeats, the eight `online`
points and, only for slots that are not `ok`, the slot's program name:
about 15 pulls for a normal night. Heartbeats are judged by their SMAX
write time, with the same `computed_max_age_s` as computed cells.

| Condition | Page shows |
|---|---|
| Fault heartbeat stale (or missing) | banner "Fault system not running; states as of ..."; every cell grey |
| `faultsystem:state` missing, bad JSON or wrong `version` | banner with the reason; every cell grey |
| Engine heartbeat stale, fault system running | banner "Compute engine not running"; cells as published |
| A node missing from the snapshot | that cell grey; one warning logged |

## The Processes page

`/display/processes` shows whether each critical process is running. It
is defined by `conf/processes.json` (path from `--processes-json` or
`SLAMA_PROCESSES_JSON`), loaded by {py:mod}`slama.web.process_page`: page
name, `update_interval`, `names_refresh_s`, and a list of groups drawn in
file order. A group has a `title` and a `type`:

`heartbeat`
:   `processes`, each a `label` and a heartbeat `point`. Each shows
    `running` (green), `stopped 3m` (red, the age of the last write) or
    `missing`, judged by the point's SMAX write time with
    `computed_max_age_s`, as on the Fault System page. The shipped group
    has the compute engine and the fault system.

`smainit`
:   `hosts` and `slots` in the `__each__` grammar (`"0-23"`). One card per
    host: the host name, then each named slot's program name and status
    label (`running`, `terminated`, `quit`, ...), coloured by the
    `monitorsystem:smainit:{h}:slot:{j}:status` validity: green running,
    red otherwise, grey (not checked) for a program that normally exits.
    The card header says "no report for 3h" (red) when `report_age` is
    stale, and "no data" when it is missing. Hover a program for its slot
    and point.

A label that is not current is never shown, because an operator reads
the text before the colour. On a host that has stopped reporting, the
engine marks every program not checked but keeps its last label, so a
dead host's programs would read a grey "running". The page shows them as
"no report" instead, and a status with no data (the point is missing, or
the compute engine has stopped) as "---". Both are counted as unknown,
and the last label read is in the tooltip
({py:func}`program_row <slama.web.process_page.program_row>`).

Above the cards a count line gives running, not running, not checked and
unknown programs, and the number of hosts not reporting; "not running",
"unknown" and the host count are red when non-zero. On the 2026-11-04
snapshot: 143, 3, 0 and 15 of 161, with 3 hosts not reporting (`newdds`,
`corcon`, `m5`). A banner says "Compute engine not running: program
states are not being updated" when the engine heartbeat is stale; every
program then reads "---", because `DataBridge.fetch_cell` gates every
`monitorsystem:` point on its write time.

A hand-written `displays/*.json` page cannot draw the smainit group,
because slots are positional: which program is in which slot is only
known from the `name` points. Program names change only when smainit is
reconfigured, so they are read for every slot (312 pulls) on the first
refresh and then every `names_refresh_s` (60 s); each refresh pulls the
status of the named slots only and each host's `report_age`, about 350
values (about 0.2 s against the dev snapshot). Programs are in slot
order; whether some should be listed first is open (#56-5 in #50).

Adding a heartbeat process or an smainit host is a config edit; a new
kind of process is a new group `type` plus a reader for it. The smainit
host list is also in `smax.json`, `computations.json` and `faults.json`;
a test checks that `processes.json` matches `smax.json`.

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
  {py:mod}`slama.web.display_config`, {py:mod}`slama.web.fault_page`,
  {py:mod}`slama.web.process_page`.
