"""
Skill: docker_skill
Docker 容器管理 — 透過 docker CLI
"""
from __future__ import annotations
import json, logging, subprocess
logger = logging.getLogger("arcmind.skill.docker")

def _run_docker(args: list[str], timeout: int = 30) -> tuple[bool, str]:
    r = subprocess.run(["docker"] + args, capture_output=True, timeout=timeout)
    out = r.stdout.decode("utf-8", errors="replace").strip()
    err = r.stderr.decode("utf-8", errors="replace").strip()
    return r.returncode == 0, out if r.returncode == 0 else err

def _list_containers(inputs: dict) -> dict:
    all_flag = inputs.get("all", True)
    args = ["ps", "--format", "{{json .}}"]
    if all_flag:
        args.insert(1, "-a")
    ok, out = _run_docker(args)
    if not ok:
        return {"success": False, "error": out}
    containers = [json.loads(line) for line in out.split("\n") if line.strip()]
    return {"success": True, "containers": containers, "count": len(containers)}

def _list_images(inputs: dict) -> dict:
    ok, out = _run_docker(["images", "--format", "{{json .}}"])
    if not ok:
        return {"success": False, "error": out}
    images = [json.loads(line) for line in out.split("\n") if line.strip()]
    return {"success": True, "images": images, "count": len(images)}

def _start(inputs: dict) -> dict:
    container = inputs.get("container", "")
    if not container:
        return {"success": False, "error": "container 為必填"}
    ok, out = _run_docker(["start", container])
    return {"success": ok, "container": container, "output": out}

def _stop(inputs: dict) -> dict:
    container = inputs.get("container", "")
    if not container:
        return {"success": False, "error": "container 為必填"}
    ok, out = _run_docker(["stop", container])
    return {"success": ok, "container": container, "output": out}

def _logs(inputs: dict) -> dict:
    container = inputs.get("container", "")
    tail = int(inputs.get("tail", 50))
    if not container:
        return {"success": False, "error": "container 為必填"}
    ok, out = _run_docker(["logs", "--tail", str(tail), container])
    return {"success": ok, "logs": out[:5000], "container": container}

def _exec_cmd(inputs: dict) -> dict:
    container = inputs.get("container", "")
    command = inputs.get("command", "")
    if not container or not command:
        return {"success": False, "error": "container 和 command 為必填"}
    ok, out = _run_docker(["exec", container] + command.split(), timeout=60)
    return {"success": ok, "output": out[:5000], "container": container}

def _run_container(inputs: dict) -> dict:
    image = inputs.get("image", "")
    name = inputs.get("name", "")
    ports = inputs.get("ports", [])  # ["8080:80"]
    envs = inputs.get("env", {})
    detach = inputs.get("detach", True)
    cmd = inputs.get("command", "")
    if not image:
        return {"success": False, "error": "image 為必填"}
    args = ["run"]
    if detach:
        args.append("-d")
    if name:
        args.extend(["--name", name])
    for p in ports:
        args.extend(["-p", p])
    for k, v in envs.items():
        args.extend(["-e", f"{k}={v}"])
    args.append(image)
    if cmd:
        args.extend(cmd.split())
    ok, out = _run_docker(args, timeout=120)
    return {"success": ok, "output": out[:500], "image": image}

def _stats(inputs: dict) -> dict:
    ok, out = _run_docker(["stats", "--no-stream", "--format", "{{json .}}"])
    if not ok:
        return {"success": False, "error": out}
    stats = [json.loads(line) for line in out.split("\n") if line.strip()]
    return {"success": True, "stats": stats, "count": len(stats)}

def run(inputs: dict) -> dict:
    action = inputs.get("action", "list_containers")
    handlers = {"list_containers": _list_containers, "list_images": _list_images,
                "start": _start, "stop": _stop, "logs": _logs, "exec": _exec_cmd,
                "run": _run_container, "stats": _stats}
    h = handlers.get(action)
    if not h:
        return {"success": False, "error": f"未知 action: {action}", "available_actions": list(handlers.keys())}
    try:
        return h(inputs)
    except Exception as e:
        logger.error("[docker] %s failed: %s", action, e)
        return {"success": False, "error": str(e)}
