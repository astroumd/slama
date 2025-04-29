from slama.plot import MonitorPointPlot
from slama.monitor import MonitorPointUpdater, MonitorPoint
from smax import SmaxRedisClient

mp = MonitorPoint("mytestpoint",value=None,units="K",table="weather:forecast:gfs", key="test_temp")
smax_client = SmaxRedisClient('localhost',redis_port=6380)
mpu = MonitorPointUpdater(mp,smax_client)

plot = MonitorPointPlot(mpu, interval=2)
