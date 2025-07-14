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
parser.add_argument("-e", "--end", help="End date in YYYY-MM-DD format (only used if start is provided)")
parser.add_argument("-d", "--debug", action="store_true", help="Enable debug mode to show additional information")
args = parser.parse_args()

# === CONFIGURATION ===
JIRA_USERNAME = os.getenv("JIRA_USERNAME")
JIRA_API_TOKEN = os.getenv("JIRA_API_TOKEN")
JIRA_SERVER = os.getenv("JIRA_SERVER")

# Epic field name can vary between Jira instances
# Try both common approaches - customfield for older/cloud instances and parent for newer instances
EPIC_LINK_FIELD = "customfield_10014"  # Common default for Jira Cloud
PARENT_FIELD = "parent"  # Used in newer Jira instances

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
end_date = None
date_range_display = None

if args.start:
    try:
        user_date = date_parser.parse(args.start)
        user_start_date = user_date.strftime("%Y-%m-%dT%H:%M:%S.000+0000")
        display_date = args.start
        
        # Check if end date is provided
        if args.end:
            try:
                end_user_date = date_parser.parse(args.end)
                end_date = end_user_date.strftime("%Y-%m-%dT%H:%M:%S.000+0000")
                date_range_display = f"from {args.start} to {args.end}"
                print(f"Using date range: {date_range_display}")
            except Exception as e:
                print(f"Error parsing end date: {e}")
                print(f"Using only start date: {args.start}")
                date_range_display = f"since {args.start}"
        else:
            date_range_display = f"since {args.start}"
            print(f"Using start date: {date_range_display}")
    except Exception as e:
        print(f"Error parsing provided start date: {e}")
        print("Using default date range instead (past 14 days)")
        user_start_date = None

# If no user date provided or there was an error, use the past 14 days
if not user_start_date:
    # Calculate the date 14 days ago
    fourteen_days_ago = datetime.utcnow() - timedelta(days=14)
    user_start_date = fourteen_days_ago.strftime("%Y-%m-%dT%H:%M:%S.000+0000")
    display_date = fourteen_days_ago.strftime("%Y-%m-%d")
    date_range_display = f"past 14 days (since {display_date})"
    print(f"Using default date range: {date_range_display}")

# === STEP 1: Find issues with worklogs since the specified date ===
since = user_start_date
jql = f"worklogAuthor = currentUser() AND worklogDate >= '{display_date}'"
if end_date:
    # Add a day to the end date to make it inclusive
    end_date_obj = date_parser.parse(args.end)
    end_date_plus_one = (end_date_obj + timedelta(days=1)).strftime("%Y-%m-%d")
    jql = f"worklogAuthor = currentUser() AND worklogDate >= '{display_date}' AND worklogDate < '{end_date_plus_one}'"

# Print JQL if debug mode is enabled
if args.debug:
    print(f"\n🔍 Debug: Using JQL query:\n{jql}")

search_url = f"{JIRA_SERVER}/rest/api/3/search"
params = {
    "jql": jql,
    "fields": f"summary,{EPIC_LINK_FIELD},{PARENT_FIELD}",
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
print(f"\n🧾 Worklogs {date_range_display}:\n{'='*40}")

# Collect all worklogs before printing
all_worklogs = []

for issue in issues:
    key = issue["key"]
    summary = issue["fields"]["summary"]
    epic_link = issue["fields"].get(EPIC_LINK_FIELD)
    
    # If no epic link found, try to get parent
    if not epic_link and PARENT_FIELD in issue["fields"] and issue["fields"][PARENT_FIELD]:
        parent = issue["fields"][PARENT_FIELD]
        if parent.get("fields", {}).get("issuetype", {}).get("name") == "Epic":
            # Parent is directly an epic
            epic_link = parent["key"]
        else:
            # Parent is not an epic, but check if it has an epic link (only one level)
            parent_key = parent["key"]
            parent_url = f"{JIRA_SERVER}/rest/api/3/issue/{parent_key}"
            parent_response = requests.get(parent_url, headers=headers, params={"fields": f"{EPIC_LINK_FIELD}"})
            if parent_response.status_code == 200:
                parent_data = parent_response.json()
                parent_epic_link = parent_data["fields"].get(EPIC_LINK_FIELD)
                if parent_epic_link:
                    epic_link = parent_epic_link
            
    worklog_url = f"{JIRA_SERVER}/rest/api/3/issue/{key}/worklog"
    worklogs = requests.get(worklog_url, headers=headers).json().get("worklogs", [])

    for log in worklogs:
        author = log["author"]["emailAddress"]
        started = log["started"]
        time_spent = log["timeSpent"]
        comment = log.get("comment", {}).get("content", [])

        if author == JIRA_USERNAME and started >= since:
            # Skip if end date is provided and the worklog is after the end of the specified day
            if end_date:
                end_day_plus_one = (end_user_date + timedelta(days=1)).strftime("%Y-%m-%dT00:00:00.000+0000")
                if started >= end_day_plus_one:
                    continue
                
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
                "epic_link": epic_link,
                "time_spent": time_spent,
                "comment_text": comment_text
            })

# Sort worklogs by date
sorted_worklogs = sorted(all_worklogs, key=lambda x: x["started"])

# Print sorted worklogs in chronological order
print(f"{'Date':<12}{'Issue':<15}{'Epic':<15}{'Summary':<30}{'Time':<10}Comment")
print(f"{'-'*12}{'-'*15}{'-'*15}{'-'*30}{'-'*10}{'-'*30}")
for log in sorted_worklogs:
    date = log["started_date"]
    epic = log.get("epic_link", "No Epic")
    print(f"{date:<12}{log['key']:<15}{epic if epic else 'No Epic':<15}{log['summary'][:28]:<30}{log['time_spent']:<10}{log['comment_text']}")

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

# === STEP 3: Group time by epic ===
print(f"\n🏆 Time by Epic:\n{'='*40}")

# Get all epics from the worklogs
epic_links = set(log.get("epic_link") for log in all_worklogs)

# Create a mapping of epic IDs to their details and aggregate time
epic_details = {}
epic_times = {}

# Initialize time for each epic
for epic_id in epic_links:
    epic_times[epic_id] = 0

# Sum up time per epic
for log in all_worklogs:
    epic_id = log.get("epic_link")
    minutes = parse_time_spent(log["time_spent"])
    epic_times[epic_id] += minutes

# Fetch epic names if there are any epic links
if any(epic_id for epic_id in epic_links if epic_id):
    for epic_id in epic_links:
        if not epic_id:  # Skip None values
            continue
            
        # Fetch epic details
        epic_url = f"{JIRA_SERVER}/rest/api/3/issue/{epic_id}"
        try:
            epic_response = requests.get(epic_url, headers=headers)
            if epic_response.status_code == 200:
                epic_data = epic_response.json()
                epic_details[epic_id] = {
                    "key": epic_id,
                    "summary": epic_data["fields"]["summary"]
                }
            else:
                epic_details[epic_id] = {
                    "key": epic_id,
                    "summary": "Unknown Epic"
                }
        except Exception as e:
            print(f"Error fetching epic details for {epic_id}: {e}")
            epic_details[epic_id] = {
                "key": epic_id,
                "summary": "Unknown Epic"
            }

# Print the time spent per epic (sorted by time spent, descending)
print(f"{'Epic Key':<15}{'Epic Name':<40}{'Time':<15}")
print(f"{'-'*15}{'-'*40}{'-'*15}")

# Sort epics by time spent (descending)
sorted_epics = sorted(epic_times.items(), key=lambda x: x[1], reverse=True)

# Print each epic's time
for epic_id, minutes in sorted_epics:
    # Handle issues with no epic
    if not epic_id:
        epic_key = "No Epic"
        epic_name = "Tasks without Epic"
    else:
        epic_key = epic_id
        epic_name = epic_details.get(epic_id, {}).get("summary", "Unknown Epic")
    
    # Format time
    hours = minutes // 60
    remaining_minutes = minutes % 60
    time_formatted = f"{hours}h"
    if remaining_minutes > 0:
        time_formatted += f" {remaining_minutes}m"
    
    print(f"{epic_key:<15}{epic_name[:38]:<40}{time_formatted:<15}")
