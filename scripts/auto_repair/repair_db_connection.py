#!/usr/bin/env python3
"""
自动修复脚本 - 数据库连接失败
Auto-Repair: Database Connection Error

错误类型: Database Connection Error
触发条件: DB_HOST/USER/NAME 环境变量未设置, PostgreSQL 服务未启动
"""

import os
import sys
import subprocess
from datetime import datetime

LOG_FILE = "logs/auto_repair_db.log"

def log(msg):
    """日志输出"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_msg = f"[{timestamp}] {msg}"
    print(log_msg)
    try:
        os.makedirs("logs", exist_ok=True)
        with open(LOG_FILE, "a") as f:
            f.write(log_msg + "\n")
    except:
        pass

def check_db_env():
    """检查数据库环境变量"""
    required_vars = ["DB_HOST", "DB_USER", "DB_NAME", "DB_PASSWORD"]
    missing = []
    for var in required_vars:
        if not os.environ.get(var):
            missing.append(var)
    return missing

def repair():
    """执行修复"""
    log("=== 开始修复: 数据库连接失败 ===")
    
    # Step 1: 检查环境变量
    missing = check_db_env()
    if missing:
        log(f"⚠️ 缺少环境变量: {', '.join(missing)}")
        log("请在 .env 文件中配置以下变量:")
        for var in missing:
            print(f"  {var}=your_value")
        
        # 尝试创建示例 .env 文件
        if not os.path.exists(".env"):
            try:
                with open(".env.example", "w") as f:
                    f.write("# 数据库配置\n")
                    f.write("DB_HOST=localhost\n")
                    f.write("DB_USER=postgres\n")
                    f.write("DB_NAME=arcmind\n")
                    f.write("DB_PASSWORD=your_password\n")
                log("✅ 已创建 .env.example 模板文件")
            except Exception as e:
                log(f"❌ 创建模板失败: {e}")
        return False
    
    # Step 2: 检查 PostgreSQL 服务
    log("检查 PostgreSQL 服务...")
    try:
        result = subprocess.run(["pg_isready"], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            log("✅ PostgreSQL 服务运行正常")
        else:
            log("⚠️ PostgreSQL 服务未运行")
            log("尝试启动: brew services start postgresql")
            subprocess.run(["brew", "services", "start", "postgresql"], check=False)
    except FileNotFoundError:
        log("⚠️ pg_isready 未安装，请安装 PostgreSQL")
    except Exception as e:
        log(f"⚠️ 检查 PostgreSQL 失败: {e}")
    
    # Step 3: 测试连接
    log("测试数据库连接...")
    try:
        import psycopg2
        conn = psycopg2.connect(
            host=os.environ.get("DB_HOST"),
            user=os.environ.get("DB_USER"),
            password=os.environ.get("DB_PASSWORD"),
            dbname=os.environ.get("DB_NAME")
        )
        conn.close()
        log("✅ 数据库连接成功")
        return True
    except ImportError:
        log("⚠️ psycopg2 未安装，执行: pip install psycopg2-binary")
        return False
    except Exception as e:
        log(f"❌ 连接失败: {e}")
        return False

if __name__ == "__main__":
    success = repair()
    sys.exit(0 if success else 1)
