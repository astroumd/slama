#!/usr/bin/env python3
"""
SMA Observation Timetable Generator
Idiomatic Python conversion of timetable.pl

Usage: python3 timetable.py <observation_log_file>

Reads an SMA observation log and prints a formatted summary table of
what was observed, when, and at what elevation.
"""

import re
import subprocess
import sys
from dataclasses import dataclass
from typing import Optional

# ---------------------------------------------------------------------------
# Table formatting
# ---------------------------------------------------------------------------

_RULE = "============================================================="
_HEADER = (
    f"{_RULE}\n"
    "|  HST  |  UTC  |       Source       |   Type   | Elevation |\n"
    f"{_RULE}"
)
_ROW = "| {hst:>5} | {utc:>5} | {source:<19} | {type_:<8} |   {el:<6}|"


def _print_row(hst: str, utc: str, source: str, type_: str, el: str) -> None:
    print(_ROW.format(hst=hst, utc=utc, source=source, type_=type_, el=el))


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

_TIME_RE = re.compile(r'([01]?[0-9]|2[0-3]):[0-5][0-9](:[0-5][0-9])?')


def _fix_utc(utc: str) -> str:
    """Zero-pad single-digit minutes: '9:5' -> '9:05'."""
    m = re.match(r'\b([0-9]+):([0-9])\b', utc)
    return f"{m.group(1)}:0{m.group(2)}" if m else utc


def _utc_to_hst(utc: str) -> str:
    """Convert UTC HH:MM to Hawaii Standard Time (UTC - 10 h)."""
    parts = utc.split(":")
    h = (int(parts[0]) - 10) % 24
    return f"{'00' if h == 0 else h}:{parts[1]}"


def _get_project_info(line: str):
    """Return (pi, project) from a 'project' line, or (None, None)."""
    if line.startswith("project"):
        parts = line.split("'")
        return (parts[1] if len(parts) > 1 else "",
                parts[3] if len(parts) > 3 else "")
    return None, None


def _get_integration(line: str) -> Optional[str]:
    """Return integration time value from an 'integrate' line."""
    if line.startswith("integrate"):
        parts = line.split()
        return parts[2] if len(parts) > 2 else None
    return None


def _get_time(line: str):
    """Return (hst, utc) from a 'The lookup time' line, or (None, None)."""
    if "The lookup time" in line:
        parts = line.split()
        utc = parts[7] if len(parts) > 7 else ""
        utc = _fix_utc(utc)
        return _utc_to_hst(utc), utc
    return None, None


def _get_elevation(line: str, pointed: bool = False, mosaic: bool = False) -> Optional[str]:
    if " el" not in line:
        return None
    if pointed:
        return "N/A"
    parts = line.split()
    return parts[5] if mosaic else (parts[3] if len(parts) > 3 else None)


def _get_other_source(line: str) -> Optional[str]:
    """Extract source name from a line that contains ' el'."""
    if " el" in line:
        return line.split()[0]
    return None


def _get_obs_source(line: str, mosaic: bool = False):
    """Return (source, type) from an 'observe -s …' line."""
    parts   = line.split()
    source  = parts[2] if len(parts) > 2 else ""
    obs_type = "Target"

    if "-t" in parts:
        idx = parts.index("-t")
        obs_type = parts[idx + 1] if idx + 1 < len(parts) else obs_type

    if "-n" in parts:
        idx_n = parts.index("-n")
        if mosaic:
            source = parts[12] if len(parts) > 12 else source
        else:
            source = parts[idx_n + 1] if idx_n + 1 < len(parts) else source
            if "-t" in parts:
                idx_t = parts.index("-t")
                obs_type = parts[idx_t + 1] if idx_t + 1 < len(parts) else obs_type

    return source, obs_type


# ---------------------------------------------------------------------------
# Record handlers
# ---------------------------------------------------------------------------

def _print_header(record: str) -> None:
    pi = project = integration = ""
    for line in record.splitlines():
        p, proj = _get_project_info(line)
        if p is not None:
            pi, project = p, proj
        intg = _get_integration(line)
        if intg:
            integration = intg
    print(f"\n{project}\tPI: {pi}\tInt. time: {integration}s")


def _record_obs(record: str, pointed: bool) -> None:
    hst = utc = source = obs_type = el = ""
    done   = False
    mosaic = bool(re.search(r'Mosaic', record, re.MULTILINE))

    for line in record.splitlines():
        if done:
            break
        h, u = _get_time(line)
        if h:
            hst, utc = h, u
        e = _get_elevation(line, pointed, mosaic)
        if e:
            el = e
        if line.startswith("observe -s"):
            source, obs_type = _get_obs_source(line, mosaic)
            done = True

    _print_row(hst, utc, source, obs_type, el)


def _record_pointing(record: str) -> None:
    lines    = record.splitlines()
    hst = utc = source = el = ""
    obs_type = "Pointing"

    if len(lines) > 4:
        source = _get_other_source(lines[4]) or ""
        el     = _get_elevation(lines[4])    or ""
    if len(lines) > 3:
        h, u = _get_time(lines[3])
        if h:
            hst, utc = h, u

    if "waveplates" in record and len(lines) > 5:
        h, u = _get_time(lines[4])
        if h:
            hst, utc = h, u
        el = _get_elevation(lines[5]) or el

    _print_row(hst, utc, source, obs_type, el)


def _record_transit(record: str) -> None:
    hst = utc = source = el = ""
    obs_type = "Transit"
    for line in record.splitlines():
        s = _get_other_source(line)
        if s:
            source = s
        e = _get_elevation(line)
        if e:
            el = e
        h, u = _get_time(line)
        if h:
            hst, utc = h, u
    _print_row(hst, utc, source, obs_type, el)


def _record_end(end_time: str) -> None:
    hst = _utc_to_hst(end_time) if end_time else ""
    _print_row(hst, end_time, "End of Observation", "", "")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def process_file(filename: str) -> None:
    # Report any sources missing a scan count
    result = subprocess.run(
        ["sed", "-n", r"/^The\scurrent\ssource/p", filename],
        capture_output=True, text=True,
    )
    for line in sorted(set(result.stdout.splitlines())):
        print(line)

    print(_HEADER)

    with open(filename) as f:
        content = f.read()

    current_time = ""
    chunk        = 0

    for record in content.split("\n-"):
        is_obs     = bool(re.search(r' observe -s ',  record, re.MULTILINE))
        is_pointing = bool(re.search(r' point on',    record))
        is_transit  = bool(re.search(r' transit ',    record))

        # Track most recent timestamp in this record
        for m in _TIME_RE.finditer(record):
            current_time = m.group(0)

        if chunk == 0:
            _print_header(record)

        if is_transit and not is_obs:
            _record_transit(record)
        if is_pointing:
            _record_pointing(record)
        if is_obs and not is_transit:
            _record_obs(record, is_pointing)

        chunk += 1

    _record_end(current_time)
    print(_RULE)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <observation_log_file>", file=sys.stderr)
        sys.exit(1)
    process_file(sys.argv[1])
