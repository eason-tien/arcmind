"""
Skill: summarize_skill
內容摘要技能 — 對文字、URL、檔案進行 LLM 摘要。

支援來源: text / url / file
支援格式: brief / detailed / bullet_points
支援語言: zh-TW / en
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger("arcmind.skill.summarize")


def _fetch_url_text(url: str, max_chars: int = 15000) -> str:
    """使用 Jina Reader 提取 URL 的乾淨文字。"""
    try:
        import httpx
        resp = httpx.get(
            f"https://r.jina.ai/{url}",
            headers={"Accept": "text/plain", "X-Return-Format": "text"},
            timeout=20,
            follow_redirects=True,
        )
        if resp.status_code == 200:
            return resp.text.strip()[:max_chars]
    except Exception as e:
        logger.warning("[summarize] URL fetch failed: %s", e)
    return ""


def _read_file_text(file_path: str, max_chars: int = 30000) -> str:
    """讀取本地檔案文字內容。"""
    p = Path(file_path).expanduser()
    if not p.exists():
        raise FileNotFoundError(f"檔案不存在: {file_path}")
    if not p.is_file():
        raise ValueError(f"不是檔案: {file_path}")

    suffix = p.suffix.lower()

    # PDF
    if suffix == ".pdf":
        try:
            import fitz  # PyMuPDF
            doc = fitz.open(str(p))
            text = "\n".join(page.get_text() for page in doc)
            doc.close()
            return text[:max_chars]
        except ImportError:
            return f"[需要 pip install PyMuPDF 來讀取 PDF: {p.name}]"

    # DOCX
    if suffix == ".docx":
        try:
            import docx
            doc = docx.Document(str(p))
            text = "\n".join(para.text for para in doc.paragraphs)
            return text[:max_chars]
        except ImportError:
            return f"[需要 pip install python-docx 來讀取 DOCX: {p.name}]"

    # Plain text / Markdown / Code
    try:
        return p.read_text(encoding="utf-8", errors="replace")[:max_chars]
    except Exception:
        return p.read_text(encoding="latin-1", errors="replace")[:max_chars]


def _build_prompt(text: str, style: str, language: str,
                  focus: str = "", max_length: int = 0) -> tuple[str, str]:
    """Build system prompt and user prompt for summarization."""
    lang_map = {"zh-TW": "繁體中文", "en": "English", "zh": "中文"}
    lang_str = lang_map.get(language, language)

    style_instructions = {
        "brief": f"用 {lang_str} 寫一段簡短摘要（3~5 句話）。",
        "detailed": f"用 {lang_str} 寫一份詳細結構化摘要，包含：\n1. 主旨\n2. 關鍵要點\n3. 重要數據/細節\n4. 結論/行動建議",
        "bullet_points": f"用 {lang_str} 以條列式列出所有重要要點（每點一行，• 開頭）。",
        "executive": f"用 {lang_str} 寫一份高階管理層摘要：\n1. 一句話結論\n2. 背景\n3. 關鍵發現（最多 5 點）\n4. 建議行動",
    }

    instruction = style_instructions.get(style, style_instructions["brief"])

    if focus:
        instruction += f"\n\n重點關注: {focus}"
    if max_length > 0:
        instruction += f"\n\n字數上限: {max_length} 字"

    system = "你是專業的內容摘要專家。精確提取核心資訊，不遺漏重要細節，不添加原文沒有的內容。"
    user_prompt = f"{instruction}\n\n---\n以下是要摘要的內容:\n\n{text[:12000]}"

    return system, user_prompt


def run(inputs: dict) -> dict:
    """
    Summarize skill entry point.

    inputs:
      source: "text" | "url" | "file"  (預設 text)
      text: str  (source=text 時必填)
      url: str   (source=url 時必填)
      file_path: str (source=file 時必填)
      style: "brief" | "detailed" | "bullet_points" | "executive" (預設 brief)
      language: "zh-TW" | "en" (預設 zh-TW)
      focus: str  (可選，聚焦摘要方向)
      max_length: int (可選，字數上限)
    """
    source = inputs.get("source", "text")
    style = inputs.get("style", "brief")
    language = inputs.get("language", "zh-TW")
    focus = inputs.get("focus", "")
    max_length = int(inputs.get("max_length", 0))

    # 1. 取得原文
    if source == "url":
        url = inputs.get("url", "")
        if not url:
            return {"success": False, "error": "url 為必填"}
        text = _fetch_url_text(url)
        if not text:
            return {"success": False, "error": f"無法提取 URL 內容: {url}"}
    elif source == "file":
        file_path = inputs.get("file_path", "")
        if not file_path:
            return {"success": False, "error": "file_path 為必填"}
        try:
            text = _read_file_text(file_path)
        except Exception as e:
            return {"success": False, "error": str(e)}
    else:
        text = inputs.get("text", "")
        if not text:
            return {"success": False, "error": "text 為必填"}

    if len(text.strip()) < 50:
        return {"success": False, "error": "內容太短，無法摘要"}

    # 2. LLM 摘要
    try:
        from runtime.model_router import model_router

        system, user_prompt = _build_prompt(text, style, language, focus, max_length)

        resp = model_router.complete(
            prompt=user_prompt,
            system=system,
            max_tokens=2048,
            task_type="general",
            budget="medium",
        )
        summary = resp.content.strip()

        # Strip think tags
        summary = re.sub(r'<think>[\s\S]*?</think>\s*', '', summary).strip()

        return {
            "success": True,
            "summary": summary,
            "source": source,
            "style": style,
            "language": language,
            "original_length": len(text),
            "summary_length": len(summary),
            "compression_ratio": round(len(summary) / len(text), 3) if text else 0,
        }

    except Exception as e:
        logger.error("[summarize] LLM summarization failed: %s", e)
        return {"success": False, "error": str(e)}
