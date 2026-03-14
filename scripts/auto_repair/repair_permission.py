#!/usr/bin/env python3
"""
自动修复脚本 - 权限问题
Auto-Repair: Permission Denied

错误类型: Permission Denied
触发条件: 文件/目录权限不足, 用户不是管理员
"""

import os
import sys
import stat
import subprocess
from datetime import datetime
import pwd
import grp

LOG_FILE = "logs/auto_repair_permission.log"

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

def get_current_user():
    """获取当前用户"""
    return pwd.getpwuid(os.getuid()).pw_name

def check_permission(path):
    """检查路径权限"""
    if not os.path.exists(path):
        return None
    
    st = os.stat(path)
    mode = st.st_mode
    
    # 权限信息
    perms = []
    if mode & stat.S_IRUSR: perms.append("r")
    else: perms.append("-")
    if mode & stat.S_IWUSR: perms.append("w")
    else: perms.append("-")
    if mode & stat.S_IXUSR: perms.append("x")
    else: perms.append("-")
    
    owner = pwd.getpwuid(st.st_uid).pw_name
    group = grp.getgrgid(st.st_gid).gr_name
    
    return {
        "path": path,
        "perms": "".join(perms),
        "owner": owner,
        "group": group,
        "mode": oct(stat.S_IMODE(mode))
    }

def fix_permission(path, recursive=False):
    """修复权限"""
    log(f"修复权限: {path}")
    
    if not os.path.exists(path):
        log(f"⚠️ 路径不存在: {path}")
        return False
    
    current_user = get_current_user()
    
    try:
        if os.path.isfile(path):
            os.chmod(path, 0o644)
            log(f"✅ 文件权限已设为 644: {path}")
        elif os.path.isdir(path):
            os.chmod(path, 0o755)
            log(f"✅ 目录权限已设为 755: {path}")
            
            if recursive:
                for root, dirs, files in os.walk(path):
                    for d in dirs:
                        dp = os.path.join(root, d)
                        os.chmod(dp, 0o755)
                    for f in files:
                        fp = os.path.join(root, f)
                        os.chmod(fp, 0o644)
                log(f"✅ 递归修复完成: {path}")
        
        return True
    except PermissionError:
        log(f"❌ 权限不足，需要 sudo: {path}")
        return False
    except Exception as e:
        log(f"❌ 修复失败: {e}")
        return False

def check_critical_paths():
    """检查关键路径权限"""
    log("=== 检查关键路径权限 ===")
    
    critical_paths = [
        ".",
        "scripts",
        "data",
        "config",
        "logs",
        "outputs",
    ]
    
    issues = []
    for path in critical_paths:
        if os.path.exists(path):
            info = check_permission(path)
            if info:
                log(f"  {info['path']}: {info['perms']} (owner: {info['owner']})")
                
                # 检查写权限
                test_file = os.path.join(path, ".write_test")
                try:
                    with open(test_file, "w") as f:
                        f.write("test")
                    os.remove(test_file)
                except PermissionError:
                    issues.append(f"{path}: 无写权限")
    
    return issues

def repair():
    """执行修复"""
    log("=== 开始修复: 权限问题 ===")
    
    current_user = get_current_user()
    log(f"当前用户: {current_user}")
    
    # Step 1: 检查关键路径
    issues = check_critical_paths()
    
    if issues:
        log(f"⚠️ 发现 {len(issues)} 个权限问题:")
        for issue in issues:
            log(f"  - {issue}")
        
        # 尝试修复
        log("尝试自动修复...")
        for path in ["data", "logs", "outputs", "scripts"]:
            if os.path.exists(path):
                fix_permission(path, recursive=True)
    else:
        log("✅ 所有关键路径权限正常")
    
    # Step 2: 检查是否是管理员
    if sys.platform == "darwin":
        result = subprocess.run(
            ["groups"],
            capture_output=True,
            text=True
        )
        if "admin" in result.stdout:
            log("✅ 用户具有管理员权限")
        else:
            log("⚠️ 用户没有管理员权限，某些操作可能受限")
    
    return len(issues) == 0

if __name__ == "__main__":
    success = repair()
    sys.exit(0 if success else 1)
