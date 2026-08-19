"""Tick loop that evaluates computations and writes results back to SMAX.

:class:`ComputeEngine` is the runtime counterpart to
:class:`slama.fault.faultsystem.FaultSystem` — same "read → evaluate →
act" shape (poll-based ``tick()``, thread-safe ``run_forever``/``stop``/
``set_interval``/``reload_config``, injectable clocks for tests) but
where ``FaultSystem`` acts by dispatching :class:`Action`\\ s,
``ComputeEngine`` acts by writing new monitor points back to SMAX.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from smax import SmaxRedisClient
from smax.smax_data_types import SmaxBool, SmaxFloat, SmaxInt, SmaxStr

from slama.monitor.monitorpoint import Validity
from slama.monitor.monitorsystem import MonitorSystem

from .computeconfig import ComputeConfig
from .computenode import ComputeContext, ComputeNode, ResolvedInput
from .functions import get_function


logger = logging.getLogger(__name__)


@dataclass
class ComputeResult:
    """One canonical name's outcome for a single tick.

    A single-output node (``ComputeNode.output`` is a str) produces
    exactly one ``ComputeResult``; a multi-output node (``output`` is a
    dict, design doc §8) produces one per declared role.

    Attributes
    ----------
    canonical_name : str
        The computed point's canonical name.
    value : Any or None
        The computed value, or ``None`` if the node short-circuited to
        ``INVALID_NO_DATA`` (no value was written to SMAX in that
        case — see :meth:`ComputeEngine.tick`).
    validity : Validity
        The validity written for this point.
    """

    canonical_name: str
    value: Any
    validity: Validity


_WRAPPERS = (
    (bool, SmaxBool),
    (int, SmaxInt),
    (float, SmaxFloat),
    (str, SmaxStr),
)
"""Ordered (Python type, Smax<Type>) pairs used by :func:`_wrap`.

Order matters: ``bool`` must be checked before ``int`` since Python's
``bool`` is an ``int`` subclass.
"""


def _wrap(value: Any, wall_clock_s: float):
    """Wrap a plain Python value in the matching ``smax.smax_data_types`` class.

    The wrapped object behaves as the value itself (it subclasses
    ``bool``/``int``/``float``/``str``) while also carrying
    ``.timestamp``, which is what :attr:`MonitorPoint.value` and
    :attr:`MonitorPoint.time` expect from anything passed to
    :meth:`MonitorPoint.update`.

    ``wall_clock_s`` is a float epoch (what ``time.time()``/the
    engine's ``wall_clock`` return); ``SmaxVarBase.timestamp`` is
    typed as ``datetime | None``, so it is converted here rather than
    passed through — passing the float directly type-checks (the
    field has no runtime type enforcement) but breaks the first thing
    that reads ``.time`` (``MonitorPoint.time`` does
    ``Time(self._smax_result.timestamp)``, and ``astropy.time.Time``
    rejects a bare float).
    """
    timestamp = datetime.fromtimestamp(wall_clock_s, tz=timezone.utc)
    for py_type, wrapper in _WRAPPERS:
        if isinstance(value, py_type):
            return wrapper(value, timestamp=timestamp)
    raise TypeError(f"compute function returned unsupported type {type(value)!r}")


class ComputeEngine:
    """Evaluate a :class:`ComputeConfig` against a :class:`MonitorSystem` on a tick loop.

    Parameters
    ----------
    config : ComputeConfig
        Topologically ordered nodes to evaluate each tick.
    monitor_system : MonitorSystem
        Tree providing both the source (hardware) points read as
        inputs and the ``monitorsystem`` points written as outputs.
        Computed outputs are updated in this tree's own
        :class:`MonitorPoint` objects in place (see :meth:`tick`, step
        4), which is what lets a downstream node see an upstream
        node's *this-tick* result rather than last tick's SMAX value.
    client : SmaxRedisClient or None, optional
        Used to refresh inputs (:meth:`MonitorSystem.read_all`) and to
        write outputs (``smax_share`` for the value, ``smax_push_meta``
        for validity). If ``None``, :meth:`tick` still computes and
        updates the in-memory tree but performs no I/O — useful for
        tests.
    clock : callable, optional
        Monotonic clock used for ``ctx.clock()`` (sequence/trajectory
        timing) and staleness comparisons against wall-clock reads —
        actually staleness compares against ``wall_clock`` (SMAX
        timestamps are wall-clock); ``clock`` is only exposed to
        compute functions. Defaults to :func:`time.monotonic`.
    wall_clock : callable, optional
        Wall-clock source used for SMAX timestamps and staleness
        comparisons. Defaults to :func:`time.time`.
    """

    def __init__(
        self,
        config: ComputeConfig,
        monitor_system: MonitorSystem,
        client: SmaxRedisClient | None = None,
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

        self._nodes: list[ComputeNode] = []
        self._interval_s: float = 5.0
        self._tick_outputs: dict[str, tuple[Any, Validity]] = {}

        self._apply_config(config)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run_forever(self) -> None:
        """Block, ticking at the configured interval, until :meth:`stop`.

        Mirrors :meth:`FaultSystem.run_forever` exactly: waits on a
        :class:`threading.Event` between ticks (so :meth:`stop` cuts
        the wait short), and logs+continues past exceptions from
        :meth:`tick` rather than crashing the loop.
        """
        logger.info(
            "ComputeEngine starting: %d nodes, interval=%.2fs",
            len(self._nodes), self._interval_s,
        )
        while not self._stop_event.is_set():
            try:
                self.tick()
            except Exception:
                logger.exception("ComputeEngine tick failed")
            with self._lock:
                interval = self._interval_s
            if self._stop_event.wait(interval):
                break
        logger.info("ComputeEngine stopped")

    def stop(self) -> None:
        """Signal :meth:`run_forever` to exit after the current tick."""
        self._stop_event.set()

    def set_interval(self, seconds: float) -> None:
        """Change the polling interval used by :meth:`run_forever`."""
        if seconds <= 0:
            raise ValueError(f"interval must be positive, got {seconds!r}")
        with self._lock:
            self._interval_s = float(seconds)
        logger.info("ComputeEngine interval set to %.2fs", seconds)

    def reload_config(self, path: str | Path) -> None:
        """Rebuild the node list from a new config file.

        Every node's ``state`` (see :attr:`ComputeNode.state`) starts
        fresh — trajectory checks like ``sequence_validity`` forget
        prior ticks across a reload, same as
        :meth:`FaultSystem.reload_config` resets fault debounce state.
        """
        new_config = ComputeConfig.from_file(path, self._monitor_system)
        with self._lock:
            self._apply_config(new_config)
        logger.info("ComputeEngine reloaded config from %s", path)

    @property
    def interval_s(self) -> float:
        with self._lock:
            return self._interval_s

    @property
    def nodes(self) -> list[ComputeNode]:
        """The current, topologically ordered node list (read-only view)."""
        return self._nodes

    def tick(self) -> list[ComputeResult]:
        """Run one evaluation pass over every node, in dependency order.

        1. If a client was provided, refresh source values via
           :meth:`MonitorSystem.read_all`.
        2. For each node, in topological order: resolve its inputs
           (see :meth:`_resolve_inputs`), call its registered function
           and validate its result (see :meth:`_evaluate_node`), unless
           resolution already short-circuited to ``INVALID_NO_DATA``.
           The function call and result validation are wrapped in
           try/except (design doc §8.3): any exception — including a
           multi-output function returning a mismatched key set — logs
           and resolves every one of *this node's*
           :attr:`ComputeNode.output_names` to ``INVALID_NO_DATA``,
           without aborting the tick for the remaining nodes.
        3. Record each canonical name's result in ``self._tick_outputs``
           so any later node in this same tick that depends on it sees
           it immediately (:meth:`_resolve_one` checks this before
           falling back to the tree).
        4. If a value was produced, write it to SMAX
           (``smax_share``) and update the tree's own
           :class:`MonitorPoint` in place; always push the validity
           metadata (``smax_push_meta("validity", ...)``), even for a
           short-circuited ``INVALID_NO_DATA`` result, so consumers
           can see that a computation had nothing to report this tick.

        Returns
        -------
        list of ComputeResult
            One entry per canonical name written (one per node for a
            single-output entry, one per role for a multi-output entry —
            see design doc §8), in topological order of the owning node.
        """
        if self._client is not None:
            self._monitor_system.read_all(self._client)

        now_wall = self._wall_clock()
        self._tick_outputs = {}
        results: list[ComputeResult] = []

        for node in self._nodes:
            per_output = self._evaluate_node(node, now_wall)
            for name, (value, validity) in per_output.items():
                self._tick_outputs[name] = (value, validity)
                self._write_one(name, value, validity, now_wall)
                results.append(ComputeResult(name, value, validity))

        return results

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _apply_config(self, config: ComputeConfig) -> None:
        self._nodes = config.nodes
        self._interval_s = config.default_interval_s

    def _resolve_one(self, name: str, now_wall: float, staleness_s: float) -> tuple[Any, Validity]:
        """Resolve a single input name to ``(value, effective_validity)``.

        Checks ``self._tick_outputs`` first (an already-computed node
        output from *this* tick takes priority over the tree, which
        for a computed point may still hold last tick's value). A
        missing point, a ``None`` value, or a point older than
        ``staleness_s`` all resolve to ``INVALID_NO_DATA`` — this
        engine-level policy is what lets compute functions assume
        every input they see is fresh (design doc §3.4).
        """
        if name in self._tick_outputs:
            return self._tick_outputs[name]

        try:
            mp = self._monitor_system.get_monitor_point(name)
        except KeyError:
            return None, Validity.INVALID_NO_DATA

        value = mp.value
        if value is None:
            return None, Validity.INVALID_NO_DATA

        try:
            stale = (now_wall - mp.time.unix) > staleness_s
        except (AttributeError, TypeError, ValueError):
            # mp.time is None (never updated), or the underlying
            # result has no usable .timestamp -- narrowed
            # deliberately: a bare `except Exception` here would also
            # swallow bugs in _wrap()/mp.time itself as silent,
            # permanent INVALID_NO_DATA, the worst failure shape for
            # a monitoring system.
            stale = True
        if stale:
            return value, Validity.INVALID_NO_DATA

        return value, mp.validity

    def _resolve_inputs(self, node: ComputeNode, now_wall: float):
        """Resolve every input for ``node``, applying its invalid-input policy.

        Returns ``None`` if the node should short-circuit to
        ``INVALID_NO_DATA`` without calling its function: for
        dict-form inputs, any missing/stale named input does this
        (a required named input can't be dropped); for list-form
        inputs, ``"propagate"`` does this on any invalid input, and
        both policies do this if *every* input turns out invalid
        (nothing left to compute over).
        """
        if isinstance(node.inputs, dict):
            resolved: dict[str, ResolvedInput] = {}
            for key, name in node.inputs.items():
                value, validity = self._resolve_one(name, now_wall, node.staleness_s)
                if validity == Validity.INVALID_NO_DATA:
                    return None
                resolved[key] = ResolvedInput(name, value, validity)
            return resolved

        resolved_list: list[ResolvedInput] = []
        for name in node.inputs:
            value, validity = self._resolve_one(name, now_wall, node.staleness_s)
            if validity == Validity.INVALID_NO_DATA:
                if node.invalid_inputs == "propagate":
                    return None
                continue
            resolved_list.append(ResolvedInput(name, value, validity))
        if not resolved_list:
            return None
        return resolved_list

    def _derive_validity(self, output: str, value: Any, now_wall: float) -> Validity:
        """Determine validity for a function that returned a bare value.

        Writes ``value`` into the output point's own
        :class:`MonitorPoint` and reads back its ``validity`` — this
        reuses whatever thresholds (or, per Phase 1, ``state_validity``
        map) are declared for that point in ``smax.json``, exactly as
        for any ordinary point.
        """
        mp = self._monitor_system.get_monitor_point(output)
        mp.update(_wrap(value, now_wall))
        return mp.validity

    def _evaluate_node(
        self, node: ComputeNode, now_wall: float
    ) -> dict[str, tuple[Any, Validity]]:
        """Resolve, call, and validate one node; never raises.

        Returns a mapping of every one of ``node``'s
        :attr:`ComputeNode.output_names` to its ``(value, Validity)``
        result. Three ways a node ends up with ``INVALID_NO_DATA`` for
        every one of its outputs: input resolution short-circuited
        (:meth:`_resolve_inputs` returned ``None``), the function call
        raised, or — for a multi-output node — the function's returned
        dict didn't have exactly the declared role names (design doc
        §8.2). Per §8.3, none of these abort the tick for other nodes:
        the exception is caught here, logged, and only this node's
        outputs are marked invalid.
        """
        resolved = self._resolve_inputs(node, now_wall)
        if resolved is None:
            return {name: (None, Validity.INVALID_NO_DATA) for name in node.output_names}

        try:
            ctx = ComputeContext(clock=self._clock, state=node.state, params=node.params)
            fn = get_function(node.function)
            outcome = fn(resolved, ctx)

            if isinstance(node.output, dict):
                if not isinstance(outcome, dict) or set(outcome) != set(node.output):
                    got = sorted(outcome) if isinstance(outcome, dict) else type(outcome).__name__
                    raise ValueError(
                        f"multi-output computation {node.output!r}: function "
                        f"{node.function!r} must return a dict with exactly the "
                        f"declared role keys {sorted(node.output)}, got {got!r}"
                    )
                per_output: dict[str, tuple[Any, Validity]] = {}
                for role, name in node.output.items():
                    role_outcome = outcome[role]
                    if isinstance(role_outcome, tuple):
                        value, validity = role_outcome
                    else:
                        value = role_outcome
                        validity = self._derive_validity(name, value, now_wall)
                    per_output[name] = (value, validity)
                return per_output

            if isinstance(outcome, tuple):
                value, validity = outcome
            else:
                value = outcome
                validity = self._derive_validity(node.output, value, now_wall)
            return {node.output: (value, validity)}

        except Exception:
            logger.exception(
                "computation %r (function %r) failed; marking INVALID_NO_DATA",
                node.output, node.function,
            )
            return {name: (None, Validity.INVALID_NO_DATA) for name in node.output_names}

    def _write_one(self, canonical_name: str, value: Any, validity: Validity, now_wall: float) -> None:
        """Write one canonical name's result: value (if any) to SMAX, validity always.

        A short-circuited ``INVALID_NO_DATA`` result (``value is
        None``) is not written as a value — overwriting the last
        known-good value with nothing would discard real history for
        no benefit — but its validity metadata is still pushed, and
        the tree's :class:`MonitorPoint` is left untouched so a later,
        unrelated read of it isn't corrupted.
        """
        mp = self._monitor_system.get_monitor_point(canonical_name)
        if value is not None:
            # Idempotent for the bare-value-return path, where
            # _derive_validity() already called mp.update() with the
            # same value; the sole update for the (value, Validity)
            # tuple-return path.
            mp.update(_wrap(value, now_wall))
            if self._client is not None:
                self._client.smax_share(mp.table, mp.key, value)
        if self._client is not None:
            self._client.smax_push_meta("validity", canonical_name, str(int(validity)))
