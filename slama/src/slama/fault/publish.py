"""Publish the fault system's per-tick decisions to SMAX.

The three SLAMA processes talk only through SMAX, so the fault system
publishes what it decided each tick for readers such as the Fault System
display page. It writes two points in its own top-level ``faultsystem``
table (``monitorsystem`` belongs to the compute engine):

- :data:`STATE_NAME` (``faultsystem:state``): one JSON snapshot of every
  fault node, built by :func:`build_snapshot`;
- :data:`FAULT_HEARTBEAT_NAME` (``faultsystem:heartbeat``): the tick's
  wall-clock epoch, written **after** the state, so a reader that sees a
  fresh heartbeat sees a state at least as new.

Snapshot format (``version`` 1)::

    {
      "version": 1,
      "tick": 1790094623.0,
      "interval_s": 2.0,
      "nodes": {
        "<canonical name>": {
          "state": "root",
          "validity": "VALID_ERROR",
          "since": 1790094421.0,
          "hidden_by": ["<faulted parent>", ...]     # consequence only
        },
        ...
      }
    }

Every node appears every tick, in ``faults.json`` order, so a reader can
tell ``ok`` from "missing". Readers parse with :func:`parse_snapshot`,
which checks ``version``. Why one snapshot rather than one SMAX point per
node is recorded in ``docs/source/fault-system.md`` ("Published state").
"""
from __future__ import annotations

import json
import logging
from typing import Iterable, Mapping

from slama.monitor.monitorpoint import Validity

from .faultnode import FaultNode


logger = logging.getLogger(__name__)

__all__ = [
    "SNAPSHOT_VERSION", "STATE_NAME", "FAULT_HEARTBEAT_NAME", "TABLE", "STATES",
    "build_snapshot", "node_state", "publish", "parse_snapshot", "state_counts",
]

TABLE: str = "faultsystem"
"""str: the fault system's own SMAX table."""

STATE_NAME: str = f"{TABLE}:state"
"""str: canonical name of the JSON snapshot point."""

FAULT_HEARTBEAT_NAME: str = f"{TABLE}:heartbeat"
"""str: canonical name of the fault system's own heartbeat point.

Not the compute engine's heartbeat
(:data:`slama.monitor.compute.engine.HEARTBEAT_NAME`,
``monitorsystem:engine:heartbeat``), which is a fault node.
"""

SNAPSHOT_VERSION: int = 1
"""int: snapshot format version; :func:`parse_snapshot` rejects others."""

STATES: tuple[str, ...] = ("ok", "consequence", "debouncing", "ignored", "root")
"""tuple of str: every node state, in the precedence :func:`node_state` applies."""


def node_state(name: str, *, faulted: set[str], debounced: set[str],
               hidden: set[str], ignored: bool) -> str:
    """Classify one node for the snapshot; the first matching rule wins.

    Parameters
    ----------
    name : str
        The node's canonical name.
    faulted : set of str
        Nodes whose verdict is a fault this tick.
    debounced : set of str
        Faulted nodes whose filter has elapsed this tick.
    hidden : set of str
        Faulted nodes with at least one faulted parent this tick.
    ignored : bool
        Whether an active ignore pattern matches ``name``.

    Returns
    -------
    str
        ``"ok"`` when not faulted; ``"consequence"`` when hidden;
        ``"debouncing"`` while the filter runs; ``"ignored"`` for a root
        an ignore pattern suppresses; otherwise ``"root"``. Dedup does
        not change the state: a root stays ``"root"`` after its event.
    """
    if name not in faulted:
        return "ok"
    if name in hidden:
        return "consequence"
    if name not in debounced:
        return "debouncing"
    if ignored:
        return "ignored"
    return "root"


def build_snapshot(nodes: Mapping[str, FaultNode], *,
                   validities: Mapping[str, Validity],
                   faulted: set[str], debounced: set[str], hidden: set[str],
                   is_ignored, tick: float, interval_s: float) -> dict:
    """Build one tick's snapshot (pure: no I/O, no clock reads).

    Parameters
    ----------
    nodes : mapping of str to FaultNode
        The DAG, in config order; :attr:`FaultNode.faulted_since` supplies
        ``since``.
    validities : mapping of str to Validity
        Each node's verdict this tick.
    faulted, debounced, hidden : set of str
        This tick's classification, as computed by
        :meth:`FaultSystem.tick <slama.fault.faultsystem.FaultSystem.tick>`.
    is_ignored : callable
        ``is_ignored(name) -> bool``: whether an ignore pattern matches.
    tick : float
        The tick's wall-clock epoch.
    interval_s : float
        The polling interval in effect.

    Returns
    -------
    dict
        The snapshot described in the module docstring.
    """
    out_nodes: dict[str, dict] = {}
    for name, node in nodes.items():
        entry = {
            "state": node_state(name, faulted=faulted, debounced=debounced,
                                hidden=hidden, ignored=is_ignored(name)),
            "validity": validities[name].name,
            "since": node.faulted_since,
        }
        if name in hidden:
            entry["hidden_by"] = [p for p in node.parents if p in faulted]
        out_nodes[name] = entry
    return {
        "version": SNAPSHOT_VERSION,
        "tick": float(tick),
        "interval_s": float(interval_s),
        "nodes": out_nodes,
    }


def publish(client, snapshot: dict) -> None:
    """Write ``snapshot`` to :data:`STATE_NAME`, then the heartbeat.

    Parameters
    ----------
    client : SmaxRedisClient
        Connected client; ``smax_share`` is the only method used.
    snapshot : dict
        From :func:`build_snapshot`. Its ``tick`` becomes the heartbeat
        value.

    Raises
    ------
    Exception
        Whatever ``smax_share`` raises. The caller decides whether a
        failure is fatal; :class:`FaultSystem` logs it and carries on.
    """
    text = json.dumps(snapshot, separators=(",", ":"))
    client.smax_share(TABLE, "state", text)
    client.smax_share(TABLE, "heartbeat", float(snapshot["tick"]))


def parse_snapshot(text) -> dict:
    """Parse a ``faultsystem:state`` value written by :func:`publish`.

    Parameters
    ----------
    text : str or bytes
        The pulled value.

    Returns
    -------
    dict
        The snapshot.

    Raises
    ------
    ValueError
        If ``text`` is not JSON, not an object, or its ``version`` is not
        :data:`SNAPSHOT_VERSION`.
    """
    if isinstance(text, (bytes, bytearray)):
        text = text.decode("utf-8")
    try:
        snapshot = json.loads(text)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError(f"faultsystem:state is not JSON: {exc}") from exc
    if not isinstance(snapshot, dict):
        raise ValueError("faultsystem:state is not a JSON object")
    version = snapshot.get("version")
    if version != SNAPSHOT_VERSION:
        raise ValueError(
            f"faultsystem:state version {version!r}; this reader understands "
            f"{SNAPSHOT_VERSION}"
        )
    return snapshot


def state_counts(snapshot: dict, states: Iterable[str] = STATES) -> dict[str, int]:
    """Count nodes per state, for a one-line summary.

    Parameters
    ----------
    snapshot : dict
        From :func:`build_snapshot` or :func:`parse_snapshot`.
    states : iterable of str, optional
        States to report, in order. Defaults to :data:`STATES`.

    Returns
    -------
    dict of str to int
        ``state -> count``, including zero counts, in ``states`` order.
    """
    counts = dict.fromkeys(states, 0)
    for entry in snapshot["nodes"].values():
        counts[entry["state"]] = counts.get(entry["state"], 0) + 1
    return counts
