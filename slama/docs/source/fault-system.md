# Fault system

The fault system watches a configured set of critical monitor points and
reports **root causes**. When an upstream failure takes down a dozen
downstream points, the operator should get one alert, not thirteen.

## Concepts

Fault
:   A point whose `Validity` is in `FAULT_STATES`: `INVALID_NO_DATA`,
    `INVALID_NO_HW`, `INVALID_HW_BAD`, `VALID_ERROR`, `VALID_ERROR_LOW` or
    `VALID_ERROR_HIGH`. Warnings are **not** faults.

Parents are causal, not hierarchical
:   Each node lists `parents`: the points whose failure *causes* this one to
    fail (a power rail upstream of a heater). It has nothing to do with the
    colon-separated canonical-name hierarchy. Two sibling leaves under
    `antenna:1:air:` are independent unless an explicit causal edge is
    written. Leaving `parents` empty is correct when no real dependency has
    been established, and the shipped `faults.json` is currently **all roots**
    for exactly that reason.

Root fault
:   A debounced fault none of whose parents is also debounced-faulted. Only
    root faults dispatch actions.

Debounce (`transient_filter_s`)
:   A fault must persist continuously for this many seconds before it
    counts. `0` disables the filter.

Action
:   Anything with `fire(event: FaultEvent) -> None`. Version 1 ships
    `LogFileAction`. A new type is a class, a builder function, and an entry
    in `ACTION_TYPES`; `FaultSystem` itself does not change.

## Configuration

The shipped `conf/faults.json` is a flat list of root nodes. A config with a
causal edge looks like this (every parent must itself be declared as a fault
entry, or the load fails):

```json
{
  "defaults": { "transient_filter_s": 5, "interval_s": 2 },
  "actions":  { "log": { "type": "log_file", "path": "/tmp/slama-faults.log" } },
  "faults": [
    {
      "__each__": { "over": "1-8", "as": "i", "template": {
        "canonical_name": "antenna:{i}:air:temperature",
        "actions": ["log"]
      }}
    },
    {
      "__each__": { "over": "1-8", "as": "i", "template": {
        "canonical_name": "antenna:{i}:air:heater",
        "parents": ["antenna:{i}:air:temperature"],
        "actions": ["log"]
      }}
    }
  ]
}
```

`FaultConfig.from_file` flattens `__each__` blocks, checks that every action
and parent reference resolves, and rejects duplicate canonical names. A
malformed config fails at load, not at the first fault.

## What one tick does

`FaultSystem.tick()`:

1. `MonitorSystem.read_all(client)` refreshes every point.
2. Each critical node is classified faulted or not. A node recovering
   resets its debounce and dedup state.
3. A node is **debounced** once faulted for `transient_filter_s` of
   monotonic time.
4. Root detection: debounced and no parent debounced.
5. Ignore patterns (`fnmatch`, optional TTL) suppress dispatch only.
   An ignored node still counts as faulted for root detection, so ignoring
   a cause does not promote its consequences to roots.
6. Dedup: an event fires once per validity transition, not every tick.
7. `Action.fire(FaultEvent)` for each action bound to the node.

`run_forever()` ticks at the interval and catches and logs a failed tick
rather than dying. `ignore`, `unignore`, `set_interval`, `reload_config`
and `stop` are thread-safe and may be called from another thread.

## Running it

```bash
uv run python -m slama.fault src/slama/conf/faults.json --interval 2
tail -f /tmp/slama-faults.log
```

## Things to know

- The fault system takes its verdict from `MonitorPoint.validity`, which
  `mp.update()` derives from the **value against the thresholds in
  `smax.json`**. It does not look at the SMAX timestamp, so a stale value
  that is within limits is not a fault. This differs from the web display,
  which does distrust old computed points (see [](display-system.md)).
- `read_all` pulls the whole tree. The `MonitorSystem.read` docstring puts
  that at about 13 s per pass against Valkey for the full `smax.json`, which
  is longer than the configured 2 s interval. Narrowing the pull to the
  watched points (as the compute engine does with `read`) is a natural
  improvement.
- The CLI has no `--as-of`; see [](replay-as-of.md).
