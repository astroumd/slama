"""FaultConfig: loads the fault-system JSON config and expands __each__
template blocks into a flat list of FaultNode definitions."""
from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from pathlib import Path

from slama.monitor.monitorsystem import _parse_index_set

from .actions import Action, build_action
from .faultnode import FaultNode


DEFAULT_PLACEHOLDER_VAR = "i"


@dataclass
class FaultConfig:
    nodes: dict[str, FaultNode] = field(default_factory=dict)
    actions: dict[str, Action] = field(default_factory=dict)
    default_interval_s: float = 5.0

    @classmethod
    def from_file(cls, path: str | Path) -> "FaultConfig":
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"fault config not found: {path}")
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        return cls.from_dict(raw)

    @classmethod
    def from_dict(cls, raw: dict) -> "FaultConfig":
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

        # Validate parent references point to known nodes.
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
    """Expand one entry from the 'faults' list. A plain dict returns a
    single-element list; an __each__ block expands to one dict per index."""
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
    """Recursively replace '{var}' with value in every string inside obj."""
    placeholder = f"{{{var}}}"
    if isinstance(obj, str):
        return obj.replace(placeholder, value)
    if isinstance(obj, list):
        return [_substitute(x, var, value) for x in obj]
    if isinstance(obj, dict):
        return {k: _substitute(v, var, value) for k, v in obj.items()}
    return copy.deepcopy(obj)
