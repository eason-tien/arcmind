"""
Skill: screenshot_skill
螢幕截圖 — macOS screencapture / Linux import/scrot
"""
from __future__ import annotations

import logging
import platform
import subprocess
import time
from pathlib import Path

logger = logging.getLogger("arcmind.skill.screenshot")
_OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data" / "screenshots"


def _capture(inputs: dict) -> dict:
    """Take a screenshot."""
    mode = inputs.get("mode", "full")
    delay = int(inputs.get("delay", 0))
    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"screen_{int(time.time())}.png"
    out_path = _OUTPUT_DIR / filename

    system = platform.system()
    if system == "Darwin":
        cmd = ["screencapture"]
        if mode == "window":
            cmd.append("-w")
        elif mode == "area":
            cmd.append("-s")
        elif mode == "clipboard":
            cmd.append("-c")
        if delay > 0:
            cmd.extend(["-T", str(delay)])
        if mode != "clipboard":
            cmd.append(str(out_path))
        result = subprocess.run(cmd, capture_output=True, timeout=30)
        if result.returncode != 0:
            return {"success": False, "error": result.stderr.decode()}
        if mode == "clipboard":
            return {"success": True, "mode": "clipboard"}
    elif system == "Linux":
        for tool_cmd in [
            ["scrot", str(out_path)] + (["-s"] if mode == "area" else []),
            ["gnome-screenshot", "-f", str(out_path)],
        ]:
            try:
                subprocess.run(tool_cmd, capture_output=True, timeout=30, check=True)
                break
            except (subprocess.CalledProcessError, FileNotFoundError):
                continue
    else:
        return {"success": False, "error": f"不支援: {system}"}

    if out_path.exists():
        return {"success": True, "path": str(out_path), "mode": mode, "size": out_path.stat().st_size}
    return {"success": False, "error": "截圖檔案未生成"}


def _list_screenshots(inputs: dict) -> dict:
    max_results = int(inputs.get("max_results", 20))
    if not _OUTPUT_DIR.exists():
        return {"success": True, "screenshots": [], "count": 0}
    files = sorted(_OUTPUT_DIR.glob("*.png"), key=lambda p: p.stat().st_mtime, reverse=True)
    items = [{"path": str(f), "name": f.name, "size": f.stat().st_size} for f in files[:max_results]]
    return {"success": True, "screenshots": items, "count": len(items)}


def run(inputs: dict) -> dict:
    """
    Screenshot skill. action: capture | list
    mode: full | window | area | clipboard
    """
    action = inputs.get("action", "capture")
    handlers = {"capture": _capture, "list": _list_screenshots}
    handler = handlers.get(action)
    if not handler:
        return {"success": False, "error": f"未知 action: {action}", "available_actions": list(handlers.keys())}
    try:
        return handler(inputs)
    except Exception as e:
        logger.error("[screenshot] %s failed: %s", action, e)
        return {"success": False, "error": str(e), "action": action}
