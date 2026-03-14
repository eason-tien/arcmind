# -*- coding: utf-8 -*-
"""
ArcMind API — GitHub Webhook Routes
=====================================
接收 GitHub webhook 事件，路由到自動回應處理器。
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging

from fastapi import APIRouter, Request, Header, HTTPException

logger = logging.getLogger("arcmind.github_webhook")
router = APIRouter()


def _verify_signature(payload: bytes, signature: str, secret: str) -> bool:
    """Verify GitHub webhook signature (HMAC-SHA256)."""
    if not secret:
        return True  # No secret configured, skip verification
    expected = "sha256=" + hmac.new(
        secret.encode(), payload, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


def _send_telegram(message: str) -> None:
    """Send notification via Telegram."""
    try:
        import urllib.request
        import urllib.parse
        from config.settings import settings

        token = settings.telegram_bot_token
        chat_id = settings.telegram_chat_id
        if not token or not chat_id:
            return

        if len(message) > 4000:
            message = message[:4000] + "\n...(truncated)"

        url = f"https://api.telegram.org/bot{token}/sendMessage"
        data = urllib.parse.urlencode({
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "HTML",
        }).encode()
        req = urllib.request.Request(url, data=data, method="POST")
        urllib.request.urlopen(req, timeout=15)
    except Exception as e:
        logger.warning("[GitHubWebhook] Telegram notify failed: %s", e)


# ── Event Handlers ───────────────────────────────────────────────────────────

def _handle_push(payload: dict) -> str:
    """Handle push event."""
    repo = payload.get("repository", {}).get("full_name", "?")
    ref = payload.get("ref", "").replace("refs/heads/", "")
    commits = payload.get("commits", [])
    pusher = payload.get("pusher", {}).get("name", "?")

    commit_lines = []
    for c in commits[:5]:
        sha = c.get("id", "")[:7]
        msg = c.get("message", "").split("\n")[0][:60]
        commit_lines.append(f"  • <code>{sha}</code> {msg}")

    text = (
        f"🔀 <b>Push to {repo}</b> ({ref})\n"
        f"By: {pusher} | {len(commits)} commit(s)\n"
    )
    if commit_lines:
        text += "\n".join(commit_lines)
    return text


def _handle_pull_request(payload: dict) -> str:
    """Handle pull_request event."""
    action = payload.get("action", "")
    pr = payload.get("pull_request", {})
    repo = payload.get("repository", {}).get("full_name", "?")
    title = pr.get("title", "")
    number = pr.get("number", "?")
    author = pr.get("user", {}).get("login", "?")
    url = pr.get("html_url", "")

    icon = {"opened": "🟢", "closed": "🔴", "merged": "🟣",
            "review_requested": "👀"}.get(action, "📋")

    text = (
        f"{icon} <b>PR #{number} {action}</b> in {repo}\n"
        f"<b>{title}</b>\n"
        f"By: {author}\n"
        f"{url}"
    )
    return text


def _handle_issues(payload: dict) -> str:
    """Handle issues event."""
    action = payload.get("action", "")
    issue = payload.get("issue", {})
    repo = payload.get("repository", {}).get("full_name", "?")
    title = issue.get("title", "")
    number = issue.get("number", "?")
    author = issue.get("user", {}).get("login", "?")
    url = issue.get("html_url", "")

    icon = {"opened": "🟢", "closed": "🔴", "labeled": "🏷"}.get(action, "📋")

    return (
        f"{icon} <b>Issue #{number} {action}</b> in {repo}\n"
        f"<b>{title}</b>\n"
        f"By: {author}\n"
        f"{url}"
    )


def _handle_workflow_run(payload: dict) -> str | None:
    """Handle workflow_run event (only notify on failure)."""
    action = payload.get("action", "")
    run = payload.get("workflow_run", {})

    if action != "completed":
        return None

    conclusion = run.get("conclusion", "")
    if conclusion == "success":
        return None  # Don't spam on success

    repo = payload.get("repository", {}).get("full_name", "?")
    name = run.get("name", "?")
    branch = run.get("head_branch", "?")
    url = run.get("html_url", "")

    icon = "❌" if conclusion == "failure" else "⚠️"
    return (
        f"{icon} <b>CI {conclusion}</b>: {name}\n"
        f"Repo: {repo} | Branch: {branch}\n"
        f"{url}"
    )


def _handle_release(payload: dict) -> str:
    """Handle release event."""
    action = payload.get("action", "")
    release = payload.get("release", {})
    repo = payload.get("repository", {}).get("full_name", "?")
    tag = release.get("tag_name", "?")
    name = release.get("name", tag)
    url = release.get("html_url", "")

    return (
        f"🚀 <b>Release {action}</b>: {name} ({tag})\n"
        f"Repo: {repo}\n"
        f"{url}"
    )


def _handle_issue_comment(payload: dict) -> str | None:
    """Handle issue_comment event."""
    action = payload.get("action", "")
    if action != "created":
        return None

    comment = payload.get("comment", {})
    issue = payload.get("issue", {})
    repo = payload.get("repository", {}).get("full_name", "?")
    author = comment.get("user", {}).get("login", "?")
    body = comment.get("body", "")[:200]
    number = issue.get("number", "?")
    is_pr = "pull_request" in issue
    kind = "PR" if is_pr else "Issue"

    return (
        f"💬 <b>Comment on {kind} #{number}</b> in {repo}\n"
        f"By: {author}\n"
        f"{body}"
    )


# ── Webhook Endpoint ─────────────────────────────────────────────────────────

_EVENT_HANDLERS = {
    "push": _handle_push,
    "pull_request": _handle_pull_request,
    "issues": _handle_issues,
    "workflow_run": _handle_workflow_run,
    "release": _handle_release,
    "issue_comment": _handle_issue_comment,
}


@router.post("/webhook")
async def github_webhook(
    request: Request,
    x_github_event: str = Header(None, alias="X-GitHub-Event"),
    x_hub_signature_256: str = Header(None, alias="X-Hub-Signature-256"),
):
    """Receive and process GitHub webhook events."""
    payload_bytes = await request.body()

    # Verify signature — fail-closed when secret is configured
    from config.settings import settings
    secret = getattr(settings, "github_webhook_secret", "")
    if secret:
        if not x_hub_signature_256:
            raise HTTPException(status_code=401, detail="Missing X-Hub-Signature-256 header")
        if not _verify_signature(payload_bytes, x_hub_signature_256, secret):
            raise HTTPException(status_code=401, detail="Invalid signature")

    # Handle ping
    if x_github_event == "ping":
        return {"status": "pong"}

    # Parse payload
    try:
        payload = json.loads(payload_bytes)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    logger.info("[GitHubWebhook] Received event: %s", x_github_event)

    # Route to handler
    handler = _EVENT_HANDLERS.get(x_github_event)
    if handler:
        try:
            message = handler(payload)
            if message:
                _send_telegram(message)
                return {"status": "notified", "event": x_github_event}
            return {"status": "skipped", "event": x_github_event}
        except Exception as e:
            logger.error("[GitHubWebhook] Handler error: %s", e)
            return {"status": "error", "error": str(e)}

    # Unknown event — log but don't fail
    logger.info("[GitHubWebhook] Unhandled event: %s", x_github_event)
    return {"status": "ignored", "event": x_github_event}
