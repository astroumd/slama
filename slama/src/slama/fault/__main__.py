"""Command-line entry point for the fault system.

Run the fault loop in a blocking foreground process::

    python -m slama.fault conf/faults.json
    python -m slama.fault conf/faults.json --interval 2
    python -m slama.fault conf/faults.json --smax-json /path/to/smax.json \\
                                           --host localhost --port 6380

The module initializes stdlib logging, loads the fault config, builds
a :class:`MonitorSystem` from the SMAX JSON schema, connects to the
SMAX (Redis / Valkey) backend, and runs :meth:`FaultSystem.run_forever`
until the user sends ``SIGINT`` (Ctrl-C), at which point it calls
:meth:`FaultSystem.stop` and exits cleanly.

Notes
-----
The default SMAX port is ``6380`` (the SLAMA/SMA convention) rather
than Redis's default ``6379``.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from smax import SmaxRedisClient

from slama.monitor.monitorsystem import MonitorSystem
from slama.smax_logging import configure_smax_logging

from .faultconfig import FaultConfig
from .faultsystem import FaultSystem


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
        Process exit code. Currently always ``0`` — failures
        during parsing / config loading raise exceptions rather
        than returning a non-zero status, so the shell observes
        a traceback and a non-zero exit via the Python runtime.
        The explicit ``0`` return covers the clean Ctrl-C path.

    Notes
    -----
    Recognised arguments:

    ``config`` (positional)
        Path to the fault-system JSON config.
    ``--smax-json PATH``
        Path to the SMAX monitor-system JSON. Defaults to
        ``conf/smax.json`` relative to the installed ``slama``
        package.
    ``--host HOST``
        SMAX host. Defaults to ``localhost``.
    ``--port N``
        SMAX Redis port. Defaults to ``6380``.
    ``--interval SECONDS``
        Override the config's default polling interval.
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
    parser = argparse.ArgumentParser(prog="python -m slama.fault")
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
        "--log-level", default="INFO",
        help="stdlib logging level (default: INFO)",
    )
    parser.add_argument(
        "--smax-log-level", default="WARNING",
        help="Level for the smax-python library's own logging (default: "
             "WARNING; INFO logs every pull and share)",
    )
    args = parser.parse_args(argv)

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

    system = FaultSystem(config, monitor_system, client=client)
    if args.interval is not None:
        system.set_interval(args.interval)

    try:
        system.run_forever()
    except KeyboardInterrupt:
        system.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
