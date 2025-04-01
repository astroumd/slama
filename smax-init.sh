#!/bin/bash
#
# Loads the SMA-X scripts into Redis, and stores their hash values under
# 'scripts'
#
# Author: Attila Kovacs
# Version: 2022 March 1
#
# This script, along with the SMA-X lua scripts, should be stored under
# /usr/share/smax on the Redis server machine, along with the
# 'smax-scripts.service' file, which should be sym-linked to
# /lib/systemd/system so that the scripts are automatically re-loaded upon
# Redis restarts.

LUA="${SLAMA}/lua"
REDIS_NAME="Valkey"
REDIS_CLI="valkey-cli_sma"
REDIS_SERVER="valkey-server_sma"
REDIS_PORT="6380"

if [ "$1" != "" ] ; then 
  LUA="$1"
fi

# Try for up to 5 seconds to get a response from redis...
for i in {1..5}; do
  result=`${REDIS_CLI} -p ${REDIS_PORT} ping`
  if [ "$result" == "PONG" ] ; then
    break
  fi
  if [ $i -eq 5 ]; then
    echo "ERROR! Could not connect to Redis. SMA-X scripts not loaded."
    exit 1
  fi
  sleep 1
done

echo "INFO: ${REDIS_NAME} is online. Loading SMA-X helper scripts..."

load_script() {
  NAME=$1
  echo -n "> Loading $NAME. New? "
  SCRIPT=`cat $LUA/$NAME.lua`
  SHA1=`${REDIS_CLI} -p ${REDIS_PORT} script load "$SCRIPT"`
  ${REDIS_CLI}  -p ${REDIS_PORT} hset scripts $NAME $SHA1
  
  if [ $? -ne 0 ] ; then
    echo "ERROR! loading $NAME. Goodbye!"
    exit 1
  fi
}


load_script HGetWithMeta
load_script HSetWithMeta
load_script HMGetWithMeta
load_script HMSetWithMeta
load_script GetStruct
load_script DSMGetTable
load_script DelKey

exit 0


