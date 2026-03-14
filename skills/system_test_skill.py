#!/usr/bin/env python3
"""
Skill: system_test
ArcMind 系统自动测试与修复 — 每12小时执行一次

功能：
1. 检查系统健康状态
2. 检查错误日志，识别异常
3. 如有问题启动自动修复迭代
4. 保存健康检查报告

执行方式（通过 Cron 每12小时调用）：
    cron_system.add_interval(
        name='system_test_12h',
        seconds=43200,  # 12小时
        skill_name='system_test',
        input_data={'action': 'run'}
    )

或手动执行：
    from skills.system_test import run
    result = run({'action': 'run'})
"""
from __future__ import annotations
import json
import logging
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

# 配置路径
BASE_DIR = Path("/Users/eason/Code/arcmind")
LOG_DIR = BASE_DIR / "outputs" / "health_check"
LOG_DIR.mkdir(parents=True, exist_ok=True)

logger = logging.getLogger("arcmind.skill.system_test")


def _get_health_check_script() -> Path:
    """获取健康检查脚本路径"""
    return BASE_DIR / "scripts" / "health_check_and_repair.py"


def _get_log_file() -> Path:
    """获取日志文件路径"""
    return LOG_DIR / f"system_test_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"


def _log(message: str, level: str = "INFO") -> None:
    """输出日志到文件和控制台"""
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    log_line = f"[{timestamp}] [{level}] {message}"
    print(log_line)
    
    log_file = _get_log_file()
    with open(log_file, 'a', encoding='utf-8') as f:
        f.write(log_line + '\n')


def _run_command(cmd: str, timeout: int = 60) -> Dict[str, Any]:
    """执行shell命令"""
    try:
        result = subprocess.run(
            cmd, 
            shell=True, 
            capture_output=True, 
            text=True, 
            timeout=timeout,
            cwd=str(BASE_DIR)
        )
        return {
            "success": result.returncode == 0,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
            "returncode": result.returncode
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "stdout": "", "stderr": "Command timeout", "returncode": -1}
    except Exception as e:
        return {"success": False, "stdout": "", "stderr": str(e), "returncode": -1}


def _check_error_logs() -> Dict[str, Any]:
    """检查错误日志，识别异常"""
    _log("=" * 60)
    _log("🔍 步骤1: 检查错误日志")
    _log("=" * 60)
    
    error_patterns = {
        "ERROR": [],
        "WARNING": [],
        "CRITICAL": [],
        "npm_404": [],
        "exception": [],
    }
    
    # 检查各个日志文件
    log_files = [
        BASE_DIR / "logs" / "approval_gate_sweep.log",
        BASE_DIR / "logs" / "system.log",
        BASE_DIR / "logs" / "error.log",
    ]
    
    # 额外检查 outputs 目录下的日志
    outputs_logs = []
    if (BASE_DIR / "outputs").exists():
        outputs_logs = list((BASE_DIR / "outputs").glob("**/*.log"))
    log_files.extend(outputs_logs[:10])
    
    for log_file in log_files:
        if not log_file.exists():
            continue
            
        try:
            # 读取最近1000行
            result = _run_command(f"tail -1000 '{log_file}'")
            if result["success"]:
                lines = result["stdout"].split('\n')
                for line in lines:
                    line_lower = line.lower()
                    if "error" in line_lower and "error_log" not in str(log_file):
                        error_patterns["ERROR"].append(f"[{log_file.name}] {line[:200]}")
                    if "warning" in line_lower:
                        error_patterns["WARNING"].append(f"[{log_file.name}] {line[:200]}")
                    if "critical" in line_lower:
                        error_patterns["CRITICAL"].append(f"[{log_file.name}] {line[:200]}")
                    if "404" in line_lower or "not found" in line_lower:
                        error_patterns["npm_404"].append(f"[{log_file.name}] {line[:200]}")
                    if "exception" in line_lower:
                        error_patterns["exception"].append(f"[{log_file.name}] {line[:200]}")
        except Exception as e:
            _log(f"⚠️ 读取日志失败 {log_file}: {e}", "WARNING")
    
    # 统计
    summary = {
        "ERROR_count": len(error_patterns["ERROR"]),
        "WARNING_count": len(error_patterns["WARNING"]),
        "CRITICAL_count": len(error_patterns["CRITICAL"]),
        "npm_404_count": len(error_patterns["npm_404"]),
        "exception_count": len(error_patterns["exception"]),
    }
    
    _log(f"📊 日志检查结果: {summary}")
    
    # 显示关键错误
    if error_patterns["CRITICAL"]:
        _log(f"❌ 发现 {len(error_patterns['CRITICAL'])} 个严重错误:")
        for err in error_patterns["CRITICAL"][:5]:
            _log(f"   {err}", "ERROR")
    
    if error_patterns["npm_404"]:
        _log(f"⚠️ 发现 {len(error_patterns['npm_404'])} 个 npm 404 错误:")
        for err in error_patterns["npm_404"][:3]:
            _log(f"   {err}", "WARNING")
    
    return {"patterns": error_patterns, "summary": summary}


def _check_system_health() -> Dict[str, Any]:
    """检查系统健康状态"""
    _log("=" * 60)
    _log("🔍 步骤2: 检查系统健康状态")
    _log("=" * 60)
    
    health_status = {
        "database": "unknown",
        "disk_space": "unknown",
        "memory": "unknown",
        "processes": "unknown",
    }
    
    # 1. 检查数据库
    db_path = BASE_DIR / "data" / "arcmind.db"
    if db_path.exists():
        result = _run_command(f"sqlite3 '{db_path}' 'SELECT COUNT(*) FROM sqlite_master;'")
        health_status["database"] = "ok" if result["success"] else "error"
    else:
        # 尝试备选路径
        db_path_alt = BASE_DIR / "arcmind.db"
        if db_path_alt.exists():
            result = _run_command(f"sqlite3 '{db_path_alt}' 'SELECT COUNT(*) FROM sqlite_master;'")
            health_status["database"] = "ok" if result["success"] else "error"
        else:
            health_status["database"] = "not_found"
    
    _log(f"🗄️ 数据库状态: {health_status['database']}")
    
    # 2. 检查磁盘空间
    result = _run_command("df -h / | tail -1 | awk '{print $5}'")
    disk_usage = result["stdout"].replace('%', '') if result["success"] else "unknown"
    health_status["disk_space"] = f"{disk_usage}%"
    _log(f"💾 磁盘使用率: {health_status['disk_space']}")
    
    # 3. 检查内存 (macOS)
    result = _run_command("vm_stat | head -10")
    if result["success"]:
        health_status["memory"] = result["stdout"][:200]
        _log(f"🧠 内存状态: {health_status['memory'][:100]}...")
    
    # 4. 检查关键进程
    result = _run_command("pgrep -f 'arcmind|python.*pm' | wc -l")
    if result["success"]:
        proc_count = int(result["stdout"]) if result["stdout"].isdigit() else 0
        health_status["processes"] = proc_count
        _log(f"⚙️ 运行进程数: {proc_count}")
    
    return health_status


def _check_cron_status() -> Dict[str, Any]:
    """检查Cron任务状态"""
    _log("=" * 60)
    _log("🔍 步骤3: 检查Cron任务状态")
    _log("=" * 60)
    
    cron_status = {
        "total_jobs": 0,
        "enabled_jobs": 0,
        "jobs": []
    }
    
    # 尝试导入数据库模块
    try:
        sys.path.insert(0, str(BASE_DIR))
        from db.schema import get_db_session, CronJob_
        
        with get_db_session() as db:
            all_jobs = db.query(CronJob_).all()
            cron_status["total_jobs"] = len(all_jobs)
            cron_status["enabled_jobs"] = sum(1 for j in all_jobs if j.enabled)
            
            for job in all_jobs[:10]:  # 最多显示10个
                cron_status["jobs"].append({
                    "name": job.name,
                    "enabled": job.enabled,
                    "skill": job.skill_name,
                    "last_run": job.last_run.isoformat() if job.last_run else None,
                })
        
        _log(f"📅 Cron任务: {cron_status['enabled_jobs']}/{cron_status['total_jobs']} 已启用")
        
    except Exception as e:
        _log(f"⚠️ Cron状态检查跳过: {e}", "WARNING")
    
    return cron_status


def _run_auto_repair(error_summary: Dict[str, int]) -> Dict[str, Any]:
    """根据错误情况运行自动修复"""
    _log("=" * 60)
    _log("🔧 步骤4: 执行自动修复（如需要）")
    _log("=" * 60)
    
    # 判断是否需要修复
    need_repair = False
    reasons = []
    
    if error_summary.get("CRITICAL_count", 0) > 0:
        need_repair = True
        reasons.append("发现严重错误")
    
    if error_summary.get("npm_404_count", 0) > 3:
        need_repair = True
        reasons.append("npm 404 错误过多")
    
    if error_summary.get("ERROR_count", 0) > 10:
        need_repair = True
        reasons.append("错误数量过多")
    
    if not need_repair:
        _log("✅ 无需自动修复")
        return {"repair_needed": False, "reasons": []}
    
    _log(f"⚠️ 需要修复，原因: {', '.join(reasons)}")
    
    # 调用自动修复脚本
    repair_script = BASE_DIR / "scripts" / "auto_repair" / "auto_repair.py"
    if repair_script.exists():
        result = _run_command(f"python3 '{repair_script}' --detect-only", timeout=120)
        
        if result["success"]:
            _log("✅ 自动修复脚本执行成功")
        else:
            _log(f"⚠️ 自动修复脚本执行失败: {result['stderr']}", "WARNING")
        
        return {
            "repair_needed": True,
            "reasons": reasons,
            "repair_result": result
        }
    else:
        _log("⚠️ 自动修复脚本不存在，跳过", "WARNING")
        return {"repair_needed": False, "reasons": [], "error": "repair_script_not_found"}


def _save_health_report(health_data: Dict[str, Any]) -> Path:
    """保存健康检查报告"""
    report = {
        "timestamp": datetime.now().isoformat(),
        "health_data": health_data,
    }
    
    report_path = LOG_DIR / f"health_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(report_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    
    _log(f"📄 健康报告已保存: {report_path}")
    return report_path


def _run_system_test() -> Dict[str, Any]:
    """运行完整的系统测试"""
    _log("=" * 60)
    _log("🚀 ArcMind 系统测试开始")
    _log(f"⏰ 执行时间: {datetime.now().isoformat()}")
    _log("=" * 60)
    
    health_data = {}
    
    # 1. 检查错误日志
    log_result = _check_error_logs()
    health_data["error_logs"] = log_result
    
    # 2. 检查系统健康
    sys_health = _check_system_health()
    health_data["system_health"] = sys_health
    
    # 3. 检查Cron状态
    cron_status = _check_cron_status()
    health_data["cron_status"] = cron_status
    
    # 4. 根据错误情况决定是否修复
    repair_result = _run_auto_repair(log_result["summary"])
    health_data["repair"] = repair_result
    
    # 5. 保存报告
    report_path = _save_health_report(health_data)
    
    # 汇总
    _log("=" * 60)
    _log("📊 系统测试汇总")
    _log("=" * 60)
    
    error_count = log_result["summary"]["ERROR_count"]
    warning_count = log_result["summary"]["WARNING_count"]
    critical_count = log_result["summary"]["CRITICAL_count"]
    
    overall_status = "healthy"
    if critical_count > 0:
        overall_status = "critical"
        _log(f"❌ 状态: 发现 {critical_count} 个严重问题，需要人工介入", "ERROR")
    elif error_count > 0:
        overall_status = "warning"
        _log(f"⚠️ 状态: 发现 {error_count} 个错误，已尝试自动修复")
    elif warning_count > 0:
        overall_status = "ok_with_warnings"
        _log(f"✅ 状态: 系统正常运行，有 {warning_count} 个警告")
    else:
        _log("✅ 状态: 系统完全正常")
    
    _log(f"📄 详细报告: {report_path}")
    _log("🏁 系统测试完成")
    
    return {
        "success": True,
        "overall_status": overall_status,
        "error_count": error_count,
        "warning_count": warning_count,
        "critical_count": critical_count,
        "report_path": str(report_path),
        "health_data": health_data
    }


def run(inputs: dict) -> dict:
    """
    Skill 入口函数
    
    输入参数:
        action: 操作类型 (默认: "run")
            - "run": 运行完整系统测试
            - "quick": 快速检查（仅检查日志）
            - "health": 检查系统健康状态
            - "cron_status": 检查Cron任务状态
            - "register_cron": 注册12小时定时任务
    """
    action = inputs.get("action", "run")
    
    try:
        if action == "run":
            return _run_system_test()
        
        elif action == "quick":
            log_result = _check_error_logs()
            return {
                "success": True,
                "action": "quick",
                "summary": log_result["summary"],
                "critical_errors": log_result["patterns"]["CRITICAL"][:5]
            }
        
        elif action == "health":
            health = _check_system_health()
            return {
                "success": True,
                "action": "health",
                "health": health
            }
        
        elif action == "cron_status":
            status = _check_cron_status()
            return {
                "success": True,
                "action": "cron_status",
                "status": status
            }
        
        elif action == "register_cron":
            # 注册12小时定时任务
            try:
                sys.path.insert(0, str(BASE_DIR))
                from runtime.cron import cron_system
                
                result = cron_system.add_interval(
                    name='system_test_12h',
                    seconds=43200,  # 12小时
                    skill_name='system_test',
                    input_data={'action': 'run'},
                    governor_required=False
                )
                
                return {
                    "success": True,
                    "action": "register_cron",
                    "result": str(result)
                }
            except Exception as e:
                return {
                    "success": False,
                    "action": "register_cron",
                    "error": str(e)
                }
        
        else:
            return {
                "success": False,
                "error": f"未知 action: {action}",
                "available_actions": ["run", "quick", "health", "cron_status", "register_cron"]
            }
    
    except Exception as e:
        logger.error("[system_test] %s failed: %s", action, e)
        return {
            "success": False,
            "error": str(e),
            "action": action
        }


if __name__ == "__main__":
    # 手动测试
    result = run({'action': 'run'})
    print(json.dumps(result, ensure_ascii=False, indent=2))
