#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Query TaskTracker for active and pending tasks."""

import sys
import os

# Add project root to path
project_root = '/Users/eason/Code/arcmind'
sys.path.insert(0, project_root)
os.chdir(project_root)

from runtime.task_tracker import task_tracker, TaskStatus
from datetime import datetime

# Get all active tasks
active_tasks = task_tracker.get_all_active()

print("=" * 60)
print("TaskTracker - 所有进行中的任务")
print("=" * 60)

if not active_tasks:
    print("\n无进行中的任务")
else:
    # Sort by created_at (older first)
    active_tasks.sort(key=lambda t: t.created_at)
    
    print(f"\n共 {len(active_tasks)} 个进行中/待处理任务:\n")
    
    for i, task in enumerate(active_tasks, 1):
        created_time = datetime.fromtimestamp(task.created_at).strftime('%Y-%m-%d %H:%M:%S')
        
        print(f"【任务 {i}】")
        print(f"  Task ID: {task.task_id}")
        print(f"  命令: {task.command}")
        print(f"  状态: {task.status.value}")
        print(f"  进度: {task.progress_pct:.0%}")
        print(f"  创建时间: {created_time}")
        
        if task.steps:
            print(f"  步骤数: {len(task.steps)}")
            completed_steps = sum(1 for s in task.steps if s.status == TaskStatus.COMPLETED)
            current_step = task.current_step + 1 if task.current_step < len(task.steps) else 0
            print(f"  当前步骤: {current_step}/{len(task.steps)}")
            print(f"  已完成步骤: {completed_steps}/{len(task.steps)}")
            
            # Show step details
            print("  步骤详情:")
            for step in task.steps:
                icon = {
                    "created": "[ ]",
                    "queued": "[~]",
                    "planning": "[P]",
                    "executing": "[>]",
                    "completed": "[✓]",
                    "failed": "[X]",
                    "cancelled": "[-]"
                }.get(step.status.value, "[?]")
                print(f"    {icon} Step {step.index+1}: {step.description[:50]}")
        
        if task.worker_id:
            print(f"  Worker: {task.worker_id}")
        if task.model:
            print(f"  Model: {task.model}")
        
        print()

# Also get recently completed tasks
print("\n" + "=" * 60)
print("最近完成的任务 (30分钟内)")
print("=" * 60)
recent = task_tracker.get_recently_completed(within_minutes=30)
if not recent:
    print("\n无最近完成的任务")
else:
    print(f"\n共 {len(recent)} 个最近完成的任务:\n")
    for task in recent:
        ended_time = datetime.fromtimestamp(task.ended_at).strftime('%Y-%m-%d %H:%M:%S')
        print(f"  - {task.task_id}: {task.command[:50]} [{task.status.value}] (完成于 {ended_time})")

# Summary
print("\n" + "=" * 60)
print("任务统计")
print("=" * 60)
total = len(task_tracker._tasks)
active_count = len(active_tasks)
completed_count = len([t for t in task_tracker._tasks.values() if t.status == TaskStatus.COMPLETED])
failed_count = len([t for t in task_tracker._tasks.values() if t.status == TaskStatus.FAILED])

print(f"  总任务数: {total}")
print(f"  进行中: {active_count}")
print(f"  已完成: {completed_count}")
print(f"  失败: {failed_count}")
