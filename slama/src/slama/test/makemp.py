
from slama.monitor import MonitorPoint, MonitorPointUpdater, MonitorPointWriter
from smax import SmaxRedisClient

smax_client = SmaxRedisClient('localhost',redis_port=6380)
mp = MonitorPoint("mytestpoint",value=None,units="K",table="weather:forecast:gfs", key="test_temp")

mpw = MonitorPointWriter(mp,smax_client)


