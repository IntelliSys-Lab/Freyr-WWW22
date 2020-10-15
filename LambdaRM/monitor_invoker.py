import socket
import time
import redis
import psutil
import docker

from utils import run_cmd


# Connect to Redis pool
redis_host = "192.168.196.213"
redis_port = 6379
redis_password = "openwhisk"

pool = redis.ConnectionPool(host=redis_host, port=redis_port, password=redis_password, decode_responses=True)
r = redis.Redis(connection_pool=pool)

# Connect to Docker 
docker_client = docker.from_env()

# Get invoker name
invoker_hostname = socket.gethostname()
invoker_ip = socket.gethostbyname(invoker_hostname)
invoker = run_cmd('cat ../ansible/environments/distributed/hosts | grep "invoker" | grep "{}" | awk {}'.format(invoker_ip, "{'print $1'}"))

# Monitor 
while True:
    time.sleep(0.2)
    invoker_dict = {}

    # Total cpu-shares
    current_cpu_shares = 0
    for container in docker_client.api.containers(filters={"name": "guest"}):
        id = container["Id"]
        cpu_share = docker_client.api.inspect_container(id)["HostConfig"]["CpuShares"]
        current_cpu_shares = current_cpu_shares + cpu_share

    invoker_dict["current_cpu_shares"] = current_cpu_shares

    # CPU and memory utilization
    memory_util = psutil.virtual_memory().percent
    cpu_util = psutil.cpu_percent()
    invoker_dict["memory_util"] = memory_util
    invoker_dict["cpu_util"] = cpu_util

    # Write into Redis
    r.hmset(invoker, invoker_dict)



    

