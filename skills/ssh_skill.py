"""
Skill: ssh_skill
SSH 遠端執行 — 透過 subprocess ssh 命令或 paramiko

連線: host / user / port / key_file 參數
或 SSH config (~/.ssh/config) 別名
"""
from __future__ import annotations
import logging, os, subprocess
from pathlib import Path
logger = logging.getLogger("arcmind.skill.ssh")

def _build_ssh_cmd(inputs: dict) -> list[str]:
    host = inputs.get("host", "")
    user = inputs.get("user", "")
    port = int(inputs.get("port", 22))
    key_file = inputs.get("key_file", "")
    if not host:
        raise ValueError("host 為必填")
    cmd = ["ssh", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=10"]
    if port != 22:
        cmd.extend(["-p", str(port)])
    if key_file:
        cmd.extend(["-i", str(Path(key_file).expanduser())])
    target = f"{user}@{host}" if user else host
    cmd.append(target)
    return cmd

def _exec_command(inputs: dict) -> dict:
    command = inputs.get("command", "")
    if not command:
        return {"success": False, "error": "command 為必填"}
    timeout = int(inputs.get("timeout", 30))
    ssh_cmd = _build_ssh_cmd(inputs)
    ssh_cmd.append(command)
    r = subprocess.run(ssh_cmd, capture_output=True, timeout=timeout)
    return {
        "success": r.returncode == 0,
        "stdout": r.stdout.decode("utf-8", errors="replace")[:5000],
        "stderr": r.stderr.decode("utf-8", errors="replace")[:2000],
        "return_code": r.returncode,
        "host": inputs.get("host"),
    }

def _upload(inputs: dict) -> dict:
    local = inputs.get("local_path", "")
    remote = inputs.get("remote_path", "")
    if not local or not remote:
        return {"success": False, "error": "local_path 和 remote_path 為必填"}
    host = inputs.get("host", "")
    user = inputs.get("user", "")
    port = int(inputs.get("port", 22))
    key_file = inputs.get("key_file", "")
    cmd = ["scp", "-o", "StrictHostKeyChecking=no"]
    if port != 22:
        cmd.extend(["-P", str(port)])
    if key_file:
        cmd.extend(["-i", str(Path(key_file).expanduser())])
    target = f"{user}@{host}:{remote}" if user else f"{host}:{remote}"
    cmd.extend([local, target])
    r = subprocess.run(cmd, capture_output=True, timeout=120)
    return {"success": r.returncode == 0, "local": local, "remote": remote,
            "error": r.stderr.decode()[:500] if r.returncode != 0 else ""}

def _download(inputs: dict) -> dict:
    remote = inputs.get("remote_path", "")
    local = inputs.get("local_path", "")
    if not remote or not local:
        return {"success": False, "error": "remote_path 和 local_path 為必填"}
    host = inputs.get("host", "")
    user = inputs.get("user", "")
    port = int(inputs.get("port", 22))
    key_file = inputs.get("key_file", "")
    cmd = ["scp", "-o", "StrictHostKeyChecking=no"]
    if port != 22:
        cmd.extend(["-P", str(port)])
    if key_file:
        cmd.extend(["-i", str(Path(key_file).expanduser())])
    source = f"{user}@{host}:{remote}" if user else f"{host}:{remote}"
    Path(local).parent.mkdir(parents=True, exist_ok=True)
    cmd.extend([source, local])
    r = subprocess.run(cmd, capture_output=True, timeout=120)
    return {"success": r.returncode == 0, "remote": remote, "local": local,
            "error": r.stderr.decode()[:500] if r.returncode != 0 else ""}

def _test_connection(inputs: dict) -> dict:
    ssh_cmd = _build_ssh_cmd(inputs)
    ssh_cmd.append("echo ok")
    r = subprocess.run(ssh_cmd, capture_output=True, timeout=15)
    return {"success": r.returncode == 0, "host": inputs.get("host"),
            "error": r.stderr.decode()[:500] if r.returncode != 0 else ""}

def run(inputs: dict) -> dict:
    action = inputs.get("action", "exec")
    handlers = {"exec": _exec_command, "upload": _upload,
                "download": _download, "test": _test_connection}
    h = handlers.get(action)
    if not h:
        return {"success": False, "error": f"未知 action: {action}", "available_actions": list(handlers.keys())}
    try:
        return h(inputs)
    except Exception as e:
        logger.error("[ssh] %s failed: %s", action, e)
        return {"success": False, "error": str(e)}
