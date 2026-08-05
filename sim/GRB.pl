#!/usr/bin/perl -w
{ BEGIN {$^W =0}
#
################## Script Header Info #####################
#
# Experiment Code: 2016A-A012
# Experiment Title: Search for Bright submm afterglows Associated with Gamma-Ray Bursts
# PI: Yuji Urata
# Contact Person: Yuji Urata
# Email  : urata@asiaa.sinica.edu.tw
# Office : +886-3-4227151 ex 65951
# Home   : +886-2-29201172
# Array  : all
#
#
############## SPECIAL INSTRUCTIONS ################
#
# none
#
################## Priming ################################
#
# observe -s GRB -r 21:01:11.22 -d +42:13:13.7 -e 2000 -v 0
# dopplerTrack -S GRB -r 230 -u -s25
# restartCorrelator -R l -s128
# setFeedOffset -f 230
#
################## Pointing ###############################
#
# Pointing: At start of track
# Syntax Example: point -i 60 -r 3 -L -l -t -Q
#
################## Source, Calibrator and Limits ##########
#
$inttime="30";
$targ0="GRB -r 21:01:11.22 -d +42:13:13.7 -e 2000 -v 0"; $ntarg0="24";
$cal0="mwc349a"; $ncal0="4";
$cal1="2015+371"; $ncal1="4";
$flux0="titan"; $nflux0="20";
$bpass0="3c279"; $nbpass0="120";
$MINEL_TARG = 17; $MAXEL_TARG = 83;
$MINEL_GAIN = 17; $MAXEL_GAIN = 83;
$MINEL_FLUX = 17; $MAXEL_FLUX = 81;
$MINEL_BPASS= 17; $MAXEL_BPASS= 87;
$MINEL_CHECK= 19;
#
################## Script Initialization ##################
#
do 'sma.pl';
do 'sma_add.pl';
checkANT();
command("radio");
command("integrate -t $inttime");
$myPID=$$;
command("project -r -p 'Yuji Urata' -d '2016A-A012'");
print "----- initialization done, starting script -----\n";
#
################## Science Script #########################
#
print "----- initial flux and bandpass calibration -----\n";
if(!$restart){
#  &DoPass(bpass0,nbpass0);
  &DoFlux(flux0,nflux0);
}

print "----- main science target observe loop -----\n";
  &ObsLoop(cal0,cal1,targ0,cal0,targ0,cal0,targ0);

print "----- final flux and bandpass calibration -----\n";
  &DoFlux(flux0,nflux0);
  &DoPass(bpass0,nbpass0);

print "----- Congratulations!  This is the end of the script.  -----\n";}
#
################## File End ###############################
