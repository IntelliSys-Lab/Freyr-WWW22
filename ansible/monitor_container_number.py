import os
import sys
import socket
import time
import redis


# Connect to redis pool
redis_host = "192.168.196.213"
redis_port = 6379
redis_password = "openwhisk"

pool = redis.ConnectionPool(host=redis_host, port=redis_port, password=redis_password, decode_responses=True)
r = redis.Redis(connection_pool=pool)

# Get invoker name
invoker_hostname = socket.gethostname()
invoker_ip = socket.gethostbyname(invoker_hostname)
invoker = os.popen(
    'cat environments/distributed/hosts | grep "invoker" | grep "{}" | awk {}'.format(invoker_ip, "{'print $1'}")
).read().replace('\n', '')

# Monitor alive container number
while True:
    time.sleep(0.5)
    n_container = os.popen('docker ps | grep "guest" | wc -l').read()
    r.hset(invoker, "n_container", n_container)
    

