"""
Skill: json_tool
JSON/YAML/CSV 資料處理 — 格式轉換/查詢/驗證/合併
"""
from __future__ import annotations
import csv, io, json, logging
from pathlib import Path
logger = logging.getLogger("arcmind.skill.json_tool")

def _parse(inputs: dict) -> dict:
    """Parse and validate JSON/YAML/CSV."""
    text = inputs.get("text", "")
    file_path = inputs.get("file_path", "")
    fmt = inputs.get("format", "auto")
    if file_path:
        text = Path(file_path).expanduser().read_text(encoding="utf-8", errors="replace")
    if not text:
        return {"success": False, "error": "text 或 file_path 為必填"}
    if fmt == "auto":
        fmt = "yaml" if text.lstrip().startswith("---") or ": " in text.split("\n")[0] else "json"
        if "," in text.split("\n")[0] and not text.lstrip().startswith("{"):
            fmt = "csv"
    if fmt == "json":
        data = json.loads(text)
    elif fmt == "yaml":
        import yaml
        data = yaml.safe_load(text)
    elif fmt == "csv":
        reader = csv.DictReader(io.StringIO(text))
        data = list(reader)
    else:
        return {"success": False, "error": f"不支援格式: {fmt}"}
    return {"success": True, "data": data, "format": fmt, "type": type(data).__name__}

def _convert(inputs: dict) -> dict:
    """Convert between JSON/YAML/CSV."""
    data = inputs.get("data")
    text = inputs.get("text", "")
    from_fmt = inputs.get("from", "json")
    to_fmt = inputs.get("to", "yaml")
    if text and not data:
        r = _parse({"text": text, "format": from_fmt})
        if not r["success"]:
            return r
        data = r["data"]
    if data is None:
        return {"success": False, "error": "data 或 text 為必填"}
    if to_fmt == "json":
        result = json.dumps(data, ensure_ascii=False, indent=2)
    elif to_fmt == "yaml":
        import yaml
        result = yaml.dump(data, allow_unicode=True, default_flow_style=False)
    elif to_fmt == "csv":
        if not isinstance(data, list):
            return {"success": False, "error": "CSV 需要 list of dicts"}
        output = io.StringIO()
        if data and isinstance(data[0], dict):
            writer = csv.DictWriter(output, fieldnames=data[0].keys())
            writer.writeheader()
            writer.writerows(data)
        result = output.getvalue()
    else:
        return {"success": False, "error": f"不支援: {to_fmt}"}
    output_path = inputs.get("output", "")
    if output_path:
        Path(output_path).write_text(result, encoding="utf-8")
    return {"success": True, "result": result[:5000], "format": to_fmt,
            "saved_to": output_path if output_path else None}

def _query(inputs: dict) -> dict:
    """Query JSON data using JMESPath or simple dot notation."""
    data = inputs.get("data")
    text = inputs.get("text", "")
    path = inputs.get("path", "")
    if text and not data:
        data = json.loads(text)
    if data is None or not path:
        return {"success": False, "error": "data 和 path 為必填"}
    try:
        import jmespath
        result = jmespath.search(path, data)
        return {"success": True, "result": result, "engine": "jmespath"}
    except ImportError:
        pass
    # Simple dot notation fallback
    current = data
    for key in path.split("."):
        if isinstance(current, dict):
            current = current.get(key)
        elif isinstance(current, list) and key.isdigit():
            current = current[int(key)]
        else:
            return {"success": False, "error": f"路徑無效: {path}"}
    return {"success": True, "result": current, "engine": "dot_notation"}

def _merge(inputs: dict) -> dict:
    """Merge multiple JSON objects or arrays."""
    items = inputs.get("items", [])
    if len(items) < 2:
        return {"success": False, "error": "至少需要 2 個 items"}
    if all(isinstance(i, dict) for i in items):
        result = {}
        for item in items:
            result.update(item)
    elif all(isinstance(i, list) for i in items):
        result = []
        for item in items:
            result.extend(item)
    else:
        return {"success": False, "error": "items 必須全部是 dict 或全部是 list"}
    return {"success": True, "result": result, "merged_count": len(items)}

def _validate(inputs: dict) -> dict:
    """Validate JSON/YAML syntax."""
    text = inputs.get("text", "")
    fmt = inputs.get("format", "json")
    if not text:
        return {"success": False, "error": "text 為必填"}
    try:
        if fmt == "json":
            json.loads(text)
        elif fmt == "yaml":
            import yaml
            yaml.safe_load(text)
        return {"success": True, "valid": True, "format": fmt}
    except Exception as e:
        return {"success": True, "valid": False, "format": fmt, "error": str(e)}

def run(inputs: dict) -> dict:
    action = inputs.get("action", "parse")
    handlers = {"parse": _parse, "convert": _convert, "query": _query,
                "merge": _merge, "validate": _validate}
    h = handlers.get(action)
    if not h:
        return {"success": False, "error": f"未知 action: {action}", "available_actions": list(handlers.keys())}
    try:
        return h(inputs)
    except Exception as e:
        logger.error("[json_tool] %s failed: %s", action, e)
        return {"success": False, "error": str(e)}
