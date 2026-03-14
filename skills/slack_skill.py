"""
Skill: slack_skill
Slack 整合 — 訊息發送、頻道管理、歷史記錄

需要: pip install slack_sdk
Token: SLACK_BOT_TOKEN 環境變數
"""
from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger("arcmind.skill.slack")

_TOKEN = os.environ.get("SLACK_BOT_TOKEN", "")


def _get_client():
    """Get Slack WebClient."""
    try:
        from slack_sdk import WebClient
    except ImportError:
        raise RuntimeError("需要安裝 slack_sdk: pip install slack_sdk")
    if not _TOKEN:
        raise RuntimeError("SLACK_BOT_TOKEN 環境變數未設定")
    return WebClient(token=_TOKEN)


def _send_message(inputs: dict) -> dict:
    """Send a message to a Slack channel."""
    client = _get_client()
    channel = inputs.get("channel", "")
    text = inputs.get("text", "")
    thread_ts = inputs.get("thread_ts", "")

    if not channel or not text:
        return {"success": False, "error": "channel 和 text 為必填"}

    kwargs = {"channel": channel, "text": text}
    if thread_ts:
        kwargs["thread_ts"] = thread_ts

    resp = client.chat_postMessage(**kwargs)
    return {
        "success": True,
        "ts": resp.get("ts"),
        "channel": resp.get("channel"),
    }


def _list_channels(inputs: dict) -> dict:
    """List Slack channels."""
    client = _get_client()
    limit = int(inputs.get("limit", 50))
    types = inputs.get("types", "public_channel,private_channel")

    resp = client.conversations_list(types=types, limit=limit)
    channels = [
        {
            "id": c["id"],
            "name": c.get("name", ""),
            "topic": c.get("topic", {}).get("value", ""),
            "member_count": c.get("num_members", 0),
        }
        for c in resp.get("channels", [])
    ]

    return {"success": True, "channels": channels, "count": len(channels)}


def _read_history(inputs: dict) -> dict:
    """Read channel message history."""
    client = _get_client()
    channel = inputs.get("channel", "")
    limit = int(inputs.get("limit", 20))

    if not channel:
        return {"success": False, "error": "channel 為必填"}

    resp = client.conversations_history(channel=channel, limit=limit)
    messages = [
        {
            "ts": m.get("ts"),
            "user": m.get("user", ""),
            "text": m.get("text", "")[:500],
            "type": m.get("type"),
        }
        for m in resp.get("messages", [])
    ]

    return {"success": True, "messages": messages, "count": len(messages)}


def _react(inputs: dict) -> dict:
    """Add a reaction to a message."""
    client = _get_client()
    channel = inputs.get("channel", "")
    timestamp = inputs.get("timestamp", "")
    emoji = inputs.get("emoji", "thumbsup")

    if not channel or not timestamp:
        return {"success": False, "error": "channel 和 timestamp 為必填"}

    client.reactions_add(channel=channel, name=emoji, timestamp=timestamp)
    return {"success": True, "emoji": emoji}


def _upload_file(inputs: dict) -> dict:
    """Upload a file to Slack."""
    client = _get_client()
    channel = inputs.get("channel", "")
    file_path = inputs.get("file_path", "")
    title = inputs.get("title", "")
    comment = inputs.get("comment", "")

    if not channel or not file_path:
        return {"success": False, "error": "channel 和 file_path 為必填"}

    resp = client.files_upload_v2(
        channel=channel,
        file=file_path,
        title=title or file_path.split("/")[-1],
        initial_comment=comment,
    )
    return {"success": True, "file_id": resp.get("file", {}).get("id")}


def _search_messages(inputs: dict) -> dict:
    """Search messages across channels."""
    client = _get_client()
    query = inputs.get("query", "")
    count = int(inputs.get("count", 20))

    if not query:
        return {"success": False, "error": "query 為必填"}

    resp = client.search_messages(query=query, count=count)
    messages = resp.get("messages", {}).get("matches", [])
    results = [
        {
            "text": m.get("text", "")[:300],
            "user": m.get("username", ""),
            "channel": m.get("channel", {}).get("name", ""),
            "ts": m.get("ts"),
            "permalink": m.get("permalink", ""),
        }
        for m in messages
    ]

    return {"success": True, "results": results, "count": len(results)}


def run(inputs: dict) -> dict:
    """
    Slack skill entry point.

    inputs:
      action: send_message | list_channels | read_history | react |
              upload_file | search_messages
    """
    action = inputs.get("action", "list_channels")

    handlers = {
        "send_message": _send_message,
        "list_channels": _list_channels,
        "read_history": _read_history,
        "react": _react,
        "upload_file": _upload_file,
        "search_messages": _search_messages,
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
        logger.error("[slack] %s failed: %s", action, e)
        return {"success": False, "error": str(e), "action": action}
