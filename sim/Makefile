
# URLs that are of interest. Most of these are not actually needed

.PHONY:  help install

DEBUG = --debug

## help:     this help
help: Makefile
	@sed -n 's/^##//p' $<

## test1:    run the python test
test1:
	./my_sma_obs_script.py --simulate --time  "12 21 2024 14 00" $(DEBUG) > test1.run
	./timetable.py test1.run                                     $(DEBUG) > test1.tt
	@echo "Compare test1 files with corresponding test0 files"

## test0:    run the perl test
test0:
	perl -I$(SMAOP) my_sma_obs_script.pl -s -t "12 21 2024 04 00" > test0.run
	perl -I$(SMAOP) timetable.pl test0.run                        > test0.tt
	@echo "Compare test0 files with corresponding my_sma_obs_script files"

## time:     display current unix time and current local time
time:
	date +"%s - %c"
