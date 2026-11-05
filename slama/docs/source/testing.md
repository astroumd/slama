# Testing

```bash
uv run pytest                  # everything
uv run pytest -n auto          # parallel (pytest-xdist)
uv run pytest src/slama/fault -k debounce
uv run pytest --cov=slama      # coverage (pytest-cov)
```

Written against the repository as of this guide, the suite collects **1089
tests and runs in about fifteen seconds**. None of it needs a SMAX server (a
run with Valkey up on 6380 opened no connections to it): tests use fakes in place of `SmaxRedisClient` and build a {py:class}`MonitorSystem <slama.monitor.monitorsystem.MonitorSystem>` from
either a small fixture or the real `smax.json`.

| Area | Location | What it covers |
|------|----------|----------------|
| Compute engine | `src/slama/monitor/compute/test/` | config loading and validation, engine ticks, every compute function, the real `computations.json` |
| Monitor points | `src/slama/monitor/test/` | {py:class}`MonitorPoint <slama.monitor.monitorpoint.MonitorPoint>` validity, {py:class}`MonitorSystem <slama.monitor.monitorsystem.MonitorSystem>` tree build (fixture `fixture_smax.json`), the computed-point verdict gate |
| Fault system | `src/slama/fault/test/` | config and parent-lag validation, verdicts, debounce by verdict, root detection, dedup, ignores, actions, the published snapshot, CLI, the shipped `faults.json` against `smax.json` and `computations.json` |
| Web | `src/slama/web/test/` | {py:class}`DataBridge <slama.web.data_bridge.DataBridge>` validity to CSS mapping, computed-point freshness; the Fault System page's layout (against the shipped `faults.json`), reader, cell views and rendering; the Processes page's config (against the shipped `processes.json` and `smax.json`), names cache, views and rendering; both generated pages through the server's shared render and WebSocket push |
| Site files | `src/slama/test/` | `site_paths`, `sitefiles` parsers, logging |
| Coordinates | `src/slama/coordinates/test/` | astronomy helpers |
| Scripts | `scripts/test_*.py` | maintenance scripts |

## Conventions

- **Inject the clock.** {py:class}`ComputeEngine <slama.monitor.compute.engine.ComputeEngine>` and {py:class}`FaultSystem <slama.fault.faultsystem.FaultSystem>` accept `clock` and
  `wall_clock`. Tests pass lambdas and advance them by hand instead of
  sleeping. Do the same in new code.
- **Fake the client.** The engine accepts `client=None` to compute with no
  I/O, or a small fake with `smax_pull`/`smax_share`. The fault system
  needs a fake with `smax_pull_meta` (its verdict is the pushed validity);
  with `client=None` every node reads `INVALID_NO_DATA`.
- **Site files are pinned.** The autouse fixture in `conftest.py` points
  `SLAMA_SITE_ROOT` at the `site/` mirror, so results never depend on the
  receivers installed on the machine running the tests. A test that needs a
  different root sets the variable itself and calls
  `site_paths.reset_site_root()`.
- **Test the real configs.** `test_realconfig.py` loads the shipped
  `computations.json` and `smax.json`, and `fault/test/test_shippedconfig.py`
  checks `faults.json` against both, so a typo in any of them breaks the
  suite rather than production.
- **Document with numpydoc.** New and changed code gets full numpydoc
  docstrings; the API reference in these docs is generated from them.

## Checking against a live SMAX

Unit tests do not prove that values flow end to end. For that, run the pieces
from [](getting-started.md) against the dev database and use `--as-of` with
the compute engine ([](replay-as-of.md)). Say so before running anything that
writes to a shared database.

## Linting

```bash
uv run ruff check src      # reports existing findings today
```
