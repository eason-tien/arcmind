"""
ArcMind Auto-Updater
從 GitHub 檢查並自動拉取最新版本。
"""
import os
import json
import logging
import subprocess
from pathlib import Path
from datetime import datetime

logger = logging.getLogger("arcmind.updater")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
VERSION_FILE = PROJECT_ROOT / "VERSION"
GITHUB_REPO = "eason-tien/arcmind"
UPDATE_CHECK_FILE = PROJECT_ROOT / "data" / ".last_update_check"


def get_local_version() -> str:
    """讀取本地版本號"""
    try:
        return VERSION_FILE.read_text().strip()
    except FileNotFoundError:
        return "0.0.0"


def get_remote_version() -> str | None:
    """從 GitHub API 取得最新版本"""
    try:
        result = subprocess.run(
            ["curl", "-s", f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            tag = data.get("tag_name", "")
            return tag.lstrip("v") if tag else None
    except Exception as e:
        logger.warning(f"[Updater] Failed to check remote version: {e}")
    return None


def check_for_update() -> dict:
    """
    檢查是否有新版本。
    
    Returns:
        {
            "local_version": "0.3.0",
            "remote_version": "0.3.1",
            "update_available": True,
            "release_url": "https://github.com/..."
        }
    """
    local = get_local_version()
    remote = get_remote_version()
    
    result = {
        "local_version": local,
        "remote_version": remote,
        "update_available": False,
        "checked_at": datetime.now().isoformat(),
    }
    
    if remote and remote != local:
        # 簡易版本比較
        try:
            local_parts = [int(x) for x in local.split(".")]
            remote_parts = [int(x) for x in remote.split(".")]
            if remote_parts > local_parts:
                result["update_available"] = True
                result["release_url"] = f"https://github.com/{GITHUB_REPO}/releases/latest"
        except ValueError:
            pass
    
    # 記錄檢查時間
    try:
        UPDATE_CHECK_FILE.parent.mkdir(parents=True, exist_ok=True)
        UPDATE_CHECK_FILE.write_text(json.dumps(result, indent=2))
    except Exception:
        pass
    
    return result


def pull_update(force: bool = False) -> dict:
    """
    從 GitHub 拉取最新代碼。
    
    Args:
        force: 是否強制更新（覆蓋本地修改）
    
    Returns:
        {"success": bool, "message": str, "old_version": str, "new_version": str}
    """
    old_version = get_local_version()
    
    try:
        # 確保在 git repo 中
        git_dir = PROJECT_ROOT / ".git"
        if not git_dir.exists():
            return {"success": False, "message": "Not a git repository", 
                    "old_version": old_version, "new_version": old_version}
        
        # Stash 本地修改
        subprocess.run(
            ["git", "stash", "--include-untracked"],
            cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=30
        )
        
        # Git pull
        if force:
            subprocess.run(
                ["git", "fetch", "origin", "main"],
                cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=30
            )
            result = subprocess.run(
                ["git", "reset", "--hard", "origin/main"],
                cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=30
            )
        else:
            result = subprocess.run(
                ["git", "pull", "origin", "main"],
                cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=30
            )
        
        new_version = get_local_version()
        
        if result.returncode == 0:
            logger.info(f"[Updater] Updated: {old_version} → {new_version}")
            return {
                "success": True,
                "message": f"Updated {old_version} → {new_version}" if old_version != new_version else "Already up to date",
                "old_version": old_version,
                "new_version": new_version,
                "git_output": result.stdout.strip(),
            }
        else:
            return {
                "success": False,
                "message": f"Git pull failed: {result.stderr.strip()}",
                "old_version": old_version,
                "new_version": old_version,
            }
            
    except subprocess.TimeoutExpired:
        return {"success": False, "message": "Git pull timed out",
                "old_version": old_version, "new_version": old_version}
    except Exception as e:
        return {"success": False, "message": str(e),
                "old_version": old_version, "new_version": old_version}


# Tool 介面（供 OODA tool_loop 調用）
def run(inputs: dict) -> dict:
    """
    Auto-updater tool interface.
    
    inputs:
      - action: "check" | "update" | "force_update" | "version"
    """
    action = inputs.get("action", "check")
    
    if action == "version":
        return {"version": get_local_version()}
    elif action == "check":
        return check_for_update()
    elif action == "update":
        return pull_update(force=False)
    elif action == "force_update":
        return pull_update(force=True)
    else:
        return {"error": f"Unknown action: {action}"}
