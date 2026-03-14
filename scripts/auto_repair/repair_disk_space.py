#!/usr/bin/env python3
"""
自动修复脚本 - 磁盘空间不足
Auto-Repair: Disk Space Low

错误类型: Disk Space Low
触发条件: 磁盘使用率超过 90%
"""

import os
import sys
import subprocess
from datetime import datetime

LOG_FILE = "logs/auto_repair_disk.log"

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

def get_disk_usage(path="/"):
    """获取磁盘使用情况"""
    try:
        stat = os.statvfs(path)
        total = stat.f_blocks * stat.f_frsize
        free = stat.f_bavail * stat.f_frsize
        used = total - free
        percent = (used / total) * 100
        return {
            "total": total,
            "used": used,
            "free": free,
            "percent": percent
        }
    except Exception as e:
        log(f"获取磁盘信息失败: {e}")
        return None

def find_large_files(directory, min_size_mb=100):
    """查找大文件"""
    large_files = []
    
    for root, dirs, files in os.walk(directory):
        # 跳过隐藏目录和系统目录
        dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ['node_modules', '__pycache__']]
        
        for file in files:
            try:
                filepath = os.path.join(root, file)
                size = os.path.getsize(filepath)
                size_mb = size / (1024 * 1024)
                
                if size_mb >= min_size_mb:
                    large_files.append({
                        "path": filepath,
                        "size_mb": size_mb
                    })
            except:
                pass
    
    return sorted(large_files, key=lambda x: x["size_mb"], reverse=True)

def clean_logs():
    """清理日志文件"""
    log("清理日志文件...")
    
    logs_dir = "logs"
    if not os.path.exists(logs_dir):
        log("日志目录不存在")
        return 0
    
    cleaned = 0
    for file in os.listdir(logs_dir):
        filepath = os.path.join(logs_dir, file)
        if os.path.isfile(filepath):
            size = os.path.getsize(filepath)
            try:
                os.remove(filepath)
                cleaned += size
                log(f"  删除: {file} ({size/1024:.1f}KB)")
            except:
                pass
    
    log(f"清理完成: {cleaned/1024/1024:.2f}MB")
    return cleaned

def clean_temp():
    """清理临时文件"""
    log("清理临时文件...")
    
    temp_patterns = [
        "*.pyc",
        "__pycache__",
        "*.tmp",
        ".DS_Store",
    ]
    
    # Python cache
    for root, dirs, files in os.walk("."):
        dirs[:] = [d for d in dirs if d not in ['.git', '.venv', 'node_modules']]
        
        if "__pycache__" in dirs:
            pycache = os.path.join(root, "__pycache__")
            try:
                import shutil
                shutil.rmtree(pycache)
                log(f"  删除: {pycache}")
            except:
                pass
    
    log("临时文件清理完成")

def repair():
    """执行修复"""
    log("=== 开始修复: 磁盘空间不足 ===")
    
    # Step 1: 检查磁盘使用情况
    usage = get_disk_usage()
    
    if usage:
        log(f"磁盘使用率: {usage['percent']:.1f}%")
        log(f"总空间: {usage['total']/1024/1024/1024:.2f}GB")
        log(f"可用空间: {usage['free']/1024/1024/1024:.2f}GB")
        
        if usage['percent'] < 90:
            log("✅ 磁盘空间充足")
            return True
    else:
        log("⚠️ 无法获取磁盘信息")
    
    # Step 2: 查找大文件
    log("\n查找大文件...")
    large_files = find_large_files(".", min_size_mb=50)[:10]
    
    if large_files:
        log("前10个大文件:")
        for f in large_files:
            log(f"  {f['size_mb']:.1f}MB - {f['path']}")
    else:
        log("未发现大文件")
    
    # Step 3: 清理
    log("\n执行清理...")
    clean_logs()
    clean_temp()
    
    # Step 4: 再次检查
    usage = get_disk_usage()
    if usage:
        log(f"\n清理后磁盘使用率: {usage['percent']:.1f}%")
        log(f"可用空间: {usage['free']/1024/1024/1024:.2f}GB")
        
        if usage['percent'] < 90:
            log("✅ 磁盘空间已恢复")
            return True
    
    log("⚠️ 磁盘空间仍然不足，建议:")
    log("  1. 清理 Docker: docker system prune -a")
    log("  2. 清理 Homebrew: brew cleanup")
    log("  3. 删除不需要的文件")
    
    return False

if __name__ == "__main__":
    success = repair()
    sys.exit(0 if success else 1)
