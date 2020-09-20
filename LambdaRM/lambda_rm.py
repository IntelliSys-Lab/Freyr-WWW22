import os
import time
import redis
import numpy as np
import matplotlib.pyplot as plt

from logger import Logger
from plotter import Plotter
from ppo2_agent import PPO2Agent



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
        n_invoker=2,
        timeout_limit=60,
        decay_factor=0.8,
        reward_type="completion_time_decay"
    ):
        self.n_invoker = n_invoker
        self.timeout_limit = timeout_limit
        self.decay_factor = decay_factor
        self.reward_type = reward_type
        self.profile = profile
        self.timetable = timetable

        self.state_space = 1 + 3 * n_invoker + 5 * self.profile.get_size()
        self.action_space = 1 + 4 * self.profile.get_size()

        self.pool = redis.ConnectionPool(
            host=redis_host, 
            port=redis_port, 
            password=redis_password, 
            decode_responses=True
        )
        self.redis_client = redis.Redis(connection_pool=self.pool)

        # Time module
        self.system_up_time = time.time()
        self.system_runtime = 0
        self.system_step = 0

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

    def update_openwhisk(self):
        for function in self.profile.function_profile:
            function.update_openwhisk()

    def invoke_openwhisk(self):
        timestep = self.timetable.get_timestep(self.system_step)
        if timestep is not None:
            for function_i in range(self.profile.get_size()):
                for _ in range(timestep[function_i]):
                    self.profile.function_profile[function_i].invoke_openwhisk(self.system_runtime)
    
    def try_update_request_history(self):
        for function in self.profile.function_profile:
            function.try_update_request_history(self.system_runtime)

    def get_timeout_num(self):
        n_timeout = 0
        for function in self.profile.function_profile:
            for request in function.get_request_history():
                if request.get_done_time() == self.system_runtime:
                    n_timeout = n_timeout + 1

        return n_timeout

    def get_avg_completion_time(self):
        request_num = 0
        total_completion_time = 0

        for function in self.profile.function_profile:
            for request in function.get_request_history():
                if request.get_is_done() is True:
                    request_num = request_num + 1
                    total_completion_time = total_completion_time + request.get_completion_time()
            
        if request_num == 0:
            avg_completion_time = 0
        else:
            avg_completion_time = total_completion_time / request_num

        return avg_completion_time

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
            function_state.append(function.get_avg_interval(self.system_runtime))
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
        n_timeout = self.get_timeout_num()
        timeout_reward = - self.timeout_limit * n_timeout
        
        # Penalty for undone requests
        n_undone_request = observation[0]
        undone_reward = 0

        if self.reward_type == "completion_time":
            for function in self.profile.function_profile:
                for request in function.get_request_history():
                    if request.get_is_done() is False:
                        undone_reward = undone_reward + (- interval)

        elif self.reward_type == "completion_time_decay":
            for function in self.profile.function_profile:
                for request in function.get_request_history():
                    if request.get_is_done() is False:
                        undone_reward = undone_reward + (- interval * np.power(self.decay_factor, self.system_runtime - request.get_invoke_time()))

        # Total reward
        reward = timeout_reward + undone_reward

        return reward

    def get_done(self, observation):
        done = False

        n_undone_request = observation[0]
        if self.system_step >= self.timetable.get_size() and n_undone_request == 0:
            done = True
            
        return done

    def get_info(self):
        info = {
            "system_step": self.system_step,
            "avg_completion_time": self.get_avg_completion_time(),
            "timeout_num": self.get_timeout_num(),
        }

        return info

    def step(self, action=None):
        is_valid_action = self.update_function_profile(action)
        
        if is_valid_action is True: # THE WORLD!
            # Get observation for next state
            observation = self.get_observation() 
            reward = 0
        else: # Time starts proceeding
            current_time = time.time()
            interval = current_time - (self.system_up_time + self.system_runtime)
            self.system_runtime = current_time - self.system_up_time
            self.system_step = self.system_step + 1

            # Update functions on OpenWhisk
            self.update_openwhisk()

            # Invoke functions according to timetable
            self.invoke_openwhisk()

            # Try to update undone requests
            self.try_update_request_history()

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
        self.system_up_time = time.time()
        self.system_runtime = 0
        self.system_step = 0
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
                
                observation = next_observation
        
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
    # Policy gradient training
    #

    def train(
        self,
        max_episode=150,
        keep_alive_window=60,
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
        
        # Trends recording
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
            time.sleep(keep_alive_window)
        
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
        