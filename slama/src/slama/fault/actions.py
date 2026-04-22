"""Action protocol and built-in actions.

v1 ships LogFileAction. Additional actions (email, SMAX alarm) can be
added as new classes registered in ACTION_TYPES — FaultSystem does not
need changes."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from .faultnode import FaultEvent


logger = logging.getLogger(__name__)


class Action(Protocol):
    def fire(self, event: FaultEvent) -> None: ...


class LogFileAction:
    """Append a single line per root fault to a log file."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def fire(self, event: FaultEvent) -> None:
        iso = datetime.fromtimestamp(event.timestamp, tz=timezone.utc).isoformat()
        line = f"{iso} {event.canonical_name} {event.validity.name}\n"
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(line)


def _build_log_file(spec: dict) -> Action:
    if "path" not in spec:
        raise ValueError(f"log_file action requires 'path': {spec!r}")
    return LogFileAction(spec["path"])


ACTION_TYPES: dict[str, callable] = {
    "log_file": _build_log_file,
}


def build_action(spec: dict) -> Action:
    """Build an Action from a config dict with a 'type' field."""
    if "type" not in spec:
        raise ValueError(f"action spec missing 'type': {spec!r}")
    t = spec["type"]
    if t not in ACTION_TYPES:
        raise ValueError(
            f"unknown action type {t!r}; known types: {sorted(ACTION_TYPES)}"
        )
    return ACTION_TYPES[t](spec)
