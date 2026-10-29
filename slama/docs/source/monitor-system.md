# Monitor system

The monitor system is the shared foundation: an in-memory model of the SMAX
database, plus the compute engine that adds derived points to it.

## MonitorPoint and MonitorSystem

`slama.monitor.monitorpoint.MonitorPoint` extends `smax.SmaxVarBase`. Each
holds:

- `canonical_name` (for example `RM:acc1:RM_TRACK_EL_F`) and SMAX type;
- optional numeric thresholds `warn_low`, `warn_high`, `err_low`, `err_high`,
  or string rules (`valid_strings`, a `state_validity` map);
- a `validity`, set when a new value arrives by comparing it to the
  thresholds.

`slama.monitor.monitorsystem.MonitorSystem` extends `treelib.Tree`. It reads
`smax.json`, expands `__each__` blocks, and builds `MonitorSubsystem` branch
nodes with `MonitorPoint` leaves. Frequently used methods:

```python
from slama.monitor import MonitorSystem

ms = MonitorSystem("src/slama/conf/smax.json")
mp = ms.get_monitor_point("RM:acc1:RM_TRACK_EL_F")
ms.read(["RM:acc1:RM_TRACK_EL_F"], client)   # pull just these
ms.read_all(client)                          # pull everything
```

`MonitorPointUpdater`, `MonitorPointSubscriber` and `MonitorPointWriter`
are the lower-level helpers for pulling, subscribing and writing through
the SMAX client.

### Validity colours

The web display colours a cell from the validity. When a curses page from
the old C monitor is ported, a computed point's validity follows how the C
code *drew* it: beep or red is an error, yellow or standout is a warning,
green or normal is good. [](records/curses_color_validity.md) holds the
full table and the deviations that were agreed.

## The compute engine

The engine reads existing points, derives new ones (counts, rollups,
min/max, "is the antenna on source", sun distance, sequence timeouts, ...)
and writes the result back to SMAX under `monitorsystem:`. A display or
fault entry then treats `monitorsystem:antenna:1:sun_distance` like any
hardware point.

### Declare, then compute

Every output must first be **declared** under the `monitorsystem` subtree of
`smax.json`, with its type, units and thresholds exactly like a hardware
point. Config loading rejects an output that is not declared, so a typo is a
load-time error rather than a silently empty cell.

Then `computations.json` wires it up:

```json
{
  "defaults": { "interval_s": 2, "staleness_s": 30, "invalid_inputs": "skip" },
  "computations": [
    {
      "output": "monitorsystem:array:antennas_online",
      "function": "count_true",
      "inputs": ["DSM:hal9000:DSM_ONLINE_ANTENNAS_V11_B"],
      "params": { "indices": [1, 2, 3, 4, 5, 6, 7, 8] },
      "staleness_s": null
    }
  ]
}
```

This entry is the real one from `conf/computations.json`. A per-antenna entry
wraps the same keys in an `__each__` block with `{i}` placeholders (see
`monitorsystem:antenna:{i}:sun_distance` in that file).

Rules enforced when the file loads:

- every `output` is declared in `smax.json` and appears only once;
- every input pattern resolves to at least one real point;
- `function` is a registered name;
- entries that consume another entry's output are topologically sorted, and
  a cycle is an error.

### What one tick does

`ComputeEngine.tick()` runs the nodes in dependency order:

1. Refresh the input points from SMAX.
2. Resolve each input to `(value, effective validity)`. An input older than
   its `staleness_s` is demoted to `INVALID_NO_DATA`, so functions never see
   stale data as fresh.
3. Short-circuit to `INVALID_NO_DATA` when a required named input is missing.
4. Call the function. It may return a bare value, a `(value, Validity)`
   pair, or, for multi-output entries, a dict of those keyed by role.
5. For a bare value, derive validity from the output's own thresholds in
   `smax.json`.
6. Write the value with `smax_share` and the validity with
   `smax_push_meta("validity", ...)`.

A downstream node sees an upstream node's result from *this* tick, not last
tick's SMAX value.

### Staleness and `staleness_s: null`

Freshness is judged from the SMAX timestamp of the input. Some real points
are written **only when their value changes** (for example the DSM list of
online antennas, which can be many hours old and still correct). Giving such
an input `"staleness_s": null` exempts it from the age check. The same
applies to a heartbeat whose *value* is a Unix time, where the function
checks the age itself.

### Adding a function

Functions live in `slama/monitor/compute/functions.py`, registered with the
`@compute_function("name")` decorator and a uniform signature
`f(inputs, ctx)`. The one hard rule is **no logic in JSON**: config wires
inputs to a function and sets a policy flag; anything more is a Python
function with a unit test. Add the output to `smax.json`, add the entry to
`computations.json`, then add tests beside
`monitor/compute/test/test_functions.py`.

### Where to read more

- [](records/monitorsystem_writer_design.md): the full design, the rejected
  alternative, multi-output entries (section 8) and site-file `@` tokens
  (section 9).
- The API reference for {py:mod}`slama.monitor.compute.engine`.
