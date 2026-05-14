#!/usr/bin/env python3
"""
Compare monitor points defined in smax.json against the flat list from the
Valkey database (docs/all_monitor_points.txt) and report what is missing from
smax.json.

Usage:
    uv run src/slama/scripts/compare_monitor_points.py [--in-smax] [--missing]

Options:
    --missing   (default) Print names present in Valkey but absent from smax.json
    --in-smax   Print names present in smax.json but absent from Valkey
"""

import argparse
import json
from pathlib import Path


def parse_range(range_str: str) -> list[str]:
    """Parse a range string like '1-8' or '1,3,5' into a list of string indices."""
    indices = []
    for part in range_str.split(","):
        part = part.strip()
        if "-" in part:
            start, end = part.split("-", 1)
            indices.extend(str(i) for i in range(int(start), int(end) + 1))
        else:
            indices.append(part)
    return indices


def is_leaf(obj: dict) -> bool:
    """A dict node is a leaf monitor point if it declares an smax_type."""
    return "smax_type" in obj


def expand_smax(obj, prefix: str = "") -> set[str]:
    """
    Recursively expand a smax.json subtree into a set of canonical names.

    Handles the ``__each__`` template pattern which expands a subtree over
    a numeric range (e.g. antenna 1-8).
    """
    names: set[str] = set()

    if not isinstance(obj, dict):
        return names

    # Handle __each__ template: replicate template subtree for each index
    if "__each__" in obj:
        each = obj["__each__"]
        template = each["template"]
        for idx in parse_range(each["over"]):
            sub_prefix = f"{prefix}:{idx}" if prefix else idx
            names |= expand_smax(template, sub_prefix)
        # Also process any sibling keys outside __each__ at this level
        for key, value in obj.items():
            if key == "__each__":
                continue
            sub_prefix = f"{prefix}:{key}" if prefix else key
            names |= expand_smax(value, sub_prefix)
        return names

    # Leaf node: emit the canonical name
    if is_leaf(obj):
        if prefix:
            names.add(prefix)
        # Also recurse into children that are themselves dicts (nested structure)
        for key, value in obj.items():
            if isinstance(value, dict):
                sub_prefix = f"{prefix}:{key}" if prefix else key
                names |= expand_smax(value, sub_prefix)
        return names

    # Interior node: recurse into children
    for key, value in obj.items():
        sub_prefix = f"{prefix}:{key}" if prefix else key
        if isinstance(value, dict):
            names |= expand_smax(value, sub_prefix)

    return names


def load_smax_names(smax_path: Path) -> set[str]:
    with smax_path.open() as f:
        data = json.load(f)
    return expand_smax(data)


def load_valkey_names(txt_path: Path) -> set[str]:
    names = set()
    for line in txt_path.read_text().splitlines():
        line = line.strip()
        if line:
            names.add(line)
    return names


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--missing", action="store_true", default=True,
                       help="Show Valkey names absent from smax.json (default)")
    group.add_argument("--in-smax", action="store_true",
                       help="Show smax.json names absent from Valkey")
    group.add_argument("--common", action="store_true",
                       help="Show names present in both files")
    group.add_argument("--summary", action="store_true",
                       help="Print only the summary counts, no names")
    # scripts/ sits at the repo root
    _repo_root = Path(__file__).resolve().parent.parent
    parser.add_argument("--smax", type=Path,
                        default=_repo_root / "src" / "slama" / "conf" / "smax.json",
                        help="Path to smax.json")
    parser.add_argument("--valkey", type=Path,
                        default=_repo_root / "docs" / "all_monitor_points.txt",
                        help="Path to all_monitor_points.txt")
    args = parser.parse_args()

    smax_names = load_smax_names(args.smax)
    valkey_names = load_valkey_names(args.valkey)

    if args.in_smax:
        result = sorted(smax_names - valkey_names)
        label = "In smax.json but NOT in Valkey"
    elif args.common:
        result = sorted(smax_names & valkey_names)
        label = "In both smax.json and Valkey"
    elif args.summary:
        result = []
        label = ""
    else:
        result = sorted(valkey_names - smax_names)
        label = "In Valkey but NOT in smax.json"

    if not args.summary:
        print(f"# {label} ({len(result)} entries)\n")
        for name in result:
            print(name)
        print()

    missing = valkey_names - smax_names
    in_smax_only = smax_names - valkey_names
    common = smax_names & valkey_names
    print(f"# Summary")
    print(f"  smax.json canonical names : {len(smax_names)}")
    print(f"  Valkey names              : {len(valkey_names)}")
    print(f"  In both                   : {len(common)}")
    print(f"  In Valkey, not smax.json  : {len(missing)}")
    print(f"  In smax.json, not Valkey  : {len(in_smax_only)}")


if __name__ == "__main__":
    main()
