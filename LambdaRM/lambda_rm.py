import time
import redis
import couchdb
import numpy as np
import matplotlib.pyplot as plt
import multiprocessing

from logger import Logger
from plotter import Plotter
from ppo2_agent import PPO2Agent
from utils import SystemTime, Request







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
        n_invoker=2,
        keep_alive_window=60,
        timeout_limit=60,
        decay_factor=0.8,
        reward_type="completion_time_decay"
    ):
        self.n_invoker = n_invoker
        self.keep_alive_window = keep_alive_window
        self.timeout_limit = timeout_limit
        self.decay_factor = decay_factor
        self.reward_type = reward_type
        self.profile = profile
        self.timetable = timetable

        # Calculate state and action space 
        self.state_space = 1 + 3 * n_invoker + 5 * self.profile.get_size()
        self.action_space = 1 + 4 * self.profile.get_size()

        # Set up Redis client
        self.pool = redis.ConnectionPool(
            host=redis_host, 
            port=redis_port, 
            password=redis_password, 
            decode_responses=True
        )
        self.redis_client = redis.Redis(connection_pool=self.pool)

        # Set up CouchDB client
        self.couch_client = couchdb.Server(
            "{}://{}:{}@{}:{}/".format(
                couch_protocol, couch_user, couch_password, couch_host, couch_port
            )
        )

        # Time module
        self.system_time = SystemTime()

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
            p = multiprocessing.Process(
                target=function.update_openwhisk,
                args=(self.couch_client,)
            )
            jobs.append(p)
            p.start()
        
        for p in jobs:
            p.join()

    # Multiprocessing
    def invoke_openwhisk(self):
        timestep = self.timetable.get_timestep(self.system_time.get_system_step())
        if timestep is not None:
            manager = multiprocessing.Manager()
            result_dict = manager.dict()
            for function in self.profile.function_profile:
                result_dict[function.function_id] = manager.list()

            jobs = []

            for function_i in range(self.profile.get_size()):
                for _ in range(timestep[function_i]):
                    p = multiprocessing.Process(
                        target=self.profile.function_profile[function_i].invoke_openwhisk,
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
    def try_update_request_history(self):
        manager = multiprocessing.Manager()
        result_dict = manager.dict()
        for function in self.profile.function_profile:
            result_dict[function.function_id] = manager.dict()
            for request in function.get_request_history():
                result_dict[function.function_id][request.request_id] = manager.dict()
                result_dict[function.function_id][request.request_id]["is_done"] = False # Default value

        jobs = []

        for function in self.profile.function_profile:
            for request in function.get_request_history():
                if request.get_is_done() is False:
                    p = multiprocessing.Process(
                        target=request.try_update,
                        args=(result_dict, self.system_time.get_system_runtime(), self.couch_client)
                    )
                    jobs.append(p)
                    p.start()
        
        for p in jobs:
            p.join()

        # Update requests according to the result dict
        for function_id in result_dict.keys():
            for function in self.profile.function_profile:
                if function_id == function.get_function_id():
                    for request_id in result_dict[function_id].keys():
                        for request in function.get_request_history():
                            if request_id == request.get_request_id():
                                is_done = result_dict[function_id][request_id]["is_done"] 
                                # Check if done
                                if is_done is True:
                                    done_time = self.system_time.get_system_runtime()
                                    is_timeout = result_dict[function_id][request_id]["is_timeout"] 
                                    # Check if timeout
                                    if is_timeout is False:
                                        duration = result_dict[function_id][request_id]["duration"]
                                        is_cold_start = result_dict[function_id][request_id]["is_cold_start"]
                                    else:
                                        duration = None
                                        is_cold_start = None

                                    # Set updates for each request
                                    request.set_updates(
                                        is_done=is_done,
                                        done_time=done_time,
                                        is_timeout=is_timeout,
                                        completion_time=duration,
                                        is_cold_start=is_cold_start
                                    )
                                        
    def get_n_undone_request_from_profile(self):
        n_undone_request = 0

        for function in self.profile.function_profile:
            for request in function.get_request_history():
                if request.get_is_done() is False:
                    n_undone_request = n_undone_request + 1

        return n_undone_request

    def get_current_timeout_num(self):
        n_timeout = 0
        for function in self.profile.function_profile:
            for request in function.get_request_history():
                if request.get_done_time() == self.system_time.get_system_runtime() and request.get_is_timeout() is True:
                    n_timeout = n_timeout + 1

        return n_timeout

    def get_total_timeout_num(self):
        n_timeout = 0
        for function in self.profile.function_profile:
            for request in function.get_request_history():
                if request.get_is_timeout() is True:
                    n_timeout = n_timeout + 1

        return n_timeout

    def get_avg_completion_time(self):
        request_num = 0
        total_completion_time = 0

        for function in self.profile.function_profile:
            for request in function.get_request_history():
                if request.get_is_done() is True and request.get_is_timeout() is False:
                    request_num = request_num + 1
                    total_completion_time = total_completion_time + request.get_completion_time()
            
        if request_num == 0:
            avg_completion_time = 0
        else:
            avg_completion_time = total_completion_time / request_num

        return avg_completion_time

    def get_request_history_dict(self):
        request_history_dict = {}
        for function in self.profile.function_profile:
            request_history_dict[function.function_id] = function.get_request_history()

        return request_history_dict

    def get_observation(self):
        # Controller state
        controller_state = []
        n_undone_request = int(self.redis_client.get("n_undone_request"))
        controller_state.append(n_undone_request)

        # Invoker state
        invoker_state = []
        for i in range(self.n_invoker):
            invoker = "invoker{}".format(i) 

            available_cpu = int(self.redis_client.hget(invoker, "available_cpu"))
            invoker_state.append(available_cpu)
            available_memory = int(self.redis_client.hget(invoker, "available_memory"))
            invoker_state.append(available_memory)
            n_container = int(self.redis_client.hget(invoker, "n_container"))
            invoker_state.append(n_container)

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
        #  invoker_1_n_container,
        #  .
        #  .
        #  .
        #  invoker_n_available_cpu, 
        #  invoker_n_available_memory,
        #  invoker_n_n_container,
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
            (np.array(controller_state),
            np.array(invoker_state),
            np.array(function_state))
        )

        return observation

    def get_reward(self, observation, interval):
        # Penalty for timeout requests
        n_timeout = self.get_current_timeout_num()
        timeout_reward = - self.timeout_limit * n_timeout
        
        # Penalty for undone requests
        n_undone_request = 0
        undone_reward = 0

        if self.reward_type == "completion_time":
            for function in self.profile.function_profile:
                for request in function.get_request_history():
                    if request.get_is_done() is False:
                        n_undone_request = n_undone_request + 1
                        undone_reward = undone_reward + (- interval)

        elif self.reward_type == "completion_time_decay":
            for function in self.profile.function_profile:
                for request in function.get_request_history():
                    if request.get_is_done() is False:
                        n_undone_request = n_undone_request + 1
                        undone_reward = undone_reward + (- interval * np.power(self.decay_factor, self.system_time.get_system_runtime() - request.get_invoke_time()))

        # Total reward
        reward = timeout_reward + undone_reward

        return reward

    def get_done(self, observation):
        done = False

        # n_undone_request = observation[0]
        n_undone_request = self.get_n_undone_request_from_profile()
        if self.system_time.get_system_step() >= self.timetable.get_size() and n_undone_request == 0:
            done = True
            
        return done

    def get_info(self):
        info = {
            "system_step": self.system_time.get_system_step(),
            "avg_completion_time": self.get_avg_completion_time(),
            "timeout_num": self.get_total_timeout_num(),
            "request_history_dict": self.get_request_history_dict(),
            "system_runtime": self.system_time.get_system_runtime()
        }

        return info

    def step(self, action=None):
        is_valid_action = self.update_function_profile(action)
        
        if is_valid_action is True: # THE WORLD!
            # Get observation for next state
            observation = self.get_observation() 
            reward = 0
        else: # Time starts proceeding
            interval = self.system_time.step()
            print("system_step: {}, system_runtime: {}".format(self.system_time.get_system_step(), self.system_time.get_system_runtime()))
            
            # Update functions on OpenWhisk
            before_update = time.time()
            self.update_openwhisk()
            after_update = time.time()
            print("Update overhead: {}".format(after_update - before_update))

            # Invoke functions according to timetable
            before_invoke = time.time()
            self.invoke_openwhisk()
            after_invoke = time.time()
            print("Invoke overhead: {}".format(after_invoke - before_invoke))

            # Try to update undone requests
            before_try = time.time()
            self.try_update_request_history()
            after_try = time.time()
            print("Try overhead: {}".format(after_try - before_try))
            print("")

            # Get observation for next state
            observation = self.get_observation() 
            reward = self.get_reward(observation, interval)
            
            # Reset resource adjust direction for each function 
            for function in self.profile.function_profile:
                function.reset_resource_adjust_direction()

        # Done?
        done = self.get_done(observation)
        
        # Return information
        info = self.get_info()
        
        return observation, reward, done, info

    def reset(self):
        self.system_time.reset()
        self.profile.reset()
        
        observation = self.get_observation()
        
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
        # Set up logger
        logger_wrapper = Logger("FixedRM")
        logger = logger_wrapper.get_logger()
        
        # Trends recording
        reward_trend = []
        avg_completion_time_trend = []
        timeout_num_trend = []
        
        # Start training
        for episode in range(max_episode):
            observation = self.reset()

            actual_time = 0
            system_time = 0
            reward_sum = 0
            
            while True:
                actual_time = actual_time + 1
                action = self.action_space - 1
                next_observation, reward, done, info = self.step(action)

                if system_time < info["system_step"]:
                    system_time = info["system_step"]
                    system_runtime = info["system_runtime"]
                    
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
                    
                    reward_trend.append(reward_sum)
                    avg_completion_time_trend.append(avg_completion_time)
                    timeout_num_trend.append(timeout_num)
                    
                    break
                
                observation = next_observation

            # Cool down invokers
            time.sleep(self.keep_alive_window)
        
        # Plot each episode 
        plotter = Plotter()
        
        if save_plot is True:
            plotter.plot_save(
                prefix_name=plot_prefix_name, 
                reward_trend=reward_trend, 
                avg_completion_time_trend=avg_completion_time_trend,
                timeout_num_trend=timeout_num_trend, 
            )
        if show_plot is True:
            plotter.plot_show(
                reward_trend=reward_trend, 
                avg_completion_time_trend=avg_completion_time_trend, 
                timeout_num_trend=timeout_num_trend, 
            )

        logger_wrapper.shutdown_logger()

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

        # Set up logger
        logger_wrapper = Logger("GreedyRM")
        logger = logger_wrapper.get_logger()
        
        # Record trends
        reward_trend = []
        avg_completion_time_trend = []
        timeout_num_trend = []
        
        # Start training
        for episode in range(max_episode):
            observation = self.reset()
            reward_sum = 0
            actual_time = 0
            system_time = 0
            
            action = self.action_space - 1
            
            while True:
                actual_time = actual_time + 1
                observation, reward, done, info = self.step(action)
                
                if system_time < info["system_step"]:
                    system_time = info["system_step"]
                    record = info["request_history_dict"]
                    
                    #
                    # Greedy resource adjustment: Completion time decay
                    #

                    # Record last two completion time for each function and its decay at each system timestep
                    completion_time_decay_record = {}
                    for function in self.profile.function_profile:
                        completion_time_decay_record[function.function_id] = 1.0
                        
                    # Adjustment for each function
                    resource_adjust_list = {}
                    for function in self.profile.function_profile:
                        resource_adjust_list[function.function_id] = []
                    
                    # Update completion time decay for each function
                    for id in record.keys():
                        n_done_request = 0
                        for request in record[id]:
                            if request.get_is_done() is True:
                                n_done_request = n_done_request + 1

                        if n_done_request <= 1: # No request finished or no old request for this function
                            resource_adjust_list[id] = [-1, -1] # Hold 
                        else:
                            # Get two latest requests
                            old_request = None
                            new_request = None
                            old_done_time = 0
                            new_done_time = 0

                            for request in record[id]:
                                if request.get_is_done() is True:
                                    if request.get_done_time() > new_done_time:
                                        old_done_time = new_done_time
                                        old_request = new_request
                                        new_done_time = request.get_done_time()
                                        new_request = request
                                    elif request.get_done_time() >= old_done_time and request.get_done_time() <= new_done_time:
                                        old_done_time = request.get_done_time()
                                        old_request = request

                            if new_request.get_is_timeout() is True or old_request.get_is_timeout() is True: 
                                completion_time_decay_record[id] = 114514.0 # Timeout penalty
                            else: 
                                # Update decay
                                completion_time_decay_record[id] = new_request.get_completion_time() / old_request.get_completion_time()

                    # Assign resource adjusts. 
                    # Functions that have decay (latest completion time) / (previous completion time)
                    # over avg get increase, otherwise decrease
                    decay_list = []
                    for id in completion_time_decay_record.keys():
                        decay_list.append(completion_time_decay_record[id])

                    decay_avg = np.mean(decay_list)

                    for id in completion_time_decay_record.keys():
                        if completion_time_decay_record[id] >= decay_avg:
                            resource_adjust_list[id] = [1, 3] # Increase one slot for CPU and memory
                        else:
                            resource_adjust_list[id] = [0, 2] # Decrease one slot for CPU and memory
                    
                    action = encode_action(self.profile.function_profile, resource_adjust_list)
                    
                logger.debug("")
                logger.debug("Actual timestep {}".format(actual_time))
                logger.debug("System timestep {}".format(system_time))
                logger.debug("Take action: {}".format(action))
                logger.debug("Observation: {}".format(observation))
                logger.debug("Reward: {}".format(reward))
                
                reward_sum = reward_sum + reward
                
                if done:
                    avg_completion_time = info["avg_completion_time"]
                    timeout_num = info["timeout_num"]
                    
                    logger.info("")
                    logger.info("**********")
                    logger.info("**********")
                    logger.info("**********")
                    logger.info("")
                    logger.info("Episode {} finished after:".format(episode))
                    logger.info("{} actual timesteps".format(actual_time))
                    logger.info("{} system timesteps".format(system_time))
                    logger.info("Total reward: {}".format(reward_sum))
                    logger.info("Avg completion time: {}".format(avg_completion_time))
                    logger.info("Timeout num: {}".format(timeout_num))
                    
                    reward_trend.append(reward_sum)
                    avg_completion_time_trend.append(avg_completion_time)
                    timeout_num_trend.append(timeout_num)
                    
                    break
            
            # Cool down invokers
            time.sleep(self.keep_alive_window)
        
        # Plot each episode 
        plotter = Plotter()
        
        if save_plot is True:
            plotter.plot_save(
                prefix_name=plot_prefix_name, 
                reward_trend=reward_trend, 
                avg_completion_time_trend=avg_completion_time_trend,
                timeout_num_trend=timeout_num_trend
            )
        if show_plot is True:
            plotter.plot_show(
                reward_trend=reward_trend, 
                avg_completion_time_trend=avg_completion_time_trend,
                timeout_num_trend=timeout_num_trend,
            )
            
        logger_wrapper.shutdown_logger()

    #
    # Policy gradient training
    #

    def train(
        self,
        max_episode=150,
        plot_prefix_name="LambdaRM",
        save_plot=False,
        show_plot=True,
    ):
        # Set up logger
        logger_wrapper = Logger("LambdaRM")
        logger = logger_wrapper.get_logger()
        
        # Set up policy gradient agent
        pg_agent = PPO2Agent(
            observation_dim=self.state_space,
            action_dim=self.action_space,
            hidden_dims=[64, 32],
            learning_rate=0.005,
            discount_factor=1,
            ppo_clip=0.2,
            ppo_steps=5
        )
        
        # Record trends
        reward_trend = []
        avg_completion_time_trend = []
        timeout_num_trend = []
        loss_trend = []
        
        # Start training
        for episode in range(max_episode):
            observation = self.reset()
            pg_agent.reset()

            actual_time = 0
            system_time = 0
            reward_sum = 0
            
            while True:
                time.sleep(0.5)
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
                    
                logger.debug("")
                logger.debug("Actual timestep {}".format(actual_time))
                logger.debug("System timestep {}".format(system_time))
                logger.debug("Take action: {}".format(action))
                logger.debug("Observation: {}".format(observation))
                logger.debug("Reward: {}".format(reward))
                
                reward_sum = reward_sum + reward
                
                if done:
                    loss = pg_agent.propagate()
                    avg_completion_time = info["avg_completion_time"]
                    timeout_num = info["timeout_num"]
                    
                    logger.info("")
                    logger.info("**********")
                    logger.info("**********")
                    logger.info("**********")
                    logger.info("")
                    logger.info("Episode {} finished after:".format(episode))
                    logger.info("{} actual timesteps".format(actual_time))
                    logger.info("{} system timesteps".format(system_time))
                    logger.info("Total reward: {}".format(reward_sum))
                    logger.info("Avg completion time: {}".format(avg_completion_time))
                    logger.info("Timeout num: {}".format(timeout_num))
                    logger.info("Loss: {}".format(loss))
                    
                    reward_trend.append(reward_sum)
                    avg_completion_time_trend.append(avg_completion_time)
                    timeout_num_trend.append(timeout_num)
                    loss_trend.append(loss)
                    
                    break
                
                observation = next_observation

            # Cool down invokers
            time.sleep(self.keep_alive_window)
        
        # Plot each episode 
        plotter = Plotter()
        
        if save_plot is True:
            plotter.plot_save(
                prefix_name=plot_prefix_name, 
                reward_trend=reward_trend, 
                avg_completion_time_trend=avg_completion_time_trend,
                timeout_num_trend=timeout_num_trend, 
                loss_trend=loss_trend
            )
        if show_plot is True:
            plotter.plot_show(
                reward_trend=reward_trend, 
                avg_completion_time_trend=avg_completion_time_trend, 
                timeout_num_trend=timeout_num_trend, 
                loss_trend=loss_trend
            )

        logger_wrapper.shutdown_logger()
        