import time
import json
import numpy as np
import csv
from utils import run_cmd
from params import WSK_CLI, COUCH_LINK


def invoke(function_id, param):
    try:
        cmd = '{} action invoke {} -b {} | grep -v "ok:"'.format(WSK_CLI, function_id, param)
        response = str(run_cmd(cmd))
        doc = json.loads(response)

        if len(doc["annotations"]) == 6:
            init_time = doc["annotations"][5]["value"]
        else:
            init_time = 0
        wait_time = doc["annotations"][1]["value"]
        duration = doc["duration"]
    except Exception:
        init_time = 0
        wait_time = 0
        duration = 0

    return init_time, wait_time, duration

def cold_start(interval, cold_loop_time, function_id, param):
    result = {}
    result["init_time"] = []
    result["wait_time"] = []
    result["duration"] = []
    result["completion_time"] = []

    for _ in range(cold_loop_time):
        time.sleep(interval)
        init_time, wait_time, duration = invoke(function_id, param)
        completion_time = init_time + wait_time + duration
        if completion_time > 0:
            result["init_time"].append(init_time)
            result["wait_time"].append(wait_time)
            result["duration"].append(duration)
            result["completion_time"].append(completion_time)

    time.sleep(interval)

    return result

def warm_start(interval, alloc_range, warm_loop_time, function_id, param):
    result = ["actual_id","init_time", "wait_time", "duration", "completion_time"]
    init_time_list = []
    wait_time_list  = []
    duration_list  = []
    completion_time_list  = []

    for i in range(alloc_range):
        actual_id = "{}_{}".format(function_id, i)
        for loop in range(warm_loop_time):
            init_time, wait_time, duration = invoke(actual_id, param)
            completion_time = init_time + wait_time + duration
            if loop > 0 and completion_time > 0:
                init_time_list.append(init_time)
                wait_time_list.append(wait_time)
                duration_list.append(duration)
                completion_time_list.append(completion_time)

        result.append(actual_id)
        result.append(0 if len(init_time_list) == 0 else np.average(init_time_list))
        result.append(0 if len(wait_time_list) == 0 else np.average(wait_time_list))
        result.append(0 if len(duration_list) == 0 else np.average(duration_list))
        result.append(0 if len(completion_time_list) == 0 else np.average(completion_time_list))

    time.sleep(interval)

    return result

def characterize_functions(
    interval,
    alloc_range,
    cold_loop_time,
    warm_loop_time,
    file_path,
    function_invoke_params
):
    for function_id in function_invoke_params.keys():
        param = function_invoke_params[function_id]
        # cold_result = cold_start(interval, cold_loop_time, function_id, param)
        warm_result = warm_start(interval, alloc_range, warm_loop_time, function_id, param)

        # Log warm starts
        with open(file_path + "{}_saturation_point.csv".format(function_id), "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerows(warm_result)


if __name__ == "__main__":
    interval = 1
    alloc_range = 64
    cold_loop_time = 10
    warm_loop_time = 1
    file_path = "logs/"

    function_invoke_params = {}
    # function_invoke_params["dh"] = "-p username hanfeiyu -p size 500000 -p parallel 128 "
    function_invoke_params["eg"] = ""
    # function_invoke_params["ip"] = "-p width 1000 -p height 1000 -p size 128 -p parallel 8 "
    # function_invoke_params["vp"] = "-p duration 10 -p size 1 -p parallel 1 "
    # function_invoke_params["ir"] = "-p size 1 -p parallel 1 "
    # function_invoke_params["knn"] = "-p dataset_size 100 -p feature_dim 80 -p k 3 -p size 24 -p parallel 1 "
    # function_invoke_params["alu"] = "-p size 100000000 -p parallel 64 "
    # function_invoke_params["ms"] = "-p size 1000000 -p parallel 8 "
    # function_invoke_params["gd"] = "-p x_row 20 -p x_col 20 -p w_row 40 -p size 8 -p parallel 8 "
    # function_invoke_params["dv"] = "-p size 5000 -p parallel 8 "

    for function_id in function_invoke_params.keys():
        function_invoke_params[function_id] = function_invoke_params[function_id] + "-p couch_link {} -p db_name {}".format(COUCH_LINK, function_id)

    characterize_functions(
        interval=interval, 
        alloc_range=alloc_range,
        cold_loop_time=cold_loop_time,
        warm_loop_time=warm_loop_time,
        file_path=file_path,
        function_invoke_params=function_invoke_params
    )

    print("")
    print("Workload characterization finished!")
    print("")
