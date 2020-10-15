import couchdb
import docker

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


docker_client = docker.from_env()
# docker_api_client = docker.APIClient(base_url='unix://var/run/docker.sock')

for container in docker_client.api.containers(filters={"name": "t"}):
    id = container["Id"]
    print(docker_client.api.inspect_container(id)["HostConfig"]["CpuShares"])

