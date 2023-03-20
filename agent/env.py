import time
import redis
import couchdb
import numpy as np
import torch
import multiprocessing

from utils import SystemTime, Request, RequestRecord
from run_command import run_cmd
from params import WSK_CLI
from workload_generator import WorkloadGenerator


class Environment():
    """ 
    Environment for running experiments
    """

    def __init__(
        self,
        workload_params,
        env_params
    ):
        self.workload_params = workload_params
        self.env_params = env_params

        # Set up workloads
        self.workload_generator = WorkloadGenerator(
            azure_file_path=self.workload_params.azure_file_path,
            user_defined_dict=self.workload_params.user_defined_dict,
            exp_id=self.workload_params.exp_id
        )
        self.profile = self.workload_generator.generate_profile()
        self.event_pq = self.workload_generator.generate_event_pq()

        # Get total number of invokers
        self.n_invoker = self.env_params.n_invoker
        
        # Set up Redis client
        self.pool = redis.ConnectionPool(
            host=self.env_params.redis_host, 
            port=self.env_params.redis_port, 
            password=self.env_params.redis_password, 
            decode_responses=True
        )
        self.redis_client = redis.Redis(connection_pool=self.pool)

        # Set up CouchDB client
        self.couch_client = couchdb.Server(self.env_params.couch_link)

        # Set up time module
        self.system_time = SystemTime(self.env_params.interval_limit)

        # Set up request record
        self.request_record = RequestRecord(self.profile.get_function_profile())

        # Misc
        self.cool_down = self.env_params.cool_down
        self.eps = np.finfo(np.float32).eps.item()

    #
    # Process action
    #
    
    def decode_action(self, index):
        if index is not None:
            action = {}
            action["cpu"] = int(index / self.env_params.memory_cap_per_function) + 1
            action["memory"] = int(index % self.env_params.memory_cap_per_function) + 1
        else:
            action = None

        return action

    def encode_action(self, action):
        return (action["cpu"] - 1) * self.env_params.memory_cap_per_function + action["memory"]

    def update_function_profile(self, next_function_id, action):
        if isinstance(action, dict):
            function = self.profile.get_function_profile()[next_function_id]
            if "cpu" in action:
                function.set_function(cpu=action["cpu"], memory=function.get_memory())
            if "memory" in action:
                function.set_function(cpu=function.get_cpu(), memory=action["memory"])

    def try_update_function_baseline(self, next_function_id):
        function = self.profile.get_function_profile()[next_function_id]
        for request in reversed(self.request_record.success_request_record_per_function[next_function_id]):
            if request.get_baseline() == 0:
                function.set_baseline(request.get_duration())
                break

    #
    # Interactions with OpenWhisk
    #

    def invoke_openwhisk(
        self, 
        index,
        function_id,
        is_safeguard
    ):
        function = self.profile.get_function_profile()[function_id]
        request_id = function.invoke_openwhisk()
        if is_safeguard is True:
            baseline = 0
            function.set_baseline(baseline)
        else:
            if function.get_baseline() == 0:
                self.try_update_function_baseline(function_id)

            baseline = function.get_baseline()

        # Create corresponding request
        request = Request(
            index=index,
            function_id=function_id, 
            request_id=request_id, 
            invoke_time=self.system_time.get_system_runtime(),
            baseline=baseline,
            cpu_user_defined=function.get_cpu_user_defined(),
            memory_user_defined=function.get_memory_user_defined(),
            cpu=function.get_cpu(),
            memory=function.get_memory(),
            is_safeguard=is_safeguard
        )
        self.request_record.put_requests(request)

    def try_update_request_record(self):
        function_profile = self.profile.get_function_profile()
        manager = multiprocessing.Manager()
        result_dict = manager.dict()
        jobs = []

        for function_id in function_profile.keys():
            result_dict[function_id] = manager.dict()
            for request in self.request_record.get_undone_request_record_per_function(function_id):
                request_id = request.get_request_id()
                result_dict[function_id][request_id] = manager.dict()
                result_dict[function_id][request_id]["is_done"] = False
                
                p = multiprocessing.Process(
                    target=request.try_update,
                    args=(
                        result_dict, 
                        self.system_time.get_system_runtime(), 
                        self.env_params.couch_link
                    )
                )
                jobs.append(p)
                p.start()
        
        for p in jobs:
            p.join()

        # Update requests according to the result dict
        # Return rewards for requests that completes at this timestep
        good_slo = 0
        bad_slo = 0
        total_duration_slo = 0
        done_request_list = []

        for function_id in result_dict.keys():
            for request_id in result_dict[function_id].keys():
                request = self.request_record.request_record_per_request[request_id]
                result = result_dict[function_id][request_id]

                # Check if done
                is_done = result["is_done"] 
                if is_done is True:
                    done_time = result["done_time"]
                    init_time = result["init_time"]
                    wait_time = result["wait_time"]
                    duration = result["duration"]
                    is_timeout = result["is_timeout"]
                    is_success = result["is_success"]
                    is_cold_start = result["is_cold_start"]
                    cpu_timestamp = result["cpu_timestamp"]
                    cpu_usage = result["cpu_usage"]
                    mem_timestamp = result["mem_timestamp"]
                    mem_usage = result["mem_usage"]

                    # Set updates for done requests
                    request.set_updates(
                        is_done=is_done,
                        done_time=done_time,
                        is_timeout=is_timeout,
                        is_success=is_success,
                        init_time=init_time,
                        wait_time=wait_time,
                        duration=duration,
                        is_cold_start=is_cold_start,
                        cpu_timestamp=cpu_timestamp,
                        cpu_usage=cpu_usage,
                        mem_timestamp=mem_timestamp,
                        mem_usage=mem_usage,
                    )
                    done_request_list.append(request)

                    duration_slo = request.get_duration_slo()
                    if duration_slo < 1:
                        good_slo = good_slo + (1 - duration_slo)
                    elif duration_slo > 1:
                        bad_slo = bad_slo + (duration_slo - 1) * (request.get_cpu_user_defined() + request.get_memory_user_defined())

                    total_duration_slo = total_duration_slo + duration_slo
            
        # Update request records
        self.request_record.update_requests(done_request_list)

        return good_slo, bad_slo, total_duration_slo

    def get_n_undone_request(self):
        return int(self.redis_client.get("n_undone_request"))

    def get_available_cpu(self):
        return int(self.redis_client.get("available_cpu"))

    def get_available_memory(self):
        return int(self.redis_client.get("available_memory"))

    def refresh_openwhisk(self):
        cmd = "./refresh_openwhisk.sh"
        run_cmd(cmd)

    def refresh_couchdb_and_openwhisk(self):
        cmd = "./refresh_couchdb_and_openwhisk.sh"
        run_cmd(cmd)

    def clean_invoker_containers(self):
        cmd = "./clean_invoker_containers.sh"
        run_cmd(cmd)

    def cool_down_openwhisk(self):
        if self.cool_down == "refresh_openwhisk":
            self.refresh_openwhisk()
        elif self.cool_down == "refresh_couchdb_and_openwhisk":
            self.refresh_couchdb_and_openwhisk()
        else:
            self.clean_invoker_containers()
        
        time.sleep(1)
                                        
    def get_function_throughput(self):
        throughput = self.request_record.get_success_size() + \
        self.request_record.get_timeout_size() + \
        self.request_record.get_error_size()
        return throughput

    def get_mask(
        self, 
        next_function_id,
        cpu_range,
        memory_range
    ):
        batch_size = self.env_params.cpu_cap_per_function * self.env_params.memory_cap_per_function
        mask = torch.zeros(batch_size)

        if len(cpu_range) == 1:
            for i in range(mask.size(0)):
                cpu = self.decode_action(i)["cpu"]
                if cpu != cpu_range[0]:
                    mask[i] = -1e8
        else:
            for i in range(mask.size(0)):
                cpu = self.decode_action(i)["cpu"]
                if cpu < cpu_range[0] or cpu > cpu_range[1]:
                    mask[i] = -1e8

        if len(memory_range) == 1:
            for i in range(mask.size(0)):
                mem = self.decode_action(i)["memory"]
                if mem != memory_range[0]:
                    mask[i] = -1e8
        else:
            for i in range(mask.size(0)):
                mem = self.decode_action(i)["memory"]
                if mem < memory_range[0] or mem > memory_range[1]:
                    mask[i] = -1e8

        return mask

    # Observation space size: [batch_size, 11]
    def get_observation(
        self, 
        next_function_id
    ):
        function = self.profile.get_function_profile()[next_function_id]

        # Init observation
        n_undone_request = self.get_n_undone_request()
        available_cpu = self.get_available_cpu()
        available_memory = self.get_available_memory()
        function_avg_interval = self.request_record.get_avg_interval_per_function(next_function_id)
        function_avg_invoke_num = self.request_record.get_avg_invoke_num_per_function(next_function_id, self.system_time.get_system_runtime())
        function_avg_cpu_peak = self.request_record.get_avg_cpu_peak_per_function(next_function_id)
        function_avg_memory_peak = self.request_record.get_avg_memory_peak_per_function(next_function_id)
        function_avg_duration = self.request_record.get_avg_duration_per_function(next_function_id)
        function_baseline = function.get_baseline()

        state_batch = []
        for cpu in range(1, self.env_params.cpu_cap_per_function + 1):
            for memory in range(1, self.env_params.memory_cap_per_function + 1):
                state = []
                state.append(n_undone_request)
                state.append(available_cpu)
                state.append(available_memory)
                state.append(function_avg_interval)
                state.append(function_avg_invoke_num)
                state.append(function_avg_cpu_peak)
                state.append(function_avg_memory_peak)
                state.append(function_avg_duration)
                state.append(function_baseline)
                state.append(cpu)
                state.append(memory)

                state_batch.append(state)

        observation = torch.Tensor(state_batch)

        # Init mask
        cpu_cap_per_function = self.env_params.cpu_cap_per_function
        memory_cap_per_function = self.env_params.memory_cap_per_function
        cpu_user_defined = function.get_cpu_user_defined()
        memory_user_defined = function.get_memory_user_defined()
        
        last_request = self.request_record.get_last_n_done_request_per_function(next_function_id, 1)
        is_safeguard = False

        if len(last_request) == 0:
            cpu_range = [cpu_user_defined]
            memory_range = [memory_user_defined]
            is_safeguard = True
        else:
            last_request = last_request[0]

            if last_request.get_is_success() is False:
                cpu_range = [cpu_user_defined]
                memory_range = [memory_user_defined]
                is_safeguard = True
            else:
                last_cpu_alloc = last_request.get_cpu()
                last_mem_alloc = last_request.get_memory()
                last_cpu_peak = last_request.get_cpu_peak()
                last_mem_peak = last_request.get_mem_peak()
                recent_cpu_peak = self.request_record.get_recent_cpu_peak_per_function(next_function_id)
                recent_memory_peak = self.request_record.get_recent_memory_peak_per_function(next_function_id)

                if last_cpu_peak / cpu_user_defined <= 0.9: # Over-provisioned
                    if last_cpu_peak / last_cpu_alloc >= 0.9: # Usage spike
                        cpu_range = [cpu_user_defined]
                        is_safeguard = True
                        # print("{}, last_cpu_peak {}, last_cpu_alloc {}, cpu safeguard activate".format(next_function_id, last_cpu_peak, last_cpu_alloc))
                    else:
                        cpu_range = [min(int(recent_cpu_peak) + 1, cpu_user_defined), cpu_user_defined]
                else: # Under-provisioned
                    cpu_range = [min(int(recent_cpu_peak) + 1, cpu_cap_per_function), cpu_cap_per_function]
                        
                if last_mem_peak / (memory_user_defined * self.env_params.memory_unit) <= 0.9: # Over-provisioned
                    if last_mem_peak / (last_mem_alloc * self.env_params.memory_unit) >= 0.9: # Usage spike
                        memory_range = [memory_user_defined]
                        is_safeguard = True
                        # print("{}, last_mem_peak {}, last_mem_alloc {}, memory safeguard activate".format(next_function_id, last_mem_peak, last_mem_alloc * self.env_params.memory_unit))
                    else:
                        memory_range = [min(int(recent_memory_peak / self.env_params.memory_unit) + 1, memory_user_defined), memory_user_defined]
                else: # Under-provisioned
                    memory_range = [min(int(recent_memory_peak / self.env_params.memory_unit) + 1, memory_cap_per_function), memory_cap_per_function]

                # if len(cpu_range) > 1 and cpu_range[0] >= cpu_range[1]:
                #     print("last_cpu_peak: {}, last_cpu_alloc: {}, cpu_user_defined: {}".format(last_cpu_peak, last_cpu_alloc, cpu_user_defined))
                #     print("cpu_range: {} - {}".format(cpu_range[0], cpu_range[1]))
                # if len(memory_range) > 1 and memory_range[0] >= memory_range[1]:
                #     print("last_mem_peak: {}, last_mem_alloc: {}, memory_user_defined: {}".format(last_mem_peak / self.env_params.memory_unit, last_mem_alloc, memory_user_defined))
                #     print("memory_range: {} - {}".format(memory_range[0], memory_range[1]))

        mask = self.get_mask(
            next_function_id=next_function_id,
            cpu_range=cpu_range,
            memory_range=memory_range
        )

        observation = observation.unsqueeze(0)
        mask = mask.unsqueeze(0)

        # print("observation:")
        # print(observation)
        # print("mask:")
        # print(mask)
        # print("is_safeguard:")
        # print(is_safeguard)

        return observation, mask, is_safeguard

    def get_reward(
        self, 
        good_slo,
        bad_slo,
        total_duration_slo
    ):
        if self.get_function_throughput() == 0:
            reward = - total_duration_slo
        else:
            reward = - total_duration_slo / self.get_function_throughput() ** (1/3)

        # Constant summary on good and bad decisions
        reward = reward + good_slo - bad_slo
        
        # # Normalized by trace
        # reward = reward / self.event_pq.get_total_size() 

        return  reward

    def get_done(self):
        if self.event_pq.is_empty() is True and \
        self.system_time.get_system_step() > self.event_pq.get_max_timestep() - 1 and \
        self.get_n_undone_request() == 0:
            return True
        else:
            return False

    def get_info(self, done):
        info = {
            "system_step": self.system_time.get_system_step(),
            "system_runtime": self.system_time.get_system_runtime(),
            "n_undone_request": self.get_n_undone_request(),
            "total_available_cpu": self.get_available_cpu(),
            "total_available_memory": self.get_available_memory(),
            "request_record": self.request_record,
        }

        if done is True:
            info["timeout_num"] = self.request_record.get_timeout_size()
            info["error_num"] = self.request_record.get_error_size()
            info["csv_per_invocation"] = self.request_record.get_csv_trajectory()
            info["csv_percentile"] = self.request_record.get_csv_delta()

        return info

    def step(
        self, 
        current_timestep,
        current_index,
        current_function_id,
        is_safeguard,
        action
    ):
        # Update function configuration according to the action
        if action is not None:
            self.update_function_profile(current_function_id, action)

        # Get next event
        if self.event_pq.is_empty() is False:
            # Events proceed
            if self.system_time.get_system_step() < current_timestep:
                self.system_time.step(current_timestep - self.system_time.get_system_step())

            # Invoke functions according to the given function
            self.invoke_openwhisk(current_index, current_function_id, is_safeguard)

            # Try update all inflight requests
            good_slo, bad_slo, total_duration_slo = self.try_update_request_record()

            # Get next event
            next_timestep, next_index, next_function_id = self.event_pq.get_event()

            # Get observation for next state
            observation, mask, is_safeguard = self.get_observation(next_function_id=next_function_id)

            # Get reward
            reward = self.get_reward(
                good_slo=good_slo,
                bad_slo=bad_slo,
                total_duration_slo=total_duration_slo
            )
        else:
            # Invoke the last event
            self.invoke_openwhisk(current_index, current_function_id, is_safeguard)

            # Proceed to the end
            if self.system_time.get_system_step() < self.event_pq.get_max_timestep():
                self.system_time.step(self.event_pq.get_max_timestep() -  self.system_time.get_system_step())

            # Wait until no inflight requests
            while True:
                if self.get_done() is True:
                    break 
            
            # Retrieve tail rewards
            reward = 0

            retry = 0
            while retry < self.env_params.update_retry_time:
                if self.request_record.get_undone_size() == 0:
                    break

                # Try update all inflight requests
                good_slo, bad_slo, total_duration_slo = self.try_update_request_record()

                # Get reward
                reward = reward + self.get_reward(
                    good_slo=good_slo,
                    bad_slo=bad_slo,
                    total_duration_slo=total_duration_slo
                )

                retry = retry + 1

            self.request_record.label_all_undone_error(self.system_time.get_system_runtime())

            observation = None
            mask = None
            is_safeguard = None
            next_timestep = None
            next_index = None
            next_function_id = None

        # Done?
        done = self.get_done()

        # Return information
        info = self.get_info(done)

        return observation, mask, is_safeguard, reward, done, info, next_timestep, next_index, next_function_id

    def reset(self):
        self.system_time.reset()
        self.profile.reset()
        self.event_pq.reset()
        self.request_record.reset()
        
        next_timestep, next_index, next_function_id = self.event_pq.get_event()
        observation, mask, is_safeguard = self.get_observation(next_function_id=next_function_id)
        
        return observation, mask, is_safeguard, next_timestep, next_index, next_function_id
