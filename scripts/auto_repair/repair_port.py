#!/usr/bin/env python3
"""
自动修复脚本 - 端口占用问题
Auto-Repair: Port Occupied

错误类型: Port Occupied
触发条件: 端口被占用, 服务启动失败, Address already in use
"""

import os
import sys
import time
import subprocess
import re
from datetime import datetime

LOG_FILE = "logs/auto_repair_port.log"

# 常见需要检查的端口
COMMON_PORTS = {
    3000: "Node.js/React Dev Server",
    3001: "Node.js Alternative",
    5000: "Flask/Backend API",
    5001: "Flask Alternative",
    8000: "Django/Python HTTP",
    8080: "Java/Tomcat/Proxy",
    8888: "Jupyter Notebook",
    9000: "PHP-FPM",
    11434: "Ollama API",
    27017: "MongoDB",
    5432: "PostgreSQL",
    3306: "MySQL",
    6379: "Redis",
}

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

def get_process_by_port(port):
    """获取占用指定端口的进程"""
    log(f"检查端口 {port}...")
    try:
        # 使用 lsof 查找占用端口的进程
        result = subprocess.run(
            ["lsof", "-i", f":{port}", "-n", "-P"],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if result.returncode == 0 and result.stdout.strip():
            lines = result.stdout.strip().split("\n")
            processes = []
            for line in lines[1:]:  # 跳过标题行
                parts = line.split()
                if len(parts) >= 2:
                    processes.append({
                        "pid": parts[1],
                        "name": parts[0],
                        "status": parts[-1] if len(parts) > 7 else "LISTEN"
                    })
            return processes
        return []
    except FileNotFoundError:
        # lsof 不可用，尝试使用 netstat
        return get_process_by_port_netstat(port)
    except Exception as e:
        log(f"⚠️ 检查端口 {port} 失败: {e}")
        return []

def get_process_by_port_netstat(port):
    """使用 netstat 获取端口信息 (备用方法)"""
    try:
        result = subprocess.run(
            ["netstat", "-an", "-p", "tcp"],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if result.returncode == 0:
            processes = []
            for line in result.stdout.split("\n"):
                if f".{port}" in line and "LISTEN" in line:
                    match = re.search(r'(\d+)\/\w+', line)
                    if match:
                        pid = match.group(1)
                        processes.append({
                            "pid": pid,
                            "name": "Unknown",
                            "status": "LISTEN"
                        })
            return processes
    except:
        pass
    return []

def kill_process(pid):
    """终止进程"""
    log(f"尝试终止进程 PID: {pid}...")
    try:
        # 优雅终止
        result = subprocess.run(
            ["kill", pid],
            capture_output=True,
            text=True
        )
        
        if result.returncode == 0:
            time.sleep(1)
            # 检查进程是否已终止
            check = subprocess.run(
                ["ps", "-p", pid],
                capture_output=True,
                text=True
            )
            if check.returncode != 0:
                log(f"✅ 进程 {pid} 已终止")
                return True
        
        # 强制终止
        log(f"优雅终止失败，尝试强制终止...")
        result = subprocess.run(
            ["kill", "-9", pid],
            capture_output=True,
            text=True
        )
        
        if result.returncode == 0:
            log(f"✅ 进程 {pid} 已强制终止")
            return True
        
        log(f"❌ 无法终止进程 {pid}")
        return False
    except Exception as e:
        log(f"❌ 终止进程失败: {e}")
        return False

def scan_all_ports():
    """扫描所有常见端口"""
    log("=== 扫描常用端口 ===")
    occupied = []
    
    for port, service in COMMON_PORTS.items():
        processes = get_process_by_port(port)
        if processes:
            for proc in processes:
                occupied.append({
                    "port": port,
                    "service": service,
                    "pid": proc["pid"],
                    "name": proc["name"]
                })
                log(f"⚠️ 端口 {port} ({service}) 被占用: PID={proc['pid']}, 进程={proc['name']}")
    
    return occupied

def repair_specific_port(port):
    """修复指定端口"""
    log(f"=== 开始修复端口 {port} ===")
    
    processes = get_process_by_port(port)
    if not processes:
        log(f"端口 {port} 当前未被占用")
        return True
    
    service_name = COMMON_PORTS.get(port, "Unknown")
    log(f"端口 {port} ({service_name}) 被以下进程占用:")
    
    for proc in processes:
        log(f"  - PID: {proc['pid']}, 进程: {proc['name']}, 状态: {proc['status']}")
    
    # 询问用户是否终止
    log("是否终止这些进程? (y/n)")
    
    # 自动处理：终止所有占用进程
    for proc in processes:
        if kill_process(proc["pid"]):
            log(f"✅ 已释放端口 {port}")
            return True
    
    log(f"❌ 无法释放端口 {port}")
    return False

def repair():
    """执行修复"""
    log("=== 开始修复: 端口占用问题 ===")
    
    # 先扫描所有常用端口
    occupied = scan_all_ports()
    
    if not occupied:
        log("✅ 未发现端口被占用")
        return True
    
    log(f"发现 {len(occupied)} 个端口被占用")
    
    # 尝试释放所有占用端口
    freed_ports = set()
    for item in occupied:
        port = item["port"]
        if port in freed_ports:
            continue
        
        processes = get_process_by_port(port)
        for proc in processes:
            if kill_process(proc["pid"]):
                freed_ports.add(port)
                break
    
    # 验证
    time.sleep(2)
    remaining = scan_all_ports()
    
    if not remaining:
        log("✅ 所有占用端口已释放")
        return True
    else:
        log(f"❌ 仍有 {len(remaining)} 个端口被占用")
        for item in remaining:
            log(f"  - 端口 {item['port']}: PID={item['pid']}")
        return False

def show_usage():
    """显示使用方法"""
    print("""
使用方法:
  python3 scripts/auto_repair/repair_port.py [port]

参数:
  port    可选，指定要检查的端口号

示例:
  python3 scripts/auto_repair/repair_port.py        # 扫描所有常用端口
  python3 scripts/auto_repair/repair_port.py 3000   # 只检查 3000 端口
""")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        if sys.argv[1] in ["-h", "--help", "help"]:
            show_usage()
            sys.exit(0)
        try:
            port = int(sys.argv[1])
            success = repair_specific_port(port)
        except ValueError:
            print(f"无效的端口号: {sys.argv[1]}")
            show_usage()
            sys.exit(1)
    else:
        success = repair()
    
    sys.exit(0 if success else 1)
