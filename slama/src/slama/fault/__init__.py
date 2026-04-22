"""Fault System for SLAMA.

The fault subsystem watches the validity of a configurable set of
"critical" monitor points and identifies which faults are **root
causes** versus which are downstream consequences of an upstream
failure. Only root faults trigger actions (log entries, future email
or alarm dispatchers), so a single upstream outage produces a single
alert rather than a cascade of dozens.

Overview
--------
The system consists of five cooperating pieces:

``FaultConfig``
    Parses a JSON config file describing the critical monitor points,
    their causal-dependency DAG, per-point debounce windows, and named
    actions.
``FaultNode``
    In-memory DAG node. Holds the static config for one critical
    point plus the runtime debounce / dedup state.
``FAULT_STATES``
    The subset of :class:`slama.monitor.monitorpoint.Validity` values
    that count as a fault.
``FaultEvent``
    The record dispatched to actions when a root fault fires.
``FaultSystem``
    The main orchestrator. Polls the :class:`MonitorSystem` on a loop,
    walks the DAG to find root faults, debounces transients, de-dupes
    across ticks, and calls :class:`Action` objects.
``Action`` / ``LogFileAction`` / ``build_action``
    Pluggable action protocol and the built-in log-file action, plus
    a factory that constructs actions from the JSON ``actions`` block.

Entry points
------------
The CLI is :mod:`slama.fault.__main__`::

    python -m slama.fault conf/faults.json [--interval SECONDS]

Programmatic use::

    from slama.fault import FaultConfig, FaultSystem
    cfg = FaultConfig.from_file("conf/faults.json")
    system = FaultSystem(cfg, monitor_system, client=smax_client)
    system.run_forever()

See Also
--------
slama.monitor.monitorpoint.Validity
    Enum of validity states; ``FAULT_STATES`` is a subset of its values.
slama.monitor.monitorsystem.MonitorSystem
    The tree of monitor points the fault system observes.
"""
from .faultnode import FAULT_STATES, FaultEvent, FaultNode
from .faultconfig import FaultConfig
from .faultsystem import FaultSystem
from .actions import Action, LogFileAction, build_action

__all__ = [
    "FAULT_STATES",
    "FaultEvent",
    "FaultNode",
    "FaultConfig",
    "FaultSystem",
    "Action",
    "LogFileAction",
    "build_action",
]
