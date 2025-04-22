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
# We'll query for the active sprint instead of previous sprint

# === STEP 1: Find issues with worklogs from active sprint ===
# First get all boards
boards_url = f"{JIRA_SERVER}/rest/agile/1.0/board"
boards_response = requests.get(boards_url, headers=headers)

boards = boards_response.json().get("values", [])

# Track all issues from all boards
all_issues = []
active_sprint_data = None
fallback_date = (datetime.utcnow() - timedelta(days=14)).isoformat(timespec="seconds") + ".000+0000"

# Check all boards for sprints and issues
if boards:
    for board in boards:
        board_id = board["id"]
        print(f"Checking board: {board['name']} (ID: {board_id})")
        
        # Use the get_all_sprints function imported from sprints.py to get all sprints
        all_board_sprints = get_all_sprints(board_id)
        
        # Extract active sprints
        active_sprints = [s for s in all_board_sprints if s.get("state_display") == "ACTIVE"]
        
        # Process active sprints for this board
        if active_sprints:
            print(f"  Found {len(active_sprints)} active sprint(s) for this board")
            
            # Process each active sprint
            for current_sprint in active_sprints:
                sprint_id = current_sprint["id"]
                sprint_name = current_sprint["name"]
                sprint_start = current_sprint["startDate"]
                sprint_end = current_sprint["endDate"]
                
                print(f"  Processing active sprint: {sprint_name} (ID: {sprint_id})")
                
                # Convert to datetime objects for comparison with worklog dates
                sprint_start_dt = datetime.fromisoformat(sprint_start.replace('Z', '+00:00'))
                sprint_end_dt = datetime.fromisoformat(sprint_end.replace('Z', '+00:00'))
                
                # Format for JQL query
                since = sprint_start_dt.isoformat(timespec="seconds") + ".000+0000"
                
                # Save the active sprint data
                # If multiple active sprints exist across boards, use the one with the earliest start date
                if active_sprint_data is None or sprint_start_dt < datetime.fromisoformat(active_sprint_data["start"].replace('Z', '+00:00')):
                    active_sprint_data = {
                        "since": since,
                        "sprint_id": sprint_id,
                        "sprint_name": sprint_name,
                        "start": sprint_start,
                        "end": sprint_end
                    }
                
                # Search for issues directly in this sprint
                jql = f"worklogAuthor = currentUser() AND sprint = {sprint_id}"
                search_url = f"{JIRA_SERVER}/rest/api/3/search"
                params = {
                    "jql": jql,
                    "fields": "summary",
                    "maxResults": 100  # Increased to catch more issues
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
                
                total_found = len(board_issues) + len(epic_issues)
                print(f"  Found {total_found} issues with worklogs in sprint {sprint_name} ({len(board_issues)} direct, {len(epic_issues)} from epics)")
        else:
            print(f"  No active sprints found for this board")
else:
    print("No boards found, falling back to last 14 days")

# If no issues found across all boards, use fallback date range
if not all_issues:
    print("No issues found in any active sprints, falling back to last 14 days")
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

# Use the active sprint's start date for worklog filtering if available
since = active_sprint_data["since"] if active_sprint_data else fallback_date

# Remove duplicates (an issue might be in multiple sprints)
unique_issues = {issue["key"]: issue for issue in all_issues}.values()
issues = list(unique_issues)

print(f"Found a total of {len(issues)} unique issues with worklogs")

# === STEP 2: Fetch worklogs per issue ===
if active_sprint_data:
    print(f"\n🧾 Worklogs from the current active sprint ({active_sprint_data['sprint_name']}):\n{'='*40}")
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
