#!/usr/bin/env python3
"""
自动修复脚本 - 依赖缺失
Auto-Repair: Dependency Missing

错误类型: Dependency Missing
触发条件: requirements.txt 未安装, 模块导入失败
"""

import os
import sys
import subprocess
from datetime import datetime

LOG_FILE = "logs/auto_repair_deps.log"

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

def get_missing_imports():
    """检测缺失的模块"""
    required_modules = [
        "psycopg2",
        "flask",
        "requests",
        "APScheduler",
        "sqlalchemy",
    ]
    
    missing = []
    for module in required_modules:
        try:
            __import__(module)
        except ImportError:
            missing.append(module)
    
    return missing

def check_requirements():
    """检查 requirements.txt"""
    if os.path.exists("requirements.txt"):
        log("✅ 找到 requirements.txt")
        return True
    else:
        log("⚠️ 未找到 requirements.txt")
        return False

def install_requirements():
    """安装依赖"""
    log("安装 Python 依赖...")
    
    if not os.path.exists("requirements.txt"):
        log("❌ requirements.txt 不存在")
        return False
    
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "-r", "requirements.txt"],
            capture_output=True,
            text=True,
            timeout=300
        )
        
        if result.returncode == 0:
            log("✅ 依赖安装成功")
            return True
        else:
            log(f"❌ 安装失败: {result.stderr}")
            return False
    except subprocess.TimeoutExpired:
        log("❌ 安装超时")
        return False
    except Exception as e:
        log(f"❌ 安装异常: {e}")
        return False

def install_module(module_name):
    """安装单个模块"""
    log(f"安装模块: {module_name}...")
    
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", module_name],
            capture_output=True,
            text=True,
            timeout=120
        )
        
        if result.returncode == 0:
            log(f"✅ {module_name} 安装成功")
            return True
        else:
            log(f"❌ {module_name} 安装失败: {result.stderr}")
            return False
    except Exception as e:
        log(f"❌ {module_name} 安装异常: {e}")
        return False

def check_virtual_env():
    """检查虚拟环境"""
    venv_path = ".venv" if os.path.exists(".venv") else "venv"
    
    if os.path.exists(venv_path):
        log(f"✅ 虚拟环境存在: {venv_path}")
        
        # 检查是否在虚拟环境中
        if hasattr(sys, 'real_prefix') or (hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix):
            log(f"✅ 当前在虚拟环境中运行")
            return True
        else:
            log(f"⚠️ 未激活虚拟环境")
            log(f"建议: source {venv_path}/bin/activate")
            return False
    else:
        log(f"⚠️ 虚拟环境不存在: {venv_path}")
        return False

def repair():
    """执行修复"""
    log("=== 开始修复: 依赖缺失 ===")
    
    # Step 1: 检查虚拟环境
    check_virtual_env()
    
    # Step 2: 检查 requirements.txt
    check_requirements()
    
    # Step 3: 检测缺失模块
    missing = get_missing_imports()
    
    if missing:
        log(f"⚠️ 缺失模块: {', '.join(missing)}")
        
        # 尝试安装
        for module in missing:
            install_module(module)
        
        # 重新检测
        missing = get_missing_imports()
        
        if missing:
            log(f"❌ 仍缺失: {', '.join(missing)}")
            return False
        else:
            log("✅ 所有依赖已安装")
            return True
    else:
        log("✅ 所有依赖已安装")
        return True

if __name__ == "__main__":
    success = repair()
    sys.exit(0 if success else 1)
