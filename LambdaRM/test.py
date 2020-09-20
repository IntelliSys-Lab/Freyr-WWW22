import subprocess
import numpy as np
import copy as cp
from params import WSK_CLI



def run_cmd(cmd):
    pong = subprocess.Popen(
        cmd,
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    result = pong.stdout.read().decode().replace('\n', '')

    return result

def timeout_test():
    cmd = '{} activation get {} | grep -v "ok" | jq .annotations[3].value'.format(WSK_CLI, "e8679b44192441f8a79b441924f1f882")
    timeout = str(run_cmd(cmd))
    if timeout == "false":
        print("timeout: false")
    else:
        print("timeout: true")

def cold_start_test():
    cmd = '{} activation get {} | grep -v "ok" | jq .annotations[5]'.format(WSK_CLI, "e8679b44192441f8a79b441924f1f882")
    cold_start = str(run_cmd(cmd))
    if cold_start == "null":
        print("cold_start: false")
    else:
        print("cold_start: true")



timeout_test()
cold_start_test()