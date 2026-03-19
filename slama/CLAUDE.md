# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Background

The Submillimeter Array (SMA) is a collection of 8 radiotelescopes working
in tandem as an interferometer.  The SMA observes in the millimeter and
submillimiter wavelength bands. The SMA is located at the summit of Mauna
Kea in Hawaii.

## Project Overview

**SLAMA** (SMA LMA code) is a Python package for implementing a monitoring
system for the SMA observatory instruments, similar to CARMA's monitor
system.  It reads/writes monitor point data via an SMAX (SMA Extended)
server backed by Redis/Valkey on `localhost:6380`.  Ultimately, the monitor
data will be sent to a web based display system that will allow users to
examine telemetry from different SMA subsystems.

## Commands

**Install (development mode)**:
```bash
uv pip install -e slama
```

**Run tests** (require a running SMAX/Redis server):
```bash
cd src/slama
uv run test/test_smax.py       # Basic Redis I/O connectivity
uv run test/test_plot.py       # Real-time plot (requires concurrent smax_share() calls)
uv run test/treetest.py        # TreeLib hierarchy test (no server needed)
```

**Simulate observatory data**:
```bash
uv run fakeobs.py
```

## Architecture

### Data Flow
```
JSON config (conf/mpdefs.json, conf/smax.json)
    → MonitorPoint / MonitorSystem objects
    → SmaxRedisClient (SMAX library, localhost:6380)
    → Updater/Writer classes (read/write)
    → Visualization (plot/, mptab.py)
```

### Key Modules

**`src/slama/monitor/`** — Core monitoring abstractions:
- `MonitorPoint` — Single monitored variable, extends `SmaxVarBase`. Has `canonical_name` (e.g. `RM:acc1:RM_TRACK_EL_F`), numeric error/warning thresholds, and a `Validity` enum state.
- `MonitorPointList` — `UserList` of MonitorPoints, loaded from `mpdefs.json` via `MonitorPointList.from_file(path)`.
- `MonitorSystem` — Extends `treelib.Tree`; builds a full hierarchy from `smax.json` with `MonitorSubsystem` branch nodes and `MonitorPoint` leaf nodes.
- `MonitorListUpdater` / `MonitorPointUpdater` — Pull current values from SMAX backend.
- `MonitorPointSubscriber` — Subscribe to changes; invokes callback when a monitor point updates.
- `MonitorPointWriter` — Writes values back to SMAX via `smax_share()`.

**`src/slama/plot/`** — Visualization:
- **Important** The code  in this subdirectory is mostly prototype and test code and will not be the final display mechanism. However, it captures some ideas about what the final displays may look like.
- `MonitorPointPlot` — Real-time matplotlib plot for a single monitor point.
- `MpTableWidget` (PyQt6) — Grid table: rows = monitor points, columns = array antennas, color-coded by validity.
- `MpGridWidget` (PyQt6) — Label+value grid display.
- `MainWindow` (PyQt6) — Full GUI, updates every 2 seconds via `QTimer`.

**`src/slama/fakeobs.py`** — Simulates observatory observations; writes fake antenna tracking, weather, and tsys data to SMAX.

**`src/slama/recursewithtreelib.py`** — Utility that recursively builds a `treelib.Tree` from nested JSON.

### Configuration Files

- `src/slama/conf/mpdefs.json` — Monitor point definitions with validation thresholds (`warn_low`, `warn_high`, `err_low`, `err_high`).
- `src/slama/conf/smax.json` — Large (~107KB) hierarchical SMAX system configuration used to build `MonitorSystem`.

### Validity States (`monitor/monitorpoint.py`)

`Validity` enum covers: `INVALID_NO_DATA`, `INVALID_NO_HW`, `INVALID_HW_BAD`, `VALID`, `VALID_NOT_CHECKED`, `VALID_GOOD`, `VALID_WARNING`, `VALID_ERROR`, `VALID_WARNING_LOW/HIGH`, `VALID_ERROR_LOW/HIGH`.

### SMAX Backend

SMAX data is addressed as `table:key` pairs. The SMAX library (`smax-python`) provides `SmaxRedisClient`, `SmaxVarBase`, and `smax_share()`. The server runs at `localhost:6380` (not default Redis port 6379).

## Dependencies

- `smax` — from `ssh://git@github.com/Smithsonian/smax-python.git`
- `treelib` — hierarchical monitor system tree
- `astropy` — time/units handling
- `PyQt6` — GUI table/grid display
- `matplotlib`, `numpy`
