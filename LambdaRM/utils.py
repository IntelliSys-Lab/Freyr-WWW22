import time
import subprocess
import multiprocessing
import couchdb
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

        self.request_record = RequestRecord()
        self.resource_adjust_direction = [0, 0] # [cpu, memory]
        self.is_resource_changed = False
    
    def set_function(self, cpu=1, memory=1):
        self.cpu = cpu
        self.memory = memory

    def set_invoke_params(self, params):
        self.params.invoke_params = params

    def put_request(self, request):
        self.request_record.put_request(request)

    def get_function_id(self):
        return self.function_id

    def get_request_record(self):
        return self.request_record

    def get_cpu(self):
        return self.cpu

    def get_memory(self):
        return self.memory

    def get_is_resource_changed(self):
        return self.is_resource_changed

    def get_avg_interval(self, system_runtime):
        if system_runtime == 0:
            avg_interval = 0
        else:
            avg_interval = self.request_record.get_size() / system_runtime
        
        return avg_interval

    def get_avg_completion_time(self):
        avg_completion_time, _, _ = self.request_record.get_avg_completion_time()
        return avg_completion_time
    
    def get_is_cold_start(self):
        is_cold_start = self.request_record.get_is_cold_start()
        return is_cold_start
    
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
        
        # If either one of two resources has been changed
        if self.cpu != next_cpu or self.memory != next_memory:
            self.set_function(next_cpu, next_memory)
            self.is_resource_changed = True
        else:
            self.is_resource_changed = False

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
    def update_openwhisk(self, couch_link):
        couch_client = couchdb.Server(couch_link)
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

    def reset_request_record(self):
        self.request_record.reset()
        

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
    def try_update(self, result_dict, system_runtime, couch_link):
        couch_client = couchdb.Server(couch_link)
        couch_activations = couch_client["whisk_distributed_activations"]
        doc_request = couch_activations.get("guest/{}".format(self.request_id))

        if doc_request is not None and len(doc_request["annotations"]) >= 5:
            result_dict[self.function_id][self.request_id]["is_done"] = True
            result_dict[self.function_id][self.request_id]["duration"] = doc_request["duration"] / 1000 # Second
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


class RequestRecord():
    """
    Recording of either done or undone requests per Function
    """

    def __init__(self):
        self.total_request_record = []
        self.success_request_record = []
        self.undone_request_record = []
        self.timeout_request_record = []

    def put_request(self, request):
        self.total_request_record.append(request)

        if request.get_is_done() is False:
            self.undone_request_record.append(request)
        else:
            if request.get_is_timeout() is False:
                self.success_request_record.append(request)
            else:
                self.timeout_request_record.append(request)

    def update_request(self, done_request_list):
        for request in done_request_list:
            if request.get_is_timeout() is False:
                self.success_request_record.append(request)
            else:
                self.timeout_request_record.append(request)
            
            self.undone_request_record.remove(request)

    def get_size(self):
        total_size = len(self.total_request_record)
        return total_size

    def get_undone_size(self):
        undone_size = len(self.undone_request_record)
        return undone_size

    # Deprecated
    def get_current_timeout_size(self, system_runtime):
        current_timeout_size = 0
        for request in self.timeout_request_record:
            if request.get_done_time() == system_runtime:
                current_timeout_size = current_timeout_size + 1

        return current_timeout_size

    def get_timeout_size(self):
        timeout_size = len(self.timeout_request_record)
        return timeout_size

    def get_avg_completion_time(self):
        request_num = 0
        total_completion_time = 0

        for request in self.success_request_record:
            request_num = request_num + 1
            total_completion_time = total_completion_time + request.get_completion_time()
        
        if request_num == 0:
            avg_completion_time = 0
        else:
            avg_completion_time = total_completion_time / request_num

        return avg_completion_time, request_num, total_completion_time

    def get_is_cold_start(self):
        if self.get_size() == 0:
            is_cold_start = True
        else:
            is_cold_start = self.total_request_record[-1].get_is_cold_start()

        if is_cold_start is True:
            return 1
        else:
            return 0

    def get_total_request_record(self):
        return self.total_request_record

    def get_success_request_record(self):
        return self.success_request_record

    def get_undone_request_record(self):
        return self.undone_request_record

    def get_timeout_request_record(self):
        return self.timeout_request_record

    def reset(self):
        self.success_request_record = []
        self.undone_request_record = []
        self.timeout_request_record = []

        
    
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
    
    def __init__(self, interval_limit=None):
        self.system_up_time = time.time()
        self.system_runtime = 0
        self.system_step = 0

        self.interval_limit = interval_limit

    def get_system_up_time(self):
        return self.system_up_time

    def get_system_runtime(self):
        return self.system_runtime

    def get_system_step(self):
        return self.system_step

    def step(self):
        current_time = time.time()
        interval = current_time - (self.system_up_time + self.system_runtime)

        if self.interval_limit is not None:
            # Interval must exceed limit to keep invokers healthy
            if self.system_step >= 0 and interval < self.interval_limit:
                while interval < self.interval_limit:
                    current_time = time.time()
                    interval = current_time - (self.system_up_time + self.system_runtime)

        self.system_runtime = current_time - self.system_up_time
        self.system_step = self.system_step + 1

        return interval

    def reset(self):
        self.system_up_time = time.time()
        self.system_runtime = 0
        self.system_step = 0