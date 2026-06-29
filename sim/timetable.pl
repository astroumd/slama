#! /usr/bin/perl 
#use warnings;

$run = $ARGV[0];
#print "$run\n";
open(RUN, $run) || die "Can't open $run: $!\n";

$/ = "\n-";
$= = 1000;		#arbitrarily large to keep page break form repeating
$LST = "-----"; 	#placeholder until get_LST written
$chunk = 0;
$current_time = '';

# Ram -- 6 Feb 2024
# Added below to check for missing number of scans
my $cmd = qq{sed -n '/^The\\scurrent\\ssource/p' $run | sort | uniq};
system $cmd;

while (my $record = <RUN>) {
	my $observation = ($record =~ / observe -s /m);
	my $pointing = ($record =~ / point on/);
	my $transit = ($record =~ / transit /); 
	my $pointed = 0;

	while ($record =~ /([01]?[0-9]|2[0-3]):[0-5][0-9](:[0-5][0-9])?/gm) {
		$current_time = $&;
	}

	if (!$chunk) {
		get_header($record);
	}

	if ($transit && !$observation) {
		record_transit($record);
	}

	if ($pointing) { 
		record_pointing($record);
		$pointed = 1;
	}

	if ($observation && !$transit) {
		record_obs($record, $pointed);
	}
	$chunk++;
}
record_end($current_time);
print "=============================================================\n";

close(RUN);

format STDOUT_TOP = 
=============================================================
|  HST  |  UTC  |       Source       |   Type   | Elevation |
=============================================================
.

format STDOUT =
| @>>>> | @>>>> | @<<<<<<<<<<<<<<<<< | @<<<<<<< |   @<<<<   |
  $hst,   $utc,   $source,             $type,       $el 
.

#SUBROUTINES

sub get_project_info {
	my $line = $_[0];
	if ($line =~ /^project/) {
		my @words = split(/'/, $line);
		$pi = $words[1];
		$project = $words[3];
	}
}

sub get_integration {
	my $line = $_[0];
	if ($line =~ /^integrate/) {
		my @words = split(/\s+/, $line);
		$integration = $words[2];
	}
}

sub get_header {
	my $record = $_[0];
	local ($project, $pi, $integration);

	my @lines = split(/\n/, $record);
	foreach $line (@lines) {
		get_project_info($line);
		get_integration($line);
	}
	print "\n$project\tPI: $pi\tInt. time: $integration"."s\n";
}

sub fix_utc {
	my $utc = $_[0];
	if ($utc =~ /\b([0-9]+):([0-9]){1}\b/) {
		$utc = $1 . ':0' . $2;
	} else {
		return $utc;
	}
}	 

sub utc_to_hst {
	my ($hour, $minute) = split(/:/, $_[0]);

	$hour -= 10;
	$hour += 24 if ($hour < 0);
	$hour = "00" if ($hour == 0);

	$hst = $hour . ':' . $minute;
}

sub get_time {
	my $line = $_[0];
	if ($line =~ /The lookup time/) {
		my @words = split(/\s+/, $line);
		$utc = $words[7];
		$utc = fix_utc($utc);
		$hst = utc_to_hst($utc);
	}
}

sub get_elevation {
	my ($line, $pointed, $mosaic) =@_;
	if ($line =~ / el/) {
		my @words = split(/\s+/, $line); 
		if ($mosaic) {
			$el = $words[5];
		} else {
			$el = $words[3];
		}
	}
	if ($pointed) {
		$el = "N/A"; 
	}
}

sub get_other_source {
	#works for pointing and transit sources, takes from el line
	my $line = $_[0];
	if ($line =~ / el/) {
		my @words = split(/\s+/, $line);
		$source = $words[0];
	}
}

sub get_obs_source {
	my ($line, $mosaic) = @_;
	my @words = split(/\s+/, $line);

	$source = $words[2];
	$type = "Target";
	
	if ($line =~ /-t/) {
		$type = $words[4];
	}
	if ($line =~ /-n/) {
		if ($mosaic) {
			$source = $words[12];
		} else {
			$source = $words[4];
			$type = $words[6];
		}
	}
}

sub record_obs {
	my ($record, $pointed) = @_;
	my $obs_complete = 0;
	my $mosaic = ($record =~ /Mosaic/mg);

	local ($hst, $utc, $source, $type, $el);

	my @lines = split(/\n/, $record);
	foreach $line (@lines) {
		next if $obs_complete;
		get_time($line);
		get_elevation($line, $pointed, $mosaic);
	 	if ($line =~ /^observe -s/) {
			get_obs_source($line, $mosaic);	
			$obs_complete++;
		}
	}
	write(STDOUT);
	$obs_complete = 0;
}

sub record_pointing {
	my $record = $_[0];

	local ($hst, $utc, $source, $type, $el);
	$type = "Pointing";

	my @lines = split(/\n/, $record);
	get_other_source($lines[4]);
	get_time($lines[3]);
	get_elevation($lines[4], 0, 0);

	if ($record =~ /waveplates/) {
		get_time($lines[4]);
		get_elevation($lines[5], 0, 0);
	}
	write(STDOUT);
}

sub record_transit {
	my $record = $_[0];

	local ($hst, $utc, $el, $source, $type);
	$type = "Transit";

	my @lines = split(/\n/, $record);
	foreach $line (@lines) {
		get_other_source($line);
		get_elevation($line, 0, 0);
		get_time($line);
	}
	write(STDOUT);
}
 
sub record_end {
	my $end_time = $_[0];

	local ($hst, $utc, $source, $el, $type);

	$utc = $end_time;
	$hst = utc_to_hst($utc);
	$source = "End of Observation";
	$el = '';
	$type = '';

	write(STDOUT);
} 
