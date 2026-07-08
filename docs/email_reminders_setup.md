# Email Reminder Setup

The reminder script sends appointment emails based on upcoming Google Calendar events. It is designed for a study calendar where events are checked a fixed number of days ahead, for example tomorrow and three days from now.

In the current workflow, the calendar event description contains a participant/study ID. The script uses that ID to look up the contact email in local protected spreadsheets. For simpler test calendars, it can also extract an email address directly from the event description with `--recipient-source description-email`.

## 1. Create Google Calendar API Credentials

Create a Google Cloud project and enable the Google Calendar API:

1. Open the Google Cloud Console.
2. Create a new project.
3. Enable the Google Calendar API.
4. Create OAuth 2.0 credentials.
5. Choose `Desktop app` as the application type.
6. Download the OAuth client file and save it locally as `config/credentials.json`.

During testing, add the Google account that runs the script as a test user:

1. Open `APIs & Services`.
2. Go to the OAuth consent screen.
3. Add the relevant account under test users.
4. Save the changes.

The first successful manual run creates `config/token.json`. Both local files are ignored by Git.

## 2. Configure Local Settings

Install dependencies:

```powershell
python -m pip install -r requirements.txt
```

Set the local environment variables before running the script:

```powershell
$env:STUDY_CALENDAR_ID="your-calendar-id@group.calendar.google.com"
$env:STUDY_SMTP_SERVER="smtp.example.org"
$env:STUDY_SMTP_PORT="587"
$env:STUDY_SMTP_USER="your-login@example.org"
$env:STUDY_SMTP_PASSWORD="local-password-or-app-password"
$env:STUDY_FROM_EMAIL="study-team@example.org"
$env:STUDY_MATCHING_LIST="H:\private\matching-list.xlsx"
$env:STUDY_MATCHING_PASSWORD="local-file-password"
$env:STUDY_SCREENING_LIST="H:\private\screening-list.xlsm"
$env:STUDY_SCREENING_PASSWORD="local-file-password"
$env:STUDY_REAUTH_NOTIFY_EMAIL="maintainer@example.org"
```

Run a dry check first:

```powershell
python .\email_reminders\send_reminders.py --days 1 3 --dry-run
```

For a calendar where the event description already contains the participant email:

```powershell
python .\email_reminders\send_reminders.py --days 1 3 --recipient-source description-email --dry-run
```

## 3. Run the Reminder Script

After checking the output with `--dry-run`, run:

```powershell
python .\email_reminders\send_reminders.py --days 1 3
```

If the Google token expires or is revoked, refresh it manually:

```powershell
$env:RUN_MANUALLY="true"
python .\email_reminders\send_reminders.py --days 1 --dry-run
```

The browser login flow will refresh the local token cache.

## 4. Schedule on Windows

The script can be scheduled with Windows Task Scheduler. The exact batch file is intentionally not tracked because it usually contains local usernames, Python paths, and private environment variables.

Typical setup:

1. Open Task Scheduler.
2. Create a new basic task.
3. Choose a daily trigger.
4. Select `Start a program`.
5. Point the action to a local batch or PowerShell wrapper that sets the required environment variables and runs `email_reminders\send_reminders.py`.
6. Save and test the task manually before relying on the schedule.

Keep scheduler exports and local wrapper scripts outside Git unless they are fully sanitized.
