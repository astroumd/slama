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
import logging
from dataclasses import dataclass, field
from pathlib import Path

from slama.monitor.monitorsystem import MonitorSystem, _parse_index_set

from .computenode import ComputeNode
from .functions import get_function


logger = logging.getLogger(__name__)


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
            output_names = _output_names_for(output)

            for name in output_names:
                if name in seen_outputs:
                    raise ValueError(f"duplicate computation output {name!r}")
                seen_outputs.add(name)

                if not _point_exists(name, monitor_system):
                    raise ValueError(
                        f"computation output {name!r} is not declared in the "
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

            if "interval_s" in entry:
                logger.warning(
                    "computation %r sets 'interval_s' (%r), but ComputeEngine "
                    "does not yet consult per-node intervals (design doc §7 "
                    "decision 3) -- it will run on the engine's single global "
                    "interval instead",
                    output, entry["interval_s"],
                )

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

    Parameters
    ----------
    entry : dict
        One raw entry from ``computations.json``'s ``"computations"``
        list — either an ordinary entry (returned unchanged) or a
        single-key ``{"__each__": {"over": ..., "template": ...,
        "as": ...}}`` block.

    Returns
    -------
    list of dict
        ``[entry]`` unchanged if there is no ``__each__`` key;
        otherwise one substituted copy of ``__each__["template"]`` per
        index in ``__each__["over"]``.

    Raises
    ------
    ValueError
        If ``__each__`` has sibling keys, is not a dict, is missing
        ``"over"`` or ``"template"``, or ``"template"`` is not a dict.
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
    """Recursively replace ``{var}`` with ``value`` in every string.

    Parameters
    ----------
    obj : str, list, dict, or any
        The object to substitute into. Strings are scanned for the
        placeholder; lists and dicts are walked recursively (values
        only, for dicts — keys are returned unchanged); any other type
        is returned as a deep copy, untouched.
    var : str
        The placeholder variable name, without braces (e.g. ``"i"``
        for the literal placeholder ``"{i}"``).
    value : str
        The string to substitute in place of ``{var}``.

    Returns
    -------
    str, list, dict, or any
        A new object of the same shape as ``obj`` with every
        occurrence of ``{var}`` replaced by ``value``.
    """
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

def _output_names_for(output) -> list[str]:
    """Validate and flatten an entry's ``output`` to its canonical names.

    ``output`` is either a plain string (single-output) or a non-empty
    dict of role name -> canonical name (multi-output, design doc §8).
    Role names and canonical names must both be strings. Raises
    ``ValueError`` on any other shape, including an empty dict (a
    multi-output entry that produces nothing is a config mistake, not
    a valid zero-output entry).

    Parameters
    ----------
    output : str or dict of str to str
        The raw ``"output"`` value from one ``computations.json``
        entry, before any type validation.

    Returns
    -------
    list of str
        ``[output]`` for the single-output case, or
        ``list(output.values())`` for the multi-output case.

    Raises
    ------
    ValueError
        If ``output`` is not a str or dict, the dict is empty, or any
        dict key/value is not a str.
    """
    if isinstance(output, str):
        return [output]
    if isinstance(output, dict):
        if not output:
            raise ValueError(f"computation 'output' dict must not be empty: {output!r}")
        for role, name in output.items():
            if not isinstance(role, str) or not isinstance(name, str):
                raise ValueError(
                    f"computation 'output' dict must map str role -> str "
                    f"canonical name, got {output!r}"
                )
        return list(output.values())
    raise ValueError(f"computation 'output' must be a str or dict, got {output!r}")


def _point_exists(canonical_name: str, monitor_system: MonitorSystem) -> bool:
    """Check whether a canonical name is a declared point in ``monitor_system``.

    Parameters
    ----------
    canonical_name : str
        The exact canonical name to look up (no ranges, globs, or
        ``__each__`` placeholders — those are already resolved by the
        time this is called).
    monitor_system : MonitorSystem
        Tree to check against.

    Returns
    -------
    bool
        ``True`` if :meth:`MonitorSystem.get_monitor_point` succeeds
        for ``canonical_name``, ``False`` if it raises ``KeyError``.
    """
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

    A segment containing ``-`` that is *not* a valid numeric range
    (e.g. ``"4K-plate"``, ``"a1-a2"`` — real segment names in
    ``smax.json``) makes ``_parse_index_set`` raise; here that is
    caught and the segment is treated as a single literal instead.
    ``_parse_index_set`` itself is left raising for its other caller
    (``__each__`` expansion, shared with ``slama.fault``), where a
    malformed range is more likely a config typo than a literal name.

    Any candidate containing ``*`` is then resolved against every
    canonical name in ``monitor_system`` via ``fnmatch``; any
    candidate without ``*`` is checked for exact existence. Every
    pattern must resolve to at least one point, or loading fails fast.

    Parameters
    ----------
    pattern : str
        One colon-separated input pattern from a ``computations.json``
        entry's ``inputs`` (e.g. ``"antenna:1-8:is_online"``,
        ``"antenna:1:*"``).
    monitor_system : MonitorSystem
        Tree used both for exact-existence checks and, if a glob
        segment appears, as the source of every candidate canonical
        name to match against.

    Returns
    -------
    list of str
        Every concrete canonical name ``pattern`` resolves to (one or
        more).

    Raises
    ------
    ValueError
        If any expanded candidate is a literal name not declared in
        ``monitor_system``, or a glob candidate matches no points.
    """
    segments = pattern.split(":")
    per_segment = []
    for seg in segments:
        try:
            per_segment.append(_parse_index_set(seg))
        except ValueError:
            per_segment.append([seg])
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

    Parameters
    ----------
    output : str or dict of str to str
        The owning entry's raw ``"output"`` — used only to identify
        the entry in error messages, not interpreted here.
    raw_inputs : list of str or dict of str to str
        The entry's raw ``"inputs"`` value, before resolution.
    monitor_system : MonitorSystem
        Tree used by :func:`_resolve_pattern` to resolve each pattern.

    Returns
    -------
    list of str or dict of str to str
        Resolved canonical names, in the same shape (list or dict) as
        ``raw_inputs``.

    Raises
    ------
    ValueError
        If ``raw_inputs`` is neither a list nor a dict, a list form
        resolves to no names at all, or a dict-form pattern resolves
        to anything other than exactly one name.
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
    """Flatten a node's resolved ``inputs`` to a plain list of canonical names.

    Parameters
    ----------
    node : ComputeNode
        Node whose :attr:`ComputeNode.inputs` (list or dict form,
        already resolved to concrete canonical names) is flattened.

    Returns
    -------
    list of str
        ``list(node.inputs.values())`` for dict-form inputs, or
        ``list(node.inputs)`` for list-form inputs — either way, every
        canonical name ``node`` reads from, order-preserved.
    """
    if isinstance(node.inputs, dict):
        return list(node.inputs.values())
    return list(node.inputs)


def _build_dependency_order(nodes: list[ComputeNode]) -> list[ComputeNode]:
    """Topologically sort ``nodes`` so a node's dependencies precede it.

    A node ``A`` depends on node ``B`` iff one of ``A``'s resolved
    input names literally equals one of ``B``'s :attr:`ComputeNode.output_names`
    (a glob input that happens to match a computed output is not
    detected as a dependency — see design doc §6.1's comparison table;
    this is a documented limitation, not a bug). For a multi-output
    node, every one of its output names maps back to the same node —
    depending on *any* one of its results is a dependency on the whole
    entry, since they share one function call.

    Parameters
    ----------
    nodes : list of ComputeNode
        Fully-resolved nodes (every ``output``/``inputs`` already
        expanded to concrete canonical names), in no particular order.

    Returns
    -------
    list of ComputeNode
        The same nodes, reordered via Kahn's algorithm so every node
        appears after all the nodes it depends on. This is the order
        :meth:`ComputeConfig.from_dict` stores as
        :attr:`ComputeConfig.nodes`, and the order
        :meth:`slama.monitor.compute.engine.ComputeEngine.tick`
        iterates each tick.

    Raises
    ------
    ValueError
        If the dependency graph contains a cycle; the message lists
        every node still unresolved when Kahn's algorithm stalls.
    """
    by_output: dict[str, ComputeNode] = {}
    for n in nodes:
        for name in n.output_names:
            by_output[name] = n

    # Kahn's algorithm operates on nodes, keyed by their *first* output
    # name (arbitrary but stable, since output_names is never empty) —
    # every other output name for a multi-output node just aliases back
    # to the same node via by_output.
    key_of = {id(n): n.output_names[0] for n in nodes}
    depends_on: dict[str, set[str]] = {
        key_of[id(n)]: {
            key_of[id(by_output[name])]
            for name in _input_names(n)
            if name in by_output and by_output[name] is not n
        }
        for n in nodes
    }

    ordered: list[ComputeNode] = []
    by_key = {key_of[id(n)]: n for n in nodes}
    remaining = set(by_key)
    while remaining:
        ready = sorted(key for key in remaining if not (depends_on[key] & remaining))
        if not ready:
            raise ValueError(
                f"dependency cycle among computation outputs: {sorted(remaining)}"
            )
        for key in ready:
            ordered.append(by_key[key])
            remaining.discard(key)
    return ordered
