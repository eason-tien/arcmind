"""
Skill: cron_skill
CRON 排程管理介面 — 查看/新增/刪除/暫停 ArcMind 排程任務

讀取 ArcMind 的 runtime/cron.py 排程設定
"""
from __future__ import annotations
import json, logging, os
from pathlib import Path
logger = logging.getLogger("arcmind.skill.cron")
_CRON_FILE = Path(__file__).resolve().parent.parent / "config" / "cron_tasks.json"

def _load_tasks() -> list[dict]:
    if _CRON_FILE.exists():
        return json.loads(_CRON_FILE.read_text(encoding="utf-8"))
    return []

def _save_tasks(tasks: list[dict]) -> None:
    _CRON_FILE.parent.mkdir(parents=True, exist_ok=True)
    _CRON_FILE.write_text(json.dumps(tasks, ensure_ascii=False, indent=2), encoding="utf-8")

def _list_tasks(inputs: dict) -> dict:
    tasks = _load_tasks()
    active = [t for t in tasks if t.get("enabled", True)]
    return {"success": True, "tasks": tasks, "total": len(tasks), "active": len(active)}

def _add_task(inputs: dict) -> dict:
    name = inputs.get("name", "")
    schedule = inputs.get("schedule", "")  # cron expression: "0 8 * * *"
    skill = inputs.get("skill", "")
    skill_inputs = inputs.get("skill_inputs", {})
    description = inputs.get("description", "")
    if not name or not schedule or not skill:
        return {"success": False, "error": "name, schedule, skill 為必填"}
    tasks = _load_tasks()
    if any(t["name"] == name for t in tasks):
        return {"success": False, "error": f"任務 '{name}' 已存在"}
    task = {
        "name": name, "schedule": schedule, "skill": skill,
        "skill_inputs": skill_inputs, "description": description,
        "enabled": True,
    }
    tasks.append(task)
    _save_tasks(tasks)
    return {"success": True, "task": task, "total": len(tasks)}

def _remove_task(inputs: dict) -> dict:
    name = inputs.get("name", "")
    if not name:
        return {"success": False, "error": "name 為必填"}
    tasks = _load_tasks()
    original = len(tasks)
    tasks = [t for t in tasks if t["name"] != name]
    if len(tasks) == original:
        return {"success": False, "error": f"任務 '{name}' 不存在"}
    _save_tasks(tasks)
    return {"success": True, "removed": name, "remaining": len(tasks)}

def _toggle_task(inputs: dict) -> dict:
    name = inputs.get("name", "")
    enabled = inputs.get("enabled")
    if not name:
        return {"success": False, "error": "name 為必填"}
    tasks = _load_tasks()
    for t in tasks:
        if t["name"] == name:
            t["enabled"] = enabled if enabled is not None else not t.get("enabled", True)
            _save_tasks(tasks)
            return {"success": True, "name": name, "enabled": t["enabled"]}
    return {"success": False, "error": f"任務 '{name}' 不存在"}

def _update_task(inputs: dict) -> dict:
    name = inputs.get("name", "")
    if not name:
        return {"success": False, "error": "name 為必填"}
    tasks = _load_tasks()
    for t in tasks:
        if t["name"] == name:
            if "schedule" in inputs:
                t["schedule"] = inputs["schedule"]
            if "skill" in inputs:
                t["skill"] = inputs["skill"]
            if "skill_inputs" in inputs:
                t["skill_inputs"] = inputs["skill_inputs"]
            if "description" in inputs:
                t["description"] = inputs["description"]
            _save_tasks(tasks)
            return {"success": True, "task": t}
    return {"success": False, "error": f"任務 '{name}' 不存在"}

def run(inputs: dict) -> dict:
    action = inputs.get("action", "list")
    handlers = {"list": _list_tasks, "add": _add_task, "remove": _remove_task,
                "toggle": _toggle_task, "update": _update_task}
    h = handlers.get(action)
    if not h:
        return {"success": False, "error": f"未知 action: {action}", "available_actions": list(handlers.keys())}
    try:
        return h(inputs)
    except Exception as e:
        logger.error("[cron] %s failed: %s", action, e)
        return {"success": False, "error": str(e)}
