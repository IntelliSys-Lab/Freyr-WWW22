import couchdb
import docker
import json
import psutil

from utils import run_cmd
from params import WSK_CLI

# couch_protocol = "http"
# couch_user = "whisk_admin"
# couch_password = "some_passw0rd"
# couch_host = "192.168.196.65"
# couch_port = "5984"

# couch = couchdb.Server(
#     "{}://{}:{}@{}:{}/".format(
#         couch_protocol, couch_user, couch_password, couch_host, couch_port
#     )
# )

# couch_activations = couch["whisk_distributed_activations"]
# couch_whisks = couch["whisk_distributed_whisks"]
# couch_subjects = couch["whisk_distributed_subjects"]

# request_id = "b8259acb7632455ba59acb7632955bd3"
# # print(couch_activations["guest/{}".format(request_id)])
# for i in couch_activations:
#     if request_id in couch_activations:
#         print(i)

cpu_times = psutil.cpu_times()
cpu_stats = psutil.cpu_stats()
cpu_freq = psutil.cpu_freq()
cpu_percent = psutil.cpu_percent()
cpu_count = psutil.cpu_count()
load_avg = psutil.getloadavg()

virtual_memory = psutil.virtual_memory()
swap_memory = psutil.swap_memory()

disk_partitions = psutil.disk_partitions()
disk_usage = psutil.disk_usage('/')
disk_io_counters = psutil.disk_io_counters()

net_io_counters = psutil.net_io_counters()
net_connections = psutil.net_connections()
net_if_addrs = psutil.net_if_addrs()
net_if_stats = psutil.net_if_stats()

print(load_avg[0])