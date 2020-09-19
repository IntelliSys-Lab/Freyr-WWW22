import numpy as np


class EnvParameters():
    """
    Parameters used for generating FaaSEnv
    """
    def __init__(
        self,
        cpu_total=32*100,
        memory_total=45*100,
        cpu_cap_per_function=32,
        memory_cap_per_function=45,
        reward_type="slowdown",
        interval=1,
        decay_factor=1,
        timeout_penalty=600
    ):
        self.cpu_total = cpu_total
        self.memory_total = memory_total
        self.cpu_cap_per_function = cpu_cap_per_function
        self.memory_cap_per_function = memory_cap_per_function
        self.reward_type = reward_type
        self.interval = interval
        self.decay_factor = decay_factor
        self.timeout_penalty = timeout_penalty

        
class FunctionParameters():
    """
    Parameters used for generating Function
    """
    def __init__(
        self,
        cpu_cap=15,
        memory_cap=15,
        cpu_least_hint=1,
        memory_least_hint=1,
        function_id=None
    ):
        self.cpu_cap = cpu_cap
        self.memory_cap = memory_cap
        self.cpu_least_hint = cpu_least_hint
        self.memory_least_hint = memory_least_hint
        self.function_id = function_id

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

    
    
    
