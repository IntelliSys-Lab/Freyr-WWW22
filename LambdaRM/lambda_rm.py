import time
import redis
import numpy as np
import matplotlib.pyplot as plt
import multiprocessing
import queue

from logger import Logger
from plotter import Plotter
from ppo2_agent import PPO2Agent
from utils import SystemTime, Request, ResourceUtilsRecord
from run_command import run_cmd



class LambdaRM():
    """ 
    LambdaRM: Serverless Resource Management via Reinforce Learning.
    """

    def __init__(
        self,
        profile,
        timetable,
        redis_host="192.168.196.213",
        redis_port=6379,
        redis_password="openwhisk",
        couch_protocol = "http",
        couch_user = "whisk_admin",
        couch_password = "some_passw0rd",
        couch_host = "192.168.196.65",
        couch_port = "5984",
        cool_down=60,
        interval_limit=None,
        fail_penalty=60,
        decay_factor=0.8,
    ):
        self.cool_down = cool_down
        self.fail_penalty = fail_penalty
        self.decay_factor = decay_factor
        self.profile = profile
        self.timetable = timetable

        # Get total number of invokers
        self.n_invoker = int(run_cmd('cat ../ansible/environments/distributed/hosts | grep "invoker" | grep -v "\[invokers\]" | wc -l'))
        
        # Calculate state and action space 
        self.state_space = 1 + 3 * self.n_invoker + 5 * self.profile.get_size()
        self.action_space = 1 + 4 * self.profile.get_size()

        # Set up Redis client
        self.pool = redis.ConnectionPool(
            host=redis_host, 
            port=redis_port, 
            password=redis_password, 
            decode_responses=True
        )
        self.redis_client = redis.Redis(connection_pool=self.pool)

        # Define CouchDB link
        self.couch_link = "{}://{}:{}@{}:{}/".format(
            couch_protocol, couch_user, couch_password, couch_host, couch_port
        )

        # Set up time module
        self.system_time = SystemTime(interval_limit)

        # Set up logger module
        self.logger_wrapper = Logger()

        # Set up resource utils record
        self.resource_utils_record = ResourceUtilsRecord(self.n_invoker)

    #
    # Interfaces with OpenWhisk
    #

    def decode_action(self, action):
        function_index = int(action/4)
        resource = None
        adjust = 0
        
        if action%4 == 0:
            resource = 0 # CPU
            adjust = -1 # Decrease one slot
        elif action%4 == 1:
            resource = 0 # CPU
            adjust = 1 # Increase one slot
        elif action%4 == 2:
            resource = 1 # Memory
            adjust = -1 # Decrease one slot
        elif action%4 == 3:
            resource = 1 # Memory
            adjust = 1 # Increase one slot
        
        return function_index, resource, adjust

    
    def update_function_profile(self, action):
        if isinstance(action, list): # WARNING! Only used by greedy RM!
            actions = action
            for act in actions:
                function_index, resource, adjust = self.decode_action(act)
                # if self.profile.function_profile[function_index].validate_resource_adjust(resource, adjust) is True:
                #     self.profile.function_profile[function_index].set_resource_adjust(resource, adjust)

                self.profile.function_profile[function_index].set_resource_adjust(resource, adjust)

                # Set the sequence of this function as well
                if self.profile.function_profile[function_index].get_sequence() is not None:
                    sequence = self.profile.function_profile[function_index].get_sequence()
                    for function_id in sequence:
                        for function in self.profile.get_function_profile():
                            if function_id == function.get_function_id():
                                function.set_resource_adjust(resource, adjust)
            
            return False
        
        if action == self.action_space - 1: # Explicit invalid action
            return False
        else:
            function_index, resource, adjust = self.decode_action(action)
            if self.profile.function_profile[function_index].validate_resource_adjust(resource, adjust) is True:
                self.profile.function_profile[function_index].set_resource_adjust(resource, adjust)
                return True
            else:
                return False # Implicit invalid action

    # Multiprocessing
    def update_openwhisk(self):
        jobs = []

        for function in self.profile.function_profile:
            if function.get_is_resource_changed() is True:
                p = multiprocessing.Process(
                    target=function.update_openwhisk,
                    args=(self.couch_link,)
                )
                jobs.append(p)
                p.start()
        
        for p in jobs:
            p.join()

    # Multiprocessing
    def invoke_openwhisk(self):
        timestep = self.timetable.get_timestep(self.system_time.get_system_step()-1)
        if timestep is not None:
            manager = multiprocessing.Manager()
            result_dict = manager.dict()
            jobs = []

            for function_i in range(self.profile.get_size()):
                function = self.profile.function_profile[function_i]
                result_dict[function.function_id] = manager.list()
                for _ in range(timestep[function_i]):
                    p = multiprocessing.Process(
                        target=function.invoke_openwhisk,
                        args=(result_dict,)
                    )
                    jobs.append(p)
                    p.start()
            
            for p in jobs:
                p.join()

            # Create requests according to the result dict
            for function_id in result_dict.keys():
                for function in self.profile.function_profile:
                    if function_id == function.get_function_id():
                        for request_id in result_dict[function_id]:
                            request = Request(function_id, request_id, self.system_time.get_system_runtime())
                            function.put_request(request)
    
    # Multiprocessing
    def try_update_request_record(self):
        manager = multiprocessing.Manager()
        result_dict = manager.dict()
        jobs = []

        for function in self.profile.function_profile:
            result_dict[function.function_id] = manager.dict()
            for request in function.get_request_record().get_undone_request_record():
                result_dict[function.function_id][request.request_id] = manager.dict()
                result_dict[function.function_id][request.request_id]["is_done"] = False # Default value
                
                p = multiprocessing.Process(
                    target=request.try_update,
                    args=(
                        result_dict, 
                        self.system_time.get_system_runtime(), 
                        self.couch_link
                    )
                )
                jobs.append(p)
                p.start()
        
        for p in jobs:
            p.join()

        # Update requests according to the result dict
        # Return the timeout requests and rewards for done requests at this timestep
        total_timeout = 0
        total_error = 0
        total_completion_time = 0
        done_request_dict = {}

        for function in self.profile.function_profile:
            function_id = function.get_function_id()
            done_request_dict[function_id] = []

            for request in function.get_request_record().get_undone_request_record():
                request_id = request.get_request_id()

                # Check if done
                is_done = result_dict[function_id][request_id]["is_done"] 
                if is_done is True:
                    done_time = self.system_time.get_system_runtime()
                    is_timeout = result_dict[function_id][request_id]["is_timeout"] 
                    is_success = result_dict[function_id][request_id]["is_success"] 
                    duration = result_dict[function_id][request_id]["duration"]
                    is_cold_start = result_dict[function_id][request_id]["is_cold_start"]

                    total_completion_time = total_completion_time + duration

                    # Check if timeout
                    if is_timeout is True:
                        total_timeout = total_timeout + 1

                    # Check if error
                    if is_success is False:
                        total_error = total_error + 1

                    # Set updates for done requests
                    request.set_updates(
                        is_done=is_done,
                        done_time=done_time,
                        is_timeout=is_timeout,
                        is_success=is_success,
                        completion_time=duration,
                        is_cold_start=is_cold_start
                    )
                    done_request_dict[function_id].append(request)
            
        # Update request cord of each function
        for function in self.profile.get_function_profile():
            function.get_request_record().update_request(done_request_dict[function.get_function_id()])

        return total_timeout, total_error, total_completion_time

    # Multiprocessing
    def query_resource_utils(self, invoker, result_dict):
        cpu_util = float(self.redis_client.hget(invoker, "cpu_util"))
        memory_util = float(self.redis_client.hget(invoker, "memory_util"))

        result_dict[invoker]["cpu_util"] = cpu_util
        result_dict[invoker]["memory_util"] = memory_util

    # Multiprocessing
    def update_resource_utils(self):
        manager = multiprocessing.Manager()
        result_dict = manager.dict()
        jobs = []

        for i in range(self.n_invoker):
            invoker = "invoker{}".format(i)
            result_dict[invoker] = manager.dict()

            p = multiprocessing.Process(
                target=self.query_resource_utils,
                args=(invoker, result_dict)
            )
            jobs.append(p)
            p.start()

        for p in jobs:
            p.join()
        
        for invoker in result_dict.keys():
            cpu_util = result_dict[invoker]["cpu_util"]
            memory_util = result_dict[invoker]["memory_util"]
            self.resource_utils_record.put_resource_utils(invoker, cpu_util, memory_util)

    def refresh_openwhisk(self):
        cmd = "cd ../ansible && sudo ansible-playbook -i environments/distributed openwhisk.yml && cd ../LambdaRM"
        run_cmd(cmd)
        time.sleep(30)

    def cool_down_openwhisk(self):
        if self.cool_down == "refresh":
            self.refresh_openwhisk()
        else:
            time.sleep(self.cool_down)
                                        
    def get_n_undone_request_from_profile(self):
        n_undone_request = 0
        for function in self.profile.function_profile:
            n_undone_request = n_undone_request + function.get_request_record().get_undone_size()

        return n_undone_request

    # Deprecated
    # def get_current_timeout_num(self):
    #     n_timeout = 0
    #     for function in self.profile.function_profile:
    #         n_timeout = n_timeout + function.get_request_record().get_current_timeout_size(self.system_time.get_system_runtime())

    #     return n_timeout

    def get_total_timeout_num(self):
        n_timeout = 0
        for function in self.profile.get_function_profile():
            n_timeout = n_timeout + function.get_request_record().get_timeout_size()

        return n_timeout

    def get_total_error_num(self):
        n_error = 0
        for function in self.profile.get_function_profile():
            n_error = n_error + function.get_request_record().get_error_size()

        return n_error

    def get_avg_completion_time(self):
        request_num = 0
        total_completion_time = 0

        for function in self.profile.function_profile:
            _, r, t = function.get_request_record().get_avg_completion_time()
            request_num = request_num + r
            total_completion_time = total_completion_time + t
            
        if request_num == 0:
            avg_completion_time = 0
        else:
            avg_completion_time = total_completion_time / request_num

        return avg_completion_time

    def get_avg_completion_time_per_function(self):
        avg_completion_time_per_function = {}

        for function in self.profile.get_function_profile():
            avg_completion_time_per_function[function.get_function_id()] = function.get_avg_completion_time()

        return avg_completion_time_per_function

    def get_request_record_dict(self):
        request_record_dict = {}
        for function in self.profile.function_profile:
            request_record_dict[function.function_id] = {}
            avg_completion_time, _, _ = function.get_request_record().get_avg_completion_time()
            avg_interval = function.get_avg_interval(self.system_time.get_system_runtime())
            cpu = function.get_cpu()
            memory = function.get_memory()
            request_record_dict[function.function_id]["avg_completion_time"] = avg_completion_time
            request_record_dict[function.function_id]["avg_interval"] = avg_interval
            request_record_dict[function.function_id]["cpu"] = cpu
            request_record_dict[function.function_id]["memory"] = memory

        return request_record_dict

    def get_resource_utils_record(self):
        self.resource_utils_record.calculate_avg_resource_utils()
        return self.resource_utils_record.get_record()

    def get_function_throughput(self):
        throughput = 0
        for function in self.profile.get_function_profile():
            request_record = function.get_request_record()
            throughput = throughput + request_record.get_success_size() + request_record.get_timeout_size() + request_record.get_error_size()

        return throughput

    # Multiprocessing
    def query_invoker_state(self, invoker, result_dict):
        available_cpu = int(self.redis_client.hget(invoker, "available_cpu"))
        available_memory = int(self.redis_client.hget(invoker, "available_memory"))
        current_cpu_shares = int(self.redis_client.hget(invoker, "current_cpu_shares"))

        result_dict[invoker]["available_cpu"] = available_cpu
        result_dict[invoker]["available_memory"] = available_memory
        result_dict[invoker]["current_cpu_shares"] = current_cpu_shares

    # Multiprocessing
    def get_observation(self):
        # Controller state
        controller_state = []
        n_undone_request = int(self.redis_client.get("n_undone_request"))
        controller_state.append(n_undone_request)

        # Invoker state
        invoker_state = []
        total_available_cpu = 0
        total_available_memory = 0

        manager = multiprocessing.Manager()
        result_dict = manager.dict()
        jobs = []

        for i in range(self.n_invoker):
            invoker = "invoker{}".format(i) 
            result_dict[invoker] = manager.dict()

            p = multiprocessing.Process(
                target=self.query_invoker_state,
                args=(invoker, result_dict)
            )
            jobs.append(p)
            p.start()

        for p in jobs:
            p.join()

        for invoker in result_dict.keys():
            available_cpu = result_dict[invoker]["available_cpu"]
            available_memory = result_dict[invoker]["available_memory"]
            current_cpu_shares = result_dict[invoker]["current_cpu_shares"]

            invoker_state.append(available_cpu)
            invoker_state.append(available_memory)
            invoker_state.append(current_cpu_shares)
            
            total_available_cpu = total_available_cpu + available_cpu
            total_available_memory = total_available_memory + available_memory

        # Function state
        function_state = []
        for function in self.profile.function_profile:
            function_state.append(function.get_cpu())
            function_state.append(function.get_memory())
            function_state.append(function.get_avg_interval(self.system_time.get_system_runtime()))
            function_state.append(function.get_avg_completion_time())
            function_state.append(function.get_is_cold_start())
        
        # Observation space size: 1+3*n+5*m
        #
        # [n_undone_request,
        #  invoker_1_available_cpu, 
        #  invoker_1_available_memory,
        #  invoker_1_current_cpu_shares,
        #  .
        #  .
        #  .
        #  invoker_n_available_cpu, 
        #  invoker_n_available_memory,
        #  invoker_n_current_cpu_shares,
        #  function_1_cpu,
        #  function_1_memory,
        #  function_1_avg_interval,
        #  function_1_avg_completion_time,
        #  function_1_is_cold_start,
        #  .
        #  .
        #  .
        #  function_m_cpu,
        #  function_m_memory,
        #  function_m_avg_interval,
        #  function_m_avg_completion_time,
        #  function_m_is_cold_start]
        observation = np.hstack(
            (
                np.array(controller_state),
                np.array(invoker_state),
                np.array(function_state)
            )
        )

        return observation, total_available_cpu, total_available_memory

    def get_reward(
        self, 
        total_timeout, 
        total_error,
        interval, 
        total_completion_time
    ):
        # Penalty for timeout requests
        timeout_reward = - self.fail_penalty * total_timeout

        # Penalty for error requests
        error_reward = - self.fail_penalty * total_error

        # Penalty for success requests
        success_reward = - total_completion_time
        
        # Total reward
        reward = timeout_reward + error_reward + success_reward

        return reward

    def get_done(self, observation=None):
        done = False

        if observation is not None:
            n_undone_request = observation[0]
        else:
            n_undone_request = self.get_n_undone_request_from_profile()
        if self.system_time.get_system_step() >= self.timetable.get_size() and n_undone_request == 0:
            done = True
            
        return done

    def get_info(
        self,
        total_available_cpu=None,
        total_available_memory=None
    ):
        info = {
            "system_step": self.system_time.get_system_step(),
            "avg_completion_time": self.get_avg_completion_time(),
            "avg_completion_time_per_function": self.get_avg_completion_time_per_function(),
            "timeout_num": self.get_total_timeout_num(),
            "error_num": self.get_total_error_num(),
            "request_record_dict": self.get_request_record_dict(),
            "system_runtime": self.system_time.get_system_runtime(),
            "function_throughput": self.get_function_throughput()
        }

        if total_available_cpu is not None:
            info["total_available_cpu"] = total_available_cpu

        if total_available_memory is not None:
            info["total_available_memory"] = total_available_memory

        if self.get_done() is True:
            info["resource_utils_record"] = self.get_resource_utils_record()

        return info

    def step(self, action=None):
        is_valid_action = self.update_function_profile(action)
        
        if is_valid_action is True: # THE WORLD!
            # Get observation for next state
            observation, total_available_cpu, total_available_memory = self.get_observation() 
            reward = 0
        else: # Time starts proceeding
            interval = self.system_time.step()
            # print("system_step: {}, system_runtime: {}, interval: {}".format(
            #     self.system_time.get_system_step(), 
            #     self.system_time.get_system_runtime(), 
            #     interval
            #     )
            # )
            
            # Update functions on OpenWhisk
            # before_update = time.time()
            self.update_openwhisk()
            # after_update = time.time()
            # print("Update overhead: {}".format(after_update - before_update))

            # Invoke functions according to timetable
            # before_invoke = time.time()
            self.invoke_openwhisk()
            # after_invoke = time.time()
            # print("Invoke overhead: {}".format(after_invoke - before_invoke))

            # Update resource utils
            # before_utils = time.time()
            self.update_resource_utils()
            # after_utils = time.time()
            # print("Utils overhead: {}".format(after_utils - before_utils))

            # Try to update undone requests
            # before_try = time.time()
            total_timeout, total_error, total_completion_time = self.try_update_request_record()
            # after_try = time.time()
            # print("Try overhead: {}".format(after_try - before_try))
            # print("")

            # Get observation for next state
            observation, total_available_cpu, total_available_memory = self.get_observation() 
            reward = self.get_reward(
                total_timeout=total_timeout,
                total_error=total_error,
                interval=interval,
                total_completion_time=total_completion_time
            )

            # Reset resource adjust direction for each function 
            for function in self.profile.function_profile:
                function.reset_resource_adjust_direction()

        # Done?
        done = self.get_done()
        
        # Return information
        info = self.get_info(
            total_available_cpu=total_available_cpu,
            total_available_memory=total_available_memory
        )
        
        return observation, reward, done, info

    def reset(self):
        self.system_time.reset()
        self.profile.reset()
        self.resource_utils_record.reset()
        
        observation, total_available_cpu, total_available_memory = self.get_observation()
        
        return observation

    #
    # Fixed RM
    #

    def fixed_rm(
        self,
        max_episode=5,
        plot_prefix_name="FixedRM",
        save_plot=False,
        show_plot=True,
    ):
        rm = plot_prefix_name
        
        # Trends recording
        reward_trend = []
        avg_completion_time_trend = []
        timeout_num_trend = []
        error_num_trend = []
        avg_completion_time_per_function_trend = {}
        for function in self.profile.get_function_profile():
            avg_completion_time_per_function_trend[function.get_function_id()] = []
        
        # Start training
        for episode in range(max_episode):
            observation = self.reset()

            actual_time = 0
            system_time = 0
            system_runtime = 0
            reward_sum = 0

            function_throughput_list = []

            # Set up logger
            logger = self.logger_wrapper.get_logger(rm, True)
            
            while True:
                actual_time = actual_time + 1
                action = self.action_space - 1
                next_observation, reward, done, info = self.step(action)

                if system_time < info["system_step"]:
                    system_time = info["system_step"]
                    system_runtime = info["system_runtime"]
                    function_throughput_list.append(info["function_throughput"])
                    
                logger.debug("")
                logger.debug("System runtime: {}".format(system_runtime))
                logger.debug("Actual timestep {}".format(actual_time))
                logger.debug("System timestep {}".format(system_time))
                logger.debug("Take action: {}".format(action))
                logger.debug("Observation: {}".format(observation))
                logger.debug("Reward: {}".format(reward))

                reward_sum = reward_sum + reward
                
                if done:
                    avg_completion_time = info["avg_completion_time"]
                    timeout_num = info["timeout_num"]
                    error_num = info["error_num"]
                    
                    logger.info("")
                    logger.info("**********")
                    logger.info("**********")
                    logger.info("**********")
                    logger.info("")
                    logger.info("Epoch finished after {} episodes:".format(episode))
                    logger.info("Total {} system runtime".format(system_runtime))
                    logger.info("Total {} actual timesteps".format(actual_time))
                    logger.info("Total {} system timesteps".format(system_time))
                    logger.info("Total reward: {}".format(reward_sum))
                    logger.info("Avg completion time: {}".format(avg_completion_time))
                    logger.info("Timeout num: {}".format(timeout_num))
                    logger.info("Error num: {}".format(error_num))
                    
                    reward_trend.append(reward_sum)
                    avg_completion_time_trend.append(avg_completion_time)
                    timeout_num_trend.append(timeout_num)
                    error_num_trend.append(error_num)

                    # Log average completion time per function
                    avg_completion_time_per_function = info["avg_completion_time_per_function"]
                    for function_id in avg_completion_time_per_function.keys():
                        avg_completion_time_per_function_trend[function_id].append(avg_completion_time_per_function[function_id])

                    # Log resource utilization 
                    resource_utils_record = info["resource_utils_record"]
                    self.log_resource_utils(False, rm, episode, resource_utils_record)

                    # Log function throughput
                    self.log_function_throughput(False, rm, episode, function_throughput_list)
                    
                    break
                
                observation = next_observation

            # Cool down OpenWhisk
            self.cool_down_openwhisk()
        
        # Plot each episode 
        plotter = Plotter()
        
        if save_plot is True:
            plotter.plot_save(
                prefix_name=plot_prefix_name, 
                reward_trend=reward_trend, 
                avg_completion_time_trend=avg_completion_time_trend,
                timeout_num_trend=timeout_num_trend, 
                error_num_trend=error_num_trend, 
            )
        if show_plot is True:
            plotter.plot_show(
                reward_trend=reward_trend, 
                avg_completion_time_trend=avg_completion_time_trend, 
                timeout_num_trend=timeout_num_trend, 
                error_num_trend=error_num_trend, 
            )

        # Log trends
        self.log_trends(
            rm_name=rm,
            reward_trend=reward_trend,
            overwrite=False,
            avg_completion_time_trend=avg_completion_time_trend,
            avg_completion_time_per_function_trend=avg_completion_time_per_function_trend,
            timeout_num_trend=timeout_num_trend,
            error_num_trend=error_num_trend,
            loss_trend=None,
        )

    #
    # Greedy RM
    #

    def greedy_rm(
        self,
        max_episode=10,
        plot_prefix_name="GreedyRM",
        save_plot=False,
        show_plot=True,
    ):
        #
        # Encode sequential resource changes into discrete actions
        #

        def encode_action(function_profile, resource_adjust_list):
            actions = []
            
            for function in function_profile:
                for key in resource_adjust_list.keys():
                    if function.function_id == key:
                        index = function_profile.index(function)
                        
                        if resource_adjust_list[key][0] != -1:
                            adjust_cpu = index*4 + resource_adjust_list[key][0]
                            actions.append(adjust_cpu)
                        if resource_adjust_list[key][1] != -1:
                            adjust_memory = index*4 + resource_adjust_list[key][1]
                            actions.append(adjust_memory)
                            
            return actions

        rm = plot_prefix_name
        
        # Record trends
        reward_trend = []
        avg_completion_time_trend = []
        timeout_num_trend = []
        error_num_trend = []
        avg_completion_time_per_function_trend = {}
        for function in self.profile.get_function_profile():
            avg_completion_time_per_function_trend[function.get_function_id()] = []
        
        # Start training
        for episode in range(max_episode):
            observation = self.reset()

            reward_sum = 0
            actual_time = 0
            system_time = 0
            system_runtime = 0

            function_throughput_list = []
            
            action = self.action_space - 1
            
            # Set up logger
            logger = self.logger_wrapper.get_logger(rm, True)

            # Set up completion time record
            completion_time_decay_record = {}
            for function in self.profile.function_profile:
                completion_time_decay_record[function.function_id] = {}
                completion_time_decay_record[function.function_id]["old_completion_time"] = 0
                completion_time_decay_record[function.function_id]["new_completion_time"] = 0
                completion_time_decay_record[function.function_id]["decay"] = 1.0

            while True:
                actual_time = actual_time + 1
                observation, reward, done, info = self.step(action)
                
                if system_time < info["system_step"]:
                    system_time = info["system_step"]
                    system_runtime = info["system_runtime"]
                    function_throughput_list.append(info["function_throughput"])

                    record = info["request_record_dict"]
                    # total_available_cpu = 8*10
                    # total_available_memory = 8*10
                    total_available_cpu = info["total_available_cpu"]
                    total_available_memory = info["total_available_memory"] / 256
                    
                    #
                    # Greedy resource adjustment: Completion time decay
                    #

                    # Adjustment for each function
                    resource_adjust_list = {}
                    for function in self.profile.function_profile:
                        resource_adjust_list[function.function_id] = []
                    
                    # Update completion time decay for each function
                    for id in record.keys():
                        old_completion_time = completion_time_decay_record[id]["new_completion_time"]
                        new_completion_time = record[id]["avg_completion_time"]

                        completion_time_decay_record[id]["old_completion_time"] = old_completion_time
                        completion_time_decay_record[id]["new_completion_time"] = new_completion_time

                        # Check if it's just a beginning
                        if old_completion_time != 0 and new_completion_time != 0: 
                            decay = new_completion_time / old_completion_time
                            completion_time_decay_record[id]["decay"] = decay

                        cpu = record[id]["cpu"]
                        memory = record[id]["memory"]
                        total_available_cpu = total_available_cpu - cpu
                        total_available_memory = total_available_memory - memory

                    # Increase resources in a greedy way. 
                    pq = queue.PriorityQueue()
                    for id in completion_time_decay_record.keys():
                        decay = completion_time_decay_record[id]["decay"]
                        if decay <= 1.0:
                            resource_adjust_list[id] = [-1, -1] # Hold
                        else:
                            pq.put((-decay, id))

                    while pq.empty() is False:
                        id = pq.get()[1]
                        avg_interval = record[id]["avg_interval"]
                        
                        if avg_interval*1 <= total_available_cpu and avg_interval*1 <= total_available_memory:
                            # Increase one slot for CPU and memory
                            resource_adjust_list[id] = [1, 3] 
                            total_available_cpu = total_available_cpu - avg_interval*1
                            total_available_memory = total_available_memory - avg_interval*1
                        else:
                            # Hold
                            resource_adjust_list[id] = [-1, -1] 
                    
                    action = encode_action(self.profile.function_profile, resource_adjust_list)

                logger.debug("")
                logger.debug("Actual timestep {}".format(actual_time))
                logger.debug("System timestep {}".format(system_runtime))
                logger.debug("Take action: {}".format(action))
                logger.debug("Observation: {}".format(observation))
                logger.debug("Reward: {}".format(reward))
                
                reward_sum = reward_sum + reward
                
                if done:
                    avg_completion_time = info["avg_completion_time"]
                    timeout_num = info["timeout_num"]
                    error_num = info["error_num"]
                    
                    logger.info("")
                    logger.info("**********")
                    logger.info("**********")
                    logger.info("**********")
                    logger.info("")
                    logger.info("Episode {} finished after:".format(episode))
                    logger.info("{} actual timesteps".format(actual_time))
                    logger.info("{} system timesteps".format(system_runtime))
                    logger.info("Total reward: {}".format(reward_sum))
                    logger.info("Avg completion time: {}".format(avg_completion_time))
                    logger.info("Timeout num: {}".format(timeout_num))
                    logger.info("Error num: {}".format(error_num))
                    
                    reward_trend.append(reward_sum)
                    avg_completion_time_trend.append(avg_completion_time)
                    timeout_num_trend.append(timeout_num)
                    error_num_trend.append(error_num)

                    # Log average completion time per function
                    avg_completion_time_per_function = info["avg_completion_time_per_function"]
                    for function_id in avg_completion_time_per_function.keys():
                        avg_completion_time_per_function_trend[function_id].append(avg_completion_time_per_function[function_id])

                    # Log resource utilization 
                    resource_utils_record = info["resource_utils_record"]
                    self.log_resource_utils(False, rm, episode, resource_utils_record)

                    # Log function throughput
                    self.log_function_throughput(False, rm, episode, function_throughput_list)
                    
                    break
            
            # Cool down OpenWhisk
            self.cool_down_openwhisk()
        
        # Plot each episode 
        plotter = Plotter()
        
        if save_plot is True:
            plotter.plot_save(
                prefix_name=plot_prefix_name, 
                reward_trend=reward_trend, 
                avg_completion_time_trend=avg_completion_time_trend,
                timeout_num_trend=timeout_num_trend,
                error_num_trend=error_num_trend,
            )
        if show_plot is True:
            plotter.plot_show(
                reward_trend=reward_trend, 
                avg_completion_time_trend=avg_completion_time_trend,
                timeout_num_trend=timeout_num_trend,
                error_num_trend=error_num_trend,
            )
        
        # Log trends
        self.log_trends(
            rm_name=rm,
            reward_trend=reward_trend,
            overwrite=False,
            avg_completion_time_trend=avg_completion_time_trend,
            avg_completion_time_per_function_trend=avg_completion_time_per_function_trend,
            timeout_num_trend=timeout_num_trend,
            error_num_trend=error_num_trend,
            loss_trend=None,
        )

    #
    # Policy gradient training
    #

    def train(
        self,
        max_episode=150,
        plot_prefix_name="LambdaRM_train",
        save_plot=False,
        show_plot=True,
    ):
        rm = plot_prefix_name
        
        # Set up policy gradient agent
        pg_agent = PPO2Agent(
            observation_dim=self.state_space,
            action_dim=self.action_space,
            hidden_dims=[64, 32],
            learning_rate=0.002,
            discount_factor=1,
            ppo_clip=0.2,
            ppo_steps=5
        )
        
        # Record trends
        reward_trend = []
        avg_completion_time_trend = []
        timeout_num_trend = []
        error_num_trend = []
        loss_trend = []
        avg_completion_time_per_function_trend = {}
        for function in self.profile.get_function_profile():
            avg_completion_time_per_function_trend[function.get_function_id()] = []
        
        # Pinpoint best avg completion time model
        min_avg_completion_time = 10e8
        min_timeout_or_error_num = 10e8
        timeout_min_avg_completion_time = 10e8

        # Start training
        for episode in range(max_episode):
            observation = self.reset()
            pg_agent.reset()

            actual_time = 0
            system_time = 0
            system_runtime = 0
            reward_sum = 0

            function_throughput_list = []

            # Set up logger
            logger = self.logger_wrapper.get_logger(rm, True)
            
            while True:
                actual_time = actual_time + 1
                action, value_pred, log_prob = pg_agent.choose_action(observation)
                next_observation, reward, done, info = self.step(action.item())

                pg_agent.record_trajectory(
                    observation=observation, 
                    action=action, 
                    reward=reward,
                    value=value_pred,
                    log_prob=log_prob
                )
                
                if system_time < info["system_step"]:
                    system_time = info["system_step"]
                    system_runtime = info["system_runtime"]
                    function_throughput_list.append(info["function_throughput"])
                    
                logger.debug("")
                logger.debug("Actual timestep {}".format(actual_time))
                logger.debug("System timestep {}".format(system_runtime))
                logger.debug("Take action: {}".format(action))
                logger.debug("Observation: {}".format(observation))
                logger.debug("Reward: {}".format(reward))
                
                reward_sum = reward_sum + reward
                
                if done:
                    avg_completion_time = info["avg_completion_time"]
                    timeout_num = info["timeout_num"]
                    error_num = info["error_num"]
                    
                    # Save best model that has min timeouts
                    if timeout_num + error_num < min_timeout_or_error_num:
                        min_timeout_or_error_num = timeout_num + error_num
                        pg_agent.save("ckpt/best_timeout_or_error.pth")
                    elif timeout_num + error_num == min_timeout_or_error_num:
                        if avg_completion_time < timeout_min_avg_completion_time:
                            timeout_min_avg_completion_time = avg_completion_time
                            pg_agent.save("ckpt/best_timeout_or_error.pth")

                    # Save best model that has min avg completion time
                    if avg_completion_time < min_avg_completion_time:
                        min_avg_completion_time = avg_completion_time
                        pg_agent.save("ckpt/best_avg_completion_time.pth")

                    loss = pg_agent.propagate()
                    
                    logger.info("")
                    logger.info("**********")
                    logger.info("**********")
                    logger.info("**********")
                    logger.info("")
                    logger.info("Episode {} finished after:".format(episode))
                    logger.info("{} actual timesteps".format(actual_time))
                    logger.info("{} system timesteps".format(system_runtime))
                    logger.info("Total reward: {}".format(reward_sum))
                    logger.info("Avg completion time: {}".format(avg_completion_time))
                    logger.info("Timeout num: {}".format(timeout_num))
                    logger.info("Error num: {}".format(error_num))
                    logger.info("Loss: {}".format(loss))
                    
                    reward_trend.append(reward_sum)
                    avg_completion_time_trend.append(avg_completion_time)
                    timeout_num_trend.append(timeout_num)
                    error_num_trend.append(error_num)
                    loss_trend.append(loss)
                    
                    # # Log average completion time per function
                    # avg_completion_time_per_function = info["avg_completion_time_per_function"]
                    # for function_id in avg_completion_time_per_function.keys():
                    #     avg_completion_time_per_function_trend[function_id].append(avg_completion_time_per_function[function_id])

                    # # Log resource utilization 
                    # resource_utils_record = info["resource_utils_record"]
                    # self.log_resource_utils(False, rm, episode, resource_utils_record)

                    # # Log function throughput
                    # self.log_function_throughput(False, rm, episode, function_throughput_list)
                    
                    break
                
                observation = next_observation

            # Cool down OpenWhisk
            self.cool_down_openwhisk()
        
        # Plot each episode 
        plotter = Plotter()
        
        if save_plot is True:
            plotter.plot_save(
                prefix_name=plot_prefix_name, 
                reward_trend=reward_trend, 
                avg_completion_time_trend=avg_completion_time_trend,
                timeout_num_trend=timeout_num_trend, 
                error_num_trend=error_num_trend, 
                loss_trend=loss_trend
            )
        if show_plot is True:
            plotter.plot_show(
                reward_trend=reward_trend, 
                avg_completion_time_trend=avg_completion_time_trend, 
                timeout_num_trend=timeout_num_trend, 
                error_num_trend=error_num_trend, 
                loss_trend=loss_trend
            )

        # Log trends
        self.log_trends(
            rm_name=rm,
            reward_trend=reward_trend,
            overwrite=False,
            avg_completion_time_trend=avg_completion_time_trend,
            avg_completion_time_per_function_trend=avg_completion_time_per_function_trend,
            timeout_num_trend=timeout_num_trend,
            error_num_trend=error_num_trend,
            loss_trend=loss_trend,
        )

    def eval(
        self,
        max_episode=10,
        checkpoint_path="ckpt/best_avg_completion_time.pth",
        plot_prefix_name="LambdaRM_eval",
        save_plot=False,
        show_plot=True,
    ):
        rm = plot_prefix_name
        
        # Set up policy gradient agent
        pg_agent = PPO2Agent(
            observation_dim=self.state_space,
            action_dim=self.action_space,
            hidden_dims=[64, 32],
            learning_rate=0.002,
            discount_factor=1,
            ppo_clip=0.2,
            ppo_steps=5
        )

        # Restore checkpoint model
        pg_agent.load(checkpoint_path)
        
        # Record trends
        reward_trend = []
        avg_completion_time_trend = []
        timeout_num_trend = []
        error_num_trend = []
        avg_completion_time_per_function_trend = {}
        for function in self.profile.get_function_profile():
            avg_completion_time_per_function_trend[function.get_function_id()] = []
        
        # Start training
        for episode in range(max_episode):
            observation = self.reset()
            pg_agent.reset()

            actual_time = 0
            system_time = 0
            system_runtime = 0
            reward_sum = 0

            function_throughput_list = []
            
            # Set up logger
            logger = self.logger_wrapper.get_logger(rm, True)

            while True:
                actual_time = actual_time + 1
                action, value_pred, log_prob = pg_agent.choose_action(observation)
                next_observation, reward, done, info = self.step(action.item())

                if system_time < info["system_step"]:
                    system_time = info["system_step"]
                    system_runtime = info["system_runtime"]
                    function_throughput_list.append(info["function_throughput"])
                    
                logger.debug("")
                logger.debug("Actual timestep {}".format(actual_time))
                logger.debug("System timestep {}".format(system_runtime))
                logger.debug("Take action: {}".format(action))
                logger.debug("Observation: {}".format(observation))
                logger.debug("Reward: {}".format(reward))
                
                reward_sum = reward_sum + reward
                
                if done:
                    avg_completion_time = info["avg_completion_time"]
                    timeout_num = info["timeout_num"]
                    error_num = info["error_num"]
                    
                    logger.info("")
                    logger.info("**********")
                    logger.info("**********")
                    logger.info("**********")
                    logger.info("")
                    logger.info("Episode {} finished after:".format(episode))
                    logger.info("{} actual timesteps".format(actual_time))
                    logger.info("{} system timesteps".format(system_runtime))
                    logger.info("Total reward: {}".format(reward_sum))
                    logger.info("Avg completion time: {}".format(avg_completion_time))
                    logger.info("Timeout num: {}".format(timeout_num))
                    logger.info("Error num: {}".format(error_num))
                    
                    reward_trend.append(reward_sum)
                    avg_completion_time_trend.append(avg_completion_time)
                    timeout_num_trend.append(timeout_num)
                    error_num_trend.append(error_num)

                    # Log average completion time per function
                    avg_completion_time_per_function = info["avg_completion_time_per_function"]
                    for function_id in avg_completion_time_per_function.keys():
                        avg_completion_time_per_function_trend[function_id].append(avg_completion_time_per_function[function_id])

                    # Log resource utilization 
                    resource_utils_record = info["resource_utils_record"]
                    self.log_resource_utils(False, rm, episode, resource_utils_record)

                    # Log function throughput
                    self.log_function_throughput(False, rm, episode, function_throughput_list)

                    break
                
                observation = next_observation

            # Cool down OpenWhisk
            self.cool_down_openwhisk()
        
        # Plot each episode 
        plotter = Plotter()
        
        if save_plot is True:
            plotter.plot_save(
                prefix_name=plot_prefix_name, 
                reward_trend=reward_trend, 
                avg_completion_time_trend=avg_completion_time_trend,
                timeout_num_trend=timeout_num_trend, 
                error_num_trend=error_num_trend, 
                loss_trend=None
            )
        if show_plot is True:
            plotter.plot_show(
                reward_trend=reward_trend, 
                avg_completion_time_trend=avg_completion_time_trend, 
                timeout_num_trend=timeout_num_trend, 
                error_num_trend=error_num_trend, 
                loss_trend=None
            )

        # Log trends
        self.log_trends(
            rm_name=rm,
            reward_trend=reward_trend,
            overwrite=False,
            avg_completion_time_trend=avg_completion_time_trend,
            avg_completion_time_per_function_trend=avg_completion_time_per_function_trend,
            timeout_num_trend=timeout_num_trend,
            error_num_trend=error_num_trend,
            loss_trend=None,
        )

    def log_trends(
        self, 
        rm_name,
        overwrite,
        reward_trend,
        avg_completion_time_trend,
        avg_completion_time_per_function_trend,
        timeout_num_trend,
        error_num_trend,
        loss_trend=None,
    ):
        # Log reward trend
        logger = self.logger_wrapper.get_logger("RewardTrends", overwrite)
        logger.debug("")
        logger.debug("**********")
        logger.debug("**********")
        logger.debug("**********")
        logger.debug("")
        logger.debug(time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()))
        logger.debug("{}:".format(rm_name))
        logger.debug(','.join(str(reward) for reward in reward_trend))

        # Log avg completion time trend
        logger = self.logger_wrapper.get_logger("AvgCompletionTimeTrends", overwrite)
        logger.debug("")
        logger.debug("**********")
        logger.debug("**********")
        logger.debug("**********")
        logger.debug("")
        logger.debug(time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()))
        logger.debug("{}:".format(rm_name))
        logger.debug(','.join(str(avg_completion_time) for avg_completion_time in avg_completion_time_trend))

        # Log avg completion time per function trend 
        logger = self.logger_wrapper.get_logger("AvgCompletionTimePerFunctionTrends", overwrite)
        logger.debug("")
        logger.debug("**********")
        logger.debug("**********")
        logger.debug("**********")
        logger.debug("")
        logger.debug(time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()))
        logger.debug("{}:".format(rm_name))
        logger.debug("")
        for function_id in avg_completion_time_per_function_trend.keys():
            logger.debug("{}:".format(function_id))
            logger.debug(','.join(str(avg_completion_time) for avg_completion_time in avg_completion_time_per_function_trend[function_id]))

        # Log timeout number trend
        logger = self.logger_wrapper.get_logger("TimeoutNumTrends", overwrite)
        logger.debug("")
        logger.debug("**********")
        logger.debug("**********")
        logger.debug("**********")
        logger.debug("")
        logger.debug(time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()))
        logger.debug("{}:".format(rm_name))
        logger.debug(','.join(str(timeout_num) for timeout_num in timeout_num_trend))

        # Log error number trend
        logger = self.logger_wrapper.get_logger("ErrorNumTrends", overwrite)
        logger.debug("")
        logger.debug("**********")
        logger.debug("**********")
        logger.debug("**********")
        logger.debug("")
        logger.debug(time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()))
        logger.debug("{}:".format(rm_name))
        logger.debug(','.join(str(error_num) for error_num in error_num_trend))

        # Log loss trend
        if loss_trend is not None:
            logger = self.logger_wrapper.get_logger("LossTrends", overwrite)
            logger.debug("")
            logger.debug("**********")
            logger.debug("**********")
            logger.debug("**********")
            logger.debug("")
            logger.debug(time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()))
            logger.debug("{}:".format(rm_name))
            logger.debug(','.join(str(loss) for loss in loss_trend))

    def log_resource_utils(
        self, 
        overwrite,
        rm_name,
        episode,
        record
    ):
        logger = self.logger_wrapper.get_logger("ResourceUtils", overwrite)
        logger.debug("")
        logger.debug("**********")
        logger.debug("**********")
        logger.debug("**********")
        logger.debug("")
        logger.debug(time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()))
        logger.debug("{} episode {}:".format(rm_name, episode))

        for i in range(self.n_invoker):
            invoker = "invoker{}".format(i)

            logger.debug(invoker)
            logger.debug("cpu_util")
            logger.debug(','.join(str(cpu_util) for cpu_util in record[invoker]["cpu_util"]))
            logger.debug("memory_util")
            logger.debug(','.join(str(memory_util) for memory_util in record[invoker]["memory_util"]))
            logger.debug("avg_cpu_util")
            logger.debug(record[invoker]["avg_cpu_util"])
            logger.debug("avg_memory_util")
            logger.debug(record[invoker]["avg_memory_util"])
            logger.debug("")

        logger.debug("avg_invoker")
        logger.debug("cpu_util")
        logger.debug(','.join(str(cpu_util) for cpu_util in record["avg_invoker"]["cpu_util"]))
        logger.debug("memory_util")
        logger.debug(','.join(str(memory_util) for memory_util in record["avg_invoker"]["memory_util"]))
        logger.debug("avg_cpu_util")
        logger.debug(record["avg_invoker"]["avg_cpu_util"])
        logger.debug("avg_memory_util")
        logger.debug(record["avg_invoker"]["avg_memory_util"])

    def log_function_throughput(
        self,
        overwrite,
        rm_name,
        episode,
        function_throughput_list
    ):
        logger = self.logger_wrapper.get_logger("FunctionThroughput", overwrite)
        logger.debug("")
        logger.debug("**********")
        logger.debug("**********")
        logger.debug("**********")
        logger.debug("")
        logger.debug(time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()))
        logger.debug("{} episode {}:".format(rm_name, episode))
        logger.debug("function_throughput")
        logger.debug(','.join(str(function_throughput) for function_throughput in function_throughput_list))

