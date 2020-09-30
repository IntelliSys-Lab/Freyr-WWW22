import pandas as pd
from utils import Function, Profile, Timetable
from params import FunctionParameters, TimetableParameters


class WorkflowGenerator():
    """
    Generate workflows
    """
    def azure_params(
        self,
        max_timestep=120,
        azure_file_path="azurefunctions-dataset2019/",
        memory_traces_file="sampled_memory_traces.csv",
        invocation_traces_file="sampled_invocation_traces.csv"
    ):
        memory_traces = pd.read_csv(azure_file_path + memory_traces_file)
        invocation_traces = pd.read_csv(azure_file_path + invocation_traces_file)

        function_params_dict = {}

        # Retrieve function hash and its corresponding application hash
        for _, row in invocation_traces.iterrows():
            function_id = row["FunctionId"]
            function_params_dict[function_id] = {}

        for function_id in function_params_dict.keys():
            for _, row in memory_traces.iterrows():
                if row["FunctionId"] == function_id:
                    if row["AverageAllocatedMb"] < 256:
                        least_hint = 1
                        function_params_dict[function_id]["memory_least_hint"] = least_hint
                        function_params_dict[function_id]["cpu_least_hint"] = least_hint
                    elif row["AverageAllocatedMb"] > 2048:
                        least_hint = 8
                        function_params_dict[function_id]["memory_least_hint"] = least_hint
                        function_params_dict[function_id]["cpu_least_hint"] = least_hint
                    else:
                        least_hint = int(row["AverageAllocatedMb"]/256) + 1
                        function_params_dict[function_id]["memory_least_hint"] = least_hint
                        function_params_dict[function_id]["cpu_least_hint"] = least_hint

                    function_params_dict[function_id]["memory_cap"] = 8
                    function_params_dict[function_id]["cpu_cap"] = 8
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
            max_timestep=max_timestep, 
            distribution_type="azure",
            azure_invocation_traces=invocation_traces
        )

        return profile_params, timetable_params

    def generate_profile(self, profile_params):
        function_params = profile_params
        function_list = []
        
        # Hardcoded parameters of functions
        for param in function_params:
            if param.function_id == "alu":
                param.invoke_params = "-p loopTime 10000000 -p parallelIndex 100" # 64: 1.3 sec, 1: 10 sec
            elif param.function_id == "ms":
                param.invoke_params = "-p listSize 100000 -p loopTime 1" # 64: 1.3 sec, 1: 5.5 sec
            elif param.function_id == "gd":
                param.invoke_params = "-p x_row 20 -p x_col 20 -p w_row 50 -p loopTime 1" # 64: 2.2 sec, 1: 8.7 sec
            elif param.function_id == "knn":
                param.invoke_params = "-p datasetSize 1000 -p featureDim 100 -p k 3 -p loopTime 1" # 64: 1.7 sec, 1: 7.2 sec
            elif param.function_id == "imageProcessSequence":
                param.invoke_params = "-p imageName test.jpg" # 64: 11.5 sec, 1: 26.6 sec
            elif param.function_id == "alexa-frontend":
                param.invoke_params = "-p utter 'open smarthome to I love Taylor Swift'" # 64: 4 sec, 1: 9.6 sec
            
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
        timetable_params=None,
        max_timestep=120,
    ):
        if default == "azure":
            default_profile_params, default_timetable_params = self.azure_params(max_timestep=max_timestep)

        if profile_params is None:
            profile_params = default_profile_params
        profile = self.generate_profile(profile_params)
            
        if timetable_params is None:
            timetable_params = default_timetable_params
        timetable = self.generate_timetable(profile, timetable_params)
            
        return profile, timetable

