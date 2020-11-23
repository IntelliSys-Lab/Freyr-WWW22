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
    # Push 
    function_memory = random.randint(128, 512)
    redis_client.rpush(function_list, function_memory)
    print("CONTROLLER - push function memory: {}".format(function_memory))

    # Pop
    invoker_i = None
    while True:
        message = redis_client.blpop(invoker_list, 1)
        if message is not None:
            invoker_i = int(message[1])
            print("CONTROLLER - pop invoker: {}".format(invoker_i))
            break
    
    i = i + 1
