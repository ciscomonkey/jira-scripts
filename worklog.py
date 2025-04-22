import requests
from datetime import datetime, timedelta
import base64
import os
from dotenv import load_dotenv

load_dotenv()

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

def get_all_sprints(board_id):
    """Get all sprints for a given board, both active and closed"""
    all_sprints = []
    
    # Get active sprints with pagination
    startAt = 0
    isLast = False
    while not isLast:
        active_url = f"{JIRA_SERVER}/rest/agile/1.0/board/{board_id}/sprint?state=active&startAt={startAt}"
        active_response = requests.get(active_url, headers=headers)
        active_data = active_response.json()
        active_sprints = active_data.get("values", [])
        
        for sprint in active_sprints:
            sprint["state_display"] = "ACTIVE"
            all_sprints.append(sprint)
        
        isLast = active_data.get("isLast", True)
        startAt += len(active_sprints)
    
    # Get closed sprints with pagination
    startAt = 0
    isLast = False
    while not isLast:
        closed_url = f"{JIRA_SERVER}/rest/agile/1.0/board/{board_id}/sprint?state=closed&startAt={startAt}"
        closed_response = requests.get(closed_url, headers=headers)
        closed_data = closed_response.json()
        closed_sprints = closed_data.get("values", [])
        
        for sprint in closed_sprints:
            sprint["state_display"] = "CLOSED"
            all_sprints.append(sprint)
        
        isLast = closed_data.get("isLast", True)
        startAt += len(closed_sprints)
    
    # Get future sprints with pagination
    startAt = 0
    isLast = False
    while not isLast:
        future_url = f"{JIRA_SERVER}/rest/agile/1.0/board/{board_id}/sprint?state=future&startAt={startAt}"
        future_response = requests.get(future_url, headers=headers)
        future_data = future_response.json()
        future_sprints = future_data.get("values", [])
        
        for sprint in future_sprints:
            sprint["state_display"] = "FUTURE"
            all_sprints.append(sprint)
        
        isLast = future_data.get("isLast", True)
        startAt += len(future_sprints)
    
    return all_sprints

# === DATE RANGE SETUP ===
# Instead of using a fixed 7-day window, we'll query for the previous sprint

# === STEP 1: Find issues with worklogs from previous sprint ===
# First get all boards
boards_url = f"{JIRA_SERVER}/rest/agile/1.0/board"
boards_response = requests.get(boards_url, headers=headers)

boards = boards_response.json().get("values", [])

# Track all issues from all boards
all_issues = []
recent_sprint_data = None
fallback_date = (datetime.utcnow() - timedelta(days=14)).isoformat(timespec="seconds") + ".000+0000"

# Check all boards for sprints and issues
if boards:
    for board in boards:
        board_id = board["id"]
        print(f"Checking board: {board['name']} (ID: {board_id})")
        
        # Use the get_all_sprints function imported from sprints.py to get all sprints
        all_board_sprints = get_all_sprints(board_id)
        
        # Extract closed sprints
        closed_sprints = [s for s in all_board_sprints if s.get("state_display") == "CLOSED"]
        
        # Instead of just getting the most recent sprint, identify all recently closed sprints
        # Sort closed sprints by end date (newest first)
        sorted_closed_sprints = sorted(closed_sprints, key=lambda x: x["endDate"], reverse=True)
        
        if sorted_closed_sprints:
            # Get the most recent sprint's end date as reference
            most_recent_sprint = sorted_closed_sprints[0]
            most_recent_end_dt = datetime.fromisoformat(most_recent_sprint["endDate"].replace('Z', '+00:00'))
            
            # Consider sprints that ended within 7 days of the most recent one
            recent_sprints = []
            for sprint in sorted_closed_sprints:
                sprint_end_dt = datetime.fromisoformat(sprint["endDate"].replace('Z', '+00:00'))
                # Include sprints that ended within 7 days of the most recent one
                if (most_recent_end_dt - sprint_end_dt).days <= 7:
                    recent_sprints.append(sprint)
            
            print(f"  Found {len(recent_sprints)} recently closed sprints on this board")
            
            # Extract active sprints for troubleshooting
            active_sprints = [s for s in all_board_sprints if s.get("state_display") == "ACTIVE"]
            active_sprint_info = "None found" 
            if active_sprints:
                active_sprint = active_sprints[0]  # Usually there's only one active sprint
                active_sprint_info = f"{active_sprint['name']} (ID: {active_sprint['id']})"
            
            print(f"  Current active sprint: {active_sprint_info}")
            
            # Process all recent sprints
            for sprint in recent_sprints:
                sprint_id = sprint["id"]
                sprint_name = sprint["name"]
                sprint_start = sprint["startDate"]
                sprint_end = sprint["endDate"]
                
                print(f"  Processing sprint: {sprint_name} (ID: {sprint_id})")
                
                # Convert to datetime objects for comparison with worklog dates
                sprint_start_dt = datetime.fromisoformat(sprint_start.replace('Z', '+00:00'))
                sprint_end_dt = datetime.fromisoformat(sprint_end.replace('Z', '+00:00'))
                
                # Format for JQL query
                since = sprint_start_dt.isoformat(timespec="seconds") + ".000+0000"
                
                # Update the most recent sprint data overall
                if recent_sprint_data is None or sprint_end_dt > datetime.fromisoformat(recent_sprint_data["end"].replace('Z', '+00:00')):
                    recent_sprint_data = {
                        "since": since,
                        "sprint_id": sprint_id,
                        "sprint_name": sprint_name,
                        "end": sprint_end
                    }
                
                # Search for issues directly in this sprint
                jql = f"worklogAuthor = currentUser() AND sprint = {sprint_id}"
                search_url = f"{JIRA_SERVER}/rest/api/3/search"
                params = {
                    "jql": jql,
                    "fields": "summary",
                    "maxResults": 100
                }
                
                response = requests.get(search_url, headers=headers, params=params)
                board_issues = response.json().get("issues", [])
                all_issues.extend(board_issues)
                
                # Now search for issues belonging to epics in this sprint
                epic_jql = f"worklogAuthor = currentUser() AND issueFunction in epicsOf('sprint = {sprint_id}')"
                epic_params = {
                    "jql": epic_jql,
                    "fields": "summary",
                    "maxResults": 100
                }
                
                epic_response = requests.get(search_url, headers=headers, params=epic_params)
                epic_issues = epic_response.json().get("issues", [])
                all_issues.extend(epic_issues)
                
                found_count = len(board_issues) + len(epic_issues)
                print(f"    Found {found_count} issues with worklogs ({len(board_issues)} direct, {len(epic_issues)} from epics)")
        else:
            print(f"  No closed sprints found for this board")
else:
    print("No boards found, falling back to last 14 days")

# If no issues found across all boards, use fallback date range
if not all_issues:
    print("No issues found in any sprints, falling back to last 14 days")
    since = fallback_date
    jql = f"worklogAuthor = currentUser() AND worklogDate >= -14d"
    search_url = f"{JIRA_SERVER}/rest/api/3/search"
    params = {
        "jql": jql,
        "fields": "summary",
        "maxResults": 50
    }
    response = requests.get(search_url, headers=headers, params=params)
    all_issues = response.json().get("issues", [])

# Use the most recent sprint's start date for worklog filtering if available
since = recent_sprint_data["since"] if recent_sprint_data else fallback_date

# Remove duplicates (an issue might be in multiple sprints)
unique_issues = {issue["key"]: issue for issue in all_issues}.values()
issues = list(unique_issues)

print(f"Found a total of {len(issues)} unique issues with worklogs")

# === STEP 2: Fetch worklogs per issue ===
if recent_sprint_data:
    print(f"\n🧾 Worklogs from the most recent sprint:\n{'='*40}")
else:
    print(f"\n🧾 Worklogs from the past 14 days (fallback):\n{'='*40}")

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

# Sort worklogs by key, then by date
sorted_worklogs = sorted(all_worklogs, key=lambda x: (x["key"], x["started"]))

# Print sorted worklogs
for log in sorted_worklogs:
    print(f"{log['started_date']}\t{log['key']}\t{log['summary']}\t{log['time_spent']}\t{log['comment_text']}")

# Calculate total time spent
total_minutes = 0
for log in all_worklogs:
    time_str = log['time_spent']
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
    
    total_minutes += minutes
    #print(f"Parsed '{log['time_spent']}' as {minutes} minutes, running total: {total_minutes}")  # Debug output

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
