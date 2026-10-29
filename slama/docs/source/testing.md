# Testing

```bash
uv run pytest                  # everything
uv run pytest -n auto          # parallel (pytest-xdist)
uv run pytest src/slama/fault -k debounce
uv run pytest --cov=slama      # coverage (pytest-cov)
```

Written against the repository as of this guide, the suite collects **756
tests and runs in about ten seconds**. None of it needs a SMAX server: tests
use fakes in place of `SmaxRedisClient` and build a `MonitorSystem` from
either a small fixture or the real `smax.json`.

| Area | Location | What it covers |
|------|----------|----------------|
| Compute engine | `src/slama/monitor/compute/test/` | config loading and validation, engine ticks, every compute function, the real `computations.json` |
| Monitor points | `src/slama/monitor/test/` | `MonitorPoint` validity, `MonitorSystem` tree build (fixture `fixture_smax.json`) |
| Fault system | `src/slama/fault/test/` | config, debounce, root detection, dedup, ignores, actions, CLI |
| Web | `src/slama/web/test/` | `DataBridge` validity to CSS mapping, computed-point freshness |
| Site files | `src/slama/test/` | `site_paths`, `sitefiles` parsers, logging |
| Coordinates | `src/slama/coordinates/test/` | astronomy helpers |
| Scripts | `scripts/test_*.py` | maintenance scripts |

## Conventions

- **Inject the clock.** `ComputeEngine` and `FaultSystem` accept `clock` and
  `wall_clock`. Tests pass lambdas and advance them by hand instead of
  sleeping. Do the same in new code.
- **Fake the client.** The engine and fault system accept `client=None` to
  compute with no I/O, or a small fake with `smax_pull`/`smax_share`.
- **Site files are pinned.** The autouse fixture in `conftest.py` points
  `SLAMA_SITE_ROOT` at the `site/` mirror, so results never depend on the
  receivers installed on the machine running the tests. A test that needs a
  different root sets the variable itself and calls
  `site_paths.reset_site_root()`.
- **Test the real configs.** `test_realconfig.py` loads the shipped
  `computations.json` and `smax.json`, so a typo in either breaks the suite
  rather than production.
- **Document with numpydoc.** New and changed code gets full numpydoc
  docstrings; the API reference in these docs is generated from them.

## Checking against a live SMAX

Unit tests do not prove that values flow end to end. For that, run the pieces
from [](getting-started.md) against the dev database and use `--as-of` with
the compute engine ([](replay-as-of.md)). Say so before running anything that
writes to a shared database.

## Linting

```bash
uv run ruff check src
uv run pre-commit run --all-files
```
