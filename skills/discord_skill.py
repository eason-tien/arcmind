"""
Skill: discord_skill
Discord Bot 整合 — 訊息發送、頻道管理、伺服器資訊

需要: pip install discord.py
Token: DISCORD_BOT_TOKEN 環境變數
"""
from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger("arcmind.skill.discord")

_TOKEN = os.environ.get("DISCORD_BOT_TOKEN", "")


def _api_request(method: str, endpoint: str, json_data: dict | None = None) -> dict:
    """Make a Discord API request."""
    if not _TOKEN:
        raise RuntimeError("DISCORD_BOT_TOKEN 環境變數未設定")

    try:
        import httpx
    except ImportError:
        raise RuntimeError("需要安裝 httpx: pip install httpx")

    url = f"https://discord.com/api/v10{endpoint}"
    headers = {"Authorization": f"Bot {_TOKEN}", "Content-Type": "application/json"}

    with httpx.Client(timeout=15) as client:
        if method == "GET":
            resp = client.get(url, headers=headers)
        elif method == "POST":
            resp = client.post(url, headers=headers, json=json_data or {})
        elif method == "DELETE":
            resp = client.delete(url, headers=headers)
        elif method == "PATCH":
            resp = client.patch(url, headers=headers, json=json_data or {})
        else:
            raise ValueError(f"Unsupported method: {method}")

    resp.raise_for_status()
    return resp.json() if resp.content else {}


def _send_message(inputs: dict) -> dict:
    """Send a message to a Discord channel."""
    channel_id = inputs.get("channel_id", "")
    content = inputs.get("content", "")
    embed = inputs.get("embed")

    if not channel_id or (not content and not embed):
        return {"success": False, "error": "channel_id 和 content/embed 為必填"}

    body = {}
    if content:
        body["content"] = content
    if embed:
        body["embeds"] = [embed] if isinstance(embed, dict) else embed

    result = _api_request("POST", f"/channels/{channel_id}/messages", body)
    return {"success": True, "message_id": result.get("id"), "channel_id": channel_id}


def _list_guilds(inputs: dict) -> dict:
    """List guilds (servers) the bot is in."""
    result = _api_request("GET", "/users/@me/guilds")
    guilds = [
        {"id": g["id"], "name": g["name"], "icon": g.get("icon"), "owner": g.get("owner", False)}
        for g in result
    ]
    return {"success": True, "guilds": guilds, "count": len(guilds)}


def _list_channels(inputs: dict) -> dict:
    """List channels in a guild."""
    guild_id = inputs.get("guild_id", "")
    if not guild_id:
        return {"success": False, "error": "guild_id 為必填"}

    result = _api_request("GET", f"/guilds/{guild_id}/channels")
    channels = [
        {
            "id": c["id"],
            "name": c.get("name", ""),
            "type": c.get("type"),
            "topic": c.get("topic", ""),
            "position": c.get("position", 0),
        }
        for c in result
        if c.get("type") in (0, 2, 5, 15)  # text, voice, announcement, forum
    ]
    return {"success": True, "channels": channels, "count": len(channels)}


def _read_history(inputs: dict) -> dict:
    """Read channel message history."""
    channel_id = inputs.get("channel_id", "")
    limit = int(inputs.get("limit", 20))

    if not channel_id:
        return {"success": False, "error": "channel_id 為必填"}

    result = _api_request("GET", f"/channels/{channel_id}/messages?limit={limit}")
    messages = [
        {
            "id": m["id"],
            "author": m.get("author", {}).get("username", ""),
            "content": m.get("content", "")[:500],
            "timestamp": m.get("timestamp", ""),
        }
        for m in result
    ]
    return {"success": True, "messages": messages, "count": len(messages)}


def _add_reaction(inputs: dict) -> dict:
    """Add a reaction to a message."""
    channel_id = inputs.get("channel_id", "")
    message_id = inputs.get("message_id", "")
    emoji = inputs.get("emoji", "👍")

    if not channel_id or not message_id:
        return {"success": False, "error": "channel_id 和 message_id 為必填"}

    import urllib.parse
    encoded = urllib.parse.quote(emoji)
    _api_request("PUT", f"/channels/{channel_id}/messages/{message_id}/reactions/{encoded}/@me")
    return {"success": True, "emoji": emoji}


def _get_guild_info(inputs: dict) -> dict:
    """Get detailed guild information."""
    guild_id = inputs.get("guild_id", "")
    if not guild_id:
        return {"success": False, "error": "guild_id 為必填"}

    result = _api_request("GET", f"/guilds/{guild_id}?with_counts=true")
    return {
        "success": True,
        "id": result["id"],
        "name": result["name"],
        "member_count": result.get("approximate_member_count", 0),
        "online_count": result.get("approximate_presence_count", 0),
        "description": result.get("description", ""),
        "owner_id": result.get("owner_id", ""),
    }


def run(inputs: dict) -> dict:
    """
    Discord skill entry point.

    inputs:
      action: send_message | list_guilds | list_channels | read_history |
              add_reaction | get_guild_info
    """
    action = inputs.get("action", "list_guilds")
    handlers = {
        "send_message": _send_message,
        "list_guilds": _list_guilds,
        "list_channels": _list_channels,
        "read_history": _read_history,
        "add_reaction": _add_reaction,
        "get_guild_info": _get_guild_info,
    }
    handler = handlers.get(action)
    if not handler:
        return {"success": False, "error": f"未知 action: {action}", "available_actions": list(handlers.keys())}
    try:
        return handler(inputs)
    except Exception as e:
        logger.error("[discord] %s failed: %s", action, e)
        return {"success": False, "error": str(e), "action": action}
