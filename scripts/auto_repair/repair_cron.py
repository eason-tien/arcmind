#!/usr/bin/env python3
"""
自动修复脚本 - Cron 服务未启动
Auto-Repair: Cron Service Not Running

错误类型: Cron Service Not Running
触发条件: Cron 调度器未启动, 定时任务未注册
"""

import os
import sys
import subprocess
import time
from datetime import datetime

LOG_FILE = "logs/auto_repair_cron.log"

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

def check_cron_status():
    """检查 Cron 状态"""
    log("检查 Cron 服务状态...")
    
    # 尝试导入 APScheduler
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.schedulers import _running
        
        scheduler = BackgroundScheduler()
        
        # 检查调度器状态
        if hasattr(scheduler, 'running') and scheduler.running:
            log("✅ Cron 调度器运行中")
            return True
        else:
            log("⚠️ Cron 调度器未运行")
            return False
    except ImportError:
        log("⚠️ APScheduler 未安装")
        return False
    except Exception as e:
        log(f"⚠️ 检查失败: {e}")
        return False

def start_cron_service():
    """启动 Cron 服务"""
    log("启动 Cron 服务...")
    
    # 方法1: 尝试启动内置 cron
    cron_script = "scripts/start_cron.py"
    
    if os.path.exists(cron_script):
        log(f"执行启动脚本: {cron_script}")
        try:
            result = subprocess.run(
                [sys.executable, cron_script],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode == 0:
                log("✅ Cron 服务已启动")
                return True
            else:
                log(f"⚠️ 启动脚本执行失败: {result.stderr}")
        except Exception as e:
            log(f"❌ 启动失败: {e}")
    else:
        log(f"⚠️ 启动脚本不存在: {cron_script}")
    
    return False

def check_system_cron():
    """检查系统 Cron (macOS)"""
    if sys.platform != "darwin":
        return False
    
    log("检查 macOS 系统 Cron...")
    
    # 检查 cron 进程
    result = subprocess.run(
        ["pgrep", "-fl", "cron"],
        capture_output=True,
        text=True
    )
    
    if result.returncode == 0 and result.stdout:
        log(f"✅ 系统 Cron 运行中: {result.stdout.strip()}")
        return True
    else:
        log("⚠️ 系统 Cron 未运行")
        
        # 尝试启动 launchctl
        log("尝试通过 launchctl 启动...")
        subprocess.run(
            ["launchctl", "load", "/System/Library/LaunchDaemons/com.apple.cron.plist"],
            capture_output=True
        )
        
        return False

def register_cron_jobs():
    """注册 Cron 任务"""
    log("检查 Cron 任务注册...")
    
    # 检查是否有注册脚本
    register_scripts = [
        "scripts/register_health_cron.py",
        "scripts/register_cron.py",
    ]
    
    for script in register_scripts:
        if os.path.exists(script):
            log(f"执行注册脚本: {script}")
            try:
                result = subprocess.run(
                    [sys.executable, script],
                    capture_output=True,
                    text=True,
                    timeout=30
                )
                if result.returncode == 0:
                    log(f"✅ Cron 任务已注册")
                    return True
            except Exception as e:
                log(f"⚠️ 注册失败: {e}")
    
    log("⚠️ 未找到注册脚本")
    return False

def repair():
    """执行修复"""
    log("=== 开始修复: Cron 服务未启动 ===")
    
    issues = []
    
    # Step 1: 检查 Cron 状态
    if not check_cron_status():
        issues.append("Cron 调度器未运行")
    
    # Step 2: 检查系统 Cron
    if sys.platform == "darwin":
        if not check_system_cron():
            issues.append("系统 Cron 未运行")
    
    # Step 3: 尝试启动
    if issues:
        log(f"⚠️ 发现 {len(issues)} 个问题")
        
        # 尝试启动
        if start_cron_service():
            return True
        
        # 尝试注册任务
        register_cron_jobs()
        
        # 再次检查
        time.sleep(2)
        if check_cron_status():
            return True
        
        log("❌ 自动修复失败，请手动执行:")
        log("  python scripts/start_cron.py")
        return False
    else:
        log("✅ Cron 服务运行正常")
        return True

if __name__ == "__main__":
    success = repair()
    sys.exit(0 if success else 1)
