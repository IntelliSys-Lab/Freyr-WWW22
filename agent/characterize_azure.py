import pandas as pd
import csv

#
# Import Azure Functions traces
#

def characterize_azure(azure_file_path):     
    csv_suffix = ".csv"
    azure_mem_dist = [["uuid", "pct1", "pct99"]]
    azure_duration_dist = [["uuid", "pct1", "pct99"]]

    # Memory traces
    # n_memory_files = ["01", "02", "03", "04", "05", "06", "07", "08", "09", "10", "11", "12"]
    n_memory_files = ["01"]
    memory_prefix = "app_memory_percentiles.anon.d"
    
    for n in n_memory_files:
        memory_df = pd.read_csv(azure_file_path + memory_prefix + n + csv_suffix, index_col="HashApp")
        memory_df = memory_df[~memory_df.index.duplicated()]
        memory_df_dict = memory_df.to_dict('index')
        
        for func_hash in memory_df_dict.keys():
            mem_trace = memory_df_dict[func_hash]
            azure_mem_dist.append([func_hash, mem_trace["AverageAllocatedMb_pct1"], mem_trace["AverageAllocatedMb_pct99"]])

    print("Finish matching memory traces!")

    # Duration traces
    # n_duration_files = ["01", "02", "03", "04", "05", "06", "07", "08", "09", "10", "11", "12", "13", "14"]
    n_duration_files = ["01"]
    duration_prefix = "function_durations_percentiles.anon.d"

    for n in n_duration_files:
        duration_df = pd.read_csv(azure_file_path + duration_prefix + n + csv_suffix, index_col="HashFunction")
        duration_df = duration_df[~duration_df.index.duplicated()]
        duration_df_dict = duration_df.to_dict('index')

        for func_hash in duration_df_dict.keys():
            duration_trace = duration_df_dict[func_hash]
            azure_duration_dist.append([func_hash, duration_trace["percentile_Average_1"], duration_trace["percentile_Average_99"]])

    print("Finish matching duration traces!")

    with open(azure_file_path + "azure_mem_dist.csv", "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerows(azure_mem_dist)

    with open(azure_file_path + "azure_duration_dist.csv", "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerows(azure_duration_dist)


if __name__ == "__main__":
    azure_file_path = "azurefunctions-dataset2019/"

    print("Load Azure Functions traces...")
    characterize_azure(azure_file_path=azure_file_path)
    print("Characterization complete!")
