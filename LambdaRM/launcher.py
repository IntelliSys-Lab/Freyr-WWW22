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
        timetable_params=timetable_params,
        max_timestep=120
    )
    
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
        # cool_down="refresh",
        cool_down=65,
        interval_limit=1,
        fail_penalty=60,
        decay_factor=0.9,
        profile=profile,
        timetable=timetable,
    )
    
    # # Fixed RM
    # lambda_rm.refresh_openwhisk()
    # lambda_rm.fixed_rm(
    #     max_episode=10,
    #     plot_prefix_name="FixedRM",
    #     save_plot=True,
    #     show_plot=False
    # )

    # Greedy RM
    # lambda_rm.refresh_openwhisk()
    lambda_rm.greedy_rm(
        max_episode=10,
        plot_prefix_name="GreedyRM",
        save_plot=True,
        show_plot=False
    )

    # # Train
    # lambda_rm.refresh_openwhisk()
    # lambda_rm.train(
    #     max_episode=100,
    #     plot_prefix_name="LambdaRM_train",
    #     save_plot=True,
    #     show_plot=False
    # )
    
    # # Eval best timeout/error model
    # lambda_rm.refresh_openwhisk()
    # lambda_rm.eval(
    #     max_episode=10,
    #     checkpoint_path="ckpt/best_timeout_or_error.pth",
    #     plot_prefix_name="LambdaRM_eval_best_timeout_or_error",
    #     save_plot=True,
    #     show_plot=False,
    # )

    # # Eval best avg completion time model
    # lambda_rm.refresh_openwhisk()
    # lambda_rm.eval(
    #     max_episode=10,
    #     checkpoint_path="ckpt/best_avg_completion_time.pth",
    #     plot_prefix_name="LambdaRM_eval_best_avg_completion_time",
    #     save_plot=True,
    #     show_plot=False,
    # )


if __name__ == "__main__":
    
    # Launch LambdaRM
    launch()
    
    
