import time
import redis
import numpy as np
import matplotlib.pyplot as plt
import multiprocessing
import queue

from logger import Logger
from plotter import Plotter
from ppo2_agent import PPO2Agent
from utils import SystemTime, Request, RequestRecord, ResourceUtilsRecord
from run_command import run_cmd
from params import WSK_CLI



class Framework():
    """ 
    Wrapper for OpenWhisk serverless framework
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

        # Set up request record
        self.request_record = RequestRecord(self.profile.get_function_profile())

        # Set up resource utils record
        self.resource_utils_record = ResourceUtilsRecord(self.n_invoker)

    #
    # Interfaces with OpenWhisk
    #

    def decode_action(self, action):
        function_profile_list = list(self.params.get_function_profile().keys())
        function_index = int(action/4)
        function_id = function_profile_list[function_index].get_function_id()
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
        
        return function_id, resource, adjust
    
    def update_function_profile(self, action):
        function_profile = self.profile.get_function_profile()

        if isinstance(action, list): # WARNING! Only used by greedy RM!
            actions = action
            for act in actions:
                function_id, resource, adjust = self.decode_action(act)
                function = function_profile[function_id]
                # if function_profile[function_id].validate_resource_adjust(resource, adjust) is True:
                #     function_profile[function_id].set_resource_adjust(resource, adjust)
                function.set_resource_adjust(resource, adjust)

                # Set the sequence members as well if it is a function sequence
                if function.get_sequence() is not None:
                    sequence = function.get_sequence()
                    for member_id in sequence:
                        function_profile[member_id].set_resource_adjust(resource, adjust)
            
            return False
        else:
            if action == self.action_space - 1: # Explicit invalid action
                return False
            else:
                function_id, resource, adjust = self.decode_action(action)
                function = function_profile[function_id]
                if function.validate_resource_adjust(resource, adjust) is True:
                    function.set_resource_adjust(resource, adjust)
                    return True
                else:
                    return False # Implicit invalid action

    # # Multiprocessing
    # def update_openwhisk(self):
    #     function_profile = self.profile.get_function_profile()
    #     jobs = []

    #     for function_id in function_profile.keys():
    #         function = function_profile[function_id]
    #         if function.get_is_resource_changed() is True:
    #             p = multiprocessing.Process(
    #                 target=function.update_openwhisk,
    #                 args=(self.couch_link,)
    #             )
    #             jobs.append(p)
    #             p.start()
        
    #     for p in jobs:
    #         p.join()

    def update_openwhisk(self):
        function_profile = self.profile.get_function_profile() 
        sequence_dict = self.profile.get_sequence_dict()

        # Update functions except for sequence entries
        for function_id in function_profile.keys():
            function = function_profile[function_id]
            if function_id not in sequence_dict.keys():
                function.update_openwhisk()
        
        # Collect sequence updates
        updated_sequence_dict = {}
        for entry in sequence_dict.keys():
            member_list = sequence_dict[entry]
            updated_sequence_dict[entry] = []

            for member_id in member_list:
                member_actual_id = function_profile[member_id].get_function_actual_id()
                updated_sequence_dict[entry].append(member_actual_id)

        # Multiprocessing
        def update_sequence(entry, member_list):
            cmd = '{} action update {} --sequence'.format(WSK_CLI, entry)
            for index, member in enumerate(member_list):
                if index == 0:
                    cmd = '{} {}'.format(cmd, member)
                else:
                    cmd = '{},{}'.format(cmd, member)

            run_cmd(cmd)

        # Update function sequences
        jobs = []

        for entry in updated_sequence_dict.keys():
            member_list = updated_sequence_dict[entry]
            p = multiprocessing.Process(
                target=update_sequence,
                args=(entry, member_list)
            )
            jobs.append(p)
            p.start()
        
        for p in jobs:
            p.join()

    # Multiprocessing
    def invoke_openwhisk(self):
        function_profile = self.profile.get_function_profile()
        timestep = self.timetable.get_timestep(self.system_time.get_system_step()-1)
        if timestep is not None:
            manager = multiprocessing.Manager()
            result_dict = manager.dict()
            jobs = []

            for function_id in timestep.keys():
                invoke_num = timestep[function_id]
                function = function_profile[function_id]
                result_dict[function_id] = manager.list()
                for _ in range(invoke_num):
                    p = multiprocessing.Process(
                        target=function.invoke_openwhisk,
                        args=(result_dict,)
                    )
                    jobs.append(p)
                    p.start()
            
            for p in jobs:
                p.join()

            # Create requests according to the result dict
            for function_id in function_profile.keys():
                for request_id in result_dict[function_id]:
                    request = Request(function_id, request_id, self.system_time.get_system_runtime())
                    self.request_record.put_requests(request)
    
    # Multiprocessing
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
                result_dict[function_id][request_id]["is_done"] = False # Default value
                
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
        done_request_list = []

        for function_id in function_profile.keys():
            for request in self.request_record.get_undone_request_record_per_function(function_id):
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
                    done_request_list.append(request)
            
        # Update request records
        self.request_record.update_requests(done_request_list)

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
        # cmd = "cd ../ansible && sudo ansible-playbook -i environments/distributed openwhisk.yml && cd ../LambdaRM"
        cmd = "./refresh_openwhisk.sh"
        run_cmd(cmd)
        time.sleep(30)

    def refresh_couchdb_and_openwhisk(self):
        cmd = "./refresh_couchdb_and_openwhisk.sh"
        run_cmd(cmd)
        time.sleep(30)

    def cool_down_openwhisk(self):
        if self.cool_down == "refresh_openwhisk":
            self.refresh_openwhisk()
        elif self.cool_down == "refresh_couchdb_and_openwhisk":
            self.refresh_couchdb_and_openwhisk()
        else:
            time.sleep(self.cool_down)
                                        
    def get_function_dict(self):
        function_profile = self.profile.get_function_profile()
        function_dict = {}
        for function_id in function_profile.keys():
            function = function_profile[function_id]
            function_dict[function_id] = {}

            avg_completion_time = self.request_record.get_avg_completion_time_per_function(function_id)
            avg_interval = self.request_record.get_avg_interval_per_function(self.system_time.get_system_runtime(), function_id)
            cpu = function.get_cpu()
            memory = function.get_memory()
            total_sequence_size = function.get_total_sequence_size()

            is_success = False
            i = 1
            while i <= self.request_record.get_total_size_per_function(function_id):
                request = self.request_record.get_total_request_record_per_function(function_id)[-i]
                if request.get_is_done() is True:
                    is_success = request.get_is_success()
                    break

                i = i + 1

            function_dict[function_id]["avg_completion_time"] = avg_completion_time
            function_dict[function_id]["avg_interval"] = avg_interval
            function_dict[function_id]["cpu"] = cpu
            function_dict[function_id]["memory"] = memory
            function_dict[function_id]["total_sequence_size"] = total_sequence_size
            function_dict[function_id]["is_success"] = is_success

        return function_dict

    def get_resource_utils_record(self):
        self.resource_utils_record.calculate_avg_resource_utils()
        return self.resource_utils_record.get_resource_utils_record()

    def get_function_throughput(self):
        throughput = self.request_record.get_success_size() + \
            self.request_record.get_timeout_size() + \
                self.request_record.get_error_size()
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
        function_profile = self.profile.get_function_profile()

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
        for function_id in function_profile.keys():
            function = function_profile[function_id]
            function_state.append(function.get_cpu())
            function_state.append(function.get_memory())
            function_state.append(self.request_record.get_avg_interval_per_function(self.system_time.get_system_runtime(), function_id))
            function_state.append(self.request_record.get_avg_completion_time_per_function(function_id))
            function_state.append(self.request_record.get_is_cold_start_per_function(function_id))
        
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
            n_undone_request = self.request_record.get_undone_size()
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
            "avg_completion_time": self.request_record.get_avg_completion_time(),
            "timeout_num": self.request_record.get_timeout_size(),
            "error_num": self.request_record.get_error_size(),
            "function_dict": self.get_function_dict(),
            "system_runtime": self.system_time.get_system_runtime(),
            "function_throughput": self.get_function_throughput(),
            "request_record": self.request_record
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
            function_profile = self.profile.get_function_profile()
            for function_id in function_profile.keys():
                function = function_profile[function_id]
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
        self.request_record.reset()
        
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

        # Set up logger
        logger = self.logger_wrapper.get_logger(rm, True)
        
        # Trends recording
        reward_trend = []
        avg_completion_time_trend = []
        timeout_num_trend = []
        error_num_trend = []
        avg_completion_time_per_function_trend = {}
        function_profile = self.profile.get_function_profile()
        for function_id in function_profile.keys():
            avg_completion_time_per_function_trend[function_id] = []
        
        # Start training
        for episode in range(max_episode):
            observation = self.reset()

            actual_time = 0
            system_time = 0
            system_runtime = 0
            reward_sum = 0

            function_throughput_list = []
            
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
                    request_record = info["request_record"]
                    for function_id in avg_completion_time_per_function_trend.keys():
                        avg_completion_time_per_function_trend[function_id].append(
                            request_record.get_avg_completion_time_per_function(function_id)
                        )

                    # Log resource utilization 
                    resource_utils_record = info["resource_utils_record"]
                    self.log_resource_utils(
                        rm_name=rm, 
                        overwrite=False, 
                        episode=episode, 
                        resource_utils_record=resource_utils_record
                    )

                    # Log function throughput
                    self.log_function_throughput(
                        rm_name=rm, 
                        overwrite=False, 
                        episode=episode, 
                        function_throughput_list=function_throughput_list
                    )
                    
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
            function_profile_list = list(function_profile.keys())
            actions = []
            
            for index, function_id in enumerate(function_profile_list):
                if resource_adjust_list[function_id][0] != -1:
                    adjust_cpu = index*4 + resource_adjust_list[function_id][0]
                    actions.append(adjust_cpu)
                if resource_adjust_list[function_id][1] != -1:
                    adjust_memory = index*4 + resource_adjust_list[function_id][1]
                    actions.append(adjust_memory)
                            
            return actions

        rm = plot_prefix_name

        # Set up logger
        logger = self.logger_wrapper.get_logger(rm, True)
        
        # Record trends
        reward_trend = []
        avg_completion_time_trend = []
        timeout_num_trend = []
        error_num_trend = []
        avg_completion_time_per_function_trend = {}
        function_profile = self.profile.get_function_profile()
        for function_id in function_profile.keys():
            avg_completion_time_per_function_trend[function_id] = []
        
        # Start training
        for episode in range(max_episode):
            observation = self.reset()

            reward_sum = 0
            actual_time = 0
            system_time = 0
            system_runtime = 0

            function_throughput_list = []
            
            action = self.action_space - 1

            # Set up completion time record
            completion_time_decay_record = {}
            for function_id in function_profile.keys():
                completion_time_decay_record[function_id] = {}
                completion_time_decay_record[function_id]["old_completion_time"] = 0
                completion_time_decay_record[function_id]["new_completion_time"] = 0
                completion_time_decay_record[function_id]["decay"] = 1.0

            while True:
                actual_time = actual_time + 1
                observation, reward, done, info = self.step(action)
                
                if system_time < info["system_step"]:
                    system_time = info["system_step"]
                    system_runtime = info["system_runtime"]
                    function_throughput_list.append(info["function_throughput"])

                    record = info["function_dict"]
                    # total_available_cpu = 8*10
                    # total_available_memory = 32*10
                    total_available_cpu = info["total_available_cpu"]
                    total_available_memory = info["total_available_memory"] / 256
                    
                    #
                    # Greedy resource adjustment: Completion time decay
                    #

                    # Adjustment for each function, default hold
                    resource_adjust_list = {}
                    for function_id in function_profile.keys():
                        resource_adjust_list[function_id] = [-1, -1]
                    
                    # Update completion time decay for each function
                    for id in record.keys():
                        old_completion_time = completion_time_decay_record[id]["new_completion_time"]
                        new_completion_time = record[id]["avg_completion_time"]

                        completion_time_decay_record[id]["old_completion_time"] = old_completion_time
                        completion_time_decay_record[id]["new_completion_time"] = new_completion_time

                        # Check if it's just beginning
                        if old_completion_time != 0 and new_completion_time != 0: 
                            decay = new_completion_time / old_completion_time
                            completion_time_decay_record[id]["decay"] = decay

                        total_available_cpu = total_available_cpu - record[id]["avg_interval"] * record[id]["total_sequence_size"] * record[id]["cpu"]
                        total_available_memory = total_available_memory - record[id]["avg_interval"] * record[id]["total_sequence_size"] * record[id]["memory"]
                    
                    print("")
                    print("Initial total_available_cpu: {}".format(total_available_cpu))
                    print("Initial total_available_memory: {}".format(total_available_memory))

                    # Increase/decrease resources in a greedy way. 
                    pq_increase = queue.PriorityQueue()
                    pq_decrease = queue.PriorityQueue()
                    timeout_or_error_list = []
                    potential_available_cpu = 0
                    potential_available_memory = 0

                    for id in completion_time_decay_record.keys():
                        is_timeout = record[id]["is_timeout"]
                        is_success = record[id]["is_success"]

                        if is_timeout is True or is_success is False:
                            timeout_or_error_list.append(id)
                        else:
                            decay = completion_time_decay_record[id]["decay"]
                            if decay > 1.0: # Increase
                                pq_increase.put((-decay, id))
                            elif decay < 1.0: # Decrease
                                pq_decrease.put((decay, id))
                                potential_available_cpu = record[id]["avg_interval"] * record[id]["total_sequence_size"] * 1
                                potential_available_memory = record[id]["avg_interval"] * record[id]["total_sequence_size"] * 1

                    # Perform greedy
                    # if total_available_cpu + potential_available_cpu >= 0 and total_available_memory + potential_available_memory >= 0:
                    if total_available_cpu >= 0 and total_available_memory >= 0:
                        for id in timeout_or_error_list:
                            resource_adjust_list[id] = [1, 3] 
                            total_available_cpu = total_available_cpu - record[id]["avg_interval"] * record[id]["total_sequence_size"] * 1
                            total_available_memory = total_available_memory - record[id]["avg_interval"] * record[id]["total_sequence_size"] * 1

                            print("Increase {}, decay: {}, cpu: {}, memory: {}".format(
                                id, completion_time_decay_record[id]["decay"], record[id]["cpu"], record[id]["memory"])
                            )

                        while pq_increase.empty() is False:
                            id_increase = pq_increase.get()[1]
                            
                            while pq_decrease.empty() is False and \
                                (record[id_increase]["avg_interval"] * record[id_increase]["total_sequence_size"] * 1 > total_available_cpu or \
                                    record[id_increase]["avg_interval"] * record[id_increase]["total_sequence_size"] * 1 > total_available_memory):
                                id_decrease = pq_decrease.get()[1]
                                # Check this is knn and reaching its error boundary
                                if id_decrease == "knn":
                                    if record[id_decrease]["cpu"] == 2 or record[id_decrease]["memory"] == 2:
                                        # Hold
                                        resource_adjust_list[id_decrease] = [-1, -1] 
                                        print("Hold {}, decay: {}, cpu: {}, memory: {}".format(
                                            id_decrease, completion_time_decay_record[id_decrease]["decay"], record[id_decrease]["cpu"], record[id_decrease]["memory"])
                                        )
                                    else:
                                        # Decrease
                                        resource_adjust_list[id_decrease] = [0, 2] 
                                        total_available_cpu = total_available_cpu + record[id_decrease]["avg_interval"] * record[id_decrease]["total_sequence_size"] * 1
                                        total_available_memory = total_available_memory + record[id_decrease]["avg_interval"] * record[id_decrease]["total_sequence_size"] * 1

                                        print("Decrease {}, decay: {}, cpu: {}, memory: {}".format(
                                            id_decrease, completion_time_decay_record[id_decrease]["decay"], record[id_decrease]["cpu"], record[id_decrease]["memory"])
                                        )
                                else:
                                    # Decrease one slot of CPU and memory for better performed functions
                                    resource_adjust_list[id_decrease] = [0, 2] 
                                    total_available_cpu = total_available_cpu + record[id_decrease]["avg_interval"] * record[id_decrease]["total_sequence_size"] * 1
                                    total_available_memory = total_available_memory + record[id_decrease]["avg_interval"] * record[id_decrease]["total_sequence_size"] * 1

                                    print("Decrease {}, decay: {}, cpu: {}, memory: {}".format(
                                        id_decrease, completion_time_decay_record[id_decrease]["decay"], record[id_decrease]["cpu"], record[id_decrease]["memory"])
                                    )

                            if record[id_increase]["avg_interval"] * record[id_increase]["total_sequence_size"] * 1 <= total_available_cpu and \
                                record[id_increase]["avg_interval"] * record[id_increase]["total_sequence_size"] * 1 <= total_available_memory:
                                # Increase one slot of CPU and memory for worse performed functions
                                resource_adjust_list[id_increase] = [1, 3] 
                                total_available_cpu = total_available_cpu - record[id_increase]["avg_interval"] * record[id_increase]["total_sequence_size"] * 1
                                total_available_memory = total_available_memory - record[id_increase]["avg_interval"] * record[id_increase]["total_sequence_size"] * 1

                                print("Increase {}, decay: {}, cpu: {}, memory: {}".format(
                                    id_increase, completion_time_decay_record[id_increase]["decay"], record[id_increase]["cpu"], record[id_increase]["memory"])
                                )
                            else:
                                # Hold
                                resource_adjust_list[id_increase] = [-1, -1] 

                                print("Hold {}, decay: {}, cpu: {}, memory: {}".format(
                                    id_increase, completion_time_decay_record[id_increase]["decay"], record[id_increase]["cpu"], record[id_increase]["memory"])
                                )
                    # Decrease one slot of CPU and memory for every function since total available resources are below zero
                    # else: 
                    #     while pq_increase.empty() is False:
                    #         id_increase = pq_increase.get()[1]

                    #         # Check this is knn and reaching its error boundary
                    #         if id_increase == "knn":
                    #             if record[id_increase]["cpu"] == 2 or record[id_increase]["memory"] == 2:
                    #                 # Hold
                    #                 resource_adjust_list[id_increase] = [-1, -1] 
                    #                 print("Hold {}, decay: {}, cpu: {}, memory: {}".format(
                    #                     id_increase, completion_time_decay_record[id_increase]["decay"], record[id_increase]["cpu"], record[id_increase]["memory"])
                    #                 )
                    #             else:
                    #                 # Decrease
                    #                 resource_adjust_list[id_increase] = [0, 2] 
                    #                 total_available_cpu = total_available_cpu + record[id_increase]["avg_interval"] * record[id_increase]["total_sequence_size"] * 1
                    #                 total_available_memory = total_available_memory + record[id_increase]["avg_interval"] * record[id_increase]["total_sequence_size"] * 1

                    #                 print("Decrease {}, decay: {}, cpu: {}, memory: {}".format(
                    #                     id_increase, completion_time_decay_record[id_increase]["decay"], record[id_increase]["cpu"], record[id_increase]["memory"])
                    #                 )
                    #         else:
                    #             resource_adjust_list[id_increase] = [0, 2] 
                    #             total_available_cpu = total_available_cpu + record[id_increase]["avg_interval"] * record[id_increase]["total_sequence_size"] * 1
                    #             total_available_memory = total_available_memory + record[id_increase]["avg_interval"] * record[id_increase]["total_sequence_size"] * 1

                    #             print("Decrease {}, decay: {}, cpu: {}, memory: {}".format(
                    #                 id_increase, completion_time_decay_record[id_increase]["decay"], record[id_increase]["cpu"], record[id_increase]["memory"])
                    #             )

                    #     while pq_decrease.empty() is False:
                    #         id_decrease = pq_decrease.get()[1]

                    #         # Check this is knn and reaching its error boundary
                    #         if id_decrease == "knn":
                    #             if record[id_decrease]["cpu"] == 2 or record[id_decrease]["memory"] == 2:
                    #                 # Hold
                    #                 resource_adjust_list[id_decrease] = [-1, -1] 
                    #                 print("Hold {}, decay: {}, cpu: {}, memory: {}".format(
                    #                     id_decrease, completion_time_decay_record[id_decrease]["decay"], record[id_decrease]["cpu"], record[id_decrease]["memory"])
                    #                 )
                    #             else:
                    #                 # Decrease
                    #                 resource_adjust_list[id_decrease] = [0, 2] 
                    #                 total_available_cpu = total_available_cpu + record[id_decrease]["avg_interval"] * record[id_decrease]["total_sequence_size"] * 1
                    #                 total_available_memory = total_available_memory + record[id_decrease]["avg_interval"] * record[id_decrease]["total_sequence_size"] * 1

                    #                 print("Decrease {}, decay: {}, cpu: {}, memory: {}".format(
                    #                     id_decrease, completion_time_decay_record[id_decrease]["decay"], record[id_decrease]["cpu"], record[id_decrease]["memory"])
                    #                 )
                    #         else:
                    #             resource_adjust_list[id_decrease] = [0, 2] 
                    #             total_available_cpu = total_available_cpu + record[id_decrease]["avg_interval"] * record[id_decrease]["total_sequence_size"] * 1
                    #             total_available_memory = total_available_memory + record[id_decrease]["avg_interval"] * record[id_decrease]["total_sequence_size"] * 1

                    #             print("Decrease {}, decay: {}, cpu: {}, memory: {}".format(
                    #                 id_decrease, completion_time_decay_record[id_decrease]["decay"], record[id_decrease]["cpu"], record[id_decrease]["memory"])
                    #             )
                    
                    action = encode_action(self.profile.get_function_profile(), resource_adjust_list)

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
                    request_record = info["request_record"]
                    for function_id in avg_completion_time_per_function_trend.keys():
                        avg_completion_time_per_function_trend[function_id].append(
                            request_record.get_avg_completion_time_per_function(function_id)
                        )

                    # Log resource utilization 
                    resource_utils_record = info["resource_utils_record"]
                    self.log_resource_utils(
                        rm_name=rm, 
                        overwrite=False, 
                        episode=episode, 
                        resource_utils_record=resource_utils_record
                    )

                    # Log function throughput
                    self.log_function_throughput(
                        rm_name=rm, 
                        overwrite=False, 
                        episode=episode, 
                        function_throughput_list=function_throughput_list
                    )
                    
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
    # LambdaRM training
    #

    def lambda_rm_train(
        self,
        max_episode=150,
        plot_prefix_name="LambdaRM_train",
        save_plot=False,
        show_plot=True,
    ):
        rm = plot_prefix_name

        # Set up logger
        logger = self.logger_wrapper.get_logger(rm, True)
        
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
        function_profile = self.profile.get_function_profile()
        for function_id in function_profile.keys():
            avg_completion_time_per_function_trend[function_id] = []
        
        # Record max sum rewards
        max_reward_sum = -10e8

        # Start training
        for episode in range(max_episode):
            observation = self.reset()
            pg_agent.reset()

            actual_time = 0
            system_time = 0
            system_runtime = 0
            reward_sum = 0

            function_throughput_list = []

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
                    
                    # Save the best model
                    if max_reward_sum < reward_sum:
                        max_reward_sum = reward_sum
                        pg_agent.save(model_save_path)

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
                    # request_record = info["request_record"]
                    # for function_id in avg_completion_time_per_function_trend.keys():
                    #     avg_completion_time_per_function_trend[function_id].append(
                    #         request_record.get_avg_completion_time_per_function(function_id)
                    #     )

                    # # Log resource utilization 
                    # resource_utils_record = info["resource_utils_record"]
                    # self.log_resource_utils(
                    #     rm_name=rm, 
                    #     overwrite=False, 
                    #     episode=episode, 
                    #     resource_utils_record=resource_utils_record
                    # )

                    # # Log function throughput
                    # self.log_function_throughput(
                    #     rm_name=rm, 
                    #     overwrite=False, 
                    #     episode=episode, 
                    #     function_throughput_list=function_throughput_list
                    # )
                    
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

    def lambda_rm_eval(
        self,
        max_episode=10,
        checkpoint_path="ckpt/best_avg_completion_time.pth",
        plot_prefix_name="LambdaRM_eval",
        save_plot=False,
        show_plot=True,
    ):
        rm = plot_prefix_name

        # Set up logger
        logger = self.logger_wrapper.get_logger(rm, True)
        
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
        function_profile = self.profile.get_function_profile()
        for function_id in function_profile.keys():
            avg_completion_time_per_function_trend[function_id] = []
        
        # Start training
        for episode in range(max_episode):
            observation = self.reset()
            pg_agent.reset()

            actual_time = 0
            system_time = 0
            system_runtime = 0
            reward_sum = 0

            function_throughput_list = []
            
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
                    request_record = info["request_record"]
                    for function_id in avg_completion_time_per_function_trend.keys():
                        avg_completion_time_per_function_trend[function_id].append(
                            request_record.get_avg_completion_time_per_function(function_id)
                        )

                    # Log resource utilization 
                    resource_utils_record = info["resource_utils_record"]
                    self.log_resource_utils(
                        rm_name=rm, 
                        overwrite=False, 
                        episode=episode, 
                        resource_utils_record=resource_utils_record
                    )

                    # Log function throughput
                    self.log_function_throughput(
                        rm_name=rm, 
                        overwrite=False, 
                        episode=episode, 
                        function_throughput_list=function_throughput_list
                    )

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

        # Rollback handler 
        logger = self.logger_wrapper.get_logger(rm_name, False)

    def log_resource_utils(
        self, 
        rm_name,
        overwrite,
        episode,
        resource_utils_record
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
            logger.debug(','.join(str(cpu_util) for cpu_util in resource_utils_record[invoker]["cpu_util"]))
            logger.debug("memory_util")
            logger.debug(','.join(str(memory_util) for memory_util in resource_utils_record[invoker]["memory_util"]))
            logger.debug("avg_cpu_util")
            logger.debug(resource_utils_record[invoker]["avg_cpu_util"])
            logger.debug("avg_memory_util")
            logger.debug(resource_utils_record[invoker]["avg_memory_util"])
            logger.debug("")

        logger.debug("avg_invoker")
        logger.debug("cpu_util")
        logger.debug(','.join(str(cpu_util) for cpu_util in resource_utils_record["avg_invoker"]["cpu_util"]))
        logger.debug("memory_util")
        logger.debug(','.join(str(memory_util) for memory_util in resource_utils_record["avg_invoker"]["memory_util"]))
        logger.debug("avg_cpu_util")
        logger.debug(resource_utils_record["avg_invoker"]["avg_cpu_util"])
        logger.debug("avg_memory_util")
        logger.debug(resource_utils_record["avg_invoker"]["avg_memory_util"])

        # Rollback handler 
        logger = self.logger_wrapper.get_logger(rm_name, False)

    def log_function_throughput(
        self,
        rm_name,
        overwrite,
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
        
        # Rollback handler 
        logger = self.logger_wrapper.get_logger(rm_name, False)
