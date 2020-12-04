import time
import multiprocessing
import couchdb
import numpy as np
import copy as cp
import json

from params import WSK_CLI
from run_command import run_cmd


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
        self.sequence = self.params.sequence

        self.function_actual_id = self.function_id

        self.resource_adjust_direction = [0, 0] # [cpu, memory]
        self.is_resource_changed = True
    
    def set_function(self, cpu=1, memory=1):
        self.cpu = cpu
        self.memory = memory

    def set_invoke_params(self, params):
        self.params.invoke_params = params

    def get_function_id(self):
        return self.function_id

    def get_function_actual_id(self):
        return self.function_actual_id

    def get_sequence(self):
        return self.sequence

    def get_sequence_size(self):
        sequence_size = 0
        if self.sequence is not None:
            sequence_size = len(self.sequence)

        return sequence_size

    def get_total_sequence_size(self):
        total_sequence_size = 1
        if self.sequence is not None:
            total_sequence_size = total_sequence_size + len(self.sequence)

        return total_sequence_size

    def get_cpu(self):
        return self.cpu

    def get_memory(self):
        return self.memory

    def get_is_resource_changed(self):
        return self.is_resource_changed

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
        if resource == 0: # Cpu 
            if adjust == 1: # Increase
                if self.cpu == self.params.cpu_cap: # Implicit invalid action: reach cpu cap
                    return False 
            else: # Decrease
                if self.cpu == self.params.cpu_least_hint: # Implicit invalid action: reach cpu least hint
                    return False 
        else: # Memory
            if adjust == 1: # Increase
                if self.memory == self.params.memory_cap: # Implicit invalid action: reach memory cap
                    return False 
            else: # Decrease
                if self.memory == self.params.memory_least_hint: # Implicit invalid action: reach memory least hint
                    return False 
                    
        if self.resource_adjust_direction[resource] == 0: # Not touched yet
            return True   
        else:
            if self.resource_adjust_direction[resource] == adjust: # Consistent direction
                return True
            else: # Implicit invalid action: wrong direction
                return False
    
    def translate_to_openwhisk(self):
        openwhisk_input = (self.cpu - 1) * 8 + self.memory
        return openwhisk_input

    # Note: update too frequently may trigger function mismatch errors
    # Multiprocessing
    # def update_openwhisk(self, couch_link):
    #     couch_client = couchdb.Server(couch_link)
    #     couch_whisks = couch_client["whisk_distributed_whisks"]
    #     doc_function = couch_whisks["guest/{}".format(self.function_id)]
    #     doc_function["limits"]["memory"] = self.translate_to_openwhisk()
    #     couch_whisks.save(doc_function)

    # def update_openwhisk(self, couch_link):
    #     cmd = '{} action update {} -m {}'.format(WSK_CLI, self.function_id, self.translate_to_openwhisk())
    #     run_cmd(cmd)
        
    def update_openwhisk(self):
        self.function_actual_id = "{}{}".format(self.function_id, self.translate_to_openwhisk())

    # # Multiprocessing
    # def invoke_openwhisk(self, result_dict):
    #     if self.params.invoke_params == None:
    #         cmd = '{} action invoke {} | awk {}'.format(WSK_CLI, self.function_id, "{'print $6'}")
    #     else:
    #         cmd = '{} action invoke {} {} | awk {}'.format(WSK_CLI, self.function_id, self.params.invoke_params, "{'print $6'}")
        
    #     request_id = str(run_cmd(cmd))
    #     result_dict[self.function_id].append(request_id)

    # Multiprocessing
    def invoke_openwhisk(self, result_dict):
        if self.params.invoke_params == None:
            cmd = '{} action invoke {} | awk {}'.format(WSK_CLI, self.function_actual_id, "{'print $6'}")
        else:
            cmd = '{} action invoke {} {} | awk {}'.format(WSK_CLI, self.function_actual_id, self.params.invoke_params, "{'print $6'}")
        
        request_id = str(run_cmd(cmd))
        result_dict[self.function_id].append(request_id)

    def reset_resource_adjust_direction(self):
        self.resource_adjust_direction = [0, 0]


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
        self.is_success = False
        self.is_cold_start = False

    # Multiprocessing
    def try_update(self, result_dict, system_runtime, couch_link):
        # # Check timeout first before check done
        # if system_runtime - self.invoke_time > 120:
        #     # Manually label timeout or error
        #     # result_dict[self.function_id][self.request_id]["is_done"] = True
        #     # result_dict[self.function_id][self.request_id]["duration"] = 60 # Second
        #     # result_dict[self.function_id][self.request_id]["is_timeout"] = True
        #     # result_dict[self.function_id][self.request_id]["is_success"] = False
        #     # result_dict[self.function_id][self.request_id]["is_cold_start"] = True

        #     # Try query via wsk cli
        #     result = run_cmd('{} activation get {} | grep -v "ok"'.format(WSK_CLI, self.request_id))
        #     try:
        #         result_json = json.loads(result)
        #         result_dict[self.function_id][self.request_id]["is_done"] = True
        #         result_dict[self.function_id][self.request_id]["duration"] = result_json["duration"] / 1000 # Second
        #         result_dict[self.function_id][self.request_id]["is_timeout"] = result_json["annotations"][3]["value"]
        #         result_dict[self.function_id][self.request_id]["is_success"] = result_json["response"]["success"]

        #         if len(result_json["annotations"]) == 6:
        #             result_dict[self.function_id][self.request_id]["is_cold_start"] = True
        #         else:
        #             result_dict[self.function_id][self.request_id]["is_cold_start"] = False
        #     # Manually label timeout or error
        #     except json.decoder.JSONDecodeError:
        #         print("{}: {}".format(self.request_id, result))
        #         result_dict[self.function_id][self.request_id]["is_done"] = True
        #         result_dict[self.function_id][self.request_id]["duration"] = 60 # Second
        #         result_dict[self.function_id][self.request_id]["is_timeout"] = True
        #         result_dict[self.function_id][self.request_id]["is_success"] = False
        #         result_dict[self.function_id][self.request_id]["is_cold_start"] = True
        # else:
        couch_client = couchdb.Server(couch_link)
        couch_activations = couch_client["whisk_distributed_activations"]
        doc_request = couch_activations.get("guest/{}".format(self.request_id))

        # Request done?
        if doc_request is not None: 
            # Either timeout or error happened
            if len(doc_request["annotations"]) < 4:
                # Try query via wsk cli
                result = run_cmd('{} activation get {} | grep -v "ok"'.format(WSK_CLI, self.request_id))
                try:
                    result_json = json.loads(result)
                    result_dict[self.function_id][self.request_id]["is_done"] = True
                    result_dict[self.function_id][self.request_id]["duration"] = result_json["duration"] / 1000 # Second
                    result_dict[self.function_id][self.request_id]["is_timeout"] = result_json["annotations"][3]["value"]
                    result_dict[self.function_id][self.request_id]["is_success"] = result_json["response"]["success"]

                    if len(result_json["annotations"]) == 6:
                        result_dict[self.function_id][self.request_id]["is_cold_start"] = True
                    else:
                        result_dict[self.function_id][self.request_id]["is_cold_start"] = False
                # Manually label timeout or error
                except json.decoder.JSONDecodeError:
                    result_dict[self.function_id][self.request_id]["is_done"] = False
            # Request is done
            else:
                result_dict[self.function_id][self.request_id]["is_done"] = True
                result_dict[self.function_id][self.request_id]["duration"] = doc_request["duration"] / 1000 # Second
                if doc_request["response"]["statusCode"] == 0:
                    result_dict[self.function_id][self.request_id]["is_success"] = True
                else:
                    result_dict[self.function_id][self.request_id]["is_success"] = False

                # Sequence request
                if len(doc_request["annotations"]) == 4:
                    result_dict[self.function_id][self.request_id]["is_timeout"] = False
                # Normal request
                else:
                    result_dict[self.function_id][self.request_id]["is_timeout"] = doc_request["annotations"][3]["value"]
                
                if len(doc_request["annotations"]) == 6:
                    result_dict[self.function_id][self.request_id]["is_cold_start"] = True
                else:
                    result_dict[self.function_id][self.request_id]["is_cold_start"] = False
        # Not done yet
        else:
            result_dict[self.function_id][self.request_id]["is_done"] = False

    def set_updates(
        self, 
        is_done, 
        done_time, 
        is_timeout, 
        is_success,
        completion_time=None, 
        is_cold_start=None
    ):
        self.is_done = is_done
        self.done_time = done_time
        self.is_timeout = is_timeout
        self.is_success = is_success
        
        if completion_time is not None:
            self.completion_time = completion_time
        if is_cold_start is not None:
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

    def get_is_success(self):
        return self.is_success
        
    def get_is_cold_start(self):
        return self.is_cold_start


class RequestRecord():
    """
    Recording of requests both in total and per Function
    """

    def __init__(self, function_profile):
        # General records
        self.total_request_record = []
        self.success_request_record = []
        self.undone_request_record = []
        self.timeout_request_record = []
        self.error_request_record = []

        # Records per function
        self.total_request_record_per_function = {}
        self.success_request_record_per_function = {}
        self.undone_request_record_per_function = {}
        self.timeout_request_record_per_function = {}
        self.error_request_record_per_function = {}

        for function_id in function_profile.keys():
            self.total_request_record_per_function[function_id] = []
            self.success_request_record_per_function[function_id] = []
            self.undone_request_record_per_function[function_id] = []
            self.timeout_request_record_per_function[function_id] = []
            self.error_request_record_per_function[function_id] = []

    def put_requests(self, request_list):
        if isinstance(request_list, Request):
            request = request_list
            function_id = request.get_function_id()

            self.total_request_record.append(request)
            self.total_request_record_per_function[function_id].append(request)

            if request.get_is_done() is False: # Undone?
                self.undone_request_record.append(request)
                self.undone_request_record_per_function[function_id].append(request)
            else: # Done
                if request.get_is_success() is True: # Success?
                    self.success_request_record.append(request)
                    self.success_request_record_per_function[function_id].append(request)
                else: # Not success
                    if request.get_is_timeout() is True: # Timeout?
                        self.timeout_request_record.append(request)
                        self.timeout_request_record_per_function[function_id].append(request)
                    else: # Error
                        self.error_request_record.append(request)
                        self.error_request_record_per_function[function_id].append(request)
        else:
            for request in request_list:
                function_id = request.get_function_id()

                self.total_request_record.append(request)
                self.total_request_record_per_function[function_id].append(request)

                if request.get_is_done() is False: # Undone?
                    self.undone_request_record.append(request)
                    self.undone_request_record_per_function[function_id].append(request)
                else: # Done
                    if request.get_is_success() is True: # Success?
                        self.success_request_record.append(request)
                        self.success_request_record_per_function[function_id].append(request)
                    else: # Not success
                        if request.get_is_timeout() is True: # Timeout?
                            self.timeout_request_record.append(request)
                            self.timeout_request_record_per_function[function_id].append(request)
                        else: # Error
                            self.error_request_record.append(request)
                            self.error_request_record_per_function[function_id].append(request)

    def update_requests(self, done_request_list):
        if isinstance(done_request_list, Request):
            request = done_request_list
            function_id = request.get_function_id()

            if request.get_is_success() is True: # Success?
                self.success_request_record.append(request)
                self.success_request_record_per_function[function_id].append(request)
            else: # Not success
                if request.get_is_timeout() is True: # Timeout?
                    self.timeout_request_record.append(request)
                    self.timeout_request_record_per_function[function_id].append(request)
                else: # Error
                    self.error_request_record.append(request)
                    self.error_request_record_per_function[function_id].append(request)

            self.undone_request_record.remove(request)
            self.undone_request_record_per_function[function_id].remove(request)
        else:
            for request in done_request_list:
                function_id = request.get_function_id()

                if request.get_is_success() is True: # Success?
                    self.success_request_record.append(request)
                    self.success_request_record_per_function[function_id].append(request)
                else: # Not success
                    if request.get_is_timeout() is True: # Timeout?
                        self.timeout_request_record.append(request)
                        self.timeout_request_record_per_function[function_id].append(request)
                    else: # Error
                        self.error_request_record.append(request)
                        self.error_request_record_per_function[function_id].append(request)

                self.undone_request_record.remove(request)
                self.undone_request_record_per_function[function_id].remove(request)

    def get_total_size(self):
        total_size = len(self.total_request_record)
        return total_size

    def get_undone_size(self):
        undone_size = len(self.undone_request_record)
        return undone_size

    def get_success_size(self):
        success_size = len(self.success_request_record)
        return success_size

    def get_timeout_size(self):
        timeout_size = len(self.timeout_request_record)
        return timeout_size
        
    def get_error_size(self):
        error_size = len(self.error_request_record)
        return error_size

    def get_avg_completion_time(self):
        request_num = 0
        total_completion_time = 0

        for request in self.success_request_record:
            request_num = request_num + 1
            total_completion_time = total_completion_time + request.get_completion_time()

        for request in self.timeout_request_record:
            request_num = request_num + 1
            total_completion_time = total_completion_time + request.get_completion_time()
        
        if request_num == 0:
            avg_completion_time = 0
        else:
            avg_completion_time = total_completion_time / request_num

        return avg_completion_time

    def get_avg_interval(self, system_time):
        if system_time == 0:
            avg_interval = 0
        else:
            avg_interval = len(self.total_request_record) / system_time

        return avg_interval

    def get_total_size_per_function(self, function_id):
        total_size_per_function = len(self.total_request_record_per_function[function_id])
        return total_size_per_function

    def get_undone_size_per_function(self, function_id):
        undone_size_per_function = len(self.undone_request_record_per_function[function_id])
        return undone_size_per_function

    def get_success_size_per_function(self, function_id):
        success_size_per_function = len(self.success_request_record_per_function[function_id])
        return success_size_per_function

    def get_timeout_size_per_function(self, function_id):
        timeout_size_per_function = len(self.timeout_request_record_per_function[function_id])
        return timeout_size_per_function

    def get_avg_completion_time_per_function(self, function_id):
        request_num = 0
        total_completion_time = 0

        for request in self.success_request_record_per_function[function_id]:
            request_num = request_num + 1
            total_completion_time = total_completion_time + request.get_completion_time()

        for request in self.timeout_request_record_per_function[function_id]:
            request_num = request_num + 1
            total_completion_time = total_completion_time + request.get_completion_time()
        
        if request_num == 0:
            avg_completion_time_per_function = 0
        else:
            avg_completion_time_per_function = total_completion_time / request_num

        return avg_completion_time_per_function

    def get_avg_interval_per_function(self, system_time, function_id):
        if system_time == 0:
            avg_interval_per_function = 0
        else:
            avg_interval_per_function = len(self.total_request_record_per_function[function_id]) / system_time

        return avg_interval_per_function

    def get_is_cold_start_per_function(self, function_id):
        if self.get_total_size_per_function(function_id) == 0:
            is_cold_start = True
        else:
            is_cold_start = self.total_request_record_per_function[function_id][-1].get_is_cold_start()

        if is_cold_start is False:
            return 0
        else:
            return 1

    def get_total_request_record(self):
        return self.total_request_record

    def get_success_request_record(self):
        return self.success_request_record

    def get_undone_request_record(self):
        return self.undone_request_record

    def get_timeout_request_record(self):
        return self.timeout_request_record

    def get_error_request_record(self):
        return self.error_request_record

    def get_total_request_record_per_function(self, function_id):
        return self.total_request_record_per_function[function_id]

    def get_success_request_record_per_function(self, function_id):
        return self.success_request_record_per_function[function_id]

    def get_undone_request_record_per_function(self, function_id):
        return self.undone_request_record_per_function[function_id]

    def get_timeout_request_record_per_function(self, function_id):
        return self.timeout_request_record_per_function[function_id]

    def get_error_request_record_per_function(self, function_id):
        return self.error_request_record_per_function[function_id]

    def reset(self):
        self.total_request_record = []
        self.success_request_record = []
        self.undone_request_record = []
        self.timeout_request_record = []
        self.error_request_record = []

        for function_id in self.total_request_record_per_function.keys():
            self.total_request_record_per_function[function_id] = []
            self.success_request_record_per_function[function_id] = []
            self.undone_request_record_per_function[function_id] = []
            self.timeout_request_record_per_function[function_id] = []
            self.error_request_record_per_function[function_id] = []


class ResourceUtilsRecord():
    """
    Recording of CPU and memory utilizations per invoker in sec
    """

    def __init__(self, n_invoker):
        self.n_invoker = n_invoker

        self.resource_utils_record = {}

        for i in range(self.n_invoker):
            invoker = "invoker{}".format(i)
            self.resource_utils_record[invoker] = {}
            self.resource_utils_record[invoker]["cpu_util"] = []
            self.resource_utils_record[invoker]["memory_util"] = []
            self.resource_utils_record[invoker]["avg_cpu_util"] = 0
            self.resource_utils_record[invoker]["avg_memory_util"] = 0
        
        self.resource_utils_record["avg_invoker"] = {}
        self.resource_utils_record["avg_invoker"]["cpu_util"] = []
        self.resource_utils_record["avg_invoker"]["memory_util"] = []
        self.resource_utils_record["avg_invoker"]["avg_cpu_util"] = 0
        self.resource_utils_record["avg_invoker"]["avg_memory_util"] = 0

    def put_resource_utils(self, invoker, cpu_util, memory_util):
        self.resource_utils_record[invoker]["cpu_util"].append(cpu_util)
        self.resource_utils_record[invoker]["memory_util"].append(memory_util)

    def calculate_avg_resource_utils(self):
        for i in range(self.n_invoker):
            invoker = "invoker{}".format(i)
            self.resource_utils_record[invoker]["avg_cpu_util"] = np.mean(self.resource_utils_record[invoker]["cpu_util"])
            self.resource_utils_record[invoker]["avg_memory_util"] = np.mean(self.resource_utils_record[invoker]["memory_util"])

        for timestep in range(len(self.resource_utils_record["invoker0"]["cpu_util"])):
            cpu_util_tmp_list = []
            memory_util_tmp_list = []
            
            for i in range(self.n_invoker):
                if i == 0:
                    cpu_util_tmp_list = []
                    memory_util_tmp_list = []
                    
                invoker = "invoker{}".format(i)
                cpu_util_tmp_list.append(self.resource_utils_record[invoker]["cpu_util"][timestep])
                memory_util_tmp_list.append(self.resource_utils_record[invoker]["memory_util"][timestep])

            self.resource_utils_record["avg_invoker"]["cpu_util"].append(np.mean(cpu_util_tmp_list))
            self.resource_utils_record["avg_invoker"]["memory_util"].append(np.mean(memory_util_tmp_list))

        self.resource_utils_record["avg_invoker"]["avg_cpu_util"] = np.mean(self.resource_utils_record["avg_invoker"]["cpu_util"])
        self.resource_utils_record["avg_invoker"]["avg_memory_util"] = np.mean(self.resource_utils_record["avg_invoker"]["memory_util"])
    
    def get_resource_utils_record(self):
        return self.resource_utils_record

    def reset(self):
        self.resource_utils_record = {}
        
        for i in range(self.n_invoker):
            invoker = "invoker{}".format(i)
            self.resource_utils_record[invoker] = {}
            self.resource_utils_record[invoker]["cpu_util"] = []
            self.resource_utils_record[invoker]["memory_util"] = []
            self.resource_utils_record[invoker]["avg_cpu_util"] = 0
            self.resource_utils_record[invoker]["avg_memory_util"] = 0

        self.resource_utils_record["avg_invoker"] = {}
        self.resource_utils_record["avg_invoker"]["cpu_util"] = []
        self.resource_utils_record["avg_invoker"]["memory_util"] = []
        self.resource_utils_record["avg_invoker"]["avg_cpu_util"] = 0
        self.resource_utils_record["avg_invoker"]["avg_memory_util"] = 0

        
    
class Profile():
    """
    Record settings of functions
    """
    
    def __init__(self, function_profile):
        self.function_profile = function_profile
        self.default_function_profile = cp.deepcopy(function_profile)

        self.sequence_dict = {}
        for function_id in self.function_profile.keys():
            function = self.function_profile[function_id]
            if function.get_sequence() is not None:
                self.sequence_dict[function_id] = function.get_sequence()
        
    def put_function(self, function):
        function_id = function.get_function_id()
        self.function_profile[function_id] = function
    
    def get_size(self):
        return len(self.function_profile)

    def get_function_profile(self):
        return self.function_profile

    def get_sequence_dict(self):
        return self.sequence_dict

    def reset(self):
        self.function_profile = cp.deepcopy(self.default_function_profile)
        
        
class Timetable():
    """
    Dictate which and when functions will be invoked
    """
    
    def __init__(self, timetable=[]):
        self.timetable = timetable
        
    def put_timestep(self, row):
        self.timetable.append(row)
        
    def get_timestep(self, timestep):
        if timestep >= self.get_size():
            return None
        else:
            return self.timetable[timestep]
    
    def get_size(self):
        return len(self.timetable)
    

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
            # Interval must satisfy limit to keep invokers healthy
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