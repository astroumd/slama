"""Load and expand the fault-system JSON configuration.

:class:`FaultConfig` is the on-disk schema for the fault system.
A valid config is a JSON document of the form::

    {
      "defaults": { "transient_filter_s": 5, "interval_s": 2 },
      "actions": {
        "log": { "type": "log_file", "path": "/var/log/slama/faults.log" }
      },
      "faults": [
        { "canonical_name": "antenna:1:power:ok", "actions": ["log"] },
        {
          "__each__": {
            "over": "1-8",
            "as": "i",
            "template": {
              "canonical_name": "antenna:{i}:air:heater",
              "parents": ["antenna:{i}:power:ok"],
              "actions": ["log"]
            }
          }
        }
      ]
    }

The loader flattens ``__each__`` template blocks (using the shared
:func:`slama.monitor.monitorsystem._parse_index_set` index expander)
into a single list of :class:`FaultNode` objects, validates that
every action and parent reference resolves, and rejects duplicate
canonical names.

Notes
-----
The ``parents`` list in each entry encodes **causal fault
dependency**, not the colon-separated canonical-name hierarchy of
the monitor system. Leaving ``parents`` empty is the correct choice
when no real physical dependency has been established.
"""
from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from pathlib import Path

from slama.monitor.monitorsystem import _parse_index_set

from .actions import Action, build_action
from .faultnode import FaultNode


DEFAULT_PLACEHOLDER_VAR: str = "i"
"""str: default template placeholder variable name.

In an ``__each__`` block, the loop index is substituted into
``{var}`` placeholders inside the template. If the block's ``"as"``
key is not given, the placeholder name defaults to this value —
matching the ``{i}`` convention used throughout the shipped
``conf/faults.json``.
"""


@dataclass
class FaultConfig:
    """Parsed and validated fault-system configuration.

    A :class:`FaultConfig` is produced by :meth:`from_file` or
    :meth:`from_dict` and consumed by :class:`FaultSystem` at
    construction / reload time. It contains fully-resolved
    :class:`FaultNode` objects (templates expanded, parent
    references checked) and materialized :class:`Action` instances
    (not raw dicts).

    Attributes
    ----------
    nodes : dict of str to FaultNode
        Map from canonical name to the DAG node for that point. The
        iteration order matches the order of appearance in the JSON
        (template blocks expanded in place).
    actions : dict of str to Action
        Map from action key (as used by
        :attr:`FaultNode.actions`) to a live :class:`Action`
        instance. Built via :func:`build_action`.
    default_interval_s : float
        Default polling interval in seconds for
        :meth:`FaultSystem.run_forever`. Pulled from
        ``defaults.interval_s`` with a fallback of ``5.0`` seconds.
    """

    nodes: dict[str, FaultNode] = field(default_factory=dict)
    actions: dict[str, Action] = field(default_factory=dict)
    default_interval_s: float = 5.0

    @classmethod
    def from_file(cls, path: str | Path) -> "FaultConfig":
        """Load, parse, and validate a fault config from a JSON file.

        Parameters
        ----------
        path : str or pathlib.Path
            Path to the JSON config file.

        Returns
        -------
        FaultConfig
            The fully-resolved config.

        Raises
        ------
        FileNotFoundError
            If ``path`` does not exist.
        json.JSONDecodeError
            If the file is not valid JSON.
        ValueError
            If the config fails the validation performed by
            :meth:`from_dict` (unknown action, duplicate node,
            dangling parent reference, malformed ``__each__`` block,
            etc.).
        """
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"fault config not found: {path}")
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        return cls.from_dict(raw)

    @classmethod
    def from_dict(cls, raw: dict) -> "FaultConfig":
        """Build a :class:`FaultConfig` from an already-parsed dict.

        This is the authoritative validation path — ``from_file`` is
        a thin wrapper that only adds JSON reading. Exposed as a
        classmethod so tests can construct configs without writing
        temporary files.

        The method:

        1. Reads ``defaults`` (``transient_filter_s``, ``interval_s``)
           with fallback values.
        2. Builds every action via :func:`build_action`.
        3. Walks ``faults`` and expands each entry through
           :func:`_expand_entry`, flattening ``__each__`` blocks.
        4. Constructs a :class:`FaultNode` per expanded entry,
           applying default ``transient_filter_s`` where not
           specified.
        5. Validates that every action key referenced by a fault
           resolves to a declared action, that canonical names are
           unique, and that every ``parents`` entry refers to a
           declared fault node.

        Parameters
        ----------
        raw : dict
            Parsed JSON config.

        Returns
        -------
        FaultConfig

        Raises
        ------
        ValueError
            For any of the validation failures listed above.
        """
        defaults = raw.get("defaults", {}) or {}
        default_transient = float(defaults.get("transient_filter_s", 0.0))
        default_interval = float(defaults.get("interval_s", 5.0))

        actions: dict[str, Action] = {}
        for key, spec in (raw.get("actions") or {}).items():
            actions[key] = build_action(spec)

        flat_entries: list[dict] = []
        for entry in raw.get("faults", []) or []:
            flat_entries.extend(_expand_entry(entry))

        nodes: dict[str, FaultNode] = {}
        for entry in flat_entries:
            if "canonical_name" not in entry:
                raise ValueError(f"fault entry missing 'canonical_name': {entry!r}")
            name = entry["canonical_name"]
            if name in nodes:
                raise ValueError(f"duplicate fault entry for {name!r}")
            for action_key in entry.get("actions", []):
                if action_key not in actions:
                    raise ValueError(
                        f"fault {name!r} references unknown action "
                        f"{action_key!r}; known: {sorted(actions)}"
                    )
            nodes[name] = FaultNode(
                canonical_name=name,
                parents=list(entry.get("parents", [])),
                transient_filter_s=float(
                    entry.get("transient_filter_s", default_transient)
                ),
                actions=list(entry.get("actions", [])),
            )

        for node in nodes.values():
            for parent in node.parents:
                if parent not in nodes:
                    raise ValueError(
                        f"fault {node.canonical_name!r} lists unknown parent "
                        f"{parent!r} (not declared as its own fault entry)"
                    )

        return cls(
            nodes=nodes,
            actions=actions,
            default_interval_s=default_interval,
        )


def _expand_entry(entry: dict) -> list[dict]:
    """Expand one entry from the ``faults`` list.

    Plain fault dicts are returned as a single-element list. An
    ``__each__`` block is expanded into one dict per index value
    produced by :func:`_parse_index_set` on the ``over`` field, with
    ``{var}`` placeholders replaced throughout the template.

    Parameters
    ----------
    entry : dict
        Either a plain fault dict (``{"canonical_name": ...}``) or
        an ``__each__`` wrapper::

            {
              "__each__": {
                "over": "1-8",
                "as": "i",         # optional, defaults to "i"
                "template": { ... }
              }
            }

    Returns
    -------
    list of dict
        One or more plain fault dicts with all placeholders
        substituted. The caller treats the result as a flat list.

    Raises
    ------
    ValueError
        If the ``__each__`` block has sibling keys at the top level,
        is not a dict, is missing ``over`` or ``template``, or has a
        non-dict ``template``.
    """
    if "__each__" in entry:
        if set(entry.keys()) != {"__each__"}:
            raise ValueError(
                f"__each__ block must have no sibling keys: {entry!r}"
            )
        each = entry["__each__"]
        if not isinstance(each, dict):
            raise ValueError(f"__each__ must be a dict: {entry!r}")
        if "over" not in each or "template" not in each:
            raise ValueError(
                f"__each__ block must have 'over' and 'template' keys: {entry!r}"
            )
        template = each["template"]
        if not isinstance(template, dict):
            raise ValueError(f"__each__ template must be a dict: {entry!r}")
        var = each.get("as", DEFAULT_PLACEHOLDER_VAR)
        indices = _parse_index_set(each["over"])
        return [_substitute(template, var, idx) for idx in indices]
    return [entry]


def _substitute(obj, var: str, value: str):
    """Recursively replace ``{var}`` with ``value`` in every string.

    Strings are substituted with :meth:`str.replace`; lists and dicts
    are walked recursively; all other types are deep-copied
    unchanged so each expansion produces an independent object.

    Parameters
    ----------
    obj : object
        The template tree element to process. Typically a dict at
        the top level; recursive calls may see any JSON-compatible
        value.
    var : str
        Placeholder name (without braces). The literal
        ``"{" + var + "}"`` is what gets replaced.
    value : str
        Replacement string. The index values from
        :func:`_parse_index_set` are always strings.

    Returns
    -------
    object
        A new object of the same shape as ``obj`` with substitutions
        applied. Input is never mutated.
    """
    placeholder = f"{{{var}}}"
    if isinstance(obj, str):
        return obj.replace(placeholder, value)
    if isinstance(obj, list):
        return [_substitute(x, var, value) for x in obj]
    if isinstance(obj, dict):
        return {k: _substitute(v, var, value) for k, v in obj.items()}
    return copy.deepcopy(obj)
