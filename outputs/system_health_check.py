#!/usr/bin/env python3
"""
ArcMind 系统状态检查脚本
检测关键指标和服务运行状态
"""

import os
import sys
import sqlite3
import subprocess
import json
from datetime import datetime
from pathlib import Path

# 项目根目录
PROJECT_ROOT = Path("/Users/eason/Code/arcmind")
OUTPUT_DIR = PROJECT_ROOT / "outputs"
DB_PATH = PROJECT_ROOT / "data" / "arcmind.db"

class SystemHealthChecker:
    def __init__(self):
        self.results = []
        self.timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    def add_result(self, name, status, details=""):
        self.results.append({
            "name": name,
            "status": status,  # "OK" / "WARN" / "ERROR"
            "details": details
        })
    
    def check_tasktracker(self):
        """检查 TaskTracker 任务状态"""
        try:
            if not DB_PATH.exists():
                self.add_result("TaskTracker", "ERROR", "数据库文件不存在")
                return
            
            conn = sqlite3.connect(str(DB_PATH))
            cursor = conn.cursor()
            
            # 检查表是否存在
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='task_tracker'")
            if not cursor.fetchone():
                conn.close()
                self.add_result("TaskTracker", "WARN", "task_tracker 表未创建")
                return
            
            # 查询任务统计
            cursor.execute("SELECT status, COUNT(*) FROM task_tracker GROUP BY status")
            stats = cursor.fetchall()
            
            total = sum(s[1] for s in stats)
            stats_str = ", ".join([f"{s[0]}:{s[1]}" for s in stats]) if stats else "无数据"
            
            # 检查是否有卡住的任务 (>1小时未完成)
            try:
                cursor.execute("""
                    SELECT COUNT(*) FROM task_tracker 
                    WHERE status IN ('created', 'executing') 
                    AND created_at < datetime('now', '-1 hour')
                """)
                stuck = cursor.fetchone()[0]
            except:
                stuck = 0
            
            conn.close()
            
            if stuck > 0:
                self.add_result("TaskTracker", "WARN", f"总计 {total} 任务 ({stats_str}), {stuck} 个卡住")
            else:
                self.add_result("TaskTracker", "OK", f"总计 {total} 任务 ({stats_str})")
                
        except Exception as e:
            self.add_result("TaskTracker", "ERROR", str(e))
    
    def check_pm_workers(self):
        """检查 PM Workers 活跃数"""
        try:
            # 检查 PM 工作目录
            pm_dir = PROJECT_ROOT / ".agents" / "pm"
            
            # 尝试获取 Python 进程信息
            result = subprocess.run(
                ["pgrep", "-f", "pm_pool|PMPool|project_manager"],
                capture_output=True,
                text=True
            )
            
            active_count = len(result.stdout.strip().split("\n")) if result.stdout.strip() else 0
            
            if active_count > 0:
                self.add_result("PM Workers", "OK", f"{active_count} 个活跃进程")
            else:
                self.add_result("PM Workers", "WARN", "无活跃 PM Worker 进程")
                
        except Exception as e:
            self.add_result("PM Workers", "ERROR", str(e))
    
    def check_database(self):
        """检查数据库连接状态"""
        try:
            if not DB_PATH.exists():
                self.add_result("Database", "ERROR", "数据库文件不存在")
                return
            
            conn = sqlite3.connect(str(DB_PATH))
            cursor = conn.cursor()
            
            # 获取表列表
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = cursor.fetchall()
            
            table_count = len(tables)
            
            # 获取任务总数
            try:
                cursor.execute("SELECT COUNT(*) FROM task_tracker")
                task_count = cursor.fetchone()[0]
            except:
                task_count = 0
            
            conn.close()
            
            if table_count == 0:
                self.add_result("Database", "WARN", "数据库为空，无表")
            else:
                self.add_result("Database", "OK", f"{table_count} 表, {task_count} 任务记录")
            
        except Exception as e:
            self.add_result("Database", "ERROR", str(e))
    
    def check_cron(self):
        """检查 Cron 服务状态"""
        try:
            # 检查 cron 服务 (macOS)
            result = subprocess.run(
                ["pgrep", "-x", "cron"],
                capture_output=True,
                text=True
            )
            
            if result.stdout.strip():
                self.add_result("Cron Service", "OK", "服务运行中")
            else:
                self.add_result("Cron Service", "WARN", "服务未运行")
                
        except Exception as e:
            self.add_result("Cron Service", "ERROR", str(e))
    
    def check_api_service(self):
        """检查 API 服务状态"""
        try:
            # 检查 API 进程
            result = subprocess.run(
                ["pgrep", "-f", "api/server.py|uvicorn|fastapi"],
                capture_output=True,
                text=True
            )
            
            if result.stdout.strip():
                pids = result.stdout.strip().split("\n")
                self.add_result("API Service", "OK", f"PIDs: {', '.join(pids)}")
            else:
                self.add_result("API Service", "WARN", "API 服务未运行")
                
        except Exception as e:
            self.add_result("API Service", "ERROR", str(e))
    
    def check_disk(self):
        """检查磁盘使用率"""
        try:
            result = subprocess.run(
                ["df", "-h", str(PROJECT_ROOT)],
                capture_output=True,
                text=True
            )
            
            lines = result.stdout.strip().split("\n")
            if len(lines) >= 2:
                parts = lines[1].split()
                usage = parts[4] if len(parts) > 4 else parts[3]
                
                # 提取数字
                usage_pct = int(usage.replace("%", ""))
                
                if usage_pct > 90:
                    self.add_result("Disk Usage", "ERROR", f"{usage} 使用中")
                elif usage_pct > 80:
                    self.add_result("Disk Usage", "WARN", f"{usage} 使用中")
                else:
                    self.add_result("Disk Usage", "OK", f"{usage} 使用中")
            else:
                self.add_result("Disk Usage", "ERROR", "无法获取磁盘信息")
                
        except Exception as e:
            self.add_result("Disk Usage", "ERROR", str(e))
    
    def check_memory(self):
        """检查内存使用率"""
        try:
            result = subprocess.run(
                ["vm_stat"],
                capture_output=True,
                text=True
            )
            
            if result.stdout:
                lines = result.stdout.strip().split("\n")
                stats = {}
                for line in lines:
                    if ":" in line:
                        key = line.split(":")[0].strip().replace(" ", "_")
                        val = line.split(":")[1].strip().replace(".", "")
                        try:
                            stats[key] = int(val)
                        except:
                            pass
                
                if "Pages_Active" in stats and "Pages_Free" in stats:
                    total = stats.get("Pages_Active", 0) + stats.get("Pages_Free", 0) + stats.get("Pages_Inactive", 0)
                    if total > 0:
                        usage = stats.get("Pages_Active", 0) / total * 100
                        
                        if usage > 90:
                            self.add_result("Memory Usage", "ERROR", f"{usage:.1f}%")
                        elif usage > 80:
                            self.add_result("Memory Usage", "WARN", f"{usage:.1f}%")
                        else:
                            self.add_result("Memory Usage", "OK", f"{usage:.1f}%")
                        return
            
            # 备用方案
            result = subprocess.run(
                ["top", "-l", "1", "-n", "0"],
                capture_output=True,
                text=True
            )
            
            for line in result.stdout.split("\n"):
                if "PhysMem" in line:
                    self.add_result("Memory Usage", "OK", line.strip())
                    return
            
            self.add_result("Memory Usage", "WARN", "无法获取内存信息")
            
        except Exception as e:
            self.add_result("Memory Usage", "ERROR", str(e))
    
    def generate_report(self):
        """生成报告"""
        # 统计
        ok_count = sum(1 for r in self.results if r["status"] == "OK")
        warn_count = sum(1 for r in self.results if r["status"] == "WARN")
        error_count = sum(1 for r in self.results if r["status"] == "ERROR")
        
        # 生成 Markdown 报告
        md_content = f"""# ArcMind 系统状态检查报告

**检查时间**: {self.timestamp}

## 检查结果汇总

| 状态 | 数量 |
|------|------|
| ✅ 正常 | {ok_count} |
| ⚠️ 警告 | {warn_count} |
| ❌ 错误 | {error_count} |

---

## 详细检查结果

| 检查项 | 状态 | 详情 |
|--------|------|------|
"""
        
        for r in self.results:
            icon = {"OK": "✅", "WARN": "⚠️", "ERROR": "❌"}[r["status"]]
            md_content += f"| {r['name']} | {icon} {r['status']} | {r['details']} |\n"
        
        md_content += f"""
---

## 系统健康评估

{"🎉 系统运行正常" if error_count == 0 else "⚠️ 系统存在警告/错误，请检查"}

"""
        
        return md_content, ok_count, warn_count, error_count
    
    def run_all_checks(self):
        """运行所有检查"""
        print("🔍 开始系统状态检查...\n")
        
        self.check_tasktracker()
        self.check_pm_workers()
        self.check_database()
        self.check_cron()
        self.check_api_service()
        self.check_disk()
        self.check_memory()
        
        return self.generate_report()


def main():
    checker = SystemHealthChecker()
    md_content, ok, warn, error = checker.run_all_checks()
    
    # 输出到控制台
    print(md_content)
    
    # 保存到文件
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = OUTPUT_DIR / f"system_status_{timestamp}.md"
    
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(md_content)
    
    print(f"\n📄 报告已保存到: {output_file}")
    
    # 返回退出码
    sys.exit(0 if error == 0 else 1)


if __name__ == "__main__":
    main()
