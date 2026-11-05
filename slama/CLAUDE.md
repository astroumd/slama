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

**Run the compute engine and fault system** (each a blocking foreground process; both default to SMAX `localhost:6380`):
```bash
uv run python -m slama.monitor.compute src/slama/conf/computations.json   # --interval N, --once, --as-of
uv run python -m slama.fault src/slama/conf/faults.json                   # --interval N, --once, --as-of, --smax-json, --host, --port
```
Both honour `SMAX_HOST`/`SMAX_PORT` (shared helper `slama.cli_common`). The fault CLI's `--as-of` sets only the wall clock (debounce stays on the real monotonic clock); it has no `--site-root` because it reads no site files. See `docs/source/replay-as-of.md` for `--as-of` against the static dev snapshot.

**Simulate observatory data**: `scripts/fakeobs.py` is currently broken (issue #52) and a rewrite is planned. Do not patch it.

**Tests**: a pytest suite exists (about 756 tests, about 10 s) and needs no SMAX server; tests use fakes in place of `SmaxRedisClient`:
```bash
uv run pytest -n auto
```
Tests live beside the code in `test/` subdirectories (and `scripts/test_*.py`). `conftest.py` pins the site-file root to the `site/` mirror. See `docs/source/testing.md` for areas covered and conventions (injected clocks, fake clients).

**Docs**: the Sphinx developer guide is in `docs/source/`; build with `make html` (warnings are errors) or `make live` from `docs/`.

## Architecture

### Data Flow
```
JSON config (conf/smax.json, conf/computations.json, conf/faults.json, conf/displays/*.json)
    → MonitorPoint / MonitorSystem / ComputeConfig / FaultConfig / DisplayConfig objects
    → SmaxRedisClient (SMAX library, localhost:6380)
    → three independent processes, communicating only through SMAX keys:
        compute engine (slama.monitor.compute) → writes `monitorsystem:*` points
        fault system   (slama.fault)           → root-cause faults → actions/log
        web server     (slama.web)             → FastAPI + HTMX display (WebSocket live updates, Plotly plots)
```

### Key Modules

**`src/slama/monitor/`** — Core monitoring abstractions:

- `MonitorPoint` — Single monitored variable, extends `SmaxVarBase`. Has `canonical_name` (e.g. `RM:acc1:RM_TRACK_EL_F`), numeric error/warning thresholds, and a `Validity` enum state. `smax_type` is optional; accepts `units` as an alias for `unit`.
- `MonitorSystem` — Extends `treelib.Tree`; builds a full hierarchy from `smax.json` with `MonitorSubsystem` branch nodes and `MonitorPoint` leaf nodes. `_parse_index_set` expands the `__each__` repetition shorthand shared by every JSON loader.
- `MonitorPointUpdater` — Pulls current values from SMAX backend.
- `MonitorPointSubscriber` — Subscribe to changes; invokes callback when a monitor point updates.
- `MonitorPointWriter` — Writes values back to SMAX via `smax_share()`.
- `recursewithtreelib.py` — Utility that recursively builds a `treelib.Tree` from nested JSON.

**`src/slama/monitor/compute/`** — Compute engine (see `docs/source/monitorsystem_writer_design.md`): `ComputeConfig` loads `computations.json`; `ComputeEngine` ticks, resolving `ComputeNode` inputs, running registered functions (`functions.py`), and writing derived points and validities under `monitorsystem:`. Accepts an injected clock/client and `--as-of` replay.

**`src/slama/fault/`** — Fault system (see `docs/source/fault-system.md`): `FaultConfig` loads `faults.json` (critical points, causal-dependency DAG, debounce windows, actions); `FaultSystem` polls validities, finds root faults, debounces and de-dupes, and dispatches `Action`s (e.g. `LogFileAction`).

**`src/slama/coordinates/`** — Spatial and spectral coordinate helpers (`core.py`).

**`src/slama/sitefiles.py`, `site_paths.py`, `smax_logging.py`, `cli_common.py`** — Site-file parsers and path resolution (see Configuration Files), shared SMAX logging setup, and the shared CLI `--host`/`--port` (`SMAX_HOST`/`SMAX_PORT`) defaults.

**`src/slama/web/`** — FastAPI web display (see `docs/source/web_display_design.md` for full architecture):

- `server.py` — FastAPI app. Routes: `GET /` (index), `GET /display/{name}` (rendered page), `WS /ws/display/{name}` (live HTML fragment updates + client settings), `GET /api/history/{canonical_name}` (time series JSON).
- `data_bridge.py` — `DataBridge` fetches SMAX values, maps them to `CellData` with validity CSS classes (`cell-good`, `cell-warning`, `cell-error`, `cell-nodata`, `cell-unchecked`), and maintains a per-canonical-name ring buffer (`deque(maxlen=1800)`, ~1 hour at 2s) for history plots. Lazy SMAX connection; graceful degradation on failure.
- `display_config.py` — Loads `conf/displays/*.json` and expands block templates (`{ant}` placeholders → per-column canonical names). Block types: `table`, `grid`, `cells`.
- `templates/` — Jinja2 templates (`base.html`, `index.html`, `display.html`, `components/{table,grid,cells}.html`).
- `static/style.css` — Dark observatory theme with validity colors.

**`scripts/`** — Maintenance scripts (`dump_redis.py`, `printmonsys.py`, `curses_completeness.py`, `compare_monitor_points.py`, ...) and `fakeobs.py` (broken, see Commands).

### Configuration Files

- `src/slama/conf/smax.json` — Monitor point definitions with validation thresholds (`warn_low`, `warn_high`, `err_low`, `err_high`). This is the authoritative schema source and the hierarchical system configuration used to build `MonitorSystem`. The database does not contain validities, so they are captured here, and only here (never as code constants).
- `src/slama/conf/computations.json` — Compute engine definitions: each derived `monitorsystem:` output, its function and inputs.
- `src/slama/conf/faults.json` — Fault system config: critical points, causal DAG, debounce, actions.
- `src/slama/conf/displays/*.json` — One JSON file per display page (e.g. `tracking.json`, `rxH.json`). Discovered automatically by the server — adding a new file requires no code changes.
- `src/slama/tables/` — Source catalogs (`SystemSource.cat`, `mpound.cat`).
- `site/` — Offsite mirror of the observatory's `/global` and `/otherInstances`, laid out as a fake filesystem root. 
    -  `slama.site_paths.site_path("/global/...")` resolves C paths against `$SLAMA_SITE_ROOT`, else live `/` when `/global/configFiles` exists, else this mirror; 
    - `slama.sitefiles` ports the C parsers (`rxtype.conf`, `loadtype.conf`, `dewarTemp.conf`, `wselect.conf`, `fire/ignoreAntSmoking.txt`, per-antenna `pointingModel`). `/global` and `/otherInstances` are detected separately (each by its own marker dir). 
    - `computations.json` reads them via `"over": "@rxtype:wsma"` / `"@loadtype:!wsma"` and `"@dewarTemp:{i}:ch4_index"` / `"@wselect:{i}"` / `"@smokeIgnore:{i}"` / `"@tiltDefault:{i}"` params; the token grammar and rules are in `docs/source/monitorsystem_writer_design.md` §9. 
    - Provenance in `site/README.md`; tests pin the root to the mirror (`conftest.py`).

### Validity States (`monitor/monitorpoint.py`)

`Validity` enum covers: `INVALID_NO_DATA`, `INVALID_NO_HW`, `INVALID_HW_BAD`, `VALID`, `VALID_NOT_CHECKED`, `VALID_GOOD`, `VALID_WARNING`, `VALID_ERROR`, `VALID_WARNING_LOW/HIGH`, `VALID_ERROR_LOW/HIGH`.

When porting a curses page, pick a computed point's validity from how the C draws it (beep / red → ERROR, yellow or standout → WARNING, green / normal → GOOD); the full mapping and recorded deviations are in `docs/source/curses_color_validity.md`.

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
