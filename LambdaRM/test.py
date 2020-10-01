import couchdb
import subprocess
from params import WSK_CLI

couch_protocol = "http"
couch_user = "whisk_admin"
couch_password = "some_passw0rd"
couch_host = "192.168.196.65"
couch_port = "5984"

couch = couchdb.Server(
    "{}://{}:{}@{}:{}/".format(
        couch_protocol, couch_user, couch_password, couch_host, couch_port
    )
)


def run_cmd(cmd):
    pong = subprocess.Popen(
        cmd,
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    result = pong.stdout.read().decode().replace('\n', '')

    return result


couch_activations = couch["whisk_distributed_activations"]
couch_whisks = couch["whisk_distributed_whisks"]

# run_cmd("{} action invoke {} {}".format(WSK_CLI, "function0", "-p threads 2 -p calcs 5000000 -p sleep 0 -p loops 2 -p arraySize 1000000"))

# doc_function = couch_whisks["guest/function0"]
# print(doc_function)
# doc_function["limits"]["memory"] = 1
# couch_whisks.save(doc_function)

doc_function = couch_activations["guest/1bc6cd95ca5e49c486cd95ca5e49c4ea"]
if len(doc_function["annotations"]) >= 4:
    for i in doc_function["annotations"]:
        print(i)
#1bc6cd95ca5e49c486cd95ca5e49c4ea

# run_cmd("{} action invoke {} {}".format(WSK_CLI, "function0", "-p threads 2 -p calcs 5000000 -p sleep 0 -p loops 2 -p arraySize 1000000"))

# activation_id = "fb886d9c540b43d2886d9c540b43d297"
# activation_id = "de910bbc780f4ae3910bbc780f9ae311"
# doc_activation = couch_activations.get("guest/{}".format(activation_id))
# if doc_activation is not None:
#     print(doc_activation["annotations"])
