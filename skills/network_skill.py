"""
Skill: network_skill
網路診斷 — ping, DNS lookup, port check, HTTP request, traceroute
"""
from __future__ import annotations
import json, logging, socket, subprocess, time, urllib.request, urllib.error
logger = logging.getLogger("arcmind.skill.network")

def _ping(inputs: dict) -> dict:
    host = inputs.get("host", "")
    count = int(inputs.get("count", 4))
    if not host:
        return {"success": False, "error": "host 為必填"}
    r = subprocess.run(["ping", "-c", str(count), host], capture_output=True, timeout=30)
    return {"success": r.returncode == 0, "output": r.stdout.decode("utf-8", errors="replace")[:2000],
            "host": host}

def _dns_lookup(inputs: dict) -> dict:
    host = inputs.get("host", "")
    record_type = inputs.get("record_type", "A")
    if not host:
        return {"success": False, "error": "host 為必填"}
    try:
        r = subprocess.run(["dig", "+short", host, record_type], capture_output=True, timeout=10)
        records = [l.strip() for l in r.stdout.decode().strip().split("\n") if l.strip()]
        return {"success": True, "host": host, "type": record_type, "records": records}
    except FileNotFoundError:
        # fallback to socket
        try:
            ips = socket.getaddrinfo(host, None)
            records = list(set(addr[4][0] for addr in ips))
            return {"success": True, "host": host, "type": "A", "records": records}
        except socket.gaierror as e:
            return {"success": False, "error": str(e)}

def _port_check(inputs: dict) -> dict:
    host = inputs.get("host", "")
    ports = inputs.get("ports", [80, 443])
    timeout_s = float(inputs.get("timeout", 3))
    if not host:
        return {"success": False, "error": "host 為必填"}
    results = []
    for port in ports:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout_s)
        try:
            sock.connect((host, int(port)))
            results.append({"port": port, "status": "open"})
        except (socket.timeout, ConnectionRefusedError, OSError):
            results.append({"port": port, "status": "closed"})
        finally:
            sock.close()
    return {"success": True, "host": host, "results": results}

def _http_request(inputs: dict) -> dict:
    url = inputs.get("url", "")
    method = inputs.get("method", "GET").upper()
    if not url:
        return {"success": False, "error": "url 為必填"}
    start = time.time()
    try:
        req = urllib.request.Request(url, method=method)
        headers = inputs.get("headers", {})
        for k, v in headers.items():
            req.add_header(k, v)
        with urllib.request.urlopen(req, timeout=15) as resp:
            elapsed = round(time.time() - start, 3)
            body = resp.read(10000).decode("utf-8", errors="replace")
            return {"success": True, "status": resp.status, "headers": dict(resp.headers),
                    "body": body, "elapsed_s": elapsed, "url": url}
    except urllib.error.HTTPError as e:
        return {"success": False, "status": e.code, "error": str(e), "url": url}
    except Exception as e:
        return {"success": False, "error": str(e), "url": url}

def _traceroute(inputs: dict) -> dict:
    host = inputs.get("host", "")
    if not host:
        return {"success": False, "error": "host 為必填"}
    r = subprocess.run(["traceroute", "-m", "15", host], capture_output=True, timeout=60)
    return {"success": r.returncode == 0,
            "output": r.stdout.decode("utf-8", errors="replace")[:3000], "host": host}

def _whois(inputs: dict) -> dict:
    domain = inputs.get("domain", "")
    if not domain:
        return {"success": False, "error": "domain 為必填"}
    r = subprocess.run(["whois", domain], capture_output=True, timeout=15)
    return {"success": r.returncode == 0,
            "output": r.stdout.decode("utf-8", errors="replace")[:3000], "domain": domain}

def run(inputs: dict) -> dict:
    action = inputs.get("action", "ping")
    handlers = {"ping": _ping, "dns": _dns_lookup, "port_check": _port_check,
                "http": _http_request, "traceroute": _traceroute, "whois": _whois}
    h = handlers.get(action)
    if not h:
        return {"success": False, "error": f"未知 action: {action}", "available_actions": list(handlers.keys())}
    try:
        return h(inputs)
    except Exception as e:
        logger.error("[network] %s failed: %s", action, e)
        return {"success": False, "error": str(e)}
