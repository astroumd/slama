# installation

Order of steps is important

## 0. grab source from github

```
     git clone https://github.com/astroumd/slama
     cd slama
     # git checkout autoconf   [for now, soon can be skipped]
```



## 1. configure

This is to set up the environment needed for the local valkey db.

```
     ./configure
     make setup
```
will report some env.var, create some shell startup files.  

## 2. load environment

This is normally the entry point for any shell that needs to be using SLAMA:

```
     source slama_start.sh (or csh)
```

## If you do not need to run your own valkey database, skip to step 4. But we recommend you install a local copy here.

## 3. Install valkey
This will download and install valkey and copy some init scripts to `bin`. It will also create aliases with sma specific names to distinguish from the system valkey,  e.g. ``valkey-cli_sma, valkey-server_sma``, etc.

```
    make valkey
```

## 4. Optionally install a local python

If you want a python environment completely distinct from whatever other python installation you 
have, this step will download and install anaconda.  
```
     make anaconda
```
For `install_anaconda3` target you can optioall add `wget=wgetc` if you have the caching version
of wget, or even `wget=curl` will work.  

## 5.  Install uv

```
pip install uv -U
```

## 5. Install slama modules

```
    cd slama
    uv sync
    uv pip install -e .
```

## 6. dryrun

Start valkey, this also runs smax-init. You can check port 6380, or check `valkey` in your process table

```
     valkey-init.sh
       ...
       INFO: Valkey is online. Loading SMA-X helper scripts...
       > Loading HGetWithMeta. New? (integer) 0
       ...
       > Loading DelKey. New? (integer) 1
```
Check that valkey is up and running on the correct port
```
     valkey-cli_sma -p 6380 ping
       PONG  
```

## 7. Running the monitor and display 

Follow slama/README.md


### Comments

- valkey-init.sh starts up valkey-server_sma on port 6380 - no protection against multiple other than
  it failing because it's already running



```
1206559:M 23 Apr 2025 08:37:48.660 * Saving the final RDB snapshot before exiting.
1206559:M 23 Apr 2025 08:37:48.751 * DB saved on disk
1206559:M 23 Apr 2025 08:37:48.751 * Removing the pid file.
1206559:M 23 Apr 2025 08:37:48.751 # Valkey is now ready to exit, bye bye...
```
it should say which file it used to save on disk.  mine never ended.

- valkey-cli_sma -p 6380

this will use another port, but there's no way to use another rdb file?  The command

```
     valkey-cli_sma -p 6380 --rdb junk.rdb
```	   
simply creates a new rdb file from the sma-shared-variables.rdb

- getting keyval can be done

```
     valkey-cli_sma -p 6380 hget weather:forecast:gfs test_temp

```
but to get all the meta-data, it's better to use `smaxValue` from the clib 
