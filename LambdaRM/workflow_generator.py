import pandas as pd
from utils import Function, Profile, Timetable
from params import FunctionParameters, TimetableParameters


class WorkflowGenerator():
    """
    Generate workflows
    """
    def azure_params(
        self,
        azure_file_path="azurefunctions-dataset2019/",
        memory_traces_file="sampled_memory_traces.csv",
        duration_traces_file="sampled_duration_traces.csv",
        invocation_traces_file="sampled_invocation_traces.csv"
    ):
        memory_traces = pd.read_csv(azure_file_path + memory_traces_file)
        duration_traces = pd.read_csv(azure_file_path + duration_traces_file)
        invocation_traces = pd.read_csv(azure_file_path + invocation_traces_file)

        function_params_dict = {}

        # Retrieve function hash and its corresponding application hash
        for _, row in duration_traces.iterrows():
            function_id = row["FunctionId"]
            function_params_dict[function_id] = {}

        for function_id in function_params_dict.keys():
            for _, row in memory_traces.iterrows():
                if row["FunctionId"] == function_id:
                    if row["AverageAllocatedMb"] < 256:
                        function_params_dict[function_id]["memory_least_hint"] = 3
                        function_params_dict[function_id]["cpu_least_hint"] = 3
                    elif row["AverageAllocatedMb"] > 1024:
                        function_params_dict[function_id]["memory_least_hint"] = 15
                        function_params_dict[function_id]["cpu_least_hint"] = 15
                    else:
                        least_hint = int(row["AverageAllocatedMb"]/128) + 1
                        function_params_dict[function_id]["memory_least_hint"] = least_hint
                        function_params_dict[function_id]["cpu_least_hint"] = least_hint

                    function_params_dict[function_id]["memory_cap"] = 15
                    function_params_dict[function_id]["cpu_cap"] = 15
                    break

        # Create Profile paramters
        function_params = []

        for function_id in function_params_dict.keys():
            param = FunctionParameters(
                cpu_least_hint=function_params_dict[function_id]["cpu_least_hint"],
                memory_least_hint=function_params_dict[function_id]["memory_least_hint"],
                cpu_cap=function_params_dict[function_id]["cpu_cap"],
                memory_cap=function_params_dict[function_id]["memory_cap"],
                function_id=function_id
            )
            
            function_params.append(param)

        profile_params = function_params

        # Create timetable based on invocation traces
        timetable_params = TimetableParameters(
            max_timestep=100, 
            distribution_type="azure",
            azure_invocation_traces=invocation_traces
        )

        return profile_params, timetable_params

    def generate_profile(self, profile_params):
        function_params = profile_params
        function_list = []
        
        # Hardcoded functions
        for param in function_params:
            if param.function_id == "function0":
                param.invoke_params = "-p threads 2 -p calcs 5000000 -p sleep 0 -p loops 2 -p arraySize 1000000"
            elif param.function_id == "function1":
                param.invoke_params = "-p bucket_name openwhisk.tlq -p key 100000_Sales_Records.csv"
            elif param.function_id == "function2":
                param.invoke_params = "-p threads 2 -p calcs 200000 -p sleep 0 -p loops 2 -p arraySize 100000"
            elif param.function_id == "function3":
                param.invoke_params = "-p bucket_name openwhisk.tlq -p key 100000_Sales_Records.csv"
            
            function = Function(param)
            function.set_function(
                cpu=param.cpu_least_hint, 
                memory=param.memory_least_hint
            ) # Initially set as hinted
            
            function_list.append(function)
        
        profile = Profile(function_profile=function_list)

        return profile
    
    def azure_distribution(
        self,
        profile,
        timetable_params
    ):
        max_timestep = timetable_params.max_timestep
        invocation_traces = timetable_params.azure_invocation_traces

        function_list = profile.function_profile
        timetable_list = []

        for i in range(max_timestep):
            timestep = []

            for _, row in invocation_traces.iterrows():
                timestep.append(row["{}".format(i+1)])

            timetable_list.append(timestep)
        
        timetable = Timetable(timetable_list)
        return timetable

    def generate_timetable(
        self, 
        profile,
        timetable_params
    ):
        if timetable_params.distribution_type == "azure":
            timetable = self.azure_distribution(profile, timetable_params)
        
        return timetable
    
    def generate_workflow(
        self, 
        default="azure",
        profile_params=None, 
        timetable_params=None
    ):
        if default == "azure":
            default_profile_params, default_timetable_params = self.azure_params()

        if profile_params is None:
            profile_params = default_profile_params
        profile = self.generate_profile(profile_params)
            
        if timetable_params is None:
            timetable_params = default_timetable_params
        timetable = self.generate_timetable(profile, timetable_params)
            
        return profile, timetable

