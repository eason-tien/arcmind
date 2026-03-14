"""
Skill: git_skill
本地 Git 操作 — status, log, diff, branch, commit, stash
(不是 GitHub API，是 git CLI)
"""
from __future__ import annotations
import logging, subprocess
from pathlib import Path
logger = logging.getLogger("arcmind.skill.git")

def _git(args: list[str], cwd: str = "", timeout: int = 30) -> tuple[bool, str]:
    cmd = ["git"] + args
    r = subprocess.run(cmd, capture_output=True, timeout=timeout, cwd=cwd or None)
    out = r.stdout.decode("utf-8", errors="replace").strip()
    err = r.stderr.decode("utf-8", errors="replace").strip()
    return r.returncode == 0, out if r.returncode == 0 else (err or out)

def _status(inputs: dict) -> dict:
    cwd = inputs.get("repo_path", "")
    ok, out = _git(["status", "--porcelain", "-b"], cwd)
    if not ok:
        return {"success": False, "error": out}
    lines = out.split("\n")
    branch = lines[0].replace("## ", "") if lines else ""
    changes = [l for l in lines[1:] if l.strip()]
    return {"success": True, "branch": branch, "changes": changes, "clean": len(changes) == 0}

def _log(inputs: dict) -> dict:
    cwd = inputs.get("repo_path", "")
    n = int(inputs.get("limit", 10))
    fmt = inputs.get("format", "%h|%an|%ar|%s")
    ok, out = _git(["log", f"-{n}", f"--pretty=format:{fmt}"], cwd)
    if not ok:
        return {"success": False, "error": out}
    commits = []
    for line in out.split("\n"):
        parts = line.split("|", 3)
        if len(parts) >= 4:
            commits.append({"hash": parts[0], "author": parts[1], "date": parts[2], "message": parts[3]})
    return {"success": True, "commits": commits, "count": len(commits)}

def _diff(inputs: dict) -> dict:
    cwd = inputs.get("repo_path", "")
    staged = inputs.get("staged", False)
    file_path = inputs.get("file", "")
    args = ["diff", "--stat"]
    if staged:
        args.append("--cached")
    if file_path:
        args.extend(["--", file_path])
    ok, out = _git(args, cwd)
    # Also get full diff (limited)
    args2 = ["diff"]
    if staged:
        args2.append("--cached")
    if file_path:
        args2.extend(["--", file_path])
    _, full_diff = _git(args2, cwd)
    return {"success": ok, "stat": out, "diff": full_diff[:5000]}

def _branch(inputs: dict) -> dict:
    cwd = inputs.get("repo_path", "")
    ok, out = _git(["branch", "-a", "--format=%(refname:short) %(objectname:short) %(upstream:short)"], cwd)
    if not ok:
        return {"success": False, "error": out}
    branches = []
    for line in out.split("\n"):
        parts = line.split()
        if parts:
            branches.append({"name": parts[0], "hash": parts[1] if len(parts) > 1 else "",
                            "upstream": parts[2] if len(parts) > 2 else ""})
    # current branch
    _, current = _git(["branch", "--show-current"], cwd)
    return {"success": True, "current": current, "branches": branches}

def _commit(inputs: dict) -> dict:
    cwd = inputs.get("repo_path", "")
    message = inputs.get("message", "")
    add_all = inputs.get("add_all", False)
    if not message:
        return {"success": False, "error": "message 為必填"}
    if add_all:
        _git(["add", "-A"], cwd)
    ok, out = _git(["commit", "-m", message], cwd)
    return {"success": ok, "output": out[:2000]}

def _stash(inputs: dict) -> dict:
    cwd = inputs.get("repo_path", "")
    sub_action = inputs.get("sub_action", "list")
    if sub_action == "list":
        ok, out = _git(["stash", "list"], cwd)
        return {"success": ok, "stashes": out.split("\n") if out else []}
    elif sub_action == "push":
        msg = inputs.get("message", "")
        args = ["stash", "push"]
        if msg:
            args.extend(["-m", msg])
        ok, out = _git(args, cwd)
        return {"success": ok, "output": out}
    elif sub_action == "pop":
        ok, out = _git(["stash", "pop"], cwd)
        return {"success": ok, "output": out}
    return {"success": False, "error": f"未知 sub_action: {sub_action}"}

def _checkout(inputs: dict) -> dict:
    cwd = inputs.get("repo_path", "")
    target = inputs.get("target", "")
    create = inputs.get("create", False)
    if not target:
        return {"success": False, "error": "target 為必填"}
    args = ["checkout"]
    if create:
        args.append("-b")
    args.append(target)
    ok, out = _git(args, cwd)
    return {"success": ok, "output": out, "target": target}

def run(inputs: dict) -> dict:
    action = inputs.get("action", "status")
    handlers = {"status": _status, "log": _log, "diff": _diff, "branch": _branch,
                "commit": _commit, "stash": _stash, "checkout": _checkout}
    h = handlers.get(action)
    if not h:
        return {"success": False, "error": f"未知 action: {action}", "available_actions": list(handlers.keys())}
    try:
        return h(inputs)
    except Exception as e:
        logger.error("[git] %s failed: %s", action, e)
        return {"success": False, "error": str(e)}
