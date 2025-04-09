# installation

Order of steps is important

## 1. configure

Since this repo has just been placed here, nothing else is in place.

```
     ./configure
     make build1
```
will report some env.var, create some shell startup files.

## 2. python

If you don't have a python environment, or a way to make a virtual environment,
the `install_anaconda`, with optionally wget=wgetc if you have the caching version
of wget.

###  uv ?

```
pip install uv -U
uv init slama
uv add smax-python
uv add astropy
uv python install 3.10
uv add smax-python
```

## 3. load environment

This is normally the entry point for any shell that needs to be SLAMA

