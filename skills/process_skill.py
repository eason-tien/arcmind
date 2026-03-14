"""
Skill: process_skill
系統進程管理 — 列出/搜尋/終止進程 + 資源監控
"""
from __future__ import annotations
import logging, os, platform, subprocess, json
logger = logging.getLogger("arcmind.skill.process")

def _list_processes(inputs: dict) -> dict:
    sort_by = inputs.get("sort_by", "cpu")  # cpu | memory | pid
    limit = int(inputs.get("limit", 30))
    sort_flag = {
        "cpu": "-pcpu", "memory": "-pmem", "pid": "-pid"
    }.get(sort_by, "-pcpu")
    cmd = ["ps", "aux", f"--sort={sort_flag}"] if platform.system() == "Linux" else ["ps", "aux"]
    r = subprocess.run(cmd, capture_output=True, timeout=10)
    lines = r.stdout.decode("utf-8", errors="replace").strip().split("\n")
    header = lines[0] if lines else ""
    procs = []
    for line in lines[1:limit+1]:
        parts = line.split(None, 10)
        if len(parts) >= 11:
            procs.append({"user": parts[0], "pid": int(parts[1]), "cpu": float(parts[2]),
                          "mem": float(parts[3]), "command": parts[10][:200]})
    if sort_by == "cpu":
        procs.sort(key=lambda p: p["cpu"], reverse=True)
    elif sort_by == "memory":
        procs.sort(key=lambda p: p["mem"], reverse=True)
    return {"success": True, "processes": procs[:limit], "count": len(procs)}

def _search_processes(inputs: dict) -> dict:
    query = inputs.get("query", "")
    if not query:
        return {"success": False, "error": "query 為必填"}
    r = subprocess.run(["pgrep", "-aif", query], capture_output=True, timeout=10)
    lines = r.stdout.decode("utf-8", errors="replace").strip().split("\n")
    procs = []
    for line in lines:
        if line.strip():
            parts = line.split(None, 1)
            if parts:
                procs.append({"pid": int(parts[0]), "command": parts[1][:200] if len(parts) > 1 else ""})
    return {"success": True, "processes": procs, "count": len(procs)}

def _kill_process(inputs: dict) -> dict:
    pid = inputs.get("pid")
    signal = inputs.get("signal", "TERM")
    if not pid:
        return {"success": False, "error": "pid 為必填"}
    r = subprocess.run(["kill", f"-{signal}", str(pid)], capture_output=True, timeout=5)
    return {"success": r.returncode == 0, "pid": pid, "signal": signal,
            "error": r.stderr.decode().strip() if r.returncode != 0 else ""}

def _system_resources(inputs: dict) -> dict:
    info = {"platform": platform.system(), "machine": platform.machine()}
    try:
        info["cpu_count"] = os.cpu_count()
        load = os.getloadavg()
        info["load_avg"] = {"1m": load[0], "5m": load[1], "15m": load[2]}
    except Exception:
        pass
    if platform.system() == "Darwin":
        r = subprocess.run(["vm_stat"], capture_output=True, timeout=5)
        info["vm_stat"] = r.stdout.decode()[:500]
        r2 = subprocess.run(["df", "-h", "/"], capture_output=True, timeout=5)
        info["disk"] = r2.stdout.decode()[:300]
    else:
        try:
            info["memory"] = open("/proc/meminfo").read()[:500]
        except Exception:
            pass
    return {"success": True, **info}

def run(inputs: dict) -> dict:
    action = inputs.get("action", "list")
    handlers = {"list": _list_processes, "search": _search_processes,
                "kill": _kill_process, "resources": _system_resources}
    h = handlers.get(action)
    if not h:
        return {"success": False, "error": f"未知 action: {action}", "available_actions": list(handlers.keys())}
    try:
        return h(inputs)
    except Exception as e:
        logger.error("[process] %s failed: %s", action, e)
        return {"success": False, "error": str(e)}
