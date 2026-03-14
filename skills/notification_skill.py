"""
Skill: notification_skill
系統通知 — macOS osascript / Linux notify-send
"""
from __future__ import annotations
import logging, platform, subprocess
logger = logging.getLogger("arcmind.skill.notification")

def _notify(inputs: dict) -> dict:
    title = inputs.get("title", "ArcMind")
    message = inputs.get("message", "")
    subtitle = inputs.get("subtitle", "")
    sound = inputs.get("sound", "default")
    if not message:
        return {"success": False, "error": "message 為必填"}
    system = platform.system()
    if system == "Darwin":
        script = f'display notification "{message}"'
        if title:
            script += f' with title "{title}"'
        if subtitle:
            script += f' subtitle "{subtitle}"'
        if sound and sound != "none":
            script += f' sound name "{sound}"'
        r = subprocess.run(["osascript", "-e", script], capture_output=True, timeout=5)
        return {"success": r.returncode == 0, "platform": "macOS",
                "error": r.stderr.decode().strip() if r.returncode != 0 else ""}
    elif system == "Linux":
        cmd = ["notify-send"]
        if title:
            cmd.append(title)
        cmd.append(message)
        r = subprocess.run(cmd, capture_output=True, timeout=5)
        return {"success": r.returncode == 0, "platform": "Linux",
                "error": r.stderr.decode().strip() if r.returncode != 0 else ""}
    return {"success": False, "error": f"不支援: {system}"}

def _say(inputs: dict) -> dict:
    text = inputs.get("text", "")
    voice = inputs.get("voice", "")
    rate = inputs.get("rate", "")
    if not text:
        return {"success": False, "error": "text 為必填"}
    if platform.system() != "Darwin":
        return {"success": False, "error": "say 只支援 macOS"}
    cmd = ["say"]
    if voice:
        cmd.extend(["-v", voice])
    if rate:
        cmd.extend(["-r", str(rate)])
    cmd.append(text[:500])
    r = subprocess.run(cmd, capture_output=True, timeout=30)
    return {"success": r.returncode == 0}

def _dialog(inputs: dict) -> dict:
    message = inputs.get("message", "")
    title = inputs.get("title", "ArcMind")
    buttons = inputs.get("buttons", ["OK"])
    if not message:
        return {"success": False, "error": "message 為必填"}
    if platform.system() != "Darwin":
        return {"success": False, "error": "dialog 只支援 macOS"}
    btn_str = ", ".join(f'"{b}"' for b in buttons[:3])
    script = f'display dialog "{message}" with title "{title}" buttons {{{btn_str}}}'
    r = subprocess.run(["osascript", "-e", script], capture_output=True, timeout=60)
    output = r.stdout.decode().strip()
    clicked = output.split(":")[-1] if ":" in output else output
    return {"success": r.returncode == 0, "clicked": clicked.strip()}

def run(inputs: dict) -> dict:
    action = inputs.get("action", "notify")
    handlers = {"notify": _notify, "say": _say, "dialog": _dialog}
    h = handlers.get(action)
    if not h:
        return {"success": False, "error": f"未知 action: {action}", "available_actions": list(handlers.keys())}
    try:
        return h(inputs)
    except Exception as e:
        logger.error("[notification] %s failed: %s", action, e)
        return {"success": False, "error": str(e)}
