# Architecture

## The big picture

```text
 observatory real-time systems (RM, DSM, ...)
              │ write
              ▼
 ┌────────────────────────────────┐
 │  SMAX  (Valkey/Redis :6380)    │◄──────────────┐ write monitorsystem:*
 │  table:key → value + metadata  │               │ (value + validity)
 └───────┬───────────┬────────────┘        ┌──────┴─────────────┐
         │ read      │ read                │  compute engine    │
         ▼           ▼                     │  slama.monitor.    │
 ┌──────────────┐ ┌──────────────┐         │  compute           │
 │ fault system │ │ web server   │         └──────▲─────────────┘
 │ slama.fault  │ │ slama.web    │                │ read
 │ → log/alerts │ │ → browsers   │                │
 └──────────────┘ └──────────────┘         (same SMAX, source points)
```

SLAMA never talks to the hardware. Other programs publish into SMAX; SLAMA
reads, derives, judges and presents. The three SLAMA processes are
independent: none imports another's runtime state, and they communicate only
through SMAX keys. That is what lets each be restarted, replayed or tested on
its own.

## Configuration drives behaviour

Almost nothing about *which* points matter is written in Python. It lives in
JSON under `src/slama/conf/`:

`smax.json`
:   The authoritative schema of the SMAX database: every point's canonical
    name, type, units, description and the **validity thresholds**
    (`warn_low`, `warn_high`, `err_low`, `err_high`, valid strings, state
    mappings). Thresholds live here and nowhere else, never as constants in
    code. A live database may lack metadata that `smax.json` describes, so
    treat `smax.json` as the specification and the database as one
    implementation of it.

`computations.json`
:   What the compute engine derives: for each output under `monitorsystem:`,
    which function runs over which inputs.

`faults.json`
:   Which points the fault system watches, their causal dependencies,
    debounce windows and actions.

`displays/*.json`
:   One file per web page. Adding a file adds a page; no code change.

`mpdefs.json`
:   An older, incomplete list of point definitions. Prefer `smax.json`.

`smax.json`, `computations.json` and `faults.json` use the same shorthand for
repetition (display files expand `{ant}` placeholders through a table's
`columns.var`/`columns.values` instead): an `__each__` block with an
`over` index spec (`"1-8"`, `"1-3,5,7-9"`, `"H,V"`) and a `template` whose
`{i}` placeholders are replaced per index. The expander is
`slama.monitor.monitorsystem._parse_index_set`, shared by every loader.

## Core vocabulary

Canonical name
:   A SMAX address written `table:key`, such as `RM:acc1:RM_TRACK_EL_F`. The
    web UI, fault config and compute config all refer to points this way.
    Computed points live under the `monitorsystem:` table.

Validity
:   The {py:class}`Validity <slama.monitor.monitorpoint.Validity>` enum in `slama.monitor.monitorpoint` says how far to trust
    a value: `INVALID_NO_DATA`, `INVALID_NO_HW`, `INVALID_HW_BAD`, `VALID`,
    `VALID_NOT_CHECKED`, `VALID_GOOD`, `VALID_WARNING[_LOW|_HIGH]` and
    `VALID_ERROR[_LOW|_HIGH]`. The same enum feeds the cell colours, the
    compute engine's rollups and the fault system's definition of "faulted".

Monitor point and monitor system
:   {py:class}`MonitorPoint <slama.monitor.monitorpoint.MonitorPoint>` is one variable plus its thresholds and current validity;
    {py:class}`MonitorSystem <slama.monitor.monitorsystem.MonitorSystem>` is the tree of all of them built from `smax.json`.
    See [](monitor-system.md).

## Time and clocks

Three different clocks appear in the code, and mixing them up is the usual
source of confusion:

- **SMAX timestamps**: wall-clock time of the last write to a key. These
  decide whether an input is "stale".
- **Monotonic clocks**: used by the fault system's debounce and ignore TTLs,
  and by the compute functions' sequence timing.
- **Injectable wall clock**: the compute engine and fault system both take a
  `wall_clock` callable (default `time.time`) so tests, and `--as-of`, can
  freeze time.

[](replay-as-of.md) explains why this matters for development.

## Site files

Some computations depend on files that exist on the observatory's NFS
(`/global/...`, `/otherInstances/...`), such as receiver types, dewar
temperature channels and pointing models. `slama.site_paths.site_path()`
resolves those C-era paths against, in order: `$SLAMA_SITE_ROOT`; the live
`/` if `/global/configFiles` exists; otherwise the `site/` mirror in the
repository. `slama.sitefiles` ports the C parsers.
`computations.json` refers to them with `@` tokens such as
`"over": "@rxtype:wsma"`; the grammar is in
[](monitorsystem_writer_design.md). The tests pin the root to the
mirror (`conftest.py`) so results never depend on the machine they run on.

## Package layout

```text
src/slama/
├── monitor/            MonitorPoint, MonitorSystem, Validity
│   └── compute/        compute engine: config, engine, functions
├── fault/              fault DAG, FaultSystem, actions
├── web/                FastAPI server, DataBridge, templates, static
├── coordinates/        astronomy helpers used by computations
├── sitefiles.py        parsers for observatory site files
├── site_paths.py       /global path resolution
├── smax_logging.py     quiets smax-python's own logging
└── conf/               all JSON configuration (see above)
scripts/                maintenance and inspection utilities
site/                   offline mirror of /global and /otherInstances
docs/                   this documentation
```

Astronomy helpers (horizontal/equatorial transforms, observed frequency,
the Sun's position and angular distance) are in {py:mod}`slama.coordinates.core`;
the compute function {py:func}`sun_distance_degrees <slama.monitor.compute.functions.sun_distance_degrees>`
calls into them.

The `--smax-log-level` option on the compute and fault CLIs is applied by
{py:func}`configure_smax_logging <slama.smax_logging.configure_smax_logging>`,
which also installs a {py:class}`RepeatedMissingKeyFilter <slama.smax_logging.RepeatedMissingKeyFilter>`
so a missing SMAX key is logged once, then hourly, instead of every tick.
