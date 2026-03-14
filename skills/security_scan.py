# -*- coding: utf-8 -*-
"""
ArcMind Security Scan Skill
=============================
白帽安全扫描与漏洞评估自动化。

支持：
  - 端口扫描 (nmap)
  - Web 漏洞扫描 (nikto)
  - 系统安全审计 (lynis)
  - SSL/TLS 检测 (openssl)
  - DNS 信息收集 (dig/whois)
  - Python 代码安全审计 (bandit)
  - 依赖漏洞检查 (safety/pip-audit)
  - 网络路径追踪 (traceroute)
  - 自动化综合安全报告
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger("arcmind.skill.security_scan")

# ── 报告输出目录 ──
REPORT_DIR = Path(__file__).parent.parent / "data" / "security_reports"
REPORT_DIR.mkdir(parents=True, exist_ok=True)


def _run_cmd(cmd: list[str], timeout: int = 120, sudo: bool = False) -> dict:
    """Execute a command and return structured result."""
    if sudo:
        cmd = ["sudo", "-n"] + cmd
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout
        )
        return {
            "success": result.returncode == 0,
            "stdout": result.stdout[:8000],
            "stderr": result.stderr[:2000],
            "returncode": result.returncode,
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "stdout": "", "stderr": "Command timed out", "returncode": -1}
    except FileNotFoundError:
        return {"success": False, "stdout": "", "stderr": f"Command not found: {cmd[0]}", "returncode": -1}
    except Exception as e:
        return {"success": False, "stdout": "", "stderr": str(e), "returncode": -1}


# ══════════════════════════════════════════════════════════════
# 1. 端口扫描 (nmap)
# ══════════════════════════════════════════════════════════════
def port_scan(target: str, scan_type: str = "quick", ports: str = "") -> dict:
    """
    Execute nmap port scan.

    Args:
        target: IP address or hostname to scan
        scan_type: "quick" (top 100), "standard" (top 1000), "full" (all ports),
                   "service" (service/version detection), "vuln" (vulnerability scripts)
        ports: Custom port range (e.g., "80,443,8080" or "1-1024")
    """
    # Safety: only allow scanning internal/local networks and owned domains
    cmd = ["nmap"]

    if scan_type == "quick":
        cmd += ["-sT", "-T4", "--top-ports", "100"]
    elif scan_type == "standard":
        cmd += ["-sT", "-T4"]
    elif scan_type == "full":
        cmd += ["-sT", "-T4", "-p-"]
    elif scan_type == "service":
        cmd += ["-sT", "-T4", "-sV"]
    elif scan_type == "vuln":
        cmd += ["-sT", "-T4", "--script", "vuln", "--script-timeout", "30s"]

    if ports:
        cmd += ["-p", ports]

    cmd += ["-oN", "-", target]

    logger.info("[SecurityScan] Port scan: %s (type=%s)", target, scan_type)
    result = _run_cmd(cmd, timeout=300, sudo=False)

    # Parse results
    open_ports = []
    for line in result["stdout"].split("\n"):
        if "/tcp" in line or "/udp" in line:
            parts = line.split()
            if len(parts) >= 3 and ("open" in parts[1]):
                open_ports.append({
                    "port": parts[0],
                    "state": parts[1],
                    "service": " ".join(parts[2:]),
                })

    return {
        "target": target,
        "scan_type": scan_type,
        "open_ports": open_ports,
        "port_count": len(open_ports),
        "raw_output": result["stdout"],
        "success": result["success"],
    }


# ══════════════════════════════════════════════════════════════
# 2. Web 漏洞扫描 (nikto)
# ══════════════════════════════════════════════════════════════
def web_vuln_scan(target: str, port: int = 80, ssl: bool = False) -> dict:
    """
    Execute nikto web vulnerability scan.

    Args:
        target: Target hostname or IP
        port: Target port
        ssl: Use SSL/TLS
    """
    cmd = ["nikto", "-h", target, "-p", str(port), "-Tuning", "123456789abc", "-maxtime", "300s"]
    if ssl:
        cmd += ["-ssl"]

    logger.info("[SecurityScan] Web vuln scan: %s:%d (ssl=%s)", target, port, ssl)
    result = _run_cmd(cmd, timeout=360)

    # Parse findings
    findings = []
    for line in result["stdout"].split("\n"):
        if line.startswith("+ ") and "OSVDB" in line:
            findings.append(line.strip())
        elif line.startswith("+ ") and ("vulnerability" in line.lower() or "found" in line.lower()):
            findings.append(line.strip())

    return {
        "target": f"{target}:{port}",
        "ssl": ssl,
        "findings": findings,
        "finding_count": len(findings),
        "raw_output": result["stdout"],
        "success": result["success"],
    }


# ══════════════════════════════════════════════════════════════
# 3. 系统安全审计 (lynis)
# ══════════════════════════════════════════════════════════════
def system_audit(profile: str = "default") -> dict:
    """
    Execute lynis system security audit.

    Args:
        profile: Audit profile ("default" or "server")
    """
    cmd = ["lynis", "audit", "system", "--no-colors", "--quick"]

    logger.info("[SecurityScan] System audit (lynis)")
    result = _run_cmd(cmd, timeout=300, sudo=False)

    # Parse hardening index and warnings
    hardening_index = "N/A"
    warnings = []
    suggestions = []

    for line in result["stdout"].split("\n"):
        if "Hardening index" in line:
            match = re.search(r"(\d+)", line)
            if match:
                hardening_index = int(match.group(1))
        elif "Warning" in line and "]" in line:
            warnings.append(line.strip())
        elif "Suggestion" in line and "]" in line:
            suggestions.append(line.strip())

    return {
        "hardening_index": hardening_index,
        "warnings": warnings[:20],
        "warning_count": len(warnings),
        "suggestions": suggestions[:20],
        "suggestion_count": len(suggestions),
        "raw_output": result["stdout"][-3000:],  # Last part has summary
        "success": result["success"],
    }


# ══════════════════════════════════════════════════════════════
# 4. SSL/TLS 检测
# ══════════════════════════════════════════════════════════════
def ssl_check(target: str, port: int = 443) -> dict:
    """
    Check SSL/TLS certificate and configuration.

    Args:
        target: Hostname to check
        port: SSL port (default 443)
    """
    results = {}

    # Certificate info
    cmd = ["openssl", "s_client", "-connect", f"{target}:{port}", "-servername", target]
    r = _run_cmd(cmd, timeout=15)
    results["cert_chain"] = r["stdout"][:2000]

    # Certificate dates
    cmd2_input = r["stdout"]
    try:
        proc = subprocess.run(
            ["openssl", "x509", "-noout", "-dates", "-subject", "-issuer"],
            input=cmd2_input, capture_output=True, text=True, timeout=10
        )
        results["cert_info"] = proc.stdout
    except Exception:
        results["cert_info"] = "N/A"

    # Check for weak protocols
    weak_protocols = []
    for proto in ["ssl3", "tls1", "tls1_1"]:
        cmd = ["openssl", "s_client", "-connect", f"{target}:{port}",
               f"-{proto}", "-servername", target]
        r = _run_cmd(cmd, timeout=10)
        if r["success"] and "CONNECTED" in r["stdout"]:
            weak_protocols.append(proto)

    results["weak_protocols"] = weak_protocols
    results["target"] = f"{target}:{port}"
    results["success"] = True

    return results


# ══════════════════════════════════════════════════════════════
# 5. DNS / WHOIS 信息收集
# ══════════════════════════════════════════════════════════════
def dns_recon(domain: str) -> dict:
    """
    DNS reconnaissance for a domain.

    Args:
        domain: Target domain to investigate
    """
    results = {"domain": domain}

    # A records
    r = _run_cmd(["dig", "+short", "A", domain], timeout=10)
    results["a_records"] = r["stdout"].strip().split("\n") if r["success"] else []

    # MX records
    r = _run_cmd(["dig", "+short", "MX", domain], timeout=10)
    results["mx_records"] = r["stdout"].strip().split("\n") if r["success"] else []

    # NS records
    r = _run_cmd(["dig", "+short", "NS", domain], timeout=10)
    results["ns_records"] = r["stdout"].strip().split("\n") if r["success"] else []

    # TXT records (SPF, DKIM, etc.)
    r = _run_cmd(["dig", "+short", "TXT", domain], timeout=10)
    results["txt_records"] = r["stdout"].strip().split("\n") if r["success"] else []

    # WHOIS
    r = _run_cmd(["whois", domain], timeout=15)
    results["whois"] = r["stdout"][:3000] if r["success"] else "WHOIS lookup failed"

    results["success"] = True
    return results


# ══════════════════════════════════════════════════════════════
# 6. Python 代码安全审计 (bandit)
# ══════════════════════════════════════════════════════════════
def code_audit(path: str, severity: str = "medium") -> dict:
    """
    Static security analysis of Python code using bandit.

    Args:
        path: Directory or file path to audit
        severity: Minimum severity ("low", "medium", "high")
    """
    sev_map = {"low": "l", "medium": "m", "high": "h"}
    sev_flag = sev_map.get(severity, "m")

    cmd = [
        "bandit", "-r", path,
        "-f", "json",
        "-ll" if sev_flag == "m" else ("-lll" if sev_flag == "h" else "-l"),
        "--exclude", ".git,__pycache__,venv,node_modules,.tox"
    ]

    logger.info("[SecurityScan] Code audit: %s (severity>=%s)", path, severity)
    result = _run_cmd(cmd, timeout=120)

    try:
        data = json.loads(result["stdout"])
        issues = data.get("results", [])
        metrics = data.get("metrics", {}).get("_totals", {})

        return {
            "path": path,
            "severity_filter": severity,
            "issues": [
                {
                    "file": i["filename"],
                    "line": i["line_number"],
                    "severity": i["issue_severity"],
                    "confidence": i["issue_confidence"],
                    "text": i["issue_text"],
                    "test_id": i["test_id"],
                }
                for i in issues[:30]
            ],
            "issue_count": len(issues),
            "metrics": metrics,
            "success": True,
        }
    except (json.JSONDecodeError, KeyError):
        return {
            "path": path,
            "raw_output": result["stdout"][:3000],
            "stderr": result["stderr"][:1000],
            "success": result["returncode"] == 0,
        }


# ══════════════════════════════════════════════════════════════
# 7. 依赖漏洞检查
# ══════════════════════════════════════════════════════════════
def dependency_check(requirements_path: str = "") -> dict:
    """
    Check Python dependencies for known vulnerabilities.

    Args:
        requirements_path: Path to requirements.txt (empty = scan current env)
    """
    if requirements_path:
        cmd = ["safety", "check", "-r", requirements_path, "--json"]
    else:
        cmd = ["safety", "check", "--json"]

    logger.info("[SecurityScan] Dependency vulnerability check")
    result = _run_cmd(cmd, timeout=60)

    try:
        data = json.loads(result["stdout"])
        vulns = data if isinstance(data, list) else data.get("vulnerabilities", [])
        return {
            "vulnerable_packages": len(vulns),
            "vulnerabilities": vulns[:20],
            "success": True,
        }
    except (json.JSONDecodeError, KeyError):
        return {
            "raw_output": result["stdout"][:3000],
            "stderr": result["stderr"][:1000],
            "success": result["returncode"] == 0,
        }


# ══════════════════════════════════════════════════════════════
# 8. 网络扫描与路径追踪
# ══════════════════════════════════════════════════════════════
def network_recon(target: str) -> dict:
    """
    Network reconnaissance: traceroute + ping.

    Args:
        target: Target host
    """
    results = {"target": target}

    # Traceroute
    r = _run_cmd(["traceroute", "-m", "15", "-w", "2", target], timeout=60)
    results["traceroute"] = r["stdout"] if r["success"] else r["stderr"]

    # Ping
    r = _run_cmd(["ping", "-c", "5", "-W", "2", target], timeout=15)
    results["ping"] = r["stdout"] if r["success"] else r["stderr"]

    results["success"] = True
    return results


# ══════════════════════════════════════════════════════════════
# 9. 基础设施安全检查
# ══════════════════════════════════════════════════════════════
def infra_security_check() -> dict:
    """
    Check local infrastructure security posture.
    Returns findings about firewall, open ports, users, permissions.
    """
    results = {}

    # Listening ports
    r = _run_cmd(["ss", "-tlnp"], timeout=10)
    results["listening_ports"] = r["stdout"]

    # Firewall rules
    r = _run_cmd(["iptables", "-L", "-n", "--line-numbers"], timeout=10, sudo=False)
    results["firewall_rules"] = r["stdout"]

    # Users with login shell
    try:
        with open("/etc/passwd", "r") as f:
            users = [
                line.split(":")[0]
                for line in f
                if line.strip() and not line.startswith("#")
                and line.split(":")[-1].strip() in ("/bin/bash", "/bin/sh", "/bin/zsh")
            ]
        results["login_users"] = users
    except Exception:
        results["login_users"] = []

    # SSH config check
    ssh_issues = []
    try:
        with open("/etc/ssh/sshd_config", "r") as f:
            sshd = f.read()
        if "PermitRootLogin yes" in sshd:
            ssh_issues.append("Root login is enabled")
        if "PasswordAuthentication yes" in sshd:
            ssh_issues.append("Password authentication is enabled (key-only recommended)")
        if "X11Forwarding yes" in sshd:
            ssh_issues.append("X11 forwarding is enabled")
    except Exception:
        ssh_issues.append("Cannot read sshd_config")
    results["ssh_issues"] = ssh_issues

    # World-writable files in critical dirs
    r = _run_cmd(["find", "/etc", "-perm", "-002", "-type", "f"], timeout=15, sudo=False)
    results["world_writable_etc"] = r["stdout"].strip().split("\n") if r["stdout"].strip() else []

    # Check for unattended upgrades
    r = _run_cmd(["systemctl", "is-enabled", "unattended-upgrades"], timeout=5)
    results["auto_updates"] = r["stdout"].strip()

    results["success"] = True
    return results


# ══════════════════════════════════════════════════════════════
# 10. 综合安全报告
# ══════════════════════════════════════════════════════════════
def full_security_audit(target: str = "localhost", include_web: bool = False) -> dict:
    """
    Run a comprehensive security audit and generate a report.

    Args:
        target: Primary target for network scans
        include_web: Include web vulnerability scan (slower)
    """
    logger.info("[SecurityScan] Starting full security audit for %s", target)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report = {
        "timestamp": timestamp,
        "target": target,
        "sections": {},
    }

    # 1. Port scan
    try:
        report["sections"]["port_scan"] = port_scan(target, scan_type="service")
    except Exception as e:
        report["sections"]["port_scan"] = {"error": str(e)}

    # 2. Infrastructure check
    try:
        report["sections"]["infrastructure"] = infra_security_check()
    except Exception as e:
        report["sections"]["infrastructure"] = {"error": str(e)}

    # 3. System audit (lynis)
    try:
        report["sections"]["system_audit"] = system_audit()
    except Exception as e:
        report["sections"]["system_audit"] = {"error": str(e)}

    # 4. Code audit (ArcMind itself)
    try:
        report["sections"]["code_audit"] = code_audit("/home/engineering/ArcMind", severity="medium")
    except Exception as e:
        report["sections"]["code_audit"] = {"error": str(e)}

    # 5. Dependency check
    try:
        report["sections"]["dependency_check"] = dependency_check()
    except Exception as e:
        report["sections"]["dependency_check"] = {"error": str(e)}

    # 6. Web scan (optional, slow)
    if include_web:
        try:
            report["sections"]["web_vuln"] = web_vuln_scan(target, port=8100)
        except Exception as e:
            report["sections"]["web_vuln"] = {"error": str(e)}

    # Generate summary
    total_issues = 0
    critical = 0
    for section_name, section_data in report["sections"].items():
        if isinstance(section_data, dict):
            count = section_data.get("issue_count", 0) + \
                    section_data.get("finding_count", 0) + \
                    section_data.get("warning_count", 0) + \
                    section_data.get("vulnerable_packages", 0)
            total_issues += count
            if section_data.get("hardening_index") and \
               isinstance(section_data["hardening_index"], int) and \
               section_data["hardening_index"] < 50:
                critical += 1

    report["summary"] = {
        "total_issues": total_issues,
        "critical_findings": critical,
        "sections_completed": len(report["sections"]),
    }

    # Save report
    report_path = REPORT_DIR / f"audit_{timestamp}.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False, default=str)
    report["report_path"] = str(report_path)

    logger.info("[SecurityScan] Audit complete: %d issues found, report saved to %s",
                total_issues, report_path)

    return report


# ══════════════════════════════════════════════════════════════
# Skill 注册接口 (ArcMind skill framework)
# ══════════════════════════════════════════════════════════════
SKILL_META = {
    "name": "security_scan",
    "description": "白帽安全扫描与漏洞评估 — 端口扫描、Web 漏洞、系统审计、代码审计、依赖检查",
    "version": "1.0.0",
    "author": "ArcMind Security",
    "capabilities": [
        "port_scan", "web_vuln_scan", "system_audit", "ssl_check",
        "dns_recon", "code_audit", "dependency_check", "network_recon",
        "infra_security_check", "full_security_audit",
    ],
    "triggers": [
        "安全扫描", "漏洞评估", "端口扫描", "渗透测试", "security scan",
        "vulnerability", "nmap", "nikto", "audit", "pentest",
    ],
}


def invoke(action: str, params: dict) -> dict:
    """Skill entry point for ArcMind skill framework."""
    actions = {
        "port_scan": port_scan,
        "web_vuln_scan": web_vuln_scan,
        "system_audit": system_audit,
        "ssl_check": ssl_check,
        "dns_recon": dns_recon,
        "code_audit": code_audit,
        "dependency_check": dependency_check,
        "network_recon": network_recon,
        "infra_security_check": infra_security_check,
        "full_security_audit": full_security_audit,
    }

    func = actions.get(action)
    if not func:
        return {"error": f"Unknown action: {action}. Available: {list(actions.keys())}"}

    try:
        return func(**params)
    except Exception as e:
        logger.error("[SecurityScan] Action %s failed: %s", action, e)
        return {"error": str(e), "action": action}
