# SMA simulator

Currently runs in perl (see /global/rrao/sma_obs_perl) but in here you can also
find some claude attempts to convert to python. 

## SMA machines

Sim only tested on "oddjob".

## External needs

- calfind (in: current repo)   - oddly enough not referenced in python code yet
- lookup (in: /common/bin)     - needs to be compiled (see below)

they need to be compiled. See below

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

## External programs

The simulator depends on two programs: `calfind` and `lookup`.

### 1. calfind

This program needs some files in /global, but it otherwise standalone. Use `make test4` to test if it's been
properly set up:

```
      $ make test4
      calfind -r 267.25 -d 70.117
      0359+509 --  2.34 Jy, RA  3.99, Dec  51.0
      0359+509 --  2.34 Jy, RA  3.99, Dec  51.0
```
and some CLI help

```
$ calfind --help
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

This program connects via RPC to a lookup server on `hcn`. For a local compilation
both `lookup` and `lookupd` need to reside in your $PATH.   Also note the default
LOOKUP_SERVER is "lookup", so either use `-S localhost` for off-site usage, or
alias your `localhost` with `lookup` in `/etc/hosts`. 

Use `make test3` to test if it's been properly set up:

```
      $ make test3
      lookup -t "14 Dec 2010 12:40:15" -s sun
      102.397195 -56.489876 0.000000
      102.397216 -56.489765 0.000000
      lookup -t "14 Dec 2010 12:40:15" -s moon
      285.892346 -24.044227 99.411428
      285.892403 -24.044336 99.411429
      lookup -t "14 Dec 2010 12:40:15" -s mars
      106.175860 -68.953131 12.577175
      106.175843 -68.953021 12.577175
      lookup -t "14 Dec 2010 12:40:15" -r 267.25 -d 70.117
      339.448921 25.808073 129.295149
      339.448921 25.808073 129.295149

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

Worked, after some hack re. casting const strings, but RPC tunnel not solved yet. Also needs data
in /global/catalogs and for lookup there is some config files (in ~/SMA/global/configFiles/lookup)

SMAGIT=~/SMA/slama/SMA-Software


- submodules:
SuperNOVAS/
redisx/                 src/redisx.c
smax/                   src/smax-messages.c
smax-postgres/
xchange/                src/xstruct.c

(see the build/redo1 script - for now)

####   /global

At SMA a few hardcoded directories contain a number of data files needed by the ephemeris/simulation codes.

1. /global/catalogs/ : 57M
2. /global/configFiles/lookup:   (configFiles has 25M if you want everything)
3. /global/polar/ : wobble file(s)
4. /ephemeris :  various NAIF files, e.g. de440s.bsp. This directory can be large (see configFiles/lookup/spiceKernels.conf)
5. /common :  not used by off-site yet, we put lookup in our own local bin and modify $PATH via sim.rc

Currently these files are hardcoded in the software, there is no config file or environment variable to
tailor these (yet).   Best is to keep a symlink from /global and /ephemeris to something in your user space.
Normally you need root access for this.

As for /ephemeris, instructions how to get (new) NAIF files are in `SMA-Software/global/lookup/jpl/README.md`


1.  in SMA-Software/online/Linux/applications/obscon/smash :
    make
    -> calfind
    -> cp bin/x86_64/calfind  ~/SMA/slama/sim/bin

2.  in  SMA-Software/global/lookup
    make
    -> lookup, lookupd
    -> cp bin/x86_64/lookup*  ~/SMA/slama/sim/bin


On ubuntu to have `lookupd` to work, the `rpcbind` is not always installed by default, at least on ubuntu.
This installs and tests it

      
      sudo apt install rpcbind
      sudo systemctl enable --now rpcbind
      rpcinfo -p

after `lookupd` has been running, you should see port 7451 being used in `tpcinfo`. On the next reboot,
`rpcbind` will also be running again due to the `--now` flag, if it was not yet.


## Running lookup

First

```
      lookupd debug
      

rpcinfo -p localhost
rpcinfo -u <host> <program_num> <version_num>
