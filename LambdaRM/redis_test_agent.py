import redis
import random

from utils import run_cmd


# Set up Redis client
redis_host = "192.168.196.213"
redis_port = 6379
redis_password = "openwhisk"

pool = redis.ConnectionPool(
    host=redis_host, 
    port=redis_port, 
    password=redis_password, 
    decode_responses=True
)
redis_client = redis.Redis(connection_pool=pool)

function_list = "function_to_schedule" 
invoker_list = "invoker_to_choose" 

i = 0
while i < 10:
    # Pop
    function_memory = None
    while True:
        message = redis_client.blpop(function_list)
        if message is not None:
            function_memory = int(message[1])
            print("AGENT - pop function memory: {}".format(function_memory))
            break

    # Push 
    invoker_i = random.randint(0, 1)
    redis_client.rpush(invoker_list, invoker_i)
    print("AGENT - push invoker: {}".format(invoker_i))

    i = i + 1
