"""
Skill: translation_skill
多語言翻譯 — LLM 翻譯 + DeepL API fallback

支援: 中英日韓泰 + 任意語言
"""
from __future__ import annotations

import logging
import os
import re
from typing import Any

logger = logging.getLogger("arcmind.skill.translation")

_LANGUAGE_MAP = {
    "zh": "中文（繁體）", "zh-TW": "中文（繁體）", "zh-CN": "中文（簡體）",
    "en": "English", "ja": "日本語", "ko": "한국어", "th": "ภาษาไทย",
    "fr": "Français", "de": "Deutsch", "es": "Español", "pt": "Português",
    "it": "Italiano", "ru": "Русский", "ar": "العربية", "vi": "Tiếng Việt",
}


def _translate_deepl(text: str, target_lang: str, source_lang: str = "") -> str | None:
    """Translate using DeepL API."""
    api_key = os.environ.get("DEEPL_API_KEY", "")
    if not api_key:
        return None

    try:
        import httpx

        # DeepL uses uppercase lang codes
        target = target_lang.upper().replace("ZH-TW", "ZH").replace("ZH-CN", "ZH")
        base_url = "https://api-free.deepl.com" if api_key.endswith(":fx") else "https://api.deepl.com"

        params = {
            "auth_key": api_key,
            "text": text,
            "target_lang": target,
        }
        if source_lang:
            params["source_lang"] = source_lang.upper()

        resp = httpx.post(f"{base_url}/v2/translate", data=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        translations = data.get("translations", [])
        if translations:
            return translations[0].get("text", "")
    except Exception as e:
        logger.warning("[translation] DeepL failed: %s", e)
    return None


def _translate_llm(text: str, target_lang: str, source_lang: str = "",
                   style: str = "", glossary: dict | None = None) -> str:
    """Translate using LLM (model_router)."""
    from runtime.model_router import model_router

    target_name = _LANGUAGE_MAP.get(target_lang, target_lang)
    source_name = _LANGUAGE_MAP.get(source_lang, "auto-detect") if source_lang else "auto-detect"

    prompt_parts = [
        f"將以下文字翻譯為 {target_name}。",
        f"來源語言: {source_name}",
    ]
    if style:
        prompt_parts.append(f"翻譯風格: {style}")
    if glossary:
        terms = ", ".join(f"{k}→{v}" for k, v in glossary.items())
        prompt_parts.append(f"術語表: {terms}")
    prompt_parts.extend([
        "規則: 只輸出翻譯結果，不要加任何說明。保留原文格式（換行、標點、Markdown）。",
        "",
        "---",
        text,
    ])

    resp = model_router.complete(
        prompt="\n".join(prompt_parts),
        system="你是專業翻譯員。精確翻譯，保持原文語氣和格式。只輸出翻譯結果。",
        max_tokens=4096,
        task_type="general",
        budget="medium",
    )
    result = resp.content.strip()
    result = re.sub(r'<think>[\s\S]*?</think>\s*', '', result).strip()
    return result


def _detect_language(inputs: dict) -> dict:
    """Detect the language of input text."""
    text = inputs.get("text", "")
    if not text:
        return {"success": False, "error": "text 為必填"}

    try:
        from runtime.model_router import model_router
        resp = model_router.complete(
            prompt=f'Detect the language of this text. Reply with ONLY the ISO 639-1 code (e.g., "en", "zh", "ja", "ko", "th"). Text: "{text[:500]}"',
            system="You are a language detection expert. Reply with only the language code.",
            max_tokens=10,
            task_type="general",
            budget="low",
        )
        lang = resp.content.strip().lower().strip('"').strip("'")
        lang = re.sub(r'<think>[\s\S]*?</think>\s*', '', lang).strip()
        lang_name = _LANGUAGE_MAP.get(lang, lang)
        return {"success": True, "language": lang, "language_name": lang_name}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _translate(inputs: dict) -> dict:
    """Translate text."""
    text = inputs.get("text", "")
    target = inputs.get("target", "en")
    source = inputs.get("source", "")
    style = inputs.get("style", "")  # formal / casual / technical / literary
    glossary = inputs.get("glossary")  # {term: translation}
    use_deepl = inputs.get("use_deepl", True)

    if not text:
        return {"success": False, "error": "text 為必填"}

    # Try DeepL first (faster, higher quality for supported languages)
    if use_deepl and not style and not glossary:
        deepl_result = _translate_deepl(text, target, source)
        if deepl_result:
            return {
                "success": True,
                "translation": deepl_result,
                "engine": "deepl",
                "source_lang": source or "auto",
                "target_lang": target,
                "original_length": len(text),
            }

    # LLM translation
    try:
        result = _translate_llm(text, target, source, style, glossary)
        return {
            "success": True,
            "translation": result,
            "engine": "llm",
            "source_lang": source or "auto",
            "target_lang": target,
            "style": style or "default",
            "original_length": len(text),
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def _batch_translate(inputs: dict) -> dict:
    """Translate multiple texts at once."""
    texts = inputs.get("texts", [])
    target = inputs.get("target", "en")

    if not texts:
        return {"success": False, "error": "texts 為必填（list）"}

    results = []
    for t in texts[:20]:  # Max 20 items
        r = _translate({"text": t, "target": target, "source": inputs.get("source", "")})
        results.append(r.get("translation", r.get("error", "")))

    return {"success": True, "translations": results, "count": len(results)}


def run(inputs: dict) -> dict:
    """
    Translation skill entry point.

    inputs:
      action: translate | detect | batch_translate
      text: str (必填)
      target: str (目標語言 ISO 639-1, 預設 en)
      source: str (來源語言, 可選)
      style: str (formal/casual/technical/literary, 可選)
      glossary: dict (術語表 {term: translation}, 可選)
    """
    action = inputs.get("action", "translate")
    handlers = {
        "translate": _translate,
        "detect": _detect_language,
        "batch_translate": _batch_translate,
    }
    handler = handlers.get(action)
    if not handler:
        return {"success": False, "error": f"未知 action: {action}", "available_actions": list(handlers.keys())}
    try:
        return handler(inputs)
    except Exception as e:
        logger.error("[translation] %s failed: %s", action, e)
        return {"success": False, "error": str(e), "action": action}
