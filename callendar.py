from __future__ import annotations

import os
from difflib import SequenceMatcher
from datetime import datetime, timedelta, timezone
from typing import Any

from dotenv import load_dotenv
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

SCOPES = ["https://www.googleapis.com/auth/calendar"]


def _env(name: str, default: str) -> str:
    value = os.getenv(name, default).strip()
    return value if value else default


def get_calendar_service():
    load_dotenv("token.env")
    credentials_file = _env("GOOGLE_CREDENTIALS_FILE", "google_credentials.json")
    token_file = _env("GOOGLE_TOKEN_FILE", "google_token.json")

    creds = None
    if os.path.exists(token_file):
        creds = Credentials.from_authorized_user_file(token_file, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(credentials_file):
                raise FileNotFoundError(
                    f"Missing OAuth client file: {credentials_file}. "
                    "Download it from Google Cloud Console and place it in project root."
                )
            flow = InstalledAppFlow.from_client_secrets_file(credentials_file, SCOPES)
            creds = flow.run_local_server(port=0)

        with open(token_file, "w", encoding="utf-8") as token:
            token.write(creds.to_json())

    return build("calendar", "v3", credentials=creds, cache_discovery=False)


def _normalize_iso(dt_str: str) -> datetime:
    value = dt_str.strip()
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone(timedelta(hours=1)))
    return dt


def list_events(max_results: int = 10) -> list[dict[str, Any]]:
    service = get_calendar_service()
    calendar_id = _env("GOOGLE_CALENDAR_ID", "primary")
    now = datetime.now(timezone.utc).isoformat()
    result = (
        service.events()
        .list(
            calendarId=calendar_id,
            timeMin=now,
            maxResults=max_results,
            singleEvents=True,
            orderBy="startTime",
        )
        .execute()
    )
    return result.get("items", [])


def _name_score(query: str, candidate: str) -> float:
    return SequenceMatcher(None, query.lower().strip(), candidate.lower().strip()).ratio()


def find_events_by_name(name: str, max_results: int = 20) -> list[dict[str, Any]]:
    service = get_calendar_service()
    calendar_id = _env("GOOGLE_CALENDAR_ID", "primary")
    now = datetime.now(timezone.utc).isoformat()
    result = (
        service.events()
        .list(
            calendarId=calendar_id,
            q=name,
            timeMin=now,
            maxResults=max_results,
            singleEvents=True,
            orderBy="startTime",
        )
        .execute()
    )
    items = result.get("items", [])
    return sorted(
        items,
        key=lambda e: _name_score(name, e.get("summary", "")),
        reverse=True,
    )


def find_best_event_id_by_name(name: str, min_score: float = 0.45) -> str | None:
    matches = find_events_by_name(name=name, max_results=20)
    if not matches:
        return None
    best = matches[0]
    score = _name_score(name, best.get("summary", ""))
    if score < min_score:
        return None
    return best.get("id")


def create_event(
    summary: str,
    start_iso: str,
    end_iso: str = "",
    description: str = "",
    timezone_name: str = "UTC",
) -> dict[str, Any]:
    start_dt = _normalize_iso(start_iso)
    if end_iso.strip():
        end_dt = _normalize_iso(end_iso)
    else:
        end_dt = start_dt + timedelta(hours=1)

    if end_dt <= start_dt:
        end_dt = start_dt + timedelta(hours=1)

    service = get_calendar_service()
    calendar_id = _env("GOOGLE_CALENDAR_ID", "primary")
    body = {
        "summary": summary,
        "description": description,
        "start": {"dateTime": start_dt.isoformat()},
        "end": {"dateTime": end_dt.isoformat()},
    }
    try:
        return service.events().insert(calendarId=calendar_id, body=body).execute()
    except HttpError as exc:
        details = exc._get_reason() if hasattr(exc, "_get_reason") else str(exc)
        raise ValueError(
            f"Google Calendar rejected event payload. "
            f"summary={summary!r}, start={body['start']['dateTime']!r}, "
            f"end={body['end']['dateTime']!r}, calendar_id={calendar_id!r}, "
            f"reason={details}"
        ) from exc


def update_event(
    event_id: str,
    summary: str | None = None,
    start_iso: str | None = None,
    end_iso: str | None = None,
    description: str | None = None,
    timezone_name: str = "UTC",
) -> dict[str, Any]:
    service = get_calendar_service()
    calendar_id = _env("GOOGLE_CALENDAR_ID", "primary")
    event = service.events().get(calendarId=calendar_id, eventId=event_id).execute()

    if summary is not None:
        event["summary"] = summary
    if description is not None:
        event["description"] = description
    if start_iso is not None:
        event["start"] = {"dateTime": start_iso, "timeZone": timezone_name}
    if end_iso is not None:
        event["end"] = {"dateTime": end_iso, "timeZone": timezone_name}

    return (
        service.events()
        .update(calendarId=calendar_id, eventId=event_id, body=event)
        .execute()
    )


def delete_event(event_id: str) -> None:
    service = get_calendar_service()
    calendar_id = _env("GOOGLE_CALENDAR_ID", "primary")
    service.events().delete(calendarId=calendar_id, eventId=event_id).execute()


def update_event_by_name(
    event_name: str,
    summary: str | None = None,
    start_iso: str | None = None,
    end_iso: str | None = None,
    description: str | None = None,
    timezone_name: str = "UTC",
) -> dict[str, Any]:
    event_id = find_best_event_id_by_name(event_name)
    if not event_id:
        raise ValueError(f"No matching event found for name: {event_name}")
    return update_event(
        event_id=event_id,
        summary=summary,
        start_iso=start_iso,
        end_iso=end_iso,
        description=description,
        timezone_name=timezone_name,
    )


def delete_event_by_name(event_name: str) -> str:
    event_id = find_best_event_id_by_name(event_name)
    if not event_id:
        raise ValueError(f"No matching event found for name: {event_name}")
    delete_event(event_id)
    return event_id


if __name__ == "__main__":
    print("Authenticating and reading next 5 events from Google Calendar...")
    events = list_events(max_results=5)
    if not events:
        print("No upcoming events.")
    else:
        for event in events:
            start = event.get("start", {}).get("dateTime", event.get("start", {}).get("date"))
            print(f"- {start} | {event.get('summary', '(no title)')} | id={event.get('id')}")
