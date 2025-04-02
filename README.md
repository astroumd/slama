# slama
bootstrap repo for SMA repos

## repos:

* https://github.com/Smithsonian/SMA-Software

* https://github.com/Smithsonian/smax-python

* https://github.com/Smithsonian/smax-server

### other

* https://github.com/Smithsonian/redisx

* https://github.com/Smithsonian/SuperNOVAS

* https://github.com/Smithsonian/supernovas-rpm-spec

* QL reduction pipeline

* pyuvdata

* grafana

* compass (matlab based)

* polaris (matlab based)

* CASA

### related

* https://github.com/valkey-io/valkey


## Configure

Configure should

* create slama_start.sh

* create and set global environment variables like REDIS_NAME, REDIS_CLI, RESID_SERVER, REDIS_PORT, LUA 
    - maybe add $REDIS_DBFILE to the list (sma-shared-variables.rdb)

* update data/valkey_sma.conf to use $REDIS_PORT, REDIS_DBFILE

* create smax-init.sh and valkey-init.sh from *.in 


## Makefile

make install should
    
 * install valkey*_sma in ${SLAMA}/bin
 
* install valkey-init.sh and smax-init.sh in $SLAMA/bin
 
* copy smax-server/lua to ${SLAMA}/lua

* update data/valkey_sma.conf with REDIS_PORT, REDIS_DBFILE(?
