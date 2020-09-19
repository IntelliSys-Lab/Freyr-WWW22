import os
import numpy as np
import copy as cp



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

    def put_request(self, request):
        self.request_history.append(request)

    def get_function_id(self):
        return self.function_id

    def get_request_history(self):
        return self.request_history

    def try_update_request_history(self, system_time):
        for request in self.request_history:
            if request.get_is_done() is False:
                if request.check_if_done(system_time) is True:
                    request.update()
    
    def get_cpu(self):
        return self.cpu

    def get_memory(self):
        return self.memory

    def get_avg_interval(self, system_time):
        if system_time == 0:
            avg_interval = 0
        else:
            avg_interval = len(self.request_history) / system_time
        
        return avg_interval

    def get_avg_completion_time(self):
        request_num = 0
        total_completion_time = 0

        for request in self.request_history:
            if request.get_is_done() is True:
                request_num = request_num + 1
                total_completion_time = total_completion_time + request.get_completion_time()
        
        if request_num == 0:
            avg_completion_time = 0
        else:
            avg_completion_time = total_completion_time / request_num

        return avg_completion_time
    
    def get_is_cold_start(self):
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
        openwhisk_input = (self.cpu - 1) * 15 + self.memory
        return openwhisk_input

    def update_openwhisk(self):
        os.system('wsk action update {} --memory {}'.format(self.function_id, self.translate_to_openwhisk()))

    def invoke_openwhisk(self):
        request_id = os.popen('wsk action invoke {} | awk {}'.format(self.function_id, "{'print $6'}")).read().replace('\n', '')
        request = Request(self.function_id, request_id)
        self.put_request(request)

    def reset_resource_adjust_direction(self):
        self.resource_adjust_direction = [0, 0]

    def reset_request_history(self):
        self.request_history = []
        

class Request():
    """
    An invocation of a function
    """
    def __init__(self, function_id, request_id):
        self.function_id = function_id
        self.request_id = request_id
        self.is_done = False
        self.done_time = 0

        self.completion_time = 0
        self.is_timeout = False
        self.is_cold_start = False
        
    def check_if_done(self, system_time):
        result = os.popen('wsk activation get {}'.format(self.request_id)).read().replace('\n', '')
        
        if "error" in result:
            self.is_done = False
            return False
        else:
            self.is_done = True
            self.done_time = system_time
            return True

    def update(self):
        # Get completion time
        duration = os.popen('wsk activation get {} | grep -v "ok" | jq .duration'.format(self.request_id)).read().replace('\n', '')
        self.completion_time = int(duration)
        
        # Get timeout
        timeout = os.popen('wsk activation get {} | grep -v "ok" | jq .annotations[3].value'.format(self.request_id)).read().replace('\n', '')
        if timeout == "false":
            self.is_timeout = False
        else:
            self.is_timeout = True
        
        # Get cold start
        initTime = os.popen('wsk activation get {} | grep -v "ok" | jq .annotations[5]'.format(self.request_id)).read().replace('\n', '')
        if initTime == "null":
            self.is_cold_start = False
        else:
            self.is_cold_start = True

    def get_is_done(self):
        return self.is_done

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
    
