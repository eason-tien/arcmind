#!/usr/bin/env python3
"""
自动修复脚本 - API 超时/服务不可用
Auto-Repair: API Timeout / Service Unavailable

错误类型: API Timeout
触发条件: 外部 API 服务宕机, 网络延迟过高, 请求超时
"""

import os
import sys
import time
import subprocess
from datetime import datetime

LOG_FILE = "logs/auto_repair_api.log"

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

def check_network():
    """检查网络连接"""
    log("检查网络连接...")
    test_hosts = ["8.8.8.8", "api.openai.com", "api.github.com"]
    
    for host in test_hosts:
        result = subprocess.run(
            ["ping", "-c", "1", "-t", "5", host],
            capture_output=True,
            text=True
        )
        if result.returncode == 0:
            log(f"✅ 网络到 {host} 正常")
            return True
    
    log("⚠️ 网络连接可能存在问题")
    return False

def check_dns():
    """检查 DNS 解析"""
    log("检查 DNS 解析...")
    test_domains = ["openai.com", "github.com"]
    
    for domain in test_domains:
        result = subprocess.run(
            ["nslookup", domain],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            log(f"✅ DNS 解析 {domain} 正常")
            return True
    
    log("⚠️ DNS 解析可能存在问题")
    return False

def check_api_service(service_name, check_url):
    """检查特定 API 服务"""
    import urllib.request
    import urllib.error
    
    log(f"检查 API 服务: {service_name}")
    try:
        req = urllib.request.Request(check_url, method='HEAD')
        req.add_header('User-Agent', 'ArcMind-AutoRepair/1.0')
        response = urllib.request.urlopen(req, timeout=10)
        log(f"✅ {service_name} 服务正常 (HTTP {response.status})")
        return True
    except urllib.error.URLError as e:
        log(f"⚠️ {service_name} 连接失败: {e.reason}")
        return False
    except Exception as e:
        log(f"❌ {service_name} 检查失败: {e}")
        return False

def repair():
    """执行修复"""
    log("=== 开始修复: API 超时/服务不可用 ===")
    
    issues = []
    
    # Step 1: 检查网络
    if not check_network():
        issues.append("网络连接异常")
        log("建议: 检查网络线缆/WiFi, 重启路由器")
    
    # Step 2: 检查 DNS
    if not check_dns():
        issues.append("DNS 解析异常")
        log("建议: 更换 DNS 服务器 (8.8.8.8, 114.114.114.114)")
    
    # Step 3: 检查常见 API 服务
    apis = [
        ("OpenAI API", "https://api.openai.com"),
        ("GitHub API", "https://api.github.com"),
    ]
    
    for name, url in apis:
        if not check_api_service(name, url):
            issues.append(f"{name} 不可用")
    
    # 总结
    if not issues:
        log("✅ 所有 API 服务检查通过")
        return True
    else:
        log(f"❌ 发现 {len(issues)} 个问题: {', '.join(issues)}")
        return False

if __name__ == "__main__":
    success = repair()
    sys.exit(0 if success else 1)
