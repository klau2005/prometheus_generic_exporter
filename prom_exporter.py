#!/usr/bin/env python3
"""Run external scripts/commands and export their output as prometheus metrics"""

import ast
import glob
import json
import logging
import os
import queue
import socket
import threading
import time
from subprocess import run as run_cmd

import schedule
from prometheus_client import Counter, Gauge, start_http_server

__author__ = "Claudiu Tomescu"
__version__ = "0.10.0"
__date__ = "Sep 2025"
__maintainer__ = "Claudiu Tomescu"
__email__ = "klau2005@tutanota.com"
__status__ = "Production"

### Variables ###
config_files_list = glob.glob("configs/*.json")
# list that will be the main object loaded in memory with all details
# related to the scripts that will be executed, interval, arguments, etc
configs_list = []
cwd = os.getcwd()
job_queue = queue.Queue()
hostname = socket.gethostname()
ip_addr = socket.gethostbyname(hostname)
metrics_port = os.environ.get("METRICS_PORT", 8000)
DEFAULT_INTERVAL = 600
# in the future, we intend to use the metric type for creating the proper prometheus metric
# for now, we use the default of Gauge
# default_metric_type = "Gauge"
DEFAULT_METRIC_HELP = "Generic metric HELP"
log_levels = {
    "CRITICAL": 50,
    "ERROR": 40,
    "WARNING": 30,
    "INFO": 20,
    "DEBUG": 10,
    "NOTSET": 0,
}
log_level_name = os.environ.get("LOG_LEVEL", "INFO")
log_level = log_levels[log_level_name]
LOG_FMT = "[%(asctime)s] [%(levelname)s] %(message)s"

logging.basicConfig(level=log_level, datefmt="%Y-%m-%d %H:%M:%S %z", format=LOG_FMT)
logging.info('Starting Generic Prometheus Exporter version "%s"', __version__)
logging.info("Using log level %s", log_level_name)
# for the schedule module, we set the log level as WARNING as it is too noisy at INFO level
schedule.logger.setLevel(logging.WARNING)

# list to hold all instantiated prometheus metric objects
prom_metrics_list = []


### Functions ###
def run_ext_script(**kwargs):
    """
    run the external scripts, get their exit code and
    in case it is not 0, increase the error metric for that item; else it will
    convert the output as dictionary, instantiate one prometheus metric for each
    component the script tests and expose the metrics as prometheus metrics
    """

    cmd = kwargs["cmd"]
    # run command for each component we need to test and capture status code and output
    logging.debug('Executing external script with args: "%s"', cmd)
    result = run_cmd(cmd, capture_output=True, text=True, check=False)
    logging.debug("Got following result (exit code + output):")
    logging.debug("%s: %s", result.returncode, result.stdout)
    exit_code = result.returncode
    output = result.stdout.rstrip("\n")
    item = kwargs["item"]
    prom_metric_name = item["metric"]
    prometheus_metric_errors = kwargs["prom_metric_err"]
    # in the future, we intend to use the metric type for creating the proper prometheus metric
    # for now, we use the default of Gauge
    # metric_type = item.get("TYPE", default_metric_type)
    metric_help = item.get("HELP", DEFAULT_METRIC_HELP)
    labels_dict = kwargs["labels_dict"]
    labels_list = kwargs["labels_list"]

    # test if exit code is success
    if exit_code != 0:
        logging.warning('External command "%s" returned error:', cmd)
        logging.warning("Result: %s", result.stderr.rstrip("\n"))
        prometheus_metric_errors.labels(**labels_dict).inc()
    else:
        # if external script/command exited with 0, we start processing the result;
        # the subprocess function returns the output as string; we can see what this string
        # contains by trying to convert the output to a dict/float
        # (string types will generate error)
        try:
            output = ast.literal_eval(output)
        except ValueError:
            # looks this is not a supported type so we'll generate a helpful log warning message
            logging.warning("External command returned unsupported output type:")
            logging.warning('Output: "%s", Type: "%s"', output, type(output))
            # and we increment the metric error value for this item
            prometheus_metric_errors.labels(**labels_dict).inc()
            return
        # first check if the output returned by script is json/dict
        if isinstance(output, dict):
            for key in output.keys():
                # we set the value of the <key> for the "component" label in the labels dict
                labels_dict["component"] = key

                try:
                    # first we try to instantiate the metrics
                    prom_metric_obj = Gauge(prom_metric_name, metric_help, labels_list)
                except ValueError:
                    # if a metric with this name was already instantiated, we can find
                    # it in the global list defined above
                    for obj in prom_metrics_list:
                        if obj.describe()[0].name == prom_metric_name:
                            # try to set the metric value
                            try:
                                obj.labels(**labels_dict).set(output[key])
                            except ValueError:
                                # if we've come so far, it means the metric was already instantiated
                                # and we're trying to use different labels for the same metric name
                                logging.error("Invalid combination of metric{labels}:")
                                logging.error("%s%s", prom_metric_name, labels_dict)
                else:
                    # in case the metric was instantiated for the first time, we save it in a global
                    # list and set it's value based on the script output
                    try:
                        prom_metric_obj.labels(**labels_dict).set(output[key])
                    except ValueError:
                        # ValueError here probably means the labels defined when the prometheus
                        # metric was instantiated don't match the ones passed
                        # when setting the metric value
                        logging.error("Labels mismatch:")
                        logging.error("%s - %s", labels_list, labels_dict.keys())
                    else:
                        prom_metrics_list.append(prom_metric_obj)

        else:
            # try to see if it is int/float
            try:
                output = float(output)
            # if it's not an int/float, not sure what else it can be (we tested earlier for strings)
            except ValueError:
                pass
            else:
                try:
                    # first we try to instantiate the metrics
                    prom_metric_obj = Gauge(prom_metric_name, metric_help, labels_list)
                except ValueError:
                    # if a metric with this name was already instantiated, we can find
                    # it in the global list defined above
                    for obj in prom_metrics_list:
                        if obj.describe()[0].name == prom_metric_name:
                            # try to set the metric value
                            try:
                                obj.labels(**labels_dict).set(output)
                            except ValueError:
                                # if we've come so far, it means the metric was already instantiated
                                # and we're trying to use different labels for the same metric name
                                logging.error("Invalid combination of metric{labels}:")
                                logging.error("%s%s", prom_metric_name, labels_dict)
                else:
                    # in case the metric was instantiated for the first time, we save it in a global
                    # list and set it's value based on the script output
                    prom_metrics_list.append(prom_metric_obj)
                    prom_metric_obj.labels(**labels_dict).set(output)


def parse_config_folder(c_list):
    """
    generate list with all config files available
    """

    for config_file in config_files_list:
        logging.debug("New config file parsed: %s", config_file)
        c_list += parse_config_file(config_file)

    return c_list


def parse_config_file(f):
    """
    load the config file in json format, parse it and return a list from the scripts section;
    it does format validation and it merges any existing global labels with the local ones,
    overriding the global with the local
    """

    # Load json file with list of scripts to schedule and run
    try:
        with open(f, encoding="UTF-8") as config:
            scripts_dict = json.load(config)
    except PermissionError:
        logging.error("No permission to read %s/%s file", cwd, f)
        return []
    # if file is not in valid JSON format, log this and exit
    except ValueError:
        logging.error("Provided config file %s/%s is not a valid JSON file", cwd, f)
        return []

    # start validating the config file structure
    try:
        scripts_list = scripts_dict["scripts"]
    except KeyError:
        logging.error(
            "Provided config file %s/%s does not have the proper structure", cwd, f
        )
        return []
    if not isinstance(scripts_list, list):
        logging.error(
            "Provided config file %s/%s does not have the proper structure", cwd, f
        )
        return []

    # check if the file has a global_labels section
    global_labels = scripts_dict.get("global_labels", {})

    # iterate over each item in the scripts list and add the global labels
    # to the local ones (where they exist)
    for script in scripts_list:
        local_labels = script.get("labels", {})
        labels = global_labels.copy()
        labels.update(local_labels)
        script["labels"] = labels

        # we add a new label named "component" but first we check that no label
        # named like this was already defined in the config file
        # in that case, we don't want to delete the original but rename the label name and
        # preserve it's value; we also write a WARNING log entry describing this situation
        if "component" in script["labels"].keys():
            script["labels"]["user_defined_component"] = script["labels"].pop(
                "component"
            )
            logging.warning(
                "Found <component> label defined in config file, "
                "automatically renamed to <user_defined_component>"
            )

    return scripts_dict["scripts"]


def generate_params_dict(item):
    """
    Generate a command, item, error metric and labels dictionary
    """
    metric_name = item["metric"]
    metric_errors = f"{metric_name}_errors_total"
    script_interval = int(item.get("interval", DEFAULT_INTERVAL))
    # in the future, we intend to use the metric type for creating the proper prometheus metric
    # for now, we use the default of Gauge
    # metric_type = item.get("TYPE", default_metric_type)
    metric_help = item.get("HELP", DEFAULT_METRIC_HELP)
    # save script with parameters in a string; it will be passed as argument to the command
    script = item["script"]
    command = script
    try:
        for param in item["params"]:
            command += f" {param}"
    except KeyError:
        pass
    command = command.split()

    labels_dict = item.get("labels", {})
    # and add the value "main" to the corresponding labels dict key
    # (we'll overwrite it later where necessary)
    labels_dict["component"] = "main"
    labels_list = list(labels_dict.keys())

    # instantiate the prometheus counter metrics for the script errors item
    try:
        prometheus_metric_errors = Counter(metric_errors, metric_help, labels_list)
    # if it was already instantiated, just pass
    except ValueError:
        pass

    # save the command, item and the error metric in a dictionary
    param_dict = {
        "cmd": command,
        "item": item,
        "prom_metric_err": prometheus_metric_errors,
        "labels_list": labels_list,
        "labels_dict": labels_dict,
    }
    return param_dict, script_interval


def main():
    """
    main function where we start the Prometheus HTTP server
    and we enter the scheduler loop
    """

    # start the http server to expose the prometheus metrics
    logging.info("Starting web-server...")
    start_http_server(metrics_port, ip_addr)
    logging.info("Server started and listening at %s:%s", ip_addr, metrics_port)

    main_list = parse_config_folder(configs_list)

    if len(main_list) == 0:
        logging.error(
            "No valid config files to parse, serving only standard python metrics"
        )

    # main part of program that will go through all scripts in the list and run the command for each
    for item in main_list:
        param_dict, script_interval = generate_params_dict(item)
        # this list will hold 2 items, first one is the run_ext_script function, second one is
        # the dictionary generated above; we'll use this when we launch the threads for all items
        item_list = [run_ext_script, param_dict]

        # for each external script, add the list defined above in the queue at the predefined
        # interval; the main loop will continuosly get the scripts from the queue and run them
        logging.debug(
            'New item "%s" scheduled to run every "%s" seconds',
            item_list,
            script_interval,
        )
        schedule.every(script_interval).seconds.do(job_queue.put, item_list)

    # enter the main scheduler loop
    while True:
        # start the scheduling
        schedule.run_pending()
        try:
            # see if we have anything in the queue
            queue_item = job_queue.get(block=False)
        except queue.Empty:
            logging.debug("There are no items in the queue right now...")
            # if queue is empty for now, sleep for one second
            time.sleep(1)
        else:
            job_queue.task_done()
            # if queue has items, get them one by one and run them (we have functions and
            # corresponding dictionary as kwargs for the function in it)
            item_func = queue_item[0]
            item_kwargs = queue_item[1]

            def job_func():
                """run the run_ext_script function with params for each item"""
                item_func(**item_kwargs)

            # start a new thread for each function; this will let us run the functions in parallel
            logging.debug('Running "%s" in new thread', queue_item)
            worker_thread = threading.Thread(target=job_func)
            worker_thread.start()
        time.sleep(1)


if __name__ == "__main__":
    main()
