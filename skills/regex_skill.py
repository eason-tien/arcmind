"""
Skill: regex_skill
正規表達式工具 — 測試/匹配/替換/提取/解釋
"""
from __future__ import annotations
import logging, re
logger = logging.getLogger("arcmind.skill.regex")

def _test(inputs: dict) -> dict:
    pattern = inputs.get("pattern", "")
    text = inputs.get("text", "")
    flags = _parse_flags(inputs.get("flags", ""))
    if not pattern or not text:
        return {"success": False, "error": "pattern 和 text 為必填"}
    try:
        compiled = re.compile(pattern, flags)
        match = compiled.search(text)
        return {"success": True, "matches": match is not None,
                "match": match.group(0) if match else None,
                "span": list(match.span()) if match else None}
    except re.error as e:
        return {"success": False, "error": f"正規表達式錯誤: {e}"}

def _find_all(inputs: dict) -> dict:
    pattern = inputs.get("pattern", "")
    text = inputs.get("text", "")
    flags = _parse_flags(inputs.get("flags", ""))
    if not pattern or not text:
        return {"success": False, "error": "pattern 和 text 為必填"}
    try:
        matches = re.findall(pattern, text, flags)
        return {"success": True, "matches": matches[:200], "count": len(matches)}
    except re.error as e:
        return {"success": False, "error": f"正規表達式錯誤: {e}"}

def _replace(inputs: dict) -> dict:
    pattern = inputs.get("pattern", "")
    replacement = inputs.get("replacement", "")
    text = inputs.get("text", "")
    flags = _parse_flags(inputs.get("flags", ""))
    count = int(inputs.get("count", 0))
    if not pattern or not text:
        return {"success": False, "error": "pattern 和 text 為必填"}
    try:
        result = re.sub(pattern, replacement, text, count=count, flags=flags)
        changes = result != text
        return {"success": True, "result": result[:10000], "changed": changes}
    except re.error as e:
        return {"success": False, "error": f"正規表達式錯誤: {e}"}

def _extract_groups(inputs: dict) -> dict:
    pattern = inputs.get("pattern", "")
    text = inputs.get("text", "")
    flags = _parse_flags(inputs.get("flags", ""))
    if not pattern or not text:
        return {"success": False, "error": "pattern 和 text 為必填"}
    try:
        matches = []
        for m in re.finditer(pattern, text, flags):
            entry = {"full_match": m.group(0), "groups": list(m.groups())}
            if m.groupdict():
                entry["named_groups"] = m.groupdict()
            matches.append(entry)
        return {"success": True, "matches": matches[:100], "count": len(matches)}
    except re.error as e:
        return {"success": False, "error": f"正規表達式錯誤: {e}"}

def _split(inputs: dict) -> dict:
    pattern = inputs.get("pattern", "")
    text = inputs.get("text", "")
    if not pattern or not text:
        return {"success": False, "error": "pattern 和 text 為必填"}
    try:
        parts = re.split(pattern, text)
        return {"success": True, "parts": parts[:200], "count": len(parts)}
    except re.error as e:
        return {"success": False, "error": f"正規表達式錯誤: {e}"}

def _common_patterns(inputs: dict) -> dict:
    return {"success": True, "patterns": {
        "email": r"[\w.+-]+@[\w-]+\.[\w.-]+",
        "url": r"https?://[^\s<>\"']+",
        "ip_v4": r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b",
        "phone_tw": r"09\d{2}-?\d{3}-?\d{3}",
        "date_iso": r"\d{4}-\d{2}-\d{2}",
        "date_slash": r"\d{2}/\d{2}/\d{4}",
        "chinese": r"[\u4e00-\u9fff]+",
        "html_tag": r"<[^>]+>",
        "number": r"-?\d+\.?\d*",
        "uuid": r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    }}

def _parse_flags(flags_str: str) -> int:
    flags = 0
    if not flags_str:
        return flags
    flag_map = {"i": re.IGNORECASE, "m": re.MULTILINE, "s": re.DOTALL, "x": re.VERBOSE}
    for c in flags_str:
        if c in flag_map:
            flags |= flag_map[c]
    return flags

def run(inputs: dict) -> dict:
    action = inputs.get("action", "test")
    handlers = {"test": _test, "find_all": _find_all, "replace": _replace,
                "extract_groups": _extract_groups, "split": _split, "common_patterns": _common_patterns}
    h = handlers.get(action)
    if not h:
        return {"success": False, "error": f"未知 action: {action}", "available_actions": list(handlers.keys())}
    try:
        return h(inputs)
    except Exception as e:
        logger.error("[regex] %s failed: %s", action, e)
        return {"success": False, "error": str(e)}
