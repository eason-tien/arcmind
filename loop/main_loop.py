"""
ArcMind 主循環 — OODA Loop
Observe → Orient → Decide → Act → [學習]

每個請求都走完整的五個階段：
1. Observe:  收集輸入（使用者指令 / Cron / MGIS Proactive）
2. Orient:   查詢 MGIS 記憶 + 分析目標狀態 + 注入 Persona
3. Decide:   模型路由 + Planner 生成步驟 + Governor 審計
4. Act:      Skill 執行
5. Learn:    Feedback 寫回 MGIS

v0.3.0: 整合 Gateway Session 管理和 Persona Injector。
"""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from foundation.mgis_client import mgis
from runtime.model_router import model_router
from runtime.skill_manager import skill_manager
from runtime.lifecycle import lifecycle
from loop.goal_tracker import goal_tracker
from loop.feedback import feedback

logger = logging.getLogger("arcmind.main_loop")


def _strip_think_tags(text: str) -> str:
    """Strip <think>...</think> chain-of-thought tags from model output."""
    if not text:
        return text
    return re.sub(r"<think>[\s\S]*?</think>\s*", "", text).strip()

# ── 資料結構 ──────────────────────────────────────────────────────────────────

@dataclass
class LoopInput:
    """一次 OODA 執行的輸入"""
    command: str                          # 使用者指令 / 任務描述
    source: str = "user"                  # user | cron | proactive
    session_id: int | None = None
    goal_id: int | None = None
    context: dict = field(default_factory=dict)
    skill_hint: str | None = None         # 提示使用哪個 Skill
    model_hint: str | None = None         # 模型覆蓋 (from /model command)
    task_type: str = "general"
    budget: str = "medium"


@dataclass
class LoopResult:
    """一次 OODA 執行的完整結果"""
    success: bool
    task_id: int | None
    skill_used: str | None
    model_used: str | None
    output: Any
    tokens_used: int
    elapsed_s: float
    governor_approved: bool
    error: str | None = None
    plan_steps: list[dict] = field(default_factory=list)
    memory_hits: list[dict] = field(default_factory=list)
    harness_run_id: str | None = None


# ── MainLoop ──────────────────────────────────────────────────────────────────

class MainLoop:
    """
    ArcMind OODA 主循環。
    每次 run() 執行完整的五個階段。
    """

    def run(self, inp: LoopInput) -> LoopResult:
        start = time.monotonic()
        task_id = None
        skill_used = None
        model_used = None
        governor_approved = False
        memory_hits = []
        plan_steps = []
        tokens_used = 0

        try:
            # ── 1. OBSERVE ───────────────────────────────────────────────────
            logger.info("[OBSERVE] command='%s' source=%s", inp.command[:80], inp.source)

            # 隱式偏好萃取（火即忘，不阻塞）
            try:
                from memory.preference_manager import extract_and_update_preference
                extract_and_update_preference(inp.command)
            except Exception:
                pass

            # 環境拓撲注入（三維度認知）
            env_summary = ""
            try:
                from memory.env_topology import get_topology_summary
                env_summary = get_topology_summary()
                if env_summary:
                    inp.context["env_topology"] = env_summary
            except Exception:
                pass

            # 建立 Task 記錄
            task_id = lifecycle.tasks.create(
                title=inp.command[:200],
                task_type=inp.task_type,
                session_id=inp.session_id,
                input_data={"command": inp.command, "context": inp.context},
            )

            # ── 2. ORIENT ────────────────────────────────────────────────────
            logger.info("[ORIENT] Querying local 4-layer memory...")
            try:
                from memory.memory_store import memory_store as _mem
                # Topic-based retrieval (semantic/procedural/causal)
                memory_hits = _mem.query(
                    query=inp.command,
                    top_k=5,
                )
                # Recent conversation history (episodic) — so agent remembers past turns
                recent_conv = _mem.get_recent(limit=10, memory_type="episodic")
                # Merge: recent conversation first, then topic hits (dedup by id)
                seen_ids = set()
                merged = []
                for item in recent_conv:
                    if item["id"] not in seen_ids:
                        merged.append(item)
                        seen_ids.add(item["id"])
                for item in memory_hits:
                    if item["id"] not in seen_ids:
                        merged.append(item)
                        seen_ids.add(item["id"])
                memory_hits = merged
                if memory_hits:
                    logger.info("[ORIENT] Memory: %d items (%d conv + %d topic)",
                                len(memory_hits), len(recent_conv), len(memory_hits) - len(recent_conv))
            except Exception as e:
                logger.warning("[ORIENT] Memory query failed (degraded): %s", e)
                memory_hits = []

            # 若有活躍目標，帶入 context
            try:
                active_goals = goal_tracker.list_active()
                goal_context = [
                    {"id": g["id"], "title": g["title"], "progress": g["progress"]}
                    for g in active_goals[:3]
                ]
            except Exception:
                goal_context = []

            # ── 3. DECIDE ────────────────────────────────────────────────────
            logger.info("[DECIDE] Planning and routing...")

            # 確定使用哪個 Skill
            skill_name = inp.skill_hint
            if not skill_name:
                skill_name = self._pick_skill(inp.command, inp.task_type)

            # 選擇模型
            if inp.model_hint:
                # Per-session override from /model command
                model_used = inp.model_hint
                if model_used.endswith(":auto"):
                    # "ollama:auto" → use provider's default
                    prov = model_used.split(":")[0]
                    model_used, _ = model_router.select_model(inp.task_type, inp.budget)
                    if prov != model_used.split(":")[0]:
                        # Force to requested provider
                        from config.settings import settings
                        defaults = {
                            "ollama": f"ollama:{settings.ollama_default_model}",
                            "custom": f"custom:{settings.custom_model_name}",
                        }
                        model_used = defaults.get(prov, f"{prov}:default")
                logger.info("[DECIDE] Model override: %s", model_used)
            else:
                chosen_model, _ = model_router.select_model(inp.task_type, inp.budget)
                model_used = chosen_model

            # 輸出模式提示注入
            output_mode = inp.context.get("output_mode", "")
            if output_mode and output_mode != "default":
                mode_hints = {
                    "concise": "\n[系統提示] 用戶偏好簡潔回答，請用要點式、精簡的方式回覆。",
                    "detailed": "\n[系統提示] 用戶偏好詳細回答，請完整解釋每個步驟和原因。",
                    "code": "\n[系統提示] 用戶偏好程式碼優先，盡量直接給出可用的程式碼，減少文字解釋。",
                }
                hint = mode_hints.get(output_mode, "")
                if hint:
                    inp.command = inp.command + hint

            # Governor 審計（本地 Governor）
            try:
                from governor.governor import governor as _gov
                from governor.circuit_breaker import circuit_breaker as _cb
                # Circuit breaker: 檢查任務是否被凍結
                if _cb.is_frozen(task_id):
                    lifecycle.tasks.fail(task_id, "Circuit breaker: task frozen")
                    return LoopResult(
                        success=False, task_id=task_id,
                        skill_used=skill_name, model_used=model_used,
                        output=None, tokens_used=0,
                        elapsed_s=round(time.monotonic() - start, 3),
                        governor_approved=False,
                        error="Circuit breaker: task frozen (cooldown)",
                    )
                # Governor 風險評估
                gov_result = _gov.evaluate(
                    action=f"execute_skill:{skill_name}",
                    context={
                        "command": inp.command[:300],
                        "skill": skill_name,
                        "source": inp.source,
                        "session_id": inp.session_id,
                    },
                )
                audit = {"approved": gov_result.decision != "BLOCKED",
                         "reason": gov_result.reason,
                         "risk_score": gov_result.risk_score}
            except Exception as e:
                logger.warning("[DECIDE] Governor failed (auto-approved): %s", e)
                audit = {"approved": True}

            if not audit.get("approved", True):
                reason = audit.get("reason", "Governor blocked")
                feedback.on_governor_blocked(
                    action=f"execute_skill:{skill_name}",
                    reason=reason,
                )
                lifecycle.tasks.fail(task_id, f"Governor blocked: {reason}")
                return LoopResult(
                    success=False,
                    task_id=task_id,
                    skill_used=skill_name,
                    model_used=model_used,
                    output=None,
                    tokens_used=0,
                    elapsed_s=round(time.monotonic() - start, 3),
                    governor_approved=False,
                    error=f"Governor blocked: {reason}",
                )


            governor_approved = True
            lifecycle.tasks.assign(task_id, skill_name, governor_ok=True, model=model_used)

            # ── 4. ACT ───────────────────────────────────────────────────────
            logger.info("[ACT] Invoking skill=%s", skill_name)
            lifecycle.tasks.start_executing(task_id)

            if skill_manager.is_registered(skill_name):
                # 本地 Skill
                skill_result = skill_manager.invoke(skill_name, {
                    **inp.context,
                    "command": inp.command,
                })
            else:
                # 嘗試 OpenClaw（若啟用）
                from protocol.openclaw_adapter import openclaw
                if openclaw.enabled:
                    skill_result = openclaw.invoke_skill(skill_name, {
                        **inp.context, "command": inp.command,
                    })
                else:
                    # Fallback: 直接用模型回應
                    skill_result = self._model_fallback(inp, memory_hits, model_override=model_used)
                    skill_name = "_model_direct"

            skill_used = skill_name
            lifecycle.tasks.start_verifying(task_id)

            # ── 5. LEARN ─────────────────────────────────────────────────────
            output = skill_result.get("output")
            error = skill_result.get("error")
            tokens_used = skill_result.get("tokens", 0)

            if skill_result.get("success", True) and not error:
                output_summary = (
                    str(output)[:200] if output else ""
                )
                try:
                    lifecycle.tasks.close(task_id, {"output": output}, tokens_used)
                except Exception as e:
                    logger.warning("[LEARN] lifecycle.close failed: %s", e)
                try:
                    feedback.on_task_success(
                        task_id, inp.command[:100], skill_name,
                        output_summary, tokens_used,
                    )
                except Exception as e:
                    logger.warning("[LEARN] feedback.on_task_success failed: %s", e)

                # ── Write to 4-layer memory (ChromaDB) ──
                try:
                    from memory.memory_store import memory_store as _mem

                    # Dynamic importance based on complexity
                    base_importance = min(0.3 + (tokens_used / 50000), 0.8)

                    # Episodic: 記錄對話
                    _mem.add_episodic(
                        content=f"用戶：{inp.command[:300]}\n回覆：{output_summary}",
                        source=inp.source or "api",
                        session_id=inp.session_id,
                        importance=base_importance,
                    )

                    # Procedural: 記錄技能使用模式
                    if skill_name and skill_name != "_model_direct":
                        _mem.add_procedural(
                            content=f"指令 '{inp.command[:100]}' → 使用 {skill_name}",
                            skill_used=skill_name,
                            importance=0.5,
                        )

                    # Semantic: 自動提取有價值的知識
                    if output and len(str(output)) > 200 and tokens_used > 2000:
                        _mem.add_semantic(
                            content=f"任務: {inp.command[:150]}\n結果摘要: {output_summary}",
                            source="auto_extract",
                            importance=min(base_importance + 0.1, 0.9),
                        )

                except Exception as _mem_err:
                    logger.debug("[LEARN] Memory write failed (non-fatal): %s", _mem_err)

                # 更新目標進度（若有關聯目標）
                if inp.goal_id:
                    try:
                        goal = goal_tracker.get(inp.goal_id)
                        if goal and goal["status"] == "active":
                            new_progress = min(goal["progress"] + 0.1, 0.99)
                            goal_tracker.update_progress(inp.goal_id, new_progress)
                    except Exception:
                        pass
            else:
                try:
                    lifecycle.tasks.fail(task_id, error or "Unknown error")
                    feedback.on_task_failure(
                        task_id, inp.command[:100], skill_name, error or "Unknown"
                    )
                except Exception as e:
                    logger.warning("[LEARN] feedback.on_task_failure failed: %s", e)

                # ── Causal memory: 記錄失敗原因 ──
                try:
                    from memory.memory_store import memory_store as _mem
                    _mem.add_causal(
                        cause=f"指令 '{inp.command[:100]}' 使用 {skill_name or 'unknown'}",
                        effect=f"失敗: {str(error)[:200]}",
                        confidence=0.7,
                    )
                except Exception:
                    pass

            elapsed = round(time.monotonic() - start, 3)
            return LoopResult(
                success=not bool(error),
                task_id=task_id,
                skill_used=skill_used,
                model_used=model_used,
                output=output,
                tokens_used=tokens_used,
                elapsed_s=elapsed,
                governor_approved=governor_approved,
                error=error,
                memory_hits=memory_hits,
            )

        except Exception as e:
            logger.exception("MainLoop unhandled exception: %s", e)
            if task_id:
                lifecycle.tasks.fail(task_id, str(e))
            elapsed = round(time.monotonic() - start, 3)
            return LoopResult(
                success=False,
                task_id=task_id,
                skill_used=skill_used,
                model_used=model_used,
                output=None,
                tokens_used=0,
                elapsed_s=elapsed,
                governor_approved=governor_approved,
                error=str(e),
            )

    # ── 內部輔助 ──────────────────────────────────────────────────────────────

    def _pick_skill(self, command: str, task_type: str) -> str:
        """
        選擇執行方式。

        NOTE: 之前的 keyword-based skill routing 已停用。
        原因：skills (web_search.py, code_exec.py) 期待結構化參數如
        {"query": "..."} 或 {"code": "..."}，但 keyword matcher 只傳入
        raw command text，導致 "query is required" / "code is required" 錯誤。

        現在統一用 _model_direct → _model_fallback → Agentic Tool Loop，
        讓 LLM 自己決定呼叫哪些工具並正確傳遞參數。
        這才是 OpenClaw 級別的執行力。
        """
        return "_model_direct"

    def _model_fallback(self, inp: LoopInput, memory_hits: list,
                         model_override: str | None = None) -> dict:
        """
        當沒有適合 Skill 時，使用 Agentic Tool Loop 回應。
        先檢查是否應該委派給子 Agent，否則 MAIN 自己處理。
        """
        # ── 委派檢查：MAIN → Sub-Agent ──
        try:
            from runtime.delegator import delegator

            match = delegator.route(inp.command)
            if match:
                logger.info("[MainLoop] 🔀 Delegating to %s (%s)",
                            match.agent_name, match.capability)
                result = delegator.execute(match, inp.command)
                return {
                    "success": result.get("success", False),
                    "output": result.get("output", ""),
                    "tokens": result.get("tokens", 0),
                    "tool_calls": result.get("tool_calls", []),
                    "delegated_to": match.agent_id,
                }
        except ImportError:
            pass
        except Exception as e:
            logger.warning("[MainLoop] Delegation failed, MAIN handling: %s", e)
        # 使用 PersonaInjector 構建分層 system prompt
        try:
            from persona.injector import persona_injector

            memory_ctx = ""
            if memory_hits:
                memory_ctx = "\n".join(
                    f"- {h.get('content', '')[:100]}" for h in memory_hits
                )

            context_summary = ""
            if memory_ctx:
                context_summary = f"## 相關記憶\n{memory_ctx}"
            # 環境認知注入
            env_topo = inp.context.get("env_topology", "")
            if env_topo:
                context_summary += f"\n\n{env_topo}"
            if inp.context:
                ctx_for_summary = {k: v for k, v in inp.context.items() if k != "env_topology"}
                if ctx_for_summary:
                    context_summary += f"\n\n## Session Context\n{json.dumps(ctx_for_summary, ensure_ascii=False)[:500]}"

            # ── 雙軌長時記憶注入 ──
            # 注入 1: 用戶偏好
            try:
                from memory.preference_manager import get_preferences_tag
                pref_tag = get_preferences_tag()
                if pref_tag:
                    context_summary += f"\n\n{pref_tag}"
            except Exception:
                pass

            # 注入 2: 歷史 SOP
            try:
                from memory.sop_manager import sop_manager as _sop
                sop_tag = _sop.search_similar_sop(inp.command, threshold=0.85)
                if sop_tag:
                    context_summary += f"\n\n{sop_tag}"
                    logger.info("[ORIENT] Injected History SOP")
            except Exception:
                pass

            system = persona_injector.build_system_prompt(
                context_summary=context_summary,
                agent_type=inp.context.get("agent_type", "main"),
            )
        except ImportError:
            system = (
                "你是 ArcMind，一個自主智能體。"
                "你可以使用工具來搜尋、執行命令、讀寫檔案。"
                "根據使用者指令，選擇最適合的工具來完成任務。"
            )

        # ── 使用 Agentic Tool Loop（OpenClaw 的核心執行力）──
        try:
            from runtime.tool_loop import agentic_complete

            # Build conversation messages from session history for continuity
            messages = []
            conv_history = inp.context.get("conversation_history", [])
            if conv_history:
                # Include prior turns (skip last user message — we'll add it fresh)
                for turn in conv_history[:-1]:
                    messages.append({
                        "role": turn["role"],
                        "content": turn["content"],
                    })
                # Add current prompt as the final user message
                messages.append({"role": "user", "content": inp.command})

            result = agentic_complete(
                prompt=inp.command,
                system=system,
                task_type=inp.task_type,
                budget=inp.budget,
                model=model_override,
                messages=messages if messages else None,
            )
            return {
                "success": True,
                "output": _strip_think_tags(result["content"]),
                "tokens": result.get("total_tokens", 0),
                "tool_calls": result.get("tool_calls", []),
            }
        except Exception as e:
            logger.warning("[MainLoop] Agentic loop failed, falling back to single-shot: %s", e)
            # Fallback to single-shot (no tools) if agentic loop fails
            resp = model_router.complete(
                prompt=inp.command,
                system=system,
                task_type=inp.task_type,
                budget=inp.budget,
                model=model_override,
            )
            return {
                "success": True,
                "output": _strip_think_tags(resp.content),
                "tokens": resp.total_tokens,
            }

    def run_from_gateway(
        self,
        command: str,
        session_context: dict | None = None,
        channel: str = "gateway",
    ) -> LoopResult:
        """
        Gateway 入口：接收來自 Gateway 的消息。
        自動整合 session context 和 persona。
        """
        context = session_context or {}
        inp = LoopInput(
            command=command,
            source=channel,
            session_id=context.get("session_db_id"),
            task_type=context.get("task_type", "general"),
            context=context,
        )
        return self.run(inp)


main_loop = MainLoop()
