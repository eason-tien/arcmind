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


def _strip_dangerous_html(text: str) -> str:
    """Strip dangerous HTML tags from AI responses."""
    if not text:
        return text
    for tag in ['script', 'style', 'iframe', 'embed', 'object', 'applet']:
        text = re.sub(rf'<{tag}[^>]*>.*?</{tag}>', '', text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(rf'<{tag}[^>]*/\s*>', '', text, flags=re.IGNORECASE)
    for tag in ['link', 'meta']:
        text = re.sub(rf'<{tag}[^>]*/?>\s*', '', text, flags=re.IGNORECASE)
    text = re.sub(r'<action[^>]*>.*?</action>', '', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<tool_call>.*?</tool_call>', '', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'</?(?:action|tool_call|command|parameters|tool_name)[^>]*>', '', text, flags=re.IGNORECASE)
    return text


def _normalize_ml_content(content):
    """Normalize model response content to plain string."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        return content.get("text", content.get("content", "")) or ""
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict):
                t = block.get("text", block.get("content", ""))
                if t:
                    parts.append(str(t))
            elif isinstance(block, str):
                parts.append(block)
            elif hasattr(block, "text") and block.text:
                parts.append(str(block.text))
        return "\n".join(parts) if parts else ""
    if hasattr(content, "text"):
        return str(content.text) if content.text else ""
    return str(content)


def _llm_classify_intent(command: str, model: str = None) -> str:
    """Use LLM to classify user intent. Replaces keyword-based NLC.
    Returns: 'action', 'question', or 'chat'.
    """
    from runtime.model_router import model_router
    import logging
    _log = logging.getLogger("arcmind.main_loop")
    try:
        resp = model_router.complete(
            prompt=(
                "将以下用户请求分类为三种类型之一：\n"
                "- action: 用户想要执行操作，或需要通过系统命令获取信息（安装、创建、"
                "部署、配置、搭建、下载、上传、启动、停止、删除、修复、更新、扫描、测试、"
                "克隆、生成、制作等需要执行的任务；也包括：检查是否已安装、"
                "查看系统/服务/容器/文件/端口状态、确认某东西是否存在、"
                "列出目录内容等需要执行命令才能回答的请求）\n"
                "- question: 用户在询问概念性知识或请求分析解释，不需要执行系统命令就能回答"
                "（为什么、是什么、怎么回事、你觉得、解释一下、什么意思、什么原因等）\n"
                "- chat: 闲聊、问候、日常对话（你好、谢谢、再见等）\n\n"
                f"用户请求: {command}\n\n"
                "只回复一个词: action, question, 或 chat"
            ),
            system="你是意图分类器。只回复一个英文词: action, question, 或 chat。不要解释。",
            model=model,
            max_tokens=100,
            task_type="general",
            budget="low",
        )
        # Handle <think> tags from thinking models (MiniMax M2.5)
        raw = resp.content.strip()
        blob = raw.lower()

        # Try content after </think> first (ideal case)
        think_end = re.search(r'</think>\s*(.*)', blob, re.DOTALL)
        if think_end and think_end.group(1).strip():
            result = think_end.group(1).strip().rstrip(".")
        else:
            # Search entire response (handles unclosed <think>, no tags, etc.)
            result = blob.rstrip(".").strip()

        # Direct match
        if result in ("action", "question", "chat"):
            _log.info("[MainLoop] LLM intent: %s for command: %s", result, command[:50])
            return result
        # Fuzzy match
        for cat in ("action", "question", "chat"):
            if cat in result:
                _log.info("[MainLoop] LLM intent (fuzzy): %s from '%s'", cat, result[:60])
                return cat
        _log.warning("[MainLoop] Unexpected intent: '%s', default='action'", result[:100])
        return "action"
    except Exception as e:
        _log.warning("[MainLoop] Intent classification failed: %s, default='action'", e)
        return "action"


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
    # Strip MiniMax tool call blocks: <minimax:tool_call>...</minimax:tool_call>
    text = re.sub(r"<minimax:tool_call>[\s\S]*?</minimax:tool_call>\s*", "", text)
    # Strip generic XML tool call blocks: <tool_call>...</tool_call>, <tool_calls>...</tool_calls>
    text = re.sub(r"</?tool_?calls?>\s*", "", text)
    # Strip <invoke>...</invoke> blocks (tool call XML fragments)
    text = re.sub(r"<invoke\b[^>]*>[\s\S]*?</invoke>\s*", "", text)
    # Strip function call patterns like functions.xxx:N
    text = re.sub(r"functions\.\w+:\d+\s*", "", text)
    text = re.sub(r'\{"command"\s*:\s*"[^"]*"(?:,\s*"[^"]*"\s*:\s*[^}]*)?\}', '', text)
    text = re.sub(r'<\|/?tool[^|]*\|>', '', text)
    text = re.sub(r"\[\s*\{\s*'type'\s*:\s*'text'[^]]*\]", '', text)
    text = _strip_dangerous_html(text)
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

        # P2-2: OpenTelemetry tracing (manual span — avoids re-indenting 600+ lines)
        try:
            from runtime.tracing import get_tracer
            _tracer = get_tracer("arcmind.main_loop")
            _span = _tracer.start_as_current_span("main_loop.run")
            _otel_span = _span.__enter__()
            _otel_span.set_attribute("command", inp.command[:200])
            _otel_span.set_attribute("source", inp.source or "")
        except Exception:
            _span = None
            _otel_span = None

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

            # ── PM Agent: Complexity-based routing ──
            # Skip PM routing for sub-agent calls (prevent recursion)
            if not inp.context.get("sub_agent_role"):
                try:
                    # V2: Enhanced 4-way classifier with project support
                    try:
                        from runtime.project_classifier import classify_complexity
                    except ImportError:
                        from runtime.complexity_classifier import classify_complexity
                    try:
                        complexity = classify_complexity(inp.command, inp.session_id)
                    except Exception as cls_err:
                        logger.warning("[DECIDE] classify_complexity failed: %s, default=simple", cls_err)
                        complexity = "simple"

                    # Store in context so downstream (_model_fallback) can check
                    inp.context["_complexity"] = complexity

                    if complexity == "progress_query":
                        # ROOT-2 fix: 收集 PM 數據注入 context，讓 LLM 決定回覆
                        # 不再直接硬返回，保留對話連續性
                        try:
                            from runtime.task_tracker import task_tracker
                            progress_data = task_tracker.format_pm_dashboard(inp.session_id) or ""

                            try:
                                recently_done = task_tracker.get_recently_completed(
                                    session_id=inp.session_id, within_minutes=60
                                )
                                if recently_done:
                                    done_lines = ["\n\n\u2705 **最近完成的任务:**"]
                                    for t in recently_done:
                                        worker_tag = f" [{t.worker_id}]" if t.worker_id else ""
                                        preview = str(t.result)[:200] if t.result else "无结果"
                                        done_lines.append(f"  [{t.task_id}]{worker_tag} {t.command[:60]}\n    结果: {preview}")
                                    progress_data += "\n".join(done_lines)
                            except Exception:
                                pass

                            try:
                                from runtime.project_registry import project_registry
                                session_str = str(inp.session_id) if inp.session_id else None
                                project_progress = project_registry.format_all_projects(session_str)
                                if project_progress:
                                    progress_data += "\n\n" + project_progress
                            except ImportError:
                                pass

                            if progress_data.strip():
                                inp.context["_progress_data"] = progress_data
                        except Exception as _pe:
                            logger.debug("[DECIDE] progress data collection failed: %s", _pe)

                    if complexity == "project":
                        # V2: Project-level task → create project + spawn PM Agent
                        try:
                            from runtime.project_registry import project_registry
                            from runtime.task_tracker import task_tracker
                            from runtime.pm_agent import PMAgent, pm_pool

                            # 1. Create project in registry
                            project = project_registry.create_project(
                                name=inp.command[:100],
                                description=inp.command,
                                session_id=str(inp.session_id) if inp.session_id else None,
                            )
                            project_registry.transition_project(project["id"], "planning")

                            # 2. Spawn PM Agent (same as complex path)
                            pm_task_id = task_tracker.create(
                                command=inp.command,
                                session_id=inp.session_id,
                            )

                            session_ctx = inp.context.copy()
                            session_ctx["session_db_id"] = inp.session_id
                            session_ctx["project_id"] = project["id"]

                            pm = PMAgent(pm_task_id, inp.command, session_ctx)
                            pm_pool.submit(pm)

                            # 3. Record PM assignment in project registry
                            try:
                                project_registry.assign_pm_agent(project["id"], pm_task_id)
                            except Exception:
                                pass

                            active_count = pm_pool.get_active_count()
                            ack_msg = (
                                f"\U0001f4ca 收到！这是一个项目级任务，我已创建项目 "
                                f"[{project['id']}] \"{project['name'][:50]}\" "
                                f"并分配 PM Agent [{pm.worker_id}] (任务 {pm_task_id}) "
                                f"使用 {pm.model.split(':')[-1]} 模型在后台执行。\n"
                                f"当前有 {active_count} 个 PM 在工作。\n"
                                f"你可以随时问「进度?」来查看。"
                            )
                            return LoopResult(
                                success=True, task_id=task_id,
                                skill_used="_project_create", model_used="n/a",
                                output=ack_msg, tokens_used=0,
                                elapsed_s=round(time.monotonic() - start, 3),
                                governor_approved=True,
                            )
                        except Exception as e:
                            logger.warning("[DECIDE] Project creation failed: %s, falling back to complex", e)
                            # Fall through to complex handling

                    # complexity == "complex" → CEO handles directly with agentic tool loop
                    # CEO has web_search, run_command, memory tools — no need to spawn PM
                    # Only "project" spawns PM (multi-phase initiative needing decomposition)
                    # complexity == "simple" or "complex" → fall through to existing flow
                except Exception as e:
                    logger.warning("[DECIDE] PM routing failed: %s, falling back to direct", e)

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

            # Governor 審計（本地 Governor + V3 PolicyEngine）
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
                # V3: Governor 風險評估 + PolicyEngine + ApprovalGate
                gov_ctx = {
                    "command": inp.command[:300],
                    "skill": skill_name,
                    "source": inp.source,
                    "session_id": inp.session_id,
                    "task_id": task_id,
                }
                gov_result = _gov.evaluate_with_policy(
                    action=f"execute_skill:{skill_name}",
                    context=gov_ctx,
                )
                audit = {"approved": gov_result.decision not in ("BLOCKED", "APPROVAL_REQUIRED"),
                         "reason": gov_result.reason,
                         "risk_score": gov_result.risk_score,
                         "decision": gov_result.decision}
            except Exception as e:
                logger.error("[DECIDE] Governor failed (fail-closed — action BLOCKED): %s", e)
                audit = {"approved": False, "reason": f"Governor error: {e}", "risk_score": 1.0, "decision": "BLOCKED"}

            # V3: Handle APPROVAL_REQUIRED — pause task, wait for human approval
            if audit.get("decision") == "APPROVAL_REQUIRED":
                reason = audit.get("reason", "Policy requires approval")
                logger.info("[DECIDE] ⏸️ APPROVAL_REQUIRED for skill=%s: %s", skill_name, reason)
                lifecycle.tasks.fail(task_id, f"Approval required: {reason}")
                return LoopResult(
                    success=False,
                    task_id=task_id,
                    skill_used=skill_name,
                    model_used=model_used,
                    output=f"⏸️ 此操作需要人工審批: {reason}\n請在 Telegram 確認後重新執行。",
                    tokens_used=0,
                    elapsed_s=round(time.monotonic() - start, 3),
                    governor_approved=False,
                    error=f"Approval required: {reason}",
                )

            if not audit.get("approved", True):
                reason = audit.get("reason", "Governor blocked")
                feedback.on_governor_blocked(
                    action=f"execute_skill:{skill_name}",
                    reason=reason,
                )
                # 記錄到 episodic memory，方便日後分析被阻止的模式
                try:
                    from memory.memory_store import memory_store
                    memory_store.add_episodic(
                        content=f"Governor blocked action: execute_skill:{skill_name}. Reason: {reason}",
                        metadata={"type": "governor_blocked", "skill": skill_name, "reason": reason},
                    )
                except Exception:
                    pass
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

            # V3.1: Resolve caller agent identity for skill ACL
            _caller_agent = (
                inp.context.get("sub_agent_role")
                or inp.context.get("agent_type", "main")
            )
            # Set thread-local for tool_loop's _tool_invoke_skill
            try:
                from runtime.tool_loop import set_caller_agent
                set_caller_agent(_caller_agent)
            except Exception:
                pass

            if skill_manager.is_registered(skill_name):
                # 本地 Skill
                try:
                    skill_result = skill_manager.invoke(skill_name, {
                        **inp.context,
                        "command": inp.command,
                    }, caller_agent=_caller_agent)
                except Exception as _perm_err:
                    if "not permitted" in str(_perm_err):
                        # V3.1: Agent skill ACL denied → fallback to model
                        logger.warning("[ACT] Skill ACL denied: %s", _perm_err)
                        skill_result = self._model_fallback(inp, memory_hits, model_override=model_used)
                        skill_name = "_model_direct"
                    else:
                        raise
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

                    # MEM-1: 跳過閒聊/簡短對話的 episodic 寫入
                    _is_trivial = (
                        inp.task_type in ("chat", "question", "greeting")
                        or (len(inp.command) < 10 and tokens_used < 500)
                    )
                    if not _is_trivial:
                        # Episodic: 記錄有價值的對話
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
        # ── PM routing is handled in DECIDE phase (classify_complexity). ──
        # _model_fallback only runs for tasks already classified as "simple"
        # or when sub-agents need CEO to execute directly.

        # ── 使用 PersonaInjector 構建 system prompt ──
        agent_type = inp.context.get("sub_agent_role") or inp.context.get("agent_type", "main")
        from runtime.model_router import model_router  # must be at function top to avoid UnboundLocalError
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
            # ROOT-2: progress_query 不再硬返回，而是注入 PM 數據讓 LLM 決定回覆
            progress_data = inp.context.get("_progress_data", "")
            if progress_data:
                context_summary += f"\n\n## 當前任務/項目狀態\n{progress_data}"

            # CRIT-2 fix: 注入用戶偏好
            pref_tag = ""
            try:
                from memory.preference_manager import get_preferences_tag
                pref_tag = get_preferences_tag()
            except Exception:
                pass

            # LOGIC-1 fix: 讀取 agents.json 的 per-agent system_prompt
            agent_extra = ""
            try:
                import json as _json
                import pathlib
                _agents_path = pathlib.Path(__file__).parent.parent / "config" / "agents.json"
                if _agents_path.exists():
                    agents_cfg = _json.loads(_agents_path.read_text(encoding="utf-8"))
                    for ag in agents_cfg.get("agents", []):
                        if ag.get("id") == agent_type and ag.get("system_prompt"):
                            agent_extra = ag["system_prompt"]
                            break
            except Exception:
                pass

            extra = ""
            if pref_tag:
                extra += pref_tag + "\n\n"
            if agent_extra:
                extra += agent_extra

            system = persona_injector.build_system_prompt(
                context_summary=context_summary,
                extra_instructions=extra.strip(),
                agent_type=agent_type,
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
        # ── Casual chat detection: bypass tool system entirely ──
        # Import utilities needed by both chat and agentic paths
        # _strip_think_tags is defined at module level (enhanced version with HTML/markup stripping)

        is_casual = False
        try:
            from runtime.delegator import Delegator
            is_casual = Delegator._is_casual_chat(inp.command)
        except Exception:
            pass

        if is_casual:
            # ── Check if this is a knowledge question that needs tools ──
            _KNOWLEDGE_MARKERS = [
                '什么是', '怎么', '如何', '为什么', '哪个', '哪些',
                '有没有', '能不能', '是不是', '可以吗',
                '最近', '现在', '今天', '明天', '这周',
                '新闻', '资讯', '消息', '动态',
                '多少钱', '价格', '汇率', '股价',
                '天气', '温度',
                '谁', 'who', 'what', 'how', 'why', 'when', 'where',
                '?', '？',
            ]
            cmd_lower = inp.command.lower()
            needs_search = any(m in cmd_lower for m in _KNOWLEDGE_MARKERS)
            if needs_search:
                logger.info("[MainLoop] Knowledge question detected, using agentic mode with tools")
                is_casual = False  # Fall through to agentic mode
            else:
                # ── Chat Mode: single-shot LLM call without any tools ──
                logger.info("[MainLoop] Chat mode: no tools, lightweight prompt")
                try:
                    from runtime.model_router import model_router

                    # Build lightweight chat system prompt (no TOOLS.md)
                    try:
                        from persona.loader import persona_loader
                        soul = persona_loader.get_soul() or ""
                        user_md = persona_loader.get_user() or ""
                        chat_system = soul + "\n\n" + user_md
                    except Exception:
                        chat_system = system  # fallback to full system prompt

                    # Build messages with conversation history
                    chat_messages = []
                    chat_messages.append({"role": "system", "content": chat_system})
                    conv_history = inp.context.get("conversation_history", [])
                    if conv_history:
                        for turn in conv_history[:-1]:
                            chat_messages.append({
                                "role": turn["role"],
                                "content": turn["content"],
                            })
                    chat_messages.append({"role": "user", "content": inp.command})

                    chosen = model_override or model_router.select_model(inp.task_type, inp.budget)[0]
                    provider_name, model_id = model_router._parse_model(chosen)
                    provider = model_router._providers.get(provider_name)

                    if provider:
                        resp = provider.complete(
                            model=model_id,
                            messages=chat_messages,
                            system=None,
                            max_tokens=2048,
                            timeout=120,  # Chat mode 2 分鐘 LLM 呼叫上限
                        )
                        text = _normalize_ml_content(resp.content) if hasattr(resp, 'content') else str(resp)
                        tokens = resp.total_tokens if hasattr(resp, 'total_tokens') else 0
                        cleaned = _strip_think_tags(text) if text else ""
                        # If response became empty after stripping (model output was only tool calls),
                        # fall through to agentic mode so tools can actually be used
                        if cleaned and cleaned.strip():
                            return {
                                "success": True,
                                "output": cleaned,
                                "tokens": tokens,
                                "tool_calls": [],
                            }
                        else:
                            logger.info("[MainLoop] Chat mode response empty after stripping, falling through to agentic mode")
                            is_casual = False  # Will fall through
                except Exception as chat_err:
                    logger.warning("[MainLoop] Chat mode failed, falling through to agentic: %s", chat_err)
                # If chat mode fails or response was empty, fall through to normal agentic mode below

        # ── Normal task mode: tool filtering + agentic loop ──
        tool_filter = None

        # LOGIC-2 fix: 優先使用 agents.json 的 allowed_tools
        try:
            import json as _json
            import pathlib
            _agents_path = pathlib.Path(__file__).parent.parent / "config" / "agents.json"
            if _agents_path.exists():
                agents_cfg = _json.loads(_agents_path.read_text(encoding="utf-8"))
                for ag in agents_cfg.get("agents", []):
                    if ag.get("id") == agent_type:
                        allowed = ag.get("allowed_tools", [])
                        if allowed and "__all__" not in allowed:
                            tool_filter = allowed
                            logger.info("[MainLoop] Agent '%s' allowed_tools: %s", agent_type, allowed)
                        break
        except Exception:
            pass

        # Semantic tool filtering fallback (when no agent tool restriction)
        if tool_filter is None:
            try:
                from runtime.capability_selector import capability_selector
                tool_filter = capability_selector.get_relevant_tool_names(inp.command, top_k=20)
                if tool_filter:
                    # URL 检测：如果命令中包含 URL，强制注入 read_url_content
                    import re as _re
                    if _re.search(r'https?://', inp.command):
                        _url_tools = ["read_url_content", "web_search"]
                        for _ut in _url_tools:
                            if _ut not in tool_filter:
                                tool_filter.insert(0, _ut)
                        logger.info("[MainLoop] URL detected, injected read_url_content + web_search into tool_filter")
                    logger.info("[MainLoop] Tool filter: %s", ", ".join(tool_filter[:5]))
            except Exception:
                pass  # 篩選失敗不影響功能，會使用全部工具

        # ── Gate 閉環: Pre-Gate 檢查 ──
        _gate_on = False
        gate_ctx = None
        try:
            from config.settings import settings as _s
            _gate_on = _s.gate_enabled
        except Exception:
            pass

        if _gate_on:
            try:
                from runtime.gate import pre_gate, GateContext
                gate_ctx = GateContext(
                    intent=inp.command,
                    tool_names=tool_filter or [],
                    system_snippet=system[:500] if system else "",
                )
                pre = pre_gate(gate_ctx)
                if not pre.ok:
                    # 擴大工具選擇
                    logger.info("[Gate] Pre-Gate rejected, expanding tool_filter (top_k=%d→%d)",
                                gate_ctx.top_k, gate_ctx.top_k + 3)
                    tool_filter = capability_selector.get_relevant_tool_names(
                        inp.command, top_k=gate_ctx.top_k + 3)
            except Exception as _ge:
                logger.debug("[Gate] Pre-Gate error (disabled): %s", _ge)
                _gate_on = False  # gate 掛了就關掉，不影響下游

        # ── 使用 Agentic Tool Loop（OpenClaw 的核心執行力）──
        try:
            from runtime.tool_loop import agentic_complete

            # Build conversation messages from session history for continuity
            messages = []
            conv_history = inp.context.get("conversation_history", [])
            if conv_history:
                # 限制对话历史到最近 10 条消息，防止上下文过长导致偷懒
                recent_history = conv_history[-11:-1] if len(conv_history) > 11 else conv_history[:-1]
                for turn in recent_history:
                    messages.append({
                        "role": turn["role"],
                        "content": turn["content"],
                    })
                # Add current prompt as the final user message
                messages.append({"role": "user", "content": inp.command})

            # LLM-based intent classification (replaces keyword NLC)
            cmd_lower = inp.command.lower()
            intent = _llm_classify_intent(inp.command, model_override)
            needs_action = (intent == "action")
            logger.info("[MainLoop] LLM intent: %s, needs_action=%s", intent, needs_action)

            # ── Hallucination Prevention: Strict Role Enforcement ──
            strict_action_roles = {"qa", "code", "devops"}
            if inp.context.get("sub_agent_role") in strict_action_roles:
                needs_action = True

            # 强制中文回复 + 反幻觉指令
            if system:
                system = system + (
                    "\n\n**核心规则（必须遵守）**：\n"
                    "1. 你必须始终使用简体中文回复用户。\n"
                    "2. **严禁幻觉（最高优先级）**：\n"
                    "   - 你绝对不可以声称已完成任何操作而没有实际调用工具\n"
                    "   - 安装软件 → 必须用 run_command 执行\n"
                    "   - 克隆仓库 → 必须用 run_command 执行 git clone\n"
                    "   - 生成文件 → 必须用 write_file 或 run_command\n"
                    "   - 读取网页 → 必须用 read_url_content\n"
                    "   - 搜索信息 → 必须用 web_search\n"
                    "3. **文件验证原则**：\n"
                    "   - 如果你说某文件存在，你必须先用 run_command 执行 ls 确认\n"
                    "   - 绝对不能编造文件路径、文件大小等具体信息\n"
                    "4. **诚实原则**：\n"
                    "   - 如果你之前声称做了某事但实际没有执行，你必须承认\n"
                    "   - 如果你不能完成某任务，说明原因，不要假装完成\n"
                    "5. **禁止的行为**：\n"
                    "   - 禁止说已完成但没调用 run_command\n"
                    "   - 禁止编造文件路径和输出结果\n"
                    "   - 禁止基于之前的虚假对话继续编造"
                )

            result = agentic_complete(
                prompt=inp.command,
                system=system,
                task_type=inp.task_type,
                budget=inp.budget,
                model=model_override,
                messages=messages if messages else None,
                require_tool_usage=needs_action,
                tool_filter=tool_filter,
                skip_auto_memory=True,  # main_loop ORIENT 已注入記憶
            )
            # The agentic_complete function returns a dict, extract its 'content'
            output_text = _strip_think_tags(result["content"])

            # ── Gate 閉環: Post-Gate 檢查 + 重試 ──
            if _gate_on and gate_ctx is not None:
                try:
                    from runtime.gate import post_gate, apply_feedback, MAX_RETRIES

                    post = post_gate(inp.command, output_text)
                    while not post.passed and gate_ctx.retry_count < MAX_RETRIES:
                        if post.failure_type == "leaked_json":
                            # 機械攔截，直接清掉，不重試主模型
                            output_text = "我正在處理你的請求，請稍候。"
                            break

                        # 閉環: Post → Pre 調整 → 重跑主模型
                        gate_ctx = apply_feedback(gate_ctx, post)
                        pre = pre_gate(gate_ctx)
                        if not pre.ok or gate_ctx.extra_constraints:
                            if post.failure_type == "wrong_skill":
                                tool_filter = capability_selector.get_relevant_tool_names(
                                    inp.command, top_k=gate_ctx.top_k)
                            if gate_ctx.extra_constraints:
                                system = (system or "") + f"\n[Constraint] {gate_ctx.extra_constraints}"

                        logger.info("[Gate] Retrying main model (attempt %d/%d)",
                                    gate_ctx.retry_count, MAX_RETRIES)
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
                        output_text = _strip_think_tags(result["content"])
                        post = post_gate(inp.command, output_text)
                except Exception as _ge:
                    logger.debug("[Gate] Post-Gate error (pass-through): %s", _ge)

            # ── P6-Layer3: 行動審計摘要（Proof-of-Work） ──
            _tool_calls = result.get("tool_calls", [])
            if _tool_calls:
                _action_lines = []
                for tc in _tool_calls:
                    _tn = tc.get("tool", "?")
                    _ti = tc.get("input", {})
                    _success = tc.get("success", True)
                    _icon = "✅" if _success else "❌"
                    # Build concise input summary
                    _input_summary = ""
                    if isinstance(_ti, dict):
                        # Show first key=value pair for context
                        for k, v in _ti.items():
                            _vs = str(v)[:60]
                            _input_summary = f'({k}="{_vs}")'
                            break
                    _out_preview = str(tc.get("output", ""))[:80].replace("\n", " ")
                    _action_lines.append(f"  {_icon} {_tn}{_input_summary} → {_out_preview}")
                if _action_lines:
                    _action_summary = "\n\n📋 本次行動：\n" + "\n".join(_action_lines)
                    output_text = output_text.rstrip() + _action_summary

            return {
                "success": True,
                "output": output_text,
                "tokens": result.get("total_tokens", 0),
                "tool_calls": _tool_calls,
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
                "output": _strip_think_tags(_normalize_ml_content(resp.content)),
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
