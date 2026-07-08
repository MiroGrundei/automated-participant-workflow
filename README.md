# Automated Participant Workflow

Automation tools developed for participant-facing MRI/neuroscience study workflows. Originally designed for the [MeMoSLAP study](https://memoslap.de/en/home).

```text
Participant enrolled
        |
Reminder emails
        |
Study completion
        |
MRI souvenir generated
```

This repository currently supports two practical workflow steps:

- scheduled reminder emails from Google Calendar events
- individualized structural MRI screenshot generation after study completion

The code is intentionally small and operational. It documents the workflow without committing credentials, participant data, DICOM files, NIfTI files, or generated private outputs.

## Repository layout

```text
automated-participant-workflow/
|-- email_reminders/
|   |-- templates/
|   `-- send_reminders.py
|-- mri_screenshot_generator/
|   `-- generate_screenshots.py
|-- config/
|   `-- example_config.yaml
|-- docs/
|   |-- email_reminders_setup.md
|   |-- workflow.md
|   `-- privacy_and_security.md
|-- README.md
|-- .gitignore
`-- requirements.txt
```

## Setup

Install the Python dependencies:

```powershell
python -m pip install -r requirements.txt
```

Use `config/example_config.yaml` as a reference for local settings. Google OAuth files live locally at:

```text
config/credentials.json
config/token.json
```

Both files are ignored by Git.

## Reminder emails

The reminder script reads events from a Google Calendar. In the running workflow, the calendar description contains a participant/study ID rather than an email address. The script resolves that ID through local password-protected study spreadsheets, then sends the German MRI appointment reminder template.

```powershell
$env:STUDY_CALENDAR_ID="your-calendar-id@group.calendar.google.com"
$env:STUDY_SMTP_SERVER="smtp.example.org"
$env:STUDY_SMTP_USER="your-login@example.org"
$env:STUDY_SMTP_PASSWORD="local-password-or-app-password"
$env:STUDY_FROM_EMAIL="study-team@example.org"
$env:STUDY_MATCHING_LIST="H:\private\matching-list.xlsx"
$env:STUDY_MATCHING_PASSWORD="local-file-password"
$env:STUDY_SCREENING_LIST="H:\private\screening-list.xlsm"
$env:STUDY_SCREENING_PASSWORD="local-file-password"
$env:STUDY_REAUTH_NOTIFY_EMAIL="maintainer@example.org"

python .\email_reminders\send_reminders.py --days 1 3
```

Use `--dry-run` while checking calendar parsing and recipient lookup. For older/test events that contain an email directly in the calendar description, use `--recipient-source description-email`. If token refresh fails during scheduled execution, rerun manually with `RUN_MANUALLY=true` to refresh the local token.

Detailed setup notes are in `docs/email_reminders_setup.md`.

## MRI screenshots

The MRI snapshot generator inspects zipped DICOM exports, selects the most likely T1 anatomical series, converts it with `dcm2niix`, and saves a text-free sagittal/coronal/axial PNG.

```powershell
python .\mri_screenshot_generator\generate_screenshots.py `
  --subjects 2275 2276 `
  --work-dir H:\study\t1_snapshot_work `
  --snapshot-dir H:\study\t1_snapshots `
  --log H:\study\t1_snapshots\t1_snapshot_log.csv
```

Local working files and generated screenshots are ignored by Git because they may derive from participant scans.

## Security Note

Credential files, tokens, private spreadsheet paths, participant data, and generated MRI outputs are not tracked. See `docs/privacy_and_security.md` for the project hygiene notes.
