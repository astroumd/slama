# SMA simulator

Currently runs in perl (see /global/rrao/sma_obs_perl) but in here you can also
find some claude attempts to convert to python. 

## SMA machines

Sim only tested on "oddjob".

## External needs

- calfind (in: current repo)   - oddly enough not referenced in python code yet
- lookup (in: /common/bin)     - stub in the repo that always returns "180 45 90"

## Example

Ideally we add SMAOP to the PATH environment

      SMAOP=/global/rrao/sma_obs_perl
      export PATH=$SMAOP:$PATH
      
      perl -I$SMAOP my_sma_obs_script.pl -s -t "12 21 2024 04 00"
      > ./my_sma_obs_script.run
      perl -I$SMAOP timetable.pl my_sma_obs_script.run            > ./my_sma_obs_script.tt

Note that the regression was done May 13, 2026, and there appears to be some skew.
0.0001 deg in reported elevation)

The python code would run as follows:

      ./my_sma_obs_script.py --simulate --time  "12 21 2024 14 00" > test.run
      ./timetable.py test.run      

Note that the python script need HST, not UTC. This is a bug to be resolved. Another bug is
that no pointing is done.


### Example Scripts

* my_sma_obs_script.pl - original
* my_sma_obs_script.py - converted
* GBT.pl - original
* GBT.py - converted


## Some claude testing of pl->py

sma.py:    Core library -- State dataclass, initialize,
	   check_ant, check_elevation, run_command,
	   get_lst, simulate_lst, etc.

sma_add:   Observing loops -- obs_loop, do_flux, do_pass,
	   pointing logic, elevation checks

timetable: Standalone log parser / timetable printer


### Key idiomatic changes
                                                                                                      
  Global variables -- State dataclass
  All ~50 Perl globals become fields of a single State object that is passed explicitly. This makes   
  data flow visible and testable.                                                                     
                                                                                                      
  Symbolic references -- dict                                                                          
  The Perl pattern of passing variable names (ObsLoop(targ0, cal0)) and dereferencing them (${$name})
  is replaced with a plain SOURCES dict. obs_loop(["cal0", "targ0"], SOURCES, state) reads naturally. 
  
  GetOptions -- argparse                                                                               
  Full help text, type checking, and --long-form flags come for free.
                                                                                                      
  Backticks / system() -- subprocess.run()                                                             
  Explicit, with capture_output=True where the output is needed.                                      
                                                                                                      
  Month name ladder -- dict                                                                            
  The 24-if month-to-number chain becomes a one-liner dict.
                                                                                                      
  Time::Local / localtime -- datetime / calendar.timegm                                                
  Standard library throughout; the LST maths is a direct port of the astronomy formulas.

### Simulation mode

Working correctly:

  - Initializes, detects non-SMA machine, enters simulate mode automatically                          
  - Flux calibration for Neptune (20 scans) and Uranus (20 scans) completes                           
  - Main observing loop runs cal0 -> cal1 -> targ0 with proper observe/tsys/integrate sequence        
  - Simulated clock advances correctly with each command                                              
  - Final gain calibration fires at the end of each loop                                              
  - Exits cleanly after hitting max_loops = 200                                                       
  - Prints "Congratulations!" at the end

### Final warning

Please remember to stow the antennas safely if you are leaving.


## External programs

The simulator depends on two programs: `calfind` and `lookup`.

### 1. calfind

```
calfind --help
Usage: calfind [OPTIONS]

Find a suitable calibrator around an observed position.

  -a, --azimuth=<deg>     Azimuth of the current source.
  -e, --elevation=<deg>   Elevation of the current source 
  -m, --minEl=<deg>       Minimum elevation for the returned calibrator
                          (default: 30)
  -M, --maxEl=<deg>       Maximum elevation for the returned calibrator
                          (default: 80)
  -r, --ra=<hour>         R.A. (if equatorial)
  -d, --dec=<deg>         Declination (if equatorial)
  -f, --minflux=<Jy>      Minimum flux for the calibrator (default: 0.5)
  -h, --hifreq            Observation is at 345 GHz (versus 230 GHz)
  -L, --lst=<hour>        Specify the LST (<= 0: now)
  -v, --debug             Enable debugging mode

Help options
  -?, --help              Show this help message
  --usage                 Display brief usage message
```

### 2. lookup

```
lookup --help
Usage: lookup [OPTIONS] [source-name]

Looks up current Az/El position and other information on catalog or ephemeris sources.

  -s, --source=<string>               Source name. It can be specified without
                                      -s also.
  -r, --ra=<hours|hh:mm:ss.sss>       Right ascension coordinate
  -d, --dec=<deg|+dd:mm:ss.sss>       Declination coordinate
  -e, --epoch=<year>                  Epoch of input coordinates 1950 or 2000.
  -p, --pmra=<mas/yr>                 Proper motion in RA.
  -q, --pmdec=<mas/yr>                Proper motion in declination.
  -R, --RAOff=<arcsec>                RA offset.
  -D, --DecOff=<arcsec>               Dec offset.
  -l, --elevlim=<deg>                 Elevation limit (implies -w; default:
                                      20).
  -v, --velocity=<km/s>               Radial velocity
  -t, --time=<dd MMM YYYY hh:mm:ss>   Date & time, e.g. "14 Dec 2010 12:40:15"
  -o, --optical                       Optical refraction correction (instead
                                      of radio).
  -c, --reconfigure                   Reload catalogs and ephemeris data.
  -P, --properties                    Print source properties.
  -T, --track                         Print current track segment information.
  -F, --flux=<GHz>                    Print estimated brightness at given
                                      frequency.
  -V, --verbose                       Produce verbose output.
  -w, --when                          Print rise/set/transit times
  -S, --server=<hostname|IP>          Specify an alternative lookup server
                                      address.

Help options
  -?, --help                          Show this help message
  --usage                             Display brief usage message
```

### 3. value

Not used in simulation mode. Finds legacy reflective memory data


### 4. getAntList

Not used in simulation mode. 



### Compiling calfind and lookup off-site

Worked, after some hack re. casting const strings, but RPC tunnel not solved yet.
