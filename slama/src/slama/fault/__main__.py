"""Command-line entry point for the fault system.

Run the fault loop in a blocking foreground process::

    python -m slama.fault conf/faults.json
    python -m slama.fault conf/faults.json --interval 2
    python -m slama.fault conf/faults.json --once
    python -m slama.fault conf/faults.json --once --as-of 1790094623
    python -m slama.fault conf/faults.json --smax-json /path/to/smax.json \\
                                           --host localhost --port 6380

The module initializes stdlib logging, loads the fault config, builds
a :class:`MonitorSystem` from the SMAX JSON schema, connects to the
SMAX (Redis / Valkey) backend, and runs :meth:`FaultSystem.run_forever`
until the user sends ``SIGINT`` (Ctrl-C), at which point it calls
:meth:`FaultSystem.stop` and exits cleanly. With ``--once`` it runs a
single :meth:`FaultSystem.tick` instead. Every tick publishes
``faultsystem:state`` and ``faultsystem:heartbeat`` (:mod:`slama.fault.publish`),
so ``--once`` against the static dev snapshot writes those two keys into it.

Environment variables (used when ``--host``/``--port`` are not given,
as for the compute engine and the web display server)::

    SMAX_HOST   SMAX/Redis server hostname (default: localhost)
    SMAX_PORT   SMAX/Redis server port     (default: 6380)

Notes
-----
The default SMAX port is ``6380`` (the SLAMA development convention)
rather than Redis's default ``6379``; see
:data:`slama.cli_common.DEFAULT_SMAX_PORT`.

Unlike the compute CLI there is no ``--site-root``: the fault system
reads no site files. Add it if ``faults.json`` ever gains ``@`` tokens.
"""
from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Mapping
from pathlib import Path

from smax import SmaxRedisClient

from slama.cli_common import add_smax_args
from slama.monitor.monitorsystem import MonitorSystem
from slama.smax_logging import configure_smax_logging

from .faultconfig import FaultConfig
from .faultsystem import FaultSystem
from .publish import state_counts


logger = logging.getLogger(__name__)


def _build_parser(environ: Mapping[str, str] | None = None) -> argparse.ArgumentParser:
    """Build the command-line parser.

    Parameters
    ----------
    environ : mapping of str to str or None, optional
        Environment to read ``SMAX_HOST``/``SMAX_PORT`` defaults from;
        ``None`` (the default) uses :data:`os.environ`. Injectable for
        tests.

    Returns
    -------
    argparse.ArgumentParser
        Parser for the arguments listed in :func:`main`. ``--host`` /
        ``--port`` defaults come from :func:`slama.cli_common.add_smax_args`.
    """
    parser = argparse.ArgumentParser(prog="[uv run] python -m slama.fault")
    parser.add_argument(
        "config",
        type=Path,
        help="Path to the fault-system JSON config (e.g. conf/faults.json)",
    )
    parser.add_argument(
        "--smax-json",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "conf" / "smax.json",
        help="Path to the SMAX monitor-system JSON (default: conf/smax.json)",
    )
    add_smax_args(parser, environ)
    parser.add_argument(
        "--interval", type=float, default=None,
        help="Loop interval in seconds (overrides config default)",
    )
    parser.add_argument(
        "--once", action="store_true",
        help="Run a single tick, log the events it dispatched, and exit",
    )
    parser.add_argument(
        "--as-of", type=float, default=None, metavar="EPOCH",
        help="Use EPOCH (Unix seconds) as the wall clock, for replaying a "
             "static SMAX snapshot. Debounce and ignore timers still run "
             "on the real monotonic clock.",
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
    """Parse arguments and run the fault loop to completion.

    Parameters
    ----------
    argv : list of str or None, optional
        Command-line arguments, **excluding** the program name. If
        ``None`` (the default), :func:`argparse.ArgumentParser.parse_args`
        uses :data:`sys.argv`. Pass an explicit list from tests or
        wrappers.

    Returns
    -------
    int
        Process exit code: ``0`` on a clean Ctrl-C or a completed
        ``--once`` run. Failures during parsing or config loading
        raise (or exit with status 2 for a usage error), so the shell
        sees a non-zero status.

    Notes
    -----
    Recognised arguments:

    ``config`` (positional)
        Path to the fault-system JSON config.
    ``--smax-json PATH``
        Path to the SMAX monitor-system JSON. Defaults to
        ``conf/smax.json`` relative to the installed ``slama``
        package.
    ``--host HOST``, ``--port N``
        SMAX server. Default to ``SMAX_HOST`` / ``SMAX_PORT``, else
        ``localhost:6380`` (:func:`slama.cli_common.add_smax_args`).
    ``--interval SECONDS``
        Override the config's default polling interval.
    ``--once``
        Run one :meth:`FaultSystem.tick`, log each dispatched event at
        ``INFO``, log one line of node-state counts, and exit. Actions
        still fire, and the state is published to SMAX.
    ``--as-of EPOCH``
        Replace only the **wall** clock with the constant ``EPOCH``.
        The monotonic clock behind debounce (``transient_filter_s``)
        and ignore TTLs stays real; freezing it would stop every
        debounce from ever elapsing. See ``docs/source/replay-as-of.md``.
    ``--log-level LEVEL``
        stdlib logging level (``DEBUG``, ``INFO``, ``WARNING``,
        ...). Defaults to ``INFO``.
    ``--smax-log-level LEVEL``
        Level for the smax-python library's own logging. Defaults to
        ``WARNING`` (``INFO`` logs every pull and share); repeated
        missing-key errors are deduplicated (see
        :mod:`slama.smax_logging`).

    On ``KeyboardInterrupt`` the loop's :meth:`FaultSystem.stop` is
    invoked so the current tick finishes cleanly before the process
    exits.
    """
    args = _build_parser().parse_args(argv)

    # force=True: smax-python calls logging.basicConfig() at import time,
    # which would otherwise make this call a silent no-op and leave the
    # root logger at WARNING, hiding --log-level INFO output.
    logging.basicConfig(
        level=args.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        force=True,
    )
    configure_smax_logging(args.smax_log_level)

    config = FaultConfig.from_file(args.config)
    monitor_system = MonitorSystem(args.smax_json)
    client = SmaxRedisClient(args.host, redis_port=args.port)

    system_kwargs = {}
    if args.as_of is not None:
        system_kwargs["wall_clock"] = lambda: args.as_of
    system = FaultSystem(config, monitor_system, client=client, **system_kwargs)
    if args.interval is not None:
        system.set_interval(args.interval)

    if args.once:
        events = system.tick()
        for e in events:
            logger.info("%s %s", e.canonical_name, e.validity.name)
        logger.info("--once: %d event(s) dispatched", len(events))
        counts = state_counts(system.last_snapshot)
        logger.info("--once: states %s",
                    ", ".join(f"{k} {v}" for k, v in counts.items()))
        return 0

    try:
        system.run_forever()
    except KeyboardInterrupt:
        system.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
