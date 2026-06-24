#!/usr/bin/env python3
"""
SMA Observation Script
Experiment : 2016A-A012
Title      : Search for Bright submm afterglows Associated with Gamma-Ray Bursts
PI         : Yuji Urata
Contact    : urata@asiaa.sinica.edu.tw  |  +886-3-4227151 ex 65951

SPECIAL INSTRUCTIONS
--------------------
None.

PRIMING
-------
observe -s GRB -r 21:01:11.22 -d +42:13:13.7 -e 2000 -v 0
dopplerTrack -S GRB -r 230 -u -s25
restartCorrelator -R l -s128
setFeedOffset -f 230

POINTING
--------
At start of track.
Example syntax: point -i 60 -r 3 -L -l -t -Q

Converted from GRB.pl
"""

from sma import State, check_ant, parse_args, run_command
from sma_add import do_flux, do_pass, obs_loop

# ---------------------------------------------------------------------------
# Source, calibrator and elevation limits
# ---------------------------------------------------------------------------

INTTIME = "30"

SOURCES: dict = {
    "targ0":   "GRB -r 21:01:11.22 -d +42:13:13.7 -e 2000 -v 0",
    "ntarg0":  24,
    "cal0":    "mwc349a",
    "ncal0":   4,
    "cal1":    "2015+371",
    "ncal1":   4,
    "flux0":   "titan",
    "nflux0":  20,
    "bpass0":  "3c279",
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
)

parse_args(state)
check_ant(state)

run_command("radio", state)
run_command(f"integrate -t {INTTIME}", state)
run_command("project -r -p 'Yuji Urata' -d '2016A-A012'", state)
print("----- initialization done, starting script -----")

# ---------------------------------------------------------------------------
# Science script
# ---------------------------------------------------------------------------

print("----- initial flux and bandpass calibration -----")
if not state.restart:
    # do_pass("bpass0", "nbpass0", SOURCES, state)
    do_flux("flux0", "nflux0", SOURCES, state)

print("----- main science target observe loop -----")
obs_loop(["cal0", "cal1", "targ0", "cal0", "targ0", "cal0", "targ0"], SOURCES, state)

print("----- final flux and bandpass calibration -----")
do_flux("flux0", "nflux0", SOURCES, state)
do_pass("bpass0", "nbpass0", SOURCES, state)

print("----- Congratulations!  This is the end of the script.  -----")
