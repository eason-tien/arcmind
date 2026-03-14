#!/usr/bin/env python3
"""
系统健康检查脚本
每12小时执行一次，检查：
- Cron 服务状态
- 数据库连接
- PM Workers 活跃数
- API 服务状态
"""
import sys
sys.path.insert(0, '/Users/eason/Code/arcmind')

import json
from datetime import datetime
from runtime.cron import cron_system
from db.schema import get_db_session, TaskTracker_, CronJob_


def check_cron_service():
    """检查 Cron 服务"""
    return {
        "name": "Cron Service",
        "status": "running" if cron_system._started else "stopped",
        "details": {
            "started": cron_system._started,
            "scheduler_running": cron_system._scheduler.running if cron_system._scheduler else False
        }
    }


def check_database():
    """检查数据库连接"""
    try:
        with get_db_session() as db:
            # 尝试查询任务数量
            task_count = db.query(TaskTracker_).count()
            cron_count = db.query(CronJob_).count()
        return {
            "name": "Database",
            "status": "healthy",
            "details": {
                "task_count": task_count,
                "cron_count": cron_count
            }
        }
    except Exception as e:
        return {
            "name": "Database",
            "status": "error",
            "details": {"error": str(e)}
        }


def check_pm_workers():
    """检查 PM Workers 状态"""
    try:
        from runtime.heartbeat import heartbeat
        worker_count = len(heartbeat._executors)
        active_count = sum(1 for f in heartbeat._executors.values()
                         if hasattr(f, '_running') and f._running)
        
        return {
            "name": "PM Workers",
            "status": "active" if worker_count > 0 else "idle",
            "details": {
                "total_workers": worker_count,
                "active_workers": active_count
            }
        }
    except Exception as e:
        return {
            "name": "PM Workers",
            "status": "error",
            "details": {"error": str(e)}
        }


def check_api_service():
    """检查 API 服务"""
    import subprocess
    try:
        result = subprocess.run(
            ["lsof", "-i", ":8000"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.stdout:
            return {
                "name": "API Service",
                "status": "running",
                "details": {"port": 8000, "process": "active"}
            }
        else:
            return {
                "name": "API Service",
                "status": "stopped",
                "details": {"port": 8000}
            }
    except Exception as e:
        return {
            "name": "API Service",
            "status": "unknown",
            "details": {"error": str(e)}
        }


def main():
    print("=" * 60)
    print(f"系统健康检查 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    
    results = []
    
    # 执行各项检查
    checks = [
        check_cron_service,
        check_database,
        check_pm_workers,
        check_api_service,
    ]
    
    for check in checks:
        result = check()
        results.append(result)
        status_icon = "✅" if result["status"] in ["healthy", "running", "active"] else "⚠️"
        print(f"\n{status_icon} {result['name']}: {result['status']}")
        for k, v in result.get("details", {}).items():
            print(f"   {k}: {v}")
    
    # 总结
    healthy_count = sum(1 for r in results if r["status"] in ["healthy", "running", "active"])
    total_count = len(results)
    
    print("\n" + "=" * 60)
    print(f"总结: {healthy_count}/{total_count} 检查通过")
    print("=" * 60)
    
    # 输出 JSON 格式结果（供程序解析）
    output = {
        "timestamp": datetime.now().isoformat(),
        "summary": {
            "total": total_count,
            "healthy": healthy_count
        },
        "checks": results
    }
    
    print("\n[JSON Output]")
    print(json.dumps(output, ensure_ascii=False, indent=2))
    
    return 0 if healthy_count == total_count else 1


if __name__ == "__main__":
    sys.exit(main())
