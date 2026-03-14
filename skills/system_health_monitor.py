"""
Skill: system_health_monitor
系统健康监控 — 每12小时自动检测系统状态、错误日志、异常修复迭代

功能：
1. 每12小时运行系统健康检查（CPU/内存/磁盘/数据库/进程）
2. 检查错误日志（outputs 目录下的 error*.md 文件）
3. 检测系统异常并自动修复迭代
4. 生成健康报告并支持定时执行

定时任务设置：
- schedule: "0 */12 * * *" (每12小时)
- 或使用 action=run_now 立即执行
"""
from __future__ import annotations
import json
import logging
import os
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("arcmind.skill.system_health_monitor")

# 项目根目录
PROJECT_ROOT = Path("/Users/eason/Code/arcmind")
OUTPUT_DIR = PROJECT_ROOT / "outputs"
DB_PATH = PROJECT_ROOT / "data" / "arcmind.db"
ERROR_LOG_DIR = OUTPUT_DIR


def _check_system_health() -> dict:
    """执行系统健康检查"""
    results = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "checks": [],
        "errors": [],
        "warnings": []
    }
    
    # 1. 检查数据库连接
    try:
        if not DB_PATH.exists():
            results["errors"].append(f"数据库文件不存在: {DB_PATH}")
        else:
            conn = sqlite3.connect(str(DB_PATH))
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = cursor.fetchall()
            results["checks"].append(f"Database: OK ({len(tables)} tables)")
            conn.close()
    except Exception as e:
        results["errors"].append(f"Database: {str(e)}")
    
    # 2. 检查磁盘空间
    try:
        result = subprocess.run(
            ["df", "-h", str(PROJECT_ROOT)],
            capture_output=True,
            text=True,
            timeout=10
        )
        lines = result.stdout.strip().split("\n")
        if len(lines) >= 2:
            parts = lines[1].split()
            usage = parts[4] if len(parts) > 4 else parts[3]
            usage_pct = int(usage.replace("%", ""))
            if usage_pct > 90:
                results["errors"].append(f"Disk usage: {usage} (CRITICAL)")
            elif usage_pct > 80:
                results["warnings"].append(f"Disk usage: {usage} (Warning)")
            else:
                results["checks"].append(f"Disk usage: {usage}")
    except Exception as e:
        results["warnings"].append(f"Disk check failed: {str(e)}")
    
    # 3. 检查 PM Workers 进程
    try:
        result = subprocess.run(
            ["pgrep", "-f", "pm_pool|PMPool|project_manager"],
            capture_output=True,
            text=True,
            timeout=10
        )
        active_count = len(result.stdout.strip().split("\n")) if result.stdout.strip() else 0
        if active_count > 0:
            results["checks"].append(f"PM Workers: {active_count} active")
        else:
            results["warnings"].append("PM Workers: No active processes")
    except Exception as e:
        results["warnings"].append(f"PM Workers check failed: {str(e)}")
    
    # 4. 检查 API 服务
    try:
        result = subprocess.run(
            ["pgrep", "-f", "api/server.py|uvicorn|fastapi"],
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.stdout.strip():
            results["checks"].append("API Service: Running")
        else:
            results["warnings"].append("API Service: Not running")
    except Exception as e:
        results["warnings"].append(f"API Service check failed: {str(e)}")
    
    # 5. 检查 TaskTracker 任务状态
    try:
        if DB_PATH.exists():
            conn = sqlite3.connect(str(DB_PATH))
            cursor = conn.cursor()
            
            # 检查卡住的任务
            cursor.execute("""
                SELECT COUNT(*) FROM task_tracker 
                WHERE status IN ('created', 'executing') 
                AND created_at < datetime('now', '-1 hour')
            """)
            stuck = cursor.fetchone()[0]
            
            # 获取总任务数
            cursor.execute("SELECT COUNT(*) FROM task_tracker")
            total = cursor.fetchone()[0]
            
            conn.close()
            
            if stuck > 0:
                results["warnings"].append(f"TaskTracker: {stuck} stuck tasks / {total} total")
            else:
                results["checks"].append(f"TaskTracker: {total} tasks")
    except Exception as e:
        results["warnings"].append(f"TaskTracker check failed: {str(e)}")
    
    # 6. 检查 Cron 服务
    try:
        result = subprocess.run(
            ["pgrep", "-x", "cron"],
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.stdout.strip():
            results["checks"].append("Cron Service: Running")
        else:
            results["warnings"].append("Cron Service: Not running")
    except Exception as e:
        results["warnings"].append(f"Cron check failed: {str(e)}")
    
    return results


def _check_error_logs() -> dict:
    """检查错误日志"""
    error_results = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "error_files": [],
        "total_errors": 0,
        "recent_errors": []
    }
    
    try:
        if not ERROR_LOG_DIR.exists():
            error_results["error_files"].append("Error log directory not found")
            return error_results
        
        # 查找 error*.md 文件
        error_files = list(ERROR_LOG_DIR.glob("error*.md"))
        
        for error_file in error_files:
            try:
                content = error_file.read_text(encoding="utf-8")
                lines = content.split("\n")
                
                # 统计错误数量
                error_count = sum(1 for line in lines if "ERROR" in line.upper() or "❌" in line)
                
                if error_count > 0:
                    error_results["error_files"].append({
                        "file": error_file.name,
                        "errors": error_count,
                        "path": str(error_file)
                    })
                    error_results["total_errors"] += error_count
                    
                    # 获取最近的错误
                    for line in lines:
                        if "ERROR" in line.upper() or "❌" in line:
                            error_results["recent_errors"].append({
                                "file": error_file.name,
                                "message": line.strip()[:100]
                            })
                            if len(error_results["recent_errors"]) >= 10:
                                break
            except Exception as e:
                logger.warning(f"Failed to read {error_file}: {e}")
        
        # 也检查最新的系统状态报告
        status_files = sorted(ERROR_LOG_DIR.glob("system_status_*.md"), reverse=True)
        if status_files:
            latest_status = status_files[0]
            content = latest_status.read_text(encoding="utf-8")
            if "ERROR" in content or "❌" in content:
                error_results["recent_errors"].append({
                    "file": latest_status.name,
                    "message": "System status contains errors"
                })
                
    except Exception as e:
        logger.error(f"Error checking logs: {e}")
        error_results["error_files"].append(f"Check failed: {str(e)}")
    
    return error_results


def _auto_repair(health_check: dict, error_check: dict) -> dict:
    """自动修复尝试"""
    repair_results = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "actions": [],
        "success": True
    }
    
    # 1. 如果有卡住的任务，尝试清理
    try:
        if "stuck" in str(health_check.get("warnings", [])):
            if DB_PATH.exists():
                conn = sqlite3.connect(str(DB_PATH))
                cursor = conn.cursor()
                
                # 将超时的 executing 任务重置为 failed
                cursor.execute("""
                    UPDATE task_tracker 
                    SET status = 'failed', updated_at = datetime('now')
                    WHERE status = 'executing' 
                    AND updated_at < datetime('now', '-2 hours')
                """)
                
                updated = cursor.rowcount
                conn.commit()
                conn.close()
                
                if updated > 0:
                    repair_results["actions"].append(f"Reset {updated} stuck tasks to failed")
        else:
            repair_results["actions"].append("No stuck tasks to repair")
    except Exception as e:
        repair_results["actions"].append(f"Task repair failed: {str(e)}")
        repair_results["success"] = False
    
    # 2. 如果有错误日志，生成错误分析报告
    if error_check.get("total_errors", 0) > 0:
        try:
            report_path = OUTPUT_DIR / f"auto_repair_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
            report_content = f"""# 自动修复报告

**生成时间**: {repair_results['timestamp']}

## 检测到的错误

### 错误日志统计
- 总错误文件数: {len(error_check.get('error_files', []))}
- 总错误数: {error_check.get('total_errors', 0)}

### 最近错误
"""
            for err in error_check.get("recent_errors", [])[:5]:
                report_content += f"- **{err['file']}**: {err['message']}\n"
            
            report_content += f"""
## 执行的修复操作

"""
            for action in repair_results["actions"]:
                report_content += f"- {action}\n"
            
            report_content += f"""
## 状态

{"✅ 修复完成" if repair_results["success"] else "⚠️ 部分修复失败"}

"""
            report_path.write_text(report_content, encoding="utf-8")
            repair_results["actions"].append(f"Generated report: {report_path.name}")
        except Exception as e:
            repair_results["actions"].append(f"Report generation failed: {str(e)}")
    
    return repair_results


def _generate_report(health_check: dict, error_check: dict, repair: dict) -> dict:
    """生成综合健康报告"""
    
    # 统计状态
    total_checks = len(health_check.get("checks", []))
    total_warnings = len(health_check.get("warnings", []))
    total_errors = len(health_check.get("errors", []))
    
    # 确定整体状态
    if total_errors > 0:
        overall_status = "ERROR"
    elif total_warnings > 0:
        overall_status = "WARNING"
    else:
        overall_status = "OK"
    
    # 生成 Markdown 报告
    md_content = f"""# ArcMind 系统健康监控报告

**检查时间**: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

## 整体状态: {"✅ 正常" if overall_status == "OK" else "⚠️ 警告" if overall_status == "WARNING" else "❌ 错误"}

---

## 1. 系统健康检查

| 类型 | 数量 |
|------|------|
| ✅ 正常 | {total_checks} |
| ⚠️ 警告 | {total_warnings} |
| ❌ 错误 | {total_errors} |

### 检查详情

"""
    for check in health_check.get("checks", []):
        md_content += f"- ✅ {check}\n"
    for warning in health_check.get("warnings", []):
        md_content += f"- ⚠️ {warning}\n"
    for error in health_check.get("errors", []):
        md_content += f"- ❌ {error}\n"
    
    md_content += f"""
---

## 2. 错误日志检查

| 项目 | 数量 |
|------|------|
| 错误文件 | {len(error_check.get("error_files", []))} |
| 总错误数 | {error_check.get("total_errors", 0)} |

### 最近错误

"""
    for err in error_check.get("recent_errors", [])[:5]:
        md_content += f"- **{err['file']}**: {err['message']}\n"
    
    if not error_check.get("recent_errors"):
        md_content += "- 无最近错误\n"
    
    md_content += f"""
---

## 3. 自动修复

| 项目 | 结果 |
|------|------|
| 修复状态 | {"✅ 成功" if repair.get("success") else "⚠️ 部分失败"} |
| 修复操作 | {len(repair.get("actions", []))} |

### 执行的操作

"""
    for action in repair.get("actions", []):
        md_content += f"- {action}\n"
    
    md_content += f"""
---

## 下次检查

**预定时间**: 每12小时自动执行

**定时表达式**: `0 */12 * * *`

"""
    
    # 保存报告
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = OUTPUT_DIR / f"health_monitor_report_{timestamp}.md"
    
    try:
        report_path.write_text(md_content, encoding="utf-8")
    except Exception as e:
        logger.error(f"Failed to write report: {e}")
    
    return {
        "status": overall_status,
        "checks": total_checks,
        "warnings": total_warnings,
        "errors": total_errors,
        "report_path": str(report_path),
        "total_errors_in_logs": error_check.get("total_errors", 0),
        "repair_success": repair.get("success", False)
    }


def run(inputs: dict) -> dict:
    """
    执行系统健康监控
    
    Args:
        inputs: 包含 action 参数
            - action: "run_now" (立即执行) / "status" (查看状态)
    
    Returns:
        dict: 检查结果和报告路径
    """
    action = inputs.get("action", "run_now")
    
    try:
        if action == "status":
            # 只是状态查询，不执行完整检查
            return {
                "success": True,
                "message": "Use action='run_now' to execute health check",
                "schedule": "0 */12 * * * (every 12 hours)"
            }
        
        # 执行完整的健康检查
        logger.info("Starting system health check...")
        
        # 1. 系统健康检查
        health_check = _check_system_health()
        
        # 2. 错误日志检查
        error_check = _check_error_logs()
        
        # 3. 自动修复迭代
        repair = _auto_repair(health_check, error_check)
        
        # 4. 生成报告
        report = _generate_report(health_check, error_check, repair)
        
        return {
            "success": True,
            "status": report["status"],
            "checks_passed": report["checks"],
            "warnings": report["warnings"],
            "errors": report["errors"],
            "error_logs_found": report["total_errors_in_logs"],
            "repair_completed": report["repair_success"],
            "report_path": report["report_path"],
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return {
            "success": False,
            "error": str(e)
        }


if __name__ == "__main__":
    # 独立运行测试
    result = run({"action": "run_now"})
    print(json.dumps(result, indent=2, ensure_ascii=False))
