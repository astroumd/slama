# Replaying a snapshot with `--as-of`

## The problem

A development SMAX database is a **static copy** of the live observatory
database. Nobody is writing to it. Every key carries the SMAX timestamp of the
moment it was last written *on the day the copy was taken*. In the copy used
while writing this guide, the newest source timestamp is
`1790094623`, which is 2026-09-22 16:30:23 UTC.

The compute engine decides whether an input is usable by comparing that
timestamp to the wall clock:

```python
stale = (now_wall - mp.time.unix) > staleness_s      # engine._resolve_one
```

Run it a month later and every input is weeks older than its 30 s
`staleness_s`. Every input resolves to `INVALID_NO_DATA`, every node
short-circuits, and
`python -m slama.monitor.compute conf/computations.json --once` reports
nothing but `INVALID_NO_DATA`. The code is fine; the clock is wrong.

## The fix: tell the engine what time it is

`--as-of EPOCH` replaces the engine's wall clock with a constant:

```python
# slama/monitor/compute/__main__.py
if args.as_of is not None:
    engine_kwargs["wall_clock"] = lambda: args.as_of
```

The engine already took `wall_clock` as an injectable (the same seam the unit
tests use), so the flag adds no new code path in the engine. With the clock
set to the moment the snapshot was frozen, ages compare as they would have
that afternoon, and the outputs are **written with the as-of timestamp** so
they look like they were produced then.

## Choosing the epoch

Use the newest timestamp among the **source** points. SMAX keeps a hash named
`<timestamps>` mapping each key to its last-write time:

```bash
redis-cli -p 6380 HGETALL '<timestamps>' | paste - - \
  | grep -v '^monitorsystem' | sort -k2 -n | tail -1
```

:::{warning}
Filter out `monitorsystem:` keys. Once the compute engine has written into
the database, *its* outputs carry newer timestamps (on the day this guide was
written, `1793231387`, a month after the snapshot). A plain
`HVALS '<timestamps>' | sort -n | tail -1` then returns the engine's last
write, not the end of the source data, and replaying at that time makes
the sources look a month stale again.
:::

## Running a replay

```bash
EPOCH=1790094623
uv run python -m slama.monitor.compute src/slama/conf/computations.json \
    --once --as-of $EPOCH
```

Results are logged at INFO as `name = value (VALIDITY)`. Remember this
writes `monitorsystem:*` keys into the database you point it at.

## Limits to know about

`--as-of` belongs with `--once`
:   `run_forever` also freezes, so every tick evaluates the same instant.
    That is harmless but pointless; use it to check results, not to run a
    live loop.

The fault system's flag freezes only the wall clock
:   `python -m slama.fault ... --once --as-of $EPOCH` passes the constant
    as {py:class}`FaultSystem <slama.fault.faultsystem.FaultSystem>`'s
    `wall_clock`. Its monotonic `clock`, which drives debounce
    (`transient_filter_s`) and ignore TTLs, stays real: frozen, no debounce
    could ever elapse and no fault would be confirmed. The verdict's
    staleness gate compares each point's SMAX timestamp with this wall
    clock, so points the engine wrote during an `--as-of` run (timestamped
    now, after the as-of time) read as fresh. With the shipped filters a
    single `--once` tick only starts each debounce timer and dispatches
    nothing; its log line of state counts shows the would-be roots as
    `debouncing`. `--once` also **writes** `faultsystem:state` and
    `faultsystem:heartbeat` into the database it reads (the static dev
    snapshot), and the heartbeat's value is the as-of time, not now.

The web display still uses the real clock
:   `DataBridge._computed_css_class` compares a computed point's SMAX
    timestamp to `time.time()` and greys the cell when it is older than
    `computed_max_age_s` (6 s). Outputs written with `--as-of` carry the
    snapshot-day timestamp, so by default they render as **no-data in the
    browser** even though the values are correct. To view a replay, disable
    the check when starting the server:

    ```bash
    uv run python -m slama.web.server --computed-max-age inf
    ```

    The same setting is the `SLAMA_COMPUTED_MAX_AGE_S` environment variable
    for plain uvicorn. The server has no true `--as-of` clock; `inf` simply
    trusts the pushed validity whatever its age. Source-point cells are
    unaffected, since they are judged by value.

Points written only on change look old
:   Many RM and DSM points are written only when their value changes, so
    their SMAX timestamp can be hours or days older than the rest. That is
    why `computations.json` marks them `"staleness_s": null`. A replay does
    not change this: `--as-of` fixes "now", not how often a source writes.

## When it applies

Use `--as-of` whenever you are developing against a snapshot: writing a new
compute function and checking its output, validating a `computations.json`
change, or reproducing a reported value. Do **not** use it against the live
observatory database; there the real wall clock is right, and a fixed
`--as-of` would date every output wrongly.
