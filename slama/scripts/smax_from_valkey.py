#!/usr/bin/env python3
"""Generate smax.json entries for variables present in Valkey but missing from smax.json.

Reads a file of missing SMAX paths (one per line, e.g. from
``compare_monitor_points.py --missing``), queries the live SMAX/Valkey database
for each leaf variable's type and dimension, and outputs a JSON fragment
(organised by top-level namespace with ``__each__`` blocks where applicable)
that can be reviewed and merged into ``conf/smax.json``.

Usage
-----
    uv run scripts/smax_from_valkey.py [INPUT_FILE] [--output OUTPUT_FILE]

    INPUT_FILE defaults to ``valkeynotsmax.txt`` in the repo root.
    If --output is omitted, the JSON is written to stdout.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

# Import filter_leaves from sibling script (safe now that argparse is guarded)
sys.path.insert(0, str(Path(__file__).parent))
from dump_redis import filter_leaves


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class EachGroup:
    """Describes a detected ``__each__`` expansion group."""
    prefix: str          # e.g. "acc" for acc1-acc8, "roach2-" for roach2-01
    indices: list[str]   # numeric suffix strings, e.g. ["1","2",...,"8"]
    keys: list[str]      # original segment keys in the group


# ---------------------------------------------------------------------------
# Input filtering
# ---------------------------------------------------------------------------

def filter_input(lines: list[str]) -> list[str]:
    """Filter raw input lines to valid hierarchical SMAX paths.

    Skips blank lines, comment lines (starting with ``#``), lines with no
    ``:`` separator (no hierarchy), and ``RM:acc9:*`` entries.

    Parameters
    ----------
    lines : list of str
        Raw lines from the input file.

    Returns
    -------
    list of str
        Cleaned, valid hierarchical paths.
    """
    result = []
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        if line.startswith("RM:acc9:"):
            continue
        result.append(line)
    return result


# ---------------------------------------------------------------------------
# Pattern detection
# ---------------------------------------------------------------------------

# Matches a segment ending in digits, capturing the alpha prefix and the digits.
# Examples: "acc1" -> ("acc", "1"),  "roach2-01" -> ("roach2-", "01"),  "1" -> ("", "1")
_TRAILING_DIGITS = re.compile(r"^(.*?)(\d+)$")


def detect_each_group(keys: list[str]) -> tuple[Optional[EachGroup], list[str]]:
    """Detect a repeating ``__each__`` group within a list of segment keys.

    Groups keys that share the same non-digit prefix and differ only in their
    trailing digit suffix.  A group requires at least two members.  At most one
    group is returned (the largest one); all other keys are returned as singletons.

    Parameters
    ----------
    keys : list of str
        Segment key strings at the current level of the hierarchy.

    Returns
    -------
    tuple of (EachGroup or None, list of str)
        The detected group (or None) and the list of singleton keys.
    """
    # Group keys by their non-digit prefix
    by_prefix: dict[str, list[tuple[str, str]]] = defaultdict(list)
    no_digits: list[str] = []

    for key in keys:
        m = _TRAILING_DIGITS.match(key)
        if m:
            prefix, digits = m.group(1), m.group(2)
            by_prefix[prefix].append((digits, key))
        else:
            no_digits.append(key)

    # Pick the largest prefix group (must have >= 2 members)
    best: Optional[tuple[str, list[tuple[str, str]]]] = None
    for prefix, members in by_prefix.items():
        if len(members) >= 2:
            if best is None or len(members) > len(best[1]):
                best = (prefix, members)

    if best is None:
        return None, list(keys)

    prefix, members = best
    group = EachGroup(
        prefix=prefix,
        indices=[d for d, _ in members],
        keys=[k for _, k in members],
    )
    # Singletons: keys not in this group
    group_key_set = set(group.keys)
    singletons = [k for k in keys if k not in group_key_set]
    return group, singletons


# ---------------------------------------------------------------------------
# Numeric helpers
# ---------------------------------------------------------------------------

def dim_to_size(dim: Any) -> str:
    """Convert a ``SmaxVarBase.dim`` value to a size string.

    Parameters
    ----------
    dim : int or tuple
        Dimension from a ``SmaxVarBase`` object.

    Returns
    -------
    str
        Product of all dimensions as a string (e.g. ``(24, 6)`` → ``"144"``).
    """
    if isinstance(dim, (tuple, list)):
        return str(math.prod(dim)) if dim else "1"
    return str(int(dim))


def indices_to_over_spec(indices: list[str]) -> str:
    """Convert a list of digit-string indices to an ``__each__`` ``over`` spec.

    Detects zero-padding from the first element and collapses contiguous
    numeric runs into ``lo-hi`` notation.  Multiple non-contiguous runs are
    joined with commas.

    Parameters
    ----------
    indices : list of str
        Digit strings, e.g. ``["01","02",...,"08","11",...,"18"]``.

    Returns
    -------
    str
        A compact ``over`` spec, e.g. ``"01-08,11-18"``.
    """
    if not indices:
        return ""

    # Detect zero-padding width
    nums = sorted(int(i) for i in indices)
    first_str = sorted(indices, key=int)[0]
    width = len(first_str) if first_str != str(int(first_str)) else 0

    def fmt(n: int) -> str:
        return f"{n:0{width}d}" if width else str(n)

    # Collapse contiguous runs
    ranges: list[tuple[int, int]] = []
    lo = hi = nums[0]
    for n in nums[1:]:
        if n == hi + 1:
            hi = n
        else:
            ranges.append((lo, hi))
            lo = hi = n
    ranges.append((lo, hi))

    parts = []
    for lo, hi in ranges:
        if lo == hi:
            parts.append(fmt(lo))
        else:
            parts.append(f"{fmt(lo)}-{fmt(hi)}")
    return ",".join(parts)


# ---------------------------------------------------------------------------
# Tree builder
# ---------------------------------------------------------------------------

def build_subtree(prefix: str, rel_paths: list[str], query_fn: Callable,
                  errors: list | None = None) -> dict:
    """Recursively build a smax.json-style subtree dict.

    Queries ``query_fn(table, key)`` for each true leaf.  Detects ``__each__``
    groups among the first path segment and generates appropriate ``__each__``
    blocks.  Leaves whose query fails are silently omitted from the output;
    their full canonical names are appended to ``errors`` if provided.

    Parameters
    ----------
    prefix : str
        Absolute SMAX path to the current node (used to build query paths).
    rel_paths : list of str
        Paths relative to ``prefix`` to place under this node.
    query_fn : callable
        ``query_fn(table, key)`` returns a ``SmaxVarBase``-like object with
        ``.type``, ``.dim``, ``.description``, and ``.unit`` attributes.
    errors : list or None, optional
        Mutable list to which failed canonical names are appended.  If None,
        failures are silently discarded.

    Returns
    -------
    dict
        JSON-serialisable dict for this subtree (failed leaves omitted).
    """
    if errors is None:
        errors = []
    result: dict = {}

    # Separate direct leaves (no further ':') from deeper paths
    direct_leaves: list[str] = []
    by_child: dict[str, list[str]] = defaultdict(list)

    for path in rel_paths:
        if ":" not in path:
            direct_leaves.append(path)
        else:
            child, rest = path.split(":", 1)
            by_child[child].append(rest)

    # Query and record each direct leaf; skip failures
    for leaf in sorted(direct_leaves):
        full = f"{prefix}:{leaf}" if prefix else leaf
        table, key = full.rsplit(":", 1)
        entry = _query_leaf(table, key, query_fn, errors)
        if entry is not None:
            result[leaf] = entry

    if not by_child:
        return result

    # Detect __each__ group among child keys
    group, singletons = detect_each_group(list(by_child.keys()))

    if group is not None:
        # Use the first (alphabetically smallest) member as the representative
        rep_key = min(group.keys, key=lambda k: (len(k), k))
        rep_prefix = f"{prefix}:{rep_key}" if prefix else rep_key
        template = build_subtree(rep_prefix, by_child[rep_key], query_fn, errors)

        over = indices_to_over_spec(group.indices)
        ordered: dict = {"over": over}
        if group.prefix:
            ordered["prefix"] = group.prefix
        ordered["template"] = template
        result["__each__"] = ordered

    # Recurse into singletons
    for key in sorted(singletons):
        child_prefix = f"{prefix}:{key}" if prefix else key
        result[key] = build_subtree(child_prefix, by_child[key], query_fn, errors)

    return result


def _query_leaf(table: str, key: str, query_fn: Callable,
                errors: list) -> dict | None:
    """Call ``query_fn`` and build the leaf entry dict.

    Returns ``None`` on failure and appends the canonical name to ``errors``.
    """
    full_path = f"{table}:{key}"
    try:
        var = query_fn(table, key)
        entry: dict = {
            "size": dim_to_size(var.dim),
            "smax_type": var.type,
        }
        desc = getattr(var, "description", None)
        unit = getattr(var, "unit", None)
        if desc is not None:
            entry["description"] = desc
        if unit is not None:
            entry["unit"] = unit
        return entry
    except Exception:
        errors.append(full_path)
        return None


# ---------------------------------------------------------------------------
# Top-level entry point
# ---------------------------------------------------------------------------

def generate_smax_json(input_path: Path,
                       query_fn: Callable) -> tuple[dict, list[str]]:
    """Read the input file and generate a smax.json-style dict of missing entries.

    Parameters
    ----------
    input_path : Path
        Path to the missing-variables file (e.g. ``valkeynotsmax.txt``).
    query_fn : callable
        SMAX query function with signature ``(table, key) -> SmaxVarBase``.

    Returns
    -------
    tuple of (dict, list of str)
        The JSON-serialisable output dict keyed by namespace, and a list of
        canonical names whose database query failed.
    """
    lines = input_path.read_text().splitlines()
    paths = filter_input(lines)
    paths = filter_leaves(paths)

    # Group by top-level namespace
    by_ns: dict[str, list[str]] = defaultdict(list)
    for path in paths:
        ns, rest = path.split(":", 1)
        by_ns[ns].append(rest)

    errors: list[str] = []
    output: dict = {}
    for ns in sorted(by_ns):
        output[ns] = build_subtree(ns, by_ns[ns], query_fn, errors)

    return output, errors


# ---------------------------------------------------------------------------
# Merge helper
# ---------------------------------------------------------------------------

def deep_merge(base: dict, overlay: dict) -> dict:
    """Recursively merge *overlay* into *base*, with *base* taking precedence.

    For each key in *overlay*:

    - If the key is absent from *base*, it is added.
    - If both values are dicts, the function recurses.
    - Otherwise the *base* value is kept (base wins on conflicts).

    Neither input dict is mutated; a new dict is returned.

    Parameters
    ----------
    base : dict
        The authoritative dict (e.g. smax.json).  Its values are preserved.
    overlay : dict
        The dict whose keys are added where missing from *base*.

    Returns
    -------
    dict
        Merged result with all keys from both inputs.
    """
    result = dict(base)
    for key, ov_val in overlay.items():
        if key not in result:
            result[key] = ov_val
        elif isinstance(result[key], dict) and isinstance(ov_val, dict):
            result[key] = deep_merge(result[key], ov_val)
        # else: base wins — keep result[key] unchanged
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    _REPO_ROOT = Path(__file__).resolve().parent.parent

    _DEFAULT_SMAX_JSON = _REPO_ROOT / "src" / "slama" / "conf" / "smax.json"

    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("input", nargs="?",
                        default=str(_REPO_ROOT / "valkeynotsmax.txt"),
                        help="Input file of missing SMAX paths (default: valkeynotsmax.txt)")
    parser.add_argument("--output", "-o", default="-",
                        help="Output JSON file path, or '-' for stdout (default)")
    parser.add_argument("--merge", "-m", metavar="SMAX_JSON", nargs="?",
                        const=str(_DEFAULT_SMAX_JSON),
                        help="Merge generated entries into SMAX_JSON (default: conf/smax.json) "
                             "and write the combined result to --output. "
                             "smax.json values take precedence on conflicts.")
    parser.add_argument("--host", default="localhost", help="SMAX host (default: localhost)")
    parser.add_argument("--port", type=int, default=6380, help="SMAX port (default: 6380)")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="List names of variables that could not be fetched")
    args = parser.parse_args()

    from smax import SmaxRedisClient
    client = SmaxRedisClient(args.host, redis_port=args.port)

    def _smax_query(table, key):
        return client.smax_pull(table, key)

    result, errors = generate_smax_json(Path(args.input), _smax_query)

    if args.merge:
        merge_path = Path(args.merge)
        if not merge_path.exists():
            print(f"Error: merge file not found: {merge_path}", file=sys.stderr)
            sys.exit(1)
        base = json.loads(merge_path.read_text())
        result = deep_merge(base, result)
        print(f"Merged with {merge_path}", file=sys.stderr)

    json_str = json.dumps(result, indent=2)
    if args.output == "-":
        print(json_str)
    else:
        Path(args.output).write_text(json_str)
        print(f"Written to {args.output}", file=sys.stderr)

    if errors:
        print(f"{len(errors)} variable(s) could not be fetched from Valkey and were omitted.",
              file=sys.stderr)
        if args.verbose:
            for name in sorted(errors):
                print(f"  {name}", file=sys.stderr)
