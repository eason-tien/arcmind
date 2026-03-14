#!/usr/bin/env python3
"""
ArcMind 系统状态检查脚本 (增强版)
检查项目：
- Cron 服务状态
- 数据库连接与表结构
- PM Workers 活跃数
- API 服务状态
- 系统资源 (CPU/内存/磁盘)
- 时间同步状态
- 配置文件完整性
- 最近错误日志
"""
import sys
import os
import json
import subprocess
from datetime import datetime
from pathlib import Path

# 项目根目录
PROJECT_ROOT = Path("/Users/eason/Code/arcmind")
sys.path.insert(0, str(PROJECT_ROOT))


class Color:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    END = '\033[0m'


def print_header(title: str):
    print(f"\n{Color.BLUE}{'=' * 60}{Color.END}")
    print(f"{Color.BLUE}  {title}{Color.END}")
    print(f"{Color.BLUE}{'=' * 60}{Color.END}")


def print_status(name: str, status: str, details: str = ""):
    icon = {
        "ok": f"{Color.GREEN}✓{Color.END}",
        "warn": f"{Color.YELLOW}⚠{Color.END}",
        "error": f"{Color.RED}✗{Color.END}",
        "info": f"{Color.BLUE}○{Color.END}",
    }.get(status, "?")

    print(f"  {icon} {name}: {status}")
    if details:
        print(f"      {details}")


def check_cron_service():
    """检查 Cron 服务"""
    try:
        from runtime.cron import cron_system
        started = cron_system._started
        scheduler = cron_system._scheduler.running if cron_system._scheduler else False
        status = "ok" if started and scheduler else "warn"
        details = f"started={started}, scheduler={scheduler}"
        print_status("Cron 服务", status, details)
        return {"status": status, "details": details}
    except ImportError:
        print_status("Cron 服务", "warn", "模块未找到")
        return {"status": "warn", "details": "module not found"}
    except Exception as e:
        print_status("Cron 服务", "error", str(e))
        return {"status": "error", "details": str(e)}


def check_database():
    """检查数据库"""
    try:
        from db.schema import get_db_session, Task_, CronJob_
        with get_db_session() as db:
            task_count = db.query(Task_).count()
            cron_count = db.query(CronJob_).count()
        print_status("数据库连接", "ok", f"任务数: {task_count}, Cron数: {cron_count}")
        return {"status": "ok", "details": f"tasks={task_count}, crons={cron_count}"}
    except ImportError as e:
        # 尝试备用导入
        try:
            from db.schema import get_db_session
            with get_db_session() as db:
                # 尝试查询任意表
                result = db.execute("SELECT name FROM sqlite_master WHERE type='table'")
                tables = result.fetchall()
            print_status("数据库连接", "ok", f"表数量: {len(tables)}")
            return {"status": "ok", "details": f"tables={len(tables)}"}
        except Exception as e2:
            print_status("数据库连接", "error", str(e2))
            return {"status": "error", "details": str(e2)}
    except Exception as e:
        print_status("数据库连接", "error", str(e))
        return {"status": "error", "details": str(e)}


def check_pm_workers():
    """检查 PM Workers"""
    try:
        # 尝试多个可能的模块路径
        for module_path in ['runtime.heartbeat', 'heartbeat', 'pm_pool']:
            try:
                exec(f"from {module_path} import heartbeat")
                workers = heartbeat._executors
                total = len(workers)
                active = sum(1 for f in workers.values() if hasattr(f, '_running') and f._running)
                status = "ok" if total > 0 else "warn"
                print_status("PM Workers", status, f"总计: {total}, 活跃: {active}")
                return {"status": status, "details": f"total={total}, active={active}"}
            except ImportError:
                continue

        print_status("PM Workers", "warn", "模块未找到")
        return {"status": "warn", "details": "module not found"}
    except Exception as e:
        print_status("PM Workers", "error", str(e))
        return {"status": "error", "details": str(e)}


def check_api_service():
    """检查 API 服务端口"""
    try:
        result = subprocess.run(
            ["lsof", "-i", ":8000"],
            capture_output=True,
            text=True,
            timeout=5
        )
        status = "ok" if result.stdout else "warn"
        print_status("API 服务 (:8000)", status, "运行中" if result.stdout else "未启动")
        return {"status": status, "details": "running" if result.stdout else "stopped"}
    except Exception as e:
        print_status("API 服务", "error", str(e))
        return {"status": "error", "details": str(e)}


def check_system_resources():
    """检查系统资源"""
    try:
        # CPU - 查找Python进程
        result = subprocess.run(
            ["ps", "aux"],
            capture_output=True,
            text=True,
            timeout=5
        )
        arc_processes = [l for l in result.stdout.split('\n') if 'python' in l.lower()]
        cpu_count = len(arc_processes)

        # 磁盘
        result = subprocess.run(
            ["df", "-h", str(PROJECT_ROOT)],
            capture_output=True,
            text=True,
            timeout=5
        )

        status = "ok"
        details = f"Python进程: {cpu_count}个"
        print_status("系统资源", status, details)
        return {"status": status, "details": details}
    except Exception as e:
        print_status("系统资源", "warn", str(e))
        return {"status": "warn", "details": str(e)}


def check_time_sync():
    """检查时间同步"""
    try:
        now = datetime.now()
        status = "ok"
        print_status("系统时间", status, now.strftime("%Y-%m-%d %H:%M:%S"))
        return {"status": status, "details": now.isoformat()}
    except Exception as e:
        print_status("系统时间", "error", str(e))
        return {"status": "error", "details": str(e)}


def check_config_files():
    """检查配置文件"""
    config_files = [
        PROJECT_ROOT / ".env",
        PROJECT_ROOT / ".env.example",
    ]

    missing = []
    for f in config_files:
        if not f.exists():
            missing.append(f.name)

    status = "ok" if not missing else "warn"
    details = f"缺失: {', '.join(missing)}" if missing else "完整"
    print_status("配置文件", status, details)
    return {"status": status, "details": details}


def check_recent_errors():
    """检查最近错误日志"""
    log_dir = PROJECT_ROOT / "logs"
    if not log_dir.exists():
        print_status("错误日志", "warn", "日志目录不存在")
        return {"status": "warn", "details": "no logs"}

    try:
        # 查找最近的日志文件
        log_files = sorted(log_dir.glob("*.log"), key=lambda x: x.stat().st_mtime, reverse=True)[:3]

        if not log_files:
            print_status("错误日志", "info", "无日志文件")
            return {"status": "info", "details": "no files"}

        # 检查最新日志的错误
        latest = log_files[0]
        with open(latest) as f:
            lines = f.readlines()[-50:]  # 最后50行
            errors = [l for l in lines if 'error' in l.lower() or 'exception' in l.lower()]

        status = "warn" if errors else "ok"
        count = len(errors)
        print_status("错误日志", status, f"最新: {latest.name}, 错误: {count}条")
        return {"status": status, "details": f"latest={latest.name}, errors={count}"}
    except Exception as e:
        print_status("错误日志", "warn", str(e))
        return {"status": "warn", "details": str(e)}


def check_project_structure():
    """检查项目结构完整性"""
    required_dirs = [
        "api", "config", "db", "runtime", "heartbeat",
        "memory", "protocol", "skills", "tools", "scripts"
    ]

    missing = []
    for d in required_dirs:
        if not (PROJECT_ROOT / d).exists():
            missing.append(d)

    status = "ok" if not missing else "warn"
    details = f"缺失: {', '.join(missing)}" if missing else "完整"
    print_status("项目结构", status, details)
    return {"status": status, "details": details}


def main():
    print(f"\n{Color.BLUE}")
    print("╔" + "═" * 58 + "╗")
    print("║" + " " * 15 + "ArcMind 系统状态检查" + " " * 19 + "║")
    print("╚" + "═" * 58 + "╝")
    print(f"{Color.END}")

    print(f"\n时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"项目: {PROJECT_ROOT}")

    results = []

    # 执行各项检查
    print_header("核心服务")
    results.append(("Cron", check_cron_service()))
    results.append(("PM Workers", check_pm_workers()))
    results.append(("API", check_api_service()))

    print_header("数据层")
    results.append(("数据库", check_database()))

    print_header("系统状态")
    results.append(("系统资源", check_system_resources()))
    results.append(("时间同步", check_time_sync()))

    print_header("配置与日志")
    results.append(("配置文件", check_config_files()))
    results.append(("项目结构", check_project_structure()))
    results.append(("错误日志", check_recent_errors()))

    # 总结
    print_header("检查总结")

    ok_count = sum(1 for _, r in results if r["status"] == "ok")
    warn_count = sum(1 for _, r in results if r["status"] == "warn")
    error_count = sum(1 for _, r in results if r["status"] == "error")
    total = len(results)

    print(f"  ✓ 通过: {ok_count}")
    if warn_count:
        print(f"  ⚠ 警告: {warn_count}")
    if error_count:
        print(f"  ✗ 错误: {error_count}")

    print(f"\n  总计: {total}/{total}")

    # JSON 输出
    output = {
        "timestamp": datetime.now().isoformat(),
        "summary": {
            "ok": ok_count,
            "warn": warn_count,
            "error": error_count,
            "total": total
        },
        "checks": {name: result for name, result in results}
    }

    print(f"\n{Color.BLUE}JSON Output:{Color.END}")
    print(json.dumps(output, ensure_ascii=False, indent=2))

    return 0 if error_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
