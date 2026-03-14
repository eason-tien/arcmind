"""
Skill: text_tool
文字處理 — diff, word count, 格式化, 行操作, 模板渲染
"""
from __future__ import annotations
import difflib, logging, re, textwrap
logger = logging.getLogger("arcmind.skill.text_tool")

def _diff(inputs: dict) -> dict:
    text1 = inputs.get("text1", "")
    text2 = inputs.get("text2", "")
    context = int(inputs.get("context", 3))
    if not text1 and not text2:
        return {"success": False, "error": "text1 和 text2 至少需要一個"}
    lines1 = text1.splitlines(keepends=True)
    lines2 = text2.splitlines(keepends=True)
    diff = list(difflib.unified_diff(lines1, lines2, fromfile="text1", tofile="text2", n=context))
    return {"success": True, "diff": "".join(diff)[:10000], "changes": len([l for l in diff if l.startswith(("+","-")) and not l.startswith(("+++","---"))])}

def _word_count(inputs: dict) -> dict:
    text = inputs.get("text", "")
    if not text:
        return {"success": False, "error": "text 為必填"}
    words = len(text.split())
    chars = len(text)
    chars_no_space = len(text.replace(" ", "").replace("\n", "").replace("\t", ""))
    lines = text.count("\n") + (1 if text and not text.endswith("\n") else 0)
    sentences = len(re.split(r'[.!?。！？]+', text)) - 1
    # CJK character count
    cjk = len(re.findall(r'[\u4e00-\u9fff\u3400-\u4dbf]', text))
    return {"success": True, "words": words, "characters": chars, "characters_no_space": chars_no_space,
            "lines": lines, "sentences": max(sentences, 0), "cjk_characters": cjk}

def _format_text(inputs: dict) -> dict:
    text = inputs.get("text", "")
    operation = inputs.get("operation", "trim")
    if not text:
        return {"success": False, "error": "text 為必填"}
    ops = {
        "trim": lambda t: t.strip(),
        "upper": lambda t: t.upper(),
        "lower": lambda t: t.lower(),
        "title": lambda t: t.title(),
        "capitalize": lambda t: t.capitalize(),
        "dedent": lambda t: textwrap.dedent(t),
        "wrap": lambda t: textwrap.fill(t, width=int(inputs.get("width", 80))),
        "remove_blank_lines": lambda t: re.sub(r'\n\s*\n', '\n\n', t),
        "sort_lines": lambda t: "\n".join(sorted(t.splitlines())),
        "unique_lines": lambda t: "\n".join(dict.fromkeys(t.splitlines())),
        "reverse_lines": lambda t: "\n".join(reversed(t.splitlines())),
        "number_lines": lambda t: "\n".join(f"{i+1:4d}  {l}" for i, l in enumerate(t.splitlines())),
        "strip_html": lambda t: re.sub(r'<[^>]+>', '', t),
        "normalize_whitespace": lambda t: re.sub(r'\s+', ' ', t).strip(),
    }
    fn = ops.get(operation)
    if not fn:
        return {"success": False, "error": f"未知 operation: {operation}", "available": list(ops.keys())}
    return {"success": True, "result": fn(text)[:10000], "operation": operation}

def _extract(inputs: dict) -> dict:
    text = inputs.get("text", "")
    what = inputs.get("what", "emails")
    if not text:
        return {"success": False, "error": "text 為必填"}
    patterns = {
        "emails": r'[\w.+-]+@[\w-]+\.[\w.-]+',
        "urls": r'https?://[^\s<>"\']+',
        "numbers": r'-?\d+\.?\d*',
        "phones": r'[\+\(]?[\d\s\-\(\)]{7,15}',
        "dates": r'\d{4}[-/]\d{2}[-/]\d{2}',
        "ips": r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b',
    }
    pat = patterns.get(what, what)  # Allow custom pattern
    matches = re.findall(pat, text)
    return {"success": True, "matches": list(set(matches))[:200], "count": len(set(matches)), "pattern": pat}

def _template(inputs: dict) -> dict:
    tmpl = inputs.get("template", "")
    variables = inputs.get("variables", {})
    if not tmpl:
        return {"success": False, "error": "template 為必填"}
    try:
        result = tmpl
        for k, v in variables.items():
            result = result.replace(f"{{{{{k}}}}}", str(v))
            result = result.replace(f"${{{k}}}", str(v))
        return {"success": True, "result": result[:10000]}
    except Exception as e:
        return {"success": False, "error": str(e)}

def run(inputs: dict) -> dict:
    action = inputs.get("action", "word_count")
    handlers = {"diff": _diff, "word_count": _word_count, "format": _format_text,
                "extract": _extract, "template": _template}
    h = handlers.get(action)
    if not h:
        return {"success": False, "error": f"未知 action: {action}", "available_actions": list(handlers.keys())}
    try:
        return h(inputs)
    except Exception as e:
        logger.error("[text_tool] %s failed: %s", action, e)
        return {"success": False, "error": str(e)}
