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
        "代码", "代碼", "code", "coding", "程序", "程式",
        "function", "函数", "函數", "class", "算法", "演算法",
        "script", "脚本", "腳本", "api", "sdk",
        "implement", "實作", "实现", "寫程式", "写代码", "寫代碼",
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
        "研究", "调研", "調研", "research", "什么是", "什麼是",
        "深入了解", "想了解",
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
        "部署", "deploy", "ci/cd", "docker",
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
        "规划", "規劃", "planning", "路线图", "路線圖",
        "roadmap", "sprint", "迭代", "排期", "任務規劃", "任务规划",
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
        "marketing", "blog", "寫文案", "写文案",
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

# ── Casual chat bypass ─────────────────────────────────────────────────────
# Short greetings, acknowledgments, and small-talk bypass delegation entirely.
_CASUAL_PATTERNS: list[str] = [
    # Greetings
    r"^(你好|嗨|hi|hello|hey|哈囉|哈喽|嘿|早安|午安|晚安|早上好|下午好|晚上好|good\s*(morning|afternoon|evening))[\s!！。.？?，,~～]*$",
    # Thanks
    r"^(謝謝|谢谢|感謝|感谢|thanks?|thank\s*you|thx|3q|tks|多謝|多谢)[\s!！。.？?，,~～]*$",
    # Bye
    r"^(bye|再見|再见|掰掰|拜拜|88|886|see\s*you|晚安|good\s*night)[\s!！。.？?，,~～]*$",
    # Acknowledgments
    r"^(ok|okay|好的|好|是|對|对|嗯|了解|知道了|收到|okok|明白|好吧|行|可以|沒問題|没问题)[\s!！。.？?，,~～]*$",
    # Identity questions
    r"^(你是誰|你是谁|who\s*are\s*you|你叫什[麼么]|what.*your\s*name)[\s!！。.？?，,~～]*$",
    # Simple affirmations/negations
    r"^(是的|不是|不要|不用|不了|算了|沒事|没事|無所謂|随便|隨便)[\s!！。.？?，,~～]*$",
]
_CASUAL_MAX_LEN = 12  # Commands ≤ this length with no domain keywords → casual


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
    # ── Federation fields ──
    remote: bool = False           # 是否為遠端 agent
    peer_url: str = ""             # 遠端 peer URL
    peer_instance_id: str = ""     # 遠端實例 ID


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

    @staticmethod
    def _is_casual_chat(command: str) -> bool:
        """Detect casual chat / greetings that should NOT trigger delegation."""
        cmd = command.strip()
        cmd_lower = cmd.lower()
        # Pattern match — common greetings, thanks, bye, etc.
        for pattern in _CASUAL_PATTERNS:
            if re.match(pattern, cmd_lower):
                return True
        # Short command heuristic: if very short and no domain keywords, treat as casual
        if len(cmd) <= _CASUAL_MAX_LEN:
            for keywords in _CAPABILITY_KEYWORDS.values():
                if any(kw in cmd_lower for kw in keywords if len(kw) >= 3):
                    return False  # Has a meaningful domain keyword → not casual
            return True  # Short + no domain keywords → casual
        return False

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

    def _score_capabilities(self, command: str) -> list[tuple[str, float]]:
        """
        Score all capabilities against the command.
        P1-5: 優先使用語義匹配（Capability Selector），關鍵字作為 fallback。
        Returns sorted (cap, confidence) pairs, confidence already normalized to 0-1.
        """
        # ── 語義路由（P1-5）──
        # min_score 0.50: 過濾掉低相關性的「噪音匹配」（簡單問候、閒聊等）
        try:
            from runtime.capability_selector import capability_selector
            results = capability_selector.select_agents(command, top_k=5, min_score=0.50)
            if results:
                scores = []
                seen_caps = set()
                for r in results:
                    cap = r.entry.metadata.get("capability", "general")
                    if cap not in seen_caps:
                        # Cosine similarity 已經是 0-1 範圍，直接作為 confidence
                        scores.append((cap, r.score))
                        seen_caps.add(cap)
                if scores:
                    logger.info("[Delegator] Semantic routing: %s",
                                ", ".join(f"{c}={s:.3f}" for c, s in scores[:3]))
                    return scores
        except Exception as e:
            logger.debug("[Delegator] Semantic routing failed, using keyword fallback: %s", e)

        # ── 關鍵字 Fallback ──
        cmd_lower = command.lower()
        scores = []
        for capability, keywords in _CAPABILITY_KEYWORDS.items():
            count = sum(1 for kw in keywords if kw in cmd_lower)
            if count > 0:
                # Normalize: 1 match=0.33, 2 matches=0.67, 3+=1.0
                confidence = min(count / 3.0, 1.0)
                scores.append((capability, confidence))
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
        """
        Detect if command needs multiple agents (e.g., 'research then code').
        P1-5: 語義信號 + 關鍵字信號混合判斷。
        """
        cmd_lower = command.lower()
        # 關鍵字信號
        for pattern in _MULTI_AGENT_SIGNALS:
            if re.search(pattern, cmd_lower):
                return True

        # 語義信號：檢查是否有多個不同類型的高分 Agent 匹配
        # 閾值 0.50 防止簡單對話誤觸多 Agent
        try:
            from runtime.capability_selector import capability_selector
            results = capability_selector.select_agents(command, top_k=3, min_score=0.50)
            if len(results) >= 2:
                # 確認是不同 agent
                agent_ids = set(r.entry.metadata.get("agent_id") for r in results)
                if len(agent_ids) >= 2:
                    logger.debug("[Delegator] Semantic multi-agent signal: %s",
                                 ", ".join(agent_ids))
                    return True
        except Exception:
            pass

        return False

    # ── Single-agent routing ─────────────────────────────────────────────────

    def route(self, command: str) -> Optional[DelegationMatch]:
        """
        Route a command to a single sub-agent.
        Returns DelegationMatch if delegation is appropriate, None if CEO handles it.
        """
        if self._is_onboarding():
            return None

        # ── 閒聊 bypass：短問候/確認/小聊不委派 ──
        if self._is_casual_chat(command):
            logger.debug("[Delegator] Casual chat detected, CEO handles: '%s'", command[:30])
            return None

        scores = self._score_capabilities(command)
        if not scores:
            return None

        best_cap, best_score = scores[0]
        match = self._find_best_agent(best_cap)
        if not match:
            # No agent for this capability — return None so CEO handles it directly
            logger.info("[Delegator] No agent for '%s', falling back to CEO", best_cap)
            return None

        # Confidence 已由 _score_capabilities 正規化到 0-1：
        # - 語義路由: cosine similarity（直接使用）
        # - 關鍵字路由: min(match_count / 3.0, 1.0)
        match.confidence = best_score

        # 低信心度的匹配不委派 — 讓 CEO 直接處理
        # 語義: cosine_sim < 0.50 不委派（nomic-embed-text 的合理閾值）
        # 關鍵字: 需要 2+ 個關鍵字匹配（2/3=0.67 > 0.50）
        if match.confidence < 0.50:
            logger.info("[Delegator] Low confidence %.3f for cap='%s', CEO handles directly",
                        match.confidence, best_cap)
            return None

        logger.info("[Delegator] MATCH: '%s' → agent=%s cap=%s conf=%.3f",
                    command[:40], match.agent_id, best_cap, match.confidence)
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

        # 閒聊 bypass
        if self._is_casual_chat(command):
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
            if not match:
                # No agent for this capability — skip it, CEO will handle if needed
                logger.debug("[Delegator] Skipping cap '%s' (no agent available)", cap)
                continue

            if match and match.agent_id not in seen_agents:
                match.confidence = score  # Already normalized 0-1
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

        # Safety: verify agent actually exists in registry before executing
        agent_check = agent_registry.get(match.agent_id)
        if not agent_check:
            logger.warning("[Delegator] Agent '%s' not in registry, skipping delegation", match.agent_id)
            return {
                "success": False,
                "output": "",
                "agent_id": match.agent_id,
                "error": f"Agent '{match.agent_id}' not found",
                "elapsed_s": 0,
                "delegated": False,
            }

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

            # ── Tool Filter: 限制子 Agent 只能使用其 allowed_tools ──
            # 同時移除委派工具（delegate_task, delegate_pipeline）防止遞歸委派
            _delegation_tools = {"delegate_task", "delegate_pipeline", "delegate_multi"}
            tool_filter = None
            agent_info = agent_registry.get(match.agent_id)
            if agent_info and agent_info.allowed_tools:
                if "__all__" not in agent_info.allowed_tools:
                    tool_filter = [t for t in agent_info.allowed_tools
                                   if t not in _delegation_tools]
                else:
                    # __all__ but still exclude delegation tools to prevent loops
                    tool_filter = None  # 使用全部工具，但下面單獨排除
            # 即使是 __all__，也排除委派工具（子 Agent 不應再委派）
            if tool_filter is None and match.agent_id != "main":
                # 不傳 tool_filter → agentic_complete 用全部工具
                # 但我們明確排除委派工具
                from runtime.tool_loop import tool_registry as _tr
                all_tool_names = [s["name"] for s in _tr.get_schemas()]
                tool_filter = [t for t in all_tool_names if t not in _delegation_tools]

            result = agentic_complete(
                prompt=full_command,
                system=full_system,
                model=match.model,
                task_type=match.capability,
                tool_filter=tool_filter,
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
        pipeline_id: str | None = None,
    ) -> dict:
        """
        Execute a multi-agent DelegationPlan sequentially.
        Each step receives the prior step's output as context.
        Emits events for observability and persists state to SharedMemory.
        """
        if not plan.steps:
            return {"success": False, "error": "Empty delegation plan"}

        # Generate pipeline ID for tracking
        if not pipeline_id:
            import uuid
            pipeline_id = f"pipe-{uuid.uuid4().hex[:8]}"

        # Initialize SharedMemory for pipeline state persistence
        shared_mem = None
        try:
            from runtime.iamp import shared_memory_manager
            shared_mem = shared_memory_manager.get(pipeline_id)
            shared_mem.write("pipeline", "plan", {
                "description": plan.description,
                "total_steps": len(plan.steps),
                "command": command[:500],
                "agents": [s.agent_id for s in plan.steps],
            })
        except Exception:
            pass

        results = []
        prior_output = None

        for i, step in enumerate(plan.steps):
            logger.info("[Delegator] Plan step %d/%d: %s (%s)",
                        i + 1, len(plan.steps), step.agent_name, step.capability)

            # Emit pipeline step start event
            self._emit_pipeline_event("step_start", pipeline_id, {
                "step_index": i,
                "agent_id": step.agent_id,
                "capability": step.capability,
                "total_steps": len(plan.steps),
            })

            result = self.execute(
                match=step,
                command=command,
                system=system,
                prior_context=prior_output,
            )
            results.append(result)

            # Persist step result to SharedMemory
            if shared_mem:
                try:
                    shared_mem.write(step.agent_id, f"step_{i}_result", {
                        "success": result.get("success"),
                        "output": str(result.get("output", ""))[:1000],
                        "elapsed_s": result.get("elapsed_s", 0),
                    })
                except Exception:
                    pass

            if result.get("success"):
                prior_output = result.get("output", "")
                self._emit_pipeline_event("step_complete", pipeline_id, {
                    "step_index": i,
                    "agent_id": step.agent_id,
                    "elapsed_s": result.get("elapsed_s", 0),
                })
            else:
                logger.warning("[Delegator] Plan step %d failed, stopping", i + 1)
                self._emit_pipeline_event("step_failed", pipeline_id, {
                    "step_index": i,
                    "agent_id": step.agent_id,
                    "error": result.get("error", "unknown"),
                })
                break

        # Aggregate
        total_tokens = sum(r.get("tokens", 0) for r in results)
        total_elapsed = sum(r.get("elapsed_s", 0) for r in results)
        final_output = results[-1].get("output", "") if results else ""
        all_success = all(r.get("success") for r in results)

        # Emit pipeline completion event
        self._emit_pipeline_event(
            "pipeline_complete" if all_success else "pipeline_failed",
            pipeline_id, {
                "steps_completed": len(results),
                "total_steps": len(plan.steps),
                "total_tokens": total_tokens,
                "total_elapsed_s": round(total_elapsed, 2),
            })

        # Cleanup SharedMemory on completion
        if shared_mem:
            try:
                from runtime.iamp import shared_memory_manager
                shared_memory_manager.cleanup(pipeline_id)
            except Exception:
                pass

        return {
            "success": all_success,
            "output": final_output,
            "plan": plan.description,
            "pipeline_id": pipeline_id,
            "steps": len(results),
            "total_tokens": total_tokens,
            "total_elapsed_s": round(total_elapsed, 2),
            "delegated": True,
            "step_results": results,
        }

    # ── Federation routing ───────────────────────────────────────────────────

    async def route_federated(self, command: str) -> Optional[DelegationMatch]:
        """
        擴展路由：先本地 → 未命中再查遠端 peer capabilities。
        Returns DelegationMatch (可能 remote=True) or None.
        """
        # 1. 先嘗試本地路由
        local_match = self.route(command)
        if local_match:
            return local_match

        # 2. Federation 未啟用 → fallback CEO
        try:
            from config.settings import settings
            if not settings.federation_enabled:
                return None
        except Exception:
            return None

        # 3. 查詢遠端 peer capabilities
        try:
            from runtime.federation import federation_bridge
            cmd_lower = command.lower()

            for peer in federation_bridge._peers.values():
                if not peer.is_healthy() or not peer.capabilities:
                    continue

                # 嘗試匹配 peer 的 capabilities
                for cap in peer.capabilities:
                    cap_lower = cap.lower()
                    # 檢查 capability 關鍵字是否出現在 command 中
                    if cap_lower in _CAPABILITY_KEYWORDS:
                        keywords = _CAPABILITY_KEYWORDS[cap_lower]
                        count = sum(1 for kw in keywords if kw in cmd_lower)
                        if count > 0:
                            confidence = min(count / 3.0, 1.0)
                            match = DelegationMatch(
                                agent_id=f"peer:{peer.instance_id}:{cap}",
                                agent_name=f"[{peer.instance_id}] {cap}",
                                model="remote",
                                system_prompt="",
                                capability=cap,
                                confidence=confidence,
                                remote=True,
                                peer_url=peer.url,
                                peer_instance_id=peer.instance_id,
                            )
                            if match.confidence >= 0.50:
                                logger.info("[Delegator] FEDERATED MATCH: '%s' → peer=%s cap=%s conf=%.2f",
                                            command[:40], peer.instance_id, cap, match.confidence)
                                return match

                    # 也檢查 skill: 前綴的 capabilities
                    if cap.startswith("skill:"):
                        skill_name = cap[6:]  # 去掉 "skill:" 前綴
                        if skill_name.lower() in cmd_lower:
                            match = DelegationMatch(
                                agent_id=f"peer:{peer.instance_id}:{skill_name}",
                                agent_name=f"[{peer.instance_id}] {skill_name}",
                                model="remote",
                                system_prompt="",
                                capability=skill_name,
                                confidence=0.75,
                                remote=True,
                                peer_url=peer.url,
                                peer_instance_id=peer.instance_id,
                            )
                            logger.info("[Delegator] FEDERATED SKILL MATCH: '%s' → peer=%s skill=%s",
                                        command[:40], peer.instance_id, skill_name)
                            return match

        except Exception as e:
            logger.debug("[Delegator] Federation routing error: %s", e)

        return None

    async def execute_remote(
        self,
        match: DelegationMatch,
        command: str,
        session_id: str = "",
        channel: str = "",
    ) -> dict:
        """
        透過 FederationBridge 發送任務到遠端 peer。
        結果通過 callback → EventBus → delivery_queue 異步回傳。

        Returns: {accepted, task_id, peer_url, error}
        """
        if not match.remote or not match.peer_url:
            return {"accepted": False, "error": "Not a remote match"}

        try:
            from runtime.federation import federation_bridge
            result = await federation_bridge.send_task(
                peer_url=match.peer_url,
                task={
                    "command": command,
                    "agent_hint": match.capability,
                    "context": {
                        "capability": match.capability,
                        "confidence": match.confidence,
                    },
                },
                session_id=session_id,
                channel=channel,
            )
            return result
        except Exception as e:
            logger.error("[Delegator] execute_remote failed: %s", e)
            return {"accepted": False, "error": str(e)}

    @staticmethod
    def _emit_pipeline_event(action: str, pipeline_id: str, detail: dict) -> None:
        """Fire-and-forget pipeline observability event."""
        try:
            from runtime.event_bus import event_bus, Event, EventType, EventPriority
            event_bus.emit(Event(
                type=EventType.SYSTEM_EVENT,
                source=f"pipeline:{pipeline_id}",
                payload={"action": action, "detail": str(detail), **detail},
                priority=EventPriority.LOW,
            ))
        except Exception:
            pass


# ── Singleton ──
delegator = Delegator()
