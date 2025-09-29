#!/usr/bin/env python3
"""Run external scripts/commands and export their output as prometheus metrics"""

import ast
import glob
import json
import logging
import os
import queue
import socket
import sys
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
configs_list = glob.glob("configs/*.json")
cwd = os.getcwd()
job_queue = queue.Queue()
hostname = socket.gethostname()
ip_addr = socket.gethostbyname(hostname)
metrics_port = os.environ.get("METRICS_PORT", 8000)
default_interval = 600
# in the future, we intend to use the metric type for creating the proper prometheus metric
# for now, we use the default of Gauge
# default_metric_type = "Gauge"
default_metric_help = "Generic metric HELP"
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
log_fmt = "[%(asctime)s] [%(levelname)s] %(message)s"

logging.basicConfig(level=log_level, datefmt="%Y-%m-%d %H:%M:%S %z", format=log_fmt)
logging.info('Starting Generic Prometheus Exporter version "{0}"'.format(__version__))
logging.info("Using log level {0}".format(log_level_name))
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
    logging.debug("Executing external script with args: '{0}'".format(cmd))
    result = run_cmd(cmd, capture_output=True, text=True)
    logging.debug("Got following result (exit code + output):")
    logging.debug("{0}: {1}".format(result.returncode, result.stdout))
    exit_code = result.returncode
    output = result.stdout.rstrip("\n")
    item = kwargs["item"]
    prom_metric_name = item["metric"]
    prometheus_metric_errors = kwargs["prom_metric_err"]
    # in the future, we intend to use the metric type for creating the proper prometheus metric
    # for now, we use the default of Gauge
    # metric_type = item.get("TYPE", default_metric_type)
    metric_help = item.get("HELP", default_metric_help)
    labels_dict = kwargs["labels_dict"]
    labels_list = kwargs["labels_list"]

    # test if exit code is success
    if exit_code != 0:
        logging.warning("External command '{0}' returned error:".format(cmd))
        logging.warning("Result: '{0}'".format(result.stderr.rstrip("\n")))
        prometheus_metric_errors.labels(**labels_dict).inc()
    else:
        # if external script/command exited with 0, we start processing the result;
        # the subprocess function returns the output as string; we can see what this string
        # contains by trying to convert the output to a dict/float (string types will generate error)
        try:
            output = ast.literal_eval(output)
        except ValueError:
            # looks this is not a supported type so we'll generate a helpful log warning message
            logging.warning("External command returned unsupported output type:")
            logging.warning("Output: '{0}', Type: '{1}'".format(output, type(output)))
            # and we increment the metric error value for this item
            prometheus_metric_errors.labels(**labels_dict).inc()
            return
        # first check if the output returned by script is json/dict
        if isinstance(output, dict):
            for key, value in output.items():
                # we set the value of the <key> for the "component" label in the labels dict
                labels_dict["component"] = key

                try:
                    # first we try to instantiate the metrics
                    prom_metric_obj = Gauge(prom_metric_name, metric_help, labels_list)
                except ValueError:
                    # if a metric with this name was already instantiated, we can find
                    # it in the global list defined above
                    for obj in prom_metrics_list:
                        if obj._name == prom_metric_name:
                            # try to set the metric value
                            try:
                                obj.labels(**labels_dict).set(output[key])
                            except ValueError:
                                # if we've come so far, it means the metric was already instantiated
                                # and we're trying to use different labels for the same metric name
                                logging.error("Invalid combination of metric{labels}:")
                                logging.error(
                                    "{0}{1}".format(prom_metric_name, labels_dict)
                                )
                else:
                    # in case the metric was instantiated for the first time, we save it in a global
                    # list and set it's value based on the script output
                    try:
                        prom_metric_obj.labels(**labels_dict).set(output[key])
                    except ValueError:
                        # ValueError here probably means the labels defined when the prometheus
                        # metric was instantiated don't match the ones passed when setting the metric value
                        logging.error("Labels mismatch:")
                        logging.error(
                            "{0} - {1}".format(labels_list, labels_dict.keys())
                        )
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
                        if obj._name == prom_metric_name:
                            # try to set the metric value
                            try:
                                obj.labels(**labels_dict).set(output)
                            except ValueError:
                                # if we've come so far, it means the metric was already instantiated
                                # and we're trying to use different labels for the same metric name
                                logging.error("Invalid combination of metric{labels}:")
                                logging.error(
                                    "{0}{1}".format(prom_metric_name, labels_dict)
                                )
                else:
                    # in case the metric was instantiated for the first time, we save it in a global
                    # list and set it's value based on the script output
                    prom_metrics_list.append(prom_metric_obj)
                    prom_metric_obj.labels(**labels_dict).set(output)


def parse_config_file(f):
    """
    load the config file in json format, parse it and return a list from the scripts section;
    it does format validation and it merges any existing global labels with the local ones,
    overriding the global with the local
    """

    # Load json file with list of scripts to schedule and run
    try:
        with open(f) as config:
            scripts_dict = json.load(config)
    except PermissionError:
        logging.error("No permission to read {0}/{1} file".format(cwd, f))
        return []
    # if file is not in valid JSON format, log this and exit
    except ValueError:
        logging.error(
            "Provided config file {0}/{1} is not a valid JSON file".format(cwd, f)
        )
        return []

    # start validating the config file structure
    try:
        scripts_list = scripts_dict["scripts"]
    except KeyError:
        logging.error(
            "Provided config file {0}/{1} does not have the proper structure".format(
                cwd, f
            )
        )
        return []
    if not isinstance(scripts_list, list):
        logging.error(
            "Provided config file {0}/{1} does not have the proper structure".format(
                cwd, f
            )
        )
        return []

    # check if the file has a global_labels section
    global_labels = scripts_dict.get("global_labels", {})

    # iterate over each itm in the scripts list and add the global labels to the local ones (where they exist)
    for script in scripts_list:
        local_labels = script.get("labels", {})
        labels = global_labels.copy()
        labels.update(local_labels)
        script["labels"] = labels

        # we add a new label named "component" but first we check that no label named like this was already defined
        # in the config file; in that case, we don't want to delete the original but rename the label name and
        # preserve it's value; we also write a WARNING log entry describing this situation
        if "component" in script["labels"].keys():
            script["labels"]["user_defined_component"] = script["labels"].pop(
                "component"
            )
            logging.warning(
                "Found <component> label defined in config file, automatically renamed to <user_defined_component>"
            )

    return scripts_dict["scripts"]


def main():

    global configs_list
    global job_queue

    # define list that will be the main object loaded in memory with all details
    # related to the scripts that will be run, interval, arguments, etc
    main_list = []

    for config_file in configs_list:
        main_list += parse_config_file(config_file)

    if main_list == []:
        logging.error(
            "No valid config files to parse, serving only standard python metrics"
        )

    # main part of program that will go through all scripts in the list and run the command for each
    for item in main_list:
        metric_name = item["metric"]
        metric_errors = "{0}_errors_total".format(metric_name)
        script_interval = int(item.get("interval", default_interval))
        # in the future, we intend to use the metric type for creating the proper prometheus metric
        # for now, we use the default of Gauge
        # metric_type = item.get("TYPE", default_metric_type)
        metric_help = item.get("HELP", default_metric_help)
        # save script with parameters in a string; it will be passed as argument to the command
        script = item["script"]
        command = script
        try:
            for param in item["params"]:
                command += " {0}".format(param)
        except KeyError:
            pass
        command = command.split()

        labels_dict = item.get("labels", {})
        # and add the value "main" to the corresponding labels dict key (we'll overwrite it later where necessary)
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
        # this list will hold 2 items, first one is the run_ext_script function, second one is
        # the dictionary defined above; we'll use this when we launch the threads for all items
        item_list = [run_ext_script, param_dict]

        # for each external script, add the list defined above in the queue at the predefined
        # interval; the main loop will continuosly get the scripts from the queue and run them
        logging.debug(
            "New item '{0}' scheduled to run every '{1}' seconds".format(
                item_list, script_interval
            )
        )
        schedule.every(script_interval).seconds.do(job_queue.put, item_list)

    # start the http server to expose the prometheus metrics
    logging.info("Starting web-server...")
    start_http_server(metrics_port, ip_addr)
    logging.info(
        "Server started and listening at {0}:{1}".format(ip_addr, metrics_port)
    )
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
            logging.debug("Running '{0}' in new thread".format(queue_item))
            worker_thread = threading.Thread(target=job_func)
            worker_thread.start()
        time.sleep(1)


if __name__ == "__main__":
    main()
