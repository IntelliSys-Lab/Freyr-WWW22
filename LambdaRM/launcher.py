from params import FunctionParameters, TimetableParameters
from workflow_generator import WorkflowGenerator
from lambda_rm import LambdaRM



def launch():

    # Generate workflow
    workflow_generator = WorkflowGenerator()
    profile_params = None # Default Azure traces
    timetable_params = None # Default Azure traces
    
    profile, timetable = workflow_generator.generate_workflow(
        default="azure",
        profile_params=profile_params,
        timetable_params=timetable_params
    )
    
    reward_type = "completion_time_decay"
    file_suffix = "_Azure_Decay"

    # Set up LambdaRM
    lambda_rm = LambdaRM(
        redis_host="192.168.196.213",
        redis_port=6379,
        redis_password="openwhisk",
        n_invoker=2,
        timeout_limit=60,
        decay_factor=0.8,
        reward_type="completion_time_decay",
        profile=profile,
        timetable=timetable,
    )
    
    # Number of max episode
    max_episode = 100
    
    # Fixed RM
    # lambda_rm.fixed_rm(
    #     max_episode=1,
    #     plot_prefix_name="FixedRM" + file_suffix,
    #     save_plot=True,
    #     show_plot=False
    # )

    # Start training
    lambda_rm.train(
        max_episode=1,
        keep_alive_window=60,
        plot_prefix_name="LambdaRM" + file_suffix,
        save_plot=True,
        show_plot=False
    )


if __name__ == "__main__":
    
    # Launch LambdaRM
    launch()
    
    
