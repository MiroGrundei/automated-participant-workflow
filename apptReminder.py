import os
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from google.auth.transport.requests import Request
from datetime import datetime, timedelta, timezone
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import time


# Scopes for the API
SCOPES = ['https://www.googleapis.com/auth/calendar.readonly']

# Specify the calendarID of the specific calendar (MeMoSLAP - P2)
calendar_id = 'calendarID@group.calendar.google.com'

def get_credentials():

    # Path to the credentials file (create from Google Cloud Console)
    creds_path = os.path.join(os.path.dirname(__file__), 'credentials.json')

    creds = None

    token_path = os.path.join(os.path.dirname(__file__), 'token.json')
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)

    # If credentials exist and are expired, refresh them
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())

    # If no valid credentials exist, start a new authentication flow
    if not creds or not creds.valid:
        flow = InstalledAppFlow.from_client_secrets_file(creds_path, SCOPES)
        creds = flow.run_local_server(port=0, access_type='offline', prompt='consent')

    # Save the new token (refreshed or newly created)
    with open(token_path, 'w') as token:
        token.write(creds.to_json())

    return creds


def get_events_for_specific_day(days_from_today):
    # Function to get events for a specific day
    # days_from_today: int, number of days from today (0 = today, 1 = tomorrow, -1 = yesterday)

    # Calculate the specific day
    specific_day = datetime.utcnow() + timedelta(days=days_from_today)

    # Start of the day at 00:01
    time_min = specific_day.replace(hour=0, minute=1, second=0, microsecond=0).isoformat() + 'Z'

    # End of the day at 23:59
    time_max = specific_day.replace(hour=23, minute=59, second=59, microsecond=999999).isoformat() + 'Z'

    # Fetch events
    events_result = service.events().list(
        calendarId=calendar_id,
        timeMin=time_min,
        timeMax=time_max,
        singleEvents=True,
        orderBy='startTime'
    ).execute()
    events = events_result.get('items', [])

    return events


def extract_email_from_text(text):
    import re
    email_regex = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
    match = re.search(email_regex, text)
    return match.group(0) if match else None


def send_email(recipient, subject, body):

    # SMTP-Einstellungen
    smtp_server = ""
    smtp_port = 587  # Use 587 for TLS
    sender_email = ""  # FU Berlin Main Account
    shared_email = ""  # FU Berlin Shared Account (Group)
    sender_password = ""  # Password for main account

    # Nachricht erstellen
    message = MIMEMultipart()
    message["From"] = shared_email  # Shared Account as sender
    message["To"] = recipient
    message["Subject"] = subject
    message.attach(MIMEText(body, "plain"))

    # E-Mail senden
    try:
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()  # TLS aktivieren
            server.login(sender_email, sender_password)  # Mit Hauptkonto anmelden
            server.sendmail(shared_email, recipient, message.as_string())  # Freigegebenes Postfach als Absender
        print(f'--> Email sent successfully! From {shared_email} to {recipient}')
    except Exception as e:
        print(f"--> Sending Email failed: {e}")


def check_events_and_send_reminder(days_from_today):

    events = get_events_for_specific_day(days_from_today)

    if not events:
        print("No upcoming events found.")
        return

    now = datetime.utcnow().replace(tzinfo=timezone.utc)
    #reminder_time = timedelta(minutes=30)
    reminder_time = timedelta(days=days_from_today)  # Reminder time before the event

    for event in events:
        start_time = datetime.fromisoformat(event['start'].get('dateTime', event['start'].get('date')))
        if start_time.tzinfo is None:
            start_time = start_time.replace(tzinfo=timezone.utc)

        description = event.get('description', '')
        recipient = extract_email_from_text(description)

        if recipient:
            subject = f"Erinnerung MRT Termin: {start_time.strftime('%d.%m.%Y %H:%M')} Uhr"
            body = (
                "Hallo, vielen Dank für Ihre Teilnahme an unserer Studie!\n\n"
                f"Dies ist eine kurze Erinnerung an den nächsten Termin am {start_time.strftime('%d.%m.%Y')} um {start_time.strftime('%H:%M')} Uhr. "
                "Bitte versuchen Sie unbedingt pünktlich zu kommen und seien Sie am besten schon ein paar Minuten vor dem Termin vor Ort damit wir pünktlich loslegen können.\n\n"
                "Bitte halten Sie sich unbedingt vor jeder Sitzung an folgende Punkte:\n\n"
                "1-Bitte trinken Sie in den letzten 3 Stunden vor der Sitzung keinen Kaffee, Tee oder koffeinhaltige Getränke.\n"
                "2-Bitte betätigen Sie sich in den letzten 3 Stunden vor der Sitzung nicht intensiv körperlich.\n\n"
                "Wenn möglich beachten Sie bitte die folgenden Punkte:\n\n"
                "3-Bitte schlafen Sie in der Nacht vor der Messung ausreichend.\n"
                "4-Bitte vermeiden Sie das Rauchen vor der Messung, es sei denn, Sie sind regelmäßiger Raucher.\n"
                "5-Bitte entfernen Sie vor der Sitzung alle Metalle (Ringe, Halsketten, Ohrringe, Piercings, Gürtelschnallen, Bügel-BH).\n"
                "6-Fall sie eine Brille benötigen, bringen Sie zu Ihrem Termin bitte Kontaktlinsen oder Ihre Dioptrien-Werte mit.\n"
                "7-Möglichst die Haare frisch waschen aber keine anderen Haarprodukte an dem Morgen verwenden (Conditioner, Haargel, Haarspray, ...).\n\n"
                "Lassen Sie uns bitte unbedingt frühzeitig wissen wenn Sie den Termin nicht wahrnehmen können, aus welchen Gründen auch immer. Wir können dann gerne einen Ersatztermin ausmachen.\n\n"
                "Vielen Dank & viele Grüße,\n\n"
                "Team MeMoSLAP\n\n"
                "https://www.memoslap.de/de/home/\n"
            )
            print(f"\nEvent: {event['summary']} on {start_time.strftime('%d.%m.%Y %H:%M')}")
            send_email(recipient, subject, body)
        #else:
            #print(f"\nEvent: {event['summary']} on {start_time.strftime('%d.%m.%Y %H:%M')}")
            #print(f"--> Ignored: No valid E-Mail address in description")


if __name__ == "__main__":

    # get credentials (only needed once to get the token.json file)
    creds = get_credentials()

    service = build('calendar', 'v3', credentials=creds)

    # execute automatic email reminder for tomorrow:
    days_from_today = 1
    print(f'Checking events in {days_from_today} day(s) from today..')
    check_events_and_send_reminder(days_from_today)

    # Pause for 5 seconds
    time.sleep(5)

    # execute automatic email reminder for in 3 days:
    days_from_today = 3
    print(f'\nChecking events in {days_from_today} day(s) from today..')
    check_events_and_send_reminder(days_from_today)

