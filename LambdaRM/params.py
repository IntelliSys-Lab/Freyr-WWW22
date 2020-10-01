#
# Global variables
#

WSK_CLI = "wsk -i"
        
#
# Parameter classes
#

class FunctionParameters():
    """
    Parameters used for generating Function
    """
    def __init__(
        self,
        cpu_cap=8,
        memory_cap=8,
        cpu_least_hint=1,
        memory_least_hint=1,
        function_id=None,
        invoke_params=None,
        sequence=None,
    ):
        self.cpu_cap = cpu_cap
        self.memory_cap = memory_cap
        self.cpu_least_hint = cpu_least_hint
        self.memory_least_hint = memory_least_hint
        self.function_id = function_id
        self.invoke_params = invoke_params
        self.sequence = sequence

class TimetableParameters():
    """
    Parameters used for generating Timetable
    """
    def __init__(
        self,
        max_timestep=200,
        distribution_type="poisson",
        mod_factors=[1, 1, 1, 1, 1, 2, 5, 8, 10, 8],
        bernoulli_p=0.5,
        poisson_mu=0.8,
        azure_invocation_traces=None
    ):
        self.max_timestep = max_timestep
        self.distribution_type = distribution_type
        
        if distribution_type == "mod":
            self.mod_factors = mod_factors
        elif distribution_type == "bernoulli":
            self.bernoulli_p = bernoulli_p
        elif distribution_type == "poisson":
            self.poisson_mu = poisson_mu
        elif distribution_type == "azure":
            self.azure_invocation_traces = azure_invocation_traces

    
    
    
