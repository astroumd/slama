#!/usr/bin/env python3
"""
Generate an SMA observing script (.pl) from the GRB.pl template.

Fills in target coordinates and calibration parameters, so a new script
for a new target/event can be produced without hand-editing the Perl.

Example:
    ./make_obs_script.py --name GRB210905 --ra 21:01:11.22 --dec +42:13:13.7 \\
        --exp-code 2016A-A012 --pi "Yuji Urata" --email urata@asiaa.sinica.edu.tw \\
        --output GRB210905.pl
"""

import argparse
import os
import stat

TEMPLATE = """#!/usr/bin/perl -w
{ BEGIN {$^W =0}
#
################## Script Header Info #####################
#
# Experiment Code: __EXP_CODE__
# Experiment Title: __EXP_TITLE__
# PI: __PI__
# Contact Person: __CONTACT__
# Email  : __EMAIL__
# Office : __OFFICE__
# Home   : __HOME__
# Array  : __ARRAY__
#
#
############## SPECIAL INSTRUCTIONS ################
#
# none
#
################## Priming ################################
#
# observe -s __NAME__ -r __RA__ -d __DEC__ -e __EPOCH__ -v __VELOCITY__
# dopplerTrack -S __NAME__ -r __DOPP_FREQ__ -u -s25
# restartCorrelator -R l -s128
# setFeedOffset -f __FEED_FREQ__
#
################## Pointing ###############################
#
# Pointing: At start of track
# Syntax Example: point -i 60 -r 3 -L -l -t -Q
#
################## Source, Calibrator and Limits ##########
#
$inttime="__INTTIME__";
$targ0="__NAME__ -r __RA__ -d __DEC__ -e __EPOCH__ -v __VELOCITY__"; $ntarg0="__NTARG0__";
$cal0="__CAL0__"; $ncal0="__NCAL0__";
$cal1="__CAL1__"; $ncal1="__NCAL1__";
$flux0="__FLUX0__"; $nflux0="__NFLUX0__";
$bpass0="__BPASS0__"; $nbpass0="__NBPASS0__";
$MINEL_TARG = __MINEL_TARG__; $MAXEL_TARG = __MAXEL_TARG__;
$MINEL_GAIN = __MINEL_GAIN__; $MAXEL_GAIN = __MAXEL_GAIN__;
$MINEL_FLUX = __MINEL_FLUX__; $MAXEL_FLUX = __MAXEL_FLUX__;
$MINEL_BPASS= __MINEL_BPASS__; $MAXEL_BPASS= __MAXEL_BPASS__;
$MINEL_CHECK= __MINEL_CHECK__;
#
################## Script Initialization ##################
#
do 'sma.pl';
do 'sma_add.pl';
checkANT();
command("radio");
command("integrate -t $inttime");
$myPID=$$;
command("project -r -p '__PI__' -d '__EXP_CODE__'");
print "----- initialization done, starting script -----\\n";
#
################## Science Script #########################
#
print "----- initial flux and bandpass calibration -----\\n";
if(!$restart){
#  &DoPass(bpass0,nbpass0);
  &DoFlux(flux0,nflux0);
}

print "----- main science target observe loop -----\\n";
  &ObsLoop(cal0,cal1,targ0,cal0,targ0,cal0,targ0);

print "----- final flux and bandpass calibration -----\\n";
  &DoFlux(flux0,nflux0);
  &DoPass(bpass0,nbpass0);

print "----- Congratulations!  This is the end of the script.  -----\\n";}
#
################## File End ###############################
"""


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Generate an SMA observing .pl script from the GRB.pl template.")

    p.add_argument("--name", default="GRB", help="Target name (default: GRB)")
    p.add_argument("--ra", required=True, help="Target R.A., e.g. 21:01:11.22")
    p.add_argument("--dec", required=True, help="Target Dec., e.g. +42:13:13.7")
    p.add_argument("--epoch", default="2000", help="Coordinate epoch (default: 2000)")
    p.add_argument("--velocity", default="0", help="Radial velocity, km/s (default: 0)")
    p.add_argument("--dopp-freq", default="230", help="dopplerTrack rest freq, GHz (default: 230)")
    p.add_argument("--feed-freq", default="230", help="setFeedOffset freq, GHz (default: 230)")

    p.add_argument("--inttime", default="30", help="Integration time, s (default: 30)")
    p.add_argument("--ntarg0", default="24", help="Number of target scans (default: 24)")

    p.add_argument("--cal0", default="mwc349a", help="Gain calibrator 0 (default: mwc349a)")
    p.add_argument("--ncal0", default="4", help="Scans on cal0 (default: 4)")
    p.add_argument("--cal1", default="2015+371", help="Gain calibrator 1 (default: 2015+371)")
    p.add_argument("--ncal1", default="4", help="Scans on cal1 (default: 4)")
    p.add_argument("--flux0", default="titan", help="Flux calibrator (default: titan)")
    p.add_argument("--nflux0", default="20", help="Scans on flux0 (default: 20)")
    p.add_argument("--bpass0", default="3c279", help="Bandpass calibrator (default: 3c279)")
    p.add_argument("--nbpass0", default="120", help="Scans on bpass0 (default: 120)")

    p.add_argument("--minel-targ", default="17")
    p.add_argument("--maxel-targ", default="83")
    p.add_argument("--minel-gain", default="17")
    p.add_argument("--maxel-gain", default="83")
    p.add_argument("--minel-flux", default="17")
    p.add_argument("--maxel-flux", default="81")
    p.add_argument("--minel-bpass", default="17")
    p.add_argument("--maxel-bpass", default="87")
    p.add_argument("--minel-check", default="19")

    p.add_argument("--exp-code", default="2016A-A012", help="Experiment code")
    p.add_argument("--exp-title", default="Search for Bright submm afterglows Associated with Gamma-Ray Bursts")
    p.add_argument("--pi", default="Yuji Urata", help="PI name")
    p.add_argument("--contact", default=None, help="Contact person (default: same as --pi)")
    p.add_argument("--email", default="urata@asiaa.sinica.edu.tw")
    p.add_argument("--office", default="+886-3-4227151 ex 65951")
    p.add_argument("--home", default="+886-2-29201172")
    p.add_argument("--array", default="all")

    p.add_argument("--output", "-o", default=None,
                    help="Output filename (default: <name>.pl)")
    return p


def render(args: argparse.Namespace) -> str:
    contact = args.contact or args.pi
    values = {
        "__NAME__":        args.name,
        "__RA__":           args.ra,
        "__DEC__":          args.dec,
        "__EPOCH__":        args.epoch,
        "__VELOCITY__":     args.velocity,
        "__DOPP_FREQ__":    args.dopp_freq,
        "__FEED_FREQ__":    args.feed_freq,
        "__INTTIME__":      args.inttime,
        "__NTARG0__":       args.ntarg0,
        "__CAL0__":         args.cal0,
        "__NCAL0__":        args.ncal0,
        "__CAL1__":         args.cal1,
        "__NCAL1__":        args.ncal1,
        "__FLUX0__":        args.flux0,
        "__NFLUX0__":       args.nflux0,
        "__BPASS0__":       args.bpass0,
        "__NBPASS0__":      args.nbpass0,
        "__MINEL_TARG__":   args.minel_targ,
        "__MAXEL_TARG__":   args.maxel_targ,
        "__MINEL_GAIN__":   args.minel_gain,
        "__MAXEL_GAIN__":   args.maxel_gain,
        "__MINEL_FLUX__":   args.minel_flux,
        "__MAXEL_FLUX__":   args.maxel_flux,
        "__MINEL_BPASS__":  args.minel_bpass,
        "__MAXEL_BPASS__":  args.maxel_bpass,
        "__MINEL_CHECK__":  args.minel_check,
        "__EXP_CODE__":     args.exp_code,
        "__EXP_TITLE__":    args.exp_title,
        "__PI__":           args.pi,
        "__CONTACT__":      contact,
        "__EMAIL__":        args.email,
        "__OFFICE__":       args.office,
        "__HOME__":         args.home,
        "__ARRAY__":        args.array,
    }

    text = TEMPLATE
    for placeholder, value in values.items():
        text = text.replace(placeholder, str(value))
    return text


def main() -> None:
    args = build_parser().parse_args()
    output = args.output or f"{args.name}.pl"

    with open(output, "w") as f:
        f.write(render(args))

    mode = os.stat(output).st_mode
    os.chmod(output, mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    print(f"Wrote {output}")


if __name__ == "__main__":
    main()
