# -*- coding: utf-8 -*-
"""
ArcMind — Delegator Engine v2
===============================
零人類公司 CEO 的任務委派決策引擎。

OODA DECIDE 階段呼叫 `delegator.route(command)`:
  1. 掃描所有 sub-agents 的 capabilities
  2. 多維度意圖匹配 (keyword scoring + capability overlap)
  3. 支援多 Agent 協作路由 (parallel / sequential)
  4. 匹配成功 → 返回 DelegationMatch(es)
  5. 無匹配 → CEO 自己處理

用法：
  from runtime.delegator import delegator

  match = delegator.route("幫我寫一個 Python 排序演算法")
  # match.agent_id == "code"

  # Multi-agent: research then code
  plan = delegator.route_multi("調研 React 框架然後寫一個範例")
  # plan.steps == [DelegationMatch(search), DelegationMatch(code)]
"""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import List, Optional

from runtime.agent_registry import agent_registry

logger = logging.getLogger("arcmind.delegator")


# ── Capability keyword mapping ──────────────────────────────────────────────

_CAPABILITY_KEYWORDS: dict[str, list[str]] = {
    # coding
    "coding": [
        "代码", "代碼", "码", "code", "coding", "程序", "程式",
        "function", "函数", "函數", "class", "算法", "演算法",
        "script", "脚本", "腳本", "api", "sdk", "寫", "写",
        "implement", "實作", "实现",
    ],
    "debugging": [
        "debug", "调试", "調試", "bug", "error", "错误", "錯誤",
        "fix", "修复", "修復", "traceback", "exception",
    ],
    "code_review": [
        "review", "审查", "審查", "优化", "優化", "refactor", "重构", "重構",
    ],
    # search
    "web_search": [
        "搜索", "搜尋", "search", "google", "查找", "查詢",
        "新闻", "新聞", "news", "最新", "latest",
    ],
    "research": [
        "研究", "调研", "調研", "research", "了解", "什么是", "什麼是",
    ],
    # analysis
    "analysis": [
        "分析", "analyze", "analysis", "统计", "統計", "数据", "數據",
        "data", "报告", "報告", "report",
    ],
    "summarize": [
        "摘要", "总结", "總結", "summarize", "summary", "概述",
    ],
    # testing / QA
    "testing": [
        "测试", "測試", "test", "testing", "unit test", "qa",
        "验证", "驗證", "verify", "regression", "回歸",
    ],
    # devops
    "deployment": [
        "部署", "deploy", "ci/cd", "pipeline", "docker",
        "kubernetes", "k8s", "发布", "發布", "release",
    ],
    "monitoring": [
        "监控", "監控", "monitor", "alert", "告警", "日志", "日誌", "log",
    ],
    # product
    "requirements": [
        "需求", "requirement", "spec", "规格", "規格", "prd",
        "用户故事", "用戶故事", "user story",
    ],
    "planning": [
        "规划", "規劃", "plan", "planning", "路线图", "路線圖",
        "roadmap", "sprint", "迭代", "排期",
    ],
    # windows
    "windows": [
        "windows", "powershell", "远程", "遠端", "remote",
        "151", "windows pc",
    ],
    # security (template: security)
    "security": [
        "安全", "security", "漏洞", "vulnerability", "渗透", "滲透",
        "penetration", "audit", "owasp", "xss", "sql injection", "cve",
    ],
    # data engineering (template: data_engineer)
    "etl": [
        "etl", "pipeline", "数据管线", "數據管線", "清洗", "transform",
    ],
    "database": [
        "数据库", "資料庫", "database", "sql", "postgres", "mysql",
        "migration", "schema", "索引", "index",
    ],
    # frontend (template: frontend)
    "frontend": [
        "前端", "frontend", "react", "vue", "css", "html", "ui",
        "组件", "組件", "component", "页面", "頁面", "page",
    ],
    # design (template: designer)
    "design": [
        "设计", "設計", "design", "ux", "原型", "prototype",
        "wireframe", "线框", "線框", "figma", "mockup",
    ],
    # copywriting (template: copywriter)
    "copywriting": [
        "文案", "copy", "copywriting", "seo", "行销", "行銷",
        "marketing", "内容", "內容", "content", "blog",
    ],
    # finance (template: financial)
    "finance": [
        "财务", "財務", "finance", "预算", "預算", "budget",
        "投资", "投資", "investment", "会计", "會計", "accounting",
    ],
    # translation (template: translator)
    "translation": [
        "翻译", "翻譯", "translate", "translation", "i18n",
        "本地化", "localization", "多语", "多語",
    ],
    # SRE (template: sre)
    "sre": [
        "sre", "可靠性", "reliability", "incident", "事件响应", "事件響應",
        "oncall", "slo", "sli", "error budget",
    ],
}

# Keywords that signal multi-agent collaboration
_MULTI_AGENT_SIGNALS: list[str] = [
    "然後", "然后", "接著", "接着", "之後", "之后",
    "then", "and then", "after that", "followed by",
    "先.*再", "先.*後", "first.*then",
]


@dataclass
class DelegationMatch:
    """Result of delegation matching."""
    agent_id: str
    agent_name: str
    model: str
    system_prompt: str
    capability: str
    confidence: float = 0.0
    hire_suggestion: Optional[str] = None  # template_id if agent needs hiring first


@dataclass
class DelegationPlan:
    """Multi-agent execution plan."""
    steps: List[DelegationMatch] = field(default_factory=list)
    mode: str = "sequential"  # "sequential" or "parallel"
    description: str = ""

    @property
    def is_multi(self) -> bool:
        return len(self.steps) > 1


class Delegator:
    """
    Zero-Human Company CEO delegation engine.
    Routes tasks to the best sub-agent(s) based on intent matching.
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

    def _score_capabilities(self, command: str) -> list[tuple[str, int]]:
        """Score all capabilities against the command. Returns sorted (cap, score) pairs."""
        cmd_lower = command.lower()
        scores = []
        for capability, keywords in _CAPABILITY_KEYWORDS.items():
            score = sum(1 for kw in keywords if kw in cmd_lower)
            if score > 0:
                scores.append((capability, score))
        scores.sort(key=lambda x: x[1], reverse=True)
        return scores

    def _find_best_agent(self, capability: str) -> Optional[DelegationMatch]:
        """Find the best enabled agent for a capability, excluding CEO."""
        candidates = agent_registry.find_by_capability(capability)
        candidates = [a for a in candidates if a.id != "main"]
        if not candidates:
            return None
        agent = candidates[0]
        return DelegationMatch(
            agent_id=agent.id,
            agent_name=agent.name,
            model=agent.default_model,
            system_prompt=agent.system_prompt,
            capability=capability,
        )

    def _is_multi_agent_request(self, command: str) -> bool:
        """Detect if command needs multiple agents (e.g., 'research then code')."""
        cmd_lower = command.lower()
        for pattern in _MULTI_AGENT_SIGNALS:
            if re.search(pattern, cmd_lower):
                return True
        return False

    # ── Single-agent routing ─────────────────────────────────────────────────

    def route(self, command: str) -> Optional[DelegationMatch]:
        """
        Route a command to a single sub-agent.
        Returns DelegationMatch if delegation is appropriate, None if CEO handles it.
        """
        if self._is_onboarding():
            return None

        scores = self._score_capabilities(command)
        if not scores:
            return None

        best_cap, best_score = scores[0]
        match = self._find_best_agent(best_cap)
        if not match:
            # No active agent — check if a template could handle this
            try:
                from runtime.agent_templates import template_manager
                suggestion = template_manager.suggest_hire(command)
                if suggestion:
                    logger.info("[Delegator] No active agent for '%s', suggest hiring: %s",
                                best_cap, suggestion.template_id)
                    # Return a match pointing to CEO but with hire_suggestion
                    return DelegationMatch(
                        agent_id="main",
                        agent_name="CEO (suggest hire)",
                        model="",
                        system_prompt="",
                        capability=best_cap,
                        confidence=min(best_score / 3.0, 1.0),
                        hire_suggestion=suggestion.template_id,
                    )
            except Exception:
                pass
            return None

        match.confidence = min(best_score / 3.0, 1.0)  # Normalize to 0-1

        logger.info("[Delegator] MATCH: '%s' → agent=%s cap=%s score=%d conf=%.2f",
                    command[:40], match.agent_id, best_cap, best_score, match.confidence)
        return match

    # ── Multi-agent routing ──────────────────────────────────────────────────

    def route_multi(self, command: str) -> Optional[DelegationPlan]:
        """
        Route a command that may need multiple agents.
        Returns a DelegationPlan with ordered steps.

        Example: "調研 React 框架然後寫一個範例"
          → Step 1: search agent (research)
          → Step 2: code agent (coding)
        """
        if self._is_onboarding():
            return None

        scores = self._score_capabilities(command)
        if not scores:
            return None

        is_multi = self._is_multi_agent_request(command)

        if not is_multi or len(scores) < 2:
            # Single agent — wrap in plan for uniform interface
            match = self.route(command)
            if not match:
                return None
            return DelegationPlan(steps=[match], description=f"單一 Agent: {match.agent_name}")

        # Multi-agent: pick top capabilities that map to different agents
        steps = []
        seen_agents = set()
        for cap, score in scores:
            match = self._find_best_agent(cap)
            if match and match.agent_id not in seen_agents:
                match.confidence = min(score / 3.0, 1.0)
                steps.append(match)
                seen_agents.add(match.agent_id)
            if len(steps) >= 3:  # Max 3 agents per plan
                break

        if not steps:
            return None

        plan = DelegationPlan(
            steps=steps,
            mode="sequential",
            description=" → ".join(f"{s.agent_name}({s.capability})" for s in steps),
        )

        logger.info("[Delegator] MULTI-AGENT plan: %s", plan.description)
        return plan

    # ── Execution ────────────────────────────────────────────────────────────

    def execute(
        self,
        match: DelegationMatch,
        command: str,
        system: str | None = None,
        prior_context: str | None = None,
    ) -> dict:
        """
        Execute command using the delegated sub-agent's model.
        prior_context: output from a previous step in a multi-agent plan.
        """
        t0 = time.time()

        agent_system = match.system_prompt or system or ""

        delegation_context = (
            f"\n\n## Delegation Context\n"
            f"你是 {match.agent_name}，被 CEO 委派處理此任務。\n"
            f"專業領域：{match.capability}\n"
            f"請專注在你的專業領域，高品質完成任務。"
        )
        full_system = agent_system + delegation_context

        # Inject prior step context if multi-agent
        full_command = command
        if prior_context:
            full_command = (
                f"## 前一步驟的結果\n{prior_context}\n\n"
                f"## 你的任務\n{command}"
            )

        try:
            from runtime.tool_loop import agentic_complete

            result = agentic_complete(
                prompt=full_command,
                system=full_system,
                model=match.model,
                task_type=match.capability,
            )

            elapsed = time.time() - t0
            logger.info("[Delegator] done: agent=%s elapsed=%.1fs",
                        match.agent_id, elapsed)

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

    def execute_plan(
        self,
        plan: DelegationPlan,
        command: str,
        system: str | None = None,
    ) -> dict:
        """
        Execute a multi-agent DelegationPlan sequentially.
        Each step receives the prior step's output as context.
        """
        if not plan.steps:
            return {"success": False, "error": "Empty delegation plan"}

        results = []
        prior_output = None

        for i, step in enumerate(plan.steps):
            logger.info("[Delegator] Plan step %d/%d: %s (%s)",
                        i + 1, len(plan.steps), step.agent_name, step.capability)

            result = self.execute(
                match=step,
                command=command,
                system=system,
                prior_context=prior_output,
            )
            results.append(result)

            if result.get("success"):
                prior_output = result.get("output", "")
            else:
                logger.warning("[Delegator] Plan step %d failed, stopping", i + 1)
                break

        # Aggregate
        total_tokens = sum(r.get("tokens", 0) for r in results)
        total_elapsed = sum(r.get("elapsed_s", 0) for r in results)
        final_output = results[-1].get("output", "") if results else ""
        all_success = all(r.get("success") for r in results)

        return {
            "success": all_success,
            "output": final_output,
            "plan": plan.description,
            "steps": len(results),
            "total_tokens": total_tokens,
            "total_elapsed_s": round(total_elapsed, 2),
            "delegated": True,
            "step_results": results,
        }


# ── Singleton ──
delegator = Delegator()
