"""Command-line entry point for the monitor subsystem compute engine.

Run the compute loop in a blocking foreground process::

    python -m slama.monitor.compute conf/computations.json
    python -m slama.monitor.compute conf/computations.json --interval 2
    python -m slama.monitor.compute conf/computations.json --once

Mirrors :mod:`slama.fault.__main__` — see that module for the shared
argument conventions (SMAX host/port default to the SLAMA convention
of ``localhost:6380``, not Redis's default ``6379``).
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from smax import SmaxRedisClient

from slama.monitor.monitorsystem import MonitorSystem

from .computeconfig import ComputeConfig
from .engine import ComputeEngine


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
    process).
    """
    parser = argparse.ArgumentParser(prog="python -m slama.monitor.compute")
    parser.add_argument(
        "config",
        type=Path,
        help="Path to the compute config (e.g. conf/computations.json)",
    )
    parser.add_argument(
        "--smax-json",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "conf" / "smax.json",
        help="Path to the SMAX monitor-system JSON (default: conf/smax.json)",
    )
    parser.add_argument(
        "--host", default="localhost", help="SMAX host (default: localhost)",
    )
    parser.add_argument(
        "--port", type=int, default=6380, help="SMAX Redis port (default: 6380)",
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
        "--log-level", default="INFO",
        help="stdlib logging level (default: INFO)",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=args.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    monitor_system = MonitorSystem(args.smax_json)
    config = ComputeConfig.from_file(args.config, monitor_system)
    client = SmaxRedisClient(args.host, redis_port=args.port)

    engine = ComputeEngine(config, monitor_system, client=client)
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
