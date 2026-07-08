# Workflow

This repository documents two connected participant-facing workflow steps.

```text
Participant enrolled
        |
Reminder emails
        |
Study completion
        |
MRI souvenir generated
```

## Reminder emails

Appointments are maintained in a study Google Calendar. The reminder script checks configured future days, usually tomorrow and three days ahead. In the running workflow, the calendar description contains a participant/study ID. The script resolves that ID through local password-protected matching and screening spreadsheets, then sends the MRI appointment reminder from the study mailbox.

The script can be run manually or scheduled locally, for example with Windows Task Scheduler. Scheduler exports, machine-specific batch files, spreadsheet paths, and spreadsheet passwords are not tracked because they contain local usernames, paths, and operational details.

## MRI souvenir screenshots

After study completion, the screenshot script reads the participant's zipped DICOM export from the study storage location. It inspects DICOM headers without extracting the full archive, identifies the most likely T1 anatomical series, converts that series with `dcm2niix`, and writes a text-free PNG with sagittal, coronal, and axial views.

The generated image intentionally contains no participant ID or text labels. The filename and surrounding storage location still identify the participant operationally, so generated outputs are kept outside Git.
