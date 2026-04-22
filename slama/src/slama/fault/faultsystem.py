"""Main fault-loop orchestrator.

:class:`FaultSystem` is the runtime object that ties together
:class:`MonitorSystem`, the DAG defined in :class:`FaultConfig`, and
the registered :class:`Action` instances. On each tick it:

1. Asks the :class:`MonitorSystem` to refresh all values from SMAX.
2. Classifies each critical node as currently faulted or not.
3. Applies the per-node transient filter (``transient_filter_s``).
4. Walks the DAG to find root faults — a node is a root fault iff
   *none* of its parents are also debounced-faulted.
5. Applies the active ignore patterns (pattern / TTL based
   suppression, independent of root-detection).
6. De-duplicates against the last report for each node so a single
   persistent fault produces one event, not one per tick, unless
   the validity value itself changes.
7. Calls :meth:`Action.fire` for every action bound to the reporting
   nodes.

Thread safety
-------------
The public API methods (:meth:`set_interval`, :meth:`ignore`,
:meth:`unignore`, :meth:`reload_config`, :meth:`stop`) are safe to
call from a thread other than the one running :meth:`run_forever`.
Internally they take a :class:`threading.Lock` on the mutable state
they touch. :meth:`tick` itself is intended to be called from a
single thread (the loop thread or, in tests, the test thread).

:meth:`run_forever` blocks on a :class:`threading.Event` between
ticks rather than using :func:`time.sleep`, so :meth:`stop` causes
the loop to exit promptly rather than waiting out a full interval.
"""
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
    """One active ignore entry in :class:`FaultSystem`'s ignore list.

    Attributes
    ----------
    pattern : str
        An :mod:`fnmatch`-style wildcard pattern matched against
        canonical names (e.g. ``"antenna:1:*"``, ``"*:heater"``).
    expiry_monotonic : float or None
        Monotonic-clock deadline after which the ignore auto-expires.
        ``None`` means the ignore is indefinite and persists until
        an explicit :meth:`FaultSystem.unignore` call.
    """

    pattern: str
    expiry_monotonic: float | None


class FaultSystem:
    """Watch a DAG of critical monitor points and dispatch root faults.

    This is the main orchestrator. After construction with a parsed
    :class:`FaultConfig` and a :class:`MonitorSystem` to observe,
    call :meth:`run_forever` to enter the blocking loop (for the CLI)
    or :meth:`tick` to run a single iteration (for tests, or for
    integration into an external scheduler).

    Parameters
    ----------
    config : FaultConfig
        Fully-resolved config: DAG nodes, actions, and default
        interval.
    monitor_system : MonitorSystem
        The tree of monitor points to observe. Must provide
        ``get_monitor_point(name)`` and ``read_all(client)``.
    client : SmaxRedisClient or None, optional
        SMAX client used by :meth:`MonitorSystem.read_all` to refresh
        values at the start of each tick. If ``None`` (the default),
        :meth:`tick` skips the refresh — useful for tests that
        inject a fake :class:`MonitorSystem` with pre-set values.
    clock : callable, optional
        Monotonic clock used for debounce and ignore-TTL timers.
        Defaults to :func:`time.monotonic`. Override in tests to
        inject a controllable fake clock.
    wall_clock : callable, optional
        Wall-clock source used as :attr:`FaultEvent.timestamp`.
        Defaults to :func:`time.time`.

    Attributes
    ----------
    interval_s : float
        Read-only view of the current polling interval in seconds
        (thread-safe). Use :meth:`set_interval` to change it.
    nodes : dict of str to FaultNode
        Read-only view of the current DAG. Replaced wholesale by
        :meth:`reload_config`.

    Notes
    -----
    Ignoring a canonical name only suppresses *event dispatch* for
    that name; an ignored faulted node is still counted as faulted
    for purposes of root-cause detection, so ignoring a parent does
    not spuriously promote its children to root faults.
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
        """Block, ticking at the configured interval, until :meth:`stop`.

        Calls :meth:`tick` repeatedly. Between ticks the thread
        waits on an internal :class:`threading.Event` rather than
        sleeping, so :meth:`stop` (from another thread) cuts the
        wait short. Exceptions raised by :meth:`tick` are caught
        and logged at ``ERROR`` level; the loop then continues.

        Notes
        -----
        Intended to be called from exactly one thread (typically the
        CLI entry point's main thread). Calling it re-entrantly is
        not supported.
        """
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
        """Signal :meth:`run_forever` to exit after the current tick.

        Thread-safe. After the current tick completes (or the
        inter-tick wait returns early), :meth:`run_forever` unwinds
        and returns to its caller. Calling ``stop`` on a system
        that is not currently in :meth:`run_forever` has no effect
        beyond setting the stop flag; a subsequent
        :meth:`run_forever` will exit immediately unless the flag
        is cleared (by constructing a new :class:`FaultSystem`).
        """
        self._stop_event.set()

    def tick(self) -> list[FaultEvent]:
        """Run one iteration of the fault loop.

        The algorithm, in order, is:

        1. If ``client`` was provided, call
           :meth:`MonitorSystem.read_all` to refresh current values.
        2. Read the monotonic and wall clocks.
        3. Purge any expired ignore entries.
        4. For each DAG node, read its current
           :attr:`MonitorPoint.validity`, updating its runtime
           debounce state (:attr:`FaultNode.first_fault_t` set on
           rising edge, cleared on return-to-good). Classify the
           node as ``faulted`` (in a fault state) and, if the
           transient filter has elapsed, as ``debounced``.
        5. For each ``debounced`` node, skip it if any parent is
           also debounced (not a root), skip it if matched by an
           active ignore pattern, and skip it if the last report
           was the same validity value (dedup). Otherwise construct
           a :class:`FaultEvent`, dispatch actions, and record the
           new last-report state.

        Returns
        -------
        list of FaultEvent
            The events that were actually dispatched this tick. May
            be empty. The order is arbitrary (iteration order of the
            internal ``debounced`` set).

        Notes
        -----
        Ignored nodes are still counted as ``debounced`` for
        root-cause detection; they are only suppressed at dispatch.
        This preserves the invariant that a child is not reported
        if its parent is physically faulted, regardless of whether
        the parent is being alert-suppressed.
        """
        if self._client is not None:
            self._monitor_system.read_all(self._client)

        now_mono = self._clock()
        now_wall = self._wall_clock()

        self._purge_expired_ignores(now_mono)

        faulted: set[str] = set()
        debounced: set[str] = set()
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
            if any(p in debounced for p in node.parents):
                continue
            if self._is_ignored(name):
                continue
            validity = current_validity[name]
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
        """Change the polling interval used by :meth:`run_forever`.

        Thread-safe. The new value is picked up on the next
        iteration of the loop — any tick currently in progress
        continues under the old interval, then the inter-tick wait
        uses the new value.

        Parameters
        ----------
        seconds : float
            New interval in seconds. Must be strictly positive.

        Raises
        ------
        ValueError
            If ``seconds`` is zero or negative.
        """
        if seconds <= 0:
            raise ValueError(f"interval must be positive, got {seconds!r}")
        with self._lock:
            self._interval_s = float(seconds)
        logger.info("FaultSystem interval set to %.2fs", seconds)

    def ignore(self, pattern: str, seconds: int = 0) -> None:
        """Suppress action dispatch for canonical names matching a pattern.

        Adds an entry to the ignore list. While the entry is
        active, any fault event whose canonical name matches
        ``pattern`` under :func:`fnmatch.fnmatchcase` is dropped
        before any action is fired. The faulted node is still
        counted as faulted for root-cause detection, so ignoring a
        cause does not promote its downstream consequences to root.

        Parameters
        ----------
        pattern : str
            :mod:`fnmatch` wildcard pattern. Examples:
            ``"antenna:1:*"``, ``"*:heater"``, ``"antenna:?:power:ok"``.
        seconds : int, optional
            TTL in seconds. The ignore expires automatically after
            this many monotonic-clock seconds. ``0`` (the default)
            or any non-positive value means "indefinitely, until
            :meth:`unignore` is called".

        Notes
        -----
        Duplicate ignores are permitted — calling ``ignore`` twice
        with the same pattern adds two entries and
        :meth:`unignore` removes both at once.
        """
        expiry = None
        if seconds and seconds > 0:
            expiry = self._clock() + seconds
        with self._lock:
            self._ignores.append(_Ignore(pattern, expiry))
        logger.info("FaultSystem ignoring %r (expires=%s)", pattern, expiry)

    def unignore(self, pattern: str) -> None:
        """Remove every active ignore whose pattern equals ``pattern`` exactly.

        Parameters
        ----------
        pattern : str
            The pattern to remove. Exact string match is required —
            this is not itself a wildcard; ``unignore("antenna:*")``
            will not remove an ignore for ``"antenna:1:*"``.

        Notes
        -----
        It is not an error to call ``unignore`` with a pattern that
        is not currently active; the call becomes a no-op and logs
        a removed count of zero.
        """
        with self._lock:
            before = len(self._ignores)
            self._ignores = [i for i in self._ignores if i.pattern != pattern]
            removed = before - len(self._ignores)
        logger.info("FaultSystem unignore(%r): removed %d", pattern, removed)

    def reload_config(self, path: str | Path) -> None:
        """Rebuild the DAG from a new config file.

        Re-parses the config at ``path`` via
        :meth:`FaultConfig.from_file` and atomically swaps in the
        new nodes, actions, and default interval. The active ignore
        list is **preserved** across the reload so operator
        suppressions survive a config change.

        Parameters
        ----------
        path : str or pathlib.Path
            Path to the new fault-system JSON config.

        Raises
        ------
        FileNotFoundError, json.JSONDecodeError, ValueError
            Propagated from :meth:`FaultConfig.from_file` and
            :meth:`FaultConfig.from_dict`. On any failure, the
            current in-memory configuration is left intact — the
            swap only happens after successful parsing.

        Notes
        -----
        Runtime debounce state (``first_fault_t``, etc.) on
        previously-known nodes is **not** carried forward to the
        new config's nodes; every node in the new config starts
        with clean debounce state.
        """
        new_config = FaultConfig.from_file(path)
        with self._lock:
            self._apply_config(new_config)
        logger.info("FaultSystem reloaded config from %s", path)

    @property
    def interval_s(self) -> float:
        """float: Current polling interval in seconds (thread-safe read)."""
        with self._lock:
            return self._interval_s

    @property
    def nodes(self) -> dict[str, FaultNode]:
        """dict of str to FaultNode: Current DAG nodes keyed by canonical name.

        The returned dict is the live internal mapping; callers
        should treat it as read-only. It is replaced wholesale by
        :meth:`reload_config`.
        """
        return self._nodes

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _apply_config(self, config: FaultConfig) -> None:
        """Copy resolved config into the system's mutable state.

        Parameters
        ----------
        config : FaultConfig
            Parsed config to apply. Replaces ``_nodes``, ``_actions``,
            and ``_interval_s`` wholesale. Caller is responsible for
            holding ``self._lock``.
        """
        self._nodes = config.nodes
        self._actions = config.actions
        self._interval_s = config.default_interval_s

    def _get_mp(self, canonical_name: str) -> MonitorPoint | None:
        """Fetch a monitor point by canonical name, tolerating absence.

        Parameters
        ----------
        canonical_name : str
            Colon-delimited canonical name.

        Returns
        -------
        MonitorPoint or None
            The monitor point, or ``None`` if the name is not
            present in the :class:`MonitorSystem` (e.g. stale
            config). Absence is treated downstream as
            ``INVALID_NO_DATA``.
        """
        try:
            return self._monitor_system.get_monitor_point(canonical_name)
        except KeyError:
            return None

    def _is_ignored(self, canonical_name: str) -> bool:
        """Return True if any active ignore pattern matches ``canonical_name``.

        Parameters
        ----------
        canonical_name : str
            The canonical name to test.

        Returns
        -------
        bool
            ``True`` iff at least one entry in the ignore list
            matches under :func:`fnmatch.fnmatchcase`.
        """
        for ig in self._ignores:
            if fnmatch.fnmatchcase(canonical_name, ig.pattern):
                return True
        return False

    def _purge_expired_ignores(self, now_mono: float) -> None:
        """Drop ignore entries whose TTL has elapsed.

        Parameters
        ----------
        now_mono : float
            Current monotonic-clock time. Entries with
            ``expiry_monotonic`` less than or equal to this value
            are removed; entries with ``expiry_monotonic is None``
            (indefinite) are kept.
        """
        with self._lock:
            self._ignores = [
                ig for ig in self._ignores
                if ig.expiry_monotonic is None or ig.expiry_monotonic > now_mono
            ]

    def _dispatch(self, node: FaultNode, event: FaultEvent) -> None:
        """Fire every action bound to ``node`` with the given event.

        Each action is looked up in ``self._actions`` by name.
        Missing actions are logged at ``WARNING`` and skipped (the
        config loader validates action references, so this is only
        reachable via mid-run :meth:`reload_config` races). Action
        exceptions are caught and logged at ``ERROR``; they never
        abort the tick or prevent other actions from firing.

        Parameters
        ----------
        node : FaultNode
            The node whose actions should fire.
        event : FaultEvent
            Event to pass to each action's ``fire`` method.
        """
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
