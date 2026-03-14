#!/usr/bin/env python3
import sys
sys.path.insert(0, '/Users/eason/Code/arcmind')

from db.schema import get_db_session, CronJob_
from runtime.cron import cron_system
from datetime import datetime

print('=' * 60)
print('CRON 服务状态检查报告')
print('=' * 60)

# Cron System 状态
print('\n### Cron 系统状态 ###')
print(f'已启动: {cron_system._started}')
print(f'调度器: {cron_system._scheduler}')
print(f'调度器运行中: {cron_system._scheduler.running if cron_system._scheduler else "N/A"}')

# 数据库中的 Cron 任务
print('\n### 数据库中的 Cron 任务 ###')
with get_db_session() as db:
    jobs = db.query(CronJob_).all()
    if not jobs:
        print('  (无记录)')
    for j in jobs:
        last_run = j.last_run.strftime('%Y-%m-%d %H:%M:%S') if j.last_run else '从未运行'
        print(f'  [{j.name}]')
        print(f'    调度: {j.cron_expr or f"每 {j.interval_s} 秒"}')
        print(f'    技能: {j.skill_name}')
        print(f'    启用: {j.enabled}')
        print(f'    运行次数: {j.run_count}')
        print(f'    最后运行: {last_run}')
        print()

# APScheduler 中的任务
print('\n### APScheduler 活跃任务 ###')
if cron_system._scheduler.running:
    jobs = cron_system._scheduler.get_jobs()
    if not jobs:
        print('  (无活跃任务)')
    for job in jobs:
        next_run = job.next_run_time.strftime('%Y-%m-%d %H:%M:%S') if job.next_run_time else 'N/A'
        print(f'  [{job.id}]')
        print(f'    下次运行: {next_run}')
else:
    print('  调度器未运行')

print('\n' + '=' * 60)
