# use this to test basic functioning of redis I/O
import numpy as np
from smax import SmaxRedisClient

smax_client = SmaxRedisClient("localhost",redis_port=6380) # Replace localhost with redis hostname or IP.
value = float(np.random.rand(1)[0])
table = "weather:forecast:gfs"
key = "test_tau"
smax_client.smax_share(table, key, value)
result = smax_client.smax_pull(table, key)
print(type(result))
print(f"Input {table}:{key}={value}, fetched result {result.data} of type {result.type}")

