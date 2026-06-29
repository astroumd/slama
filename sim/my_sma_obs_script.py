#!/usr/bin/env python3
"""
SMA Observation Script
Experiment : 2024B-S045
Title      : SMA Interferometry School - 2025 Group I
             (Ishibashi / Zagorulia / Shinozaki / Hung)
PI         : Ramprasad Rao
Contact    : rrao@cfa.harvard.edu  |  (808) 933-2973

SPECIAL INSTRUCTIONS
--------------------
As the transit observation, observe either Mars or Jupiter.
Please choose between Mars and Jupiter; the schedule is uncertain.

PRIMING
-------
observe -s L1551_MC -r 04:31:11.0 -d 18:12:52.5 -e 2000 -v 0
dopplerTrack -S L1551_MC -r 230.538 -u -s1 -f 0.462 -R B -r 230.538 -u -s1 -f 0.462

POINTING
--------
None requested.
Example syntax: point -i 60 -r 3 -L -l -t -Q

Converted from my_sma_obs_script.pl
"""

import os

from sma import State, check_ant, parse_args, run_command
from sma_add import do_flux, do_pass, obs_loop

# ---------------------------------------------------------------------------
# Source, calibrator and elevation limits
# ---------------------------------------------------------------------------

INTTIME = "15"

# All source names and scan counts in one dict.
# Targets start with 'targ', gain cals with 'cal', flux cals with 'flux',
# bandpass cals with 'bpass'.  Scan counts are prefixed with 'n'.
SOURCES: dict = {
    "targ0":   "L1551_MC -r 04:31:11.0 -d 18:12:52.5 -e 2000 -v 0",
    "ntarg0":  60,
    "cal0":    "0530+135",
    "ncal0":   6,
    "cal1":    "3c120",
    "ncal1":   6,
    "transcal":   "3c84",
    "ntranscal":  10,
    "flux0":   "Uranus",
    "nflux0":  20,
    "flux1":   "Callisto",
    "nflux1":  20,
    "flux2":   "Neptune",
    "nflux2":  20,
    "bpass0":  "3c84",
    "nbpass0": 120,
}

# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------

state = State(
    inttime      = INTTIME,
    MINEL_TARG   = 17,  MAXEL_TARG   = 83,
    MINEL_GAIN   = 17,  MAXEL_GAIN   = 83,
    MINEL_FLUX   = 17,  MAXEL_FLUX   = 81,
    MINEL_BPASS  = 17,  MAXEL_BPASS  = 87,
    MINEL_CHECK  = 19,
    transcal     = SOURCES["transcal"],
    ntranscal    = str(SOURCES["ntranscal"]),
)

parse_args(state)
check_ant(state)

run_command("radio", state)
run_command(f"integrate -t {INTTIME}", state)
run_command("project -r -p 'Ramprasad Rao' -d '2024B-S045'", state)
print("----- initialization done, starting script -----")

# ---------------------------------------------------------------------------
# Science script
# ---------------------------------------------------------------------------

print("----- initial flux and bandpass calibration -----")
if not state.restart:
    # do_pass("bpass0", "nbpass0", SOURCES, state)
    do_flux("flux2", "nflux2", SOURCES, state)
    do_flux("flux0", "nflux0", SOURCES, state)
    # do_flux("flux1", "nflux1", SOURCES, state)

print("----- main science target observe loop -----")
obs_loop(["cal0", "cal1", "targ0"], SOURCES, state)

print("----- final flux and bandpass calibration -----")
# do_flux("flux0", "nflux0", SOURCES, state)
# do_flux("flux1", "nflux1", SOURCES, state)
# do_pass("bpass0", "nbpass0", SOURCES, state)

print("----- Congratulations!  This is the end of the script.  -----")
