# -*- coding: utf-8 -*-
"""
ArcMind — Preference Manager (Module A)
=========================================
隱式偏好萃取器：從用戶對話中自動提取習慣與偏好。

機制：
  1. Heuristic Gate：正則前置攔截（低成本）
  2. 觸發後 → 背景 thread 呼叫 Qwen 萃取 JSON
  3. Deep merge 到 data/user_profile.json

絕對不阻塞主迴圈。
"""
from __future__ import annotations

import json
import logging
import re
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger("arcmind.memory.preference")

_PROFILE_PATH = Path(__file__).parent.parent / "data" / "user_profile.json"

# ── Heuristic Gate ──────────────────────────────────────────────────────────

_TRIGGER_PATTERNS = re.compile(
    r"不對|改成|以後|記得|不要|我喜歡|我習慣|請用|別用|"
    r"偏好|風格|格式|預設|默認|always|never|prefer|"
    r"不用|換成|用.{1,4}方式|用.{1,4}格式|"
    r"太長|太短|太簡|太複雜|太囉嗦",
    re.IGNORECASE,
)

_EXTRACTION_PROMPT = """\
分析以下用戶訊息，提取其中隱含的偏好或習慣。
只輸出 JSON，不要任何解釋。

JSON 格式：
{
  "code_style": "偏好的程式碼風格（如有）",
  "language": "偏好的回答語言",
  "output_format": "偏好的輸出格式（簡潔/詳細/程式碼優先）",
  "tools": "偏好的工具或框架",
  "other": "其他偏好"
}

只填寫能從訊息中明確推斷的欄位，其餘設為 null。

用戶訊息：
{user_input}
"""


def should_extract(text: str) -> bool:
    """Heuristic Gate：快速判斷是否可能包含偏好資訊。"""
    return bool(_TRIGGER_PATTERNS.search(text))


def _deep_merge(base: dict, update: dict) -> dict:
    """Deep merge update into base, skipping null values."""
    for k, v in update.items():
        if v is None or v == "null" or v == "":
            continue
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v
    return base


def _load_profile() -> dict:
    """Load user profile from disk."""
    if _PROFILE_PATH.exists():
        try:
            return json.loads(_PROFILE_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_profile(profile: dict) -> None:
    """Save user profile to disk."""
    _PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _PROFILE_PATH.write_text(
        json.dumps(profile, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def _extract_sync(user_input: str) -> None:
    """
    背景執行：呼叫本地 Qwen 萃取偏好 → merge 到 profile。
    此函數在 daemon thread 中執行，絕不阻塞主迴圈。
    """
    try:
        from runtime.model_router import model_router

        prompt = _EXTRACTION_PROMPT.format(user_input=user_input[:500])

        # 使用 Ollama Qwen（輕量、快速）
        resp = model_router.complete(
            prompt=prompt,
            system="你是一個 JSON 提取器，只輸出純 JSON。",
            model="ollama:qwen3:8b",
            max_tokens=256,
        )

        raw = resp.content.strip()
        # 嘗試提取 JSON（可能被 markdown 包裹）
        if "```" in raw:
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()

        extracted = json.loads(raw)
        if not isinstance(extracted, dict):
            return

        # Merge into profile
        profile = _load_profile()
        _deep_merge(profile, extracted)
        _save_profile(profile)

        logger.info("[PreferenceMgr] Extracted and merged preferences: %s",
                    [k for k, v in extracted.items() if v and v != "null"])

    except json.JSONDecodeError:
        logger.debug("[PreferenceMgr] LLM output not valid JSON, skipping")
    except Exception as e:
        logger.warning("[PreferenceMgr] Extraction failed: %s", e)


def extract_and_update_preference(user_input: str) -> None:
    """
    Non-blocking 偏好萃取入口。
    先過 Heuristic Gate，觸發後 fire-and-forget。
    """
    if not should_extract(user_input):
        return

    logger.debug("[PreferenceMgr] Heuristic triggered, spawning extraction thread")
    t = threading.Thread(
        target=_extract_sync,
        args=(user_input,),
        daemon=True,
        name="pref-extract",
    )
    t.start()


def get_preferences_tag() -> str:
    """
    讀取 user_profile.json，返回 <User_Preferences> XML tag。
    同步操作，延遲 < 1ms（純 JSON 讀取）。
    """
    profile = _load_profile()
    if not profile:
        return ""

    # 過濾空值
    active = {k: v for k, v in profile.items() if v and v != "null"}
    if not active:
        return ""

    # 轉為簡潔文本
    parts = []
    for k, v in active.items():
        if isinstance(v, dict):
            sub = ", ".join(f"{sk}: {sv}" for sk, sv in v.items() if sv)
            if sub:
                parts.append(f"{k}: {sub}")
        else:
            parts.append(f"{k}: {v}")

    text = "; ".join(parts)
    return f"<User_Preferences>{text}</User_Preferences>"
