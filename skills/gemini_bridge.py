"""
Skill: gemini_bridge
ArcMind 与 antigravity/gemini CLI 的整合桥接。
支持直接调用和文件信箱两种模式。
"""
from __future__ import annotations

import json
import os
import subprocess
import uuid
from pathlib import Path
from datetime import datetime

# Bridge 目录（相对于项目根目录）
PROJECT_ROOT = Path(__file__).resolve().parent.parent
BRIDGE_DIR = PROJECT_ROOT / ".agents" / "bridge"
INBOX_DIR = BRIDGE_DIR / "inbox"
OUTBOX_DIR = BRIDGE_DIR / "outbox"


def _ensure_dirs():
    """确保目录存在"""
    INBOX_DIR.mkdir(parents=True, exist_ok=True)
    OUTBOX_DIR.mkdir(parents=True, exist_ok=True)


def _find_gemini_cmd() -> list[str] | None:
    """查找 gemini CLI 命令，返回命令列表（用于 subprocess）"""
    # 1. 直接检查 PATH
    for cmd_name in ["gemini", "gemini-cli"]:
        try:
            result = subprocess.run(
                ["which", cmd_name], capture_output=True, text=True
            )
            if result.returncode == 0:
                return [cmd_name]
        except Exception:
            pass
    
    # 2. 检查常见安装位置
    common_paths = [
        Path.home() / ".local" / "bin" / "gemini",
        Path("/opt/homebrew/bin/gemini"),
        Path("/usr/local/bin/gemini"),
    ]
    for p in common_paths:
        if p.exists():
            return [str(p)]
    
    # 3. Fallback: npx @google/gemini-cli
    try:
        result = subprocess.run(
            ["which", "npx"], capture_output=True, text=True
        )
        if result.returncode == 0:
            return ["npx", "-y", "@google/gemini-cli"]
    except Exception:
        pass
    
    return None


def run(inputs: dict) -> dict:
    """
    调用 gemini CLI 执行任务。
    
    inputs:
      - task: 任务描述（字符串）
      - cwd: 工作目录（可选，默认当前目录）
      - timeout: 超时秒数（默认 600）
      - mode: "direct"（直接调用）或 "filebox"（文件信箱）
      - task_id: 任务ID（filebox 模式用）
    
    returns:
      - stdout: 标准输出
      - stderr: 标准错误
      - exit_code: 退出码
      - task_id: 任务ID
      - mode: 使用的模式
    """
    task = inputs.get("task", "").strip()
    cwd = inputs.get("cwd", os.getcwd())
    timeout = int(inputs.get("timeout", 600))
    mode = inputs.get("mode", "direct")
    task_id = inputs.get("task_id", str(uuid.uuid4())[:8])
    
    if not task:
        return {"error": "task is required", "stdout": "", "stderr": "", "exit_code": -1}
    
    # 查找 gemini 命令
    gemini_cmd = _find_gemini_cmd()
    if not gemini_cmd:
        return {
            "error": "gemini CLI not found. Please install antigravity gemini first.",
            "stdout": "", "stderr": "", "exit_code": -1,
        }
    
    _ensure_dirs()
    
    # 记录任务到 inbox（可选，用于审计）
    inbox_file = INBOX_DIR / f"{task_id}.json"
    inbox_file.write_text(json.dumps({
        "task": task,
        "status": "sent",
        "timestamp": datetime.now().isoformat(),
        "cwd": cwd,
    }, ensure_ascii=False, indent=2))
    
    try:
        # gemini_cmd 是一个列表，例如 ["gemini"] 或 ["npx", "-y", "@google/gemini-cli"]
        cmd = gemini_cmd + ["-p", task]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=timeout,
            env=os.environ.copy(),
        )
        
        output = {
            "stdout": result.stdout,
            "stderr": result.stderr,
            "exit_code": result.returncode,
            "task_id": task_id,
            "mode": mode,
        }
        
        # 写入结果到 outbox
        outbox_file = OUTBOX_DIR / f"{task_id}.json"
        outbox_file.write_text(json.dumps({
            **output,
            "status": "completed" if result.returncode == 0 else "failed",
            "timestamp": datetime.now().isoformat(),
        }, ensure_ascii=False, indent=2))
        
        return output
        
    except subprocess.TimeoutExpired:
        error = f"Execution timeout ({timeout}s)"
        outbox_file = OUTBOX_DIR / f"{task_id}.json"
        outbox_file.write_text(json.dumps({
            "stdout": "",
            "stderr": error,
            "exit_code": -1,
            "task_id": task_id,
            "mode": mode,
            "status": "timeout",
            "timestamp": datetime.now().isoformat(),
        }, ensure_ascii=False, indent=2))
        
        return {"error": error, "stdout": "", "stderr": error, "exit_code": -1, "task_id": task_id}
        
    except FileNotFoundError:
        return {
            "error": f"gemini command not found at: {gemini_cmd}",
            "stdout": "", "stderr": "Command not found", "exit_code": -1,
        }
    except Exception as e:
        return {"error": str(e), "stdout": "", "stderr": str(e), "exit_code": -1, "task_id": task_id}


def check_status(task_id: str) -> dict:
    """
    检查任务状态（filebox 模式）。
    
    args:
      - task_id: 任务ID
    
    returns:
      - status: "pending" | "completed" | "failed" | "timeout" | "not_found"
      - result: 结果数据（如果完成）
    """
    outbox_file = OUTBOX_DIR / f"{task_id}.json"
    
    if not outbox_file.exists():
        # 检查 inbox（可能还在处理中）
        inbox_file = INBOX_DIR / f"{task_id}.json"
        if inbox_file.exists():
            return {"status": "pending", "task_id": task_id}
        return {"status": "not_found", "task_id": task_id}
    
    try:
        data = json.loads(outbox_file.read_text(encoding="utf-8"))
        return {
            "status": data.get("status", "unknown"),
            "result": data,
            "task_id": task_id,
        }
    except Exception as e:
        return {"status": "error", "error": str(e), "task_id": task_id}


# 便捷函数：用于 ArcMind 直接调用
def delegate(task: str, cwd: str = None, timeout: int = 600) -> dict:
    """ArcMind 调用 gemini 的简单接口"""
    return run({
        "task": task,
        "cwd": cwd or os.getcwd(),
        "timeout": timeout,
        "mode": "direct",
    })
