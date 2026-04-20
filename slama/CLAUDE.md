# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Background

The Submillimeter Array (SMA) is a collection of 8 radiotelescopes working
in tandem as an interferometer.  The SMA observes in the millimeter and
submillimiter wavelength bands. The SMA is located at the summit of Mauna
Kea in Hawaii.

## Project Overview

**SLAMA** (SMA LMA code) is a Python package for a web-based monitoring
system for the SMA observatory instruments, similar to CARMA's monitor
system.  It reads/writes monitor point data via an SMAX (SMA Extended)
server backed by Redis/Valkey on `localhost:6380`, and serves live
telemetry to browsers via FastAPI + HTMX + Jinja2. Users can browse
subsystem displays and click any numeric cell for an interactive time
series plot.

## Commands

**Install (development mode)**:
```bash
cd slama
uv sync
uv pip install -e .
```

**Run the web server**:
```bash
uv run uvicorn slama.web.server:app --reload --port 8000
```
Then open `http://localhost:8000/`.

**Simulate observatory data** (in a separate terminal, with SMAX running):
```bash
cd src/slama
uv run fakeobs.py
```

**Tests**: the legacy `test/` code is outdated per `README.md`; a pytest
suite is planned but not yet in place. `monitor/test/test_monitorpoint.py`
and `monitor/test/test_monitorsystem.py` are the current in-progress unit
tests.

## Architecture

### Data Flow
```
JSON config (conf/mpdefs.json, conf/smax.json, conf/displays/*.json)
    → MonitorPoint / MonitorSystem / DisplayConfig objects
    → SmaxRedisClient (SMAX library, localhost:6380)
    → DataBridge / Updater / Writer classes
    → FastAPI + HTMX web display (WebSocket live updates, Plotly plots)
```

### Key Modules

**`src/slama/monitor/`** — Core monitoring abstractions:
- `MonitorPoint` — Single monitored variable, extends `SmaxVarBase`. Has `canonical_name` (e.g. `RM:acc1:RM_TRACK_EL_F`), numeric error/warning thresholds, and a `Validity` enum state. `smax_type` is optional (allows loading `mpdefs.json` which lacks it); accepts `units` as an alias for `unit`.
- `MonitorPointList` — `UserList` of MonitorPoints, loaded from `mpdefs.json` via `MonitorPointList.from_file(path)`.
- `MonitorSystem` — Extends `treelib.Tree`; builds a full hierarchy from `smax.json` with `MonitorSubsystem` branch nodes and `MonitorPoint` leaf nodes.
- `MonitorListUpdater` / `MonitorPointUpdater` — Pull current values from SMAX backend.
- `MonitorPointSubscriber` — Subscribe to changes; invokes callback when a monitor point updates.
- `MonitorPointWriter` — Writes values back to SMAX via `smax_share()`.
- `recursewithtreelib.py` — Utility that recursively builds a `treelib.Tree` from nested JSON.

**`src/slama/web/`** — FastAPI web display (see `web/DESIGN.md` for full architecture):
- `server.py` — FastAPI app. Routes: `GET /` (index), `GET /display/{name}` (rendered page), `WS /ws/display/{name}` (live HTML fragment updates + client settings), `GET /api/history/{canonical_name}` (time series JSON).
- `data_bridge.py` — `DataBridge` fetches SMAX values, maps them to `CellData` with validity CSS classes (`cell-good`, `cell-warning`, `cell-error`, `cell-nodata`, `cell-unchecked`), and maintains a per-canonical-name ring buffer (`deque(maxlen=1800)`, ~1 hour at 2s) for history plots. Lazy SMAX connection; graceful degradation on failure.
- `display_config.py` — Loads `conf/displays/*.json` and expands block templates (`{ant}` placeholders → per-column canonical names). Block types: `table`, `grid`, `cells`.
- `templates/` — Jinja2 templates (`base.html`, `index.html`, `display.html`, `components/{table,grid,cells}.html`).
- `static/style.css` — Dark observatory theme with validity colors.

**`src/slama/fakeobs.py`** — Simulates observatory observations; uses `MonitorPointWriter`/`MonitorPointUpdater` to write fake antenna tracking, weather, and tsys data to SMAX.

### Configuration Files

- `src/slama/conf/mpdefs.json` — Monitor point definitions with validation thresholds (`warn_low`, `warn_high`, `err_low`, `err_high`). **Incomplete** — being filled out; `smax.json` is the authoritative schema source.
- `src/slama/conf/smax.json` — Large hierarchical SMAX system configuration used to build `MonitorSystem`.
- `src/slama/conf/displays/*.json` — One JSON file per display page (e.g. `tracking.json`, `rxH.json`). Discovered automatically by the server — adding a new file requires no code changes.
- `src/slama/tables/` — Source catalogs (`SystemSource.cat`, `mpound.cat`).

### Validity States (`monitor/monitorpoint.py`)

`Validity` enum covers: `INVALID_NO_DATA`, `INVALID_NO_HW`, `INVALID_HW_BAD`, `VALID`, `VALID_NOT_CHECKED`, `VALID_GOOD`, `VALID_WARNING`, `VALID_ERROR`, `VALID_WARNING_LOW/HIGH`, `VALID_ERROR_LOW/HIGH`.

### SMAX Backend

SMAX data is addressed as `table:key` pairs. The SMAX library (`smax-python`) provides `SmaxRedisClient`, `SmaxVarBase`, and `smax_share()`. The server runs at `localhost:6380` (not default Redis port 6379). `SmaxRedisClient` is synchronous, so the web server wraps SMAX calls in `asyncio.to_thread()` to avoid blocking the event loop.

## Dependencies

Runtime:
- `smax` — from `ssh://git@github.com/Smithsonian/smax-python.git`
- `fastapi`, `uvicorn[standard]` — web server
- `jinja2` — server-side templates
- `treelib` — hierarchical monitor system tree
- `astropy` — time/units handling
- `matplotlib`, `numpy`, `pillow`, `jsoneditor`, `ipython`

Dev (see `pyproject.toml` `[dependency-groups.dev]`): `pytest`, `pytest-xdist`, `pytest-cov`, `pytest-timeout`, `ruff`, `pre-commit`, `sphinx`, `numpydoc`.
