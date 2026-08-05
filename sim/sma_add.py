#!/usr/bin/env python3
"""
SMA Observation Control - Observing Loop Subroutines
Idiomatic Python conversion of sma_add.pl

The Perl code passed variable *names* to loops (e.g. ObsLoop(targ0, cal0))
and used symbolic dereferences (${$name}) to get values.  Here we pass a
plain dict mapping name -> value, which is idiomatic Python and easier to read.

Example:
    sources = {
        'targ0':  'L1551_MC -r 04:31:11.0 -d 18:12:52.5 -e 2000 -v 0',
        'ntarg0': 60,
        'cal0':   '0530+135',
        'ncal0':  6,
    }
    obs_loop(['cal0', 'targ0'], sources, state)
"""

import re
import subprocess
import time as time_mod
from datetime import datetime
from typing import List, Optional

from sma import (
    State,
    check_elevation,
    get_lst,
    print_pid,
    run_command,
    script_copy,
    tsys,
    write_file,
)

_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


# ---------------------------------------------------------------------------
# Main observing loop
# ---------------------------------------------------------------------------

def obs_loop(loop_items: List[str], sources: dict, state: State) -> None:
    """
    Main observing loop.

    loop_items : ordered list of source-variable names, e.g. ['cal0', 'targ0', 'cal1'].
                 Names starting with 't' are targets, 'c' gain cals, 'm' mosaic targets.
    sources    : dict mapping variable name -> value (str or int/float).
    """
    print("\n#############\n# Main Loop #\n#############\n")

    garrus_idx = state.garrus
    exit_code  = 0
    partial_loop_check = False

    if len(state.the_word) > garrus_idx:
        if state.the_word[garrus_idx] == 1:
            print("This loop has been finished.")
            exit_code = -1
        elif state.the_word[garrus_idx] == 2:
            partial_loop_check = True
            print("This loop was partially finished.")
    state.garrus += 1

    obs_list = list(loop_items)   # mutable working copy
    nloop      = 0
    init       = False
    obs_targ   = 0
    first_loop = False
    messed     = False            # True when a leading cal was prepended

    # Collect unique calibrator names for future-cal checking
    cals = list(dict.fromkeys(
        sources[obj] for obj in obs_list
        if obj.startswith("c") and obj in sources
    ))

    # Honour maxloops restart offset
    if state.max_loops != 200 and state.opt_figure:
        stuff_src = int(state.stuff[1]) if len(state.stuff) > 1 else 0
        nloop = (state.loops_done
                 if stuff_src == len(obs_list) - 1
                 else state.loops_done - 1)
        print(f"Starting with loop {state.loops_done}.")

    if exit_code == -1:
        print("Skipping this loop.\n")

    # ------------------------------------------------------------------ main while
    while exit_code == 0:
        print_pid(state)
        nloop += 1
        print(f"Loop No.= {nloop}")

        if nloop == 2 and "hal" in state.this_machine:
            script_copy(state)

        i = 0
        obs_len = len(obs_list)

        while i < obs_len:

            # Partial-restart: jump to last known position
            if partial_loop_check:
                i = state.partial_obs_loop
                print(f"Starting with source number {i + 1} in the loop.")
                partial_loop_check = False
                first_loop = True

            if _check_lst(state):
                exit_code = -1 if nloop <= 1 else 1
                print(f"Outside of LST range {state.LST_start} - {state.LST_end}")
                break

            if nloop > state.max_loops:
                exit_code = 1
                print("---- Maximum number of loops achieved.  Exiting.. ----")
                break

            if not init:
                print("\n###########################\n"
                      "# Initial Elevation Check #\n"
                      "###########################\n")
                if _check_target_el(obs_list, sources, state):
                    print("All target sources too low. Skipping this loop.")
                    exit_code = -1
                    break
                if _check_gain_el(obs_list, sources, state):
                    print("None of the calibrators are up. Skipping this loop.")
                    exit_code = -1
                    break
                init = True

            # Remove the prepended leading-cal after the first loop
            if messed and nloop > 1:
                obs_list.pop(0)
                messed  = False
                obs_len -= 1
                print("Removing the extra calibrator.")

            item = obs_list[i]

            # Ensure loop starts with a calibrator on the first pass
            if (nloop == 1 and not item.startswith("c")
                    and not state.opt_figure and not messed and i == 0):
                print("The loop doesn't start with a calibrator, adding one.")
                lead = _first_cal_var(obs_list)
                obs_list.insert(0, lead)
                messed  = True
                obs_len += 1
                continue   # re-evaluate i=0 which is now a cal

            # -------------------------------------------------------------- target
            if item.startswith("t") and exit_code != 1:
                exit_code, obs_targ = _observe_target(
                    item, obs_list, sources, state, cals, nloop, obs_len, i, obs_targ)
                if exit_code == 1:
                    break

            # --------------------------------------------------------- gain cal
            elif item.startswith("c") and exit_code != 1:
                exit_code = _observe_gain_cal(
                    item, obs_list, sources, state, nloop, first_loop, i)
                if exit_code == 1:
                    break

            i += 1

        # -------------------------------------------------------- final gain cal
        if exit_code != -1 or obs_targ >= 1:
            _final_gain_cal(obs_list, sources, state, nloop, i)

    state.loop_counter += 1
    print("##########################\n"
          "# End of Observing Loop  #\n"
          "##########################")


# ---------------------------------------------------------------------------
# Flux calibration
# ---------------------------------------------------------------------------

def do_flux(flux_var: str, nflux_var: str, sources: dict, state: State) -> None:
    """Observe a flux calibrator until nflux_var scans are complete."""
    print("\n#######################\n# FLUX Calibration    #\n#######################\n")

    flux_name = sources[flux_var]
    n_flux    = int(sources[nflux_var])
    total_scans = _restart_scan_count(state, flux_name, n_flux)

    if total_scans < n_flux:
        print(f"Checking elevation of Flux Cal {flux_name}...")
        get_lst(state)
        flux_el = check_elevation(flux_name, state)

        if flux_el < state.MINEL_FLUX:
            print("too low, skipping.")
        elif flux_el > state.MAXEL_FLUX:
            print("too high, skipping.")
        else:
            print(f"\n---- Observing {flux_var}. ----\n")
            run_command("radecoff -r 0 -d 0", state)
            state.current_source = flux_var
            if not n_flux:
                print(f"The current source ({flux_name}) does not have any scans scheduled.")

            while total_scans < n_flux:
                get_lst(state)
                flux_el = check_elevation(flux_name, state)
                if not (state.MINEL_FLUX <= flux_el <= state.MAXEL_FLUX):
                    print("Source elevation limit reached.\nExiting ...")
                    run_command("stow", state)
                    raise SystemExit(0)
                run_command(f"observe -s {flux_name} -t flux", state)
                if total_scans == 0:
                    tsys(state)
                total_scans += 10
                if not state.special_flux:
                    write_file(state.loop_counter, total_scans, 0, 0)
                run_command(f"integrate -s 10 -t {state.inttime} -w", state)
                print(f"Finished {total_scans}/{n_flux} on {flux_name}.")

    if not state.special_flux:
        state.loop_counter += 1


# ---------------------------------------------------------------------------
# Bandpass calibration
# ---------------------------------------------------------------------------

def do_pass(bpass_var: str, nbpass_var: str, sources: dict, state: State) -> None:
    """Observe a bandpass calibrator until nbpass_var scans are complete."""
    print("\n###########################\n# BANDPASS Calibration    #\n###########################\n")

    bpass_name = sources[bpass_var]
    n_bpass    = int(sources[nbpass_var])
    total_scans = _restart_scan_count(state, bpass_name, n_bpass)

    if total_scans < n_bpass:
        print(f"Checking elevation of Bandpass Cal {bpass_name}...")
        get_lst(state)
        bp_el = check_elevation(bpass_name, state)

        if bp_el < state.MINEL_BPASS:
            print("too low, skipping.")
        elif bp_el > state.MAXEL_BPASS:
            print("too high, skipping.")
        else:
            print(f"\n----  Observing {bpass_var}. ----\n")
            run_command("radecoff -r 0 -d 0", state)
            state.current_source = bpass_var
            if not n_bpass:
                print(f"The current source ({bpass_name}) does not have any scans scheduled.")

            while total_scans < n_bpass:
                get_lst(state)
                bp_el = check_elevation(bpass_name, state)
                if not (state.MINEL_BPASS <= bp_el <= state.MAXEL_BPASS):
                    print("Source elevation limit reached.\nExiting ...")
                    run_command("stow", state)
                    raise SystemExit(0)
                run_command(f"observe -s {bpass_name} -t bandpass", state)
                if total_scans == 0:
                    tsys(state)
                total_scans += 10
                write_file(state.loop_counter, total_scans, 0, 0)
                run_command(f"integrate -s 10 -t {state.inttime} -w", state)
                print(f"Finished {total_scans}/{n_bpass} on {bpass_name}.")

                if not state.opt_pointing:
                    if total_scans == 10:
                        state.last_pointing = 0
                    pointing_check(state)

    state.loop_counter += 1


# ---------------------------------------------------------------------------
# Transit calibrator
# ---------------------------------------------------------------------------

def observe_transcal(state: State) -> None:
    print("---- Searching for an available transit calibrator... ----")
    trans_el = check_elevation(state.transcal, state)
    if state.MINEL_GAIN < trans_el < 87.0:
        state.current_source = state.transcal
        print("---- Observing transit calibrator ----")
        run_command(f"observe -s {state.transcal} -R 0 -D 0", state)
        tsys(state)
        run_command(f"integrate -s 10 -t {state.inttime} -w", state)
        state.last_source = state.transcal
    else:
        print("---- Transcal not available.  Exiting.. ----")
        run_command("stow", state)
        raise SystemExit(0)


# ---------------------------------------------------------------------------
# Pointing
# ---------------------------------------------------------------------------

def pointing_check(state: State, cal: str = "") -> None:
    """Perform a pointing if the interval since the last one has elapsed."""
    if state.debug:
        print(f"PJT pointing_check {cal}")
    now = state.unix_time if state.simulate_mode else time_mod.time()
    interval = (state.night_pointing_time if state.night_pointing
                else state.day_pointing_time)

    if (now - state.last_pointing) < interval:
        return

    source = cal or state.pointing_cal
    if not source:
        state.stuff_pointing = ""
        return                       # <-- always hits this, since nothing ever sets pointing_cal or passes cal

    print("Performing automatic pointing...")
    ipoint_opts = state.ipoint or "-i 10 -r 3 -8 -c 2.5 -w -n -Q"
    if state.opt_b:
        ipoint_opts += " -B"
    if state.opt_k:
        ipoint_opts += " -k"
    run_command(f"point -s {source} {ipoint_opts}", state)
    state.last_pointing = now
    # Signal to caller that a pointing was done (Perl used $stuff)
    state._pointing_done_source = source


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _check_lst(state: State) -> bool:
    """Return True if current LST is outside [LST_start, LST_end]."""
    lst   = get_lst(state, verbose=False)
    start = state.LST_start
    end   = state.LST_end
    if start > end:
        return lst < start and lst > end
    return lst < start or lst > end


def _outside_lst_range(lst: float, state: State) -> bool:
    start, end = state.LST_start, state.LST_end
    if start < end:
        return lst < start or lst > end
    return lst < start and lst > end


def _check_target_el(obs_list, sources, state) -> bool:
    """Return True if ALL targets are below their minimum elevation."""
    print("Checking the elevation of the targets!")
    for item in obs_list:
        if not item.startswith(("t", "b", "f")):
            continue
        if item not in sources:
            continue
        el = check_elevation(sources[item], state)
        limit = {
            "t": state.MINEL_CHECK if 180 < state.source_az < 360 else state.MINEL_TARG,
            "b": state.MINEL_BPASS,
            "f": state.MINEL_FLUX,
        }[item[0]]
        if el > limit:
            return False   # at least one target is up
    return True


def _check_gain_el(obs_list, sources, state) -> bool:
    """Return True if ALL gain cals are below their minimum elevation."""
    for item in obs_list:
        if not item.startswith("c"):
            continue
        var = _select_source_var(item, sources, state)
        if var in sources and check_elevation(sources[var], state) > state.MINEL_GAIN:
            return False
    return True


def _cal_too_high_or_low(obs_list, sources, state, nloop, first_loop) -> bool:
    """Search for any available gain cal; observe it if found. Return True if one was found."""
    print("---- Source elevation limit. ----\n"
          "---- Searching for an available calibrator.. ----")
    for item in obs_list:
        if not item.startswith("c"):
            continue
        var    = _select_source_var(item, sources, state)
        targel = check_elevation(sources[var], state)
        if sources[var] == state.last_source:
            print("The current calibrator was just observed, skipping to the next source.")
            return True
        if state.MINEL_GAIN < targel < state.MAXEL_GAIN:
            name_key = f"n{var}"
            write_file(state.loop_counter, 0, 0, nloop)
            run_command(f"observe -s {sources[var]} -t gain -R 0 -D 0", state)
            tsys(state)
            run_command(f"integrate -s {sources[name_key]} -t {state.inttime} -w", state)
            state.last_source = sources[var]
            if not state.opt_pointing:
                if nloop == 1 and not first_loop:
                    state.last_pointing = 0
                pointing_check(state)
            return True
    return False


def _source_too_high_or_low(obs_list, sources, state) -> bool:
    """Return True if at least one target is within a valid elevation range."""
    print("---- Source elevation limit. ----\n"
          "---- Searching for an available target... ----")
    for item in obs_list:
        if item.startswith("t") and item in sources:
            el = check_elevation(sources[item], state)
            if state.MINEL_GAIN < el < state.MAXEL_GAIN:
                return True
    return False


def _select_source_var(item: str, sources: dict, state: State) -> str:
    """Handle 'cal0|cal1' alternative-calibrator syntax; return the best available var name."""
    if "|" not in item:
        return item
    options = item.split("|")
    print("---- Multiple calibrators possible ----")
    names = " | ".join(sources.get(o, o) for o in options)
    print(f"---- Selecting between {names}")
    for opt in options:
        if opt in sources:
            el = check_elevation(sources[opt], state)
            if state.MINEL_GAIN < el < state.MAXEL_GAIN:
                return opt
    return options[0]


def _first_cal_var(obs_list: List[str]) -> str:
    for item in obs_list:
        if item.startswith("c"):
            return item
    return obs_list[0]


def _calc_total_time(i: int, obs_list, sources, state) -> tuple:
    """
    Sum up integration time for all non-cal items from position i onward.
    Return (total_seconds, name_of_next_cal_source).
    """
    total = 0.0
    j = i
    while j < len(obs_list) and not obs_list[j].startswith("c"):
        n_key = f"n{obs_list[j]}"
        n_val = sources.get(n_key) or 0
        total += float(n_val) + 1
        j += 1

    total *= float(state.inttime)

    if j < len(obs_list) and obs_list[j].startswith("c"):
        next_cal_name = sources.get(obs_list[j], sources.get(obs_list[0], ""))
    else:
        next_cal_name = sources.get(obs_list[0], "")

    return total, next_cal_name


def _cal_lookup(cal_name: str, extra_seconds: float, state: State) -> bool:
    """Return True if cal_name will be above MINEL_GAIN after extra_seconds."""
    if state.simulate_mode:
        future = state.unix_time + extra_seconds
    else:
        future = time_mod.time() + extra_seconds

    dt = datetime.fromtimestamp(future)
    t_str = f"-t \"{dt.day} {_MONTHS[dt.month - 1]} {dt.year} {dt.hour}:{dt.minute:02d}:{dt.second:02d}\""
    cmd = f"lookup -s {cal_name} {t_str}"
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True).stdout.strip()
    parts = result.split()
    if not parts or parts[0] in ("error_flag", "Source"):
        return False
    try:
        return float(parts[1]) > state.MINEL_GAIN
    except (ValueError, IndexError):
        return False


def _find_other_cal(cals: List[str], skip_cal: str, extra_seconds: float, state: State) -> bool:
    """Try each cal in cals (except skip_cal) to see if one will be up."""
    for cal in cals:
        if cal != skip_cal and _cal_lookup(cal, extra_seconds, state):
            return True
    return False


def _restart_scan_count(state: State, source_name: str, n_total: int) -> int:
    """Return how many scans have already been done (for figure/restart mode)."""
    garrus = state.garrus
    total_scans = 0
    if len(state.the_word) > garrus:
        if state.the_word[garrus] == 1:
            print(f"Skipping the loop for {source_name}")
            total_scans = n_total
        elif state.the_word[garrus] == 2:
            total_scans = state.partial_scans
            print(f"{state.partial_scans} scans have already been taken on {source_name}")
    state.garrus += 1
    return total_scans


# ---------------------------------------------------------------------------
# Observe helpers used by obs_loop
# ---------------------------------------------------------------------------

def _observe_target(item, obs_list, sources, state, cals, nloop, obs_len, i, obs_targ):
    """Handle a target-type entry in the obs loop. Returns (exit_code, obs_targ)."""
    int_time_key = f"n{item}"
    print(f"\n---- Observing Target Source (Loop = {nloop}) ----\n")

    targel = check_elevation(sources[item], state)
    targelcheck = (state.MINEL_CHECK if 180 < state.source_az < 360
                   else state.MINEL_TARG)
    state.current_el = targel

    if targel < targelcheck:
        if _check_target_el(obs_list, sources, state):
            print("All target sources too low.")
            return 1, obs_targ

    elif targel > state.MAXEL_TARG:
        while not _source_too_high_or_low(obs_list, sources, state):
            print("---- None of the Targets are available.  Trying transcal. ----")
            lst_now = get_lst(state)
            if _outside_lst_range(lst_now, state):
                break
            observe_transcal(state)

    else:
        total_time, next_cal = _calc_total_time(i, obs_list, sources, state)
        ok = _cal_lookup(next_cal, total_time, state)
        if not ok:
            ok = _find_other_cal(cals, next_cal, total_time, state)

        if ok:
            if not sources.get(int_time_key):
                print(f"The current source ({sources[item]}) does not have any scans scheduled.")
            obs_targ = 1
            state.current_source = sources[item]
            if not state.simulate_mode:
                print(f"{sources[item].split()[0]} is at {targel:.4f} degrees elevation")
            run_command(f"observe -s {sources[item]} -R 0 -D 0", state)
            if not state.opt_mosaic:
                tsys(state)
            write_file(state.loop_counter, i, 0, nloop)
            run_command(f"integrate -s {sources[int_time_key]} -t {state.inttime} -w", state)
            state.last_source = sources[item]
        else:
            print("THE CALIBRATOR WILL BE TOO LOW AFTER THIS SOURCE LOOP, "
                  "SKIPPING TO THE FINAL GAIN CAL.")
            return 1, obs_targ

    return 0, obs_targ


def _observe_gain_cal(item, obs_list, sources, state, nloop, first_loop, i):
    """Handle a calibrator-type entry in the obs loop. Returns exit_code."""
    print(f"\n---- Observing Gain Calibrator (Loop = {nloop}) ----")
    var    = _select_source_var(item, sources, state)
    targel = check_elevation(sources[var], state)
    int_time_key = f"n{var}"

    if targel < state.MINEL_GAIN:
        if not _cal_too_high_or_low(obs_list, sources, state, nloop, first_loop):
            print(f"None of the calibrators are above {state.MINEL_GAIN} degrees")
            return 1

    elif targel > state.MAXEL_GAIN:
        if not _cal_too_high_or_low(obs_list, sources, state, nloop, first_loop):
            print("None of the calibrators are available. Trying transcal.")
            while check_elevation(sources.get("cal0", ""), state) > state.MAXEL_GAIN:
                get_lst(state)
                observe_transcal(state)

    elif sources[var] == state.last_source:
        print("The current calibrator was just observed, skipping to the next source.")

    else:
        if not sources.get(int_time_key):
            print(f"The current source ({sources[var]}) does not have any scans scheduled.")
        if not state.simulate_mode:
            print(f"{sources[var]} is at {targel:.4f} degrees elevation")
        run_command(f"observe -s {sources[var]} -t gain -R 0 -D 0", state)
        tsys(state)
        write_file(state.loop_counter, i, 0, nloop)
        run_command(f"integrate -s {sources[int_time_key]} -t {state.inttime} -w", state)
        state.last_source = sources[var]

        if not state.opt_pointing:
            if nloop == 1 and not first_loop:
                first_loop = True
                state.last_pointing = 0
            state._pre_pointing_source = sources[var]
            state._pre_pointing_time   = sources.get(int_time_key, "")
            pointing_check(state)
            # Re-observe if a pointing was just performed
            if getattr(state, "_pointing_done_source", ""):
                run_command(f"observe -s {sources[var]} -t gain -R 0 -D 0", state)
                tsys(state)
                run_command(f"integrate -s {sources[int_time_key]} -t {state.inttime} -w", state)
                state._pointing_done_source = ""

    return 0


def _final_gain_cal(obs_list, sources, state, nloop, i):
    print("\n##########################\n# Final Gain Calibration #\n##########################\n")
    for item in obs_list:
        if not item.startswith("c"):
            continue
        targel = check_elevation(sources[item], state)
        if sources[item] == state.last_source:
            print("The current calibrator was just observed, skipping to the next source.")
        elif state.MINEL_GAIN < targel < state.MAXEL_GAIN:
            state.current_source = sources[item]
            name_key = f"n{item}"
            run_command(f"observe -s {sources[item]} -R 0 -D 0", state)
            tsys(state)
            write_file(state.loop_counter, i, item, nloop)
            run_command(f"integrate -s {sources[name_key]} -t {state.inttime} -w", state)
            break
