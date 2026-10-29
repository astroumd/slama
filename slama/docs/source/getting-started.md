# Getting started

This page takes a new checkout to a running development system. Commands
run from the `slama/` directory of the repository unless noted.

## Prerequisites

- Python 3.11 or newer and [`uv`](https://docs.astral.sh/uv/).
- A SMAX server: Valkey with the SMAX Lua scripts loaded. The repository root
  (one level above this `slama/` directory) builds and starts one; see
  [](#the-smax-server).
- Network access to GitHub, because `smax-python` is installed from its git
  repository.

## Install

```bash
cd slama
uv sync                 # runtime + dev dependency group (pytest, sphinx, ruff, ...)
uv pip install -e .
```

## The SMAX server

Everything in SLAMA talks to one SMAX server. On a development machine it
listens on **port 6380**, not the usual Redis port 6379, because the
operating system's own Redis normally owns 6379. On the real observatory
system Valkey uses 6379, so there you must pass `--port 6379` or set
`SMAX_PORT=6379`. The environment variable is honoured only by the compute
engine, the web server and `fakeobs.py`; the fault system (`slama.fault`)
reads no environment variables and always needs `--port 6379`.

Check that the server is up:

```bash
redis-cli -p 6380 ping        # -> PONG
redis-cli -p 6380 DBSIZE
```

If it is not running, bring it up from the **repository root** (the
directory above `slama/`), following `INSTALL.md` there. In outline:

```bash
./configure && make setup     # writes slama_start.sh/.csh, valkey-init.sh, ...
source slama_start.sh         # sets $SLAMA and PATH; every SLAMA shell starts here
make valkey                   # builds valkey as valkey-server_sma / valkey-cli_sma
valkey-init.sh                # starts the server on 6380, then loads the Lua scripts
valkey-cli_sma -p 6380 ping   # -> PONG
```

`valkey-init.sh` copies `$SLAMA/data/sma-shared-variables.rdb` into the
current directory and starts the server from it, using
`data/valkey_sma.conf` (port 6380, `dbfilename sma-shared-variables.rdb`).
That `.rdb` is the snapshot of the live database that you develop against.
It is written back when the server shuts down, so run `valkey-init.sh` from a
scratch directory if you want the original left alone. `valkey-init.sh` does
not guard against a second instance.

:::{important}
A development database is normally a **static copy** of the live
observatory database, not a live feed. Nothing updates it. Every value in it
carries a timestamp from the day the copy was taken, so by the wall clock
all of it is stale. Read [](replay-as-of.md) before concluding that the
compute engine or the displays are broken.
:::

The host and port defaults come from the environment, so a shell that
exports them configures every tool at once:

```bash
export SMAX_HOST=localhost
export SMAX_PORT=6380
```

The compute engine, the web server and `fakeobs.py` read these variables.
The fault system does not; it takes only `--host` and `--port` (see
[](#fault-cli-differences)).

## Run the pieces

SLAMA is three independent processes that communicate only through SMAX.
You can run any subset.

### Web display

```bash
uv run uvicorn slama.web.server:app --reload --port 8000
```

or, setting the SMAX location from options rather than the environment:

```bash
uv run python -m slama.web.server --smax-port 6380 --web-port 8000 --reload
```

Open <http://localhost:8000/>. The index lists every file in
`src/slama/conf/displays/`. Against a static snapshot, cells for ordinary
source points colour normally from their frozen values, but cells for
computed `monitorsystem:` points show grey ("no data") because the web
server distrusts their old timestamps; see [](replay-as-of.md).

### Compute engine

```bash
uv run python -m slama.monitor.compute src/slama/conf/computations.json
```

The engine reads source points, derives new points under the
`monitorsystem:` table, and writes them back to SMAX. Useful flags:

```text
--once              run a single tick and exit
--interval SECONDS  override the loop interval from computations.json
--as-of EPOCH       evaluate as if the wall clock read EPOCH
--site-root DIR     where /global and /otherInstances resolve
--host / --port     SMAX location
--log-level LEVEL   stdlib logging level
```

**This writes to SMAX.** Against a snapshot copy that is acceptable, but
tell whoever owns the copy first, and keep a backup.

### Fault system

```bash
uv run python -m slama.fault src/slama/conf/faults.json
```

The fault system only reads SMAX. It logs root faults to the file named in
`faults.json` (`/tmp/slama-faults.log` in the shipped config).

(fault-cli-differences)=
:::{note}
The two daemons deliberately mirror each other but are not identical. The
compute engine has `--as-of`, `--once`, `--site-root` and honours
`SMAX_HOST`/`SMAX_PORT`; the fault system has none of these and always
defaults to `localhost:6380`.
:::

### Simulated observatory

`scripts/fakeobs.py` is meant to write simulated tracking, weather and Tsys
values so the displays move. It currently fails on import
(`MonitorPointList` is gone) and still loads the retired `mpdefs.json`, so
the simulator is not a working part of the dev loop yet. Until it is repaired,
use a snapshot database and [](replay-as-of.md).

## Run the tests

```bash
uv run pytest                 # whole suite, ~10 s, no SMAX server needed
uv run pytest -n auto         # in parallel (pytest-xdist)
uv run pytest src/slama/fault # one package
```

See [](testing.md) for what is covered and the conventions to follow.

## Build these docs

```bash
cd docs
make html                     # output in docs/_build/html
make live                     # rebuild and reload on save (sphinx-autobuild)
```

`make html` builds with warnings as errors, so a clean build is part of
the review bar for documentation changes.
