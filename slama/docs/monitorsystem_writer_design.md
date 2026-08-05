# Monitor Subsystem Writer — Design

**Status:** Draft for review — design phase only, no implementation.
**Branch:** `design/monitorsubsystem-writer`
**Date:** 2026-08-05

## 1. Goal

Design a *monitor subsystem writer*: a service that reads monitor points
from the SMAX database, performs computations on their values, and writes
new (derived) monitor points back to SMAX under a new top-level table
`monitorsystem:` whose paths parallel the existing SMAX hierarchy.

Requirements established with Marc:

1. **Computation kinds** (all must be supported, scalably):
   - Status/validity rollups (e.g. "antenna 1 overall status = worst
     validity of its children", "number of antennas online").
   - Simple numeric aggregates (min/mean/max/median/count over point sets,
     commanded-vs-actual deltas).
   - Arbitrary derived physics (unit conversions, formulas combining
     several subsystems — requires full Python expressiveness).
   - **Computed validities**: SMAX/Redis stores raw values only, with no
     validity. Validities must be *computed* from monitor point values
     (using the threshold logic already in `MonitorPoint.validity`) and
     persisted in the new table.
2. **Table contents**: `monitorsystem:` holds the new derived/aggregate
   points; each entry stores its validity alongside its value. The table
   schema must accommodate validities, which base SMAX does not.
3. **Point definitions**: computed points are *defined* (name, type,
   units, thresholds, description) in `conf/smax.json` under a new
   `monitorsystem` subtree, keeping `smax.json` the single authoritative
   schema. The computation configuration describes only *how* each point
   is computed. The web display and `MonitorSystem` tree therefore
   discover computed points with no extra code.
4. **Scalability**: adding computations for an additional monitor
   subsystem must be easy.

## 2. Context from the existing codebase

| Existing piece | What it provides |
|---|---|
| `MonitorSystem` (`monitor/monitorsystem.py`) | Full tree from `smax.json`; `read_all()`, `write()`, `get_monitor_point()`; `__each__` template expansion via `_parse_index_set()` |
| `MonitorPoint` (`monitor/monitorpoint.py`) | `validity` property computing `Validity` from `warn_*`/`err_*` thresholds and `valid_strings` |
| `MonitorPointWriter` | Thin wrapper over `smax_share(table, key, value)` |
| `FaultSystem` (`fault/faultsystem.py`) | A proven "read → evaluate → act" daemon: JSON config with `__each__` expansion, thread-safe `tick()` loop, injectable clock/client for tests, `reload_config()`, CLI `__main__` |
| smax-python | `smax_share`, `smax_pull`, pub/sub (`subscribe`), and generic metadata via `smax_push_meta(meta, table, value)` / `smax_pull_meta(table, meta)` |

The fault system and the monitor subsystem writer are structurally the
same engine — a periodic *evaluate-over-monitor-points* loop — differing
only in output: faults dispatch **actions** (side effects), the writer
produces **new monitor points** (data). Both designs below reuse the
`FaultSystem` orchestration pattern (tick loop, threading, reload,
test seams) rather than inventing a new one.

## 3. Shared architecture (common to both designs)

These decisions hold regardless of which design is chosen.

### 3.1 Process model

A standalone daemon (`python -m slama.msw` or similar), peer to the
fault system's `fault/__main__.py`. It owns one `SmaxRedisClient` and a
`MonitorSystem` built from `smax.json`. Poll-based `tick()` at a
configurable interval (default ~2 s, matching the display cadence), with
pub/sub subscription available later as an optimization — polling first
because computations aggregate *many* inputs, so per-input notifications
would mostly trigger redundant recomputation.

### 3.2 The `monitorsystem` subtree in `smax.json`

Computed points are declared exactly like hardware points, e.g.:

```json
"monitorsystem": {
  "antenna": {
    "__each__": {
      "over": "1-8",
      "template": {
        "status": {
          "smax_type": "integer",
          "description": "Worst validity over antenna {i} points"
        },
        "tsys_median": {
          "smax_type": "float",
          "unit": "K",
          "warn_high": 400,
          "err_high": 800,
          "description": "Median Tsys over receivers, antenna {i}"
        }
      }
    }
  },
  "array": {
    "antennas_online": { "smax_type": "integer", "warn_low": 6, "err_low": 4 }
  }
}
```

Consequences:

- `MonitorSystem` builds tree nodes for computed points automatically;
  displays reference them like any other canonical name
  (e.g. `monitorsystem:antenna:1:tsys_median`).
- Thresholds on *computed* points reuse the existing
  `MonitorPoint.validity` logic — a computed value gets its validity the
  same way a hardware value would.
- The writer can **validate at startup** that every output named in the
  computation config exists in the `monitorsystem` subtree, and warn
  about declared points that no computation produces (mirrors
  `FaultConfig`'s reference validation).

### 3.3 Storing validity alongside the value

SMAX stores one primitive (or array) per `table:key` plus standard
metadata (timestamp, type, dim, origin). Validity needs a home. Options:

- **(a) SMAX metadata table — recommended.** Use the existing generic
  metadata mechanism: `smax_push_meta("validity", "monitorsystem:...:tsys_median",
  int(Validity.VALID_GOOD))`. Keeps one canonical key per point;
  readers that don't care about validity are unaffected; `DataBridge`
  can fetch it with one extra call (or a pipelined pull).
- **(b) Companion key.** Write `...:tsys_median` and
  `...:tsys_median_validity` as sibling keys. Simplest possible reader
  story (plain `smax_pull`), but doubles the key count, pollutes the
  hierarchy with pseudo-points, and the schema in `smax.json` would need
  the companion declared or special-cased.
- **(c) Struct write.** Share a small struct `{value, validity}` per
  point. Atomic, but every consumer (displays, plots) must unpack it,
  breaking the "computed points look like any other point" property.

Option (a) preserves the parallel-hierarchy property and the uniform
reader model; the only cost is that validity and value are written in
two operations (acceptable: both carry SMAX timestamps, and readers
tolerate one-tick skew).

An open sub-question for implementation phase: whether to also push
validity metadata for *source* (hardware) points as a byproduct, since
the writer computes them anyway for rollups. Deferred — not required by
the current goal.

### 3.4 Missing/stale input policy

Uniform rule, engine-enforced (computations don't hand-roll it):

- Input missing from SMAX (`smax_pull` fails/empty) → input validity
  `INVALID_NO_DATA`.
- Input older than a configurable staleness window → treated as
  `INVALID_NO_DATA` (window per computation, with a global default).
- Each computation declares a policy for invalid inputs:
  `"skip"` (compute over the valid subset — right for medians/counts) or
  `"propagate"` (output becomes `INVALID_NO_DATA` — right for physics
  formulas where every term is required).

### 3.5 Computed-on-computed dependencies

Aggregates will feed higher aggregates (per-antenna status → array
status). The engine builds a dependency graph from declared
inputs/outputs and evaluates in **topological order within a single
tick**, so `monitorsystem:array:antennas_online` sees *this* tick's
per-antenna statuses, not last tick's. Cycles are a startup error.
(Same DAG-with-validation flavor as `FaultConfig`, so the pattern is
familiar in this codebase.)

---

## 4. Design A — Declarative recipe engine

**One generic engine + a JSON computation config + a registry of named
Python functions.**

### 4.1 Shape

New package `src/slama/msw/` (monitor subsystem writer):

```
msw/
  __main__.py      # CLI: --config, --smax-config, --interval, --once
  engine.py        # MswEngine: tick loop (FaultSystem pattern), DAG ordering
  mswconfig.py     # MswConfig: load/validate computations.json (FaultConfig pattern)
  functions.py     # registry: @msw_function("median"), worst_validity, count_valid, ...
```

New config `conf/computations.json` — each entry wires inputs to an
output through a **named function**:

```json
{
  "defaults": { "interval_s": 2, "staleness_s": 30, "invalid_inputs": "skip" },
  "computations": [
    {
      "__each__": {
        "over": "1-8", "as": "i",
        "template": {
          "output": "monitorsystem:antenna:{i}:status",
          "function": "worst_validity",
          "inputs": ["antenna:{i}:*"]
        }
      }
    },
    {
      "output": "monitorsystem:array:antennas_online",
      "function": "count_valid",
      "inputs": ["monitorsystem:antenna:1-8:status"]
    },
    {
      "output": "monitorsystem:weather:refraction",
      "function": "refraction_correction",
      "inputs": {
        "temp": "weather:temperature",
        "pressure": "weather:pressure",
        "elevation": "RM:acc1:RM_TRACK_EL_F"
      },
      "invalid_inputs": "propagate"
    }
  ]
}
```

- `inputs` is either a list (set-reduction functions get an ordered list
  of `(MonitorPoint, value, validity)` triples; glob patterns and index
  ranges expand against the `MonitorSystem` tree) or a dict (formula
  functions get named keyword inputs).
- `function` names a Python callable in the registry. Built-ins cover
  the rollup/aggregate vocabulary (`worst_validity`, `count_valid`,
  `min`, `max`, `mean`, `median`, `delta`, `any`, `all`, …). **Arbitrary
  physics enters as a registered function** — a plain, unit-testable
  Python function with a `@msw_function("refraction_correction")`
  decorator — while its *wiring* (which points feed it, where the result
  goes) stays in config.
- Function contract (uniform): `f(inputs, ctx) -> value` — the engine
  derives the output's validity from the declared thresholds in
  `smax.json`; a function may instead return `(value, Validity)` when it
  must assert validity directly (e.g. `worst_validity`).

### 4.2 Scaling story

Adding a subsystem's computations = adding entries to
`computations.json` (plus, only when new math is needed, one function in
`functions.py`). Declaring the outputs in `smax.json`'s `monitorsystem`
subtree is the other half of the change. No engine code changes.

### 4.3 Pros

- **Config-driven scaling.** The common cases (rollups, aggregates) need
  *zero* Python — same "add a JSON file/stanza, no code" property the
  displays and fault config already have. Consistent developer
  experience across the project.
- **Uniform machinery.** One engine implements staleness, invalid-input
  policy, DAG ordering, dedup, and validity-from-thresholds once; every
  computation inherits it. No way for an individual computation to
  forget the staleness rule.
- **Runtime reload.** `reload_config()` (as in `FaultSystem`) lets
  operators add/tune computations without restarting; input wiring is
  data, not code.
- **Validation.** Config cross-checks against `smax.json` at load:
  unknown inputs, undeclared outputs, cycles, unknown function names all
  fail fast with file/line context — the same guarantees `FaultConfig`
  gives today.
- **Introspection for free.** The wiring is data, so "what feeds
  `monitorsystem:array:antennas_online`?" is answerable by a trivial
  query (or a future web page), without reading Python.

### 4.4 Cons

- **Two-place definition.** A computed point is described in
  `smax.json` (schema) *and* `computations.json` (recipe). Startup
  validation catches drift, but it is still two files to edit.
- **Mini-language risk.** Input patterns, `__each__`, per-entry
  policies… the config vocabulary can creep toward a bad programming
  language. Mitigation: hard rule that *anything beyond wiring* is a
  registered Python function — no expressions in JSON, ever.
- **Indirection when debugging.** Following a value requires reading
  config + registry function, not one class. Log lines carrying
  `output ← function(inputs)` context mitigate.
- **Registry signature constraints.** Complex multi-output computations
  (one function producing several related points, e.g. az *and* el
  pointing errors) fit awkwardly into "one entry, one output"; needs a
  multi-output entry form or repeated near-identical entries.

---

## 5. Design B — Computation plugin classes

**An abstract `Computation` class; one subclass per computation (or per
subsystem's family of computations); auto-discovered and run by a thin
orchestrator.**

### 5.1 Shape

```
msw/
  __main__.py        # CLI, as in Design A
  engine.py          # MswEngine: discovery, DAG ordering, tick loop
  computation.py     # ABC + shared helpers (worst_validity etc. as functions)
  plugins/
    antenna.py       # AntennaStatus(Computation), TsysMedian(Computation)
    array.py         # AntennasOnline(Computation)
    weather.py       # RefractionCorrection(Computation)
```

```python
class Computation(ABC):
    """One unit of derived-point production."""

    #: canonical-name patterns this computation reads (globs/ranges allowed)
    inputs: ClassVar[Sequence[str]]
    #: canonical names this computation writes (must exist in monitorsystem subtree)
    outputs: ClassVar[Sequence[str]]
    interval_s: ClassVar[float | None] = None      # None → engine default
    invalid_inputs: ClassVar[str] = "skip"          # or "propagate"

    @abstractmethod
    def compute(self, inputs: InputSet) -> dict[str, Result]:
        """Map resolved input values to {canonical_name: (value, Validity|None)}."""
```

The engine still owns everything cross-cutting (resolution of input
patterns via `MonitorSystem`, staleness, DAG ordering across
computations, writing value + validity metadata, per-computation error
isolation à la `FaultSystem._dispatch`). Per-antenna instantiation uses
a parametrized constructor (`AntennaStatus(ant=3)`) registered in a
small factory list, or a class-level `over = "1-8"` the engine expands.

### 5.2 Scaling story

Adding a subsystem's computations = one new module in `plugins/` with
one or more `Computation` subclasses, plus the `smax.json` subtree
declarations. Discovery is automatic (package scan or explicit registry
list); no engine changes.

### 5.3 Pros

- **Full Python everywhere.** Physics, multi-output computations,
  intermediate state (e.g. a computation that needs the previous tick's
  value for a rate) are all natural. No config vocabulary to outgrow.
- **One place per computation.** The recipe lives in exactly one class;
  debugging is "read this class". Multi-output computations are
  first-class (`outputs` is a list; `compute` returns a dict).
- **Unit testing is idiomatic.** Instantiate the class, feed a
  synthetic `InputSet`, assert on the returned dict — no engine, no
  Redis, no config files. Matches the injectable-seams style of the
  fault system's tests.
- **Type checking and IDE support.** Inputs/outputs as class attributes
  are greppable and refactorable; mypy/ruff see everything.

### 5.4 Cons

- **Every change is a code change.** Tuning which points feed a rollup,
  or adding antenna 9, means editing Python, review, and redeploy — no
  operator-editable wiring, no runtime reload of substance
  (`reload_config` can only re-scan plugins, which means re-import
  machinery or a restart in practice).
- **Boilerplate for the common case.** The dominant computations
  (rollups, medians, counts) are one-liners wrapped in a class each;
  `plugins/` fills with near-identical subclasses. Helper base classes
  (e.g. `ReductionComputation`) reduce this but add their own hierarchy
  to learn — reinventing Design A's function registry with more
  ceremony.
- **Uniformity by convention only.** Nothing *forces* a plugin to use
  the engine's staleness/invalid-input policy correctly if it pokes at
  raw values; cross-cutting guarantees are weaker than in a
  single-engine design.
- **Schema drift is easier.** `inputs`/`outputs` live in code away from
  `smax.json`; startup validation still catches dangling names, but
  humans editing one side won't see the other in the same file or even
  the same language.

---

## 6. Comparison and recommendation

| Criterion | A: recipe engine | B: plugin classes |
|---|---|---|
| Add a standard rollup/aggregate | config stanza only | new subclass (code) |
| Add arbitrary physics | registered function + config stanza | new subclass |
| Multi-output computations | awkward (needs multi-output entry form) | natural |
| Operator tuning / runtime reload | yes (config reload) | effectively no |
| Debugging a value | config + function (two hops) | one class |
| Cross-cutting guarantees (staleness, policy) | enforced by engine | by convention |
| Consistency with existing patterns | high (faults.json, displays/*.json, `__each__`) | medium (fault Actions registry is the nearest analog) |
| Risk | config mini-language creep | plugin boilerplate sprawl |

**Recommendation: Design A**, with its function registry treated as a
first-class citizen. Rationale:

- The requirement list is dominated by rollups/aggregates over *many*
  similar point sets (8 antennas, N receivers) — exactly what
  declarative wiring plus `__each__` handles best, and exactly where
  Design B drowns in near-identical subclasses.
- Arbitrary physics still gets real Python (registered functions are
  plain functions — as testable as Design B's classes), so B's main
  advantage is reduced to multi-output ergonomics, which A can add later
  with a `"outputs": {...}` entry form if needed.
- It keeps the project's established idiom: JSON config with `__each__`
  templates, engine validates references at load, `reload_config` for
  operators — the fault system already trained everyone on this shape.

The main discipline required if A is chosen: **no logic in JSON** —
the moment a computation needs more than input wiring and a policy
flag, it becomes a registered Python function.

## 7. Open questions for Marc

1. Should the writer also publish validity metadata for *source*
   (hardware) points as a byproduct of computing rollups (§3.3), or is
   that a later, separate deliverable?
2. Naming: `slama.msw` vs `slama.monitorsystem` vs `slama.writer` for
   the package, and `computations.json` vs `monitorsystem.json` for the
   config?
3. Is one global tick interval acceptable initially, or do some
   computations need per-entry intervals from day one (§3.4 defaults
   include the hook either way)?
4. Should `monitorsystem:` computed points be eligible as fault-system
   inputs (e.g. fault on `array:antennas_online`)? Nothing prevents it —
   they're ordinary points — but it affects fault-config review.
