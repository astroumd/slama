#!/usr//bin/perl -w
#
# delete the very first # sign on the topmost line to check this 
# script for syntax errors if you make any changes.
# Then put back the # sign.
#
# ----------------------------------------------------------------------------#
# ---------------------------    Subroutines    ------------------------------#
# These subroutines do not depend on specific observations. Thus, they should
# not be changed.

use Time::Local;

# init values for optional params.
use Getopt::Long;
$Getopt::Long::autoabbrev=1;



sub initialize() 
{
    print "initializing.....\n";
    $specialflux=0;
    $garrus = 0;
    $silent=0;
    $newSourceFlag=0;
    $tsysDelay=11.;
    $observeDelay=10.;
    $pointDelay=120.;
    $prevUnixTime=0;
    $unixTime=0;
    $totalIntegrationTime=0;
    $decsign=1;
    $sourceNameArgindex=0;
    $firstTime=1; # used for unixtime conversion if given UTC
    $nloop=1;  
    $maxloops=200;
    $nightpointing = 0;
    $fullPolarization = 0;
    $timefluxcounter=0;
    $nightpointingtime = 10800; #time between pointings at night in seconds. Normally 3 hours (10800 seconds).
    $daypointingtime = 3600; #time between pointings during the day in seconds.
    $loopcounter = 0; #so the script knows which loop it is on (using @loop)
    GetOptions('time=s'=>\$givenUTC,'simulate','restart','mosaic','figure','antennas=s'=>\$antList,'pointing','ipoint=s'=>\$ipoint,'help','day','night','value=f'=>\$fluxvalue,'b','k');
    $nloop--;
    if($opt_help)
    {
	&Usage; die "\n";
    }
    if($givenUTC) 
    {
	($mn,$d,$year,$gh,$gm)=split(' ',$givenUTC);
	$mn=$mn-1;
	$unixTime=timelocal(0,$gm,$gh,$d,$mn,$year);
	$prevUnixTime=$unixTime;
    }

    unless($fluxvalue)
    {
	$fluxvalue = 1.0;
    }
    #print "The current time is $unixTime\n";
    if($opt_simulate) {$simulateMode=1;} else {$simulateMode=0;}
    print "simulateMode = $simulateMode\n";
    #if($opt_restart || $opt_figure) {$restart=1;} else {$restart=0;}
    if($opt_restart) {$restart=1;} else {$restart=0;}
    $maxpointingel = 75;
    if($MINEL_GAIN > 25)
    {
	$minpointingel = $MINEL_GAIN;
    }
    else
    {
	$minpointingel = 25;
    }
#Ctrl-C interrupt handler;
    $SIG{INT}=\&finish;

    $unameResponse = `uname -a`;
    ($thisOS,$thisMachine,$otherStuff)=split(' ',$unameResponse);
    print "Running on machine = $thisMachine\n";
    
    if(($thisMachine ne "hal9000") && ($thisMachine ne "obscon1")) 
    {
	print "Not running on hal9000, entering simulation mode.\n";
	$simulateMode=1;
    } 
    #grab the current time or the simulated time for the last pointing.
    print "$simulateMode\n";
    if($opt_simulate)
    {
	$lastpointing = $unixTime;
    }
    else
    {
	#the last pointing finder should go here. the simulations can use the start of script time.
	$date = `date \+%y%m%d`;
	$year = `date -u \+%Y`;
	chomp($year);
	$lastyear = $year-1;
	$ipointstuff = `ls -l /data/engineering/ipoint/ant$sma[3]/$date`;
        #$ipoint = `ls -l /sma/rtdata/engineering/ipoint/ant4/$date`;
	unless($ipointstuff =~ /\w/) #go back a day, if there wasn't an ipoint today (if we changed UT days recently)
	{
	    $date = $date - 1; #this won't work if the month changes, but that's a whole other can of worms which will be relevent about once a year.
	    $ipointstuff = `ls -l /data/engineering/ipoint/ant$sma[3]/$date`;
	}
	
	if($ipointstuff =~ /\w/ && $ipointstuff !~ /$lastyear/)
	{
	    @ipointtime = split(/\s+/, $ipointstuff);
	    @itime = split(/:/, $ipointtime[6]);
	    if ($ipointtime[4] eq "Jan")  
	    {
		$ipointtime[4] = "00";
	    }
	    if ($ipointtime[4] eq "Feb")  
	    {
		$ipointtime[4] = "01";
	    }
	    if ($ipointtime[4] eq "Mar")  
	    {
		$ipointtime[4] = "02";
	    }
	    if ($ipointtime[4] eq "Apr")  
	    {
		$ipointtime[4] = "03";
	    }
	    if ($ipointtime[4] eq "May")  
	    {
		$ipointtime[4] = "04";
	    }
	    if ($ipointtime[4] eq "Jun")  
	    {
		$ipointtime[4] = "05";
	    }
	    if ($ipointtime[4] eq "Jul")  
	    {
		$ipointtime[4] = "06";
	    }
	    if ($ipointtime[4] eq "Aug")  
	    {
		$ipointtime[4] = "07";
	    }
	    if ($ipointtime[4] eq "Sep")  
	    {
		$ipointtime[4] = "08";
	    }
	    if ($ipointtime[4] eq "Oct")  
	    {
		$ipointtime[4] = "09";
	    }
	    if ($ipointtime[4] eq "Nov")  
	    {
		$ipointtime[4] = "10";
	    }
	    if ($ipointtime[4] eq "Dec")  
	    {
		$ipointtime[4] = "11";
	    }
	    $ipointingtime = timelocal(0,$itime[1],$itime[0],$ipointtime[5],$ipointtime[4],$year);
	}
	else
	{
	    $ipointingtime = 0;
	}
	
	$cpoint = `ls -l /data/engineering/rpoint/ant$sma[3]/tmp.dat.lowfreq`;
	#$cpoint = `ls -l /sma/rtdata/engineering/rpoint/ant4/tmp.dat.lowfreq`;
	if($cpoint =~ /\w/ && $cpoint !~ /$lastyear/)
	{
	    @cpointtime = split(/\s+/, $cpoint);
	    @ctime = split(/:/, $cpointtime[6]);
	    if ($cpointtime[4] eq "Jan")  
	    {
		$cpointtime[4] = "00";
	    }
	    if ($cpointtime[4] eq "Feb")  
	    {
		$cpointtime[4] = "01";
	    }
	    if ($cpointtime[4] eq "Mar")  
	    {
		$cpointtime[4] = "02";
	    }
	    if ($cpointtime[4] eq "Apr")  
	    {
		$cpointtime[4] = "03";
	    }
	    if ($cpointtime[4] eq "May")  
	    {
		$cpointtime[4] = "04";
	    }
	    if ($cpointtime[4] eq "Jun")  
	    {
		$cpointtime[4] = "05";
	    }
	    if ($cpointtime[4] eq "Jul")  
	    {
		$cpointtime[4] = "06";
	    }
	    if ($cpointtime[4] eq "Aug")  
	    {
		$cpointtime[4] = "07";
	    }
	    if ($cpointtime[4] eq "Sep")  
	    {
		$cpointtime[4] = "08";
	    }
	    if ($cpointtime[4] eq "Oct")  
	    {
		$cpointtime[4] = "09";
	    }
	    if ($cpointtime[4] eq "Nov")  
	    {
		$cpointtime[4] = "10";
	    }
	    if ($cpointtime[4] eq "Dec")  
	    {
		$cpointtime[4] = "11";
	    }
	    $cpointingtime = timelocal(0,$ctime[1],$ctime[0],$cpointtime[5],$cpointtime[4],$year);
	}
	else
	{
	    $cpointingtime = 0;
	}
	
	if($ipointingtime == 0 && $cpointingtime == 0)
	{
	    $lastpointing = time();
	    print "No pointing could be found, setting the last pointing time to now.\n";
	}
	elsif($ipointingtime >= $cpointingtime)
	{
	    $lastpointing = $ipointingtime;
	    $month = $ipointtime[4] + 1;
	    print "The last pointing was a ipoint at $year/$month/$ipointtime[5] $itime[0]:$itime[1]\n";
	}
	else
	{
	    $lastpointing = $cpointingtime;
	    $month = $cpointtime[4] + 1;
	    print "The last pointing was a cpoint at $year/$month/$cpointtime[5] $ctime[0]:$ctime[1]\n";
	}
    }
    print "The last pointing time is $lastpointing\n";
    #exit;
    #figure out sunrise and set times
    #$sun = "278.392918 51.834654 0.000000
    #rising at 17:17, transiting at 22:18, setting at 03:19 UTC";
    if($thisMachine eq 'oldulua')
    {
	$sun = `./lookup -s sun -w`;
    }
    else
    {
	$sun = `lookup -s sun -w`;
    }
    @suntimes = split(/\s/, $sun);
    chop($suntimes[5]);
    @temp = split(/:/,$suntimes[5]);
    @temp1 = split(/:/,$suntimes[11]);
    #print "The sun set time from lookup is $suntimes[11]\n";
    if($temp1[0] > 23)
    {
	$temp1[0] = $temp1[0] - 24;
    }
    $temp[0] = $temp[0] - 1; #all this fixes the sunrise and set times since they are given for 20 degrees from the lookup.
    if($temp[1] > 45)
    {
	$temp[1] = $temp[1] - 45;
    }
    else
    {
	$temp[0] = $temp[0] - 1;
	$temp[1] = $temp[1] + 15;
    }
    $temp1[0] = $temp1[0] + 1;
    if($temp1[1] <= 20)
    {
	$temp1[1] = $temp1[1] + 40;
    }
    else
    {
	$temp1[0] = $temp1[0] + 1;
	$temp1[1] = $temp1[1] - 20;
    }
    if($temp[1] == 60)
    {
	$temp[0] += 1;
	$temp[1] = 0;
	if($temp[0] > 23)
	{
	    $temp[0] = $temp[0] - 24;
	}
    }
    if($temp1[1] == 60)
    {
	$temp1[0] += 1;
	$temp1[1] = 0;
	if($temp1[0] > 23)
	{
	    $temp1[0] = $temp1[0] - 24;
	}
    }
    if($temp[1] < 10)
    {
	$temp[1] = '0' . $temp[1];
    }
    if($temp1[1] < 10)
    {
	$temp1[1] = '0' . $temp1[1];
    }
#I'm droping the colon to make math easier later.
    $sunrise = $temp[0] . $temp[1];
    $sunset = $temp1[0] . $temp1[1];

    print "Sunrise is $sunrise and sunset is $sunset\n";
    
#add an hour to sunset, since that's when we want to switch to night time pointing times.
    $sunset = $sunset + 100;
    print "Sunset is now $sunset\n";
    $year = `date "+%Y"`;
    chomp($year);
    $month = `date "+%m"`;
    chomp($month);
    $month -= 1;
    $day = `date "+%d"`;
    chomp($day);
    $h = $temp1[0] + 1;
    #print "The time for the sunset time is $year, $month, $day, $h, $temp1[1]\n";
    $sunsettime = timelocal(0,$temp1[1],$h,$day,$month,$year);
    #print "The number of seconds is $sunsettime\n";
    if($sunsettime <= $lastpointing)
    {
	$nightpointing = 1;
	print "The last pointing was after an hour after sunset\n";
    }
    #exit;
    $mypid = $$;
    $myname = ${0};
    if(not $simulateMode) 
    {
	command("radecoff -r 0 -d 0");
	command("project -r -i $mypid -f $myname");
	printPID();
    } 
    else 
    {
	print "Script: $myname.\n";
    }

    $ants = '';
    if($antList)
    {
	#$space = `parseAntennaList $antList`;
	#chomp($space);
	#print "The parsed list is $space\n";
	@tsys = sort(split(/,/, $antList));
	@dotdot = ();
	@sera = ();
	if($antList =~ /../)
	{
	    for($g = 0; $g <= $#tsys; $g++)
	    {
		if($tsys[$g] =~ /\.\./)
		{
		    @temp = split /\.\./, $tsys[$g];
		    for($c = $temp[0]; $c <= $temp[1]; $c++)
		    {
			push @dotdot, $c;
		    }
		    push @sera, $g;
		}
	    }
	}
	$bull = 0;
	foreach $varric (@sera)
	{
	    if($bull == 0)
	    {
		splice @tsys, $varric, 1, @dotdot;
		$bull++;
	    }
	    else
	    {
		splice @tsys, $varric, 1;
	    }
	}
	if(($thisMachine ne "hal9000")  && ($thisMachine ne "obscon1"))
	{
	    $list = " 1 3 4 5 6 7 8";
	}
	else
	{
	    $list = `getAntList`;
	}
	#print "$list\n";
	chomp($list);
	if($list =~ /^\s/)
	{
	    $list =~ s/^\s//;
	}
	#print "$list\n";
	@project = split / /, $list;
	foreach $ant (@project)
	{
	    $onlist = 1;
	    foreach $tant (@tsys)
	    {
		if($tant == $ant)
		{
		    $onlist = 0;
		}
	    }
	    if($onlist)
	    {
		$ants = $ants . $ant . ",";
	    }
	}
	chop($ants);
	#$ants =~ s/ /,/g;
	#print "antList is $antList\n";
	print "ants is $ants\n";
    }
    #exit;

#here's the new bit moved here, from sma_add.pl, so it can be executed in the correct order.
    if($opt_figure)
    {
	print "starting the figuring\n";
	#this part gets the loop data from later in the script.
	$d = 0;
	@loop = ();
	@allsources = ();
	$check = 0;
	$longline = "";
	open(FILE, "$0") or die "file couldn't be opened\n";
	#print "The file that was just openned is $0\n";
	while(<FILE>)
	{ 
	    $line = $_;
	    #if($line !~ /^\#/ && $line !~ /^\s/)
	    if($line !~ /^\#/)
	    {
		#print "The line is $line";
		if($line =~ /restart/)
		{
		    $d = 1;
		    #print "d is $d\n";
		}
		if($d == 1 && $line =~ /\}/)
		{
		    $d = 0;
		}
		if($line =~ /$\;/)
		{
		    #print  "The line $line, ended with a semicolon.\n";
		    if($longline ne "")
		    {
			$longline = $longline . $line;
			$line = $longline;
			#print "The multi-line loop is $longline.\n";
		    }
		    if($line =~ /ObsLoop/ || $line =~ /DoFlux/ || $line =~ /DoPass/)
		    {
			push @loop, $line;
			#print "Pushing the above line into the array loop.\n";
		    }
		    if($line =~ /ObsLoop/ || $line =~ /DoFlux/ || $line =~ /DoPass/ || $line =~ /LST_/)
		    {
			push @loop1, $line;
			#print "Pushing the above line into the array loop.\n";
		    }
		    if($line =~ /checkANT/)
		    {
			$check = 1;
		    }
		    if($d == 1 && ($line =~ /ObsLoop/ || $line =~ /DoFlux/ || $line =~ /DoPass/))
		    {
			#print "This line is in the restart: $line";
			#$garrus++;
		    }
		    unless($check)
		    {
			if($line =~ /^\$targ/)
			{
			    @frell = split /\"/, $line;
			    @dren = split / /, $frell[1];
			    push @allsources, $dren[0];
			}
			elsif($line =~ /^\$cal/)
			{
			    @frell = split /\"/, $line;
			    push @allsources, $frell[1];
			}
			elsif($line =~ /^\$flux/)
			{
			    @frell = split /\"/, $line;
			    push @allsources, $frell[1];
			}
			elsif($line =~ /^\$bpass/)
			{
			    @frell = split /\"/, $line;
			    push @allsources, $frell[1];
			}
		    }
		    $longline = "";
		}
		elsif($line !~ /\}/ && $line !~ /restart/)
		{
		    $line =~ s/\s//g;
		    #print "The line is now:$line.\n";
		    $longline .= $line;
		    #print "long line is currently $longline\n";
		}
	    }
        }
	close(FLIE);
	#print "After reading the script this is the information we have:\n";
	#print "@loop\n";
	#print "@loop1\n"; #this also has the LST wrapers. I don't think the new scheme will need them.
	#exit;
	#this part reads the mir data file.
#these leftmost comments removed the working datafile reading which is probably not necessary
#        unless($simulateMode)
#	{
#	    $thename = "";
#	    #$machine = `shmValue -m hal9000 DSM_HAL_HAL_STORAGE_SERVER_C40`;
#	    #chomp ($machine);
#	    #if($machine !~ /\w/)
#	    #{
#		#$machine = 'hcn';
#	    #} #it seems unlikely that we'll change dataCatcher back to m5 at this point.
#	    $machine = 'hcn';
#	    $datafile = `shmValue -m $machine DSM_AS_FILE_NAME_C80`; 
#	    print "The datafile is $datafile\n";
#	    @files = `ls $datafile`;
#	    foreach $file (@files)
#	    {
#		if($file =~ /plot_me/)
#		{
#		    $thename = $file;
#		}
#	    }
#	    chomp($datafile);
#	    $datafile =~ s/\s+$//;
#	    chomp($thename);
#	    $datafile = $datafile . $thename;
#	    #print "The datafile should be: $datafile.\n";
#	    open(LOG, "<$datafile") or die "the input file couldn't be opened\n"; #for hal
#	}
#	else
#	{
#	    open(LOG, "<plot_me_5_rx0") or die "the input file couldn't be opened.\n"; #for testing
#	}	
#	$oldtime = "";
#	$newtime = "";
#	@list = ();
#	@times = ();
#	#print "Reading the datafile.\n";
#	while(<LOG>)
#	{
#	    $line = $_;
#	    @stuff = split(" ", $line);
#	    $oldtime = $newtime;
#	    $newtime = $stuff[1];
#	    if($newtime > $oldtime)
#	    {
#		$int = 3600 * ($newtime - $oldtime);
#	    }
#	    else
#	    {
#		$int = 30;
#	    }
#	    $y = 0;
#	    $n = 0;
#	    for($v=8; $v < $#stuff; $v+=6)
#	    {
#		#print "I'm in the for loop v is $v and the stopping pointing should be $#stuff.\n";
#		if($stuff[$v] == 1)
#		{
#		    $y++;
#		}
#		else
#		{
#		    $n++;
#		}
#		
#	    }
#	    if($n > $y)
#	    {
#		$check = 0;
#	    }
#	    else
#	    {
#		$check = 1;
#	    }
#	    #print "The integration time is: $int\n";
#	    #if($stuff[8] == 1 && ($int > 5.3))
#	    if($check == 1 && ($int > 5.3))
#	    {
#		push @list, $stuff[0];
#		push @times, $stuff[1];
#	    }
#	    #print "reading data for $stuff[0].\n";
#	}
#	#print "The last line is: $line";
#	close(LOG);
#	#print "Finished with the datafile.\n";
#	
##open(DATA, ">datafile.txt");
#	
#	$lastitem = "";
#	$sourcecount = -1;
#	@sourcelist = ();
#	@sourcescans = ();
#	@sourcetime = ();
#	$counter = 0;
#	#print "Setting up the arrays with the source data.\n";
#	foreach $item (@list)
#	{
#	    if($lastitem ne $item)
#	    {
#		#print DATA "$item\n";
#		$sourcecount++;
#		$sourcelist[$sourcecount] = $item;
#		$sourcescans[$sourcecount] = 1;
#		$sourcetime[$sourcecount] = $times[$counter];
#	    }
#	    else
#	    {
#		$sourcescans[$sourcecount]++;
#	    }
#	    $lastitem = $item;
#	    #print "The item is: $item\n";
#	    $counter++;
#	}
##close(DATA);
#	#exit;
#	#print "here's the final bit of information from the data taken so far:\n";
#	for($c = 0; $c <= $#sourcelist; $c++)
#	{
#	    #print "$sourcelist[$c], $sourcescans[$c]\n";
#	    if($sourcelist[$c] =~ /\+/)
#	    {
#		@plus = split('\+',$sourcelist[$c]);
#		$sourcelist[$c] = $plus[0] . '\+' . $plus[1];
#	    }
#	}
	#print "Printing the contents of the array loop:\n";
	#foreach $item (@loop)
	#{
	#    print $item;
	#}
        #exit;
#this contains the completion status for each loop in order. 0 is not started, at the start of a loop,
#or the loop was skipped, 1 is complete, and 2 is partially finished.
	@theword = ();
	$partialscans = 0; #this has the number of scans that need to be observe for flux or bp cals
	@partialobsloop = (); #this has the rest of the observing loop.
	#the new stuff can go here. Some of the old stuff below may migrate up later.

	open(RESTARTFILE, "restartfile.txt");
	while(<RESTARTFILE>)
	{ 
	    $line = $_;
	    if($line=~ /\w/)
 	    {	
		@stuff = split(/ /,$line);	
	    }	    
	}	
	close(RESTARTFILE);
	for($k=0;$k<=$#loop;$k++)
	{
 	    if($stuff[0] > $k)
	    {
		$theword[$k] = 1;
	    }
	    elsif($stuff[0] == $k)
	    {
		$theword[$k] = 2;
	    }
	    else
	    {
		$theword[$k] = 0;
	    }
	}
	if($stuff[3] != 0)
	{
	    $loopsdone = $stuff[3];
	    print "There were a total of $loopsdone loops finished.\n";
	}
	if($loop[$stuff[0]] =~ /ObsLoop/)
	{
	    #print "Looking at the obs loop.\n";
	    @temp = split(/\(/, $loop[$stuff[0]]);
	    @temp = split(/\)/, $temp[1]);
	    @temp = split(/,/, $temp[0]);
	    print "The total number of sources in the loop should be $#temp\n";
	    print "The loop should be @temp\n";
	    if($stuff[1] >= $#temp)
	    {
		$partialobsloop = 0;
	    }
	    else
	    {
		$partialobsloop = $stuff[1] + 1;
	    }
	    #if($stuff[1] == 0) #I removed the file checking stuff for now
	    #{
		#$place = $#temp;
	    #}
	    #else
	    #{
		#$place = ($stuff[1] - 1);
	    #}
	    #$checkcal = ${$temp[$place]};
	    #$checknum = $n{$temp[$place]};
	    #$checknum=2;
	    #if($stuff[2] =~ /P/)
	    #{
		#$sn = $#sourcelist - 1;
	    #}
	    #else
	    #{
		#$sn = $#sourcelist;
	    #}
	    #$sn = $#sourcelist;
	    #if($sourcelist[$sn] =~ /$checkcal/ && $sourcescans[$sn] >= $checknum)
	    #{
		#for($s=$stuff[1]; $s<=$#temp; $s++)
		#{
		    #push @partialobsloop, $temp[$s];
		#}
	    #}
	    #else
	    #{
		#for($s=$place; $s<=$#temp; $s++)
		#{
		    #push @partialobsloop, $temp[$s];
		#}
	    #}
	}
	else
	{
	    $partialscans = $stuff[1];
	    #@temp = split(/\(/, $loop[k]);
	    #@temp = split(/,/, $temp[1]);
	    #if(${$temp[0]} =~ /$sourcelist[$#sourcelist]/ && ($n{$temp[0]} >= $stuff[1]))
	    #{
		#$partialscans = $stuff[1];
	    #}
	    #else
	    #{
		#$partialscans = $stuff[1] - 10;
	    #}
	}
	print "the word is @theword\n";
	print "the partial loop is $partialobsloop\n";
	print "the remaining scans are $partialscans\n";
	#exit;
    }
}

# --- interrupt handler for CTRL-C ---
sub finish 
{
    command("radecoff -r 0 -d 0");
    sleep(1);
    print "Please remember to stow the antennas safely if you are leaving.\n";
    exit(1);
}

# --- print PID ---
# usage: printPID();
sub printPID 
{
    if(not $simulateMode) 
    {
	print "The process ID of this $0 script is $mypid\n";
    }
}


# --- check antennas ---
# usage: checkANT();
# This subroutine checks active antennas and stores them
# as an array @sma.
sub checkANT 
{
    my ($i,$exist);
    print "Checking antenna status ... \n";
    if($simulateMode == 1)
    {
	@sma = (1,2,3,4,5,6,7,8);
    }
    else
    {
	$temp = `getAntList`;
	chomp($temp);
	if($temp =~ /^\s/)
	{
	    $temp =~ s/^\s//;
	}
	@sma = split(/ /, $temp);
    }
    initialize();
    $nants = scalar(@sma);
    #if($pants !~ /[1-8],[1-8]/) #this needs to be made better.
    if($pants !~ /^[1-8]+(?:,[1-8]{1,3}){0,2}$/) #this needs to be made better.
    {
	$pants = "$sma[1],$sma[2]";
    }
    print "nants = $nants\n";
    print "pants = $pants\n";

    if(not $simulateMode) 
    { 
	print "Antennas @sma are going to be used.\n";
	scriptcopy();
    }
    #exit;
}

sub scriptcopy
{
# write out a copy of this script in the data area

    $thisfile=${0};
  $thisfileonly =(split '/', $thisfile)[-1];
  $hour=(gmtime)[2];
  $minute=(gmtime)[1];
  $seconds=(gmtime)[0];
  $day=(gmtime)[3];
  $month=(gmtime)[4]+1;
  $year=(gmtime)[5];
  $year+=1900;
  $timeStamp=sprintf("%4d%02d%02d_%02d%02d%02d",
		$year,$month,$day,$hour,$minute,$seconds);
  $scriptFileName=$thisfileonly."_".$timeStamp;
  $directoryName="/data/current/aux";
#  $directoryName=`readDSM -v DSM_AS_FILE_NAME_C80 -m hcn -l`;
#  chomp($directoryName);
  $scriptFileNameWithPath=$directoryName."/".$scriptFileName;

  # recreate projectInfo filename (as copied from sma1) from the name of the script being run ($thisfile - already defined).
    #$projInfoFileName=substr($thisfile, 0, -12)."_projectInfo";
  $projInfoFileName=".\/projectInfo_".substr($thisfileonly, 0, -3);
  $projInfoFileName=~tr/.\/\///d;
  # Create destination path using the date-stamp-removed name.
  # Same $directoryName already defined for script copy.
  $destinationprojInfoFileNamePath=$directoryName."/".substr($projInfoFileName,0,-9);

#    print "\n PLEASE SAVE THE COPY LINES BELOW FOR HOLLY (JUL 2023)\n";
  print "Copy commands:\n
  cp $thisfileonly $scriptFileNameWithPath\n
  cp $projInfoFileName $destinationprojInfoFileNamePath\n\n";

  $cpresponse=`cp $thisfileonly $scriptFileNameWithPath`;
	if($cpresponse ne "") {
	print "Copying this script to data area...\n $cpresponse";
	}

  $cpprojresponse=`cp $projInfoFileName $destinationprojInfoFileNamePath`;
    if($cpprojresponse ne "") {
    print "Copying this projectInfo file to data area...\n $cpprojresponse";
    }
}


# --- check elevation of a source ---
# usage: checkEl($sourcename);
# This subroutine checks the elevation of a source and prints
# its value.
# e.g.,
#      $a=checkEl('your_source);
# will give you the eleveation in $a and also prints it on screen.
# Also,
#      $a=checkEl('your_source',1);
# will give $a the elevation but does not print the value.
# The second argument, 'silent flag', is optional.
sub checkEl 
{
    my ($sourcename)=$_[0];
    my ($silent)    =(defined($_[1]) and $_[1]);
#    my ($sourceCoordinates,$sourceAz,$sourceEl,$sunDistance);

    if((not $simulateMode) or ($thisMachine eq "hal9000")) 
    {
	$sourceCoordinates=`lookup -s $sourcename`;
   	chomp($sourceCoordinates);
   	($sourceAz,$sourceEl,$sunDistance)=split(' ',$sourceCoordinates);
	if ($sourceAz =~ /Source/) 
	{
	    print "##########################################\n";
	    print "######## WARNING WARNING WARNING #########\n";
	    print "##### source $sourcename not found. ######\n";
	    print "##########################################\n";
	    die   " quiting from the script \n";
	}
    } 
    else 
    {
	my %month_names;
	@month_name{ 1 .. 12 } = qw(Jan Feb Mar Apr May Jun Jul Aug Sept Oct Nov Dec);
	$lookupTime="$d $month_name{$mn} $year $hour:$min";
	# check sourcename for ra dec input - if so, parse it
	if($sourcename =~ /-r/) 
	{
#	print "got ra/dec arguments...parsing them...\n";
	    if(!($sourcename =~ /-d/)) { die "both ra and dec are required\n";}
	    @sourcenameArgs=split(' ',$sourcename);
	    $iarg=0;
	    $sourceNameArgindex=0;
	    foreach $arguments (@sourcenameArgs) 
	    {
		if($arguments eq '-s') {$sourceNameArgindex=$iarg+1;}
		if($arguments=~/r/) {$raArgindex=$iarg+1;}
		if($arguments=~/d/) {$decArgindex=$iarg+1;}
		if($arguments=~/e/) {$epochArgindex=$iarg+1;}
		$iarg++;
	    }
	    $rastring=$sourcenameArgs[$raArgindex];
	    $sourceNameString=$sourcenameArgs[$sourceNameArgindex];
	    $decstring=$sourcenameArgs[$decArgindex];
	    $givenEpoch=$sourcenameArgs[$epochArgindex];
	    ($rah,$ram,$ras)=split('\:',$rastring);
	    ($decd,$decm,$decs)=split('\:',$decstring);
	    $givenRA=$rah+$ram/60.+$ras/3600.;
	    if($decd<0.) {$decsign=-1;$decd=-$decd} else {$decsign=1;}
	    $givenDEC=$decd+$decm/60.+$decs/3600.;
	    if($decsign==-1){$givenDEC=-$givenDEC;}
	    $parsedSourcename="$sourceNameString -r $givenRA -d $givenDEC -e $givenEpoch ";
	    $newSourceFlag=1;
	} 
	else 
	{
	    $newSourceFlag=0;
	}
	
	if($newSourceFlag==1) 
	{
	    if($thisMachine eq 'oldulua')
	    {
		$sourceCoordinates=`\./lookup -s $parsedSourcename -t "$lookupTime"`;
	    }
	    else
	    {
		$sourceCoordinates=`lookup -s $parsedSourcename -t "$lookupTime"`;
	    }
	} 
	else 
	{
	    if($thisMachine eq 'oldulua')
	    {
		print "lookup time: $lookupTime\n";
		$sourceCoordinates=`\./lookup -s $sourcename -t "$lookupTime"`;
	    }
	    else
	    {
		print "lookup time: $lookupTime\n";
		$sourceCoordinates=`lookup -s $sourcename -t "$lookupTime"`;
	    }
	}
	#print "The parsed source name is $parsedSourcename\n";
	print "The lookup time is: $lookupTime\n";
   	chomp($sourceCoordinates);
   	($sourceAz,$sourceEl,$sunDistance)=split(' ',$sourceCoordinates);
	if ($sourceAz =~ /Source/) 
	{
	    print "##########################################\n";
	    print "######## WARNING WARNING WARNING #########\n";
	    print "##### source $sourcename not found. ######\n";
	    print "##########################################\n";
	    die   " quiting from the script \n";
	}
   	if (not $silent) 
	{
	    if($newSourceFlag==1) 
	    {
		printf("%s is at %4.4f degrees elevation\n",$sourceNameString,$sourceEl);
	    } 
	    else 
	    {
		printf("%s is at %4.4f degrees elevation\n",$sourcename,$sourceEl);
	    }
   	}
    }
    if($sunDistance < 25.0)
    {
	print "The source $sourcename is too close to the sun at $sunDistance. Skipping it.\n";
	$sourceEl = 1.0;
    }
    return $sourceEl;
}

#this subrutine is ancient and can be removed.
sub mainLoop () 
{
    @inputArgs=@_;
    $narg=$#inputArgs+1;
    if(($narg%2)!=0) {die "Incorrect number of arguments.\n";}
    for ($i=1;$i<$narg;$i=$i+2) 
    {
        $numbercheck=$inputArgs[$i];
	if(!($numbercheck !~ /\D/)) 
	{
	    $j=$i+1;die "Argument $j is Not a number\n";
	}
    }
    
    for ($i=0;$i<$narg;$i=$i+2) 
    {
	#LST(); 
	$targel=checkEl($inputArgs[$i]);
        $current_source = $inputArgs[$i];
	
	if($targel>$MINEL_CHECK) 
	{
	    command("observe -s $inputArgs[$i]");
	    command("tsys");
	    command("integrate -s $inputArgs[$i+1] -w");
	}
	else 
	{
	    print "Source $inputArgs[$i] is too low: $targel deg.\n";
	    print "Skipping it.\n";
        }
	
    }
    
}
#this subrutine is ancient and can be removed.
sub mainLoopMosaic () 
{
    @inputArgs=@_;
    $narg=$#inputArgs+1;
    if(($narg%3)!=0) {die "Incorrect number  of arguments.\n";}
    for ($i=1;$i<$narg;$i=$i+3) 
    {
        $numbercheck=$inputArgs[$i];
	if(!($numbercheck !~ /\D/)) 
	{
	    $j=$i+1;die "Argument $j is Not a number\n";
	}
    }
    
    for ($i=0;$i<$narg;$i=$i+3) 
    {
	#LST(); 
	$targel=checkEl($inputArgs[$i]);
        $current_source = $inputArgs[$i];
	
	if($targel>$MINEL_CHECK) 
	{
	    command("observe -s $inputArgs[$i]");
	    ($raoff,$decoff)=split(',',$inputArgs[$i+2]);
	    command("radecoff -r $raoff -d $decoff");
	    command("tsys");
	    command("integrate -s $inputArgs[$i+1] -w");
	    command("radecoff -r 0 -d 0");
	} 
	else 
	{
	    print "Source $inputArgs[$i] is too low: $targel deg.\n";
	    print "Skipping it.\n";
        }
	
    }
}


# --- performs a shell task with delay and printing. ---
sub command 
{
    print "@_\n";       				# print the command
    my ($givenCommand)=$_[0];
    if($antenna && $givenCommand =~ /tsys/)
    {
	$givenCommand = "tsys -a $antenna";
    }
    if($simulateMode==0) 
    {
	system("$givenCommand");
    }	# execute the command
                          	# sleep 1 sec
    # if simulation, then increment time as given by integrate command.
    if($simulateMode==1) 
    {
	$prevUnixTime=$unixTime;
	if($givenCommand=~/integrate/) 
	{
	    ($intcommand,$tors,$timeorscans)=split(' ',$givenCommand);
	    if($tors =~/t/) 
	    {
		$integrationTime=$timeorscans;
	    }
	    if($tors =~/s/) 
	    {
		$numberOfScans=$timeorscans;
		$totalIntegrationTime=$integrationTime*$numberOfScans;
	    }
	    $unixTime=$unixTime+$totalIntegrationTime;
	}
	if($givenCommand=~/tsys/) 
	{
	    $unixTime=$unixTime+$tsysDelay;
	}
	if($givenCommand=~/observe/) 
	{
	    $unixTime=$unixTime+$observeDelay;
	}
	if($givenCommand=~/point/) 
	{
	    @pointArgs=split(' ',$givenCommand);
	    for($iarg=0;$iarg<=$#pointArgs;$iarg++) 
	    {
		if($pointArgs[$iarg]=~/r/) {$pointRepeats=$pointArgs[$iarg+1];}
	    }
	    $unixTime=$unixTime+$pointDelay*$pointRepeats;
	}
	($print_sec,$print_min,$print_hour,$print_d,$print_mon,
	 $print_year,$wday,$yday,$isdst) = localtime($prevUnixTime);
	$print_year+=1900;
	$print_mon++;
	printf "\t%02d/%02d/%d %02d:%02d:%02d --> ",$print_mon,$print_d,
	$print_year,$print_hour,$print_min,$print_sec;
	($print_sec,$print_min,$print_hour,$print_d,$print_mon,
	 $print_year,$wday,$yday,$isdst) = localtime($unixTime);
	$print_year+=1900;
	$print_mon++;
	printf "%02d/%02d/%d %02d:%02d:%02d  ---- %s\n",$print_mon,$print_d,
	$print_year,$print_hour,$print_min,$print_sec,$givenCommand;
	  # if($givenCommand =~ /observe/) {
	  # ($observecommand,$presentsource)=split('\-s',$givenCommand);
	  # $presentElevation=checkEl($presentsource);
	  # printf " : el= %.2f deg.\n",$presentElevation;
	  # } else {print "\n";}
    } 
    else {sleep 1;} 
}

# --- get LST in hours ---
# usage: LST(); or LST(1);
# The return value of this subroutine is LST in hours.
# The time is taken from the Reflective Memory. However, when in $simulatemode,
# then the return value is simulated LST in hours.
# It can print the current LST if used as LST(1);
sub LST 
{
    my ($LST);
    if($simulateMode) {$LST=simlst();}
    else {$LST= `value -a $sma[0] -v lst_hours`;}
    chomp($LST);
    #if (not $simulateMode and $_[0])  {printf("LST [hr]= %6.2f\n",$LST);}
    printf("LST [hr]= %6.2f\n",$LST);
    
    return $LST;
}

# --- simulate LST ------
sub simlst 
{
#$longitude = -4.76625185186; # hours (71d29'37.6s W) Haystack
    $longitude = -10.365168199815; # hours (-155.477522997222 W, pad-1) MaunaKea
    
    if($givenUTC eq "") 
    {
	$seconds=(gmtime)[0]+(gmtime)[1]*60.+(gmtime)[2]*3600.;
	$ut=$seconds/3600.;
	$d=(gmtime)[3];
	if((gmtime)[5]>=98) {$year=1900+(gmtime)[5];}
	else {$year=2000+(gmtime)[5];}

	$mn=1+(gmtime)[4]; 
# adding 1 because the array index for month goes from 0 to 11.
    }

# Using Eqn. 12.92-1, p 604 of the Green Book (Expl. Supp. to Almanac)
# for calculating JD from the given gregorian calendar
# date in terms of day number, month number and year number.
# lots of int()s have had to be inserted because  Perl 
# cannot do integer arithmetic. 

    if($givenUTC) 
    {
	if($firstTime==1) 
	{ 
	    ($mn,$d,$year,$gh,$gm)=split(' ',$givenUTC);
	    $mn=$mn-1;
	    $unixTime=timelocal(0,$gm,$gh,$d,$mn,$year);
	    $prevUnixTime=$unixTime;
#print "unixTime from given UTC: $unixTime\n";
	    $firstTime=0;
	}
	($sec,$min,$hour,$d,$mon,$year,$wday,$yday,$isdst) = localtime($unixTime);
	$mn=$mon+1;
	$year=1900+$year;
	$seconds=$sec+$min*60.+$hour*3600.;
	$ut=$seconds/3600.;
    }

    
    $term1=int((1461*int(($year+4800+int(($mn-14)/12))))/4);  
    $term2=int((367*($mn-2-12*(int(($mn-14)/12))))/12);
    $term3=int((3*int(($year+4900+int(($mn-14)/12))/100))/4);
    $JD=$term1+$term2-$term3+$d-32075;
    
    $TJD=$JD+$seconds/86400.;
    $TJDint=int($TJD);
    
    $T=($JD-2451545.0)/36525.; # definition.
    
    $epsilon0 = 21.448-46.8150 * $T - 0.00059 * $T * $T+ 0.001813 * $T * $T * $T;
#Eqn 3.222-1, p114 of the Green Book
    $epsilon0=$epsilon0/3600.+ 26./60. + 23.; #in degrees
    
    $epsilon0=$epsilon0* 0.0174534; #in radians
    
    $dnum= $JD-2451545.0;
    
    $radian=4.0*atan2(1,1)/180.;
    
    $angle1=(125.0-0.05295*$dnum)*$radian;
    $angle2=(200.9+1.97129*$dnum)*$radian;

    $delta=0.0026 * cos($angle1)+0.0002*cos($angle2);

    $epsilon=$epsilon0+$delta;

    $Tdu=$dnum/36525.; # No. of Julian centuries
    $theta=($ut*(1.002737909350795+5.9006e-11*$Tdu-5.9e-15*$Tdu*$Tdu))*3600.; # seconds
    $Tdu2=$Tdu*$Tdu;
    $Tdu3=$Tdu2*$Tdu;
    $gmst0=24110.54841+8640184.812866*$Tdu+0.093104*$Tdu2-6.2e-6*$Tdu3;
    $gmst0=$gmst0/3600.; # hours

    $frac=$gmst0/24.;
    $quot=int($frac);
    $gmst0=$gmst0-$quot*24;

    if($gmst0 lt 0.){$gmst0=$gmst0+24.;}
    $gmst=($gmst0+$theta/3600.); # hours

    $delta_psi=-0.0048*sin($angle1)-0.0004*sin($angle2);
#Eq 3.225-4, p120 (delta-psi is in degrees)

    $eqnequinox=$delta_psi*cos($epsilon*$radian); # degrees
    $eqnequinox=$eqnequinox*6.66666667e-2; # hours


    $gast=$gmst+$eqnequinox;
    $lst=$gast+$longitude;
    $frac=$lst/24.;
    $quot=int($frac);
    $lst=$lst-$quot*24;

    if($lst lt 0.){$lst=$lst+24.;}

    return $lst;
}

sub Usage()
{
    printf "Here is a list of all the options that can be used with any science script:
-a (antennas) a list of antennas that tsys will be skipped. For skipping an 
   antenna with a hotload problem
-b (b) Use receiver B for the pointing results, rather then receiver A (default)
-d (day) toggle off the accepting of ipoint results during the day (usually set 
   on)
-f (figure) used when restarting a script. It will figure out were the script 
   left off and start from there
-h (help) Prints this message, then quits
-i (ipoint) for use when any new ipoint options need to be added. Put in quotes 
   Default: -i 10 -r 3 -8 -c 2.5 -w -n -Q
-k (k) it adds the -k option to the ipoints take during the script
-m (mosaic) skips the tsys after each target, for use with scripts that don't 
   use the normal mosaic mode
-n (night) toggle on the accepting of ipoint results during the night (usually 
   off)
-p (pointing) opt out of the automatic pointing
-r (restart) start the script, skipping the initial bandpass and flux
-s (simulate) starts running the script in simulate mode
-t (time) specify a start time for the simulation (only works with -s)
-v (value) specify a minimum flux in Jy for the pointing calibrator (default is 
   1 Jy)

Additionally, there are a few variables that can be added to the science script 
to change a few of the normal behaviors.
\$pointingcal can be used to specify a calibrator for pointing, rather then use 
the searching program.
\$nightpointingtime can be used to change the cadence of night time pointing 
from 3 hours (specified in seconds).
\$daypointingtime can be used to change the cadence of night time pointing from 
1 hour (specified in seconds).
\$pants has two antennas that are used as the pointing calibration antennas, they
should be antennas in the project.
\$maxloops can be used to stop a script after a certain number of loops.
\$nightflux=\"source\" and \$nnightflux=\"#\" can be used to observe the specified
calibrator after night pointing.
\$timeflux=\"source\", \$ntimeflux=\"#\", and \$timeforflux=\"LST time\" they can 
be used to observe the specified source at the specified LST time.\n";
}

