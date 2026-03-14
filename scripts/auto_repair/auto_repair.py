#!/usr/bin/env python3
"""
ArcMind 自动修复框架模板
========================
支持5种常见错误类型的自动检测与修复：
1. 数据库连接失败
2. API超时
3. 端口占用
4. 权限问题
5. 依赖缺失

功能特性：
- 自动检测错误类型
- 执行对应修复操作
- 记录修复日志
- 失败时回滚或告警
"""

import os
import sys
import time
import json
import subprocess
import logging
import traceback
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional, Dict, Any, Callable
import argparse

# ============== 配置 ==============
BASE_DIR = Path("/Users/eason/Code/arcmind")
LOG_DIR = BASE_DIR / "outputs" / "auto_repair"
LOG_DIR.mkdir(parents=True, exist_ok=True)

LOG_FILE = LOG_DIR / f"repair_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

# ============== 日志配置 ==============
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)


# ============== 错误类型枚举 ==============
class ErrorType(Enum):
    """支持自动修复的错误类型"""
    DB_CONNECTION_FAILED = "database_connection_failed"
    API_TIMEOUT = "api_timeout"
    PORT_OCCUPIED = "port_occupied"
    PERMISSION_DENIED = "permission_denied"
    DEPENDENCY_MISSING = "dependency_missing"
    UNKNOWN = "unknown"


class ErrorLevel(Enum):
    """错误级别"""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


# ============== 修复结果数据结构 ==============
class RepairResult:
    """修复操作结果"""
    def __init__(self, success: bool, message: str, details: Dict[str, Any] = None):
        self.success = success
        self.message = message
        self.details = details or {}
        self.timestamp = datetime.now().isoformat()
    
    def to_dict(self) -> Dict:
        return {
            "success": self.success,
            "message": self.message,
            "details": self.details,
            "timestamp": self.timestamp
        }


# ============== 修复器基类 ==============
class BaseRepair:
    """修复器基类"""
    
    def __init__(self, error_type: ErrorType):
        self.error_type = error_type
        self.repair_history: list[RepairResult] = []
    
    def detect(self) -> bool:
        """检测是否存在该类型错误"""
        raise NotImplementedError
    
    def repair(self) -> RepairResult:
        """执行修复操作"""
        raise NotImplementedError
    
    def rollback(self) -> RepairResult:
        """回滚操作（可选）"""
        return RepairResult(True, "无需回滚")
    
    def can_auto_repair(self) -> bool:
        """判断是否支持自动修复"""
        return True


# ============== 具体修复器实现 ==============

class DBConnectionRepair(BaseRepair):
    """数据库连接失败修复器"""
    
    def __init__(self):
        super().__init__(ErrorType.DB_CONNECTION_FAILED)
        self.db_path = BASE_DIR / "arcmind.db"
        self.backup_path = LOG_DIR / "db_backup"
    
    def detect(self) -> bool:
        """检测数据库连接问题"""
        logger.info("🔍 检测数据库连接状态...")
        
        # 检查SQLite文件是否存在
        if not self.db_path.exists():
            logger.warning("⚠️ 数据库文件不存在")
            return True
        
        # 检查外部数据库环境变量
        db_host = os.environ.get("DB_HOST")
        db_user = os.environ.get("DB_USER")
        db_name = os.environ.get("DB_NAME")
        
        if not db_host:
            logger.warning("⚠️ 外部数据库环境变量未配置 (DB_HOST/DB_USER/DB_NAME)")
            return True
        
        # 尝试连接测试
        try:
            import sqlite3
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            conn.close()
            logger.info("✅ 数据库连接正常")
            return False
        except Exception as e:
            logger.error(f"❌ 数据库连接失败: {e}")
            return True
    
    def repair(self) -> RepairResult:
        """执行数据库修复"""
        logger.info("🔧 开始修复数据库连接...")
        
        try:
            # 1. 备份当前数据库
            if self.db_path.exists():
                self.backup_path.mkdir(parents=True, exist_ok=True)
                backup_file = self.backup_path / f"arcmind_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
                import shutil
                shutil.copy2(self.db_path, backup_file)
                logger.info(f"✅ 已备份数据库到: {backup_file}")
            
            # 2. 初始化数据库表（如果不存在）
            import sqlite3
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()
            
            # 创建必要的表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS task_tracker (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT UNIQUE,
                    status TEXT,
                    priority TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()
            conn.close()
            
            logger.info("✅ 数据库表初始化完成")
            return RepairResult(True, "数据库连接修复成功", {"backup": str(backup_file)})
            
        except Exception as e:
            logger.error(f"❌ 数据库修复失败: {e}")
            return RepairResult(False, f"数据库修复失败: {str(e)}")
    
    def rollback(self) -> RepairResult:
        """回滚到备份"""
        try:
            backups = sorted(self.backup_path.glob("arcmind_*.db"), reverse=True)
            if backups:
                latest = backups[0]
                import shutil
                shutil.copy2(latest, self.db_path)
                return RepairResult(True, f"已回滚到: {latest}")
            return RepairResult(False, "无备份文件可回滚")
        except Exception as e:
            return RepairResult(False, f"回滚失败: {str(e)}")


class APITimeoutRepair(BaseRepair):
    """API超时修复器"""
    
    def __init__(self):
        super().__init__(ErrorType.API_TIMEOUT)
        self.api_port = 8100
    
    def detect(self) -> bool:
        """检测API超时问题"""
        logger.info("🔍 检测API服务状态...")
        
        import socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2)
        result = sock.connect_ex(('localhost', self.api_port))
        sock.close()
        
        if result != 0:
            logger.warning(f"⚠️ API服务端口 {self.api_port} 未开放")
            return True
        
        # 尝试实际请求
        try:
            import requests
            resp = requests.get(f"http://localhost:{self.api_port}/health", timeout=5)
            if resp.status_code == 200:
                logger.info("✅ API服务正常")
                return False
        except Exception as e:
            logger.warning(f"⚠️ API响应异常: {e}")
            return True
        
        return True
    
    def repair(self) -> RepairResult:
        """执行API修复"""
        logger.info("🔧 开始修复API服务...")
        
        try:
            # 1. 重启API服务
            api_script = BASE_DIR / "api" / "server.py"
            if not api_script.exists():
                return RepairResult(False, "API服务器脚本不存在")
            
            # 检查并杀掉旧进程
            result = subprocess.run(
                ["lsof", "-ti", f":{self.api_port}"],
                capture_output=True,
                text=True
            )
            if result.stdout.strip():
                pid = result.stdout.strip()
                subprocess.run(["kill", "-9", pid])
                logger.info(f"✅ 已终止旧进程: {pid}")
            
            # 启动新进程
            subprocess.Popen(
                [sys.executable, str(api_script)],
                cwd=str(BASE_DIR),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            
            # 等待启动
            time.sleep(3)
            
            return RepairResult(True, f"API服务已重启 (端口: {self.api_port})")
            
        except Exception as e:
            logger.error(f"❌ API修复失败: {e}")
            return RepairResult(False, f"API修复失败: {str(e)}")


class PortOccupiedRepair(BaseRepair):
    """端口占用修复器"""
    
    def __init__(self, port: int = 8100):
        super().__init__(ErrorType.PORT_OCCUPIED)
        self.port = port
    
    def detect(self) -> bool:
        """检测端口占用"""
        logger.info(f"🔍 检测端口 {self.port} 占用情况...")
        
        result = subprocess.run(
            ["lsof", "-ti", f":{self.port}"],
            capture_output=True,
            text=True
        )
        
        if result.stdout.strip():
            logger.warning(f"⚠️ 端口 {self.port} 被占用: {result.stdout.strip()}")
            return True
        
        logger.info(f"✅ 端口 {self.port} 空闲")
        return False
    
    def repair(self) -> RepairResult:
        """释放占用端口"""
        logger.info(f"🔧 释放端口 {self.port}...")
        
        result = subprocess.run(
            ["lsof", "-ti", f":{self.port}"],
            capture_output=True,
            text=True
        )
        
        if result.stdout.strip():
            pid = result.stdout.strip()
            subprocess.run(["kill", "-9", pid])
            return RepairResult(True, f"已释放端口 {self.port} (PID: {pid})")
        
        return RepairResult(False, f"端口 {self.port} 无进程占用")


class PermissionRepair(BaseRepair):
    """权限问题修复器"""
    
    def __init__(self):
        super().__init__(ErrorType.PERMISSION_DENIED)
    
    def detect(self) -> bool:
        """检测权限问题"""
        logger.info("🔍 检测关键目录权限...")
        
        check_dirs = [
            BASE_DIR / "outputs",
            BASE_DIR / "scripts",
            BASE_DIR / "api"
        ]
        
        for d in check_dirs:
            if not d.exists():
                continue
            if not os.access(d, os.W_OK):
                logger.warning(f"⚠️ 目录不可写: {d}")
                return True
        
        return False
    
    def repair(self) -> RepairResult:
        """修复权限问题"""
        logger.info("🔧 修复目录权限...")
        
        try:
            dirs_to_fix = [
                BASE_DIR / "outputs",
                BASE_DIR / "scripts",
                BASE_DIR / "api"
            ]
            
            for d in dirs_to_fix:
                d.mkdir(parents=True, exist_ok=True)
                os.chmod(d, 0o755)
            
            return RepairResult(True, "权限修复完成")
            
        except Exception as e:
            return RepairResult(False, f"权限修复失败: {str(e)}")


class DependencyRepair(BaseRepair):
    """依赖缺失修复器"""
    
    def __init__(self):
        super().__init__(ErrorType.DEPENDENCY_MISSING)
    
    def detect(self) -> bool:
        """检测依赖缺失"""
        logger.info("🔍 检测核心依赖...")
        
        required_modules = [
            "sqlite3", "json", "logging", "pathlib",
            "requests", "flask"
        ]
        
        missing = []
        for mod in required_modules:
            try:
                __import__(mod)
            except ImportError:
                missing.append(mod)
        
        if missing:
            logger.warning(f"⚠️ 缺失依赖: {missing}")
            return True
        
        return False
    
    def repair(self) -> RepairResult:
        """安装缺失依赖"""
        logger.info("🔧 安装缺失依赖...")
        
        try:
            subprocess.run(
                [sys.executable, "-m", "pip", "install", "-r", str(BASE_DIR / "requirements.txt")],
                capture_output=True,
                timeout=120
            )
            return RepairResult(True, "依赖安装完成")
        except Exception as e:
            return RepairResult(False, f"依赖安装失败: {str(e)}")


# ============== 修复管理器 ==============
class AutoRepairManager:
    """自动修复管理器"""
    
    REPAIR_MAP: Dict[ErrorType, type] = {
        ErrorType.DB_CONNECTION_FAILED: DBConnectionRepair,
        ErrorType.API_TIMEOUT: APITimeoutRepair,
        ErrorType.PORT_OCCUPIED: PortOccupiedRepair,
        ErrorType.PERMISSION_DENIED: PermissionRepair,
        ErrorType.DEPENDENCY_MISSING: DependencyRepair,
    }
    
    def __init__(self):
        self.repairs: Dict[ErrorType, BaseRepair] = {}
        self.results: list[RepairResult] = []
        
        # 初始化所有修复器
        for err_type, repair_class in self.REPAIR_MAP.items():
            self.repairs[err_type] = repair_class()
    
    def detect_all(self) -> Dict[ErrorType, bool]:
        """检测所有错误类型"""
        logger.info("=" * 50)
        logger.info("🚀 开始全面错误检测...")
        logger.info("=" * 50)
        
        detected = {}
        for err_type, repair in self.repairs.items():
            try:
                is_error = repair.detect()
                detected[err_type] = is_error
            except Exception as e:
                logger.error(f"检测 {err_type.value} 时出错: {e}")
                detected[err_type] = True  # 视为检测到问题
        
        return detected
    
    def auto_repair(self, error_types: Optional[list[ErrorType]] = None) -> list[RepairResult]:
        """自动修复指定错误类型"""
        logger.info("=" * 50)
        logger.info("🔧 开始自动修复...")
        logger.info("=" * 50)
        
        results = []
        
        # 确定要修复的类型
        if error_types is None:
            detected = self.detect_all()
            error_types = [et for et, has_error in detected.items() if has_error]
        
        for err_type in error_types:
            if err_type not in self.repairs:
                logger.warning(f"未知错误类型: {err_type}")
                continue
            
            repair = self.repairs[err_type]
            
            # 检测
            if not repair.detect():
                logger.info(f"✅ {err_type.value} 无需修复")
                results.append(RepairResult(True, f"{err_type.value} 状态正常"))
                continue
            
            # 修复
            logger.info(f"🔧 修复 {err_type.value}...")
            result = repair.repair()
            results.append(result)
            self.results.append(result)
            
            # 如果修复失败，尝试回滚
            if not result.success:
                logger.warning(f"⚠️ 修复失败，尝试回滚...")
                rollback_result = repair.rollback()
                results.append(rollback_result)
        
        return results
    
    def save_report(self) -> Path:
        """保存修复报告"""
        report = {
            "timestamp": datetime.now().isoformat(),
            "results": [r.to_dict() for r in self.results]
        }
        
        report_path = LOG_DIR / f"repair_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(report_path, 'w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        
        logger.info(f"📄 报告已保存: {report_path}")
        return report_path


# ============== CLI 入口 ==============
def main():
    parser = argparse.ArgumentParser(description="ArcMind 自动修复工具")
    parser.add_argument("--detect-only", "-d", action="store_true", 
                        help="仅检测，不执行修复")
    parser.add_argument("--error-type", "-e", 
                        choices=[et.value for et in ErrorType],
                        help="指定要修复的错误类型")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="详细输出")
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    manager = AutoRepairManager()
    
    # 检测阶段
    detected = manager.detect_all()
    
    print("\n" + "=" * 50)
    print("📊 检测结果汇总")
    print("=" * 50)
    
    for err_type, has_error in detected.items():
        status = "❌ 存在问题" if has_error else "✅ 正常"
        print(f"  {err_type.value:30s} {status}")
    
    # 统计
    error_count = sum(1 for v in detected.values() if v)
    print(f"\n总计: {error_count} 项需要修复")
    
    if args.detect_only:
        sys.exit(0 if error_count == 0 else 1)
    
    # 修复阶段
    if error_count > 0:
        print("\n" + "=" * 50)
        print("🔧 执行自动修复...")
        print("=" * 50)
        
        error_types = None
        if args.error_type:
            error_types = [ErrorType(args.error_type)]
        
        results = manager.auto_repair(error_types)
        
        # 汇总
        print("\n" + "=" * 50)
        print("📋 修复结果")
        print("=" * 50)
        
        success_count = 0
        for r in results:
            status = "✅ 成功" if r.success else "❌ 失败"
            print(f"  {status}: {r.message}")
            if r.success:
                success_count += 1
        
        print(f"\n修复成功率: {success_count}/{len(results)}")
        
        # 保存报告
        manager.save_report()


if __name__ == "__main__":
    main()
