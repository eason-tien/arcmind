# -*- coding: utf-8 -*-
"""
ArcMind — Lightweight Audit Guard
====================================
只做兩件事：
  1. 委派參數防幻覺 — tool call 參數跟用戶指令零重疊就打回
  2. 洩漏偵測 — model 把 JSON tool call 當文字吐給用戶就打回

設計: 邊界，不是牆。只攔「完全離譜」的，其他全放行。
"""
from __future__ import annotations

import contextvars
import logging
import re

logger = logging.getLogger("arcmind.audit")

# ── 原始指令上下文（contextvars，thread-safe）──
_audit_context: contextvars.ContextVar[str] = contextvars.ContextVar(
    "_audit_context", default=""
)


def set_context(prompt: str) -> None:
    _audit_context.set(prompt)


def get_context() -> str:
    return _audit_context.get("")


# ═══════════════════════════════════════════════════════════════════════════
#  1. 委派參數防幻覺
# ═══════════════════════════════════════════════════════════════════════════

def check_tool_params(tool_name: str, params: dict) -> str | None:
    """
    只檢查 delegate_* 工具。
    有任何重疊 → None (放行)。
    零重疊 → 回傳 reason 字串 (打回)。
    """
    if not tool_name.startswith("delegate_"):
        return None  # 非委派工具，不管

    original = get_context()
    if not original:
        return None  # 無上下文，不管

    # 撈參數裡的文字
    texts = []
    for k in ("title", "instruction", "query", "description"):
        v = params.get(k)
        if isinstance(v, str) and v.strip():
            texts.append(v)
    td = params.get("task_data")
    if isinstance(td, dict):
        for k in ("instructions", "query", "description"):
            v = td.get(k)
            if isinstance(v, str) and v.strip():
                texts.append(v)

    if not texts:
        return None

    param_text = " ".join(texts)

    # 有任何重疊就放行（三軌: token / CJK字 / CJK二元組）
    if _any_overlap(original, param_text):
        return None

    logger.warning("[Audit] 幻覺參數: original='%s' param='%s'",
                   original[:50], param_text[:50])
    return (
        f"參數跟用戶指令無關。用戶說的是「{original[:60]}」，"
        f"請根據用戶的實際需求行動，不要編造任務。"
    )


def _any_overlap(a: str, b: str) -> bool:
    """有任何一軌有重疊就回 True — 最大限度避免誤殺。"""
    # Token
    ta = {t for t in a.lower().split() if len(t) >= 4}
    tb = {t for t in b.lower().split() if len(t) >= 4}
    if ta & tb:
        return True
    # CJK 單字
    ca = {c for c in a if "\u4e00" <= c <= "\u9fff"}
    cb = {c for c in b if "\u4e00" <= c <= "\u9fff"}
    if ca & cb:
        return True
    # CJK 二元組
    def bigrams(s):
        ch = [c for c in s if "\u4e00" <= c <= "\u9fff"]
        return {ch[i] + ch[i + 1] for i in range(len(ch) - 1)} if len(ch) >= 2 else set()
    if bigrams(a) & bigrams(b):
        return True
    return False


# ═══════════════════════════════════════════════════════════════════════════
#  2. 洩漏偵測
# ═══════════════════════════════════════════════════════════════════════════

def is_leaked_tool_call(text: str) -> bool:
    """model 把 function call JSON 當文字吐出來了嗎？"""
    if not text or len(text) < 30:
        return False
    tl = text.lower()

    # JSON 結構指標 ≥ 3 個同時出現
    indicators = [
        '"name":', '"arguments":', '"function_call":', '"tool_call":',
        '"assignee":', '"task_data":', '"function":', '"tool_calls":',
    ]
    if sum(1 for i in indicators if i in tl) >= 3:
        return True

    # XML tool call format (MiniMax)
    if "<minimax:tool_call>" in tl or "[tool_call]" in tl:
        return True

    # Model 在描述自己的 tool call
    if re.search(r"json\s*object\s*(that|which)\s*represents\s*(a\s*)?function", tl):
        return True
    if re.search(r"function\s*(is\s*)?call(ed)?\s*with.*arguments", tl):
        return True

    return False
