from params import FunctionParameters, TimetableParameters
from workload_generator import WorkloadGenerator
from framework import Framework



def launch():

    # Generate workload
    workload_generator = WorkloadGenerator()
    profile_params = None # Default Azure traces
    timetable_params = None # Default Azure traces
    
    profile, timetable = workload_generator.generate_workload(
        default="azure",
        profile_params=profile_params,
        timetable_params=timetable_params,
        max_timestep=60
    )
    
    # Set up serverless framework
    framework = Framework(
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

    # framework.refresh_couchdb_and_openwhisk()
    # framework.refresh_openwhisk()
    
    # Fixed RM
    framework.fixed_rm(
        # max_episode=10,
        max_episode=1,
        plot_prefix_name="FixedRM",
        save_plot=True,
        show_plot=False
    )

    # Greedy RM
    # framework.refresh_openwhisk()
    # framework.greedy_rm(
    #     # max_episode=10,
    #     max_episode=1,
    #     plot_prefix_name="GreedyRM",
    #     save_plot=True,
    #     show_plot=False
    # )

    # # Lambda RM train
    # framework.refresh_openwhisk()
    # framework.lambda_rm_train(
    #     max_episode=500,
    #     plot_prefix_name="LambdaRM_train",
    #     save_plot=True,
    #     show_plot=False
    # )
    
    # # Lambda RM eval the best model
    # framework.refresh_openwhisk()
    # framework.lambda_rm_eval(
    #     max_episode=10,
    #     checkpoint_path="ckpt/best_model.pth",
    #     plot_prefix_name="LambdaRM_eval",
    #     save_plot=True,
    #     show_plot=False,
    # )


if __name__ == "__main__":
    
    # Launch LambdaRM
    launch()
    
    
