# SMA monitor, fault, alarm, and web display

This package encompasses python, jinja2, css, JSON, HTML and JavaScript
required to server and view SMA monitor data.  It also includes a simple
simulator for end-to-end testing.

For more info on the server and display design see web/DESIGN.md.

### Install

Assuming you have  python 3.11+ already installed.

```
     cd slama
     uv sync
     pip install -e .

```

### Run

1.  Start the server:
```
        uv run uvicorn slama.web.server:app --reload --port 8000
```

2.  Open your browser to ``localhost:8000``. You should see:

    <img src="docs/source/static/SMAmonitorweb.png" alt="SMA Monitor web page" width="600" height="253">

    Clicking on one of the tiles opens that monitor page.   "Connecting..." will change to "Connected."

3.  Run the observation simulation program. This will simulate a observation:  Flux calibrator, Bandpass cal, gain cal, source, gain cal, source, etc.
  
```
        cd src/slama 
        uv run fakeobs.py
```

4. You can change the default calibrators and integration time with command line arguments (*not fully tested*).  See
     
``` 
        uv run fakeobs.py --help
```


### Monitor subsystem compute engine

`slama.monitor.compute` is a small daemon that reads existing SMAX monitor
points, derives new values/validities from them (counts, rollups, min/max,
etc.), and writes the results back to SMAX under a `monitorsystem:` table so
they show up in the web display like any other point. What it computes is
driven entirely by `src/slama/conf/computations.json` (which functions,
which inputs); see `docs/monitorsystem_writer_design.md` for the full
design.

**Run it** (needs a running SMAX/Valkey server, default `localhost:6380`).
Note: 6380 is the dev-system default because the OS's own Redis has already
claimed the standard port 6379; on the actual observatory system Valkey runs
on 6379, so pass `--port 6379` there:

```
        cd src/slama
        uv run python -m slama.monitor.compute conf/computations.json
```

Useful flags:

```
        --once              run a single tick and exit (no long-running loop)
        --interval SECONDS  override the loop interval from computations.json
        --smax-json PATH    path to the SMAX schema (default: conf/smax.json)
        --host / --port     SMAX host/port (default: localhost / 6380)
        --log-level LEVEL   stdlib logging level (default: INFO)
```

**Test it against a live system**

1. Start SMAX/Valkey, then start `fakeobs.py` (or the real observatory
   feeds) in one terminal to populate the source points the engine reads
   (e.g. `antenna:{1..8}:is_online` for the bundled example computation).
2. In another terminal, run a single tick and inspect the result:

```
        uv run python -m slama.monitor.compute conf/computations.json --once
        redis-cli -p 6380 HGETALL monitorsystem:array
```

   The value should reflect the source points (e.g. a count of antennas
   currently online), and the validity metadata can be checked via
   `SmaxRedisClient.smax_pull_meta("validity", "monitorsystem:array:antennas_online")`.

3. **First-run gotcha**: `MonitorSystem.read_all()` (shared with the fault
   system) eagerly pulls *every* point declared in `smax.json`, including
   the compute engine's own `monitorsystem:` outputs, before the engine
   computes anything. On a schema where an output point has never been
   written, the very first tick raises `SmaxKeyError`. Seed each declared
   output point with an initial value once (e.g. `smax_share("monitorsystem:array", "antennas_online", 0)`)
   before the engine's first run.
4. If the target Valkey instance doesn't have every point in `smax.json`
   populated (common on a partial dev setup), point `--smax-json` at a
   trimmed schema file containing only the points under test, rather than
   fighting `read_all()`'s all-or-nothing sweep of the full ~12,000-point
   production schema.

### Testing

Eventually there will be a pytest suite.  
