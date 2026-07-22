
# URLs that are of interest. Most of these are not actually needed

.PHONY:  help install

## help:     this help
help: Makefile
	@sed -n 's/^##//p' $<

## test1:    run the python test
test1:
	./my_sma_obs_script.py --simulate --time  "12 21 2024 14 00" > test1.run
	./timetable.py test.run                                      > test1.tt

## test0:    run the perl test
test0:
	perl -I$(SMAOP) my_sma_obs_script.pl -s -t "12 21 2024 04 00" > test0.run
	perl -I$(SMAOP) timetable.pl test0.run                        > test0.tt

## time:     display current unix time and current local time
time:
	date +"%s - %c"
