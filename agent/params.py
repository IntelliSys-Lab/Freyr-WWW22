from run_command import run_cmd
import torch.nn as nn

#
# Global variables
#

# Environment parameters
WSK_CLI = "wsk -i"
N_INVOKER = int(run_cmd('cat ../ansible/environments/distributed/hosts | grep "invoker" | grep -v "\[invokers\]" | wc -l'))
REDIS_HOST = run_cmd('cat ../ansible/environments/distributed/hosts | grep -A 1 "\[edge\]" | grep "ansible_host" | awk {}'.format("{'print $1'}"))
REDIS_PORT = 6379
REDIS_PASSWORD = "openwhisk"
COUCH_PROTOCOL = "http"
COUCH_USER = "whisk_admin"
COUCH_PASSWORD = "some_passw0rd"
COUCH_HOST = run_cmd('cat ../ansible/environments/distributed/hosts | grep -A 1 "\[db\]" | grep "ansible_host" | awk {}'.format("{'print $1'}"))
COUCH_PORT = "5984"
COUCH_LINK = "{}://{}:{}@{}:{}/".format(COUCH_PROTOCOL, COUCH_USER, COUCH_PASSWORD, COUCH_HOST, COUCH_PORT)
COOL_DOWN = "refresh_openwhisk"
ENV_INTERVAL_LIMIT = 1
UPDATE_RETRY_TIME = 100
CPU_CAP_PER_FUNCTION = 8
MEMORY_CAP_PER_FUNCTION = 8
MEMORY_UNIT = 64

# Training parameters
AZURE_FILE_PATH = "azurefunctions-dataset2019/"
# TRACE_FILE_PREFIX = "sampled_invocation_traces_"
TRACE_FILE_PREFIX = "exp_openwhisk_invocation_traces_"
TRACE_FILE_SUFFIX = ".csv"
EXP_TRAIN = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]
EXP_EVAL = [0]
USER_DEFINED_DICT = {
    "dh": {"cpu": 2, "memory": 2}, 
    "eg": {"cpu": 1, "memory": 1}, 
    "ip": {"cpu": 2, "memory": 4}, 
    "vp": {"cpu": 2, "memory": 6}, 
    "ir": {"cpu": 2, "memory": 6}, 
    "knn": {"cpu": 2, "memory": 4}, 
    "alu": {"cpu": 1, "memory": 2}, 
    "ms": {"cpu": 1, "memory": 2}, 
    "gd": {"cpu": 1, "memory": 4}, 
    "dv": {"cpu": 2, "memory": 6}
}
MAX_EPISODE_TRAIN = 50
MAX_EPISODE_EVAL = 10
STATE_DIM = 11
EMBED_DIM = 32
NUM_HEADS = 1
ACTION_DIM = 1
HIDDEN_DIMS = [32, 16]
LEARNING_RATE = 1e-3
ACTIVATION = nn.Tanh()
DISCOUNT_FACTOR = 1
PPO_CLIP = 0.2
PPO_EPOCH = 4
VALUE_LOSS_COEF = 0.5
ENTROPY_COEF = 0.01
MODEL_SAVE_PATH = "ckpt/"
MODEL_NAME = "min_avg_duration_slo.ckpt"
        
#
# Parameter classes
#

class EnvParameters():
    """
    Parameters used for generating Environment
    """
    def __init__(
        self,
        n_invoker,
        redis_host,
        redis_port,
        redis_password,
        couch_link,
        cool_down,
        interval_limit,
        update_retry_time,
        cpu_cap_per_function,
        memory_cap_per_function,
        memory_unit
    ):
        self.n_invoker = n_invoker
        self.redis_host = redis_host
        self.redis_port = redis_port
        self.redis_password = redis_password
        self.couch_link = couch_link
        self.cool_down = cool_down
        self.interval_limit = interval_limit
        self.update_retry_time = update_retry_time
        self.cpu_cap_per_function = cpu_cap_per_function
        self.memory_cap_per_function = memory_cap_per_function
        self.memory_unit = memory_unit

class WorkloadParameters():
    """
    Parameters used for workload configuration
    """
    def __init__(
        self,
        azure_file_path,
        user_defined_dict,
        exp_id
    ):
        self.azure_file_path = azure_file_path
        self.user_defined_dict = user_defined_dict
        self.exp_id = exp_id

class FunctionParameters():
    """
    Parameters used for generating Function
    """
    def __init__(
        self,
        function_id,
        cpu_user_defined,
        memory_user_defined,
        cpu_cap_per_function,
        memory_cap_per_function,
        invoke_params=None
    ):
        self.function_id = function_id
        self.invoke_params = invoke_params
        self.cpu_user_defined = cpu_user_defined
        self.memory_user_defined = memory_user_defined
        self.cpu_cap_per_function = cpu_cap_per_function
        self.memory_cap_per_function = memory_cap_per_function

class EventPQParameters():
    """
    Parameters used for generating EventPQ
    """
    def __init__(
        self,
        azure_invocation_traces
    ):
        self.azure_invocation_traces = azure_invocation_traces
