"""
ArcMind 主循環 — OODA Loop (Event-Driven 混合驅動)
Observe → Orient → Decide → Act → [學習]

驅動模式：
  - 同步路徑: API/WebSocket → MainLoop.run()  (Request-Response)
  - 異步路徑: EventBus → Handler → MainLoop    (Event-Driven)

每個請求都走完整的五個階段：
1. Observe:  收集輸入 + 環境感知 + Agent 狀態監控
2. Orient:   查詢記憶 + 分析目標 + 注入 Persona + 委派歷史
3. Decide:   模型路由 + 多 Agent 協作規劃 + Governor 審計
4. Act:      Skill / Agent 委派 / Pipeline 執行
5. Learn:    Feedback + Agent 績效追蹤 + 因果記憶 + Event 發佈

v0.3.0: 整合 Gateway Session 管理和 Persona Injector。
v0.5.0: 整合多 Agent 協作、IAMP、Pipeline 執行。
v0.6.0: Event-Driven 混合驅動 — EventBus 統一事件源。
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
from memory.working_memory import working_memory

logger = logging.getLogger("arcmind.main_loop")


def _strip_think_tags(text: str) -> str:
    """Strip <think>...</think> and raw tool-call markup from model output."""
    if not text:
        return text
    # Strip <think>...</think>
    text = re.sub(r"<think>[\s\S]*?</think>\s*", "", text)
    # Strip JSON arrays that are sometimes prepended before tool calls: [{"type": "text", "text": ""}]
    text = re.sub(r"^\[\{.*?\}\]\s*", "", text)
    # Strip kimi-K2.5 raw tool call blocks (handles underscores: <|tool_call_begin|>, <|toolcallssectionbegin|>)
    text = re.sub(r"<\|tool_?calls?_?section_?begin\|>[\s\S]*?<\|tool_?calls?_?section_?end\|>\s*", "", text)
    # Strip remaining kimi tool tokens (handles <|toolcall|>, <|tool_call|>, <|tool_call_end|>)
    text = re.sub(r"<\|tool_?[a-z_]*\|>", "", text)
    # Strip function call patterns like functions.xxx:N
    text = re.sub(r"functions\.\w+:\d+\s*", "", text)
    return text.strip()

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

            # Agent 狀態感知 — CEO 掌握全公司員工動態
            try:
                from runtime.agent_registry import agent_registry
                from runtime.iamp import message_bus
                agent_status = {
                    "total_agents": len(agent_registry.list_enabled()),
                    "message_bus": message_bus.stats(),
                }
                inp.context["agent_status"] = agent_status
            except Exception:
                pass

            # 建立 Task 記錄
            task_id = lifecycle.tasks.create(
                title=inp.command[:200],
                task_type=inp.task_type,
                session_id=inp.session_id,
                input_data={"command": inp.command, "context": inp.context},
            )

            # ── Event: task_created ──
            self._emit_event("task_created", inp.source, {
                "task_id": task_id, "command": inp.command[:200],
                "task_type": inp.task_type,
            })

            # ── Working Memory: 讀取 session 的工作記憶（跨請求連續性）──
            wm_key = str(inp.session_id) if inp.session_id else str(task_id)
            wm_context = ""
            try:
                wm_context = working_memory.get_context(wm_key)
                if wm_context:
                    inp.context["working_memory"] = wm_context
                    logger.info("[OBSERVE] Working memory loaded (%d chars) for session=%s",
                                len(wm_context), wm_key[:16])
            except Exception as e:
                logger.debug("[OBSERVE] Working memory read failed: %s", e)

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
                recent_conv = _mem.get_recent(limit=20, memory_type="episodic")
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

            # 委派歷史感知 — 讓 CEO 了解近期 Agent 活動
            try:
                from runtime.iamp import message_bus, MessageType
                recent_completions = [
                    m for m in message_bus.get_inbox("main", limit=10)
                    if m.msg_type in (MessageType.TASK_COMPLETE, MessageType.TASK_ESCALATE)
                ]
                if recent_completions:
                    inp.context["recent_agent_activity"] = [
                        {
                            "from": m.sender,
                            "type": m.msg_type.value,
                            "task_id": m.task_id,
                            "summary": str(m.payload.get("output", m.payload.get("reason", "")))[:100],
                        }
                        for m in recent_completions[:5]
                    ]
            except Exception:
                pass

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
                    "voice": "\n[系統提示] 目前正處於「純語音通話模式」。請務必使用「完全口語化、像真人聊天一樣自然」的語氣回覆。絕對不要使用任何 Markdown（如粗體、清單星號）、不要使用表情符號 (Emoji)、不要列出項目符號。請把所有的縮寫跟數字都用口語順口的方式表達，句子要連貫自然。",
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
                logger.error("[DECIDE] Governor failed (fail-closed — action BLOCKED): %s", e)
                audit = {"approved": False, "reason": f"Governor error: {e}", "risk_score": 1.0}

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
                # 嘗試多 Agent 協作路由
                # 若已經是指定角色的子任務，跳過二次委派
                if inp.context.get('sub_agent_role'):
                    multi_agent_result = None
                else:
                    multi_agent_result = self._try_multi_agent(inp, task_id)
                if multi_agent_result:
                    skill_result = multi_agent_result
                    skill_name = "_multi_agent"
                else:
                    # 嘗試 OpenClaw（若啟用）
                    try:
                        from protocol.openclaw_adapter import openclaw
                        if openclaw.enabled:
                            skill_result = openclaw.invoke_skill(skill_name, {
                                **inp.context, "command": inp.command,
                            })
                        else:
                            skill_result = self._model_fallback(inp, memory_hits, model_override=model_used)
                            skill_name = "_model_direct"
                    except ImportError:
                        skill_result = self._model_fallback(inp, memory_hits, model_override=model_used)
                        skill_name = "_model_direct"

            skill_used = skill_name
            lifecycle.tasks.start_verifying(task_id)

            # ── Working Memory: 寫入本次執行結果 ──
            try:
                result_summary = str(skill_result.get("output", ""))[:300]
                tool_calls = skill_result.get("tool_calls", [])
                if tool_calls:
                    tool_names = [tc.get("tool", "?") for tc in tool_calls[:5]]
                    working_memory.add(wm_key, f"使用工具: {', '.join(tool_names)}", kind="action")
                if result_summary:
                    working_memory.add(wm_key, result_summary, kind="result")
            except Exception as e:
                logger.debug("[ACT] Working memory write failed: %s", e)

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

                # ── Working Memory: flush 結論到 semantic ──
                try:
                    from memory.memory_store import memory_store as _mem
                    working_memory.flush(wm_key, _mem, user_command=inp.command)
                except Exception as _wm_err:
                    logger.debug("[LEARN] Working memory flush failed: %s", _wm_err)

                # ── MGIS 閉環: 寫回記憶 + 因果日誌 ──
                try:
                    if mgis.is_online():
                        # 寫入 MGIS 長期記憶
                        mgis.memory_add(
                            content=f"任務: {inp.command[:150]}\n結果: {output_summary}",
                            tags=["arcmind", "task_success", skill_name or "direct"],
                            metadata={"task_id": task_id, "tokens": tokens_used,
                                      "session_id": inp.session_id},
                        )
                        # 因果日誌
                        mgis.causal_log(
                            cause=f"用戶指令: {inp.command[:100]}",
                            effect=f"成功完成 (skill={skill_name}, tokens={tokens_used})",
                            metadata={"task_id": task_id},
                        )
                except Exception:
                    pass  # MGIS 離線不影響主流程

                # ── SOP 自動儲存（P2-3 提前實施）──
                try:
                    from memory.sop_manager import sop_manager as _sop
                    if output and len(str(output)) > 100 and tokens_used > 500:
                        _sop.save_successful_sop(
                            task_prompt=inp.command[:500],
                            sop_content=str(output)[:2000],
                        )
                except Exception:
                    pass

                # ── Event: agent_complete ──
                self._emit_event("agent_complete", inp.source, {
                    "task_id": task_id, "skill_used": skill_name,
                    "tokens": tokens_used, "success": True,
                })

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

                # ── Event: task_failed ──
                self._emit_event("task_failed", inp.source, {
                    "task_id": task_id, "skill_used": skill_name,
                    "error": error or "Unknown",
                })

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

                # ── MGIS 閉環: 失敗因果日誌 ──
                try:
                    if mgis.is_online():
                        mgis.causal_log(
                            cause=f"用戶指令: {inp.command[:100]} (skill={skill_name})",
                            effect=f"失敗: {str(error)[:200]}",
                            metadata={"task_id": task_id, "severity": "error"},
                        )
                except Exception:
                    pass

            # ── Agent 績效追蹤 ──
            if skill_used in ("_multi_agent", "_model_direct") and skill_result:
                try:
                    delegated_to = skill_result.get("delegated_to") or skill_result.get("agent_id")
                    if delegated_to:
                        from runtime.iamp import message_bus, MessageType
                        message_bus.send(
                            sender="main",
                            receiver=delegated_to,
                            msg_type=MessageType.STATUS_REPORT,
                            payload={
                                "success": not bool(error),
                                "tokens": tokens_used,
                                "elapsed_s": round(time.monotonic() - start, 3),
                            },
                            task_id=str(task_id),
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

    # ── Event-Driven 輔助 ──────────────────────────────────────────────────────

    @staticmethod
    def _emit_event(event_type_str: str, source: str, payload: dict) -> None:
        """Fire-and-forget event emission to EventBus."""
        try:
            from runtime.event_bus import event_bus, Event, EventType
            type_map = {
                "task_created": EventType.TASK_CREATED,
                "task_failed": EventType.TASK_FAILED,
                "agent_complete": EventType.AGENT_COMPLETE,
                "system_event": EventType.SYSTEM_EVENT,
            }
            et = type_map.get(event_type_str)
            if et:
                event_bus.emit(Event(type=et, source=source, payload=payload))
        except Exception:
            pass  # EventBus is optional — never break the main loop

    # ── 內部輔助 ──────────────────────────────────────────────────────────────

    @staticmethod
    def _pick_skill(_command: str, _task_type: str) -> str:
        """統一走 _model_direct → Agentic Tool Loop，由 LLM 決定工具調用。"""
        return "_model_direct"

    def _try_multi_agent(self, inp: LoopInput, task_id: int) -> dict | None:
        """
        嘗試多 Agent 協作路由。
        如果指令涉及多個專業領域，建立 Pipeline 執行。
        返回 None 表示不適合多 Agent，交回單一路由。
        """
        try:
            from runtime.delegator import delegator

            plan = delegator.route_multi(inp.command)
            if not plan or not plan.is_multi:
                return None

            logger.info("[ACT] Multi-agent plan: %s", plan.description)

            result = delegator.execute_plan(plan, inp.command)

            # If multi-agent pipeline failed, return None so fallback chain continues
            if not result.get("success"):
                logger.warning("[ACT] Multi-agent plan failed, falling back to single: %s",
                               str(result.get("output", ""))[:100])
                return None

            return {
                "success": True,
                "output": result.get("output", ""),
                "tokens": result.get("total_tokens", 0),
                "tool_calls": [],
                "delegated_to": "pipeline",
                "agent_id": "pipeline",
                "plan": plan.description,
                "steps": result.get("steps", 0),
            }
        except Exception as e:
            logger.warning("[ACT] Multi-agent routing failed: %s", e)
            return None

    def _model_fallback(self, inp: LoopInput, memory_hits: list,
                         model_override: str | None = None) -> dict:
        """
        當沒有適合 Skill 時，使用 Agentic Tool Loop 回應。
        先檢查是否應該委派給子 Agent，否則 MAIN 自己處理。

        P1 重構: 使用 Context Builder + Capability Selector + Memory Selector 構建最小充分上下文。
        MGIS 閉環: 若 MGIS 在線，整合治理/記憶/規劃上下文。
        """
        # ── 委派檢查：MAIN → Sub-Agent（P1-5 語義路由）──
        # Depth guard: 防止無限遞歸委派（max depth=2）
        _DELEGATION_MAX_DEPTH = 2
        delegation_depth = inp.context.get("_delegation_depth", 0)

        if not inp.context.get("sub_agent_role") and delegation_depth < _DELEGATION_MAX_DEPTH:
            try:
                from runtime.delegator import delegator

                match = delegator.route(inp.command)
                if match:
                    logger.info("[MainLoop] 🔀 Delegating to %s (%s, conf=%.3f, depth=%d)",
                                match.agent_name, match.capability, match.confidence,
                                delegation_depth)
                    result = delegator.execute(match, inp.command)
                    # Only return delegation result if it actually succeeded
                    if result.get("success"):
                        return {
                            "success": True,
                            "output": result.get("output", ""),
                            "tokens": result.get("tokens", 0),
                            "tool_calls": result.get("tool_calls", []),
                            "delegated_to": match.agent_id,
                        }
                    else:
                        # ── 失敗重路由：嘗試次佳 Agent ──
                        logger.warning("[MainLoop] Delegation to %s failed (%s), trying re-route...",
                                       match.agent_id, result.get("error", "unknown"))
                        try:
                            scores = delegator._score_capabilities(inp.command)
                            tried = {match.agent_id}
                            for cap, score in scores:
                                alt_match = delegator._find_best_agent(cap)
                                if alt_match and alt_match.agent_id not in tried and score >= 0.50:
                                    alt_match.confidence = score
                                    logger.info("[MainLoop] 🔁 Re-routing to %s (%s, conf=%.3f)",
                                                alt_match.agent_name, alt_match.capability, alt_match.confidence)
                                    alt_result = delegator.execute(alt_match, inp.command)
                                    if alt_result.get("success"):
                                        return {
                                            "success": True,
                                            "output": alt_result.get("output", ""),
                                            "tokens": alt_result.get("tokens", 0),
                                            "tool_calls": alt_result.get("tool_calls", []),
                                            "delegated_to": alt_match.agent_id,
                                        }
                                    tried.add(alt_match.agent_id)
                        except Exception as re_err:
                            logger.debug("[MainLoop] Re-route failed: %s", re_err)
                        logger.warning("[MainLoop] All delegation attempts failed, CEO handling directly")
            except ImportError:
                pass
            except Exception as e:
                logger.warning("[MainLoop] Delegation failed, MAIN handling: %s", e)
        elif delegation_depth >= _DELEGATION_MAX_DEPTH:
            logger.warning("[MainLoop] Delegation depth limit reached (%d/%d), CEO handling directly",
                           delegation_depth, _DELEGATION_MAX_DEPTH)

        # ── P1-3: 使用 Context Builder 構建最小充分上下文 ──
        try:
            from runtime.context_builder import context_builder

            system = context_builder.build(
                intent=inp.command,
                session_id=inp.session_id,
                task_id=None,
                agent_type=inp.context.get("sub_agent_role") or inp.context.get("agent_type", "main"),
                conversation_history=inp.context.get("conversation_history"),
                extra_context=inp.context,
            )
        except Exception as e:
            logger.warning("[MainLoop] Context builder failed, using legacy: %s", e)
            # ── Legacy fallback: 原始 PersonaInjector ──
            try:
                from persona.injector import persona_injector

                memory_ctx = ""
                if memory_hits:
                    memory_ctx = "\n".join(
                        f"- {h.get('content', '')[:300]}" for h in memory_hits
                    )

                context_summary = ""
                if memory_ctx:
                    context_summary = f"## 相關記憶\n{memory_ctx}"
                wm_ctx = inp.context.get("working_memory", "")
                if wm_ctx:
                    context_summary += f"\n\n## 工作記憶（上下文連續性）\n{wm_ctx}"
                env_topo = inp.context.get("env_topology", "")
                if env_topo:
                    context_summary += f"\n\n{env_topo}"

                system = persona_injector.build_system_prompt(
                    context_summary=context_summary,
                    agent_type=inp.context.get("sub_agent_role") or inp.context.get("agent_type", "main"),
                )
            except ImportError:
                system = (
                    "你是 ArcMind，一個自主智能體。"
                    "你可以使用工具來搜尋、執行命令、讀寫檔案。"
                    "根據使用者指令，選擇最適合的工具來完成任務。"
                )

        # ── P1-4: 取得語義篩選的工具列表（複用 ContextBuilder 已觸發的 CapSelector 快取）──
        # 注意: ContextBuilder.build() 內部已呼叫 capability_selector.select_all()，
        # 此處再呼叫 select_tools() 時，意圖 embedding 會命中快取，不會重複 embed。
        tool_filter = None
        try:
            from runtime.capability_selector import capability_selector
            tool_filter = capability_selector.get_relevant_tool_names(inp.command, top_k=7)
            if tool_filter:
                logger.info("[MainLoop] Tool filter: %s", ", ".join(tool_filter[:5]))
        except Exception:
            pass  # 篩選失敗不影響功能，會使用全部工具

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

            # Determine if this task requires tangible outputs (code, files, execution)
            cmd_lower = inp.command.lower()
            needs_action = any(kw in cmd_lower for kw in [
                "build", "create", "write", "implement", "deploy", "run", "setup",
                "建立", "創建", "寫", "設計", "佈署", "部署", "執行", "跑"
            ])

            # ── Hallucination Prevention: Strict Role Enforcement ──
            strict_action_roles = {"qa", "code", "devops"}
            if inp.context.get("sub_agent_role") in strict_action_roles:
                needs_action = True

            result = agentic_complete(
                prompt=inp.command,
                system=system,
                task_type=inp.task_type,
                budget=inp.budget,
                model=model_override,
                messages=messages if messages else None,
                require_tool_usage=needs_action,
                tool_filter=tool_filter,
            )
            # The agentic_complete function returns a dict, extract its 'content'
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
