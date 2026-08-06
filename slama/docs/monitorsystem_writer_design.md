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

A standalone daemon (`python -m slama.monitor.compute`), peer to the
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

**Decided (2026-08-05):** the first deliverable writes validities only
for derived points. Publishing validity metadata for *source* (hardware)
points — which the writer computes anyway for rollups — is deferred, but
the design keeps the hook so it can be added later without rework
(centralizing validity for `DataBridge` and the fault system, which each
recompute it today).

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

### 3.5 String and sequence semantics

Some string points represent a **state machine**, e.g. a receiver tuning
sequence: intermediate states mean `VALID_WARNING` ("proceeding, but you
can't use the receiver yet"), and terminal states mean `VALID_GOOD`
(tuned) or `VALID_ERROR` (failed). This splits into two orthogonal
requirements that land in different layers:

**(1) Classification — static state → validity mapping.** "What does
this state mean?" is a per-point property, exactly like numeric
thresholds, so it belongs in the point's declaration in `smax.json` and
is evaluated by `MonitorPoint.validity` — shared by both designs. The
*current* `_string_validity()` implementation is inadequate for this:

- It reuses `err_low`/`err_high`/`warn_low`/`warn_high` as string
  collections and returns `VALID_WARNING_LOW`/`_HIGH` — "low"/"high"
  are meaningless for states, and plain `VALID_WARNING` is unreachable
  for strings today.
- With `valid_strings` set, any state not listed anywhere falls through
  to `VALID_ERROR`, so one forgotten intermediate state turns a healthy
  sequence into a reported error.

Proposed schema extension (implementation phase), legacy fields kept as
a fallback path:

```json
"tuning_state": {
  "smax_type": "string",
  "state_validity": {
    "idle": "GOOD",
    "setting_lo": "WARNING",
    "locking": "WARNING",
    "tuned": "GOOD",
    "failed": "ERROR"
  },
  "unknown_state": "ERROR"
}
```

`_string_validity()` consults `state_validity` first; the explicit
`unknown_state` policy makes never-seen states a per-point decision
instead of an accident.

**(2) Trajectory — sequence-aware validity.** Order and time matter:
"stuck in `locking` for 90 s is no longer WARNING, it's ERROR", or
"jumped from `setting_lo` straight to `tuned` — suspicious". This needs
**memory across ticks**, and it is the one place the two designs
genuinely differ (see §4.1's `ctx.state` and §5.3). Trajectory checks
are computations producing a derived point (e.g.
`monitorsystem:rx:H:tuning_status`); classification stays on the source
point itself.

### 3.6 Computed-on-computed dependencies

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

New subpackage `src/slama/monitor/compute/` (beside `monitorpoint.py`
and `monitorsystem.py` — "the compute engine of the monitor system"):

```
monitor/compute/
  __main__.py      # CLI: --config, --smax-config, --interval, --once
  engine.py        # ComputeEngine: tick loop (FaultSystem pattern), DAG ordering
  computeconfig.py # ComputeConfig: load/validate computations.json (FaultConfig pattern)
  functions.py     # registry: @compute_function("median"), worst_validity, count_valid, ...
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
    },
    {
      "__each__": {
        "over": "H,V", "as": "rx",
        "template": {
          "output": "monitorsystem:rx:{rx}:tuning_status",
          "function": "sequence_validity",
          "inputs": { "state": "rx:{rx}:tuning_state" },
          "params": {
            "stuck_timeout_s": 90,
            "expected_order": ["idle", "setting_lo", "locking", "tuned"]
          }
        }
      }
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
- `params` (optional) passes static configuration — lookup tables,
  timeouts, expected state orders — to the function. This stays inside
  the "no logic in JSON" rule: `params` values are *data*; the logic
  that interprets them lives once, in the registered function.
- Function contract (uniform): `f(inputs, ctx) -> value` — the engine
  derives the output's validity from the declared thresholds in
  `smax.json`; a function may instead return `(value, Validity)` when it
  must assert validity directly (e.g. `worst_validity`).
- **Persistent per-entry state**: the engine owns a `ctx.state` dict,
  created per config entry, that survives across ticks (cleared on
  config reload). This is what makes sequence/trajectory computations
  (§3.5) possible in a stateless-function design: `sequence_validity`
  keeps `state_entered_t` in `ctx.state` and applies `stuck_timeout_s`
  against `ctx.clock` — one generic, fake-clock-testable function
  covering every receiver via `__each__`.

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
monitor/compute/
  __main__.py        # CLI, as in Design A
  engine.py          # ComputeEngine: discovery, DAG ordering, tick loop
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
  value for a rate) are all natural. Cross-tick memory is free —
  sequence/trajectory checks (§3.5) are just instance attributes
  (`self.state_entered_t`) on a long-lived `Computation` object. No
  config vocabulary to outgrow.
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
| Sequence/state-machine checks (§3.5) | generic function + `ctx.state` + `params` | instance attributes |
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
- The sequence use case (§3.5) repeats across receivers and likely
  future sequences (antenna slewing, correlator setup) — exactly where
  one generic `sequence_validity` function plus `__each__` wiring beats
  a family of near-identical subclasses. With `ctx.state`, A handles it
  without giving up statelessness where it isn't needed.
- It keeps the project's established idiom: JSON config with `__each__`
  templates, engine validates references at load, `reload_config` for
  operators — the fault system already trained everyone on this shape.

The main discipline required if A is chosen: **no logic in JSON** —
the moment a computation needs more than input wiring and a policy
flag, it becomes a registered Python function.

### 6.1 Side-by-side sketch: the same two computations both ways

To judge day-to-day feel rather than abstract pros/cons, here are the
same two computations written out in each design: (1) per-antenna
status rollup (worst validity over each antenna's points, antennas
1–8) and (2) the receiver tuning-sequence trajectory check (§3.5).
Sketches, not implementation — signatures are illustrative.

In **both** designs, the outputs are declared identically in
`smax.json`'s `monitorsystem` subtree; that half of the work never
differs.

#### Design A: two config stanzas + one shared function

`conf/computations.json`:

```json
{
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
      "__each__": {
        "over": "H,V", "as": "rx",
        "template": {
          "output": "monitorsystem:rx:{rx}:tuning_status",
          "function": "sequence_validity",
          "inputs": { "state": "rx:{rx}:tuning_state" },
          "params": {
            "stuck_timeout_s": 90,
            "expected_order": ["idle", "setting_lo", "locking", "tuned"]
          }
        }
      }
    }
  ]
}
```

`compute/functions.py` — `worst_validity` is a built-in; the sequence
check is one generic function shared by every receiver (and any future
sequence point):

```python
@compute_function("worst_validity")
def worst_validity(inputs, ctx):
    """Value and validity are the worst Validity over the input set."""
    worst = max(item.validity for item in inputs)   # Validity is an IntEnum
    return int(worst), worst


@compute_function("sequence_validity")
def sequence_validity(inputs, ctx):
    """Trajectory check for a state-machine string point.

    Classification (state -> validity) comes from the source point's
    state_validity map (§3.5); this function only adds the
    time/order-aware layer, using engine-owned per-entry state.
    """
    state = inputs["state"].value
    now = ctx.clock()
    if state != ctx.state.get("last_state"):        # state transition
        ctx.state["last_state"] = state
        ctx.state["entered_t"] = now

    validity = inputs["state"].validity             # from state_validity map
    stuck = (now - ctx.state["entered_t"]) > ctx.params["stuck_timeout_s"]
    if validity == Validity.VALID_WARNING and stuck:
        validity = Validity.VALID_ERROR             # in-progress too long
    return state, validity
```

#### Design B: two plugin classes

`compute/plugins/antenna.py` and `compute/plugins/rx.py`:

```python
class AntennaStatus(Computation):
    over = "1-8"                                    # engine instantiates per index

    def __init__(self, i):
        self.inputs = [f"antenna:{i}:*"]
        self.outputs = [f"monitorsystem:antenna:{i}:status"]

    def compute(self, inputs):
        worst = max(item.validity for item in inputs)
        return {self.outputs[0]: (int(worst), worst)}


class TuningStatus(Computation):
    over = "H,V"
    STUCK_TIMEOUT_S = 90.0
    EXPECTED_ORDER = ["idle", "setting_lo", "locking", "tuned"]

    def __init__(self, rx):
        self.inputs = {"state": f"rx:{rx}:tuning_state"}
        self.outputs = [f"monitorsystem:rx:{rx}:tuning_status"]
        self._last_state = None                     # cross-tick memory is just
        self._entered_t = None                      # instance attributes

    def compute(self, inputs):
        state = inputs["state"].value
        now = self.clock()
        if state != self._last_state:
            self._last_state, self._entered_t = state, now

        validity = inputs["state"].validity
        if (validity == Validity.VALID_WARNING
                and (now - self._entered_t) > self.STUCK_TIMEOUT_S):
            validity = Validity.VALID_ERROR
        return {self.outputs[0]: (state, validity)}
```

#### What routine changes cost in each

| Change | Design A | Design B |
|---|---|---|
| Add antenna 9 to the rollup | edit `"over"` in JSON; runtime reload | edit `over` in class; redeploy |
| Add a median-Tsys point per antenna | new config stanza (built-in `median`) | new subclass |
| Tune stuck timeout 90 s → 120 s | config edit; runtime reload | code edit; redeploy |
| Add a second sequence point (e.g. antenna slewing) | new stanza reusing `sequence_validity` | new subclass (or refactor a shared base) |
| Add genuinely new physics | new registered function **and** stanza | new subclass |
| Unit test the tuning check | call `sequence_validity()` with fake `ctx` (fake clock/state dict) | instantiate `TuningStatus`, inject fake clock |

The sketch shows the trade concretely: the *logic* is nearly identical
Python either way; what differs is where the **wiring** lives (data vs
code) and therefore who can change it, and when.

## 7. Decisions (resolved with Marc, 2026-08-05)

1. **Source-point validities: defer, keep the hook.** The first
   deliverable writes validities only for derived points (§3.3).
   Publishing validity metadata for hardware points — centralizing what
   `DataBridge` and the fault system each recompute today — is a later,
   separate deliverable the design must not preclude.
2. **Naming: `slama.monitor.compute` + `conf/computations.json`.**
   Nesting under the existing `monitor` package keeps the "computing
   monitor points" semantics without creating a near-collision between a
   top-level `slama.monitorsystem` package and the existing
   `slama.monitor.monitorsystem` module. The config name follows the
   plural-noun `faults.json` precedent.
3. **Intervals: global only, reserve the hook.** One tick interval
   (default ~2 s) for all computations, as in `FaultSystem`, so every
   tick is a consistent snapshot for DAG ordering (§3.6). The config
   schema reserves a per-entry `interval_s` key for later; per-entry
   scheduling is out of scope for the first deliverable.
4. **Fault system may consume `monitorsystem:` points — with
   guidance.** Computed points are ordinary points and may appear in
   `faults.json` (enabling aggregate faults like "antennas_online < 4";
   a dead compute daemon shows up as stale → `INVALID_NO_DATA`, a free
   watchdog). Documented rule: when a fault watches a derived point
   whose feeding source points are also watched, declare the sources as
   causal `parents` of the derived fault so one hardware failure reports
   once, at the root.
5. **`state_validity` schema extension lands first, separately.** The
   `state_validity` / `unknown_state` extension to
   `MonitorPoint._string_validity()` (§3.5) ships as its own small
   branch/PR ahead of the writer — with tests and updated `smax.json`
   string-point entries — since displays and the fault system benefit
   immediately and independently.

**Still open: the Design A vs Design B choice (§6).** The
recommendation stands (A), but Marc has not yet decided; no
implementation until this is settled.
