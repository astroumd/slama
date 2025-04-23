# installation

Order of steps is important

## 0. grab source from github

```
     git clone https://github.com/astroumd/slama
     cd slama
     git checkout autoconf   [for now]
```

## 1. configure

Since this repo has just been placed here, nothing else is in place.

```
     ./configure
     chmod +x smax-init.sh valkey-init.sh
     make build1
```
will report some env.var, create some shell startup files.

## 2. python

If you don't have a python environment, or a way to make a virtual environment,
the `install_anaconda3`, with optionally wget=wgetc if you have the caching version
of wget. Otherwise just this:

```
     make build2
```


###  uv ?

Don't use this yet.  Just noting for kicks, maybe we'll learn to use
the new `uv` hype, or even `hatch`

```
pip install uv -U
uv init slama
uv add smax-python
uv add astropy
uv python install 3.10
uv add smax-python
```

## 3. load environment

This is normally the entry point for any shell that needs to be SLAMA:

```
     source slama_start.sh
```

and can be started from any directory

## 4. get the other git directories we (may) need

```
     make git
```

## 5. build things we need (note we use valkey now, not redis)

```
     make build3
     make build4
     make build5
     make build6
```

## 6. dryrun

Start valkey, this also runs smax-init

```
     valkey-init.sh
      ...
      INFO: Valkey is online. Loading SMA-X helper scripts...
      > Loading HGetWithMeta. New? (integer) 0
      ...
      > Loading DelKey. New? (integer) 1

```

and testing smax-python:

```
      pytest smax-python/tests/test_smax_data_types.py
      pytest smax-python/tests/test_smax_redis_client.py          [doesn't work yet]

```


### Comments

- valkey-init.sh starts up valkey-server_sma on port 6380 - no protection against multiple other than it failing because it's already running



```
1206559:M 23 Apr 2025 08:37:48.660 * Saving the final RDB snapshot before exiting.
1206559:M 23 Apr 2025 08:37:48.751 * DB saved on disk
1206559:M 23 Apr 2025 08:37:48.751 * Removing the pid file.
1206559:M 23 Apr 2025 08:37:48.751 # Valkey is now ready to exit, bye bye...
```
it should say which file it used to save on disk.  mine never ended.
