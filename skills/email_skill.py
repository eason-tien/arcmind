"""
Skill: email_skill
Email 整合 — SMTP 發送 + IMAP 讀取

環境變數:
- SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS
- IMAP_HOST, IMAP_PORT, IMAP_USER, IMAP_PASS
"""
from __future__ import annotations

import email
import email.utils
import imaplib
import logging
import os
import smtplib
from email.header import decode_header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

logger = logging.getLogger("arcmind.skill.email")


def _get_smtp_config() -> dict:
    """Get SMTP configuration from env vars."""
    host = os.environ.get("SMTP_HOST", "")
    port = int(os.environ.get("SMTP_PORT", "587"))
    user = os.environ.get("SMTP_USER", "")
    password = os.environ.get("SMTP_PASS", "")

    if not host or not user:
        raise RuntimeError(
            "SMTP 設定不完整。需要設定: SMTP_HOST, SMTP_USER, SMTP_PASS"
        )
    return {"host": host, "port": port, "user": user, "password": password}


def _get_imap_config() -> dict:
    """Get IMAP configuration from env vars."""
    host = os.environ.get("IMAP_HOST", "")
    port = int(os.environ.get("IMAP_PORT", "993"))
    user = os.environ.get("IMAP_USER", os.environ.get("SMTP_USER", ""))
    password = os.environ.get("IMAP_PASS", os.environ.get("SMTP_PASS", ""))

    if not host or not user:
        raise RuntimeError(
            "IMAP 設定不完整。需要設定: IMAP_HOST, IMAP_USER, IMAP_PASS"
        )
    return {"host": host, "port": port, "user": user, "password": password}


def _decode_header_value(value: str) -> str:
    """Decode an email header value."""
    if not value:
        return ""
    decoded_parts = decode_header(value)
    result = []
    for part, charset in decoded_parts:
        if isinstance(part, bytes):
            result.append(part.decode(charset or "utf-8", errors="replace"))
        else:
            result.append(part)
    return "".join(result)


def _get_email_body(msg) -> str:
    """Extract plain text body from email message."""
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            if content_type == "text/plain":
                try:
                    return part.get_payload(decode=True).decode(
                        part.get_content_charset() or "utf-8", errors="replace"
                    )
                except Exception:
                    pass
        # Fallback to HTML
        for part in msg.walk():
            if part.get_content_type() == "text/html":
                try:
                    return part.get_payload(decode=True).decode(
                        part.get_content_charset() or "utf-8", errors="replace"
                    )
                except Exception:
                    pass
    else:
        try:
            return msg.get_payload(decode=True).decode(
                msg.get_content_charset() or "utf-8", errors="replace"
            )
        except Exception:
            pass
    return ""


# ── SMTP Actions ─────────────────────────────────────────────

def _send(inputs: dict) -> dict:
    """Send an email via SMTP."""
    config = _get_smtp_config()
    to = inputs.get("to", "")
    subject = inputs.get("subject", "")
    body = inputs.get("body", "")
    cc = inputs.get("cc", "")
    html = inputs.get("html", False)

    if not to or not subject:
        return {"success": False, "error": "to 和 subject 為必填"}

    msg = MIMEMultipart("alternative")
    msg["From"] = config["user"]
    msg["To"] = to
    msg["Subject"] = subject
    if cc:
        msg["Cc"] = cc

    content_type = "html" if html else "plain"
    msg.attach(MIMEText(body, content_type, "utf-8"))

    try:
        with smtplib.SMTP(config["host"], config["port"]) as server:
            server.starttls()
            server.login(config["user"], config["password"])
            recipients = [to] + ([cc] if cc else [])
            server.sendmail(config["user"], recipients, msg.as_string())
        return {"success": True, "to": to, "subject": subject}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ── IMAP Actions ─────────────────────────────────────────────

def _search(inputs: dict) -> dict:
    """Search emails via IMAP."""
    config = _get_imap_config()
    query = inputs.get("query", "ALL")
    folder = inputs.get("folder", "INBOX")
    max_results = int(inputs.get("max_results", 20))
    search_criteria = inputs.get("criteria", "")

    # Build IMAP search criteria
    if search_criteria:
        imap_query = search_criteria
    elif query and query != "ALL":
        imap_query = f'(OR (SUBJECT "{query}") (FROM "{query}") (BODY "{query}"))'
    else:
        imap_query = "ALL"

    try:
        conn = imaplib.IMAP4_SSL(config["host"], config["port"])
        conn.login(config["user"], config["password"])
        conn.select(folder, readonly=True)

        _, data = conn.search(None, imap_query)
        msg_ids = data[0].split()

        # Get most recent messages
        msg_ids = msg_ids[-max_results:] if len(msg_ids) > max_results else msg_ids
        msg_ids.reverse()

        messages = []
        for mid in msg_ids:
            _, msg_data = conn.fetch(mid, "(RFC822.HEADER)")
            if msg_data and msg_data[0]:
                raw = msg_data[0][1]
                msg = email.message_from_bytes(raw)
                messages.append({
                    "id": mid.decode(),
                    "from": _decode_header_value(msg.get("From", "")),
                    "to": _decode_header_value(msg.get("To", "")),
                    "subject": _decode_header_value(msg.get("Subject", "")),
                    "date": msg.get("Date", ""),
                })

        conn.logout()
        return {"success": True, "messages": messages, "count": len(messages)}

    except Exception as e:
        return {"success": False, "error": str(e)}


def _read(inputs: dict) -> dict:
    """Read a specific email by ID."""
    config = _get_imap_config()
    msg_id = inputs.get("message_id", "")
    folder = inputs.get("folder", "INBOX")

    if not msg_id:
        return {"success": False, "error": "message_id 為必填"}

    try:
        conn = imaplib.IMAP4_SSL(config["host"], config["port"])
        conn.login(config["user"], config["password"])
        conn.select(folder, readonly=True)

        _, msg_data = conn.fetch(msg_id.encode(), "(RFC822)")
        if not msg_data or not msg_data[0]:
            conn.logout()
            return {"success": False, "error": "郵件不存在"}

        raw = msg_data[0][1]
        msg = email.message_from_bytes(raw)
        body = _get_email_body(msg)

        conn.logout()

        return {
            "success": True,
            "id": msg_id,
            "from": _decode_header_value(msg.get("From", "")),
            "to": _decode_header_value(msg.get("To", "")),
            "subject": _decode_header_value(msg.get("Subject", "")),
            "date": msg.get("Date", ""),
            "body": body[:5000],
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


def _list_folders(inputs: dict) -> dict:
    """List IMAP folders."""
    config = _get_imap_config()

    try:
        conn = imaplib.IMAP4_SSL(config["host"], config["port"])
        conn.login(config["user"], config["password"])
        _, folders_data = conn.list()

        folders = []
        for f in (folders_data or []):
            if isinstance(f, bytes):
                parts = f.decode().split(' "/" ')
                if len(parts) >= 2:
                    folders.append(parts[-1].strip('"'))

        conn.logout()
        return {"success": True, "folders": folders, "count": len(folders)}

    except Exception as e:
        return {"success": False, "error": str(e)}


def _mark_read(inputs: dict) -> dict:
    """Mark an email as read."""
    config = _get_imap_config()
    msg_id = inputs.get("message_id", "")
    folder = inputs.get("folder", "INBOX")

    if not msg_id:
        return {"success": False, "error": "message_id 為必填"}

    try:
        conn = imaplib.IMAP4_SSL(config["host"], config["port"])
        conn.login(config["user"], config["password"])
        conn.select(folder)
        conn.store(msg_id.encode(), "+FLAGS", "\\Seen")
        conn.logout()
        return {"success": True, "marked": msg_id}

    except Exception as e:
        return {"success": False, "error": str(e)}


# ── Main Entry ────────────────────────────────────────────────

def run(inputs: dict) -> dict:
    """
    Email skill entry point.

    inputs:
      action: send | search | read | list_folders | mark_read
    """
    action = inputs.get("action", "search")

    handlers = {
        "send": _send,
        "search": _search,
        "read": _read,
        "list_folders": _list_folders,
        "mark_read": _mark_read,
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
        logger.error("[email] %s failed: %s", action, e)
        return {"success": False, "error": str(e), "action": action}
