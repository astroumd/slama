"""Command-line conventions shared by the SLAMA process entry points.

The compute engine (:mod:`slama.monitor.compute.__main__`) and the fault
system (:mod:`slama.fault.__main__`) both connect to SMAX and resolve the
server the same way:

1. an explicit ``--host`` / ``--port`` on the command line, else
2. the ``SMAX_HOST`` / ``SMAX_PORT`` environment variables, else
3. :data:`DEFAULT_SMAX_HOST` / :data:`DEFAULT_SMAX_PORT`.

The web server (:mod:`slama.web.server`) follows the same order but sets
the variables for uvicorn's worker rather than parsing them here.
"""
from __future__ import annotations

import argparse
import os
from collections.abc import Mapping

DEFAULT_SMAX_HOST = "localhost"
"""str: SMAX host used when neither ``--host`` nor ``SMAX_HOST`` is given."""

DEFAULT_SMAX_PORT = 6380
"""int: SMAX port used when neither ``--port`` nor ``SMAX_PORT`` is given.

The SLAMA development convention (OS Redis owns 6379); the observatory
itself uses 6379, set via ``SMAX_PORT`` or ``--port``.
"""


def add_smax_args(parser: argparse.ArgumentParser,
                  environ: Mapping[str, str] | None = None) -> None:
    """Add ``--host`` and ``--port`` with environment-aware defaults.

    Parameters
    ----------
    parser : argparse.ArgumentParser
        Parser to add the two options to.
    environ : mapping of str to str or None, optional
        Environment to read ``SMAX_HOST`` / ``SMAX_PORT`` from. ``None``
        (the default) uses :data:`os.environ`. Injectable for tests.

    Notes
    -----
    An empty ``SMAX_HOST`` or ``SMAX_PORT`` counts as unset. A
    non-integer ``SMAX_PORT`` is a usage error: ``parser.error`` prints
    the message and exits with status 2, as for a bad command-line
    value. The help text shows the default actually in effect.
    """
    env = os.environ if environ is None else environ
    host_default = env.get("SMAX_HOST") or DEFAULT_SMAX_HOST
    port_env = env.get("SMAX_PORT")
    port_default = DEFAULT_SMAX_PORT
    if port_env:
        try:
            port_default = int(port_env)
        except ValueError:
            parser.error(f"SMAX_PORT must be an integer port number, got {port_env!r}")
    parser.add_argument(
        "--host", default=host_default,
        help=f"SMAX host (default: $SMAX_HOST, else {DEFAULT_SMAX_HOST}; now {host_default})",
    )
    parser.add_argument(
        "--port", type=int, default=port_default,
        help=f"SMAX Redis port (default: $SMAX_PORT, else {DEFAULT_SMAX_PORT}; now {port_default})",
    )
