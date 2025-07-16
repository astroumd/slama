# slama python package
=======
This will be a package that can interact with smax-server in a CARMA-like monitor system.


Install
--------

in the $SLAMA directory

```pip install -e slama```  (anaconda)

or 

```uv pip install -e slama``` (uv)

or

```hatch shell``` (hatch)

Then try a basic test:

```
cd src/slama
uv run test_smax.py
```

This should write a random float to "weather:forecast:gfs:test_tau" and read it back.

Monitor Points
--------------------

The MonitorPoint, MonitorPointUpdater,and MonitorPointWriter classes are in monitor.py

Plotting
-----------

MonitorPlot class in plot.py and basic test in test_plot.py.   

```
uv run test_plot.py
```
will open an updating plot.  In another ipython window run
```
from slama.monitor import MonitorPoint, MonitorPointUpdater, MonitorPointWriter
from smax import SmaxRedisClient

smax_client = SmaxRedisClient('localhost',redis_port=6380)
mp = MonitorPoint("mytestpoint",value=None,units="K",table="weather:forecast:gfs", key="test_temp")
mpw = MonitorPointWriter(mp,smax_client)

mpw.write(a value)
mp.write(another value)
etc

```
and watch the plot update!

