#!/usr/bin/env python3
"""
ArcMind 任务管理工具
基于 tool_template 创建的任务管理工具

使用方式:
    python3 tools/task_manager.py --action <action> --params <params>
    
Actions:
    create  - 创建任务
    list    - 列出任务
    get     - 获取任务详情
    update  - 更新任务状态
    delete  - 删除任务
"""

import argparse
import json
import sys
import os
from pathlib import Path
from datetime import datetime

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / "data"
TASKS_FILE = DATA_DIR / "tasks.json"


class TaskManager:
    """任务管理器"""
    
    def __init__(self):
        self.name = "task_manager"
        self.description = "ArcMind 任务管理工具"
        self.version = "1.0.0"
        self._ensure_data_dir()
        self.tasks = self._load_tasks()
    
    def _ensure_data_dir(self):
        """确保数据目录存在"""
        DATA_DIR.mkdir(parents=True, exist_ok=True)
    
    def _load_tasks(self):
        """加载任务数据"""
        if TASKS_FILE.exists():
            try:
                with open(TASKS_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                return []
        return []
    
    def _save_tasks(self):
        """保存任务数据"""
        with open(TASKS_FILE, 'w', encoding='utf-8') as f:
            json.dump(self.tasks, f, ensure_ascii=False, indent=2)
    
    def get_result(self, status="success", data=None, message=""):
        """返回标准结果格式"""
        return {
            "status": status,
            "tool": self.name,
            "version": self.version,
            "data": data,
            "message": message,
            "timestamp": datetime.now().isoformat()
        }
    
    def execute(self, action="list", params=None):
        """执行任务管理操作"""
        params = params or {}
        
        if action == "create":
            return self._create_task(params)
        elif action == "list":
            return self._list_tasks(params)
        elif action == "get":
            return self._get_task(params)
        elif action == "update":
            return self._update_task(params)
        elif action == "delete":
            return self._delete_task(params)
        else:
            return self.get_result(status="error", message=f"未知操作: {action}")
    
    def _create_task(self, params):
        """创建任务"""
        title = params.get("title", "新任务")
        description = params.get("description", "")
        priority = params.get("priority", "medium")
        
        task_id = len(self.tasks) + 1
        task = {
            "id": task_id,
            "title": title,
            "description": description,
            "priority": priority,
            "status": "pending",
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat()
        }
        
        self.tasks.append(task)
        self._save_tasks()
        
        return self.get_result(
            data=task,
            message=f"任务创建成功: {title}"
        )
    
    def _list_tasks(self, params):
        """列出任务"""
        status_filter = params.get("status")
        priority_filter = params.get("priority")
        
        filtered_tasks = self.tasks
        
        if status_filter:
            filtered_tasks = [t for t in filtered_tasks if t.get("status") == status_filter]
        if priority_filter:
            filtered_tasks = [t for t in filtered_tasks if t.get("priority") == priority_filter]
        
        return self.get_result(
            data={
                "tasks": filtered_tasks,
                "total": len(filtered_tasks)
            },
            message=f"共 {len(filtered_tasks)} 个任务"
        )
    
    def _get_task(self, params):
        """获取任务详情"""
        task_id = params.get("id")
        
        for task in self.tasks:
            if task.get("id") == task_id:
                return self.get_result(data=task, message=f"任务详情: {task.get('title')}")
        
        return self.get_result(status="error", message=f"任务不存在: {task_id}")
    
    def _update_task(self, params):
        """更新任务"""
        task_id = params.get("id")
        
        for task in self.tasks:
            if task.get("id") == task_id:
                # 更新字段
                if "title" in params:
                    task["title"] = params["title"]
                if "description" in params:
                    task["description"] = params["description"]
                if "status" in params:
                    task["status"] = params["status"]
                if "priority" in params:
                    task["priority"] = params["priority"]
                
                task["updated_at"] = datetime.now().isoformat()
                self._save_tasks()
                
                return self.get_result(
                    data=task,
                    message=f"任务更新成功: {task.get('title')}"
                )
        
        return self.get_result(status="error", message=f"任务不存在: {task_id}")
    
    def _delete_task(self, params):
        """删除任务"""
        task_id = params.get("id")
        
        for i, task in enumerate(self.tasks):
            if task.get("id") == task_id:
                deleted_task = self.tasks.pop(i)
                self._save_tasks()
                
                return self.get_result(
                    data=deleted_task,
                    message=f"任务删除成功: {deleted_task.get('title')}"
                )
        
        return self.get_result(status="error", message=f"任务不存在: {task_id}")


def main():
    """主入口"""
    parser = argparse.ArgumentParser(description="ArcMind 任务管理工具")
    parser.add_argument("--action", type=str, default="list", 
                       help="操作: create, list, get, update, delete")
    parser.add_argument("--params", type=str, default="{}", 
                       help="JSON格式参数")
    parser.add_argument("--output", type=str, default="json", 
                       choices=["json", "text"], help="输出格式")
    
    args = parser.parse_args()
    
    # 解析参数
    try:
        params = json.loads(args.params)
    except json.JSONDecodeError:
        params = {}
    
    # 执行
    manager = TaskManager()
    result = manager.execute(action=args.action, params=params)
    
    # 输出
    if args.output == "json":
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(result.get("message", ""))
    
    # 状态码
    sys.exit(0 if result.get("status") == "success" else 1)


if __name__ == "__main__":
    main()
