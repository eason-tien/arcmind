"""
Skill: api_tester
HTTP API 測試工具 — GET/POST/PUT/DELETE + 驗證
類似 curl/Postman，支援 JSON body, headers, auth
"""
from __future__ import annotations
import json, logging, time, urllib.request, urllib.error, urllib.parse
logger = logging.getLogger("arcmind.skill.api_tester")

def _request(inputs: dict) -> dict:
    url = inputs.get("url", "")
    method = inputs.get("method", "GET").upper()
    headers = inputs.get("headers", {})
    body = inputs.get("body")
    auth = inputs.get("auth")  # {"type": "bearer", "token": "..."} or {"type": "basic", "user": "...", "pass": "..."}
    timeout_s = int(inputs.get("timeout", 15))
    if not url:
        return {"success": False, "error": "url 為必填"}
    # Build request
    data = None
    if body:
        if isinstance(body, dict):
            data = json.dumps(body).encode("utf-8")
            headers.setdefault("Content-Type", "application/json")
        elif isinstance(body, str):
            data = body.encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method)
    for k, v in headers.items():
        req.add_header(k, v)
    # Auth
    if auth:
        if auth.get("type") == "bearer":
            req.add_header("Authorization", f"Bearer {auth['token']}")
        elif auth.get("type") == "basic":
            import base64
            cred = base64.b64encode(f"{auth['user']}:{auth['pass']}".encode()).decode()
            req.add_header("Authorization", f"Basic {cred}")
    start = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            elapsed = round(time.time() - start, 3)
            resp_body = resp.read(50000).decode("utf-8", errors="replace")
            resp_headers = dict(resp.headers)
            # Try parse JSON
            parsed = None
            if "application/json" in resp_headers.get("Content-Type", ""):
                try:
                    parsed = json.loads(resp_body)
                except json.JSONDecodeError:
                    pass
            return {"success": True, "status": resp.status, "headers": resp_headers,
                    "body": parsed if parsed else resp_body[:10000],
                    "elapsed_s": elapsed, "method": method, "url": url, "is_json": parsed is not None}
    except urllib.error.HTTPError as e:
        elapsed = round(time.time() - start, 3)
        body_text = ""
        try:
            body_text = e.read(5000).decode("utf-8", errors="replace")
        except Exception:
            pass
        return {"success": False, "status": e.code, "reason": e.reason,
                "body": body_text, "elapsed_s": elapsed, "method": method, "url": url}
    except Exception as e:
        return {"success": False, "error": str(e), "method": method, "url": url}

def _chain(inputs: dict) -> dict:
    """Run multiple API requests in sequence."""
    requests = inputs.get("requests", [])
    if not requests:
        return {"success": False, "error": "requests 為必填 (list of request objects)"}
    results = []
    context = {}
    for i, req in enumerate(requests[:10]):
        # Variable substitution from previous results
        for key in ["url", "body"]:
            if isinstance(req.get(key), str):
                for var, val in context.items():
                    req[key] = req[key].replace(f"${{{var}}}", str(val))
        result = _request(req)
        results.append({"step": i + 1, **result})
        # Extract variables for next steps
        if result.get("success") and isinstance(result.get("body"), dict):
            for k, v in result["body"].items():
                context[f"step{i+1}.{k}"] = v
    return {"success": True, "results": results, "steps": len(results)}

def run(inputs: dict) -> dict:
    action = inputs.get("action", "request")
    handlers = {"request": _request, "chain": _chain}
    h = handlers.get(action)
    if not h:
        return {"success": False, "error": f"未知 action: {action}", "available_actions": list(handlers.keys())}
    try:
        return h(inputs)
    except Exception as e:
        logger.error("[api_tester] %s failed: %s", action, e)
        return {"success": False, "error": str(e)}
