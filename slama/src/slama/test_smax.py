# use this to test basic functioning of redis I/O
import numpy as np
from smax import SmaxRedisClient

def smacallback(data):
    print(f"got {data=}")

smax_client = SmaxRedisClient("localhost",redis_port=6380) # Replace localhost with redis hostname or IP.
value = float(np.random.rand(1)[0])
table = "weather:forecast:gfs"
key = "test_tau"
smax_client.smax_share(table, key, value)
result = smax_client.smax_pull(table, key)
print(type(result))
print(f"Input {table}:{key}={value}, fetched result {result.data} of type {result.type}")



table = "weather:forecast:gfs"
key = "test_array"
smax_client.smax_subscribe(f"{table}:{key}")

# Share something, which send publish notifications automatically.
value = [0.0, 1.12345, -1.54321, 100000.12345]
smax_client.smax_share(table, key, value)

# Wait for publish notifications.
result = smax_client.smax_wait_on_any_subscribed()
print(result.data, result.type)
smax_client.smax_subscribe(f"antenna:1*")
result = smax_client.smax_wait_on_any_subscribed()
print(result.data, result.type)
print(result.__dict__)

