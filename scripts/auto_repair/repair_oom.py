#!/usr/bin/env python3
"""
自动修复脚本 - 内存不足
Auto-Repair: Out of Memory (OOM)

错误类型: OOM / Memory Error
触发条件: 进程内存占用过高, 系统内存不足
"""

import os
import sys
import subprocess
from datetime import datetime

LOG_FILE = "logs/auto_repair_oom.log"

def log(msg):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_msg = f"[{timestamp}] {msg}"
    print(log_msg)
    try:
        os.makedirs("logs", exist_ok=True)
        with open(LOG_FILE, "a") as f:
            f.write(log_msg + "\n")
    except:
        pass

def get_memory_usage():
    try:
        if sys.platform == "darwin":
            result = subprocess.run(["vm_stat"], capture_output=True, text=True, timeout=5)
            lines = result.stdout.strip().split("\n")
            info = {}
            for line in lines:
                if ":" in line:
                    key, value = line.split(":", 1)
                    info[key.strip()] = value.strip().rstrip(".")
            
            total = subprocess.run(["sysctl", "hw.memsize"], capture_output=True, text=True)
            total_mem = int(total.stdout.split(":")[1].strip())
            
            wired = int(info.get("Pages wired down", "0").split()[0]) * 4096
            active = int(info.get("Pages active", "0").split()[0]) * 4096
            used = wired + active
            percent = (used / total_mem) * 100
            
            return {"total": total_mem, "used": used, "percent": percent}
        else:
            with open("/proc/meminfo", "r") as f:
                lines = f.readlines()
            
            mem = {}
            for line in lines:
                if ":" in line:
                    key, value = line.split(":", 1)
                    mem[key.strip()] = int(value.strip().split()[0]) * 1024
            
            total = mem.get("MemTotal", 0)
            available = mem.get("MemAvailable", 0)
            used = total - available
            percent = (used / total) * 100
            
            return {"total": total, "used": used, "percent": percent}
    except Exception as e:
        log(f"获取内存信息失败: {e}")
        return None

def find_memory_hogs():
    log("查找内存占用最高的进程...")
    try:
        result = subprocess.run(["ps", "aux", "-m"], capture_output=True, text=True, timeout=10)
        lines = result.stdout.strip().split("\n")[1:11]
        for line in lines:
            parts = line.split()
            if len(parts) >= 6:
                log(f"  PID {parts[1]}: {parts[5]}% - {parts[-1]}")
    except Exception as e:
        log(f"查找进程失败: {e}")

def repair():
    log("=== 开始修复: 内存不足 ===")
    
    mem = get_memory_usage()
    
    if mem:
        log(f"内存使用率: {mem['percent']:.1f}%")
        log(f"总内存: {mem['total']/1024/1024:.0f}MB")
        log(f"已使用: {mem['used']/1024/1024:.0f}MB")
        
        if mem['percent'] < 85:
            log("✅ 内存使用正常")
            return True
    else:
        log("⚠️ 无法获取内存信息")
    
    find_memory_hogs()
    log("\n建议操作: 重启挂起的进程, 关闭不需要的应用程序")
    return False

if __name__ == "__main__":
    success = repair()
    sys.exit(0 if success else 1)
