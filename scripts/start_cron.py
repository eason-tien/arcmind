#!/usr/bin/env python3
import sys
sys.path.insert(0, '/Users/eason/Code/arcmind')

from db.schema import get_db_session, CronJob_
from runtime.cron import cron_system

print('正在启动 Cron 系统...')

# 启动 cron 系统
cron_system.startup()

print(f'Cron 系统已启动: {cron_system._started}')
print(f'调度器运行中: {cron_system._scheduler.running}')

# 验证任务已加载
with get_db_session() as db:
    enabled_jobs = db.query(CronJob_).filter(CronJob_.enabled == True).all()
    print(f'\n已启用任务数: {len(enabled_jobs)}')

if cron_system._scheduler.running:
    jobs = cron_system._scheduler.get_jobs()
    print(f'APScheduler 活跃任务: {len(jobs)}')
    for job in jobs:
        next_run = job.next_run_time.strftime('%Y-%m-%d %H:%M:%S') if job.next_run_time else 'N/A'
        print(f'  - {job.id}: 下次运行 {next_run}')
