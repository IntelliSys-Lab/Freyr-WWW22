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
        couch_protocol = "http",
        couch_user = "whisk_admin",
        couch_password = "some_passw0rd",
        couch_host = "192.168.196.65",
        couch_port = "5984",
        n_invoker=2,
        keep_alive_window=60,
        timeout_limit=60,
        decay_factor=0.9,
        reward_type="completion_time_decay",
        profile=profile,
        timetable=timetable,
    )
    
    # Number of max episode
    max_episode = 100
    
    # Fixed RM
    lambda_rm.fixed_rm(
        max_episode=10,
        plot_prefix_name="FixedRM" + file_suffix,
        save_plot=True,
        show_plot=False
    )

    # Greedy RM
    lambda_rm.greedy_rm(
        max_episode=10,
        plot_prefix_name="GreedyRM" + file_suffix,
        save_plot=True,
        show_plot=False
    )

    # Start training
    lambda_rm.train(
        max_episode=max_episode,
        plot_prefix_name="LambdaRM" + file_suffix,
        save_plot=True,
        show_plot=False
    )


if __name__ == "__main__":
    
    # Launch LambdaRM
    launch()
    
    
