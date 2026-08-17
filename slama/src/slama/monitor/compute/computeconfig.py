"""Load and validate ``computations.json`` into an ordered list of ``ComputeNode``.

Mirrors :class:`slama.fault.faultconfig.FaultConfig`: ``from_file`` reads
JSON, ``from_dict`` is the authoritative validation path (so tests can
build configs without temp files), ``__each__`` blocks are flattened
before per-entry validation, and any dangling reference is a load-time
``ValueError`` rather than a runtime surprise.

Two validations are new relative to ``FaultConfig`` (a fault node's
``canonical_name`` is never checked against the ``MonitorSystem`` tree):
every entry's ``output`` must already exist as a declared point (under
``monitorsystem`` in ``smax.json``), and every input pattern must resolve
to at least one real point. Both require a ``MonitorSystem`` instance at
load time, so :meth:`ComputeConfig.from_file`/``from_dict`` take one.
"""
from __future__ import annotations

import copy
import fnmatch
import itertools
import json
from dataclasses import dataclass, field
from pathlib import Path

from slama.monitor.monitorsystem import MonitorSystem, _parse_index_set

from .computenode import ComputeNode
from .functions import get_function


DEFAULT_PLACEHOLDER_VAR: str = "i"
"""Default ``__each__`` template placeholder name — matches
:data:`slama.fault.faultconfig.DEFAULT_PLACEHOLDER_VAR`.
"""


@dataclass
class ComputeConfig:
    """Parsed and validated ``computations.json``.

    Attributes
    ----------
    nodes : list of ComputeNode
        Topologically sorted so that any node depending on another
        node's ``output`` (see :func:`_build_dependency_order`)
        appears after it. This is the order :class:`ComputeEngine`
        iterates each tick.
    default_interval_s : float
        Global tick interval (design doc §7 decision 3 — one interval
        for all nodes; no per-node override is consulted yet).
    """

    nodes: list[ComputeNode] = field(default_factory=list)
    default_interval_s: float = 5.0

    @classmethod
    def from_file(cls, path: str | Path, monitor_system: MonitorSystem) -> "ComputeConfig":
        """Load, parse, and validate a compute config from a JSON file.

        Parameters
        ----------
        path : str or pathlib.Path
            Path to the JSON config (e.g. ``conf/computations.json``).
        monitor_system : MonitorSystem
            Tree used to validate that every ``output`` and every
            resolved input canonical name is a real, declared point.

        Raises
        ------
        FileNotFoundError, json.JSONDecodeError, ValueError
            See :meth:`from_dict` for the validation failures.
        """
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"compute config not found: {path}")
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        return cls.from_dict(raw, monitor_system)

    @classmethod
    def from_dict(cls, raw: dict, monitor_system: MonitorSystem) -> "ComputeConfig":
        """Build a :class:`ComputeConfig` from an already-parsed dict.

        1. Reads ``defaults`` (``interval_s``, ``staleness_s``,
           ``invalid_inputs``) with fallback values.
        2. Walks ``computations`` and expands each entry through
           :func:`_expand_entry`, flattening ``__each__`` blocks.
        3. For each expanded entry: resolves ``output`` and every
           input pattern to concrete canonical names (via
           :func:`_resolve_pattern`), checking each against
           ``monitor_system`` and against the registered function
           name.
        4. Builds the dependency DAG between entries (an entry depends
           on another if one of its literal input names equals the
           other's ``output``) and topologically sorts it, raising on
           any cycle.

        Raises
        ------
        ValueError
            Duplicate output, unknown function, an input or output
            pattern that resolves to zero points, or a dependency
            cycle.
        """
        defaults = raw.get("defaults", {}) or {}
        default_interval = float(defaults.get("interval_s", 5.0))
        default_staleness = float(defaults.get("staleness_s", 30.0))
        default_invalid_inputs = defaults.get("invalid_inputs", "skip")

        flat_entries: list[dict] = []
        for entry in raw.get("computations", []) or []:
            flat_entries.extend(_expand_entry(entry))

        nodes: list[ComputeNode] = []
        seen_outputs: set[str] = set()
        for entry in flat_entries:
            if "output" not in entry:
                raise ValueError(f"computation entry missing 'output': {entry!r}")
            output = entry["output"]
            if output in seen_outputs:
                raise ValueError(f"duplicate computation output {output!r}")
            seen_outputs.add(output)

            if not _point_exists(output, monitor_system):
                raise ValueError(
                    f"computation output {output!r} is not declared in the "
                    f"MonitorSystem tree (add it under 'monitorsystem' in smax.json)"
                )

            function = entry.get("function")
            if function is None:
                raise ValueError(f"computation {output!r} missing 'function'")
            get_function(function)  # raises ValueError if unregistered

            raw_inputs = entry.get("inputs")
            if raw_inputs is None:
                raise ValueError(f"computation {output!r} missing 'inputs'")
            inputs = _resolve_inputs_spec(output, raw_inputs, monitor_system)

            nodes.append(ComputeNode(
                output=output,
                function=function,
                inputs=inputs,
                params=dict(entry.get("params", {})),
                invalid_inputs=entry.get("invalid_inputs", default_invalid_inputs),
                staleness_s=float(entry.get("staleness_s", default_staleness)),
                interval_s=entry.get("interval_s"),
            ))

        ordered = _build_dependency_order(nodes)

        return cls(nodes=ordered, default_interval_s=default_interval)


# ---------------------------------------------------------------------------
# __each__ expansion — mirrors slama.fault.faultconfig's _expand_entry/_substitute
# ---------------------------------------------------------------------------

def _expand_entry(entry: dict) -> list[dict]:
    """Expand one entry from the ``computations`` list.

    Identical in shape to
    :func:`slama.fault.faultconfig._expand_entry` — duplicated rather
    than imported so ``slama.monitor.compute`` does not depend on the
    ``slama.fault`` package for a generic templating helper.
    """
    if "__each__" in entry:
        if set(entry.keys()) != {"__each__"}:
            raise ValueError(f"__each__ block must have no sibling keys: {entry!r}")
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
    """Recursively replace ``{var}`` with ``value`` in every string."""
    placeholder = f"{{{var}}}"
    if isinstance(obj, str):
        return obj.replace(placeholder, value)
    if isinstance(obj, list):
        return [_substitute(x, var, value) for x in obj]
    if isinstance(obj, dict):
        return {k: _substitute(v, var, value) for k, v in obj.items()}
    return copy.deepcopy(obj)


# ---------------------------------------------------------------------------
# Input-pattern resolution
# ---------------------------------------------------------------------------

def _point_exists(canonical_name: str, monitor_system: MonitorSystem) -> bool:
    try:
        monitor_system.get_monitor_point(canonical_name)
        return True
    except KeyError:
        return False


def _resolve_pattern(pattern: str, monitor_system: MonitorSystem) -> list[str]:
    """Expand one input pattern to one or more concrete canonical names.

    A pattern is a colon-separated path where each segment is passed
    through :func:`_parse_index_set` — a plain segment (``"antenna"``,
    ``"is_online"``) passes through unchanged, a range/comma segment
    (``"1-8"``, ``"H,V"``) expands to multiple values, and a glob
    segment (``"*"``, ``"air*"``) also passes through unchanged
    (``_parse_index_set`` treats it as a single literal token) so it
    can be matched with :func:`fnmatch.fnmatchcase` below. The
    Cartesian product of all segments' expansions gives the candidate
    paths.

    Any candidate containing ``*`` is then resolved against every
    canonical name in ``monitor_system`` via ``fnmatch``; any
    candidate without ``*`` is checked for exact existence. Every
    pattern must resolve to at least one point, or loading fails fast.
    """
    segments = pattern.split(":")
    per_segment = [_parse_index_set(seg) for seg in segments]
    candidates = [":".join(combo) for combo in itertools.product(*per_segment)]

    resolved: list[str] = []
    all_names = None  # computed lazily, only if a glob candidate appears
    for candidate in candidates:
        if "*" in candidate or "?" in candidate:
            if all_names is None:
                all_names = [mp.canonical_name for mp in monitor_system.all_monitor_points()]
            matches = [n for n in all_names if fnmatch.fnmatchcase(n, candidate)]
            if not matches:
                raise ValueError(
                    f"input pattern {candidate!r} (from {pattern!r}) matched no points"
                )
            resolved.extend(matches)
        else:
            if not _point_exists(candidate, monitor_system):
                raise ValueError(
                    f"input pattern {candidate!r} (from {pattern!r}) is not a "
                    f"declared point"
                )
            resolved.append(candidate)
    return resolved


def _resolve_inputs_spec(output: str, raw_inputs, monitor_system: MonitorSystem):
    """Resolve a config entry's ``inputs`` (list or dict form) to concrete names.

    List form: each pattern may expand to multiple names (ranges,
    globs); the results are concatenated in order into a single flat
    list. Dict form: each named pattern must resolve to exactly one
    name (dict inputs are meant to be one point per name).
    """
    if isinstance(raw_inputs, list):
        names: list[str] = []
        for pattern in raw_inputs:
            names.extend(_resolve_pattern(pattern, monitor_system))
        if not names:
            raise ValueError(f"computation {output!r} has no resolvable inputs")
        return names
    if isinstance(raw_inputs, dict):
        resolved = {}
        for key, pattern in raw_inputs.items():
            matches = _resolve_pattern(pattern, monitor_system)
            if len(matches) != 1:
                raise ValueError(
                    f"computation {output!r} dict input {key!r} ({pattern!r}) "
                    f"must resolve to exactly one point, got {len(matches)}"
                )
            resolved[key] = matches[0]
        return resolved
    raise ValueError(
        f"computation {output!r} 'inputs' must be a list or dict, got {type(raw_inputs)!r}"
    )


# ---------------------------------------------------------------------------
# Dependency ordering
# ---------------------------------------------------------------------------

def _input_names(node: ComputeNode) -> list[str]:
    if isinstance(node.inputs, dict):
        return list(node.inputs.values())
    return list(node.inputs)


def _build_dependency_order(nodes: list[ComputeNode]) -> list[ComputeNode]:
    """Topologically sort ``nodes`` so a node's dependencies precede it.

    A node ``A`` depends on node ``B`` iff one of ``A``'s resolved
    input names literally equals ``B.output`` (a glob input that
    happens to match a computed output is not detected as a
    dependency — see design doc §6.1's comparison table; this is a
    documented limitation, not a bug).

    Raises
    ------
    ValueError
        If the dependency graph contains a cycle; the message lists
        every node still unresolved when Kahn's algorithm stalls.
    """
    by_output = {n.output: n for n in nodes}
    depends_on: dict[str, set[str]] = {
        n.output: {name for name in _input_names(n) if name in by_output and name != n.output}
        for n in nodes
    }

    ordered: list[ComputeNode] = []
    remaining = set(by_output)
    while remaining:
        ready = sorted(name for name in remaining if not (depends_on[name] & remaining))
        if not ready:
            raise ValueError(
                f"dependency cycle among computation outputs: {sorted(remaining)}"
            )
        for name in ready:
            ordered.append(by_output[name])
            remaining.discard(name)
    return ordered
