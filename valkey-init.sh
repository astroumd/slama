#!/bin/bash
# valkey.conf cannot have a path in database file name, must be in $cwd
REDIS_PORT=6380
cp ${SLAMA}/data/sma-shared-variables.rdb .
${SLAMA}/bin/valkey-server_sma ${SLAMA}/data/valkey_sma.conf --port ${REDIS_PORT} &
sleep 3 # wait till server is loaded
${SLAMA}/bin/smax-init.sh
