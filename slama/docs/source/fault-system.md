# Fault system

The fault system watches a configured set of critical monitor points,
reports **root causes**, and publishes every node's state to SMAX
(`faultsystem:state`). When an upstream failure takes down a dozen
downstream points, the operator should get one alert, not thirteen.

## Concepts

Fault node
:   A compute-engine output (`monitorsystem:*`). The engine decides what is
    wrong; the fault system decides what to report. Raw RM and DSM points
    are engine inputs, never fault nodes. `FaultConfig` rejects any other
    name.

Verdict
:   The validity the engine pushed for the point (`smax_push_meta`), or
    `INVALID_NO_DATA` when the point is absent from SMAX, has no metadata,
    or its SMAX timestamp is older than `computed_max_age_s`. The web
    display uses the same function,
    {py:func}`computed_validity <slama.monitor.computed_verdict.computed_validity>`,
    so the fault system and the display always agree.

Fault
:   A verdict in `FAULT_STATES`: `INVALID_NO_DATA`, `INVALID_NO_HW`,
    `INVALID_HW_BAD`, `VALID_ERROR`, `VALID_ERROR_LOW` or
    `VALID_ERROR_HIGH`. Warnings and `VALID_NOT_CHECKED` are **not**
    faults. The engine returns `VALID_NOT_CHECKED` for "does not apply
    now": an off-array antenna, a Gunn the band does not need, an empty
    smainit slot.

Parents are causal, not hierarchical
:   Each node lists `parents`: the points whose failure *causes* this one to
    fail (a dead host upstream of its antenna's drive). It has nothing to do
    with the colon-separated canonical-name hierarchy.
    `monitorsystem:engine:heartbeat` is added as a parent of every other
    node, so a stopped engine is one fault.

Root fault
:   A debounced fault none of whose parents is currently faulted. Only
    root faults dispatch actions.

Debounce
:   A fault must persist for its filter before it counts:
    `no_data_filter_s` while the verdict is `INVALID_NO_DATA`,
    `transient_filter_s` otherwise. See [Debounce](#debounce).

Context
:   Points read with a node and attached to its event (a Gunn's PLL IF power
    and noise, a slot's program name). They never fault on their own.

Action
:   Anything with `fire(event: FaultEvent) -> None`. Version 1 ships
    {py:class}`LogFileAction <slama.fault.actions.LogFileAction>`. A new type is a class, a builder function, and an entry
    in `ACTION_TYPES`; {py:class}`FaultSystem <slama.fault.faultsystem.FaultSystem>` itself does not change.

## The shipped DAG

`conf/faults.json` has 374 nodes, all under `monitorsystem:`:

| Node | Parents (plus the heartbeat) | Filters (transient / no-data) | Context |
|---|---|---|---|
| `engine:heartbeat` | none | 5 / 5 | |
| `smainit:{h}:report_age` (13 hosts) | | 5 / 15, `onset_s` 70 | |
| `smainit:{h}:slot:{j}:status` (312) | `report_age` | 5 / 90 | `slot:{j}:name` |
| `smainit:acc{i}:process:{tune6,servo}` (16) | `report_age` | 5 / 90 | |
| `antenna:{i}:drive_fault` (8) | `acc{i}` `report_age`, `process:servo` | 5 / 100 | |
| `antenna:{i}:yig1_lock_fault` (8) | `acc{i}` `report_age`, `process:tune6` | 5 / 100 | |
| `antenna:{i}:gunn{1,2}_lock_fault` (16) | `yig1_lock_fault`, `acc{i}` `report_age`, `process:tune6` | 5 / 110 | `gunn{n}_pll_ifpower`, `gunn{n}_pll_noise` |

The computed points behind these nodes are described in
[](monitorsystem_writer_design.md) §10.

- The gunn nodes list `report_age` and `process:tune6` directly, not only
  through yig1. A parent hides its children only while it is *itself*
  faulted, and a yig1 lock input freezes at its last value when `acc{i}`
  dies, so a frozen-GOOD yig1 would let gunn1's `INVALID_NO_DATA` through
  as a root.
- A dead tune6 or servo shows as two roots: its slot node and its process
  node. The LO and drive faults stay hidden. This duplicate was accepted
  (2026-11-03); dedup limits it to one extra event per episode.

## Configuration

A small config with the new keys:

```json
{
  "defaults": {
    "interval_s": 2,
    "transient_filter_s": 5,
    "no_data_filter_s": 15,
    "computed_max_age_s": 6
  },
  "actions": { "log": { "type": "log_file", "path": "/tmp/slama-faults.log" } },
  "faults": [
    { "canonical_name": "monitorsystem:engine:heartbeat",
      "no_data_filter_s": 5, "actions": ["log"] },
    { "canonical_name": "monitorsystem:smainit:acc1:report_age",
      "onset_s": 70, "actions": ["log"] },
    {
      "__each__": { "over": "0-23", "as": "j", "template": {
        "canonical_name": "monitorsystem:smainit:acc1:slot:{j}:status",
        "parents": ["monitorsystem:smainit:acc1:report_age"],
        "no_data_filter_s": 90,
        "context": ["monitorsystem:smainit:acc1:slot:{j}:name"],
        "actions": ["log"]
      }}
    }
  ]
}
```

| Key | Default | Meaning |
|---|---|---|
| `transient_filter_s` | `defaults` | Debounce for every fault state except `INVALID_NO_DATA`. |
| `no_data_filter_s` | `defaults`, else `transient_filter_s` | Debounce while the verdict is `INVALID_NO_DATA`. |
| `computed_max_age_s` | `defaults`, else 6 | Oldest acceptable age of the point's SMAX timestamp. |
| `onset_s` | the node's `computed_max_age_s` | How long the node takes to *notice* its fault; used only for the parent-lag check. |
| `context` | `[]` | `monitorsystem:*` points attached to the node's events. |

An `__each__` template may itself be an `__each__` block (host by slot).

{py:meth}`FaultConfig.from_file <slama.fault.faultconfig.FaultConfig.from_file>`
checks, and a malformed config fails at load, not at the first fault:

- every action and parent reference resolves, and canonical names are unique;
- every node and context name is a `monitorsystem:*` point;
- `monitorsystem:engine:heartbeat` is declared (it then becomes a parent of
  every other node);
- **parent lag:** every child's `no_data_filter_s` is at least each parent's
  `onset_s + max(transient_filter_s, no_data_filter_s)`.

`onset_s: 70` on the `report_age` nodes is smainit's host-down age. The
level that makes `report_age` an ERROR lives in `smax.json` (`err_high` /
`err_low`); `faults.json` only states how long that detection takes. A test
(`fault/test/test_shippedconfig.py`) fails if the two differ.

## Parent lag

When a host dies, its children's inputs stop updating. Some children read
`INVALID_NO_DATA` within seconds; the host itself is only "down" once its
report is 70 s old. Two rules keep the host as the one root:

- **A faulted parent hides its children**, whether or not the parent has
  debounced yet.
- **A hidden child's clock restarts every tick it is hidden.** Once its
  parents clear, it must stay faulted for its full filter on its own before
  it reports. Without this, recovery floods: the engine writes the heartbeat
  first and its other ~1000 outputs over the next second or so, and a
  host's RM inputs lag its smainit report by a tick or two, so children
  still stale when the parent clears would already be past their filters.
- **A child's `no_data_filter_s` outlasts its parents' detection time**
  (checked at load). A child made stale by a dead parent is still
  debouncing when the parent faults.

Only `INVALID_NO_DATA` waits the long filter. A real unlock has fresh inputs
and reads `VALID_ERROR`, so it alerts on the short `transient_filter_s`
(about 5 s), not after 100 s.

The rule is conservative: detection time uses the parent's longer filter,
and it adds up along a chain (yig1's detection, 6 + 100 s, is why the gunn
nodes need 110 s). An antenna input outage with no host or process fault
behind it alerts after 100-110 s.

## What one tick does

{py:meth}`FaultSystem.tick() <slama.fault.faultsystem.FaultSystem.tick>`:

1. {py:meth}`MonitorSystem.read <slama.monitor.monitorsystem.MonitorSystem.read>`
   refreshes only the watched points
   ({py:attr}`FaultSystem.watched_names <slama.fault.faultsystem.FaultSystem.watched_names>`:
   the nodes, then their context points), not the whole tree.
2. Each node's `validity` metadata is pulled and its verdict computed, with
   "now" from the fault system's wall clock (which `--as-of` sets).
3. Each node is classified faulted or not. A node recovering resets its
   debounce and dedup state.
4. A node is **debounced** once faulted for the filter its current verdict
   picks (see [Debounce](#debounce)).
5. Root detection: debounced and no parent faulted. A node with a faulted
   parent is hidden, and its episode start is reset to this tick.
6. Ignore patterns (`fnmatch`, optional TTL) suppress dispatch only.
   An ignored node still counts as faulted for root detection, so ignoring
   a cause does not promote its consequences to roots.
7. Dedup: an event fires once per validity transition, not every tick.
8. `Action.fire(FaultEvent)` for each action bound to the node. The event
   carries the node's value and its context values.
9. Every node's state is published as one JSON snapshot:
   `faultsystem:state`, then `faultsystem:heartbeat` (see
   [Published state](#published-state)). A publish failure is logged and
   does not stop the tick.

## Debounce

A node is **debounced** once it has been in a fault state continuously for
at least the filter its **current** verdict picks: `no_data_filter_s` for
`INVALID_NO_DATA`, `transient_filter_s` for every other fault state. Only a
debounced node can be reported.

- **Any fault state counts.** The node need not stay in the *same* state:
  `VALID_ERROR` followed by `INVALID_NO_DATA` is one continuous episode.
- **Start time.** The first tick that sees the node in a fault state sets
  {py:attr}`FaultNode.first_fault_t <slama.fault.faultnode.FaultNode.first_fault_t>`,
  on the monotonic clock. `--as-of` sets only the wall clock, so it does
  not change debounce.
- **Filter by current verdict, time from episode start.** With filters of
  5 s and 15 s:
  - `VALID_ERROR` at t = 0, then `INVALID_NO_DATA` from t = 3: debounced at
    t = 15, not t = 5.
  - `INVALID_NO_DATA` at t = 0, then `VALID_ERROR` from t = 10: debounced at
    t = 10, the first `VALID_ERROR` tick, because 10 ≥ 5.

  A change of verdict can move the deadline to the other filter, but never
  restarts the clock.
- **Hidden restarts the clock.** Each tick a parent is faulted, a hidden
  node's start time is set to that tick. Its episode effectively begins
  when nothing above it is faulted any more, so it reports a full filter
  after its parents clear (5 s for `VALID_ERROR`, 100-110 s for
  `INVALID_NO_DATA` in the shipped DAG). Its dedup state is kept, so a node
  reported before its parent failed does not fire again with the same
  validity.
- **Reset.** Any tick that reads a non-fault state (`VALID_GOOD`, a
  warning, `VALID_NOT_CHECKED`) clears the start time and the dedup state.
  The next fault starts a new episode.
- **Tick granularity.** The check runs only at ticks, so the real delay is
  the filter rounded up to the next tick (5 s at a 2 s interval is 6 s).
  For the same reason `--once` (one tick) reports nothing unless the
  filter is `0`.
- **Debounced is not reported.** A debounced node is still dropped when a
  parent is faulted (not a root), when an ignore pattern matches it, or
  when it was already reported with the same validity (dedup).
- **Flapping.** A node that alternates between fault and non-fault faster
  than its filter never debounces, because each non-fault tick resets it.
  This is a persistence filter, not a chatter filter.

`run_forever()` ticks at the interval and catches and logs a failed tick
rather than dying. `ignore`, `unignore`, `set_interval`, `reload_config`
and `stop` are thread-safe and may be called from another thread.

## Published state

The three processes talk only through SMAX, so the fault system publishes
what it decided each tick, for the Fault System display page and anything
else that wants it. It writes two points in its own table:

| Point | Type | Value |
|---|---|---|
| `faultsystem:state` | string | One JSON snapshot of every node (below). |
| `faultsystem:heartbeat` | float, s | The tick's wall-clock epoch. |

The state is written **first**, then the heartbeat, so a reader that sees a
fresh heartbeat sees a state at least as new. Judge freshness by the SMAX
write timestamp, not the heartbeat's value: during `--as-of` replay the
value is the fixed as-of time.

```json
{
  "version": 1,
  "tick": 1790094623.0,
  "interval_s": 2.0,
  "nodes": {
    "monitorsystem:smainit:acc4:process:tune6":
      {"state": "root", "validity": "VALID_ERROR", "since": 1790094421.0},
    "monitorsystem:antenna:4:yig1_lock_fault":
      {"state": "consequence", "validity": "VALID_ERROR", "since": 1790094421.0,
       "hidden_by": ["monitorsystem:smainit:acc4:process:tune6"]},
    "monitorsystem:antenna:1:drive_fault":
      {"state": "ok", "validity": "VALID_GOOD", "since": null}
  }
}
```

- Every node appears every tick, in `faults.json` order, so a reader can
  tell `ok` from "missing". The shipped config gives about 38 KB (75 KB in
  the worst case, every node hidden).
- `state`, first match wins: `ok` (not faulted); `consequence` (a parent is
  faulted; `hidden_by` lists those parents); `debouncing` (filter still
  running); `ignored` (would be `root`, but an ignore pattern matches);
  `root`. A root stays `root` on the ticks after its event: dedup limits
  events, not state. An ignore only replaces `root`, so the page always
  shows what the fault system would do.
- `validity` is this tick's verdict, so a reader needs no `monitorsystem`
  metadata pulls.
- `since` is when the current fault episode began
  ({py:attr}`FaultNode.faulted_since <slama.fault.faultnode.FaultNode.faulted_since>`).
  Unlike the debounce start time it is not reset while the node is hidden,
  so it is how long the fault has really lasted.
- Readers parse with
  {py:func}`parse_snapshot <slama.fault.publish.parse_snapshot>`, which
  rejects an unknown `version`, so a format change fails loudly.
- The reader in this repository is the Fault System display page,
  `/display/faults` ({py:mod}`slama.web.fault_page`; see
  [](display-system.md)), which draws the snapshot by antenna and host.

### Why one snapshot per tick

The alternative was one SMAX point per node (`faultsystem:<node>:state` and
so on). One snapshot was chosen (2026-11-04) because:

- **Consistency.** A reader sees one tick's decisions, never a mix of two.
  With 374 separate writes, a page refresh could land mid-tick and show a
  child as a root next to a parent that is already faulted.
- **Write cost.** Two writes per tick instead of about 750 (`smax_share`
  plus validity metadata per node). Measured against local Valkey
  (2026-11-04): 1.6 ms per tick for the 38 KB snapshot, 0.16 s per tick
  for per-node writes, on top of a tick that already makes about 1,090
  reads (about 0.3 s). Network latency on site multiplies the per-node
  cost, not the snapshot's.
- **Read cost.** The page pulls one key per refresh, not 374 values plus
  their metadata.
- **One source for the DAG.** Per-node points would have to be declared in
  `smax.json` with `__each__` blocks mirroring `faults.json`, kept in step
  by a test. With a snapshot, `faults.json` is the only place the DAG is
  written; `smax.json` declares two points.
- **Given up, deliberately:** per-node history plots and generic display
  cells for fault state. Verdict history stays on the `monitorsystem:*`
  points the nodes watch.

Writing only on change was also rejected: the snapshot's own SMAX timestamp
is the reader's freshness gate, so it must be written every tick.

### Why a separate `faultsystem` table

The state lives in a new top-level table, alongside `monitorsystem`, not
under it:

- **One writer per table.** Only the compute engine writes `monitorsystem:`;
  only the fault system writes `faultsystem:`. The table says which process
  produced a key.
- **No feedback loop.** Fault nodes must be `monitorsystem:*` points, so
  the fault system cannot be configured to watch its own output.
- **Two heartbeats, two outages.** `monitorsystem:engine:heartbeat` (engine
  alive) and `faultsystem:heartbeat` (fault system alive) are separate, and
  the page needs to tell them apart.

## Running it

```bash
uv run python -m slama.fault src/slama/conf/faults.json --interval 2
tail -f /tmp/slama-faults.log
```

The compute engine must be running: every fault node is one of its
outputs, and without it the heartbeat faults and hides everything else.

- `--host`/`--port` default to the `SMAX_HOST`/`SMAX_PORT` environment
  variables, else `localhost:6380`, as for the compute engine
  ({py:func}`slama.cli_common.add_smax_args`).
- `--once` runs a single tick, logs each dispatched event, publishes the
  state, logs one line of state counts, and exits. Actions still fire.
  With the shipped filters nothing can debounce in one tick, so `--once`
  dispatches nothing; the would-be roots show as `debouncing`:

  ```text
  --once: states ok 351, consequence 9, debouncing 14, ignored 0, root 0
  ```
- `--as-of EPOCH` replaces only the wall clock, for replaying the static
  snapshot; see [](replay-as-of.md). The staleness gate uses it, so
  snapshot points read as fresh.
- There is no `--site-root`: the fault system reads no site files. Add it
  if `faults.json` ever gains `@` tokens.

A log line is the ISO time, the node, its validity, `value=`, then each
context point as `name=value` (strings with spaces are JSON-quoted):

```text
2026-09-22T16:30:23+00:00 monitorsystem:smainit:acc4:slot:8:status VALID_ERROR value=terminated monitorsystem:smainit:acc4:slot:8:name=tune6
```

## Things to know

- A tick reads only the watched points, as the compute engine does: with
  the shipped config, 718 value pulls (374 nodes, 344 context points) and
  374 metadata pulls, about 1,090 calls and 0.3 s against local Valkey. A full-tree read is
  about 13 s, longer than the 2 s interval. On-site timing is open (#50,
  #63-1).
- A watched name missing from `smax.json` is never read: a node reads
  `INVALID_NO_DATA`, a context value `None`. The fault system logs one
  `WARNING` listing such names when it loads or reloads a config. A point
  declared but absent from SMAX faults as `INVALID_NO_DATA`.
- A lock input that RM writes only on change (`staleness_s: null` in
  `computations.json`) freezes at its last value when its host dies. That
  needs no special handling: a frozen GOOD fires nothing, a frozen ERROR
  was already reported, and the host-down fault hides it once it faults.
