import pandas as pd
import heapq
import itertools
from utils import Function, Profile, EventPQ
from params import FunctionParameters, EventPQParameters, COUCH_LINK, TRACE_FILE_PREFIX, TRACE_FILE_SUFFIX, CPU_CAP_PER_FUNCTION, MEMORY_CAP_PER_FUNCTION


class WorkloadGenerator():
    """
    Generate workfloads
    """
    def __init__(
        self,
        user_defined_dict,
        exp_id,
        azure_file_path="azurefunctions-dataset2019/"
    ):
        self.azure_file_path = azure_file_path
        self.user_defined_dict = user_defined_dict
        self.exp_id = exp_id

    def generate_profile_params(self):
        profile_params = {}
        for function_id in self.user_defined_dict.keys():
            param = FunctionParameters(
                function_id=function_id,
                cpu_user_defined=self.user_defined_dict[function_id]["cpu"],
                memory_user_defined=self.user_defined_dict[function_id]["memory"],
                cpu_cap_per_function=CPU_CAP_PER_FUNCTION,
                memory_cap_per_function=MEMORY_CAP_PER_FUNCTION
            )
            
            profile_params[function_id] = param

        return profile_params

    def generate_event_pq_params(self):
        invocation_traces = pd.read_csv(self.azure_file_path + TRACE_FILE_PREFIX + str(self.exp_id) + TRACE_FILE_SUFFIX)
        event_pq_params = EventPQParameters(azure_invocation_traces=invocation_traces)
        return event_pq_params

    def generate_profile(self):
        function_profile = {}
        profile_params = self.generate_profile_params()
        
        # Hardcoded parameters of functions
        for function_id in profile_params.keys():
            param = profile_params[function_id]
            if function_id == "dh":
                param.invoke_params = "-p username hanfeiyu -p size 20000 -p parallel 8 "
            elif param.function_id == "eg":
                param.invoke_params = "-p size 10000 -p parallel 2 "
            elif param.function_id == "ip":
                param.invoke_params = "-p width 1000 -p height 1000 -p size 36 -p parallel 2 "
            elif param.function_id == "vp":
                param.invoke_params = "-p duration 10 -p size 1 -p parallel 1 " 
            elif param.function_id == "ir":
                param.invoke_params = "-p size 1 -p parallel 1 " 
            elif param.function_id == "knn":
                param.invoke_params = "-p dataset_size 500 -p feature_dim 300 -p k 3 -p size 12 -p parallel 6 " 
            elif param.function_id == "alu":
                param.invoke_params = "-p size 100000000 -p parallel 16 " 
            elif param.function_id == "ms":
                param.invoke_params = "-p size 1000000 -p parallel 6 " 
            elif param.function_id == "gd":
                param.invoke_params = "-p x_row 20 -p x_col 20 -p w_row 40 -p size 4 -p parallel 2 " 
            elif param.function_id == "dv":
                param.invoke_params = "-p size 5000 -p parallel 4 " 

            # Add CouchDB name and link, set default configuration
            param.invoke_params = param.invoke_params + "-p couch_link {} -p db_name {}".format(COUCH_LINK, function_id)
            function = Function(param)
            function.set_function(cpu=param.cpu_user_defined, memory=param.memory_user_defined)

            # Add to profile
            function_profile[function_id] = function
        
        profile = Profile(function_profile=function_profile)

        return profile
    
    def generate_event_pq(self):
        event_pq_params = self.generate_event_pq_params()
        invocation_traces = event_pq_params.azure_invocation_traces
        max_timestep = len(invocation_traces.columns) - 2

        pq = []
        counter = itertools.count()
        for timestep in range(max_timestep):
            for _, row in invocation_traces.iterrows():
                function_id = row["HashFunction"]
                invoke_num = row["{}".format(timestep+1)]
                for _ in range(invoke_num):
                    heapq.heappush(pq, (timestep, next(counter), function_id))

        event_pq = EventPQ(pq=pq, max_timestep=max_timestep)
        return event_pq
    