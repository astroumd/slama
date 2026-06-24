#!/usr/bin/env python3
"""
SMA Observation Control - Core Library
Idiomatic Python conversion of sma.pl
"""

import argparse
import math
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Optional


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

@dataclass
class State:
    """All mutable state for the SMA observation script."""
    # runtime flags
    simulate_mode: bool = False
    restart: bool = False
    opt_figure: bool = False
    opt_mosaic: bool = False
    opt_pointing: bool = False
    opt_day: bool = False
    opt_night: bool = False
    opt_b: bool = False
    opt_k: bool = False

    # timing
    unix_time: float = 0.0
    prev_unix_time: float = 0.0
    total_integration_time: float = 0.0
    tsys_delay: float = 11.0
    observe_delay: float = 10.0
    point_delay: float = 120.0

    # pointing
    last_pointing: float = 0.0
    night_pointing: bool = False
    night_pointing_time: int = 10800   # 3 hours
    day_pointing_time: int = 3600      # 1 hour
    max_pointing_el: float = 75.0
    min_pointing_el: float = 25.0
    pointing_cal: str = ""
    ipoint: str = ""

    # loops / restart
    max_loops: int = 200
    loop_counter: int = 0
    garrus: int = 0            # restart loop index
    the_word: List[int] = field(default_factory=list)
    partial_scans: int = 0
    partial_obs_loop: int = 0
    loops_done: int = 0
    stuff: List[str] = field(default_factory=list)

    # sources
    current_source: str = ""
    last_source: str = ""
    current_el: float = 0.0
    source_az: float = 0.0
    source_el: float = 0.0
    sun_distance: float = 0.0

    # calibration
    transcal: str = ""
    ntranscal: str = "10"
    special_flux: bool = False
    flux_value: float = 1.0
    flux_track: bool = False

    # antennas
    sma: List[int] = field(default_factory=list)
    nants: int = 0
    pants: str = ""
    ants: str = ""
    antenna: str = ""
    ant_list: str = ""

    # elevation limits (set by the observation script)
    MINEL_TARG: float = 17.0
    MAXEL_TARG: float = 83.0
    MINEL_GAIN: float = 17.0
    MAXEL_GAIN: float = 83.0
    MINEL_FLUX: float = 17.0
    MAXEL_FLUX: float = 81.0
    MINEL_BPASS: float = 17.0
    MAXEL_BPASS: float = 87.0
    MINEL_CHECK: float = 19.0

    # integration time (string, passed to commands)
    inttime: str = "15"

    # LST window
    LST_start: float = 0.0
    LST_end: float = 24.0

    # misc
    given_utc: str = ""
    first_time: bool = True
    this_machine: str = ""
    mypid: int = 0
    myname: str = ""
    sunrise: str = ""
    sunset: str = ""


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def parse_args(state: State) -> None:
    parser = argparse.ArgumentParser(
        description="SMA Observation Script",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=_USAGE_EPILOG,
    )
    parser.add_argument("--time", "-t", dest="given_utc", default="",
                        metavar="'MM DD YYYY HH MM'",
                        help="Start time for simulation")
    parser.add_argument("--simulate", "-s", action="store_true",
                        help="Run in simulate mode")
    parser.add_argument("--restart", "-r", action="store_true",
                        help="Skip initial bandpass and flux")
    parser.add_argument("--mosaic", "-m", action="store_true",
                        help="Skip tsys after each target")
    parser.add_argument("--figure", "-f", action="store_true",
                        help="Figure out where script left off and restart")
    parser.add_argument("--antennas", "-a", dest="ant_list", default="",
                        help="Comma-separated antennas to exclude from tsys")
    parser.add_argument("--pointing", "-p", action="store_true",
                        help="Opt out of automatic pointing")
    parser.add_argument("--ipoint", "-i", dest="ipoint", default="",
                        help="Extra ipoint options (in quotes)")
    parser.add_argument("--day", "-d", action="store_true",
                        help="Toggle off accepting ipoint results during the day")
    parser.add_argument("--night", "-n", action="store_true",
                        help="Toggle on accepting ipoint results at night")
    parser.add_argument("--value", "-v", dest="flux_value", type=float, default=1.0,
                        help="Minimum flux (Jy) for pointing calibrator")
    parser.add_argument("-b", action="store_true",
                        help="Use receiver B for pointing")
    parser.add_argument("-k", action="store_true",
                        help="Add -k to ipoint commands")
    parser.add_argument("--max-loops", type=int, default=200,
                        dest="max_loops",
                        help="Stop after this many obs loops (default 200)")
    args = parser.parse_args()

    state.simulate_mode = args.simulate
    state.restart       = args.restart
    state.opt_figure    = args.figure
    state.opt_mosaic    = args.mosaic
    state.opt_pointing  = args.pointing
    state.opt_day       = args.day
    state.opt_night     = args.night
    state.opt_b         = args.b
    state.opt_k         = args.k
    state.given_utc     = args.given_utc
    state.flux_value    = args.flux_value or 1.0
    state.ant_list      = args.ant_list
    state.ipoint        = args.ipoint
    state.max_loops     = args.max_loops


_USAGE_EPILOG = """
Script-level variables that can be set in the observation script:
  state.pointing_cal        Force a specific pointing calibrator
  state.night_pointing_time Night pointing cadence in seconds (default 10800)
  state.day_pointing_time   Day pointing cadence in seconds (default 3600)
  state.pants               Two antennas used for pointing calibration
  state.max_loops           Stop after this many loops
"""


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------

def initialize(state: State) -> None:
    print("initializing.....")

    if state.given_utc:
        _parse_given_utc(state)

    print(f"simulateMode = {state.simulate_mode}")

    state.max_pointing_el = 75.0
    state.min_pointing_el = max(25.0, state.MINEL_GAIN)

    signal.signal(signal.SIGINT, lambda sig, frame: finish(state))

    uname = subprocess.run(["uname", "-a"], capture_output=True, text=True).stdout
    state.this_machine = uname.split()[1] if uname.split() else ""
    print(f"Running on machine = {state.this_machine}")

    if state.this_machine not in ("hal9000", "obscon1"):
        print("Not running on hal9000, entering simulation mode.")
        state.simulate_mode = True

    print(f"{state.simulate_mode}")

    if state.simulate_mode:
        state.last_pointing = state.unix_time
    else:
        _find_last_pointing(state)

    print(f"The last pointing time is {state.last_pointing}")

    _compute_sun_times(state)

    state.mypid  = os.getpid()
    state.myname = sys.argv[0]

    if not state.simulate_mode:
        run_command("radecoff -r 0 -d 0", state)
        run_command(f"project -r -i {state.mypid} -f {state.myname}", state)
        print_pid(state)
    else:
        print(f"Script: {state.myname}.")

    if state.ant_list:
        _parse_ant_list(state)

    if state.opt_figure:
        _figure_restart(state)


def _parse_given_utc(state: State) -> None:
    parts = state.given_utc.split()
    mn, d, year, gh, gm = int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3]), int(parts[4])
    # Use calendar.timegm for UTC -> unix timestamp
    from calendar import timegm
    state.unix_time = float(timegm((year, mn, d, gh, gm, 0, 0, 0, 0)))
    state.prev_unix_time = state.unix_time


def _month_to_num(mon: str) -> int:
    return {"Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
            "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12}.get(mon, 0)


def _find_last_pointing(state: State) -> None:
    from calendar import timegm
    date_str = subprocess.run(["date", "+%y%m%d"], capture_output=True, text=True).stdout.strip()
    year_str = subprocess.run(["date", "-u", "+%Y"], capture_output=True, text=True).stdout.strip()
    year = int(year_str)
    last_year = str(year - 1)
    ant = state.sma[3] if len(state.sma) > 3 else 4

    def _mtime_from_ls(path: str) -> float:
        result = subprocess.run(["ls", "-l", path], capture_output=True, text=True).stdout.strip()
        if not result or last_year in result:
            return 0.0
        parts = result.split()
        if len(parts) < 8:
            return 0.0
        mon_num = _month_to_num(parts[5])
        day = int(parts[6])
        h, m = parts[7].split(":")[:2]
        return float(timegm((year, mon_num, day, int(h), int(m), 0, 0, 0, 0)))

    ipoint_time = _mtime_from_ls(f"/data/engineering/ipoint/ant{ant}/{date_str}")
    cpoint_time = _mtime_from_ls(f"/data/engineering/rpoint/ant{ant}/tmp.dat.lowfreq")

    if ipoint_time == 0 and cpoint_time == 0:
        state.last_pointing = time.time()
        print("No pointing could be found, setting the last pointing time to now.")
    elif ipoint_time >= cpoint_time:
        state.last_pointing = ipoint_time
        print("The last pointing was a ipoint.")
    else:
        state.last_pointing = cpoint_time
        print("The last pointing was a cpoint.")


def _compute_sun_times(state: State) -> None:
    lookup_bin = "./lookup" if state.this_machine == "oldulua" else "lookup"
    try:
        sun = subprocess.run([lookup_bin, "-s", "sun", "-w"],
                             capture_output=True, text=True).stdout
    except FileNotFoundError:
        print("lookup binary not found, skipping sun time calculation.")
        return

    words = sun.split()
    if len(words) < 12:
        return

    if words[3] == 'elevation':
        offset = 4
    else:
        offset = 0

    def _hm(s: str):
        parts = s.rstrip(',').split(':')
        return int(parts[0]), int(parts[1])

    rise_h, rise_m = _hm(words[5+offset])
    set_h,  set_m  = _hm(words[11+offset])

    if set_h > 23:
        set_h -= 24

    # Adjust rise: subtract ~1 hour
    rise_h -= 1
    if rise_m > 45:
        rise_m -= 45
    else:
        rise_h -= 1
        rise_m += 15

    # Adjust set: add ~1 hour
    set_h += 1
    if set_m <= 20:
        set_m += 40
    else:
        set_h += 1
        set_m -= 20

    # Handle minute overflow
    if rise_m == 60:
        rise_h = (rise_h + 1) % 24
        rise_m = 0
    if set_m == 60:
        set_h = (set_h + 1) % 24
        set_m = 0

    state.sunrise = f"{rise_h}{rise_m:02d}"
    state.sunset  = f"{set_h}{set_m:02d}"
    print(f"Sunrise is {state.sunrise} and sunset is {state.sunset}")

    # Add an extra hour to sunset for switching to night pointing
    state.sunset = str(int(state.sunset) + 100)
    print(f"Sunset is now {state.sunset}")

    now = datetime.now()
    sunset_unix = now.replace(hour=(set_h + 1) % 24, minute=set_m,
                              second=0, microsecond=0).timestamp()
    if sunset_unix <= state.last_pointing:
        state.night_pointing = True
        print("The last pointing was after an hour after sunset")


def _parse_ant_list(state: State) -> None:
    """Build state.ants: active antennas minus excluded ones."""
    excluded: set = set()
    for item in state.ant_list.split(","):
        item = item.strip()
        if ".." in item:
            lo, hi = item.split("..")
            excluded.update(range(int(lo), int(hi) + 1))
        elif item.isdigit():
            excluded.add(int(item))

    if state.this_machine not in ("hal9000", "obscon1"):
        avail = [1, 3, 4, 5, 6, 7, 8]
    else:
        raw = subprocess.run(["getAntList"], capture_output=True, text=True).stdout.strip()
        avail = [int(x) for x in raw.split() if x.strip().isdigit()]

    state.ants = ",".join(str(a) for a in avail if a not in excluded)
    print(f"ants is {state.ants}")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def finish(state: State) -> None:
    run_command("radecoff -r 0 -d 0", state)
    time.sleep(1)
    print("Please remember to stow the antennas safely if you are leaving.")
    sys.exit(1)


def print_pid(state: State) -> None:
    if not state.simulate_mode:
        print(f"The process ID of this {state.myname} script is {state.mypid}")


def check_ant(state: State) -> None:
    """Check active antennas and store them in state.sma, then initialize."""
    print("Checking antenna status ... ")
    if state.simulate_mode:
        state.sma = list(range(1, 9))
    else:
        raw = subprocess.run(["getAntList"], capture_output=True, text=True).stdout.strip()
        state.sma = [int(x) for x in raw.split() if x.strip().isdigit()]

    initialize(state)
    state.nants = len(state.sma)

    if not re.match(r'^[1-8]+(?:,[1-8]{1,3}){0,2}$', state.pants):
        state.pants = (f"{state.sma[1]},{state.sma[2]}"
                       if len(state.sma) > 2 else "")

    print(f"nants = {state.nants}")
    print(f"pants = {state.pants}")

    if not state.simulate_mode:
        print(f"Antennas {state.sma} are going to be used.")
        script_copy(state)


def script_copy(state: State) -> None:
    """Write a timestamped copy of this script and its projectInfo to /data/current/aux."""
    this_file = Path(state.myname)
    timestamp  = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    dest_dir   = Path("/data/current/aux")
    dest_script = dest_dir / f"{this_file.name}_{timestamp}"

    proj_info_name = f"projectInfo_{this_file.stem}"
    proj_info_src  = Path(f"./{proj_info_name}")
    proj_info_dest = dest_dir / proj_info_name.rstrip("_projectInfo")

    print(f"Copy commands:\n"
          f"  cp {this_file.name} {dest_script}\n"
          f"  cp {proj_info_src} {proj_info_dest}\n")

    for src, dst in [(this_file.name, dest_script),
                     (str(proj_info_src), str(proj_info_dest))]:
        try:
            shutil.copy(src, dst)
        except Exception as e:
            print(f"  copy failed: {e}")


_lookup_cache: dict = {}   # source_name -> (az, el, sun_dist); cleared on unix_time advance


def check_elevation(source_name: str, state: State, silent: bool = False) -> float:
    """
    Return the current elevation of source_name in degrees.
    Calls the external 'lookup' utility.  In simulate mode the result is cached
    per simulated timestamp so repeated calls for the same source in the same
    'moment' only spawn one subprocess.
    """
    cache_key = (source_name, round(state.unix_time))
    if cache_key in _lookup_cache:
        az, el, sun_dist = _lookup_cache[cache_key]
        state.source_az, state.source_el, state.sun_distance = az, el, sun_dist
        if not silent:
            print(f"{source_name.split()[0]} is at {el:.4f} degrees elevation")
        return el

    if not state.simulate_mode or state.this_machine == "hal9000":
        result = subprocess.run(["lookup", "-s", source_name],
                                capture_output=True, text=True).stdout.strip()
    else:
        lookup_time = _format_lookup_time(state)
        parsed, display = _parse_source_args(source_name)
        print(f"lookup time: {lookup_time}")
        cmd = f"lookup -s {parsed} -t \"{lookup_time}\""
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True).stdout.strip()
        print(f"The lookup time is: {lookup_time}")
        source_name = display  # for display purposes

    parts = result.split()
    if not parts or parts[0] in ("Source", "error_flag"):
        print("#" * 42)
        print("######## WARNING WARNING WARNING #########")
        print(f"##### source {source_name} not found. ######")
        print("#" * 42)
        raise SystemExit(" quiting from the script")

    az, el, sun_dist = float(parts[0]), float(parts[1]), float(parts[2])
    state.source_az    = az
    state.source_el    = el
    state.sun_distance = sun_dist
    _lookup_cache[cache_key] = (az, el, sun_dist)

    if not silent:
        print(f"{source_name.split()[0]} is at {el:.4f} degrees elevation")

    if sun_dist < 25.0:
        print(f"The source {source_name} is too close to the sun at {sun_dist}. Skipping it.")
        el = 1.0

    return el


def run_command(cmd: str, state: State) -> None:
    """Print and optionally execute a command; in simulate mode advance simulated time."""
    print(cmd)
    actual = cmd
    if state.antenna and "tsys" in cmd:
        actual = f"tsys -a {state.antenna}"

    if not state.simulate_mode:
        subprocess.run(actual, shell=True)
        time.sleep(1)
    else:
        _simulate_time(cmd, state)


def tsys(state: State) -> None:
    if state.ants:
        run_command(f"tsys -x {state.ants}", state)
    else:
        run_command("tsys", state)


def get_lst(state: State, verbose: bool = True) -> float:
    """Return Local Sidereal Time in hours."""
    if state.simulate_mode:
        lst = simulate_lst(state)
    else:
        raw = subprocess.run(
            ["value", "-a", str(state.sma[0] if state.sma else 1), "-v", "lst_hours"],
            capture_output=True, text=True,
        ).stdout.strip()
        lst = float(raw)

    if verbose:
        print(f"LST [hr]= {lst:6.2f}")
    return lst


def simulate_lst(state: State) -> float:
    """Compute LST for Mauna Kea from either real UTC or simulated unix time."""
    LONGITUDE = -10.365168199815  # hours west, Mauna Kea (pad 1)

    if state.given_utc:
        if state.first_time:
            _parse_given_utc(state)
            state.first_time = False
        dt = datetime.utcfromtimestamp(state.unix_time)
    else:
        dt = datetime.utcnow()

    mn   = dt.month
    d    = dt.day
    year = dt.year
    ut   = dt.hour + dt.minute / 60.0 + dt.second / 3600.0

    # Julian Date (Explanatory Supplement eq. 12.92-1)
    term1 = (1461 * (year + 4800 + (mn - 14) // 12)) // 4
    term2 = (367 * (mn - 2 - 12 * ((mn - 14) // 12))) // 12
    term3 = (3 * ((year + 4900 + (mn - 14) // 12) // 100)) // 4
    JD    = term1 + term2 - term3 + d - 32075

    dnum = JD - 2451545.0
    T    = dnum / 36525.0
    rad  = math.pi / 180.0

    angle1 = (125.0 - 0.05295 * dnum) * rad
    angle2 = (200.9 + 1.97129 * dnum) * rad

    epsilon0 = (21.448 - 46.8150 * T - 0.00059 * T**2 + 0.001813 * T**3) / 3600.0 + 26.0 / 60.0 + 23.0
    epsilon   = (epsilon0 + 0.0026 * math.cos(angle1) + 0.0002 * math.cos(angle2)) * rad

    Tdu  = dnum / 36525.0
    theta = ut * (1.002737909350795 + 5.9006e-11 * Tdu - 5.9e-15 * Tdu**2) * 3600.0
    gmst0 = (24110.54841 + 8640184.812866 * Tdu
             + 0.093104 * Tdu**2 - 6.2e-6 * Tdu**3) / 3600.0
    gmst0 %= 24
    if gmst0 < 0:
        gmst0 += 24

    delta_psi   = -0.0048 * math.sin(angle1) - 0.0004 * math.sin(angle2)
    eqn_equinox = delta_psi * math.cos(epsilon) * 6.66666667e-2

    lst = (gmst0 + theta / 3600.0 + eqn_equinox + LONGITUDE) % 24
    if lst < 0:
        lst += 24
    return lst


def write_file(loop_counter: int, i, source, nloop: int) -> None:
    """Persist restart state to restartfile.txt."""
    with open("restartfile.txt", "w") as f:
        f.write(f"{loop_counter} {i} {source} {nloop}\n")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _simulate_time(cmd: str, state: State) -> None:
    state.prev_unix_time = state.unix_time
    parts = cmd.split()

    if "integrate" in cmd:
        # parse  integrate -t <secs>  or  integrate -s <scans>  ...
        for idx, part in enumerate(parts):
            if part in ("-t",) and idx + 1 < len(parts):
                state.total_integration_time = float(parts[idx + 1])
            if part in ("-s",) and idx + 1 < len(parts):
                state.unix_time += state.total_integration_time * float(parts[idx + 1])
    elif "tsys" in cmd:
        state.unix_time += state.tsys_delay
    elif "observe" in cmd:
        state.unix_time += state.observe_delay
    elif "point" in cmd:
        repeats = 1
        for idx, part in enumerate(parts):
            if part == "-r" and idx + 1 < len(parts):
                try:
                    repeats = int(parts[idx + 1])
                except ValueError:
                    pass
        state.unix_time += state.point_delay * repeats

    prev_dt = datetime.fromtimestamp(state.prev_unix_time)
    curr_dt = datetime.fromtimestamp(state.unix_time)
    print(f"\t{prev_dt:%m/%d/%Y %H:%M:%S} --> {curr_dt:%m/%d/%Y %H:%M:%S}  ---- {cmd}")


def _format_lookup_time(state: State) -> str:
    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
              "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    dt = datetime.fromtimestamp(state.unix_time) if state.given_utc else datetime.now()
    return f"{dt.day} {months[dt.month - 1]} {dt.year} {dt.hour}:{dt.minute:02d}"


def _parse_source_args(source_name: str):
    """
    If source_name contains -r / -d RA/Dec args, convert sexagesimal to decimal.
    Returns (parsed_string_for_lookup, display_name).
    """
    if "-r" not in source_name:
        return source_name, source_name

    parts = source_name.split()
    name = epoch = ""
    ra_str = dec_str = ""

    for i, p in enumerate(parts):
        if p == "-r" and i + 1 < len(parts):
            ra_str = parts[i + 1]
        elif p == "-d" and i + 1 < len(parts):
            dec_str = parts[i + 1]
        elif p == "-e" and i + 1 < len(parts):
            epoch = parts[i + 1]
        elif p == "-s" and i + 1 < len(parts):
            name = parts[i + 1]
        elif i == 0:
            name = p

    if not ra_str or not dec_str:
        return source_name, source_name

    rah, ram, ras = (float(x) for x in ra_str.split(":"))
    given_ra = rah + ram / 60 + ras / 3600

    decd_str, decm_str, decs_str = dec_str.split(":")
    decd = float(decd_str)
    sign = -1 if decd < 0 else 1
    decd = abs(decd)
    given_dec = sign * (decd + float(decm_str) / 60 + float(decs_str) / 3600)

    parsed = f"{name} -r {given_ra:.6f} -d {given_dec:.6f} -e {epoch}"
    return parsed, name


def _figure_restart(state: State) -> None:
    """
    Read the current script to figure out which loops have been completed,
    then read restartfile.txt to determine the exact restart point.
    """
    print("starting the figuring")
    loop: List[str] = []
    long_line = ""
    in_restart = False

    with open(sys.argv[0]) as f:
        for line in f:
            if line.lstrip().startswith("#"):
                continue
            if "restart" in line:
                in_restart = True
            if in_restart and "}" in line:
                in_restart = False

            stripped = line.rstrip()
            if stripped.endswith(";") or stripped.endswith(":"):
                full = (long_line + stripped).strip()
                long_line = ""
                if any(kw in full for kw in ("obs_loop(", "do_flux(", "do_pass(")):
                    loop.append(full)
            elif "}" not in line and "restart" not in line:
                long_line += stripped

    try:
        with open("restartfile.txt") as rf:
            for line in rf:
                if line.strip():
                    state.stuff = line.split()
    except FileNotFoundError:
        state.stuff = ["0", "0", "0", "0"]

    idx = int(state.stuff[0]) if state.stuff else 0
    state.the_word = []
    for k in range(len(loop)):
        if idx > k:
            state.the_word.append(1)
        elif idx == k:
            state.the_word.append(2)
        else:
            state.the_word.append(0)

    if len(state.stuff) > 3 and state.stuff[3] != "0":
        state.loops_done = int(state.stuff[3])
        print(f"There were a total of {state.loops_done} loops finished.")

    # Determine partial obsloop position
    if idx < len(loop) and "obs_loop(" in loop[idx]:
        stuff_src = int(state.stuff[1]) if len(state.stuff) > 1 else 0
        # parse source list from the loop call
        m = re.search(r'obs_loop\(\s*\[(.*?)\]', loop[idx])
        if m:
            sources_in_loop = [s.strip().strip("'\"") for s in m.group(1).split(",")]
            state.partial_obs_loop = (0 if stuff_src >= len(sources_in_loop)
                                      else stuff_src + 1)
    else:
        state.partial_scans = int(state.stuff[1]) if len(state.stuff) > 1 else 0

    print(f"the word is {state.the_word}")
    print(f"the partial loop is {state.partial_obs_loop}")
    print(f"the remaining scans are {state.partial_scans}")
