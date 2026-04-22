"""CLI entry point: `python -m slama.fault conf/faults.json`

Loads the fault config, builds a MonitorSystem from smax.json, connects
to SMAX on localhost:6380, and runs the fault loop until Ctrl-C."""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from smax import SmaxRedisClient

from slama.monitor.monitorsystem import MonitorSystem

from .faultconfig import FaultConfig
from .faultsystem import FaultSystem


def main(argv: list[str] | None = None) -> int:
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
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=args.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

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
