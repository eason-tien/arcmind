# -*- coding: utf-8 -*-
"""
ArcMind Skill: Environment Discovery (三維度認知掃描)
=======================================================
L1 宿主機認知 — OS / CPU / RAM / Disk / GPU / Uptime
L2 服務認知   — Ports / Processes / Docker / DB / Config files
L3 網路拓撲   — ARP cache / Route table / Interfaces (被動模式)

Cross-platform: macOS + Windows + Linux
"""
from __future__ import annotations

import json
import logging
import os
import platform
import socket
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger("arcmind.skills.env_discovery")

_IS_WINDOWS = platform.system() == "Windows"
_IS_MAC = platform.system() == "Darwin"
_IS_LINUX = platform.system() == "Linux"


# ═══════════════════════════════════════════════════════════════════════════════
#  L1 — 宿主機認知 (Host Awareness)
# ═══════════════════════════════════════════════════════════════════════════════

def _host_info(inputs: dict) -> dict:
    """Complete host information snapshot."""
    import psutil

    mem = psutil.virtual_memory()
    disk_info = []
    for part in psutil.disk_partitions(all=False):
        try:
            usage = psutil.disk_usage(part.mountpoint)
            disk_info.append({
                "mount": part.mountpoint,
                "device": part.device,
                "fstype": part.fstype,
                "total_gb": round(usage.total / (1024**3), 1),
                "used_gb": round(usage.used / (1024**3), 1),
                "free_gb": round(usage.free / (1024**3), 1),
                "percent": usage.percent,
            })
        except (PermissionError, OSError):
            continue

    cpu_freq = psutil.cpu_freq()
    boot_time = datetime.fromtimestamp(psutil.boot_time())
    uptime = datetime.now() - boot_time

    info = {
        "hostname": socket.gethostname(),
        "os": platform.system(),
        "os_version": platform.version(),
        "os_release": platform.release(),
        "architecture": platform.machine(),
        "python_version": platform.python_version(),
        "cpu": {
            "physical_cores": psutil.cpu_count(logical=False),
            "logical_cores": psutil.cpu_count(logical=True),
            "current_freq_mhz": round(cpu_freq.current, 0) if cpu_freq else None,
            "usage_percent": psutil.cpu_percent(interval=0.5),
        },
        "memory": {
            "total_gb": round(mem.total / (1024**3), 1),
            "available_gb": round(mem.available / (1024**3), 1),
            "used_gb": round(mem.used / (1024**3), 1),
            "percent": mem.percent,
        },
        "disks": disk_info,
        "uptime": str(uptime).split(".")[0],
        "boot_time": boot_time.isoformat(),
    }

    # GPU detection
    gpu = _detect_gpu()
    if gpu:
        info["gpu"] = gpu

    return info


def _resource_check(inputs: dict) -> dict:
    """Pre-check if resources are sufficient for a task."""
    import psutil

    mem = psutil.virtual_memory()
    disk = psutil.disk_usage("/")

    required_ram_gb = inputs.get("required_ram_gb", 2)
    required_disk_gb = inputs.get("required_disk_gb", 1)

    available_ram = mem.available / (1024**3)
    available_disk = disk.free / (1024**3)

    issues = []
    if available_ram < required_ram_gb:
        issues.append(f"RAM 不足: 需要 {required_ram_gb}GB, 可用 {available_ram:.1f}GB")
    if available_disk < required_disk_gb:
        issues.append(f"磁碟空間不足: 需要 {required_disk_gb}GB, 可用 {available_disk:.1f}GB")
    if psutil.cpu_percent(interval=0.3) > 90:
        issues.append(f"CPU 負載過高: {psutil.cpu_percent()}%")

    return {
        "sufficient": len(issues) == 0,
        "available_ram_gb": round(available_ram, 1),
        "available_disk_gb": round(available_disk, 1),
        "cpu_percent": psutil.cpu_percent(),
        "issues": issues,
    }


def _detect_gpu() -> list[dict] | None:
    """Detect GPU info (cross-platform)."""
    gpus = []
    try:
        if _IS_MAC:
            out = subprocess.run(
                ["system_profiler", "SPDisplaysDataType", "-json"],
                capture_output=True, text=True, timeout=5
            )
            if out.returncode == 0:
                data = json.loads(out.stdout)
                for item in data.get("SPDisplaysDataType", []):
                    gpus.append({
                        "name": item.get("sppci_model", "Unknown"),
                        "vram": item.get("sppci_vram", "N/A"),
                        "vendor": item.get("sppci_vendor", ""),
                    })
        elif _IS_WINDOWS:
            out = subprocess.run(
                ["wmic", "path", "win32_VideoController", "get",
                 "Name,AdapterRAM,DriverVersion", "/format:csv"],
                capture_output=True, text=True, timeout=5
            )
            if out.returncode == 0:
                for line in out.stdout.strip().split("\n")[1:]:
                    parts = line.strip().split(",")
                    if len(parts) >= 4:
                        gpus.append({
                            "name": parts[2],
                            "vram_bytes": parts[1],
                            "driver": parts[3],
                        })
        else:  # Linux
            out = subprocess.run(
                ["lspci"], capture_output=True, text=True, timeout=5
            )
            if out.returncode == 0:
                for line in out.stdout.split("\n"):
                    if "VGA" in line or "3D" in line:
                        gpus.append({"name": line.split(": ", 1)[-1]})
    except Exception as e:
        logger.debug("GPU detection failed: %s", e)
    return gpus if gpus else None


# ═══════════════════════════════════════════════════════════════════════════════
#  L2 — 服務認知 (Service Awareness)
# ═══════════════════════════════════════════════════════════════════════════════

def _scan_ports(inputs: dict) -> dict:
    """Scan listening ports and their processes."""
    listening = {}

    try:
        import psutil
        connections = psutil.net_connections(kind="inet")
        for conn in connections:
            if conn.status == "LISTEN":
                port = conn.laddr.port
                pid = conn.pid
                proc_name = ""
                try:
                    if pid:
                        proc_name = psutil.Process(pid).name()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
                if port not in listening:
                    listening[port] = {
                        "port": port,
                        "address": conn.laddr.ip,
                        "pid": pid,
                        "process": proc_name,
                    }
    except Exception:
        # Fallback: use lsof/netstat when psutil lacks permissions
        try:
            if _IS_WINDOWS:
                cmd = 'netstat -an | findstr LISTENING'
            else:
                cmd = 'lsof -iTCP -sTCP:LISTEN -nP 2>/dev/null | tail -30'
            out = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
            for line in out.stdout.strip().split("\n"):
                parts = line.split()
                if not parts:
                    continue
                if not _IS_WINDOWS and len(parts) >= 9:
                    proc_name = parts[0]
                    pid = parts[1]
                    addr_port = parts[8]
                    if ":" in addr_port:
                        port_str = addr_port.rsplit(":", 1)[-1]
                        if port_str.isdigit():
                            port = int(port_str)
                            if port not in listening:
                                listening[port] = {
                                    "port": port,
                                    "address": addr_port.rsplit(":", 1)[0],
                                    "pid": int(pid) if pid.isdigit() else None,
                                    "process": proc_name,
                                }
        except Exception:
            pass

    sorted_ports = sorted(listening.values(), key=lambda x: x["port"])
    known = {
        22: "SSH", 80: "HTTP", 443: "HTTPS", 3000: "Dev Server",
        3306: "MySQL", 5432: "PostgreSQL", 5672: "RabbitMQ",
        6379: "Redis", 8080: "HTTP Alt", 8100: "ArcMind",
        8443: "HTTPS Alt", 9090: "Prometheus", 27017: "MongoDB",
        1433: "MSSQL", 1521: "Oracle", 5601: "Kibana",
        9200: "Elasticsearch", 2375: "Docker",
    }
    for p in sorted_ports:
        p["service_hint"] = known.get(p["port"], "")

    return {"listening_ports": sorted_ports, "count": len(sorted_ports)}


def _list_services(inputs: dict) -> dict:
    """List running services (platform-specific)."""
    services = []
    try:
        if _IS_MAC:
            # launchd services
            out = subprocess.run(
                ["launchctl", "list"], capture_output=True, text=True, timeout=10
            )
            if out.returncode == 0:
                for line in out.stdout.strip().split("\n")[1:]:
                    parts = line.split("\t")
                    if len(parts) >= 3:
                        pid = parts[0].strip()
                        label = parts[2].strip()
                        if pid != "-" and not label.startswith("com.apple."):
                            services.append({
                                "name": label,
                                "pid": int(pid) if pid.isdigit() else None,
                                "type": "launchd",
                            })

            # Homebrew services
            out = subprocess.run(
                ["brew", "services", "list"], capture_output=True, text=True, timeout=10
            )
            if out.returncode == 0:
                for line in out.stdout.strip().split("\n")[1:]:
                    parts = line.split()
                    if len(parts) >= 2:
                        services.append({
                            "name": parts[0],
                            "status": parts[1],
                            "type": "homebrew",
                        })

        elif _IS_WINDOWS:
            out = subprocess.run(
                ["sc", "query", "type=", "service", "state=", "all"],
                capture_output=True, text=True, timeout=15,
            )
            if out.returncode == 0:
                current = {}
                for line in out.stdout.split("\n"):
                    line = line.strip()
                    if line.startswith("SERVICE_NAME:"):
                        if current:
                            services.append(current)
                        current = {"name": line.split(":", 1)[1].strip(), "type": "winsvc"}
                    elif "STATE" in line and ":" in line:
                        state = line.split(":", 1)[1].strip()
                        current["status"] = "running" if "RUNNING" in state else "stopped"
                if current:
                    services.append(current)
                # Only show running
                services = [s for s in services if s.get("status") == "running"]

        else:  # Linux
            out = subprocess.run(
                ["systemctl", "list-units", "--type=service", "--state=running", "--no-pager", "--plain"],
                capture_output=True, text=True, timeout=10,
            )
            if out.returncode == 0:
                for line in out.stdout.strip().split("\n")[1:]:
                    parts = line.split()
                    if parts:
                        services.append({"name": parts[0], "type": "systemd"})

    except Exception as e:
        logger.debug("Service listing error: %s", e)

    return {"services": services[:50], "count": len(services)}


def _find_configs(inputs: dict) -> dict:
    """Discover configuration files for known services."""
    search_root = inputs.get("root", str(Path.home()))
    max_depth = inputs.get("max_depth", 3)

    patterns = {
        "docker-compose": ["docker-compose.yml", "docker-compose.yaml", "compose.yml"],
        "nginx": ["nginx.conf"],
        "env": [".env"],
        "package": ["package.json"],
        "requirements": ["requirements.txt"],
        "dockerfile": ["Dockerfile"],
    }

    # Windows-specific
    if _IS_WINDOWS:
        patterns["iis"] = ["web.config", "applicationHost.config"]

    found = []
    root = Path(search_root)
    for category, filenames in patterns.items():
        for fn in filenames:
            try:
                # Use find/where for speed instead of Python walk
                if _IS_WINDOWS:
                    cmd = f'where /r "{root}" {fn} 2>nul'
                else:
                    cmd = f'find "{root}" -maxdepth {max_depth} -name "{fn}" -type f 2>/dev/null | head -20'

                out = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
                for line in out.stdout.strip().split("\n"):
                    if line.strip():
                        found.append({"category": category, "file": fn, "path": line.strip()})
            except Exception:
                continue

    return {"configs": found[:30], "count": len(found)}


def _db_discovery(inputs: dict) -> dict:
    """Discover databases by scanning common ports and files."""
    import psutil

    databases = []
    db_ports = {
        3306: "MySQL",
        5432: "PostgreSQL",
        1433: "MSSQL",
        1521: "Oracle",
        27017: "MongoDB",
        6379: "Redis",
        5601: "Kibana",
        9200: "Elasticsearch",
    }

    try:
        import psutil
        connections = psutil.net_connections(kind="inet")
        for conn in connections:
            if conn.status == "LISTEN" and conn.laddr.port in db_ports:
                db_type = db_ports[conn.laddr.port]
                proc_name = ""
                try:
                    if conn.pid:
                        proc_name = psutil.Process(conn.pid).name()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
                databases.append({
                    "type": db_type,
                    "port": conn.laddr.port,
                    "address": conn.laddr.ip,
                    "process": proc_name,
                    "pid": conn.pid,
                })
    except Exception:
        # Fallback: check from port scan results
        port_scan = _scan_ports({})
        for p in port_scan.get("listening_ports", []):
            if p["port"] in db_ports:
                databases.append({
                    "type": db_ports[p["port"]],
                    "port": p["port"],
                    "address": p.get("address", ""),
                    "process": p.get("process", ""),
                })

    # Also check for SQLite files in common locations
    for db_dir in [Path.home() / "Code", Path.home() / "Projects", Path.home()]:
        if db_dir.exists():
            try:
                out = subprocess.run(
                    f'find "{db_dir}" -maxdepth 3 -name "*.db" -o -name "*.sqlite" -o -name "*.sqlite3" 2>/dev/null | head -10',
                    shell=True, capture_output=True, text=True, timeout=5
                )
                for line in out.stdout.strip().split("\n"):
                    if line.strip():
                        databases.append({"type": "SQLite", "path": line.strip()})
            except Exception:
                pass

    return {"databases": databases, "count": len(databases)}


# ═══════════════════════════════════════════════════════════════════════════════
#  L3 — 網路拓撲認知 (Network Awareness) — 被動模式
# ═══════════════════════════════════════════════════════════════════════════════

def _network_interfaces(inputs: dict) -> dict:
    """List all network interfaces and IPs."""
    import psutil

    interfaces = []
    addrs = psutil.net_if_addrs()
    stats = psutil.net_if_stats()

    for name, addr_list in addrs.items():
        iface = {"name": name, "addresses": [], "is_up": False}
        if name in stats:
            iface["is_up"] = stats[name].isup
            iface["speed_mbps"] = stats[name].speed
            iface["mtu"] = stats[name].mtu

        for addr in addr_list:
            if addr.family == socket.AF_INET:
                iface["addresses"].append({
                    "type": "IPv4",
                    "address": addr.address,
                    "netmask": addr.netmask,
                    "broadcast": addr.broadcast,
                })
            elif addr.family == socket.AF_INET6:
                iface["addresses"].append({
                    "type": "IPv6",
                    "address": addr.address,
                })

        # Skip purely loopback or no-IP interfaces
        has_ip = any(a["type"] == "IPv4" and a["address"] != "127.0.0.1" for a in iface["addresses"])
        if has_ip or iface["is_up"]:
            interfaces.append(iface)

    return {"interfaces": interfaces, "count": len(interfaces)}


def _arp_table(inputs: dict) -> dict:
    """Read ARP cache (passive — no packets sent)."""
    entries = []
    try:
        if _IS_WINDOWS:
            out = subprocess.run(["arp", "-a"], capture_output=True, text=True, timeout=5)
        else:
            out = subprocess.run(["arp", "-a"], capture_output=True, text=True, timeout=5)

        if out.returncode == 0:
            for line in out.stdout.strip().split("\n"):
                line = line.strip()
                if not line or "incomplete" in line.lower():
                    continue
                # macOS/Linux: host (ip) at mac on iface
                # Windows:   ip   mac   type
                if _IS_WINDOWS:
                    parts = line.split()
                    if len(parts) >= 3 and "." in parts[0]:
                        entries.append({
                            "ip": parts[0],
                            "mac": parts[1],
                            "type": parts[2] if len(parts) > 2 else "",
                        })
                else:
                    if "(" in line and ")" in line:
                        ip_part = line.split("(")[1].split(")")[0]
                        mac_part = ""
                        if " at " in line:
                            mac_part = line.split(" at ")[1].split(" ")[0]
                        iface = ""
                        if " on " in line:
                            iface = line.split(" on ")[1].split(" ")[0]
                        if ip_part and mac_part and mac_part != "(incomplete)":
                            entries.append({
                                "ip": ip_part,
                                "mac": mac_part,
                                "interface": iface,
                            })
    except Exception as e:
        logger.debug("ARP table read error: %s", e)

    return {"arp_entries": entries, "count": len(entries)}


def _route_table(inputs: dict) -> dict:
    """Read routing table (passive)."""
    routes = []
    try:
        if _IS_WINDOWS:
            out = subprocess.run(["route", "print"], capture_output=True, text=True, timeout=5)
        elif _IS_MAC:
            out = subprocess.run(["netstat", "-rn"], capture_output=True, text=True, timeout=5)
        else:
            out = subprocess.run(["ip", "route"], capture_output=True, text=True, timeout=5)

        if out.returncode == 0:
            for line in out.stdout.strip().split("\n"):
                line = line.strip()
                if not line or line.startswith("Routing") or line.startswith("Kernel"):
                    continue
                routes.append(line)
    except Exception as e:
        logger.debug("Route table read error: %s", e)

    return {"routes": routes[:30], "count": len(routes)}


# ═══════════════════════════════════════════════════════════════════════════════
#  Full Scan — 一次掃描全部層級
# ═══════════════════════════════════════════════════════════════════════════════

def _full_scan(inputs: dict) -> dict:
    """Run L1+L2+L3 and save to topology."""
    results = {
        "L1_host": _host_info(inputs),
        "L2_ports": _scan_ports(inputs),
        "L2_services": _list_services(inputs),
        "L2_databases": _db_discovery(inputs),
        "L3_interfaces": _network_interfaces(inputs),
        "L3_arp": _arp_table(inputs),
        "L3_routes": _route_table(inputs),
        "scan_time": datetime.now().isoformat(),
    }

    # Save to topology
    try:
        from memory.env_topology import update_topology
        update_topology("L1", results["L1_host"])
        update_topology("L2", {
            "ports": results["L2_ports"],
            "services": results["L2_services"],
            "databases": results["L2_databases"],
        })
        update_topology("L3", {
            "interfaces": results["L3_interfaces"],
            "arp": results["L3_arp"],
            "routes": results["L3_routes"],
        })
        results["topology_saved"] = True
    except Exception as e:
        results["topology_saved"] = False
        results["topology_error"] = str(e)

    return results


# ═══════════════════════════════════════════════════════════════════════════════
#  Main Entry Point
# ═══════════════════════════════════════════════════════════════════════════════

_ACTIONS = {
    # L1 Host
    "host_info": _host_info,
    "resource_check": _resource_check,
    # L2 Service
    "scan_ports": _scan_ports,
    "list_services": _list_services,
    "find_configs": _find_configs,
    "db_discovery": _db_discovery,
    # L3 Network (passive only)
    "network_interfaces": _network_interfaces,
    "arp_table": _arp_table,
    "route_table": _route_table,
    # Full scan
    "full_scan": _full_scan,
}


def run(inputs: dict) -> dict:
    """
    Environment Discovery — 三維度認知掃描。

    L1 宿主機:
      host_info       — OS/CPU/RAM/Disk/GPU/Uptime 完整快照
      resource_check  — 資源預檢（required_ram_gb, required_disk_gb）

    L2 服務:
      scan_ports      — 本機 TCP LISTEN 端口 + 進程
      list_services   — 運行中服務 (launchd/systemd/winsvc)
      find_configs    — 搜尋設定檔 (docker-compose/nginx/.env 等)
      db_discovery    — 發現資料庫

    L3 網路 (被動模式):
      network_interfaces — 網卡/IP/子網
      arp_table          — ARP 快取（不發封包）
      route_table        — 路由表

    全層掃描:
      full_scan — L1+L2+L3 一次完成 + 存入拓撲圖
    """
    action = inputs.get("action", "")
    handler = _ACTIONS.get(action)
    if not handler:
        return {"error": f"Unknown action: {action}", "available": list(_ACTIONS.keys())}
    try:
        return handler(inputs)
    except Exception as e:
        logger.error("[EnvDiscovery] %s failed: %s", action, e)
        return {"error": str(e), "action": action}
