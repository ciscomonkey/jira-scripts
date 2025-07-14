# Jira Scripts

Just some quick and dirty Jira scripts to scrape work for current and previous sprints. Use at your own peril.

```worksince.py``` - Should probably just use this one.  ```-h``` for options.

```work.py``` - Generates current worklogs from active sprints.

```worklog.py``` - Generates worklogs from the previous sprints.

## Running

```shell
$ uv sync
$ uv run ./work.py
$ uv run ./worklog.py
```