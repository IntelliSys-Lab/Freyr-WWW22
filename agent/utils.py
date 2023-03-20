import time
import numpy as np
import copy as cp
import heapq
import couchdb
import multiprocessing
import csv

from params import *
from run_command import run_cmd


#
# Class utilities
#

class Function():
    """
    Function wrapper
    """
    
    def __init__(self, params):
        self.params = params
        self.function_id = self.params.function_id
        self.actual_id = "{}_28".format(self.function_id) 

        self.baseline = 0

    def set_function(self, cpu, memory):
        self.cpu = cpu
        self.memory = memory
        self.update_openwhisk()

    def set_invoke_params(self, params):
        self.params.invoke_params = params

    def set_baseline(self, duration):
        self.baseline = duration

    def get_function_id(self):
        return self.function_id
    
    def get_actual_id(self):
        return self.actual_id

    def get_cpu(self):
        return self.cpu

    def get_memory(self):
        return self.memory

    def get_cpu_user_defined(self):
        return self.params.cpu_user_defined

    def get_memory_user_defined(self):
        return self.params.memory_user_defined

    def get_baseline(self):
        return self.baseline

    def translate_to_openwhisk(self):
        return (self.cpu - 1) * self.params.memory_cap_per_function + self.memory

    def update_openwhisk(self):
        self.actual_id = "{}_{}".format(self.function_id, self.translate_to_openwhisk())

    def invoke_openwhisk(self):
        cmd = '{} action invoke {} {}'.format(WSK_CLI, self.actual_id, self.params.invoke_params)

        result = str(run_cmd(cmd))
        request_id = result.split(" ")[-1]
        
        return request_id


class Request():
    """
    An invocation of a function
    """
    def __init__(
        self, 
        index,
        function_id, 
        request_id, 
        invoke_time,
        baseline,
        cpu_user_defined,
        memory_user_defined,
        cpu,
        memory,
        is_safeguard
    ):
        self.index = index
        self.function_id = function_id
        self.request_id = request_id
        self.invoke_time = invoke_time
        self.baseline = baseline
        self.cpu_user_defined = cpu_user_defined
        self.memory_user_defined = memory_user_defined
        self.cpu = cpu
        self.memory = memory
        self.is_safeguard = is_safeguard

        self.is_done = False
        self.done_time = 0
        self.init_time = 0
        self.wait_time = 0
        self.duration = 0
        self.is_timeout = False
        self.is_success = False
        self.is_cold_start = False
        self.cpu_timestamp = []
        self.cpu_usage = []
        self.mem_timestamp = []
        self.mem_usage = []
        self.cpu_peak = 0
        self.mem_peak = 0
        self.memory_delta = 0
        self.cpu_delta = 0

    def get_index(self):
        return self.index

    def get_function_id(self):
        return self.function_id

    def get_request_id(self):
        return self.request_id

    def get_cpu_user_defined(self):
        return self.cpu_user_defined

    def get_memory_user_defined(self):
        return self.memory_user_defined

    def get_cpu(self):
        return self.cpu

    def get_memory(self):
        return self.memory

    def get_is_done(self):
        return self.is_done

    def get_invoke_time(self):
        return self.invoke_time

    def get_done_time(self):
        return self.done_time

    def get_duration(self):
        return self.duration

    def get_completion_time(self):
        return (self.init_time + self.wait_time + self.duration)

    def get_duration_slo(self):
        if self.baseline == 0:
            duration_slo = 1
        else:
            duration_slo = self.duration / self.baseline
        return duration_slo

    def get_baseline(self):
        return self.baseline

    def get_is_timeout(self):
        return self.is_timeout

    def get_is_success(self):
        return self.is_success
        
    def get_is_cold_start(self):
        return self.is_cold_start

    def get_cpu_peak(self):
        return self.cpu_peak

    def get_mem_peak(self):
        return self.mem_peak

    def get_is_safeguard(self):
        return self.is_safeguard

    def get_memory_delta(self):
        return self.memory_delta
    
    def get_cpu_delta(self):
        return self.cpu_delta
    
    # Multiprocessing
    def try_update(self, result_dict, system_runtime, couch_link):
        couch_client = couchdb.Server(couch_link)
        couch_activations = couch_client["whisk_distributed_activations"]
        doc = couch_activations.get("guest/{}".format(self.request_id))
        result = result_dict[self.function_id][self.request_id]

        if doc is not None: 
            try:
                result["is_done"] = True
                result["done_time"] = system_runtime
                result["wait_time"] = doc["annotations"][1]["value"]
                result["duration"] = doc["duration"]
                if doc["response"]["statusCode"] == 0:
                    result["is_success"] = True
                    result["cpu_timestamp"] = [float(x) for x in doc["response"]["result"]["cpu_timestamp"]]
                    result["cpu_usage"] = [float(x) for x in doc["response"]["result"]["cpu_usage"]]
                    result["mem_timestamp"] = [float(x) for x in doc["response"]["result"]["mem_timestamp"]]
                    result["mem_usage"] = [float(x) for x in doc["response"]["result"]["mem_usage"]]
                else:
                    result["is_success"] = False
                    result["cpu_timestamp"] = []
                    result["cpu_usage"] = []
                    result["mem_timestamp"] = []
                    result["mem_usage"] = []

                result["is_timeout"] = doc["annotations"][3]["value"]
                
                if len(doc["annotations"]) == 6:
                    result["is_cold_start"] = True
                    result["init_time"] = doc["annotations"][5]["value"]
                else:
                    result["is_cold_start"] = False
                    result["init_time"] = 0 
            except Exception as e:
                # print("Exception {} occurred when processing request {}".format(e, self.request_id))
                result["is_done"] = False
        else:
            result["is_done"] = False

    def set_updates(
        self, 
        is_done,
        done_time,
        is_timeout,
        is_success,
        init_time,
        wait_time,
        duration,
        is_cold_start,
        cpu_timestamp,
        cpu_usage,
        mem_timestamp,
        mem_usage
    ):
        self.is_done = is_done
        self.done_time = done_time
        self.is_timeout = is_timeout
        self.is_success = is_success
        self.init_time = init_time
        self.wait_time = wait_time
        self.duration = duration
        self.is_cold_start = is_cold_start
        self.cpu_timestamp=cpu_timestamp
        self.cpu_usage=cpu_usage
        self.mem_timestamp=mem_timestamp
        self.mem_usage=mem_usage

        if len(self.cpu_usage) > 0:
            self.cpu_peak = max(self.cpu_usage)
        if len(self.mem_usage) > 0:
            self.mem_peak = max(self.mem_usage)
        self.memory_delta = self.get_memory() - self.get_memory_user_defined()
        self.cpu_delta = self.get_cpu() - self.get_cpu_user_defined()

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

        # Records hashed by function id
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

        # Records hashed by request id
        self.request_record_per_request = {}

    def put_requests(self, request):
        function_id = request.get_function_id()
        request_id = request.get_request_id()
        self.total_request_record.append(request)
        self.total_request_record_per_function[function_id].append(request)
        self.undone_request_record.append(request)
        self.undone_request_record_per_function[function_id].append(request)
        self.request_record_per_request[request_id] = request

    def update_requests(self, done_request_list):
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

    def label_all_undone_error(self, done_time):
        done_request_list = []
        for request in self.undone_request_record:
            request.set_updates(
                is_done=True,
                done_time=done_time,
                is_timeout=False,
                is_success=False,
                init_time=60,
                wait_time=60,
                duration=60,
                is_cold_start=True,
                cpu_timestamp=[],
                cpu_usage=[],
                mem_timestamp=[],
                mem_usage=[],
            )
            done_request_list.append(request)

        self.update_requests(done_request_list)

    def get_couch_key_list(self):
        key_list = []
        for request in self.undone_request_record:
            key_list.append("guest/{}".format(request.get_request_id()))

        return key_list

    def get_last_n_done_request_per_function(self, function_id, n):
        last_n_request = []

        for request in reversed(self.total_request_record_per_function[function_id]):
            if request.get_is_done() is True:
                last_n_request.append(request)
            
            if len(last_n_request) == n:
                break

        return last_n_request

    # Only focus on latest recalibration
    def get_recent_cpu_peak_per_function(self, function_id):
        recent_cpu_peak = 0
        for request in reversed(self.success_request_record_per_function[function_id]):
            if request.get_cpu_peak() > recent_cpu_peak:
                recent_cpu_peak = request.get_cpu_peak()

            if request.get_baseline() == 0:
                break

        return recent_cpu_peak

    # Only focus on latest recalibration
    def get_recent_memory_peak_per_function(self, function_id):
        recent_memory_peak = 0
        for request in reversed(self.success_request_record_per_function[function_id]):
            if request.get_mem_peak() > recent_memory_peak:
                recent_memory_peak = request.get_mem_peak()

            if request.get_baseline() == 0:
                break

        return recent_memory_peak

    # Only focus on latest recalibration
    def get_recent_completion_time_per_function(self, function_id):
        recent_completion_time = 0
        for request in reversed(self.success_request_record_per_function[function_id]):
            if request.get_completion_time() < recent_completion_time:
                recent_completion_time = request.get_completion_time()

            if request.get_baseline() == 0:
                break

        return recent_completion_time

    def get_avg_completion_time_per_function(self, function_id):
        request_num = 0
        total_completion_time = 0

        for request in self.success_request_record_per_function[function_id]:
            request_num = request_num + 1
            total_completion_time = total_completion_time + request.get_completion_time()
        for request in self.timeout_request_record_per_function[function_id]:
            request_num = request_num + 1
            total_completion_time = total_completion_time + request.get_completion_time()
        # for request in self.error_request_record_per_function[function_id]:
        #     request_num = request_num + 1
        #     total_completion_time = total_completion_time + request.get_completion_time()
        
        if request_num == 0:
            avg_completion_time_per_function = 0
        else:
            avg_completion_time_per_function = total_completion_time / request_num

        return avg_completion_time_per_function

    def get_total_size(self):
        return len(self.total_request_record)

    def get_undone_size(self):
        return len(self.undone_request_record)

    def get_success_size(self):
        return len(self.success_request_record)

    def get_timeout_size(self):
        return len(self.timeout_request_record)
        
    def get_error_size(self):
        return len(self.error_request_record)

    def get_avg_duration_slo(self):
        request_num = 0
        total_duration_slo = 0

        for request in self.success_request_record:
            request_num = request_num + 1
            total_duration_slo = total_duration_slo + request.get_duration_slo()
        # for request in self.timeout_request_record:
        #     request_num = request_num + 1
        #     total_duration_slo = total_duration_slo + request.get_duration_slo()
        # for request in self.error_request_record:
        #     request_num = request_num + 1
        #     total_duration_slo = total_duration_slo + request.get_duration_slo()
        
        if request_num == 0:
            avg_duration_slo = 0
        else:
            avg_duration_slo = total_duration_slo / request_num

        return avg_duration_slo

    def get_avg_completion_time(self):
        request_num = 0
        total_completion_time = 0

        for request in self.success_request_record:
            request_num = request_num + 1
            total_completion_time = total_completion_time + request.get_completion_time()
        for request in self.timeout_request_record:
            request_num = request_num + 1
            total_completion_time = total_completion_time + request.get_completion_time()
        # for request in self.error_request_record:
        #     request_num = request_num + 1
        #     total_completion_time = total_completion_time + request.get_completion_time()
        
        if request_num == 0:
            avg_completion_time = 0
        else:
            avg_completion_time = total_completion_time / request_num

        return avg_completion_time

    def get_avg_interval(self):
        total_interval = 0
        num = 0
        for i, request in enumerate(self.total_request_record):
            if i < len(self.total_request_record) - 1:
                next_request = self.total_request_record[i+1]
                interval = next_request.get_invoke_time() - request.get_invoke_time()

                if interval > 0:
                    total_interval = total_interval + interval
                    num = num + 1

        if num == 0:
            avg_interval = 0
        else:
            avg_interval = total_interval / num

        return avg_interval

    def get_cold_start_num(self):
        request_num = 0
        cold_start_num = 0

        for request in self.success_request_record:
            request_num = request_num + 1
            if request.get_is_cold_start() is True:
                cold_start_num = cold_start_num + 1
        for request in self.timeout_request_record:
            request_num = request_num + 1
            if request.get_is_cold_start() is True:
                cold_start_num = cold_start_num + 1
        # for request in self.error_request_record:
        #     request_num = request_num + 1
        #     if request.get_is_cold_start() is True:
        #         cold_start_num = cold_start_num + 1

        if request_num == 0:
            cold_start_percent = 0
        else:
            cold_start_percent = cold_start_num / request_num
        
        return cold_start_percent

    def get_csv_trajectory(self):
        csv_trajectory = []
        header = ["index", "request_id", "function_id", "success", "timeout", \
            "cpu", "memory", "cpu_peak", "mem_peak", "duration", "completion_time"]
        csv_trajectory.append(header)
        
        for request in self.total_request_record:
            row = [
                request.get_index(),
                request.get_request_id(),
                request.get_function_id(),
                request.get_is_success(),
                request.get_is_timeout(),
                request.get_cpu(),
                request.get_memory(),
                request.get_cpu_peak(),
                request.get_mem_peak(),
                request.get_duration(),
                request.get_completion_time()
            ]
            csv_trajectory.append(row)
        
        return csv_trajectory

    def get_csv_delta(self):
        csv_delta = []
        header = ["index", "request_id", "is_safeguard", "cpu_delta", "mem_delta", "duration", "completion_time"]
        csv_delta.append(header)
        
        for request in self.total_request_record:
            row = [
                request.get_index(),
                request.get_request_id(),
                request.get_is_safeguard(),
                request.get_cpu_delta(),
                request.get_memory_delta(),
                request.get_duration(),
                request.get_completion_time()
            ]
            csv_delta.append(row)
        
        return csv_delta

    def get_csv_cpu_usage(self, system_up_time):
        csv_usage = []
        header = ["time", "util", "alloc"]
        
        # Find the start and end time
        start_time = 1e16
        end_time = 0
        for request in self.total_request_record:
            if request.get_is_success() is True:
                if start_time > request.cpu_timestamp[0]:
                    start_time = request.cpu_timestamp[0]
                if end_time < request.cpu_timestamp[-1]:
                    end_time = request.cpu_timestamp[-1]
            # else:
            #     if end_time < request.get_invoke_time() + system_up_time + request.get_duration():
            #         end_time = request.get_invoke_time() + system_up_time + request.get_duration()
        
        time_range = int(end_time - start_time) + 1
        usage = [(0, 0) for _ in range(time_range)]

        # Calculate usage
        for request in self.total_request_record:
            usage_list = [([], []) for _ in range(time_range)]

            if request.get_is_success() is True:
                for (timestamp, util) in zip(request.cpu_timestamp, request.cpu_usage):
                    index = int(timestamp - start_time)
                    if index < len(usage_list):
                        (util_list, alloc_list) = usage_list[index]
                        util_list.append(np.clip(util, 1, request.get_cpu()))
                        alloc_list.append(request.get_cpu())

                for t, (total_util, total_alloc) in enumerate(usage):
                    (util_list, alloc_list) = usage_list[t]
                    if len(util_list) > 0:
                        util_avg = np.mean(util_list)
                    else:
                        util_avg = 0
                    if len(alloc_list) > 0:
                        alloc_avg = np.mean(alloc_list) 
                    else:
                        alloc_avg = 0
                    usage[t] = (np.clip(total_util + util_avg, 1, 80), np.clip(total_alloc + alloc_avg, 1, 80))
            # else:
            #     base = request.get_invoke_time() + system_up_time
            #     if base < start_time:
            #         base = start_time

            #     for i in range(int(request.get_duration())):
            #         index = int(i + base - start_time)
            #         if index < len(usage_list):
            #             (util_list, alloc_list) = usage_list[index]
            #             util_list.append(0.5)
            #             alloc_list.append(request.get_cpu())

            #     for t, (total_util, total_alloc) in enumerate(usage):
            #         (util_list, alloc_list) = usage_list[t]
            #         if len(util_list) > 0:
            #             util_avg = np.mean(util_list)
            #         else:
            #             util_avg = 0
            #         if len(alloc_list) > 0:
            #             alloc_avg = np.mean(alloc_list)
            #         else:
            #             alloc_avg = 0
            #         usage[t] = (total_util + util_avg, total_alloc + alloc_avg)

        # Generate csv
        csv_usage.append(header)
        for i, (util, alloc) in enumerate(usage):
            csv_usage.append([i + 1, util, alloc])

        return csv_usage

    def get_csv_mem_usage(self, system_up_time):
        csv_usage = []
        header = ["time", "util", "alloc"]
        
        # Find the start and end time
        start_time = 1e16
        end_time = 0
        for request in self.total_request_record:
            if request.get_is_success() is True:
                if start_time > request.cpu_timestamp[0]:
                    start_time = request.cpu_timestamp[0]
                if end_time < request.cpu_timestamp[-1]:
                    end_time = request.cpu_timestamp[-1]
            # else:
            #     if end_time < request.get_invoke_time() + system_up_time + request.get_duration():
            #         end_time = request.get_invoke_time() + system_up_time + request.get_duration()
        
        time_range = int(end_time - start_time) + 1
        usage = [(0, 0) for _ in range(time_range)]

        # Calculate usage
        for request in self.total_request_record:
            usage_list = [([], []) for _ in range(time_range)]

            if request.get_is_success() is True:
                for (timestamp, util) in zip(request.mem_timestamp, request.mem_usage):
                    index = int(timestamp - start_time)
                    if index < len(usage_list):
                        (util_list, alloc_list) = usage_list[index]
                        util_list.append(np.clip(util, 1, request.get_memory()*MEMORY_UNIT))
                        alloc_list.append(request.get_memory())

                for t, (total_util, total_alloc) in enumerate(usage):
                    (util_list, alloc_list) = usage_list[t]
                    if len(util_list) > 0:
                        util_avg =np.mean(util_list)
                    else:
                        util_avg = 0
                    if len(alloc_list) > 0:
                        alloc_avg = np.mean(alloc_list)
                    else:
                        alloc_avg = 0
                    usage[t] = (np.clip(total_util + util_avg, 1, 20480), np.clip(total_alloc + alloc_avg*MEMORY_UNIT, 1, 20480))
            # else:
            #     base = request.get_invoke_time() + system_up_time
            #     if base < start_time:
            #         base = start_time
                    
            #     for i in range(int(request.get_duration())):
            #         index = int(i + base - start_time)
            #         if index < len(usage_list):
            #             (util_list, alloc_list) = usage_list[index]
            #             util_list.append(64)
            #             alloc_list.append(request.get_memory())

            #     for t, (total_util, total_alloc) in enumerate(usage):
            #         (util_list, alloc_list) = usage_list[t]
            #         if len(util_list) > 0:
            #             util_avg = np.mean(util_list)
            #         else:
            #             util_avg = 0
            #         if len(alloc_list) > 0:
            #             alloc_avg = np.mean(alloc_list)
            #         else:
            #             alloc_avg = 0
            #         usage[t] = (total_util + util_avg, total_alloc + alloc_avg*params.MEMORY_UNIT)

        # Generate csv
        csv_usage.append(header)
        for i, (util, alloc) in enumerate(usage):
            csv_usage.append([i + 1, util, alloc])

        return csv_usage

    def get_total_size_per_function(self, function_id):
        return len(self.total_request_record_per_function[function_id])

    def get_undone_size_per_function(self, function_id):
        return len(self.undone_request_record_per_function[function_id])

    def get_success_size_per_function(self, function_id):
        return len(self.success_request_record_per_function[function_id])

    def get_timeout_size_per_function(self, function_id):
        return len(self.timeout_request_record_per_function[function_id])

    def get_avg_interval_per_function(self, function_id):
        total_interval = 0
        num = 0
        for i, request in enumerate(self.total_request_record_per_function[function_id]):
            if i < len(self.total_request_record_per_function[function_id]) - 1:
                next_request = self.total_request_record_per_function[function_id][i+1]
                interval = next_request.get_invoke_time() - request.get_invoke_time()

                if interval > 0:
                    total_interval = total_interval + interval
                    num = num + 1

        if num == 0:
            avg_interval_per_function = 0
        else:
            avg_interval_per_function = total_interval / num

        return avg_interval_per_function

    def get_avg_invoke_num_per_function(self, function_id, system_runtime):
        avg_invoke_num_per_function = 0
        if system_runtime > 0:
            avg_invoke_num_per_function = len(self.total_request_record_per_function[function_id]) / system_runtime

        return avg_invoke_num_per_function

    def get_is_cold_start_per_function(self, function_id):
        if self.get_total_size_per_function(function_id) == 0:
            is_cold_start = True
        else:
            is_cold_start = self.total_request_record_per_function[function_id][-1].get_is_cold_start()

        if is_cold_start is False:
            return 0
        else:
            return 1

    # Only focus on latest recalibration
    def get_avg_duration_per_function(self, function_id):
        request_num = 0
        total_duration = 0

        for request in reversed(self.success_request_record_per_function[function_id]):
            request_num = request_num + 1
            total_duration = total_duration + request.get_duration()

            if request.get_baseline() == 0:
                break
        
        if request_num == 0:
            avg_duration_per_function = 0
        else:
            avg_duration_per_function = total_duration / request_num

        return avg_duration_per_function

    # Only focus on latest recalibration
    def get_avg_cpu_peak_per_function(self, function_id):
        request_num = 0
        total_cpu_peak = 0

        for request in reversed(self.success_request_record_per_function[function_id]):
            request_num = request_num + 1
            total_cpu_peak = total_cpu_peak + request.get_cpu_peak()

            if request.get_baseline() == 0:
                break

        if request_num == 0:
            avg_cpu_peak_per_function = 0
        else:
            avg_cpu_peak_per_function = total_cpu_peak / request_num

        return avg_cpu_peak_per_function

    # Only focus on latest recalibration
    def get_avg_memory_peak_per_function(self, function_id):
        request_num = 0
        total_mem_peak = 0

        for request in reversed(self.success_request_record_per_function[function_id]):
            request_num = request_num + 1
            total_mem_peak = total_mem_peak + request.get_mem_peak()

            if request.get_baseline() == 0:
                break

        if request_num == 0:
            avg_mem_peak_per_function = 0
        else:
            avg_mem_peak_per_function = total_mem_peak / request_num

        return avg_mem_peak_per_function

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

    def get_request_per_request(self, request_id):
        return self.request_record_per_request[request_id]

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

        self.request_record_per_request = {}


class Profile():
    """
    Record settings of functions
    """
    
    def __init__(self, function_profile):
        self.function_profile = function_profile
        self.default_function_profile = cp.deepcopy(function_profile)

    def put_function(self, function):
        function_id = function.get_function_id()
        self.function_profile[function_id] = function
    
    def get_size(self):
        return len(self.function_profile)

    def get_function_profile(self):
        return self.function_profile

    def reset(self):
        self.function_profile = cp.deepcopy(self.default_function_profile)
        
        
class EventPQ():
    """
    A priority queue of events, dictates which and when function will be invoked
    """
    
    def __init__(
        self, 
        pq,
        max_timestep
    ):
        self.pq = pq
        self.default_pq = cp.deepcopy(pq)
        self.max_timestep = max_timestep
        
    def get_event(self):
        if self.is_empty() is True:
            return None, None
        else:
            (timestep, counter, function_id) = heapq.heappop(self.pq)
            return timestep, counter, function_id
    
    def get_current_size(self):
        return len(self.pq)

    def get_total_size(self):
        return len(self.default_pq)

    def get_max_timestep(self):
        return self.max_timestep

    def is_empty(self):
        if len(self.pq) == 0:
            return True
        else:
            return False

    def reset(self):
        self.pq = cp.deepcopy(self.default_pq)
    

class SystemTime():
    """
    Time module wrapper
    """
    
    def __init__(self, interval_limit=1):
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

    def update_runtime(self, increment):
        old_runtime = self.system_runtime
        target_runtime = self.system_runtime + increment
        while self.system_runtime <= target_runtime:  
            self.system_runtime = time.time() - self.system_up_time
        return self.system_runtime - old_runtime

    def step(self, increment):
        self.system_step = self.system_step + increment
        return self.update_runtime(increment)

    def reset(self):
        self.system_up_time = time.time()
        self.system_runtime = 0
        self.system_step = 0

def export_csv_trajectory(
    rm_name,
    exp_id,
    episode,
    csv_trajectory
):
    file_path = "logs/"
    file_name = "{}_{}_{}_trajectory.csv".format(rm_name, exp_id, episode)

    with open(file_path + file_name, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerows(csv_trajectory)

def export_csv_delta(
    rm_name,
    exp_id,
    episode,
    csv_delta
):
    file_path = "logs/"
    file_name = "{}_{}_{}_delta.csv".format(rm_name, exp_id, episode)

    with open(file_path + file_name, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerows(csv_delta)

def export_csv_usage(
    rm_name,
    exp_id,
    episode,
    csv_cpu_usage,
    csv_memory_usage
):
    file_path = "logs/"

    with open(file_path + "{}_{}_{}_cpu_usage.csv".format(rm_name, exp_id, episode), "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerows(csv_cpu_usage)

    with open(file_path + "{}_{}_{}_memory_usage.csv".format(rm_name, exp_id, episode), "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerows(csv_memory_usage)
