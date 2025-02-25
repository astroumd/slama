
# URLs that we'll need

URL1  = git@github.com:Smithsonian/SMA-Software.git
URL2  = git@github.com:Smithsonian/smax-python.git
URL3  = git@github.com:Smithsonian/redisx.git
URL4  = git@github.com:Smithsonian/SuperNOVAS.git
URL5  = git@github.com:Smithsonian/supernovas-rpm-spec.git
URL6  = git@github.com:valkey-io/valkey.git
URL7  = git@github.com:Smithsonian/xchange.git

GIT_DIRS = SMA-Software smax-python SuperNOVAS xchange

# redisx smax

.PHONY:  help install 

install:
	@echo "No notes yet"
	@echo ""
	@echo "Other useful targets:"
	@echo "    make pull                  update all git repos"
	@echo "    make status                view git status in all repos"
	@echo "    make update                recompile updated repos"
	@echo "    make help                  a full list of all documented help"
	@echo "For a full list, type:  'make help'"
	@echo ""

help:
## help:      This Help
help : Makefile
	@sed -n 's/^##//p' $<


## git:       Get all git repos for this install
git:  $(GIT_DIRS)

## pull:      Update all git repos
pull:
	@echo -n "slama: "; git pull
	-@for dir in $(GIT_DIRS); do\
	(echo -n "$$dir: " ;cd $$dir; git pull); done
	@echo Last pull: `date` >> git.log

status:
	@echo -n "slama: "; git status -uno
	-@for dir in $(GIT_DIRS); do\
	(echo -n "$$dir: " ;cd $$dir; git status -uno); done

branch:
	@echo -n "slama: "; git branch --show-current
	-@for dir in $(GIT_DIRS); do\
	(echo -n "$$dir: " ;cd $$dir; git branch --show-current); done

# all git targets

SMA-Software:
	git clone $(URL1)

smax-python:
	git clone $(URL2)

redisx:
	git clone $(URL3)

SuperNOVAS:
	git clone $(URL4)

xchange:
	git clone $(URL7)
