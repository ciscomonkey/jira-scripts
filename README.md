# Jira Scripts

Just some quick and dirty Jira scripts to scrape work for current and previous sprints. Use at your own peril.

* ```worksince.py``` - Gets worklogs for previous 14 days.  ```-h``` for options

## Running

```shell
$ uv sync
$ uv run ./worksince.py -h
```

Don't use these - these are just here for legacy reference:

* ```work.py``` - Generates current worklogs from active sprints.
* ```worklog.py``` - Generates worklogs from the previous sprints.
