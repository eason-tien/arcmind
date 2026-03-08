# -*- coding: utf-8 -*-
"""
ArcMind — Delegator Engine
============================
MAIN Agent 的任務委派決策引擎。

OODA DECIDE 階段呼叫 `delegator.route(command)`:
  1. 掃描所有 sub-agents 的 capabilities
  2. 根據 keyword → capability 匹配
  3. 匹配成功 → 用 sub-agent 的 model + system_prompt 執行
  4. 無匹配 → MAIN 自己處理

用法：
  from runtime.delegator import delegator

  match = delegator.route("幫我寫一個 Python 排序演算法")
  # match.agent_id == "code", match.model == "ollama:qwen2.5-coder:14b"
"""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from typing import Optional

from runtime.agent_registry import agent_registry

logger = logging.getLogger("arcmind.delegator")


# ── Capability keyword mapping ──────────────────────────────────────────────

_CAPABILITY_KEYWORDS: dict[str, list[str]] = {
    # coding capability
    "coding": [
        "代码", "代碼", "码", "code", "coding", "程序", "程式",
        "function", "函数", "函數", "class", "算法", "演算法",
        "script", "脚本", "腳本", "api", "sdk",
    ],
    "debugging": [
        "debug", "调试", "調試", "bug", "error", "错误", "錯誤",
        "fix", "修复", "修復", "traceback", "exception",
    ],
    "code_review": [
        "review", "审查", "審查", "优化", "優化", "refactor", "重构", "重構",
    ],
    # search capability
    "web_search": [
        "搜索", "搜尋", "search", "google", "查找", "查詢",
        "新闻", "新聞", "news", "最新", "latest",
    ],
    "research": [
        "研究", "调研", "調研", "research", "了解", "什么是", "什麼是",
    ],
    # analysis capability
    "analysis": [
        "分析", "analyze", "analysis", "统计", "統計", "数据", "數據",
        "data", "报告", "報告", "report",
    ],
    "summarize": [
        "摘要", "总结", "總結", "summarize", "summary", "概述",
    ],
}


@dataclass
class DelegationMatch:
    """Result of delegation matching."""
    agent_id: str
    agent_name: str
    model: str
    system_prompt: str
    capability: str
    confidence: float = 1.0


class Delegator:
    """
    Delegation decision engine.
    Routes tasks to the most appropriate sub-agent based on capability matching.
    """

    def _is_onboarding(self) -> bool:
        """Check if onboarding is still in progress."""
        try:
            from pathlib import Path
            user_md = Path(__file__).parent.parent / "USER.md"
            if user_md.exists():
                content = user_md.read_text(encoding="utf-8")
                return "onboarding_complete: false" in content
        except Exception:
            pass
        return False

    def route(self, command: str) -> Optional[DelegationMatch]:
        """
        Check if command should be delegated to a sub-agent.
        Returns DelegationMatch if yes, None if MAIN should handle it.
        """
        # Skip delegation during onboarding
        if self._is_onboarding():
            return None

        cmd_lower = command.lower()

        # Score each capability
        best_cap: str | None = None
        best_score: int = 0

        for capability, keywords in _CAPABILITY_KEYWORDS.items():
            score = sum(1 for kw in keywords if kw in cmd_lower)
            if score > best_score:
                best_score = score
                best_cap = capability

        if not best_cap or best_score == 0:
            return None  # No match → MAIN handles it

        # Find agent with this capability (exclude MAIN)
        candidates = agent_registry.find_by_capability(best_cap)
        candidates = [a for a in candidates if a.id != "main"]

        if not candidates:
            return None  # No sub-agent for this capability

        agent = candidates[0]  # Best match (first)

        logger.info("[Delegator] MATCH: '%s' → agent=%s cap=%s score=%d",
                    command[:40], agent.id, best_cap, best_score)

        return DelegationMatch(
            agent_id=agent.id,
            agent_name=agent.name,
            model=agent.model,
            system_prompt=agent.system_prompt,
            capability=best_cap,
        )

    def execute(
        self,
        match: DelegationMatch,
        command: str,
        system: str | None = None,
    ) -> dict:
        """
        Execute command using the delegated sub-agent's model.
        Uses the tool loop with the sub-agent's model and system prompt.
        """
        t0 = time.time()

        # Use sub-agent's system prompt, fallback to MAIN's
        agent_system = match.system_prompt or system or ""

        # Add delegation context
        delegation_context = (
            f"\n\n## Delegation Context\n"
            f"你是 {match.agent_name}，被 MAIN Agent 委派處理此任務。\n"
            f"專業領域：{match.capability}\n"
            f"請專注在你的專業領域，高品質完成任務。"
        )
        full_system = agent_system + delegation_context

        try:
            from runtime.tool_loop import agentic_complete

            result = agentic_complete(
                prompt=command,
                system=full_system,
                model=match.model,
                task_type=match.capability,
            )

            elapsed = time.time() - t0
            logger.info("[Delegator] done: agent=%s elapsed=%.1fs",
                        match.agent_id, elapsed)

            # Strip <think> tags
            content = result.get("content", "")
            content = re.sub(r"<think>[\s\S]*?</think>\s*", "", content).strip()

            return {
                "success": True,
                "output": content,
                "agent_id": match.agent_id,
                "agent_name": match.agent_name,
                "model": match.model,
                "capability": match.capability,
                "elapsed_s": round(elapsed, 2),
                "delegated": True,
                "tokens": result.get("total_tokens", 0),
                "tool_calls": result.get("tool_calls", []),
            }

        except Exception as e:
            elapsed = time.time() - t0
            logger.error("[Delegator] failed: agent=%s error=%s", match.agent_id, e)
            return {
                "success": False,
                "output": f"Agent '{match.agent_name}' 執行失敗: {e}",
                "agent_id": match.agent_id,
                "error": str(e),
                "elapsed_s": round(elapsed, 2),
                "delegated": True,
            }


# ── Singleton ──
delegator = Delegator()
