import time
from logger import Logger
from env import Environment
from ppo2_agent import PPO2Agent
from utils import export_csv_trajectory, export_csv_usage, export_csv_delta
from params import WorkloadParameters, EnvParameters
import params


#
# Evaluate the best model
#

def freyr_eval(
    logger_wrapper
):
    rm = "freyr_eval"

    # Set up logger
    logger = logger_wrapper.get_logger(rm, True)

    # Set up policy gradient agent
    agent = PPO2Agent(
        observation_dim=params.STATE_DIM,
        action_dim=params.ACTION_DIM,
        hidden_dims=params.HIDDEN_DIMS,
        learning_rate=params.LEARNING_RATE,
        discount_factor=params.DISCOUNT_FACTOR,
        ppo_clip=params.PPO_CLIP,
        ppo_epoch=params.PPO_EPOCH,
        value_loss_coef=params.VALUE_LOSS_COEF,
        entropy_coef=params.ENTROPY_COEF
    )

    # Restore checkpoint model
    agent.load(params.MODEL_SAVE_PATH + params.MODEL_NAME)
    
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

            # Reset env and agent
            env.cool_down_openwhisk()
            logger = logger_wrapper.get_logger(rm, False)
            observation, mask, is_safeguard, current_timestep, current_index, current_function_id = env.reset()
            agent.reset()

            actual_time = 0
            system_time = 0
            system_runtime = 0
            reward_sum = 0

            episode_done = False
            while episode_done is False:
                actual_time = actual_time + 1
                start_time = time.time()

                action, _, value_pred, log_prob = agent.choose_action(observation, mask)
                end_time = time.time()
                # print("Mapping a state to an action: {}".format(end_time - start_time))

                next_observation, next_mask, next_is_safeguard, reward, done, info, next_timestep, next_index, next_function_id = env.step(
                    current_timestep=current_timestep,
                    current_index=current_index,
                    current_function_id=current_function_id,
                    is_safeguard=is_safeguard,
                    action=env.decode_action(action)
                )

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
                
                if done:
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
    freyr_eval(logger_wrapper=logger_wrapper)
