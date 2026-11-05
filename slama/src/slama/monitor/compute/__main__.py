"""Command-line entry point for the monitor subsystem compute engine.

Run the compute loop in a blocking foreground process::

    python -m slama.monitor.compute conf/computations.json
    python -m slama.monitor.compute conf/computations.json --interval 2
    python -m slama.monitor.compute conf/computations.json --once

Mirrors :mod:`slama.fault.__main__` — see that module for the shared
argument conventions (SMAX host/port default to the SLAMA convention
of ``localhost:6380``, not Redis's default ``6379``).

Environment variables (used when ``--host``/``--port`` are not given,
as for the web display server, :mod:`slama.web.server`)::

    SMAX_HOST   SMAX/Redis server hostname (default: localhost)
    SMAX_PORT   SMAX/Redis server port     (default: 6380)
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from smax import SmaxRedisClient

from slama import site_paths
from slama.cli_common import DEFAULT_SMAX_HOST, DEFAULT_SMAX_PORT, add_smax_args
from slama.smax_logging import configure_smax_logging
from slama.monitor.monitorsystem import MonitorSystem

from .computeconfig import ComputeConfig
from .engine import ComputeEngine

__all__ = ["DEFAULT_SMAX_HOST", "DEFAULT_SMAX_PORT", "main"]


def _build_parser(environ=None) -> argparse.ArgumentParser:
    """Build the command-line parser.

    Parameters
    ----------
    environ : mapping or None, optional
        Environment to read ``SMAX_HOST``/``SMAX_PORT`` defaults from;
        ``None`` (the default) uses :data:`os.environ`. Injectable for
        tests.

    Returns
    -------
    argparse.ArgumentParser
        Parser whose ``--host``/``--port`` defaults come from
        ``SMAX_HOST``/``SMAX_PORT`` when set, else
        :data:`~slama.cli_common.DEFAULT_SMAX_HOST` /
        :data:`~slama.cli_common.DEFAULT_SMAX_PORT` (see
        :func:`slama.cli_common.add_smax_args`). An explicit
        ``--host``/``--port`` always wins over the environment.
    """
    parser = argparse.ArgumentParser(prog="[uv run] python -m slama.monitor.compute")
    add_smax_args(parser, environ)
    parser.add_argument(
        "config",
        type=Path,
        help="Path to the compute config (e.g., conf/computations.json)",
    )
    parser.add_argument(
        "--smax-json",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "conf" / "smax.json",
        help="Path to the SMAX monitor-system JSON (default: conf/smax.json)",
    )
    parser.add_argument(
        "--interval", type=float, default=None,
        help="Loop interval in seconds (overrides config default)",
    )
    parser.add_argument(
        "--once", action="store_true",
        help="Run a single tick and exit, instead of looping",
    )
    parser.add_argument(
        "--as-of", type=float, default=None, metavar="EPOCH",
        help="Evaluate as if the wall clock read EPOCH (Unix seconds), for "
             "replaying a static SMAX snapshot whose inputs would otherwise "
             "all be stale. Outputs are written with that timestamp.",
    )
    parser.add_argument(
        "--site-root", type=Path, default=None, metavar="DIR",
        help="Root that /global and /otherInstances paths resolve against "
             "(sets $SLAMA_SITE_ROOT; default: auto-detect, see "
             "slama.site_paths)",
    )
    parser.add_argument(
        "--log-level", default="INFO",
        help="stdlib logging level (default: INFO)",
    )
    parser.add_argument(
        "--smax-log-level", default="WARNING",
        help="Level for the smax-python library's own logging (default: "
             "WARNING; INFO logs every pull and share). Repeated 'Could not "
             "find <key>' errors are logged once per key, then hourly.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Parse arguments and run the compute loop.

    Parameters
    ----------
    argv : list of str or None, optional
        Command-line arguments, excluding the program name. ``None``
        (the default) uses :data:`sys.argv`.

    Returns
    -------
    int
        Process exit code, ``0`` on a clean ``Ctrl-C`` or a completed
        ``--once`` run.

    Notes
    -----
    Recognised arguments mirror ``slama.fault``'s CLI:
    ``config`` (positional path to ``computations.json``),
    ``--smax-json``, ``--host``, ``--port``, ``--interval``,
    ``--log-level``, ``--smax-log-level``, ``--site-root``, plus ``--once`` (run a single :meth:`ComputeEngine.tick`
    and exit — useful for manual verification without a long-running
    process) and ``--as-of``. ``--host``/``--port`` default to the
    ``SMAX_HOST``/``SMAX_PORT`` environment variables (see
    :func:`_build_parser`).
    """
    args = _build_parser().parse_args(argv)

    # force=True: smax-python calls logging.basicConfig() at import time,
    # which would otherwise make this call a silent no-op (and hide the
    # --once results, logged at INFO).
    logging.basicConfig(
        level=args.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        force=True,
    )
    configure_smax_logging(args.smax_log_level)

    if args.site_root is not None:
        os.environ[site_paths.SITE_ROOT_ENV] = str(args.site_root)
        site_paths.reset_site_root()
    site_paths.site_root()  # logs the chosen root before the config reads site files

    monitor_system = MonitorSystem(args.smax_json)
    config = ComputeConfig.from_file(args.config, monitor_system)
    client = SmaxRedisClient(args.host, redis_port=args.port)

    engine_kwargs = {}
    if args.as_of is not None:
        engine_kwargs["wall_clock"] = lambda: args.as_of
    engine = ComputeEngine(config, monitor_system, client=client, **engine_kwargs)
    if args.interval is not None:
        engine.set_interval(args.interval)

    if args.once:
        results = engine.tick()
        for r in results:
            logging.getLogger(__name__).info(
                "%s = %r (%s)", r.canonical_name, r.value, r.validity.name
            )
        return 0

    try:
        engine.run_forever()
    except KeyboardInterrupt:
        engine.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
