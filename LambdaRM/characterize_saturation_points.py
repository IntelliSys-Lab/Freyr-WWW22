import time
import numpy as np
from utils import run_cmd
from params import WSK_CLI
from logger import Logger


def cold_start(app, invoke_param):
    result = {}
    loop_time = 10
    resource_levels = [1, 10, 19, 28, 37, 46, 55, 64]

    for _ in range(loop_time):
        for level in resource_levels:
            if level not in result.keys():
                result[level] = []

            run_cmd('{} action update {} -m {}'.format(WSK_CLI, app, level))
            if app == "imageProcessSequence":
                run_cmd('{} action update storeImageMetadata -m {}'.format(WSK_CLI, level))
                run_cmd('{} action update thumbnail -m {}'.format(WSK_CLI, level))
                run_cmd('{} action update handler -m {}'.format(WSK_CLI, level))
                run_cmd('{} action update transformMetadata -m {}'.format(WSK_CLI, level))
                run_cmd('{} action update extractImageMetadata -m {}'.format(WSK_CLI, level))
            elif app == "alexa-frontend":
                run_cmd('{} action update alexa-smarthome -m {}'.format(WSK_CLI, level))
                run_cmd('{} action update alexa-home-plug -m {}'.format(WSK_CLI, level))
                run_cmd('{} action update alexa-home-air-conditioning -m {}'.format(WSK_CLI, level))
                run_cmd('{} action update alexa-home-tv -m {}'.format(WSK_CLI, level))
                run_cmd('{} action update alexa-home-light -m {}'.format(WSK_CLI, level))
                run_cmd('{} action update alexa-home-door -m {}'.format(WSK_CLI, level))
                run_cmd('{} action update alexa-reminder -m {}'.format(WSK_CLI, level))
                run_cmd('{} action update alexa-fact -m {}'.format(WSK_CLI, level))
                run_cmd('{} action update alexa-interact -m {}'.format(WSK_CLI, level))

            try:
                duration = int(run_cmd('{} action invoke {} -b {} | grep -v "ok:" | jq .duration'.format(WSK_CLI, app, invoke_param)))
                result[level].append(duration)
            except ValueError:
                pass

    for level in result.keys():
        avg_duration = np.mean(result[level])
        result[level].append(avg_duration)

    return result

def warm_start(app, invoke_param):
    result = {}
    loop_time = 11
    resource_levels = [1, 10, 19, 28, 37, 46, 55, 64]

    for level in resource_levels:
        result[level] = []
        run_cmd('{} action update {} -m {}'.format(WSK_CLI, app, level))
        if app == "imageProcessSequence":
            run_cmd('{} action update storeImageMetadata -m {}'.format(WSK_CLI, level))
            run_cmd('{} action update thumbnail -m {}'.format(WSK_CLI, level))
            run_cmd('{} action update handler -m {}'.format(WSK_CLI, level))
            run_cmd('{} action update transformMetadata -m {}'.format(WSK_CLI, level))
            run_cmd('{} action update extractImageMetadata -m {}'.format(WSK_CLI, level))
        elif app == "alexa-frontend":
            run_cmd('{} action update alexa-smarthome -m {}'.format(WSK_CLI, level))
            run_cmd('{} action update alexa-home-plug -m {}'.format(WSK_CLI, level))
            run_cmd('{} action update alexa-home-air-conditioning -m {}'.format(WSK_CLI, level))
            run_cmd('{} action update alexa-home-tv -m {}'.format(WSK_CLI, level))
            run_cmd('{} action update alexa-home-light -m {}'.format(WSK_CLI, level))
            run_cmd('{} action update alexa-home-door -m {}'.format(WSK_CLI, level))
            run_cmd('{} action update alexa-reminder -m {}'.format(WSK_CLI, level))
            run_cmd('{} action update alexa-fact -m {}'.format(WSK_CLI, level))
            run_cmd('{} action update alexa-interact -m {}'.format(WSK_CLI, level))

        for loop in range(loop_time):
            if loop > 0:
                try:
                    duration = int(run_cmd('{} action invoke {} -b {} | grep -v "ok:" | jq .duration'.format(WSK_CLI, app, invoke_param)))
                    result[level].append(duration)
                except ValueError:
                    pass

    for level in result.keys():
        avg_duration = np.mean(result[level])
        result[level].append(avg_duration)

    return result

def characterize_apps(file_name, app_invoke_params):
    logger_wrapper = Logger()
    logger = logger_wrapper.get_logger(file_name, True)

    logger.debug("")
    logger.debug("**********")
    logger.debug("**********")
    logger.debug("**********")
    logger.debug("")
    logger.debug(time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()))

    for app in app_invoke_params.keys():
        invoke_param = app_invoke_params[app]
        cold_result = cold_start(app, invoke_param)
        warm_result = warm_start(app, invoke_param)

        logger.debug("")
        logger.debug("{}:".format(app))

        # Log cold starts
        for level in cold_result.keys():
            logger.debug("{} cold start at {}:".format(app, level))
            logger.debug(','.join(str(duration) for duration in cold_result[level]))

        # Log warm starts
        for level in warm_result.keys():
            logger.debug("{} warm start at {}:".format(app, level))
            logger.debug(','.join(str(duration) for duration in warm_result[level]))


if __name__ == "__main__":
    file_name = "ApplicationSaturationPoints"
    app_invoke_params = {}
    app_invoke_params["alu"] = "-p loopTime 100000000 -p parallelIndex 100"
    app_invoke_params["ms"] = "-p listSize 300000 -p loopTime 1"
    app_invoke_params["gd"] = "-p x_row 50 -p x_col 50 -p w_row 50 -p loopTime 1"
    app_invoke_params["knn"] = "-p datasetSize 10000 -p featureDim 1000 -p k 3 -p loopTime 1"
    app_invoke_params["imageProcessSequence"] = "-p imageName test.jpg"
    app_invoke_params["alexa-frontend"] = "-p utter 'open smarthome to I love Taylor Swift'"

    characterize_apps(file_name, app_invoke_params)
