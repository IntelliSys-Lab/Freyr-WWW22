import time
import subprocess
import multiprocessing
import numpy as np
import copy as cp
import json
from params import WSK_CLI


#
# Function utilities
# 

def run_cmd(cmd):
    pong = subprocess.Popen(
        cmd,
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    result = pong.stdout.read().decode().replace('\n', '')

    return result

#
# Class utilities
#

class Function():
    """
    Function used by LambdaRM
    """
    
    def __init__(self, params):
        self.params = params
        self.function_id = self.params.function_id

        self.request_history = []
        self.resource_adjust_direction = [0, 0] # [cpu, memory]
    
    def set_function(self, cpu=2, memory=2):
        self.cpu = cpu
        self.memory = memory

    def set_invoke_params(self, params):
        self.params.invoke_params = params

    def put_request(self, request):
        self.request_history.append(request)

    def get_function_id(self):
        return self.function_id

    def get_request_history(self):
        return self.request_history

    def get_cpu(self):
        return self.cpu

    def get_memory(self):
        return self.memory

    def get_avg_interval(self, system_runtime):
        if system_runtime == 0:
            avg_interval = 0
        else:
            avg_interval = len(self.request_history) / system_runtime
        
        return avg_interval

    def get_avg_completion_time(self):
        request_num = 0
        total_completion_time = 0

        for request in self.request_history:
            if request.get_is_done() is True and request.get_is_timeout() is False:
                request_num = request_num + 1
                total_completion_time = total_completion_time + request.get_completion_time()
        
        if request_num == 0:
            avg_completion_time = 0
        else:
            avg_completion_time = total_completion_time / request_num

        return avg_completion_time
    
    def get_is_cold_start(self):
        if len(self.request_history) == 0:
            is_cold_start = True
        else:
            is_cold_start = self.request_history[-1].get_is_cold_start()

        if is_cold_start is True:
            return 1
        else:
            return 0
    
    def set_resource_adjust(self, resource, adjust):
        # Adjust resources
        next_cpu = self.cpu
        next_memory = self.memory
        
        if resource == 0:
            if adjust == 1:
                if next_cpu < self.params.cpu_cap:
                    next_cpu = next_cpu + 1
            else:
                if next_cpu > self.params.cpu_least_hint:
                    next_cpu = next_cpu - 1
        else:
            if adjust == 1:
                if next_memory < self.params.memory_cap:
                    next_memory = next_memory + 1
            else:
                if next_memory > self.params.memory_least_hint:
                    next_memory = next_memory - 1
            
        self.set_function(next_cpu, next_memory)
        
        # Set resource adjust direction if not touched yet
        if self.resource_adjust_direction[resource] == 0:
            self.resource_adjust_direction[resource] = adjust

    def validate_resource_adjust(self, resource, adjust): 
        if resource == 0:
            if adjust == 1:
                if self.cpu == self.params.cpu_cap: # Implicit invalid action: reach cpu cap
                    return False 
            else:
                if self.cpu == self.params.cpu_least_hint: # Implicit invalid action: reach cpu least hint
                    return False 
        else:
            if adjust == 1:
                if self.memory == self.params.memory_cap: # Implicit invalid action: reach memory cap
                    return False 
            else:
                if self.memory == self.params.memory_least_hint: # Implicit invalid action: reach memory least hint
                    return False 
        
        if self.resource_adjust_direction[resource] == 0: # Not touched yet
            return True   
        else:
            if self.resource_adjust_direction[resource] == adjust: # Correct direction as usual
                return True
            else: # Implicit invalid action: wrong direction
                return False
    
    def translate_to_openwhisk(self):
        openwhisk_input = (self.cpu - 1) * 9 + self.memory
        return openwhisk_input

    # Multiprocessing
    def update_openwhisk(self, couch_client):
        couch_whisks = couch_client["whisk_distributed_whisks"]
        doc_function = couch_whisks["guest/{}".format(self.function_id)]
        doc_function["limits"]["memory"] = self.translate_to_openwhisk()
        couch_whisks.save(doc_function)

    # Multiprocessing
    def invoke_openwhisk(self, result_dict):
        if self.params.invoke_params == None:
            cmd = '{} action invoke {} | awk {}'.format(WSK_CLI, self.function_id, "{'print $6'}")
        else:
            cmd = '{} action invoke {} {} | awk {}'.format(WSK_CLI, self.function_id, self.params.invoke_params, "{'print $6'}")
        
        request_id = str(run_cmd(cmd))
        result_dict[self.function_id].append(request_id)

    def reset_resource_adjust_direction(self):
        self.resource_adjust_direction = [0, 0]

    def reset_request_history(self):
        self.request_history = []
        

class Request():
    """
    An invocation of a function
    """
    def __init__(self, function_id, request_id, invoke_time):
        self.function_id = function_id
        self.request_id = request_id
        self.is_done = False
        self.done_time = 0
        self.invoke_time = invoke_time

        self.completion_time = 0
        self.is_timeout = False
        self.is_cold_start = False

    # Multiprocessing
    def try_update(self, result_dict, system_runtime, couch_client):
        couch_activations = couch_client["whisk_distributed_activations"]
        doc_request = couch_activations.get("guest/{}".format(self.request_id))

        if doc_request is not None and len(doc_request["annotations"]) >= 5:
            result_dict[self.function_id][self.request_id]["is_done"] = True
            result_dict[self.function_id][self.request_id]["duration"] = doc_request["duration"]
            result_dict[self.function_id][self.request_id]["is_timeout"] = doc_request["annotations"][3]["value"]
            
            if len(doc_request["annotations"]) == 6:
                result_dict[self.function_id][self.request_id]["is_cold_start"] = True
            else:
                result_dict[self.function_id][self.request_id]["is_cold_start"] = False
        else:
            # Manually rule out timeout requests
            if system_runtime - self.invoke_time > 60:
                result_dict[self.function_id][self.request_id]["is_done"] = True
                result_dict[self.function_id][self.request_id]["is_timeout"] = True
            else:
                result_dict[self.function_id][self.request_id]["is_done"] = False

    def set_updates(
        self, 
        is_done, 
        done_time, 
        is_timeout, 
        completion_time=None, 
        is_cold_start=None
    ):
        self.is_done = is_done
        self.done_time = done_time
        self.is_timeout = is_timeout
        
        if is_timeout is False and completion_time is not None:
            self.completion_time = completion_time
        if is_timeout is False and is_cold_start is not None:
            self.is_cold_start = is_cold_start

    def get_function_id(self):
        return self.function_id

    def get_request_id(self):
        return self.request_id

    def get_is_done(self):
        return self.is_done

    def get_invoke_time(self):
        return self.invoke_time

    def get_done_time(self):
        return self.done_time

    def get_completion_time(self):
        return self.completion_time

    def get_is_timeout(self):
        return self.is_timeout

    def get_is_cold_start(self):
        return self.is_cold_start
        
    
class Profile():
    """
    Record settings of any functions that submitted to LambdaRM
    """
    
    def __init__(self, function_profile):
        self.function_profile = function_profile
        self.default_function_profile = function_profile
        
    def put_function(self, function):
        self.function_profile.append(function)
    
    def get_size(self):
        return len(self.function_profile)

    def get_function_profile(self):
        return self.function_profile

    def reset(self):
        self.function_profile = cp.deepcopy(self.default_function_profile)
        
        
class Timetable():
    """
    Dictate which and when functions will be invoked by LambdaRM
    """
    
    def __init__(self, timetable=[]):
        self.timetable = timetable
        self.size = len(self.timetable)
        
    def put_timestep(self, row):
        self.timetable.append(row)
        
    def get_timestep(self, timestep):
        if timestep >= len(self.timetable):
            return None
        else:
            return self.timetable[timestep]
    
    def get_size(self):
        return self.size
    

class SystemTime():
    """
    Time module for LambdaRM 
    """
    
    def __init__(self):
        self.system_up_time = time.time()
        self.system_runtime = 0
        self.system_step = 0

    def get_system_up_time(self):
        return self.system_up_time

    def get_system_runtime(self):
        return self.system_runtime

    def get_system_step(self):
        return self.system_step

    def step(self):
        current_time = time.time()
        interval = current_time - (self.system_up_time + self.system_runtime)
        self.system_runtime = current_time - self.system_up_time
        self.system_step = self.system_step + 1

        return interval

    def reset(self):
        self.system_up_time = time.time()
        self.system_runtime = 0
        self.system_step = 0