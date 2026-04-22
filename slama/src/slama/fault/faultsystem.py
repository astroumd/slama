"""FaultSystem: the main orchestrator. Polls the MonitorSystem on an
interval, walks the DAG to identify root faults, and dispatches actions."""
from __future__ import annotations

import fnmatch
import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from slama.monitor.monitorpoint import MonitorPoint, Validity
from slama.monitor.monitorsystem import MonitorSystem

from .actions import Action
from .faultconfig import FaultConfig
from .faultnode import FAULT_STATES, FaultEvent, FaultNode


logger = logging.getLogger(__name__)


@dataclass
class _Ignore:
    pattern: str
    expiry_monotonic: float | None  # None = never expires


class FaultSystem:
    """Watches a DAG of critical monitor points for faults, identifies
    root faults, and fires configured actions.

    The API methods (`set_interval`, `ignore`, `unignore`, `reload_config`,
    `stop`) are safe to call from a thread other than the one running
    `run_forever()`.
    """

    def __init__(
        self,
        config: FaultConfig,
        monitor_system: MonitorSystem,
        client=None,
        *,
        clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], float] = time.time,
    ):
        self._monitor_system = monitor_system
        self._client = client
        self._clock = clock
        self._wall_clock = wall_clock

        self._lock = threading.Lock()
        self._stop_event = threading.Event()

        self._nodes: dict[str, FaultNode] = {}
        self._actions: dict[str, Action] = {}
        self._ignores: list[_Ignore] = []
        self._interval_s: float = 5.0

        self._apply_config(config)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run_forever(self) -> None:
        """Block, ticking at the configured interval until stop() is called."""
        logger.info(
            "FaultSystem starting: %d critical points, interval=%.2fs",
            len(self._nodes), self._interval_s,
        )
        while not self._stop_event.is_set():
            try:
                self.tick()
            except Exception:
                logger.exception("FaultSystem tick failed")
            with self._lock:
                interval = self._interval_s
            if self._stop_event.wait(interval):
                break
        logger.info("FaultSystem stopped")

    def stop(self) -> None:
        """Signal run_forever() to exit after the current tick."""
        self._stop_event.set()

    def tick(self) -> list[FaultEvent]:
        """Run one iteration: refresh validities, find root faults,
        fire actions. Returns the list of events that were dispatched."""
        if self._client is not None:
            self._monitor_system.read_all(self._client)

        now_mono = self._clock()
        now_wall = self._wall_clock()

        self._purge_expired_ignores(now_mono)

        faulted: set[str] = set()   # names that are currently in a fault state
        debounced: set[str] = set() # subset of faulted that passed the transient filter
        current_validity: dict[str, Validity] = {}

        for name, node in self._nodes.items():
            mp = self._get_mp(name)
            validity = mp.validity if mp is not None else Validity.INVALID_NO_DATA
            current_validity[name] = validity
            is_fault = validity in FAULT_STATES

            if is_fault:
                if node.first_fault_t is None:
                    node.first_fault_t = now_mono
                faulted.add(name)
                if (now_mono - node.first_fault_t) >= node.transient_filter_s:
                    debounced.add(name)
            else:
                node.first_fault_t = None
                node.last_reported_t = None
                node.last_reported_validity = None

        events: list[FaultEvent] = []
        for name in debounced:
            node = self._nodes[name]
            # Root fault = no parent is also debounced-faulted.
            if any(p in debounced for p in node.parents):
                continue
            if self._is_ignored(name):
                continue
            validity = current_validity[name]
            # Dedup: only fire when newly faulted or validity changed
            # since the last report.
            if (node.last_reported_t is not None
                    and node.last_reported_validity == validity):
                continue
            event = FaultEvent(
                canonical_name=name,
                validity=validity,
                timestamp=now_wall,
                transient_filter_s=node.transient_filter_s,
            )
            self._dispatch(node, event)
            node.last_reported_t = now_mono
            node.last_reported_validity = validity
            events.append(event)
        return events

    def set_interval(self, seconds: float) -> None:
        if seconds <= 0:
            raise ValueError(f"interval must be positive, got {seconds!r}")
        with self._lock:
            self._interval_s = float(seconds)
        logger.info("FaultSystem interval set to %.2fs", seconds)

    def ignore(self, pattern: str, seconds: int = 0) -> None:
        """Suppress actions for any canonical name matching `pattern`
        (fnmatch wildcards). seconds<=0 means ignore indefinitely until
        unignore() is called."""
        expiry = None
        if seconds and seconds > 0:
            expiry = self._clock() + seconds
        with self._lock:
            self._ignores.append(_Ignore(pattern, expiry))
        logger.info("FaultSystem ignoring %r (expires=%s)", pattern, expiry)

    def unignore(self, pattern: str) -> None:
        """Remove all active ignores whose pattern equals `pattern` exactly."""
        with self._lock:
            before = len(self._ignores)
            self._ignores = [i for i in self._ignores if i.pattern != pattern]
            removed = before - len(self._ignores)
        logger.info("FaultSystem unignore(%r): removed %d", pattern, removed)

    def reload_config(self, path: str | Path) -> None:
        """Rebuild the DAG from `path`, preserving the active ignore list."""
        new_config = FaultConfig.from_file(path)
        with self._lock:
            self._apply_config(new_config)
        logger.info("FaultSystem reloaded config from %s", path)

    @property
    def interval_s(self) -> float:
        with self._lock:
            return self._interval_s

    @property
    def nodes(self) -> dict[str, FaultNode]:
        return self._nodes

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _apply_config(self, config: FaultConfig) -> None:
        self._nodes = config.nodes
        self._actions = config.actions
        self._interval_s = config.default_interval_s

    def _get_mp(self, canonical_name: str) -> MonitorPoint | None:
        try:
            return self._monitor_system.get_monitor_point(canonical_name)
        except KeyError:
            return None

    def _is_ignored(self, canonical_name: str) -> bool:
        for ig in self._ignores:
            if fnmatch.fnmatchcase(canonical_name, ig.pattern):
                return True
        return False

    def _purge_expired_ignores(self, now_mono: float) -> None:
        with self._lock:
            self._ignores = [
                ig for ig in self._ignores
                if ig.expiry_monotonic is None or ig.expiry_monotonic > now_mono
            ]

    def _dispatch(self, node: FaultNode, event: FaultEvent) -> None:
        for action_key in node.actions:
            action = self._actions.get(action_key)
            if action is None:
                logger.warning(
                    "fault %s references missing action %r",
                    node.canonical_name, action_key,
                )
                continue
            try:
                action.fire(event)
            except Exception:
                logger.exception(
                    "action %r failed for fault %s",
                    action_key, node.canonical_name,
                )
