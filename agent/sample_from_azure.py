import numpy as np
import pandas as pd
import csv
import random
import os
import stat
import sys
from glob import glob

import params


#
# Import Azure Functions traces
#

def sample_from_azure(
    azure_file_path,
    max_exp,
    max_timestep,
    min_timestep,
    max_invoke_per_time,
    min_invoke_per_time,
    max_invoke_per_func,
    min_invoke_per_func,
    exp_func_list
):     
    csv_suffix = ".csv"

    # Invocation traces
    trace_dict = {}
    n_invocation_files = ["01", "02", "03", "04", "05", "06", "07", "08", "09", "10", "11", "12", "13", "14"]
    invocation_prefix = "invocations_per_function_md.anon.d"

    for n in n_invocation_files:
        invocation_df = pd.read_csv(azure_file_path + invocation_prefix + n + csv_suffix, index_col="HashFunction")
        invocation_df = invocation_df[~invocation_df.index.duplicated()]
        invocation_df_dict = invocation_df.to_dict('index')

        for func_hash in invocation_df_dict.keys():
            invocation_trace = invocation_df_dict[func_hash]
            timeline = []

            for timestep in range(max_timestep):
                invoke_num = int(invocation_trace["{}".format(timestep+1)])

                # Verify invocation per time
                if invoke_num <= max_invoke_per_time and invoke_num >= min_invoke_per_time:
                    timeline.append(invoke_num)
                else:
                    break

            # Verify invocation per function
            if np.sum(timeline) <= max_invoke_per_func and np.sum(timeline) >= min_invoke_per_func and len(timeline) == 60:
                trace_dict[func_hash] = {}
                trace_dict[func_hash]["invocation_trace"] = timeline
                trace_dict[func_hash]["HashApp"] = invocation_trace["HashApp"]
                trace_dict[func_hash]["Trigger"] = invocation_trace["Trigger"]
            else:
                continue

    print("Finish sampling invocation traces!")

    # Memory traces
    n_memory_files = ["01", "02", "03", "04", "05", "06", "07", "08", "09", "10", "11", "12"]
    memory_prefix = "app_memory_percentiles.anon.d"
    
    for n in n_memory_files:
        memory_df = pd.read_csv(azure_file_path + memory_prefix + n + csv_suffix, index_col="HashApp")
        memory_df = memory_df[~memory_df.index.duplicated()]
        memory_df_dict = memory_df.to_dict('index')
        
        for func_hash in trace_dict.keys():
            app_hash = trace_dict[func_hash]["HashApp"]
            if app_hash in memory_df_dict:
                trace_dict[func_hash]["memory_trace"] = memory_df_dict[app_hash]

    print("Finish matching memory traces!")

    # Duration traces
    n_duration_files = ["01", "02", "03", "04", "05", "06", "07", "08", "09", "10", "11", "12", "13", "14"]
    duration_prefix = "function_durations_percentiles.anon.d"

    for n in n_duration_files:
        duration_df = pd.read_csv(azure_file_path + duration_prefix + n + csv_suffix, index_col="HashFunction")
        duration_df = duration_df[~duration_df.index.duplicated()]
        duration_df_dict = duration_df.to_dict('index')

        for func_hash in trace_dict.keys():
            if func_hash in duration_df_dict:
                trace_dict[func_hash]["duration_trace"] = duration_df_dict[func_hash]

    print("Finish matching duration traces!")

    # Remove incomplete traces
    func_remove_list = []
    for func_hash in trace_dict.keys():
        if "invocation_trace" not in trace_dict[func_hash] or \
            "memory_trace" not in trace_dict[func_hash] or \
            "duration_trace" not in trace_dict[func_hash]:
            func_remove_list.append(func_hash)

    for func_hash in func_remove_list:
        trace_dict.pop(func_hash)

    # Adapt to experimental traces
    # print("trace_dict length: {}".format(len(trace_dict)))
    metrics_dict = {
        "func_hash": [],
        "total_iat": 0,
        "calls": 0,
        "total_duration": 0
    }

    memory_trace_header = ["HashFunction", "SampleCount", "AverageAllocatedMb", "AverageAllocatedMb_pct1", \
        "AverageAllocatedMb_pct5", "AverageAllocatedMb_pct25", "AverageAllocatedMb_pct50", "AverageAllocatedMb_pct75", \
        "AverageAllocatedMb_pct95", "AverageAllocatedMb_pct99", "AverageAllocatedMb_pct100"]

    duration_trace_header = ["HashFunction", "Average", "Count", "Minimum", "Maximum", "percentile_Average_0", \
        "percentile_Average_1", "percentile_Average_25", "percentile_Average_50", "percentile_Average_75", \
        "percentile_Average_99", "percentile_Average_100"]

    for i in range(max_exp):
        func_hash_list = random.sample(list(trace_dict.keys()), k=len(exp_func_list))
        random_timestep = random.randint(min_timestep, max_timestep)

        invocation_trace_csv = []
        memory_trace_csv = []
        duration_trace_csv = []

        invocation_trace_header = ["HashFunction", "Trigger"] + list(range(1, random_timestep+1))
        invocation_trace_csv.append(invocation_trace_header)
        memory_trace_csv.append(memory_trace_header)
        duration_trace_csv.append(duration_trace_header)

        for index, function_id in enumerate(exp_func_list):
            func_hash = func_hash_list[index]
            invocation_trace = trace_dict[func_hash]["invocation_trace"][:random_timestep]
            
            # Record workload metrics
            if func_hash not in metrics_dict["func_hash"]:
                metrics_dict["func_hash"].append(func_hash)
            metrics_dict["calls"] = metrics_dict["calls"] + sum(invocation_trace)
            metrics_dict["total_iat"] = metrics_dict["total_iat"] + (len(invocation_trace) - 1)
            metrics_dict["total_duration"] = metrics_dict["total_duration"] + (len(invocation_trace))

            invocation_trace.insert(0, trace_dict[func_hash]["Trigger"])
            invocation_trace.insert(0, function_id)
            invocation_trace_csv.append(invocation_trace)

            memory_trace = [function_id]
            memory_trace_dict = trace_dict[func_hash]["memory_trace"]
            for header in memory_trace_header:
                if header != "HashFunction":
                    memory_trace.append(memory_trace_dict[header])

            memory_trace_csv.append(memory_trace)

            duration_trace = [function_id]
            duration_trace_dict = trace_dict[func_hash]["duration_trace"]
            for header in duration_trace_header:
                if header != "HashFunction":
                    duration_trace.append(duration_trace_dict[header])
            duration_trace_csv.append(duration_trace)

        with open(azure_file_path + "sampled_invocation_traces_{}.csv".format(i), "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerows(invocation_trace_csv)

        with open(azure_file_path + "sampled_memory_traces_{}.csv".format(i), "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerows(memory_trace_csv)

        with open(azure_file_path + "sampled_duration_traces_{}.csv".format(i), "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerows(duration_trace_csv)

    with open(azure_file_path + "z_metrics.csv", "w", newline="") as f:
        writer = csv.writer(f)
        metrics_dist_csv = []

        metrics_dist_csv.append(["funcs", len(metrics_dict["func_hash"])])
        metrics_dist_csv.append(["calls", metrics_dict["calls"]])
        metrics_dist_csv.append(["avg_iat", metrics_dict["total_iat"]/metrics_dict["calls"]])
        metrics_dist_csv.append(["request_per_sec", metrics_dict["calls"]/metrics_dict["total_duration"]])

        writer.writerows(metrics_dist_csv)

#
# Clean old sample files
#

def clean_old_samples(
    dir_name="azurefunctions-dataset2019/",
    file_pattern="sampled_*.csv"
):
    for file_name in glob(os.path.join(dir_name, file_pattern)):
        try:
            os.remove(file_name)
        except EnvironmentError:
            print("Require permission to {}".format(file_name))
            os.chmod(file_name, stat.S_IWRITE)
            os.remove(file_name)


if __name__ == "__main__":
    azure_file_path = "azurefunctions-dataset2019/"
    max_exp = 10
    max_timestep = 60
    min_timestep = 60
    max_invoke_per_time = 10
    min_invoke_per_time = 0
    max_invoke_per_func = 40
    min_invoke_per_func = 20
    exp_func_list = ["dh", "eg", "ip", "vp", "ir", "knn", "alu", "ms", "gd", "dv"]

    print("Clean old sample files...")
    clean_old_samples(dir_name=azure_file_path, file_pattern="sampled_*.csv")

    print("Load Azure Functions traces...")
    sample_from_azure(
        azure_file_path=azure_file_path,
        max_exp=max_exp,
        max_timestep=max_timestep,
        min_timestep=min_timestep,
        max_invoke_per_time=max_invoke_per_time,
        min_invoke_per_time=min_invoke_per_time,
        max_invoke_per_func=max_invoke_per_func,
        min_invoke_per_func=min_invoke_per_func,
        exp_func_list=exp_func_list
    )
    
    print("Sampling finished!")
