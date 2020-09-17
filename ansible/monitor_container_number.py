import os
import sys
import socket
import time
import redis


# Connect to redis pool
host = "192.168.196.213"
port = 6379
password = "openwhisk"

pool = redis.ConnectionPool(host=host, port=port, password=password, decode_responses=True)
r = redis.Redis(connection_pool=pool)

invoker_hostname = socket.gethostname()
invoker_ip = socket.gethostbyname(invoker_hostname)

# Monitor alive container number
while True:
    time.sleep(0.5)
    n_container = os.popen('docker ps | grep "guest" | wc -l').read()
    r.hset(invoker_ip, "n_container", n_container)
    

