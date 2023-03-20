from env import Environment
from logger import Logger
from utils import export_csv_trajectory, export_csv_usage, export_csv_delta
from params import WorkloadParameters, EnvParameters
import params


#
# Default
#

def ensure_rm(
    logger_wrapper
):
    rm = "ensure"

    # Set up logger
    logger = logger_wrapper.get_logger(rm, True)

    # Start training
    episode = 0
    for exp_id in params.EXP_EVAL:
        # Set paramters for workloads
        workload_params = WorkloadParameters(
            azure_file_path=params.AZURE_FILE_PATH,
            user_defined_dict=params.USER_DEFINED_DICT,
            exp_id=exp_id
        )

        # Set paramters for Environment
        env_params = EnvParameters(
            n_invoker=params.N_INVOKER,
            redis_host=params.REDIS_HOST,
            redis_port=params.REDIS_PORT,
            redis_password=params.REDIS_PASSWORD,
            couch_link=params.COUCH_LINK,
            cool_down=params.COOL_DOWN,
            interval_limit=params.ENV_INTERVAL_LIMIT,
            update_retry_time=params.UPDATE_RETRY_TIME,
            cpu_cap_per_function=params.CPU_CAP_PER_FUNCTION,
            memory_cap_per_function=params.MEMORY_CAP_PER_FUNCTION,
            memory_unit=params.MEMORY_UNIT
        )
        
        # Set up environment
        env = Environment(
            workload_params=workload_params,
            env_params=env_params
        )

        # Set up records
        reward_trend = []
        timeout_num_trend = []
        error_num_trend = []

        for episode_per_exp in range(params.MAX_EPISODE_EVAL):
            # Record total number of events
            total_events = env.event_pq.get_total_size()

            # Reset env
            env.cool_down_openwhisk()
            logger = logger_wrapper.get_logger(rm, False)
            observation, mask, is_safeguard, current_timestep, current_index, current_function_id = env.reset()
            is_safeguard = False

            actual_time = 0
            system_time = 0
            system_runtime = 0
            reward_sum = 0

            action = {}

            # ENSURE
            update_threshold_dict = {}
            for function_id in env.profile.get_function_profile().keys():
                update_threshold_dict[function_id] = 0

            episode_done = False
            while episode_done is False:
                actual_time = actual_time + 1
                next_observation, next_mask, next_is_safeguard, reward, done, info, next_timestep, next_index, next_function_id = env.step(
                    current_timestep=current_timestep,
                    current_index=current_index,
                    current_function_id=current_function_id,
                    is_safeguard=is_safeguard,
                    action=action
                )
                next_is_safeguard = False

                if system_time < info["system_step"]:
                    system_time = info["system_step"]
                if system_runtime < info["system_runtime"]:
                    system_runtime = info["system_runtime"]

                logger.debug("")
                logger.debug("Actual timestep {}".format(actual_time))
                logger.debug("System timestep {}".format(system_time))
                logger.debug("System runtime {}".format(system_runtime))
                logger.debug("Take action: {}".format(action))
                logger.debug("Observation: {}".format(observation))
                logger.debug("Reward: {}".format(reward))
                
                reward_sum = reward_sum + reward
                if done is False:
                    request_record = info["request_record"]
                    total_available_cpu = info["total_available_cpu"]
                    total_available_memory = info["total_available_memory"]

                    #
                    # ENSURE dynamic CPU adjustment
                    #
                
                    window_size = 3
                    latency_threshold = 1.10

                    # Classify the function
                    cpu_max = env.env_params.cpu_cap_per_function
                    if request_record.get_avg_completion_time_per_function(next_function_id) > 5: # MP
                        num_update_threshold = 5
                        cpu_step = 1
                    else: # ET
                        num_update_threshold = 3
                        cpu_step = 2

                    # If the function reaches threshold of updates
                    if update_threshold_dict[function_id] >= num_update_threshold:
                        # Monitor via a moving window
                        request_window = request_record.get_last_n_done_request_per_function(next_function_id, window_size)
                        if len(request_window) > 0:
                            total_completion_time_in_window = 0
                            for request in request_window:
                                total_completion_time_in_window = total_completion_time_in_window + request.get_completion_time()
                            avg_completion_time_in_window = total_completion_time_in_window / window_size

                            # If there is enough capacity
                            if total_available_cpu > cpu_step:
                                recent_completion_time = request_record.get_recent_completion_time_per_function(next_function_id)
                                if recent_completion_time == 0:
                                    action = {} # No increase
                                else: # If performance degrade, increase its CPU allocation based on step
                                    if avg_completion_time_in_window / recent_completion_time >= latency_threshold:
                                        action["cpu"] = min(request_window[0].get_cpu() + cpu_step, env.env_params.cpu_cap_per_function)
                                    else:
                                        action = {} # No increase
                            else: # If reaches capacity, rebalance CPU from other functions
                                action["cpu"] = max(request_window[0].get_cpu() - cpu_step, 1)
                        else:
                            action = {} # No increase

                        update_threshold_dict[function_id] = 0
                    else:
                        update_threshold_dict[function_id] = update_threshold_dict[function_id]  + 1
                else:
                    if system_time < info["system_step"]:
                        system_time = info["system_step"]
                    if system_runtime < info["system_runtime"]:
                        system_runtime = info["system_runtime"]

                    timeout_num = info["timeout_num"]
                    error_num = info["error_num"]
                    
                    logger.info("")
                    logger.info("**********")
                    logger.info("**********")
                    logger.info("**********")
                    logger.info("")
                    logger.info("Running {}".format(rm))
                    logger.info("Exp {}, Episode {} finished".format(exp_id, episode))
                    logger.info("{} actual timesteps".format(actual_time))
                    logger.info("{} system timesteps".format(system_time))
                    logger.info("{} system runtime".format(system_runtime))
                    logger.info("Total events: {}".format(total_events))
                    logger.info("Total reward: {}".format(reward_sum))
                    logger.info("Timeout num: {}".format(timeout_num))
                    logger.info("Error num: {}".format(error_num))
                    
                    reward_trend.append(reward_sum)
                    timeout_num_trend.append(timeout_num)
                    error_num_trend.append(error_num)

                    request_record = info["request_record"]

                    # Export csv files
                    export_csv_trajectory(
                        rm_name=rm,
                        exp_id=exp_id,
                        episode=episode,
                        csv_trajectory=env.request_record.get_csv_trajectory()
                    )
                    export_csv_usage(
                        rm_name=rm,
                        exp_id=exp_id,
                        episode=episode,
                        csv_cpu_usage=env.request_record.get_csv_cpu_usage(env.system_time.get_system_up_time()),
                        csv_memory_usage=env.request_record.get_csv_mem_usage(env.system_time.get_system_up_time())
                    )
                    export_csv_delta(
                        rm_name=rm,
                        exp_id=exp_id,
                        episode=episode,
                        csv_delta=env.request_record.get_csv_delta()
                    )

                    episode_done = True
                
                observation = next_observation
                mask = next_mask
                is_safeguard = next_is_safeguard
                current_timestep = next_timestep
                current_index = next_index
                current_function_id = next_function_id

            episode = episode + 1


if __name__ == "__main__":
    logger_wrapper = Logger()
    ensure_rm(logger_wrapper=logger_wrapper)