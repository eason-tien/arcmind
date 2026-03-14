"""
Skill: google_workspace
Google Workspace 整合 — Gmail / Calendar / Drive / Sheets

需要:
- pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib
- OAuth2 credentials: ~/.arcmind/google_credentials.json
- 首次使用需執行 action=auth 完成 OAuth flow
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger("arcmind.skill.google_workspace")

_CREDS_DIR = Path.home() / ".arcmind"
_CREDS_FILE = _CREDS_DIR / "google_credentials.json"
_TOKEN_FILE = _CREDS_DIR / "google_token.json"

SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/spreadsheets",
]


def _get_credentials():
    """Get or refresh Google OAuth2 credentials."""
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        raise RuntimeError(
            "需要安裝 Google API 套件: "
            "pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib"
        )

    creds = None
    if _TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(_TOKEN_FILE), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not _CREDS_FILE.exists():
                raise RuntimeError(
                    f"OAuth credentials 檔案不存在: {_CREDS_FILE}\n"
                    "請從 Google Cloud Console 下載 OAuth 2.0 Client ID JSON，"
                    f"存到 {_CREDS_FILE}"
                )
            flow = InstalledAppFlow.from_client_secrets_file(
                str(_CREDS_FILE), SCOPES
            )
            creds = flow.run_local_server(port=0)

        _CREDS_DIR.mkdir(parents=True, exist_ok=True)
        _TOKEN_FILE.write_text(creds.to_json())

    return creds


def _build_service(api: str, version: str):
    """Build a Google API service client."""
    from googleapiclient.discovery import build
    creds = _get_credentials()
    return build(api, version, credentials=creds)


# ── Gmail ─────────────────────────────────────────────────────

def _gmail_send(inputs: dict) -> dict:
    """Send an email via Gmail."""
    import base64
    from email.mime.text import MIMEText

    service = _build_service("gmail", "v1")
    to = inputs.get("to", "")
    subject = inputs.get("subject", "")
    body = inputs.get("body", "")
    cc = inputs.get("cc", "")

    msg = MIMEText(body, "plain", "utf-8")
    msg["to"] = to
    msg["subject"] = subject
    if cc:
        msg["cc"] = cc

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    result = service.users().messages().send(
        userId="me", body={"raw": raw}
    ).execute()

    return {"success": True, "message_id": result.get("id"), "thread_id": result.get("threadId")}


def _gmail_search(inputs: dict) -> dict:
    """Search Gmail messages."""
    service = _build_service("gmail", "v1")
    query = inputs.get("query", "")
    max_results = int(inputs.get("max_results", 10))

    result = service.users().messages().list(
        userId="me", q=query, maxResults=max_results
    ).execute()

    messages = []
    for msg_ref in result.get("messages", []):
        msg = service.users().messages().get(
            userId="me", id=msg_ref["id"], format="metadata",
            metadataHeaders=["From", "To", "Subject", "Date"]
        ).execute()
        headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
        messages.append({
            "id": msg["id"],
            "thread_id": msg.get("threadId"),
            "snippet": msg.get("snippet", ""),
            "from": headers.get("From", ""),
            "to": headers.get("To", ""),
            "subject": headers.get("Subject", ""),
            "date": headers.get("Date", ""),
        })

    return {"success": True, "messages": messages, "count": len(messages)}


def _gmail_read(inputs: dict) -> dict:
    """Read a specific Gmail message."""
    service = _build_service("gmail", "v1")
    msg_id = inputs.get("message_id", "")

    msg = service.users().messages().get(
        userId="me", id=msg_id, format="full"
    ).execute()

    headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}

    # Extract body
    body = ""
    payload = msg.get("payload", {})
    if payload.get("body", {}).get("data"):
        import base64
        body = base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="replace")
    elif payload.get("parts"):
        for part in payload["parts"]:
            if part.get("mimeType") == "text/plain" and part.get("body", {}).get("data"):
                import base64
                body = base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", errors="replace")
                break

    return {
        "success": True,
        "id": msg["id"],
        "subject": headers.get("Subject", ""),
        "from": headers.get("From", ""),
        "to": headers.get("To", ""),
        "date": headers.get("Date", ""),
        "body": body[:5000],
        "snippet": msg.get("snippet", ""),
    }


# ── Calendar ──────────────────────────────────────────────────

def _calendar_list_events(inputs: dict) -> dict:
    """List upcoming calendar events."""
    from datetime import datetime, timezone

    service = _build_service("calendar", "v3")
    max_results = int(inputs.get("max_results", 10))
    time_min = inputs.get("time_min", datetime.now(timezone.utc).isoformat())

    result = service.events().list(
        calendarId="primary", timeMin=time_min,
        maxResults=max_results, singleEvents=True, orderBy="startTime"
    ).execute()

    events = []
    for e in result.get("items", []):
        events.append({
            "id": e.get("id"),
            "summary": e.get("summary", "(無標題)"),
            "start": e.get("start", {}).get("dateTime", e.get("start", {}).get("date", "")),
            "end": e.get("end", {}).get("dateTime", e.get("end", {}).get("date", "")),
            "location": e.get("location", ""),
            "description": e.get("description", "")[:200],
        })

    return {"success": True, "events": events, "count": len(events)}


def _calendar_create_event(inputs: dict) -> dict:
    """Create a calendar event."""
    service = _build_service("calendar", "v3")

    event_body = {
        "summary": inputs.get("summary", "新事件"),
        "location": inputs.get("location", ""),
        "description": inputs.get("description", ""),
        "start": {"dateTime": inputs["start_time"], "timeZone": inputs.get("timezone", "Asia/Taipei")},
        "end": {"dateTime": inputs["end_time"], "timeZone": inputs.get("timezone", "Asia/Taipei")},
    }

    attendees = inputs.get("attendees", [])
    if attendees:
        event_body["attendees"] = [{"email": e} for e in attendees]

    result = service.events().insert(calendarId="primary", body=event_body).execute()
    return {"success": True, "event_id": result.get("id"), "link": result.get("htmlLink")}


def _calendar_delete_event(inputs: dict) -> dict:
    """Delete a calendar event."""
    service = _build_service("calendar", "v3")
    event_id = inputs.get("event_id", "")
    service.events().delete(calendarId="primary", eventId=event_id).execute()
    return {"success": True, "deleted": event_id}


# ── Drive ─────────────────────────────────────────────────────

def _drive_list_files(inputs: dict) -> dict:
    """List files in Google Drive."""
    service = _build_service("drive", "v3")
    query = inputs.get("query", "")
    max_results = int(inputs.get("max_results", 20))

    params = {
        "pageSize": max_results,
        "fields": "files(id, name, mimeType, modifiedTime, size, webViewLink)",
    }
    if query:
        params["q"] = query

    result = service.files().list(**params).execute()
    files = result.get("files", [])

    return {"success": True, "files": files, "count": len(files)}


def _drive_search(inputs: dict) -> dict:
    """Search files in Google Drive by name."""
    keyword = inputs.get("keyword", "")
    q = f"name contains '{keyword}' and trashed = false"
    return _drive_list_files({"query": q, "max_results": inputs.get("max_results", 20)})


def _drive_download(inputs: dict) -> dict:
    """Download a file from Google Drive."""
    service = _build_service("drive", "v3")
    file_id = inputs.get("file_id", "")
    save_path = inputs.get("save_path", f"/tmp/{file_id}")

    # Get file metadata
    meta = service.files().get(fileId=file_id, fields="name, mimeType").execute()

    from googleapiclient.http import MediaIoBaseDownload
    import io

    request = service.files().get_media(fileId=file_id)
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()

    Path(save_path).parent.mkdir(parents=True, exist_ok=True)
    Path(save_path).write_bytes(fh.getvalue())

    return {"success": True, "file_name": meta.get("name"), "saved_to": save_path, "size": len(fh.getvalue())}


# ── Sheets ────────────────────────────────────────────────────

def _sheets_read(inputs: dict) -> dict:
    """Read data from a Google Sheet."""
    service = _build_service("sheets", "v4")
    spreadsheet_id = inputs.get("spreadsheet_id", "")
    range_name = inputs.get("range", "Sheet1!A1:Z100")

    result = service.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id, range=range_name
    ).execute()

    values = result.get("values", [])
    return {"success": True, "values": values, "rows": len(values)}


def _sheets_write(inputs: dict) -> dict:
    """Write data to a Google Sheet."""
    service = _build_service("sheets", "v4")
    spreadsheet_id = inputs.get("spreadsheet_id", "")
    range_name = inputs.get("range", "Sheet1!A1")
    values = inputs.get("values", [])

    body = {"values": values}
    result = service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id, range=range_name,
        valueInputOption="USER_ENTERED", body=body
    ).execute()

    return {"success": True, "updated_cells": result.get("updatedCells", 0)}


def _sheets_create(inputs: dict) -> dict:
    """Create a new Google Sheet."""
    service = _build_service("sheets", "v4")
    title = inputs.get("title", "ArcMind Sheet")

    spreadsheet = service.spreadsheets().create(
        body={"properties": {"title": title}},
        fields="spreadsheetId,spreadsheetUrl"
    ).execute()

    return {
        "success": True,
        "spreadsheet_id": spreadsheet.get("spreadsheetId"),
        "url": spreadsheet.get("spreadsheetUrl"),
    }


# ── Auth ──────────────────────────────────────────────────────

def _auth(inputs: dict) -> dict:
    """Trigger OAuth2 authentication flow."""
    try:
        _get_credentials()
        return {"success": True, "message": "Google OAuth2 認證成功", "token_file": str(_TOKEN_FILE)}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ── Main Entry ────────────────────────────────────────────────

def run(inputs: dict) -> dict:
    """
    Google Workspace skill entry point.

    inputs:
      action: gmail_send | gmail_search | gmail_read |
              calendar_list | calendar_create | calendar_delete |
              drive_list | drive_search | drive_download |
              sheets_read | sheets_write | sheets_create |
              auth
    """
    action = inputs.get("action", "")

    handlers = {
        "gmail_send": _gmail_send,
        "gmail_search": _gmail_search,
        "gmail_read": _gmail_read,
        "calendar_list": _calendar_list_events,
        "calendar_create": _calendar_create_event,
        "calendar_delete": _calendar_delete_event,
        "drive_list": _drive_list_files,
        "drive_search": _drive_search,
        "drive_download": _drive_download,
        "sheets_read": _sheets_read,
        "sheets_write": _sheets_write,
        "sheets_create": _sheets_create,
        "auth": _auth,
    }

    handler = handlers.get(action)
    if not handler:
        return {
            "success": False,
            "error": f"未知 action: {action}",
            "available_actions": list(handlers.keys()),
        }

    try:
        return handler(inputs)
    except Exception as e:
        logger.error("[google_workspace] %s failed: %s", action, e)
        return {"success": False, "error": str(e), "action": action}
