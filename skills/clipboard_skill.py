"""
Skill: clipboard_skill
系統剪貼簿操作 — 讀取/寫入/歷史

macOS: pbcopy / pbpaste
Linux: xclip / xsel
"""
from __future__ import annotations

import logging
import platform
import subprocess
import time
from typing import Any

logger = logging.getLogger("arcmind.skill.clipboard")

_HISTORY: list[dict] = []  # In-memory clipboard history
_MAX_HISTORY = 50


def _get_clipboard() -> str:
    """Read current clipboard content."""
    system = platform.system()
    try:
        if system == "Darwin":
            result = subprocess.run(["pbpaste"], capture_output=True, timeout=5)
            return result.stdout.decode("utf-8", errors="replace")
        elif system == "Linux":
            # Try xclip first, then xsel
            for cmd in [["xclip", "-selection", "clipboard", "-o"], ["xsel", "--clipboard", "--output"]]:
                try:
                    result = subprocess.run(cmd, capture_output=True, timeout=5)
                    if result.returncode == 0:
                        return result.stdout.decode("utf-8", errors="replace")
                except FileNotFoundError:
                    continue
            raise RuntimeError("xclip 或 xsel 未安裝")
        else:
            raise RuntimeError(f"不支援的系統: {system}")
    except subprocess.TimeoutExpired:
        raise RuntimeError("剪貼簿讀取超時")


def _set_clipboard(text: str) -> None:
    """Write text to clipboard."""
    system = platform.system()
    try:
        if system == "Darwin":
            subprocess.run(["pbcopy"], input=text.encode("utf-8"), timeout=5, check=True)
        elif system == "Linux":
            for cmd in [["xclip", "-selection", "clipboard"], ["xsel", "--clipboard", "--input"]]:
                try:
                    subprocess.run(cmd, input=text.encode("utf-8"), timeout=5, check=True)
                    return
                except FileNotFoundError:
                    continue
            raise RuntimeError("xclip 或 xsel 未安裝")
        else:
            raise RuntimeError(f"不支援的系統: {system}")
    except subprocess.TimeoutExpired:
        raise RuntimeError("剪貼簿寫入超時")


def _read(inputs: dict) -> dict:
    """Read clipboard content."""
    content = _get_clipboard()
    return {
        "success": True,
        "content": content[:10000],
        "length": len(content),
        "truncated": len(content) > 10000,
    }


def _write(inputs: dict) -> dict:
    """Write to clipboard."""
    text = inputs.get("text", "")
    if not text:
        return {"success": False, "error": "text 為必填"}

    # Save to history before overwriting
    try:
        current = _get_clipboard()
        if current:
            _HISTORY.insert(0, {"content": current[:500], "time": time.time()})
            if len(_HISTORY) > _MAX_HISTORY:
                _HISTORY.pop()
    except Exception:
        pass

    _set_clipboard(text)
    return {"success": True, "written_length": len(text)}


def _history(inputs: dict) -> dict:
    """Get clipboard history (in-memory, current session only)."""
    limit = int(inputs.get("limit", 10))
    items = _HISTORY[:limit]
    return {"success": True, "history": items, "count": len(items), "total": len(_HISTORY)}


def _clear(inputs: dict) -> dict:
    """Clear clipboard."""
    _set_clipboard("")
    return {"success": True}


def _append(inputs: dict) -> dict:
    """Append text to current clipboard content."""
    text = inputs.get("text", "")
    separator = inputs.get("separator", "\n")

    if not text:
        return {"success": False, "error": "text 為必填"}

    current = _get_clipboard()
    new_content = current + separator + text if current else text
    _set_clipboard(new_content)

    return {"success": True, "total_length": len(new_content)}


def run(inputs: dict) -> dict:
    """
    Clipboard skill entry point.

    inputs:
      action: read | write | history | clear | append
      text: str (write/append 時必填)
      separator: str (append 時可選, 預設 \\n)
    """
    action = inputs.get("action", "read")
    handlers = {
        "read": _read,
        "write": _write,
        "history": _history,
        "clear": _clear,
        "append": _append,
    }
    handler = handlers.get(action)
    if not handler:
        return {"success": False, "error": f"未知 action: {action}", "available_actions": list(handlers.keys())}
    try:
        return handler(inputs)
    except Exception as e:
        logger.error("[clipboard] %s failed: %s", action, e)
        return {"success": False, "error": str(e), "action": action}
