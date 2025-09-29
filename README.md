[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

Custom collector written in Python 3 that can run any external script/command and export the output as prometheus metrics. The scripts are run at the desired interval by the scheduler, like a cron job.

For this to run, it needs one or more `*.json` files (in the configs folder) with the following format:

```
{
  "global_labels": {
    "dc": "DC01",
    "room": "Room1",
    "stage": "Production"
  },
  "scripts": [
    {"script": "python3 scripts/app1_check.py", "interval": "60", "metric": "app1_status",
    "params": ["prd-001-app1", "svc", 8084], "HELP": "Check Application1 Status", "TYPE": "gauge",
    "labels": {"project": "001 - Project 1"}},
    {"script": "bash scripts/app2_check.sh", "interval": "30", "metric": "app2_status",
    "params": ["prd-002-app2", "svc", 8085], "HELP": "Check Application2 Status", "TYPE": "gauge",
    "labels": {"project": "002 - Project 2"}}
  ]
}
```

In this file, we define each external script/command that needs to be run as an item with a couple of parameters: the script name (prepended by the executable, bash, python, etc), the interval at which it will be run by the scheduler (in seconds), the desired prometheus metric name, the parameters that need to be passed to the script (if any) and finally the prometheus specific details, HELP and metric TYPE.
`interval`, `TYPE`, `HELP` can be omited, they have default values (`interval` - 600 seconds, `TYPE` - gauge and a generic `HELP` message. Also, the `params` section can be omitted altogether if the script takes no parameters.

If we have the same label both in the main `global_labels` section and in a `script` section, the global one will be overwritten.

The scripts can either be run as-is, the collector captures their output and if integer or float it will just expose the metric with the desired labels added (global ones are applied for all the scripts in the file). iIn this case, one more label named `component` with value `main` will be added by default. For better usability the scripts to be run can be modified to output JSON data instead of a simple value. This is useful in case the script can return more than one value in a single run (for ex. one end-point that returns the status for multiple components in one shot). Example JSON output below:

`{'health': 200, 'DB': 1, 'Cassandra': 0, 'HSM': 1}`

In this case, 4 new timeseries will be created with the desired metric name but with the label `component` holding the value of the component. Example:
`test_status{component="health",...}` (there will be more labels added, defined in the global_labels section and in each script section).
Both `global_labels` and `labels` sections can be omitted if not needed. In fact, the module can start with a config file as simple as `{"scripts": []}` (in this case, no script/command will run).

For a quick start, there is an example config file (in the configs folder) and a sample script (in the scripts folder) that will generate your first metrics. Use them as a guideline and add your own.
