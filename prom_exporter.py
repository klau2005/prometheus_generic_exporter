'''Run external scripts/commands and export their output as prometheus metrics'''

try:
    import ast, os, sys, json, time
    import logging
    import schedule
    import threading
    import queue
    from subprocess import getstatusoutput as gt
    from prometheus_client import start_http_server, Counter, Gauge
except ImportError:
    print("could not load needed modules, exiting...")
    sys.exit(2)

__author__ = "Claudiu Tomescu"
__version__ = "0.7"
__date__ = "September 2018"
__maintainer__ = "Claudiu Tomescu"
__email__ = "klau2005@gmail.com"
__status__ = "Production"

### Variables ###
scripts_file = "configs/scripts.json"
cwd = os.getcwd()
job_queue = queue.Queue()
metrics_port = os.environ.get("METRICS_PORT", 8000)
log_levels = {"CRITICAL": 50, "ERROR": 40, "WARNING": 30, "INFO": 20, "DEBUG": 10, "NOTSET": 0}
log_level_name = os.environ.get("LOG_LEVEL", "INFO")
log_level = log_levels[log_level_name]
log_fmt = "[%(asctime)s] [%(levelname)s] %(message)s"

logging.basicConfig(level = log_level, datefmt = "%Y-%m-%d %H:%M:%S %z", format = log_fmt)
logging.info("Starting program version {0}".format(__version__))
logging.info("Using log level {0}".format(log_level_name))
# for the schedule module, we set the log level as WARNING as it is too noisy at INFO level
schedule.logger.setLevel(logging.WARNING)

# list to hold all instantiated prometheus metric objects
prom_metrics_list = []
# dictionary that will hold the global labels
global_labels_dict = {}
# and we save the keys in a list (we'll use it later when we create the metric objects)
global_labels_keys_list = []

### Functions ###
def run_ext_script(**kwargs):
    ''' run the external scripts, get their exit code and
    in case it is not 0, increase the error metric for that item; else it will
    convert the output as dictionary, instantiate one prometheus metric for each
    component the script tests and expose the metrics as prometheus metrics '''

    cmd = kwargs["cmd"]
    # run gt command for each component we need to test and capture status code and output
    logging.debug("Executing external script with args: '{0}'".format(cmd))
    result = gt(cmd)
    logging.debug("Got following result (exit code + output):")
    logging.debug(result)
    exit_code = result[0]
    output = result[1]
    item = kwargs["item"]
    prom_metric_name = item["metric"]
    prometheus_metric_errors = kwargs["prom_metric_err"]
    metric_type = item["TYPE"]
    metric_help = item["HELP"]
    local_labels_dict = kwargs["local_labels_dict"]
    local_labels_keys_list = kwargs["local_labels_keys_list"]

    # test if exit code is success
    if exit_code != 0:
        logging.warning("External command '{0}' returned error:".format(cmd))
        logging.warning("Result: '{0}'".format(result))
        prometheus_metric_errors.labels(**local_labels_dict).inc()
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
            prometheus_metric_errors.labels(**local_labels_dict).inc()
            return
        # first check if the output returned by script is json/dict
        if isinstance(output, dict):
            for key,value in output.items():
                # we set the value of the <key> for the "component" label in the labels dict
                local_labels_dict["component"] = key

                try:
                    # first we try to instantiate the metrics
                    prom_metric_obj = Gauge(prom_metric_name, metric_help, local_labels_keys_list)
                except ValueError:
                    # if a metric with this name was already instantiated, we can find
                    # it in the global list defined above
                    for obj in prom_metrics_list:
                        if obj._name == prom_metric_name:
                            # try to set the metric value
                            try:
                                obj.labels(**local_labels_dict).set(output[key])
                            except ValueError:
                                # if we've come so far, it means the metric was already instantiated
                                # and we're trying to use different labels for the same metric name
                                logging.error("Invalid combination of metric{labels}:")
                                logging.error("{0}{1}".format(prom_metric_name, local_labels_dict))
                else:
                    # in case the metric was instantiated for the first time, we save it in a global
                    # list and set it's value based on the script output
                    try:
                        prom_metric_obj.labels(**local_labels_dict).set(output[key])
                    except ValueError:
                        # ValueError here probably means the labels defined when the prometheus
                        # metric was instantiated don't match the ones passed when setting the metric value
                        logging.error("Labels mismatch:")
                        logging.error("{0} - {1}".format(local_labels_keys_list, local_labels_dict.keys()))
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
                    prom_metric_obj = Gauge(prom_metric_name, metric_help, local_labels_keys_list)
                except ValueError:
                    # if a metric with this name was already instantiated, we can find
                    # it in the global list defined above
                    for obj in prom_metrics_list:
                        if obj._name == prom_metric_name:
                            # try to set the metric value
                            try:
                                obj.labels(**local_labels_dict).set(output)
                            except ValueError:
                                # if we've come so far, it means the metric was already instantiated
                                # and we're trying to use different labels for the same metric name
                                logging.error("Invalid combination of metric{labels}:")
                                logging.error("{0}{1}".format(prom_metric_name, local_labels_dict))
                else:
                    # in case the metric was instantiated for the first time, we save it in a global
                    # list and set it's value based on the script output
                    prom_metrics_list.append(prom_metric_obj)
                    prom_metric_obj.labels(**local_labels_dict).set(output)

def main():
    # Load json file with list of scripts to schedule and run
    try:
        with open(scripts_file) as f:
            scripts_dict = f.read()
            # properly load the file as dictionary
            scripts_dict = ast.literal_eval(scripts_dict)
    except FileNotFoundError:
        logging.critical("{0} file could not be found in {1}/configs/ directory, exiting...".format(scripts_file, cwd))
        sys.exit(2)
    except PermissionError:
        logging.critical("No permission to read {0}/configs/{1} file, exiting...".format(cwd, scripts_file))
        sys.exit(3)

    global global_labels_dict
    global global_labels_keys_list
    global job_queue

    # check once more that the file we just read is a valid JSON file
    if not isinstance(scripts_dict, dict):
        logging.critical("Provided config file {0}/configs/{1} is not a valid JSON file, exiting...".format(cwd, scripts_file))
        sys.exit(4)

    # first we create a dictionary to hold the global labels
    try:
        global_labels_dict = scripts_dict["global_labels"]
    except KeyError:
        # if there is no such key, we set some empty dictionary/list objects
        global_labels_dict = {}
        global_labels_keys_list = []
    else:
        # and we save the keys in a list (we'll use it later when we create the metric objects)
        global_labels_keys_list = list(global_labels_dict.keys())

    # define list that will be the main object loaded in memory with all details
    # related to the scripts that will be run, interval, arguments, etc
    main_list = []

    # add the scripts to main list
    for script in scripts_dict["scripts"]:
        main_list.append(script)

    # main part of program that will go through all scripts in the list and run the gt command for each
    for item in main_list:
        metric_name = item["metric"]
        metric_errors = "{0}_errors_total".format(metric_name)
        script_interval = int(item["interval"])
        metric_type = item["TYPE"]
        metric_help = item["HELP"]
        # save script with parameters in a string; it will be passed as argument to gt command
        script = item["script"]
        command = script
        for param in item["params"]:
            command += " {0}".format(param)

        # we define a separate dictionary for each script as we'll add to it some item
        # specific labels; we don't want to modify the global one
        local_labels_dict = global_labels_dict.copy()
        # we do the same as above for the list
        local_labels_keys_list = global_labels_keys_list.copy()

        # if we have local labels defined, we are adding them here
        try:
            local_labels = item["labels"]
        except KeyError:
            local_labels = {}
        local_labels_keys_list = local_labels_keys_list + list(local_labels.keys())
        for label in local_labels.keys():
            local_labels_dict[label] = local_labels[label]

        # we add a new label named "component" but first we check that no label named like this was already defined
        # in the config file; in that case, we don't want to delete the original but rename the label name and
        # preserve it's value; we also write a WARNING log entry describing this situation
        if "component" in local_labels_dict.keys():
            local_labels_dict["user_defined_component"] = local_labels_dict.pop("component")
            logging.warning("Found <component> label defined in config file, automatically renamed <user_defined_component>")
        for pos, val in enumerate(local_labels_keys_list):
            if val == "component":
                local_labels_keys_list[pos] = "user_defined_component"

        local_labels_keys_list.append("component")
        # and add the value "main" to the corresponding labels dict key (we'll overwrite it later where necessary)
        local_labels_dict["component"] = "main"

        # instantiate the prometheus counter metrics for the script errors item
        try:
            prometheus_metric_errors = Counter(metric_errors, metric_help, local_labels_keys_list)
        # if it was already instantiated, just pass
        except ValueError:
            pass

        # save the command, item and the error metric in a dictionary
        param_dict = {"cmd": command, "item": item, "prom_metric_err": prometheus_metric_errors,
        "local_labels_keys_list": local_labels_keys_list, "local_labels_dict": local_labels_dict}
        # this list will hold 2 items, first one is the run_ext_script function, second one is
        # the dictionary defined above; we'll use this when we launch the threads for all items
        item_list = [run_ext_script, param_dict]

        # for each external script, add the list defined above in the queue at the predefined
        # interval; the main loop will continuosly get the scripts from the queue and run them
        logging.debug("New item '{0}' scheduled to run every '{1}' seconds".format(item_list, script_interval))
        schedule.every(script_interval).seconds.do(job_queue.put, item_list)

    # start the http server to expose the prometheus metrics
    logging.info("Starting web-server...")
    start_http_server(metrics_port, "0.0.0.0")
    logging.info("Server started and listening at 0.0.0.0:{0}".format(metrics_port))
    # enter the main scheduler loop
    while True:
        # start the scheduling
        schedule.run_pending()
        try:
            # see if we have anything in the queue
            queue_item = job_queue.get(block=False)
        except queue.Empty:
            logging.debug("There are no items in the queue right now...")
            # if queue is empty for now, just pass
            pass
        else:
            job_queue.task_done()
            # if queue has items, get them one by one and run them (we have functions and
            # corresponding dictionary as kwargs for the function in it)
            item_func = queue_item[0]
            item_kwargs = queue_item[1]
            def job_func():
                ''' run the run_ext_script function with params for each item '''
                item_func(**item_kwargs)
            # start a new thread for each function; this will let us run the functions in parallel
            logging.debug("Running '{0}' in new thread".format(queue_item))
            worker_thread = threading.Thread(target=job_func)
            worker_thread.start()
        time.sleep(1)

if __name__ == "__main__":
    main()
