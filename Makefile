
# URLs that are of interest. Most of these are not actually needed

_G1_ = https://github.com/
_G2_ = git@github.com:

URL1  = git@github.com:Smithsonian/SMA-Software.git
URL2  = git@github.com:Smithsonian/smax-python.git
URL3  = git@github.com:Smithsonian/redisx.git
URL4  = git@github.com:Smithsonian/SuperNOVAS.git
URL5  = git@github.com:Smithsonian/supernovas-rpm-spec.git
URL6  = git@github.com:Smithsonian/smax-postgres.git
URL7  = git@github.com:Smithsonian/xchange.git
URL8  = git@github.com:Smithsonian/smax-server.git
URL9  = git@github.com:Smithsonian/smax-clib.git
URL10 = git@github.com:Smithsonian/smax-json.git
URL11 = git@github.com:valkey-io/valkey.git
URL12 = git@github.com:redis/hiredis.git

# git software directories we may build here
GIT_DIRS = git-SMA-Software git-smax-python git-redisx git-SuperNOVAS git-valkey git-xchange git-smax-server git-valkey

# redisx smax

.PHONY:  help install 

install:
	@echo "See INSTALL.md for installation steps."
	@echo ""
	@echo "Other useful targets:"
	@echo "    make pull                  update all git repos"
	@echo "    make status                view git status in all repos"
	@echo "    make update                recompile updated repos"
	@echo "    make help                  a full list of all documented help"
	@echo "For a full list, type:  'make help'"
	@echo ""

##
# Install target should be:
# configure
# make setup
# make valkey
# make anaconda

setup:
	mkdir -p bin lua
	chmod +x smax-init.sh valkey-init.sh

anaconda: anaconda3
	./install_anaconda3

install-valkey: git-valkey
	(cd valkey; make -j PROG_SUFFIX="_sma" PREFIX=$(SLAMA) install)

valkey: install-valkey
	(cd bin; ln -sf ../valkey-init.sh ; ln -sf ../smax-init.sh)

# this is kind of ridiculous just to get the lua files.
lua:	git-smax-server lua
	cp smax-server/lua/*.lua lua

smax-python: git-smax-python
	pip install -e smax-python

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

git-SMA-Software:
	git clone $(URL1)

git-smax-python:
	git clone $(URL2)

git-redisx:
	git clone $(URL3)

git-SuperNOVAS:
	git clone $(URL4)

git-xchange:
	git clone $(URL7)

git-smax-server:
	git clone $(URL8)

git-smax-clib:
	git clone $(URL9)

git-smax-json:
	git clone $(URL10)

git-valkey:
	git clone $(URL11)

git-hiredis:
	git clone $(URL12)
