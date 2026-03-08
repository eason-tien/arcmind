"""
Antigravity Bridge - 通过文件系统控制 Antigravity 桌面应用

工作原理:
1. 找到最新的 brain 目录
2. 写入 task.md
3. 轮询等待 task.md.resolved
4. 读取结果返回

优势: 完全本地操作，无 API 调用，零封号风险
"""

import time
import uuid
from pathlib import Path
from typing import Optional
import threading

# Antigravity 目录
ANTIGRAVITY_DIR = Path("~/.gemini/antigravity").expanduser()
BRAIN_DIR = ANTIGRAVITY_DIR / "brain"

# 默认轮询配置
DEFAULT_TIMEOUT = 300  # 5分钟
POLL_INTERVAL = 1.0    # 1秒轮询一次


def _find_latest_brain_dir() -> Optional[Path]:
    """找到最近使用的 brain 目录"""
    if not BRAIN_DIR.exists():
        return None
    
    # 获取所有对话目录，按修改时间排序
    dirs = [d for d in BRAIN_DIR.iterdir() if d.is_dir()]
    if not dirs:
        return None
    
    # 返回最新修改的目录
    return max(dirs, key=lambda d: d.stat().st_mtime)


def _get_or_create_brain_dir(conversation_id: Optional[str] = None) -> Path:
    """获取或创建 brain 目录"""
    if conversation_id:
        brain_dir = BRAIN_DIR / conversation_id
    else:
        brain_dir = _find_latest_brain_dir()
        
    if not brain_dir:
        # 创建新目录
        brain_dir = BRAIN_DIR / str(uuid.uuid4())
    
    brain_dir.mkdir(parents=True, exist_ok=True)
    return brain_dir


def _wait_for_resolved(brain_dir: Path, marker: str, timeout: int) -> Optional[str]:
    """等待 task.md.resolved 文件出现并返回内容"""
    task_file = brain_dir / "task.md"
    resolved_file = brain_dir / "task.md.resolved"
    
    start_time = time.time()
    last_resolved_size = 0
    
    while time.time() - start_time < timeout:
        # 检查 task.md 是否被处理（文件时间戳变化）
        if task_file.exists():
            task_mtime = task_file.stat().st_mtime
        
        # 检查 resolved 文件
        if resolved_file.exists():
            current_size = resolved_file.stat().st_size
            
            # 检测文件变化（新内容）
            if current_size > last_resolved_size:
                time.sleep(0.5)  # 等待写入完成
                content = resolved_file.read_text()
                if content.strip():
                    return content
                
                last_resolved_size = current_size
        
        time.sleep(POLL_INTERVAL)
    
    return None


def run(inputs: dict) -> str:
    """
    通过文件系统控制 Antigravity
    
    Args:
        inputs: {
            "task": "任务描述",
            "conversation_id": "可选，指定对话ID",
            "timeout": 300  # 可选，超时秒数
        }
    
    Returns:
        Antigravity 的处理结果
    """
    task = inputs.get("task", "")
    conversation_id = inputs.get("conversation_id")
    timeout = inputs.get("timeout", DEFAULT_TIMEOUT)
    
    if not task:
        return "错误: 任务描述不能为空"
    
    # 获取 brain 目录
    brain_dir = _get_or_create_brain_dir(conversation_id)
    
    # 写入任务
    task_file = brain_dir / "task.md"
    task_file.write_text(task)
    
    print(f"📝 任务已写入: {task_file}")
    print(f"⏳ 等待 Antigravity 处理...")
    
    # 等待结果
    result = _wait_for_resolved(brain_dir, "task.md", timeout)
    
    if result:
        print(f"✅ 收到结果 ({len(result)} 字符)")
        return result
    else:
        return f"⚠️ 超时未收到结果，请检查 Antigravity 是否正在运行"


def get_conversations() -> list:
    """获取所有对话列表"""
    if not BRAIN_DIR.exists():
        return []
    
    conversations = []
    for d in BRAIN_DIR.iterdir():
        if d.is_dir():
            # 检查是否有 task.md
            has_task = (d / "task.md").exists()
            conversations.append({
                "id": d.name,
                "path": str(d),
                "has_task": has_task,
                "modified": d.stat().st_mtime
            })
    
    # 按修改时间排序
    conversations.sort(key=lambda x: x["modified"], reverse=True)
    return conversations


def read_conversation(conversation_id: str) -> dict:
    """读取指定对话的内容"""
    brain_dir = BRAIN_DIR / conversation_id
    
    if not brain_dir.exists():
        return {"error": "对话不存在"}
    
    result = {
        "conversation_id": conversation_id,
        "path": str(brain_dir),
    }
    
    # 读取任务
    task_file = brain_dir / "task.md"
    if task_file.exists():
        result["task"] = task_file.read_text()
    
    # 读取结果
    resolved_file = brain_dir / "task.md.resolved"
    if resolved_file.exists():
        result["resolved"] = resolved_file.read_text()
    
    # 读取所有历史版本
    history = []
    for f in sorted(brain_dir.glob("task.md.resolved.*")):
        history.append({
            "version": f.name,
            "content": f.read_text()[:500]  # 只取前500字符
        })
    result["history"] = history
    
    return result


def check_status() -> dict:
    """检查 Antigravity 状态"""
    status = {
        "running": False,
        "latest_conversation": None,
        "brain_dir_exists": BRAIN_DIR.exists(),
    }
    
    # 检查进程
    import subprocess
    result = subprocess.run(
        ["ps", "aux"],
        capture_output=True,
        text=True
    )
    
    if "antigravity" in result.stdout.lower():
        status["running"] = True
    
    # 获取最新对话
    latest = _find_latest_brain_dir()
    if latest:
        status["latest_conversation"] = latest.name
        status["latest_path"] = str(latest)
        
        # 检查当前任务状态
        task_file = latest / "task.md"
        resolved_file = latest / "task.md.resolved"
        
        status["has_pending_task"] = task_file.exists()
        status["has_result"] = resolved_file.exists()
        
        if task_file.exists():
            status["last_task_mtime"] = task_file.stat().st_mtime
        if resolved_file.exists():
            status["last_resolved_mtime"] = resolved_file.stat().st_mtime
    
    return status


# CLI 接口
if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage:")
        print("  antigravity_bridge.py run <task>")
        print("  antigravity_bridge.py status")
        print("  antigravity_bridge.py list")
        sys.exit(1)
    
    command = sys.argv[1]
    
    if command == "run":
        task = " ".join(sys.argv[2:])
        result = run({"task": task})
        print(result)
    elif command == "status":
        import json
        print(json.dumps(check_status(), indent=2))
    elif command == "list":
        for conv in get_conversations():
            print(f"{conv['id']} - {'✓' if conv['has_task'] else '✗'}")
    else:
        print(f"Unknown command: {command}")
