import os
import socket
import time
import redis
import psutil


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
    'cat ../ansible/environments/distributed/hosts | grep "invoker" | grep "{}" | awk {}'.format(invoker_ip, "{'print $1'}")
).read().replace('\n', '')

# Monitor 
while True:
    time.sleep(0.2)
    invoker_dict = {}

    # Alive container number
    n_container = os.popen('docker ps | grep "guest" | wc -l').read().replace('\n', '')
    invoker_dict["n_container"] = n_container

    # CPU and memory utilization
    memory_util = psutil.virtual_memory().percent
    cpu_util = psutil.cpu_percent()
    invoker_dict["memory_util"] = memory_util
    invoker_dict["cpu_util"] = cpu_util

    # Write into Redis
    r.hmset(invoker, invoker_dict)



    

