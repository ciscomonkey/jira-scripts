import requests
from datetime import datetime, timedelta
import base64
import os
from dotenv import load_dotenv
import argparse
from dateutil import parser as date_parser

load_dotenv()

# === COMMAND LINE ARGUMENTS ===
parser = argparse.ArgumentParser(description="Fetch Jira worklogs since a specified date (defaults to past 14 days)")
parser.add_argument("-s", "--start", help="Start date in YYYY-MM-DD format (defaults to 14 days ago)")
args = parser.parse_args()

# === CONFIGURATION ===
JIRA_USERNAME = os.getenv("JIRA_USERNAME")
JIRA_API_TOKEN = os.getenv("JIRA_API_TOKEN")
JIRA_SERVER = os.getenv("JIRA_SERVER")

# === AUTH HEADERS ===
auth_str = f"{JIRA_USERNAME}:{JIRA_API_TOKEN}"
auth_bytes = auth_str.encode('utf-8')
auth_b64 = base64.b64encode(auth_bytes).decode('utf-8')

headers = {
    "Authorization": f"Basic {auth_b64}",
    "Content-Type": "application/json"
}

def parse_time_spent(time_str):
    """Parse Jira time spent strings like '2d 4h 30m' into minutes"""
    minutes = 0
    
    # Parse time strings like "2h 30m", "45m", "1h", etc.
    if 'd' in time_str:
        # Handle days part
        days_parts = time_str.split('d')
        days_part = days_parts[0].strip()
        if days_part.isdigit():
            minutes += int(days_part) * 8 * 60  # 1 day = 8 hours
        
        # Check if there's hours or minutes after days
        remaining = days_parts[1].strip() if len(days_parts) > 1 else ""
        if remaining and 'h' in remaining:
            time_str = remaining  # Continue parsing the remaining part
        else:
            time_str = ""  # No more time components
            
    if 'h' in time_str:
        # Handle hours part
        hours_parts = time_str.split('h')
        hours_part = hours_parts[0].strip()
        if hours_part.isdigit():
            minutes += int(hours_part) * 60
        
        # Check if there's minutes after hours
        remaining = hours_parts[1].strip() if len(hours_parts) > 1 else ""
        if remaining and 'm' in remaining:
            time_str = remaining  # Continue parsing the remaining part
        else:
            time_str = ""  # No more time components
            
    if 'm' in time_str:
        # Handle minutes part
        minutes_part = time_str.split('m')[0].strip()
        if minutes_part.isdigit():
            minutes += int(minutes_part)
    
    return minutes

# === DATE RANGE SETUP ===
# Check if a start date was provided via command line, otherwise use 14 days ago
user_start_date = None
display_date = None

if args.start:
    try:
        user_date = date_parser.parse(args.start)
        user_start_date = user_date.strftime("%Y-%m-%dT%H:%M:%S.000+0000")
        display_date = args.start
        print(f"Using user-provided start date: {args.start}")
    except Exception as e:
        print(f"Error parsing provided date: {e}")
        print("Using default date range instead (past 14 days)")
        user_start_date = None

# If no user date provided or there was an error, use the past 14 days
if not user_start_date:
    # Calculate the date 14 days ago
    fourteen_days_ago = datetime.utcnow() - timedelta(days=14)
    user_start_date = fourteen_days_ago.strftime("%Y-%m-%dT%H:%M:%S.000+0000")
    display_date = fourteen_days_ago.strftime("%Y-%m-%d")
    print(f"Using default date range: past 14 days (since {display_date})")

# === STEP 1: Find issues with worklogs since the specified date ===
since = user_start_date
jql = f"worklogAuthor = currentUser() AND worklogDate >= '{display_date}'"
search_url = f"{JIRA_SERVER}/rest/api/3/search"
params = {
    "jql": jql,
    "fields": "summary",
    "maxResults": 100
}

response = requests.get(search_url, headers=headers, params=params)
all_issues = response.json().get("issues", [])
print(f"Found {len(all_issues)} issues with worklogs since {display_date}")

# Remove duplicates (an issue might be in multiple sprints)
unique_issues = {issue["key"]: issue for issue in all_issues}.values()
issues = list(unique_issues)

print(f"Found a total of {len(issues)} unique issues with worklogs")

# === STEP 2: Fetch worklogs per issue ===
print(f"\n🧾 Worklogs since {display_date}:\n{'='*40}")

# Collect all worklogs before printing
all_worklogs = []

for issue in issues:
    key = issue["key"]
    summary = issue["fields"]["summary"]
    worklog_url = f"{JIRA_SERVER}/rest/api/3/issue/{key}/worklog"
    worklogs = requests.get(worklog_url, headers=headers).json().get("worklogs", [])

    for log in worklogs:
        author = log["author"]["emailAddress"]
        started = log["started"]
        time_spent = log["timeSpent"]
        comment = log.get("comment", {}).get("content", [])

        if author == JIRA_USERNAME and started >= since:
            comment_text = ""
            if comment and isinstance(comment, list):
                comment_text = " ".join([
                    chunk["text"]
                    for block in comment
                    for chunk in block.get("content", [])
                    if chunk["type"] == "text"
                ])

            started_date = started.split("T")[0]
            all_worklogs.append({
                "started": started,
                "started_date": started_date,
                "key": key,
                "summary": summary,
                "time_spent": time_spent,
                "comment_text": comment_text
            })

# Sort worklogs by date
sorted_worklogs = sorted(all_worklogs, key=lambda x: x["started"])

# Print sorted worklogs in chronological order
print(f"{'Date':<12}{'Issue':<15}{'Summary':<40}{'Time':<10}Comment")
print(f"{'-'*12}{'-'*15}{'-'*40}{'-'*10}{'-'*30}")
for log in sorted_worklogs:
    date = log["started_date"]
    print(f"{date:<12}{log['key']:<15}{log['summary'][:38]:<40}{log['time_spent']:<10}{log['comment_text']}")

# Calculate total time spent
total_minutes = sum(parse_time_spent(log['time_spent']) for log in all_worklogs)

# Convert total minutes to hours and minutes format (no days)
hours = total_minutes // 60
minutes = total_minutes % 60

# Format the total time spent in hours and minutes only
total_time_formatted = f"{hours}h"
if minutes > 0:
    total_time_formatted += f" {minutes}m"

# Print summary
print(f"\n{'='*40}")
print(f"Total time logged: {total_time_formatted} ({total_minutes} minutes)")
print(f"Number of work log entries: {len(all_worklogs)}")
