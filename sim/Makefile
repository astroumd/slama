
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

## test2:     script generator comparison
test2:
	./make_obs_script.py --name GRB --ra 21:01:11.22 --dec +42:13:13.7 -o test2.pl
	@echo "Compare: diff test2.pl GRB.pl"

## time:     display current unix time and current local time
time:
	date +"%s - %c"

## test3:    a few "lookup" runs
test3:
	lookup -t "14 Dec 2010 12:40:15" -s sun
	@echo "102.397216 -56.489765 0.000000"
	lookup -t "14 Dec 2010 12:40:15" -s moon
	@echo "285.892403 -24.044336 99.411429"
	lookup -t "14 Dec 2010 12:40:15" -s mars
	@echo "106.175843 -68.953021 12.577175"

## test4:    a few "calfind" runs
test4:
	calfind -r 267.25 -d 70.117
	@echo "0359+509 --  2.34 Jy, RA  3.99, Dec  51.0"
