"""Send appointment reminder emails from upcoming Google Calendar events.

This script is used for the MEMOSLAP participant workflow. It reads calendar
events for selected days ahead, resolves participant contact details from local
protected study spreadsheets, and sends the configured reminder text by SMTP.
"""

from __future__ import annotations

import argparse
import os
import re
import smtplib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from io import BytesIO
from pathlib import Path

SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]
EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
PROJECT_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class MailSettings:
    smtp_server: str
    smtp_port: int
    sender_email: str
    sender_password: str
    from_email: str


@dataclass(frozen=True)
class LookupSettings:
    matching_list: Path
    matching_password: str
    screening_list: Path
    screening_password: str


def get_env(*names: str) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return None


def require_env(*names: str) -> str:
    value = get_env(*names)
    if not value:
        joined_names = " or ".join(names)
        raise RuntimeError(f"Missing required environment variable: {joined_names}")
    return value


def load_mail_settings() -> MailSettings:
    return MailSettings(
        smtp_server=require_env("STUDY_SMTP_SERVER", "MEMOSLAP_SMTP_SERVER"),
        smtp_port=int(get_env("STUDY_SMTP_PORT", "MEMOSLAP_SMTP_PORT") or "587"),
        sender_email=require_env("STUDY_SMTP_USER", "MEMOSLAP_SMTP_USER"),
        sender_password=require_env("STUDY_SMTP_PASSWORD", "MEMOSLAP_SMTP_PASSWORD"),
        from_email=get_env("STUDY_FROM_EMAIL", "MEMOSLAP_FROM_EMAIL")
        or require_env("STUDY_SMTP_USER", "MEMOSLAP_SMTP_USER"),
    )


def load_lookup_settings() -> LookupSettings:
    return LookupSettings(
        matching_list=Path(require_env("STUDY_MATCHING_LIST", "MEMOSLAP_MATCHING_LIST")),
        matching_password=require_env(
            "STUDY_MATCHING_PASSWORD", "MEMOSLAP_MATCHING_PASSWORD"
        ),
        screening_list=Path(require_env("STUDY_SCREENING_LIST", "MEMOSLAP_SCREENING_LIST")),
        screening_password=require_env(
            "STUDY_SCREENING_PASSWORD", "MEMOSLAP_SCREENING_PASSWORD"
        ),
    )


def get_credentials(
    credentials_path: Path,
    token_path: Path,
    mail_settings: MailSettings | None = None,
    reauth_notify_email: str | None = None,
):
    from google.auth.transport.requests import Request
    from google.auth.exceptions import RefreshError
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    creds = None
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    try:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
    except RefreshError as exc:
        if reauth_notify_email and mail_settings:
            send_email(
                recipient=reauth_notify_email,
                subject="Google Calendar reminder script needs re-authentication",
                body=(
                    "The automated Google Calendar reminder script could not "
                    "refresh its local token. Re-run it manually with "
                    "RUN_MANUALLY=true to refresh the token cache."
                ),
                mail_settings=mail_settings,
                dry_run=False,
            )
        if os.getenv("RUN_MANUALLY") == "true":
            print("Token refresh failed; starting manual re-authentication.")
        else:
            raise RuntimeError(
                "Google token expired or was revoked. Re-run manually with "
                "RUN_MANUALLY=true to refresh the local token."
            ) from exc
        creds = None

    if not creds or not creds.valid:
        if not credentials_path.exists():
            raise FileNotFoundError(
                f"Missing Google OAuth credentials file: {credentials_path}"
            )
        flow = InstalledAppFlow.from_client_secrets_file(str(credentials_path), SCOPES)
        creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")

    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(creds.to_json(), encoding="utf-8")
    return creds


def event_window(days_from_today: int) -> tuple[str, str]:
    day = datetime.now(timezone.utc) + timedelta(days=days_from_today)
    start = day.replace(hour=0, minute=1, second=0, microsecond=0)
    end = day.replace(hour=23, minute=59, second=59, microsecond=999999)
    return start.isoformat(), end.isoformat()


def get_events(service, calendar_id: str, days_from_today: int) -> list[dict]:
    time_min, time_max = event_window(days_from_today)
    events_result = (
        service.events()
        .list(
            calendarId=calendar_id,
            timeMin=time_min,
            timeMax=time_max,
            singleEvents=True,
            orderBy="startTime",
        )
        .execute()
    )
    return events_result.get("items", [])


def extract_email_from_text(text: str) -> str | None:
    match = EMAIL_RE.search(text or "")
    return match.group(0) if match else None


def read_protected_excel(file_path: Path, password: str):
    import msoffcrypto
    import pandas as pd

    decrypted = BytesIO()
    with file_path.open("rb") as f:
        office_file = msoffcrypto.OfficeFile(f)
        office_file.load_key(password=password)
        office_file.decrypt(decrypted)
    decrypted.seek(0)
    return pd.read_excel(decrypted, engine="openpyxl")


def lookup_value(
    lookup_key: int,
    file_path: Path,
    password: str,
    key_column: int = 0,
    value_column: int = 1,
) -> object | None:
    df = read_protected_excel(file_path, password)
    row = df[df.iloc[:, key_column] == lookup_key]
    return row.iloc[0, value_column] if not row.empty else None


def resolve_recipient(description: str, lookup_settings: LookupSettings | None) -> str | None:
    if lookup_settings is None:
        return extract_email_from_text(description)

    try:
        participant_id = int(description.strip())
    except ValueError:
        return extract_email_from_text(description)

    secondary_id = lookup_value(
        participant_id,
        lookup_settings.matching_list,
        lookup_settings.matching_password,
    )
    if secondary_id is None:
        print(f"Skipped: participant ID {participant_id} not found in matching list")
        return None

    recipient = lookup_value(
        int(secondary_id),
        lookup_settings.screening_list,
        lookup_settings.screening_password,
    )
    if recipient is None:
        print(f"Skipped: secondary ID {int(secondary_id)} not found in screening list")
        return None

    return str(recipient)


def parse_event_start(event: dict) -> datetime:
    raw_start = event["start"].get("dateTime", event["start"].get("date"))
    start_time = datetime.fromisoformat(raw_start.replace("Z", "+00:00"))
    if start_time.tzinfo is None:
        start_time = start_time.replace(tzinfo=timezone.utc)
    return start_time


def render_template(template_path: Path, start_time: datetime) -> str:
    template = template_path.read_text(encoding="utf-8")
    return template.format(
        appointment_date=start_time.strftime("%d.%m.%Y"),
        appointment_time=start_time.strftime("%H:%M"),
        appointment_datetime=start_time.strftime("%d.%m.%Y %H:%M"),
    )


def send_email(
    recipient: str,
    subject: str,
    body: str,
    mail_settings: MailSettings | None,
    dry_run: bool,
) -> None:
    if dry_run:
        print(f"DRY RUN: would send '{subject}' to {recipient}")
        return
    if mail_settings is None:
        raise RuntimeError("Mail settings are required unless --dry-run is used.")

    message = MIMEMultipart()
    message["From"] = mail_settings.from_email
    message["To"] = recipient
    message["Subject"] = subject
    message.attach(MIMEText(body, "plain", "utf-8"))

    with smtplib.SMTP(mail_settings.smtp_server, mail_settings.smtp_port) as server:
        server.starttls()
        server.login(mail_settings.sender_email, mail_settings.sender_password)
        server.sendmail(mail_settings.from_email, recipient, message.as_string())
    print(f"Sent reminder to {recipient}")


def process_day(
    service,
    calendar_id: str,
    days_from_today: int,
    template_path: Path,
    mail_settings: MailSettings | None,
    lookup_settings: LookupSettings | None,
    dry_run: bool,
) -> None:
    print(f"Checking events {days_from_today} day(s) from today...")
    events = get_events(service, calendar_id, days_from_today)
    if not events:
        print("No upcoming events found.")
        return

    for event in events:
        start_time = parse_event_start(event)
        recipient = resolve_recipient(event.get("description", ""), lookup_settings)
        event_name = event.get("summary", "Untitled event")

        if not recipient:
            print(f"Skipped '{event_name}': no recipient could be resolved")
            continue

        subject = f"Erinnerung MRT Termin: {start_time.strftime('%d.%m.%Y %H:%M')} Uhr"
        body = render_template(template_path, start_time)
        send_email(recipient, subject, body, mail_settings, dry_run)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Send study appointment reminders.")
    parser.add_argument(
        "--calendar-id",
        default=get_env("STUDY_CALENDAR_ID", "MEMOSLAP_CALENDAR_ID"),
    )
    parser.add_argument("--days", nargs="+", type=int, default=[1, 3])
    parser.add_argument(
        "--credentials",
        type=Path,
        default=PROJECT_ROOT / "config" / "credentials.json",
        help="Local Google OAuth client secret JSON. Do not commit this file.",
    )
    parser.add_argument(
        "--token",
        type=Path,
        default=PROJECT_ROOT / "config" / "token.json",
        help="Local Google OAuth token cache. Do not commit this file.",
    )
    parser.add_argument(
        "--template",
        type=Path,
        default=PROJECT_ROOT / "email_reminders" / "templates" / "mri_reminder_de.txt",
    )
    parser.add_argument(
        "--recipient-source",
        choices=["lookup", "description-email"],
        default=get_env("STUDY_RECIPIENT_SOURCE", "MEMOSLAP_RECIPIENT_SOURCE") or "lookup",
        help="Use protected study spreadsheets or extract an email from the calendar description.",
    )
    parser.add_argument(
        "--reauth-notify-email",
        default=get_env("STUDY_REAUTH_NOTIFY_EMAIL", "MEMOSLAP_REAUTH_NOTIFY_EMAIL"),
        help="Optional address to notify when Google token refresh fails.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print intended sends only.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.calendar_id:
        raise RuntimeError("Pass --calendar-id or set MEMOSLAP_CALENDAR_ID.")

    from googleapiclient.discovery import build

    mail_settings = None if args.dry_run else load_mail_settings()
    creds = get_credentials(
        args.credentials,
        args.token,
        mail_settings=mail_settings,
        reauth_notify_email=args.reauth_notify_email,
    )
    service = build("calendar", "v3", credentials=creds)
    lookup_settings = (
        load_lookup_settings() if args.recipient_source == "lookup" else None
    )

    for days_from_today in args.days:
        process_day(
            service=service,
            calendar_id=args.calendar_id,
            days_from_today=days_from_today,
            template_path=args.template,
            mail_settings=mail_settings,
            lookup_settings=lookup_settings,
            dry_run=args.dry_run,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
