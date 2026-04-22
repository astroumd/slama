"""DAG node and event record for the fault system.

This module defines the in-memory data structures that the fault loop
operates on:

* ``FAULT_STATES`` — the subset of ``Validity`` values that count as a
  fault.
* ``FaultNode`` — one vertex in the fault DAG. Holds both the static
  config (from JSON) and the per-tick runtime state used for debounce
  and dedup.
* ``FaultEvent`` — the value object passed to ``Action.fire()`` when
  the system decides a root fault should be reported.

Notes
-----
The ``parents`` field in ``FaultNode`` encodes **physical / causal**
fault dependency (e.g. "if this power rail drops, that heater will
necessarily read invalid"), not the colon-separated canonical-name
hierarchy of the :class:`MonitorSystem`. Sibling leaves under the
same branch are independent faults unless an explicit causal edge is
configured.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from slama.monitor.monitorpoint import Validity


FAULT_STATES: frozenset[Validity] = frozenset({
    Validity.INVALID_NO_DATA,
    Validity.INVALID_NO_HW,
    Validity.INVALID_HW_BAD,
    Validity.VALID_ERROR,
    Validity.VALID_ERROR_LOW,
    Validity.VALID_ERROR_HIGH,
})
"""frozenset of :class:`Validity`: the validity states that count as a fault.

A ``MonitorPoint`` whose current ``validity`` is in this set is
considered faulted for purposes of the fault loop. All other validity
values — including ``VALID_WARNING_*`` and ``VALID_NOT_CHECKED`` —
are **not** treated as faults here; warnings are a separate concern
from hard faults for the root-cause display.
"""


@dataclass
class FaultNode:
    """One vertex in the fault DAG.

    A ``FaultNode`` bundles the static configuration loaded from
    ``faults.json`` (``canonical_name``, ``parents``,
    ``transient_filter_s``, ``actions``) together with the per-tick
    runtime state (``first_fault_t``, ``last_reported_t``,
    ``last_reported_validity``) used to implement the debounce and
    dedup behavior in :meth:`FaultSystem.tick`.

    Attributes
    ----------
    canonical_name : str
        The fully-qualified monitor point name (e.g.
        ``"antenna:1:air:temperature"``). Matches a key in
        :meth:`MonitorSystem.get_monitor_point`.
    parents : list of str
        Canonical names of parents in the causal DAG. If any parent
        is currently faulted, this node is not treated as a root
        fault. The list is initialized empty (a root candidate).
    transient_filter_s : float
        Debounce window in seconds. A fault on this node is ignored
        until it has been continuously faulted for at least this many
        seconds. ``0.0`` disables the filter.
    actions : list of str
        Names of actions (keys into :attr:`FaultConfig.actions`) to
        fire when this node is reported as a root fault.
    first_fault_t : float or None
        Monotonic-clock time at which the current fault first
        appeared, or ``None`` if the node is currently good. Used by
        the transient filter. Reset to ``None`` whenever the point
        returns to a non-fault validity.
    last_reported_t : float or None
        Monotonic-clock time of the last event dispatched for this
        node, or ``None`` if no report has been issued for the
        current fault episode. Used for dedup so a single persistent
        fault fires actions once per validity transition, not every
        tick.
    last_reported_validity : Validity or None
        The ``validity`` value reported with the last event for this
        node. If the validity changes (e.g. from ``VALID_ERROR`` to
        ``INVALID_HW_BAD``), the event re-fires; otherwise it is
        suppressed. ``None`` matches ``last_reported_t``.
    """

    canonical_name: str
    parents: list[str] = field(default_factory=list)
    transient_filter_s: float = 0.0
    actions: list[str] = field(default_factory=list)

    first_fault_t: float | None = None
    last_reported_t: float | None = None
    last_reported_validity: Validity | None = None


@dataclass
class FaultEvent:
    """A single root-fault occurrence dispatched to :meth:`Action.fire`.

    Instances are created by :meth:`FaultSystem.tick` and passed to
    each configured :class:`Action` for one dispatch. They are
    read-only value objects — actions must not mutate them.

    Attributes
    ----------
    canonical_name : str
        The canonical name of the faulted monitor point.
    validity : Validity
        The current validity value, always a member of
        :data:`FAULT_STATES`.
    timestamp : float
        Wall-clock time of the tick that produced the event, in
        seconds since the Unix epoch (as returned by ``time.time()``).
        Suitable for formatting into an ISO timestamp for logs.
    transient_filter_s : float
        The debounce window that was configured for this node. Copied
        from :attr:`FaultNode.transient_filter_s` for convenience so
        actions can cite the filter value in alert bodies.
    """

    canonical_name: str
    validity: Validity
    timestamp: float
    transient_filter_s: float
