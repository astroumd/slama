"""Config node, resolved input, and runtime context for the compute engine.

This module defines the small value types that :mod:`computeconfig` builds
and :mod:`engine` consumes:

* ``ComputeNode`` — one entry from ``computations.json``, fully resolved
  (input patterns expanded to concrete canonical names, ``__each__``
  templates flattened). Also carries the one piece of *runtime* state a
  node needs across ticks: ``state``, a plain dict handed back to the
  computation function every tick via ``ComputeContext.state`` (see
  design doc §3.5/§4.1 — this is what lets a stateless-function design
  express sequence/trajectory checks like a tuning-state timeout).
* ``ResolvedInput`` — one input's value bundled with the *effective*
  validity the engine computed for it this tick (see
  :meth:`slama.monitor.compute.engine.ComputeEngine._resolve_one`).
* ``ComputeContext`` — the ``ctx`` argument passed to every registered
  compute function: a clock, this node's persistent ``state`` dict, and
  this node's static ``params`` from config.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable

from slama.monitor.monitorpoint import Validity


@dataclass
class ComputeNode:
    """One fully-resolved entry from ``computations.json``.

    Attributes
    ----------
    output : str or dict of str to str
        Canonical name(s) of the point(s) this entry writes. A plain
        string is the single-output case (unchanged since Phase 2). A
        dict maps function-local **role names** to canonical names for
        a multi-output entry (design doc §8) — the role names are never
        written to SMAX, only used to match the function's returned
        dict back to the right canonical name; this is what keeps a
        multi-output function reusable under ``__each__`` expansion
        (same roles, different resolved canonical names per index).
        Every canonical name in :attr:`output_names` must already exist
        in the ``MonitorSystem`` tree (declared under ``monitorsystem``
        in ``smax.json``) — checked at load time by
        :meth:`ComputeConfig.from_dict`.
    function : str
        Name of a function registered in
        :data:`slama.monitor.compute.functions.FUNCTION_REGISTRY`.
    inputs : list of str or dict of str to str
        Resolved canonical names to read. A list gives an ordered set
        (functions receive a ``list[ResolvedInput]``); a dict gives
        named inputs (functions receive a ``dict[str, ResolvedInput]``,
        and any missing/stale named input short-circuits the whole
        node to ``INVALID_NO_DATA`` — see
        :meth:`slama.monitor.compute.engine.ComputeEngine._resolve_inputs`).
    params : dict
        Static configuration passed through to the function via
        :attr:`ComputeContext.params` (lookup tables, timeouts, etc.).
        Never interpreted by the engine itself.
    invalid_inputs : {"skip", "propagate"}
        Policy for list-form inputs when some are missing/stale.
        ``"skip"`` computes over the remaining valid subset (unless
        *all* are invalid, which always short-circuits);
        ``"propagate"`` short-circuits the whole node if any input is
        invalid. Ignored for dict-form inputs, which always behave as
        ``"propagate"`` (a named input can't sensibly be dropped).
    staleness_s : float or None
        An input older than this many seconds is treated as
        ``INVALID_NO_DATA`` regardless of its own validity. ``None``
        disables the age check entirely (a present, non-``None`` value
        is never stale).
    input_staleness : dict of str to (float or None)
        Per-input overrides of :attr:`staleness_s`, keyed by dict-form
        input role name (config form ``{"name": ..., "staleness_s":
        ...}``). A role absent from this dict uses :attr:`staleness_s`.
        Needed because many RM status points are only written to SMAX
        when their value *changes*, so their SMAX timestamp says
        nothing about whether the hardware is still reporting; such an
        input gets ``None`` here and the function checks freshness
        against an RM heartbeat input (e.g. ``RM_SERVO_TIMESTAMP_L``)
        instead. See :meth:`staleness_for`.
    interval_s : float or None
        Reserved for future per-entry tick cadence (design doc §7
        decision 3). Not yet consulted by :class:`ComputeEngine` —
        every node currently runs on the engine's single global
        interval.
    state : dict
        Runtime-only. Created empty and handed back unchanged every
        tick via :attr:`ComputeContext.state`; cleared only by
        :meth:`ComputeConfig.from_dict` producing a fresh node (i.e.
        on :meth:`ComputeEngine.reload_config`).
    """

    output: str | dict[str, str]
    function: str
    inputs: list[str] | dict[str, str]
    params: dict = field(default_factory=dict)
    invalid_inputs: str = "skip"
    staleness_s: float | None = 30.0
    interval_s: float | None = None
    input_staleness: dict[str, float | None] = field(default_factory=dict)

    state: dict = field(default_factory=dict)

    @property
    def output_names(self) -> list[str]:
        """Every canonical name this entry writes, in a uniform list.

        ``[output]`` for the single-output (str) case, or
        ``list(output.values())`` for the multi-output (dict) case —
        the one place config/engine code should look when it needs
        "every point this entry produces" rather than caring which
        shape ``output`` is.
        """
        if isinstance(self.output, dict):
            return list(self.output.values())
        return [self.output]

    def staleness_for(self, role: str | None) -> float | None:
        """Staleness limit, in seconds, to apply to one input.

        Parameters
        ----------
        role : str or None
            Dict-form input role name, or ``None`` for a list-form
            input (list-form inputs have no per-input override).

        Returns
        -------
        float or None
            ``input_staleness[role]`` if the role has an override
            (which may itself be ``None``, meaning "never stale"),
            otherwise the node-wide :attr:`staleness_s`.
        """
        if role is not None and role in self.input_staleness:
            return self.input_staleness[role]
        return self.staleness_s


@dataclass
class ResolvedInput:
    """One input's current value, paired with its effective validity.

    Attributes
    ----------
    canonical_name : str
        The point this input was read from.
    value : Any
        Its current value (``None`` only ever appears transiently
        during resolution; a :class:`ResolvedInput` with ``value is
        None`` is never handed to a compute function).
    validity : Validity
        The *effective* validity for this tick — ``INVALID_NO_DATA``
        if the point was missing or older than the node's
        ``staleness_s``, otherwise the point's own ``validity``
        (hardware thresholds, or another node's already-computed
        result this same tick).
    timestamp : float or None
        Epoch seconds of the input's last SMAX write, or ``None`` if
        unknown (e.g. a same-tick computed output). Lets a function
        compare a value against *when it was written* rather than
        against "now", which includes the engine's own read lag (see
        ``clock_offset``).
    """

    canonical_name: str
    value: Any
    validity: Validity
    timestamp: float | None = None


@dataclass
class ComputeContext:
    """Runtime handle passed to every compute function as ``ctx``.

    Attributes
    ----------
    clock : callable
        Monotonic-style clock, ``() -> float``. Injectable for tests
        (see :class:`slama.fault.test.test_faultsystem.FakeClock` for
        the pattern this mirrors).
    state : dict
        This node's persistent state, shared across ticks — see
        :attr:`ComputeNode.state`.
    params : dict
        This node's static config, shared across ticks — see
        :attr:`ComputeNode.params`.
    wall_clock : callable
        Wall-clock epoch seconds, ``() -> float``: the same clock the
        engine uses for SMAX timestamps and staleness. Functions that
        compare an RM heartbeat *value* (e.g. ``RM_TRACK_TIMESTAMP_L``,
        a Unix time) against "now" must use this, not :attr:`clock`,
        which is monotonic and has an arbitrary epoch. Defaults to
        :func:`time.time`; :class:`ComputeEngine` injects its own
        ``wall_clock`` so tests stay deterministic.
    """

    clock: Callable[[], float]
    state: dict
    params: dict
    wall_clock: Callable[[], float] = time.time
