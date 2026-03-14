#!/usr/bin/env python3
"""注册健康检查定时任务"""
import sys
sys.path.insert(0, '/Users/eason/Code/arcmind')

from runtime.cron import cron_system

# 添加每12小时执行一次的健康检查定时任务
# 12小时 = 43200 秒
result = cron_system.add_interval(
    name='system_health_check',
    seconds=43200,
    skill_name='health_check',
    input_data={'script': 'scripts/health_check.py'},
    governor_required=False
)

print('定时任务已创建:')
print(result)
