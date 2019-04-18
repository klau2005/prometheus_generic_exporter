## [0.8.2] - 2019.04.18
### Changed

### Added

### Fixed
- removed unnecessary pass and added one second sleep when querying the queue for new jobs
- commented-out the metric_type (not used for now but will probably used in the future)

## [0.8.1] - 2019.03.25
### Changed

### Added

### Fixed
- fixed KeyError when trying to delete inexistent global_labels section from config file"

## [0.8.0] - 2019.03.22
### Changed
- if the program can't find any valid JSON config files, it will just log this and continue; previously it crashed
- simplify testing for the JSON config file
- exit codes are now compliant with recommendations
- metric TYPE and HELP sections can be omitted; they now have default values
- interval value can be omitted, it will be set to 600 seconds by default

### Added
- accept more than one config file

### Fixed
- if we have same label in global section and local one, the local one will override the global; previously it generated a conflict
- params section can be omitted (if the script takes no parameters); previously the config file needed a '"params": []' section

## [0.7.1] - 2019.03.01
### Changed
- upgraded requests module to version 2.20.0 - CVE-2018-18074

### Added
- added curl package

## [0.7] - 2018.09.28
### Changed
- in case of scripts returning JSON with status for multiple checks/components, we are now adding those as a new label
named <component> with the respective value; for scripts returning simple int/float, we're adding the same label
with a value of "main" (for consistency reasons); in the past, we were appending the component name to the base metric
name which was defined in the config file; result is that metric names defined in config will remain unchanged and can
now be refferenced in Grafana dashboards (or Prometheus queries) as-is (no need for regexp searches)
- existing lables defined in config file named <component> will now be renamed to user_defined_component but their defined
value will remain unchanged
- global_labels section in config file can now be omitted if not necessary
- scripts section in config file can be empty (useful for new deployments of the exporter when we don't yet have any
script to run and no labels to define (the starting config file can be as simple as ```{"scripts": []}```
- simpler type checking of the script/command returned output

### Added
- diplay the currently running version in the logs during startup

### Fixed
- sanity check for the config file format (be sure it's valid JSON)
- check for metrics labels mismatch (issue added with the addition of extra labels created during runtime)

## [0.6] - 2018.09.24
### Changed

### Added
- possibility to add multiple dimensions to prometheus metrics, called as cardinality (one metric name with multiple label values)

### Fixed

## [0.5] - 2018.08.24
### Changed
- simplified how we set listen port based on environment variable

### Added
- possibility to use different prometheus labels per each external script (until now we could only use global labels)
- logging functionality

### Fixed

## [0.4] - 2018.07.11
### Changed

### Added
- added requests module in requirements.txt file

### Fixed

## [0.3] - 2018.07.11
### Changed
- changed WORKDIR in Dockerfile to /prom_exporter
- changed port env name in main script (PROMETHEUS_PORT => METRICS_PORT)

### Added
- added exception cacthing for permission error when reading the main json file

