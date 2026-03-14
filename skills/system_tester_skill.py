"""
Skill: system_tester_skill
系统定时测试 Skill — 每12小时执行

功能：
1. 检查系统健康状态（数据库、API、进程等）
2. 检查错误日志，识别异常模式
3. 如有问题启动自动修复迭代
4. 生成测试报告并保存

使用方式：
    python -m skills.system_tester_skill
    或通过 Cron 调用
"""
from __future__ import annotations
import json
import logging
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

# 配置路径
BASE_DIR = Path("/Users/eason/Code/arcmind")
LOG_DIR = BASE_DIR / "outputs" / "system_tester"
LOG_DIR.mkdir(parents=True, exist_ok=True)

logger = logging.getLogger("arcmind.skill.system_tester")


def _run_command(cmd: str, timeout: int = 30) -> Dict[str, Any]:
    """执行 shell 命令"""
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=timeout
        )
        return {
            "success": result.returncode == 0,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
            "returncode": result.returncode,
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "stdout": "", "stderr": "Command timeout", "returncode": -1}
    except Exception as e:
        return {"success": False, "stdout": "", "stderr": str(e), "returncode": -1}


def check_database() -> Dict[str, Any]:
    """检查数据库连接和状态"""
    db_path = BASE_DIR / "data" / "arcmind.db"
    result = {
        "name": "Database",
        "status": "unknown",
        "details": {}
    }
    
    if not db_path.exists():
        result["status"] = "not_found"
        result["details"]["path"] = str(db_path)
        return result
    
    # 检查表
    tables_result = _run_command(f"sqlite3 '{db_path}' \"SELECT name FROM sqlite_master WHERE type='table';\"")
    if tables_result["success"]:
        tables = [t.strip() for t in tables_result["stdout"].split('\n') if t.strip()]
        result["details"]["tables"] = tables
        result["details"]["table_count"] = len(tables)
    
    # 检查数据量
    count_result = _run_command(f"sqlite3 '{db_path}' \"SELECT COUNT(*) FROM task_tracker;\"")
    if count_result["success"] and count_result["stdout"].isdigit():
        result["details"]["task_count"] = int(count_result["stdout"])
    
    result["status"] = "healthy"
    return result


def check_processes() -> Dict[str, Any]:
    """检查关键进程状态"""
    result = {
        "name": "Processes",
        "status": "unknown",
        "details": {}
    }
    
    # 检查 Python 进程
    ps_result = _run_command("pgrep -f 'python.*arcmind' | wc -l")
    if ps_result["success"]:
        result["details"]["arcmind_procs"] = int(ps_result["stdout"]) if ps_result["stdout"].isdigit() else 0
    
    # 检查 API 服务 (端口 8000)
    lsof_result = _run_command("lsof -i :8000")
    result["details"]["api_running"] = lsof_result["success"] and bool(lsof_result["stdout"])
    
    # 检查心跳服务
    heartbeat_result = _run_command("pgrep -f 'heartbeat' | wc -l")
    if heartbeat_result["success"]:
        result["details"]["heartbeat_procs"] = int(heartbeat_result["stdout"]) if heartbeat_result["stdout"].isdigit() else 0
    
    # 判断状态
    if result["details"].get("arcmind_procs", 0) > 0:
        result["status"] = "running"
    else:
        result["status"] = "stopped"
    
    return result


def check_system_resources() -> Dict[str, Any]:
    """检查系统资源"""
    result = {
        "name": "System Resources",
        "status": "unknown",
        "details": {}
    }
    
    # 磁盘使用率
    disk_result = _run_command("df -h / | tail -1 | awk '{print $5}'")
    if disk_result["success"]:
        disk_pct = disk_result["stdout"].replace('%', '').strip()
        result["details"]["disk_usage"] = f"{disk_pct}%"
        try:
            if int(disk_pct) > 90:
                result["status"] = "critical"
            elif int(disk_pct) > 80:
                result["status"] = "warning"
            else:
                result["status"] = "healthy"
        except ValueError:
            result["status"] = "unknown"
    
    # 内存使用
    mem_result = _run_command("free -h 2>/dev/null | grep Mem | awk '{print $3\"/\"$2}'")
    if mem_result["success"]:
        result["details"]["memory"] = mem_result["stdout"]
    
    # CPU 负载
    uptime_result = _run_command("uptime | awk -F'load average:' '{print $2}'")
    if uptime_result["success"]:
        result["details"]["load_avg"] = uptime_result["stdout"].strip()
    
    return result


def check_error_logs() -> Dict[str, Any]:
    """检查错误日志，识别异常"""
    result = {
        "name": "Error Logs",
        "status": "unknown",
        "details": {},
        "errors": [],
        "warnings": []
    }
    
    error_patterns = {
        "ERROR": [],
        "WARNING": [],
        "CRITICAL": [],
        "EXCEPTION": [],
    }
    
    # 检查 logs 目录
    logs_base = BASE_DIR / "logs"
    log_files = []
    
    if logs_base.exists():
        log_files.extend(logs_base.glob("*.log"))
    
    # 检查 outputs 目录
    outputs_logs = BASE_DIR / "outputs"
    if outputs_logs.exists():
        log_files.extend(outputs_logs.glob("**/*.log"))
    
    # 限制检查数量
    log_files = log_files[:20]
    
    for log_file in log_files:
        try:
            # 读取最近 500 行
            tail_result = _run_command(f"tail -500 '{log_file}'", timeout=10)
            if tail_result["success"]:
                lines = tail_result["stdout"].split('\n')
                for line in lines:
                    line_lower = line.lower()
                    if "error" in line_lower and "error_log" not in str(log_file).lower():
                        error_patterns["ERROR"].append(f"[{log_file.name}] {line[:150]}")
                    if "warning" in line_lower:
                        error_patterns["WARNING"].append(f"[{log_file.name}] {line[:150]}")
                    if "critical" in line_lower:
                        error_patterns["CRITICAL"].append(f"[{log_file.name}] {line[:150]}")
                    if "exception" in line_lower:
                        error_patterns["EXCEPTION"].append(f"[{log_file.name}] {line[:150]}")
        except Exception as e:
            logger.warning(f"Failed to read log {log_file}: {e}")
    
    # 限制错误数量
    result["errors"] = error_patterns["ERROR"][:20]
    result["warnings"] = error_patterns["WARNING"][:20]
    result["details"]["error_count"] = len(error_patterns["ERROR"])
    result["details"]["warning_count"] = len(error_patterns["WARNING"])
    result["details"]["critical_count"] = len(error_patterns["CRITICAL"])
    result["details"]["exception_count"] = len(error_patterns["EXCEPTION"])
    
    # 判断状态
    if error_patterns["CRITICAL"]:
        result["status"] = "critical"
    elif error_patterns["ERROR"]:
        result["status"] = "error"
    elif error_patterns["WARNING"]:
        result["status"] = "warning"
    else:
        result["status"] = "healthy"
    
    return result


def check_cron_jobs() -> Dict[str, Any]:
    """检查 Cron 任务状态"""
    result = {
        "name": "Cron Jobs",
        "status": "unknown",
        "details": {}
    }
    
    try:
        sys.path.insert(0, str(BASE_DIR))
        from db.schema import get_db_session, CronJob_
        
        with get_db_session() as db:
            jobs = db.query(CronJob_).all()
            result["details"]["total_jobs"] = len(jobs)
            result["details"]["enabled_jobs"] = sum(1 for j in jobs if j.enabled)
            result["details"]["jobs"] = [
                {
                    "name": j.name,
                    "skill": j.skill_name,
                    "enabled": j.enabled,
                    "last_run": j.last_run.isoformat() if j.last_run else None,
                    "run_count": j.run_count,
                }
                for j in jobs[:10]
            ]
        
        result["status"] = "healthy" if result["details"]["enabled_jobs"] > 0 else "no_jobs"
    except Exception as e:
        result["status"] = "error"
        result["details"]["error"] = str(e)
    
    return result


def trigger_auto_repair(error_summary: Dict[str, int]) -> Dict[str, Any]:
    """根据错误情况触发自动修复"""
    repair_result = {
        "triggered": False,
        "actions": [],
        "success": False,
    }
    
    # 判断是否需要修复
    needs_repair = False
    reasons = []
    
    if error_summary.get("critical_count", 0) > 0:
        needs_repair = True
        reasons.append("发现严重错误 (CRITICAL)")
    
    if error_summary.get("error_count", 0) > 10:
        needs_repair = True
        reasons.append(f"错误数量过多 ({error_summary['error_count']} 个)")
    
    if not needs_repair:
        return repair_result
    
    repair_result["triggered"] = True
    repair_result["reasons"] = reasons
    
    # 尝试调用自动修复脚本
    repair_script = BASE_DIR / "scripts" / "auto_repair" / "auto_repair.py"
    if repair_script.exists():
        repair_cmd = f"cd '{BASE_DIR}' && python3 '{repair_script}' --detect-only"
        cmd_result = _run_command(repair_cmd, timeout=60)
        
        repair_result["actions"].append({
            "action": "auto_repair_script",
            "success": cmd_result["success"],
            "output": cmd_result["stdout"][:500] if cmd_result["stdout"] else "",
            "error": cmd_result["stderr"][:500] if cmd_result["stderr"] else "",
        })
        
        repair_result["success"] = cmd_result["success"]
    else:
        repair_result["actions"].append({
            "action": "auto_repair_script",
            "success": False,
            "error": "Repair script not found",
        })
    
    # 记录修复尝试
    logger.info(f"Auto repair triggered: {reasons}")
    
    return repair_result


def run_tests() -> Dict[str, Any]:
    """运行所有测试并返回结果"""
    timestamp = datetime.now().isoformat()
    
    print("=" * 60)
    print(f"🧪 ArcMind 系统测试 - {timestamp}")
    print("=" * 60)
    
    results = {
        "timestamp": timestamp,
        "checks": [],
        "summary": {
            "total": 0,
            "healthy": 0,
            "warning": 0,
            "error": 0,
            "critical": 0,
        }
    }
    
    # 1. 数据库检查
    print("\n[1/5] 检查数据库...")
    db_check = check_database()
    results["checks"].append(db_check)
    print(f"    状态: {db_check['status']}")
    
    # 2. 进程检查
    print("\n[2/5] 检查进程...")
    proc_check = check_processes()
    results["checks"].append(proc_check)
    print(f"    状态: {proc_check['status']}")
    
    # 3. 系统资源检查
    print("\n[3/5] 检查系统资源...")
    sys_check = check_system_resources()
    results["checks"].append(sys_check)
    print(f"    状态: {sys_check['status']}")
    
    # 4. 错误日志检查
    print("\n[4/5] 检查错误日志...")
    log_check = check_error_logs()
    results["checks"].append(log_check)
    print(f"    状态: {log_check['status']}")
    print(f"    错误: {log_check['details'].get('error_count', 0)} 个")
    print(f"    警告: {log_check['details'].get('warning_count', 0)} 个")
    
    # 5. Cron 任务检查
    print("\n[5/5] 检查 Cron 任务...")
    cron_check = check_cron_jobs()
    results["checks"].append(cron_check)
    print(f"    状态: {cron_check['status']}")
    
    # 汇总统计
    status_counts = {"healthy": 0, "warning": 0, "error": 0, "critical": 0}
    for check in results["checks"]:
        status = check.get("status", "unknown")
        if status in status_counts:
            status_counts[status] += 1
    
    results["summary"] = {
        "total": len(results["checks"]),
        "healthy": status_counts["healthy"],
        "warning": status_counts["warning"],
        "error": status_counts["error"],
        "critical": status_counts["critical"],
    }
    
    # 错误日志摘要
    error_summary = {
        "critical_count": log_check["details"].get("critical_count", 0),
        "error_count": log_check["details"].get("error_count", 0),
        "warning_count": log_check["details"].get("warning_count", 0),
    }
    
    # 6. 自动修复（如需要）
    print("\n[修复] 检查是否需要自动修复...")
    repair_result = trigger_auto_repair(error_summary)
    results["repair"] = repair_result
    
    if repair_result["triggered"]:
        print(f"    已触发自动修复: {repair_result.get('reasons', [])}")
    else:
        print("    无需修复")
    
    # 保存报告
    report_path = LOG_DIR / f"test_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(report_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    
    print(f"\n📄 报告已保存: {report_path}")
    
    # 总结
    print("\n" + "=" * 60)
    print("📊 测试结果汇总")
    print("=" * 60)
    print(f"  ✅ 健康: {results['summary']['healthy']}")
    print(f"  ⚠️  警告: {results['summary']['warning']}")
    print(f"  ❌ 错误: {results['summary']['error']}")
    print(f"  🔴 严重: {results['summary']['critical']}")
    print("=" * 60)
    
    # 确定整体状态
    if results["summary"]["critical"] > 0:
        overall_status = "CRITICAL"
    elif results["summary"]["error"] > 0:
        overall_status = "ERROR"
    elif results["summary"]["warning"] > 0:
        overall_status = "WARNING"
    else:
        overall_status = "HEALTHY"
    
    print(f"\n🏁 整体状态: {overall_status}")
    
    results["overall_status"] = overall_status
    
    return results


def run(inputs: dict = None) -> dict:
    """Skill 入口函数"""
    try:
        test_results = run_tests()
        
        # 返回结构化结果
        return {
            "success": test_results["overall_status"] in ["HEALTHY", "WARNING"],
            "status": test_results["overall_status"],
            "summary": test_results["summary"],
            "checks": [
                {"name": c["name"], "status": c["status"]}
                for c in test_results["checks"]
            ],
            "repair_triggered": test_results.get("repair", {}).get("triggered", False),
            "report_path": str(LOG_DIR / f"test_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"),
        }
    except Exception as e:
        logger.error("System tester skill failed: %s", e)
        return {
            "success": False,
            "error": str(e),
            "status": "ERROR",
        }


if __name__ == "__main__":
    # 直接运行时执行测试
    result = run()
    print("\n" + "=" * 60)
    print("JSON Output:")
    print("=" * 60)
    print(json.dumps(result, ensure_ascii=False, indent=2))
