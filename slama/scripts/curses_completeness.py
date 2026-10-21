#!/usr/bin/env python3
"""
Check which monitor points a curses C page reads are covered by a SLAMA display.

A point is *covered* when it is shown as a row/cell on the display, or is
a (transitive) input to a ``monitorsystem`` computed point shown there.
Names are collected from the C file's string literals (``"RM_..."`` /
``"DSM_..."``) **and** from macros in the headers it ``#include``s, when
the C file uses the macro (e.g. ``RV rv[] = INIT_ANTSERVO_VARS`` in
``antservo.h``), which a plain grep of the C file misses.

Coverage is necessary, not sufficient: a page may read a value and never
display it (dead reads), so check ``printw`` usage for anything reported
missing. Run once before and once after a display change and diff, or use
``--compare``, to see only what the change lost or gained.

Usage:
    uv run scripts/curses_completeness.py C_FILE DISPLAY_JSON [--compare OLD_DISPLAY_JSON]
        [--missing] [--smax SMAX_JSON] [--computations COMPUTATIONS_JSON]

The SMA C sources (``cursesmonitor/src/*.c``, headers in ``../include``)
are not part of this repository.
"""

import argparse
import json
import re
import sys
from pathlib import Path

CONF = Path(__file__).resolve().parents[1] / "src" / "slama" / "conf"

NAME_RE = re.compile(r'"((?:RM|DSM)_[A-Z0-9_]+)"')
"""A quoted RM/DSM variable name in C source."""

INCLUDE_RE = re.compile(r'#include\s+"([^"]+)"')
"""A local ``#include "file"`` directive."""

DEFINE_RE = re.compile(r"#define\s+(\w+)((?:[^\n]*\\\n)*[^\n]*)")
"""A ``#define NAME body``, including backslash-continued lines."""


def read_names(c_file: Path) -> dict[str, str]:
    """Return every RM/DSM name a C page reads, with where it came from.

    Parameters
    ----------
    c_file : pathlib.Path
        The curses page source.

    Returns
    -------
    dict of str to str
        Name to source: ``""`` for a literal in ``c_file`` itself, else
        ``"header.h:MACRO"``. Headers are looked up next to ``c_file``
        and in ``../include``.
    """
    c = c_file.read_text(errors="replace")
    names = {n: "" for n in NAME_RE.findall(c)}
    for inc in INCLUDE_RE.findall(c):
        for d in (c_file.parent, c_file.parent.parent / "include"):
            header = d / inc
            if not header.is_file():
                continue
            for m in DEFINE_RE.finditer(header.read_text(errors="replace")):
                macro, body = m.group(1), m.group(2)
                if re.search(r"\b" + re.escape(macro) + r"\b", c):
                    for n in NAME_RE.findall(body):
                        names.setdefault(n, f"{inc}:{macro}")
            break
    return names


def display_points(display_file: Path) -> set[str]:
    """Return the point names shown on a display JSON (rows and cells)."""
    display = json.loads(display_file.read_text())
    shown = set()
    for block in display["layout"]:
        for item in block.get("rows", []) + block.get("cells", []):
            point = item.get("points") or item.get("point")
            if isinstance(point, str):
                shown.add(point)
    return shown


def generic(name: str) -> str:
    """Replace antenna numbers with the display template ``{ant}``."""
    return re.sub(r"acc\d+", "acc{ant}", re.sub(r"antenna:\d+", "antenna:{ant}", name))


def compute_inputs(nodes) -> dict[str, list[str]]:
    """Map each computed output to its input names.

    Parameters
    ----------
    nodes : iterable of ComputeNode
        Expanded nodes, e.g. ``ComputeConfig.nodes``.

    Returns
    -------
    dict of str to list of str
        Output canonical name (each output of a multi-output node) to
        its input canonical names.
    """
    out = {}
    for node in nodes:
        inputs = node.inputs.values() if isinstance(node.inputs, dict) else node.inputs
        outputs = node.output.values() if isinstance(node.output, dict) else [node.output]
        for o in outputs:
            out[o] = list(inputs)
    return out


def covered_names(shown: set[str], inputs_of: dict[str, list[str]]) -> set[str]:
    """Return the bare variable names covered by a display.

    Parameters
    ----------
    shown : set of str
        Point names on the display (templated with ``{ant}``).
    inputs_of : dict of str to list of str
        From :func:`compute_inputs`.

    Returns
    -------
    set of str
        The last ``:`` component of every shown point and every
        transitive input of a shown computed point.
    """
    covered = set(shown)

    def walk(output, seen):
        for i in inputs_of.get(output, []):
            if i not in seen:
                seen.add(i)
                covered.add(i)
                walk(i, seen)

    for output in inputs_of:
        if generic(output) in shown:
            walk(output, set())
    return {p.split(":")[-1] for p in covered}


def coverage(names: dict[str, str], covered: set[str]) -> dict[str, bool]:
    """Return name -> covered for every name the C page reads."""
    return {n: n in covered for n in names}


def main(argv=None) -> int:
    """Command-line entry point; see the module docstring."""
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("c_file", type=Path)
    ap.add_argument("display", type=Path)
    ap.add_argument("--compare", type=Path, metavar="OLD_DISPLAY",
                    help="print only names whose coverage differs from OLD_DISPLAY")
    ap.add_argument("--missing", action="store_true", help="print only uncovered names")
    ap.add_argument("--smax", type=Path, default=CONF / "smax.json")
    ap.add_argument("--computations", type=Path, default=CONF / "computations.json")
    args = ap.parse_args(argv)

    from slama.monitor.compute.computeconfig import ComputeConfig
    from slama.monitor.monitorsystem import MonitorSystem

    ms = MonitorSystem(str(args.smax))
    inputs_of = compute_inputs(ComputeConfig.from_file(args.computations, ms).nodes)
    names = read_names(args.c_file)
    new = coverage(names, covered_names(display_points(args.display), inputs_of))

    def tag(n):
        return f"  (via {names[n]})" if names[n] else ""

    if args.compare:
        old = coverage(names, covered_names(display_points(args.compare), inputs_of))
        for n in sorted(names):
            if old[n] != new[n]:
                print(f"{'GAINED' if new[n] else 'LOST  '} {n}{tag(n)}")
        return 0
    for n in sorted(names):
        if args.missing and new[n]:
            continue
        print(f"{'COVERED' if new[n] else 'missing'} {n}{tag(n)}")
    print(f"# {sum(new.values())}/{len(new)} covered", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
