# Fault system redesign: options and decision history

:::{note}
Historical record, kept as written. It holds the options weighed while
redesigning the fault system for issues #55 and #56 (2026-11-03 to
2026-11-05), and why each one lost. The current design is
[](../fault-system.md), with the computed points in
[](../monitorsystem_writer_design.md) §10 and the pages in
[](../display-system.md). The current design wins where they differ.
:::

**Status:** decided; implemented in PRs #64 to #70 and the documentation
pass that follows them.
**Decided by:** Marc, on the dates given.

The cost given for each rejected option is the one stated when the
options were put to Marc. Where none was stated, the entry only records
the choice. Some options lost to a fact found later, not to a judgement
that they were worse; those entries say so.

## Verdicts and the DAG

### Where a node's verdict comes from (2026-11-03)

- **Chosen: computed points.** Fault nodes watch `monitorsystem:*`
  points. The verdict is the validity the engine pushed, gated on the
  point's SMAX write age, the same gate the web display uses. Raw RM
  points are engine inputs only.
- **Rejected: raw RM points with `smax.json` levels.** This avoids
  depending on the engine. But conditions like "TUNE6 busy suppresses a
  Gunn unlock" would then need logic in the DAG, a second place for
  rules the engine already expresses.
- **Rejected: mixed, per node.** It is more flexible, but it means more
  config and two code paths to test.

### TUNE6 busy (2026-11-03)

- **Chosen: new fault-only points**, GOOD while tuning is active.
  `lo_lock_ok`, which the displays use, is unchanged and still matches
  the C.
- **Rejected: change `lo_lock_ok`.** The display would no longer match
  the curses colour.
- **Rejected: busy as a DAG parent.** An unlock during tuning would then
  be reported as a "busy" root, which makes busy a fault. That is wrong.
- **Rejected: busy is not relevant.** An unlock would be a fault even
  during tuning, relying on the debounce to cover short retunes. No
  further reason was recorded.

### Which smainit hosts (2026-11-03)

- **Chosen: the 13 hosts that report `SMAINIT_REPORT_X`.**
- **Overtaken: `listDead.c`'s 17.** `crate1`, `crate2`, `crate7` and
  `crate8` have no `SMAINIT_REPORT_X` in `smax.json` or the snapshot, and
  Marc said on 2026-11-03 that the crates do not exist. Confirming that on
  site is still open (#56-3 in #50); adding them later is a config change.
- **Rejected: all 25 non-ROACH hosts.** This includes hosts the
  operators do not check today.
- **Rejected: the ROACH2 boards as well.** That is about 1,750 process
  nodes, and SWARM faults may belong under a correlator parent instead.
- **Rejected: host-level nodes only.** The DAG would be smaller, but the
  log would not name the dead process.

### Host to antenna edge (2026-11-03)

- **Chosen:** `acc{i}` down is a parent of antenna *i*'s drive and LO
  nodes, so a rebooting acc is one root that names the computer.
- **Rejected: independent subtrees.** One reboot would give up to three
  alerts.
- **Rejected: ship without the edge and verify it later.**

### PLL IF power and phase noise (2026-11-03)

- **Chosen: context only.** The values ride on the Gunn fault event. The
  C draws them with sanity ranges only, so it defines no fault level to
  port. Real levels are open as #56-1.
- **Rejected: `pll_health` parents of the lock nodes.** These would need
  invented levels.
- **Rejected: invented levels, with the points as fault nodes.**
- **Rejected: leave the points out of the DAG entirely.**

### LO structure (2026-11-03, revised the same day)

- **First chosen, then overtaken: a split per chain,** `yig1 → gunn1`
  and `yig2 → gunn2`. Reading `lo_lock_ok` (`arrayMonitor.c:2152-2158`)
  showed that the C requires yig1 plus the Gunn the rest frequency
  needs, never YIG2, and that Gunn2 pairs with YIG1.
- **Chosen: follow the C.**
  - `yig1_lock_fault` is the parent of both Gunn nodes.
  - A Gunn the band does not need reads not checked.
  - There is no YIG2 node.
- **Rejected: one `lo_lock_fault` per antenna.** This is simpler, and the
  event could say which lock dropped. But the DAG could not show YIG as
  the cause of a Gunn unlock.
- **Rejected: keep the yig2 chain, gated on use.** This keeps a YIG2
  fault node the C never checks, and assumes that YIG2 feeds Gunn2.
- **Rejected: Marc describes the real wiring,** in case the C's pairing
  is out of date.

### Off-array antennas (2026-11-03)

- **Chosen:** the fault-only points read `online` and return
  `VALID_NOT_CHECKED` off-array. Host-down nodes are not gated, because a
  dead acc still matters.
- **Rejected: `online` as a parent.** This raises a "not online" root per
  antenna, which treats normal maintenance as a fault.
- **Rejected: no gating, with the ignore API used for maintenance.**

### "Not applicable" (2026-11-03)

This covers an empty slot, a normally-dead program and absent wSMA
hardware.

- **Chosen: `VALID_NOT_CHECKED`.** `FAULT_STATES` is unchanged.
- **Rejected: drop `INVALID_NO_HW` from `FAULT_STATES`.** The new points
  could then use it for "absent", but any existing point that means
  "hardware should be there and is not" would go silent.

## Timing

### Parent lag (2026-11-03)

A child can fault in seconds while its parent (host down, 70 s) is still
being detected, so the child would be reported as the root.

- **Chosen: both fixes.**
  - (a) Hide a child while any parent is *faulted*, not only debounced.
  - (b) `FaultConfig` rejects a child whose filter is shorter than its
    parents' detection time.
- **Rejected: (a) alone.** A child that faults before its parent has
  faulted at all still reports early.
- **Rejected: (b) alone.** Every child alerts slowly.
- **Rejected: accept the extra alerts and rely on dedup.**
- **Follow-up (accepted 2026-11-03):** with (b), a real Gunn unlock
  alerted after about 75 s. The long filter therefore applies only to
  `INVALID_NO_DATA`, the verdict a dead parent causes. `VALID_ERROR`
  keeps the short filter.

### How the fault system learns the 70 s (2026-11-03)

- **Chosen: `onset_s: 70`** on the `report_age` nodes in `faults.json`,
  with a test that fails if it differs from `smax.json`'s `err_high`.
- **Rejected: derive it from `MonitorSystem` at load.** It is a single
  source, but the check would leave `FaultConfig`, and the rule "a
  threshold in seconds is a detection delay" would be implicit.
- **Rejected: hand-set filters.** Nothing would catch a later change to
  the 70 s.

### Recovery flood (2026-11-04)

A hidden child kept its episode start while hidden, so when the parent
cleared, a child still stale fired at once. After an engine restart that
could be hundreds of roots.

- **Chosen: restart the hidden child's clock** each tick a parent is
  faulted. Its dedup state is kept.
- **Rejected: a grace period after the parent clears.** It adds a
  tunable, and still floods if the engine needs longer than the grace
  period.
- **Rejected: accept the flood.**

### Engine tick cost (2026-11-03)

Phase 3 took the engine tick from 0.6 s to 1.1-1.3 s against local
Valkey.

- **Chosen: accept it for now.** On-site timing is #56-4, and the fix is
  to pipeline the engine's writes.
- **Rejected: drop the 312 slot-name outputs.** The fault page would then
  have to get program names some other way.
- **Rejected: batch the writes in phase 3.** That is an engine change
  unrelated to faults.

## Processes as fault causes

### Dead process as a parent (2026-11-03)

- **Chosen: named-process points**, `smainit:acc{i}:process:tune6` and
  `:process:servo`, as the parents of the LO and drive faults.
- **Rejected: static slot edges** (for example `slot:8`). These break
  silently when a host's smainit configuration is reordered. tune6 is
  slot 8 on acc2-6; servo is slot 6 on acc1-7 but slot 5 on acc8.
- **Rejected: defer,** leaving two roots per dead tune6.

### The duplicate root (2026-11-03)

- **Accepted:** a dead tune6 or servo shows as two roots, its slot node
  and its process node. Dedup limits this to one extra event per episode.
- **Rejected: have `smainit_slots` grey those slots.** That greys the slot
  row unlike the C, and couples two lists.

## Publishing the state

### Format (2026-11-04)

- **Chosen: one JSON snapshot per tick** in `faultsystem:state`. The
  reasons are in [](../fault-system.md), "Why one snapshot per tick".
- **Rejected: one SMAX point per node.**
  - It costs about 750 extra calls per tick.
  - A reader could see half a tick.
  - It needs a `smax.json` mirror of `faults.json`, kept in step by a
    test.
  - It would gain per-node history plots and generic cells.
- **Rejected: write only on change.** The snapshot's own write time is
  the readers' freshness gate.

### Table (2026-11-04)

- **Chosen: a new top-level `faultsystem` table.**
- **Rejected: under `monitorsystem`.** That table has one writer, the
  engine, and fault nodes must be `monitorsystem:*` points, so the fault
  system could be configured to watch its own output.

## The Fault System page

### Layout (2026-11-03)

- **Chosen: an antenna grid, a host table and "Other faults"**, generated
  from `faults.json`, so every tracked node appears.
- **Rejected: an indented DAG tree.** It follows the causal edges
  directly, but runs to about 450 rows and needs a new block type.
- **Rejected: an active-faults list.** It is compact, but healthy nodes do
  not appear, so it does not show what is tracked, which the goal asked
  for.
- **Rejected: a hand-written `displays/*.json` page.** A new node in
  `faults.json` could silently miss the page.

### Data source (2026-11-04)

- **Chosen: the published snapshot**, one pull per refresh.
- **Rejected: a generated `DisplayConfig` read through `fetch_all`.** That
  is about 750 pulls per refresh, and it sees only validities, so it
  cannot tell a root from a consequence or a fault still debouncing.

### Program names (2026-11-04)

- **Chosen: pull the name only for slots that are not `ok`.**
- **Rejected: carry context values in the snapshot.** That means snapshot
  version 2, a larger snapshot, and changing phase 5.

## The Processes page

### Reading (2026-11-04)

- **Chosen: (a) per-point reads**, with program names cached and re-read
  every minute. That is about 350 values per refresh.
- **Rejected: (b) a compute-engine JSON snapshot of smainit.** It reopens
  phase 3, and only pays off with many viewers.
- **Rejected: (c) raw `SMAINIT_REPORT_X`.** It duplicates the validity
  rules the engine already applies.
- **Rejected: a hand-written `displays/*.json` page.** Slots are
  positional; only the `name` points say which program is where.

### Viewer load (2026-11-04)

- **Chosen: per-viewer refresh loops for now.** Rollout is under 10
  viewers, and load is to be measured on site against viewers and pages
  (#56-6).
- **Deferred: one shared refresh loop per page**, the fix if load is too
  high. Option (b) above is not that fix.

### Programs on a host that stopped reporting (2026-11-05)

As first built, the label stayed as last read, so a dead host's programs
read a grey "running", and the count line filed them under "not checked".

- **Chosen: replace the text and count them.**
  - The label becomes "no report", or "---" for no data.
  - The last label moves to the tooltip.
  - The programs count as "unknown".
  - The count line adds "hosts not reporting".
- **Not chosen:**
  - replace the text only, with the count line unchanged;
  - count only: keep the grey labels and add "hosts not reporting";
  - collapse a stale host's card to its header.

  No reasons were recorded beyond the choice.

### Criticality order (2026-11-04)

- Programs are in slot order. Whether some should be listed first is for
  the observatory team (#56-5).
