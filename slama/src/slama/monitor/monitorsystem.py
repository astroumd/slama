#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import json
from pathlib import Path
from smax import SmaxRedisClient
import treelib
from .monitorpoint import MonitorPoint


def _parse_index_set(spec: str) -> list[str]:
    """
    Parse an index-set specification string into an ordered list of string keys.

    The spec is a comma-separated list of tokens. Each token is either:

    - A single literal value (e.g. ``"acc1"``), or
    - A numeric range ``lo-hi`` (inclusive, e.g. ``"1-8"``).

    If ``lo`` has a leading zero (e.g. ``"01-08"``), the generated values are
    zero-padded to the same width (e.g. ``["01","02",...,"08"]``).

    Multiple range segments may appear in the same spec, separated by commas
    (e.g. ``"01-08,11-18,21-28"``).

    Order is preserved; duplicate values are an error.

    Examples:
        "1-8"              -> ["1","2","3","4","5","6","7","8"]
        "1-3,5,7-9"        -> ["1","2","3","5","7","8","9"]
        "01-08,11-18"      -> ["01","02",...,"08","11","12",...,"18"]
        "H,V"              -> ["H","V"]
        "acc1,acc2,acc3"   -> ["acc1","acc2","acc3"]
    """
    if not isinstance(spec, str) or not spec.strip():
        raise ValueError(f"index set spec must be a non-empty string, got {spec!r}")
    out: list[str] = []
    seen: set[str] = set()
    for raw in spec.split(","):
        token = raw.strip()
        if not token:
            raise ValueError(f"empty token in index set spec {spec!r}")
        if "-" in token:
            lo_s, hi_s = token.split("-", 1)
            lo_s, hi_s = lo_s.strip(), hi_s.strip()
            try:
                lo, hi = int(lo_s), int(hi_s)
            except ValueError:
                raise ValueError(
                    f"non-integer range endpoints in token {token!r} of spec {spec!r}"
                )
            if hi < lo:
                raise ValueError(f"reversed range in token {token!r} of spec {spec!r}")
            # Zero-padding: if lo_s has a leading zero, pad all values to that width
            if lo_s != str(lo):
                width = len(lo_s)
                values = [f"{i:0{width}d}" for i in range(lo, hi + 1)]
            else:
                values = [str(i) for i in range(lo, hi + 1)]
        else:
            values = [token]
        for v in values:
            if v in seen:
                raise ValueError(f"duplicate index value {v!r} in spec {spec!r}")
            seen.add(v)
            out.append(v)
    return out


class MonitorSubsystem:
    """Represents a JSON dictionary (branch node) in the monitor hierarchy."""
    def __init__(self, name: str, data: dict):
        self.name = name
        self.data = data  # raw JSON dict for this level

    def __repr__(self):
        return f"<MonitorSubsystem {self.name}>"


class MonitorSystem(treelib.Tree):
    """
    A monitoring system tree built from a hierarchical JSON config (smax.json).

    Branch nodes hold MonitorSubsystem objects; leaf nodes hold MonitorPoint objects.
    SMAX canonical names use ':' as separator, e.g. 'antenna:1:air:heater',
    where table='antenna:1:air' and key='heater'.
    """

    def __init__(self, path: Path):
        super().__init__()
        self._json_data = self._read_json_file(path)
        self.create_node(tag="root", identifier="root",
                         data=MonitorSubsystem("root", self._json_data))
        self._build_tree("root", self._json_data, smax_path="")

    def _read_json_file(self, path: Path) -> dict:
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"JSON file not found: {path}")
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _build_tree(self, parent_id: str, data: dict, smax_path: str) -> None:
        """Recursively builds the tree from a JSON dict."""
        for key, value in data.items():
            if key == "__each__":
                # Template expansion: instantiate `template` once per index in `over`.
                if not isinstance(value, dict) or "over" not in value or "template" not in value:
                    raise ValueError(
                        f"__each__ at {smax_path or '<root>'} must be a dict with "
                        f"'over' and 'template' keys"
                    )
                template = value["template"]
                if not isinstance(template, dict):
                    raise ValueError(
                        f"__each__ template at {smax_path or '<root>'} must be a dict"
                    )
                prefix = value.get("prefix", "")
                for idx in _parse_index_set(value["over"]):
                    node_key = f"{prefix}{idx}"
                    idx_path = f"{smax_path}:{node_key}" if smax_path else node_key
                    self.create_node(tag=node_key, identifier=idx_path,
                                     parent=parent_id,
                                     data=MonitorSubsystem(node_key, template))
                    self._build_tree(idx_path, template, idx_path)
                continue

            child_path = f"{smax_path}:{key}" if smax_path else key

            if isinstance(value, dict):
                if "smax_type" in value:
                    # Leaf node: this dict describes a single monitor point
                    mp = MonitorPoint(name=key, canonical_name=child_path, **value)
                    self.create_node(tag=key, identifier=child_path,
                                     parent=parent_id, data=mp)
                else:
                    # Branch node: recurse deeper
                    self.create_node(tag=key, identifier=child_path,
                                     parent=parent_id,
                                     data=MonitorSubsystem(key, value))
                    self._build_tree(child_path, value, child_path)
            # Primitive values (e.g. "description" strings at a branch level)
            # are metadata stored in the parent MonitorSubsystem.data — skip them.
            # List values are also skipped; array MPs use size/smax_type in a dict.

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    def all_monitor_points(self) -> list:
        """Return all leaf MonitorPoint nodes."""
        return [n.data for n in self.leaves() if isinstance(n.data, MonitorPoint)]

    def get_monitor_point(self, canonical_name: str) -> MonitorPoint:
        """Return the MonitorPoint for the given canonical name, or raise KeyError."""
        node = self.get_node(canonical_name)
        if node is not None and isinstance(node.data, MonitorPoint):
            return node.data
        raise KeyError(f"No MonitorPoint found for '{canonical_name}'")

    # ------------------------------------------------------------------
    # SMAX I/O
    # ------------------------------------------------------------------

    def read_all(self, client: SmaxRedisClient) -> None:
        """Pull current values from SMAX for every MonitorPoint in the tree."""
        for mp in self.all_monitor_points():
            result = client.smax_pull(mp.table, mp.key)
            mp.update(result)

    def write(self, canonical_name: str, value, client: SmaxRedisClient) -> None:
        """Write a value to SMAX for the named MonitorPoint."""
        mp = self.get_monitor_point(canonical_name)
        client.smax_share(mp.table, mp.key, value)

    # ------------------------------------------------------------------
    # Display
    # ------------------------------------------------------------------

    def summary(self) -> None:
        """Print a compact hierarchy summary."""
        self.show()

    def details(self) -> None:
        """Print identifier and data for every node."""
        for node in self.all_nodes_itr():
            print(f"{node.identifier}: {node.data}")
