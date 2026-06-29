#!/usr/bin/perl -w
{ BEGIN {$^W =0}
#
################## Script Header Info #####################
#
# Experiment Code: 2024B-S045
# Experiment Title: SMA Interferometry School - 2025 Group I (Ishibashi/Zagorulia/Shinozaki/Hung)
# PI: Ramprasad Rao
# Contact Person: Ramprasad Rao  
# Email  : rrao@cfa.harvard.edu  
# Office : (808) 933-2973  
# Home   : -   
# Array  : compact   
#
#
############## SPECIAL INSTRUCTIONS ################
#
# As the transit observation, we would like to 
# observe either Mars or Jupiter. Please choose 
# between Mars and Jupiter, since the observation 
# schedule is uncertain.
#
################## Priming ################################
#
# observe -s L1551_MC -r 04:31:11.0 -d 18:12:52.5 -e 2000 -v 0
# dopplerTrack -S L1551_MC -r 230.538 -u -s1 -f 0.462 -R B -r 230.538 -u -s1 -f 0.462
#
################## Pointing ###############################
#
# Pointing: None requested
# Syntax Example: point -i 60 -r 3 -L -l -t -Q
#
################## Source, Calibrator and Limits ##########
#
$inttime="15"; 
$targ0="L1551_MC -r 04:31:11.0 -d 18:12:52.5 -e 2000 -v 0"; $ntarg0="60"; 
$cal0="0530+135"; $ncal0="6";
$cal1="3c120"; $ncal1="6";
$transcal="3c84"; $ntranscal="10";
$flux0="Uranus"; $nflux0="20";
$flux2="Neptune"; $nflux2="20";
$flux1="Callisto"; $nflux1="20";
$bpass0="3c84"; $nbpass0="120";
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
command("project -r -p 'Ramprasad Rao' -d '2024B-S045'");
print "----- initialization done, starting script -----\n";
#
################## Science Script #########################
#
print "----- initial flux and bandpass calibration -----\n";
if(!$restart){
  #&DoPass(bpass0,nbpass0);
  &DoFlux(flux2,nflux2);
  &DoFlux(flux0,nflux0);
  #&DoFlux(flux1,nflux1);
}

print "----- main science target observe loop -----\n";
  &ObsLoop(cal0,cal1,targ0);

print "----- final flux and bandpass calibration -----\n";
  #&DoFlux(flux0,nflux0);
  #&DoFlux(flux1,nflux1);
  #&DoPass(bpass0,nbpass0);

print "----- Congratulations!  This is the end of the script.  -----\n";}
#
################## File End ###############################

