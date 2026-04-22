"""Action protocol and built-in actions.

A fault-system *action* is anything that can receive a
:class:`FaultEvent` and do something with it — write a log line, send
an email, raise an SMAX alarm, etc. Actions are looked up by name
from the JSON config's ``actions`` block and invoked by
:meth:`FaultSystem._dispatch` when a root fault is reported.

Version 1 ships a single built-in action, :class:`LogFileAction`.
New action types are added by:

1. Writing a class with a ``fire(event: FaultEvent) -> None`` method.
2. Writing a small builder function ``_build_xxx(spec: dict) ->
   Action`` that extracts parameters from the config dict and
   constructs the action.
3. Registering the builder in :data:`ACTION_TYPES` under its
   ``type`` name.

No changes to :class:`FaultSystem` are required to add a new action
type; the factory :func:`build_action` is the sole entry point used
at config-load time.

Notes
-----
The :class:`Action` type is a ``typing.Protocol`` rather than a
concrete base class, so action classes do not need to inherit from
anything — they only need to satisfy the structural ``fire()``
signature.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from .faultnode import FaultEvent


logger = logging.getLogger(__name__)


class Action(Protocol):
    """Structural protocol for fault-system actions.

    Any object with a ``fire(event)`` method that accepts a
    :class:`FaultEvent` and returns ``None`` satisfies this protocol.
    Classes need not inherit from ``Action``; structural typing is
    sufficient.

    Methods
    -------
    fire(event)
        Dispatch the given fault event. Must not raise on ordinary
        failures (e.g. IO errors) — :meth:`FaultSystem._dispatch`
        catches and logs exceptions, but well-behaved actions should
        handle their own errors gracefully when possible.
    """

    def fire(self, event: FaultEvent) -> None: ...


class LogFileAction:
    """Append a single timestamped line per root fault to a log file.

    The output line format is::

        <ISO-8601 UTC timestamp> <canonical_name> <validity_name>\\n

    with one line appended per call to :meth:`fire`. The parent
    directory is created on construction if it does not already
    exist, so the configured path need not pre-exist.

    Parameters
    ----------
    path : str or pathlib.Path
        Filesystem path of the log file to append to. The parent
        directory is created (with ``parents=True, exist_ok=True``)
        at construction time; the file itself is opened in append
        mode on each event.

    Attributes
    ----------
    path : pathlib.Path
        The resolved log-file path as a :class:`Path` object.

    Notes
    -----
    Each :meth:`fire` call opens and closes the file, which is
    simple and resilient (a log-rotation rename will not leave a
    stale file handle) but not optimal for very high event rates.
    For the observatory's fault cadence (seconds to hours between
    events) this is well within budget.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def fire(self, event: FaultEvent) -> None:
        """Append one line describing ``event`` to the log file.

        Parameters
        ----------
        event : FaultEvent
            The root-fault event to record. The line written uses
            :attr:`FaultEvent.timestamp` formatted as an ISO-8601
            UTC string, followed by the canonical name and the
            validity enum member's ``name``.
        """
        iso = datetime.fromtimestamp(event.timestamp, tz=timezone.utc).isoformat()
        line = f"{iso} {event.canonical_name} {event.validity.name}\n"
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(line)


def _build_log_file(spec: dict) -> Action:
    """Construct a :class:`LogFileAction` from a config dict.

    Parameters
    ----------
    spec : dict
        Parsed JSON spec. Must contain a ``"path"`` key giving the
        log-file path; other keys are ignored.

    Returns
    -------
    Action
        A new :class:`LogFileAction` bound to ``spec["path"]``.

    Raises
    ------
    ValueError
        If ``spec`` does not contain a ``"path"`` key.
    """
    if "path" not in spec:
        raise ValueError(f"log_file action requires 'path': {spec!r}")
    return LogFileAction(spec["path"])


ACTION_TYPES: dict[str, callable] = {
    "log_file": _build_log_file,
}
"""dict: registry mapping config ``type`` strings to builder callables.

Each entry's value is a function ``(spec: dict) -> Action`` that
extracts its own parameters from the spec and returns an
:class:`Action` instance. To add a new action type, write a class
implementing the :class:`Action` protocol, write a ``_build_xxx``
function, and insert it here under a unique type name. The JSON
config's ``actions.<name>.type`` field is looked up in this dict by
:func:`build_action`.
"""


def build_action(spec: dict) -> Action:
    """Build an :class:`Action` from a config dict.

    Looks up ``spec["type"]`` in :data:`ACTION_TYPES` and delegates
    to the matching builder function. This is the single entry
    point used by :meth:`FaultConfig.from_dict` to materialize every
    action in the JSON ``actions`` block.

    Parameters
    ----------
    spec : dict
        Parsed JSON spec for one action. Must contain a ``"type"``
        key whose value names a registered action type; additional
        keys are interpreted by the per-type builder.

    Returns
    -------
    Action
        A new action instance of the requested type.

    Raises
    ------
    ValueError
        If ``spec`` lacks a ``"type"`` key, or if the requested type
        is not registered in :data:`ACTION_TYPES`.

    Examples
    --------
    >>> build_action({"type": "log_file", "path": "/tmp/faults.log"})
    <slama.fault.actions.LogFileAction object at ...>
    """
    if "type" not in spec:
        raise ValueError(f"action spec missing 'type': {spec!r}")
    t = spec["type"]
    if t not in ACTION_TYPES:
        raise ValueError(
            f"unknown action type {t!r}; known types: {sorted(ACTION_TYPES)}"
        )
    return ACTION_TYPES[t](spec)
