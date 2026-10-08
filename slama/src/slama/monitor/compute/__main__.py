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

from slama.monitor.monitorsystem import MonitorSystem

from .computeconfig import ComputeConfig
from .engine import ComputeEngine

DEFAULT_SMAX_HOST = "localhost"
"""SMAX host used when neither ``--host`` nor ``SMAX_HOST`` is given."""

DEFAULT_SMAX_PORT = 6380
"""SMAX port used when neither ``--port`` nor ``SMAX_PORT`` is given.

The SLAMA development convention (OS Redis owns 6379); the observatory
itself uses 6379, set via ``SMAX_PORT`` or ``--port``.
"""


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
        :data:`DEFAULT_SMAX_HOST`/:data:`DEFAULT_SMAX_PORT`. An explicit
        ``--host``/``--port`` always wins over the environment.
    """
    env = os.environ if environ is None else environ
    host_default = env.get("SMAX_HOST") or DEFAULT_SMAX_HOST
    port_env = env.get("SMAX_PORT")
    port_default = DEFAULT_SMAX_PORT
    parser = argparse.ArgumentParser(prog="[uv run] python -m slama.monitor.compute")
    if port_env:
        try:
            port_default = int(port_env)
        except ValueError:
            parser.error(f"SMAX_PORT must be an integer port number, got {port_env!r}")
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
        "--host", default=host_default,
        help=f"SMAX host (default: $SMAX_HOST, else {DEFAULT_SMAX_HOST}; now {host_default})",
    )
    parser.add_argument(
        "--port", type=int, default=port_default,
        help=f"SMAX Redis port (default: $SMAX_PORT, else {DEFAULT_SMAX_PORT}; now {port_default})",
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
        "--log-level", default="INFO",
        help="stdlib logging level (default: INFO)",
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
    ``--log-level``, plus ``--once`` (run a single :meth:`ComputeEngine.tick`
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
