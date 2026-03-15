# -*- coding: utf-8 -*-
"""
V2 Phase 2: PM Escalation Manager — PM-to-Main escalation mechanism.
Auto-resolves via LLM. No timeout killing — agent runs freely.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any, Optional

logger = logging.getLogger("arcmind.pm_escalation")


class PMEscalationManager:
    """
    Manages PM Agent escalation to Main Agent.

    Flow:
    1. PM calls escalate() — in worker thread
    2. Manager emits AGENT_ESCALATE event
    3. Auto-resolves via LLM (Main Agent decision)
    4. Returns decision to PM Agent
    """

    def __init__(self):
        self._pending: dict[str, dict] = {}
        self._lock = threading.Lock()

    def escalate(
        self,
        task_id: str,
        reason: str,
        context: dict,
        timeout_s: float = 60.0,
    ) -> dict:
        """
        Called by PM Agent (in worker thread).
        Auto-resolves via LLM and returns decision.

        Returns: {"decision": "continue|skip_step|cancel", "reason": "..."}
        """
        logger.info("[Escalation] PM %s escalating: %s", task_id, reason[:100])

        # Update TaskTracker to show paused state
        try:
            from runtime.task_tracker import task_tracker, TaskStatus
            task_tracker.update_status(
                task_id, TaskStatus.PAUSED,
                log_msg=f"升级中: {reason[:80]}"
            )
        except Exception:
            pass

        # Emit escalation event
        self._emit_escalation(task_id, reason, context)

        # Store as pending
        with self._lock:
            self._pending[task_id] = {
                "reason": reason,
                "context": context,
                "timestamp": time.time(),
            }

        # Auto-resolve via LLM
        decision = self._auto_resolve(task_id, reason, context)

        # Clean up
        with self._lock:
            self._pending.pop(task_id, None)

        # V5: Notify user for cancel/skip decisions (not just silent auto-resolve)
        dec_str = decision.get("decision", "continue")
        if dec_str in ("cancel", "skip_step"):
            self._notify_user(task_id, reason, decision, context)

        # Restore TaskTracker status
        try:
            from runtime.task_tracker import task_tracker, TaskStatus
            if dec_str == "cancel":
                task_tracker.update_status(
                    task_id, TaskStatus.FAILED,
                    log_msg=f"升级取消: {decision.get('reason', '')[:80]}"
                )
            else:
                task_tracker.update_status(
                    task_id, TaskStatus.EXECUTING,
                    log_msg=f"升级决定: {dec_str} — {decision.get('reason', '')[:50]}"
                )
        except Exception:
            pass

        logger.info("[Escalation] PM %s resolved: %s", task_id, dec_str)
        return decision

    def resolve_escalation(
        self,
        task_id: str,
        decision: str,
        instructions: str = "",
    ) -> bool:
        """Manually resolve a pending escalation (via API)."""
        with self._lock:
            if task_id not in self._pending:
                return False
            self._pending.pop(task_id)
        return True

    def get_pending(self) -> list[dict]:
        """Return list of pending escalations."""
        with self._lock:
            return [
                {"task_id": tid, **info}
                for tid, info in self._pending.items()
            ]

    def _emit_escalation(self, task_id: str, reason: str, context: dict) -> None:
        """Fire AGENT_ESCALATE event."""
        try:
            from runtime.event_bus import event_bus, Event, EventType
            event_bus.emit(Event(
                type=EventType.AGENT_ESCALATE,
                source="pm_agent",
                payload={
                    "task_id": task_id,
                    "reason": reason,
                    "context": context,
                },
            ))
        except Exception as e:
            logger.debug("[Escalation] Event emission failed: %s", e)

    def _notify_user(self, task_id: str, reason: str,
                     decision: dict, context: dict) -> None:
        """
        V5: Notify user when PM task is cancelled or step is skipped.
        Emits PM_ESCALATION_NOTIFY event for frontend/Telegram to display.
        """
        dec_str = decision.get("decision", "?")
        dec_reason = decision.get("reason", "")
        original_task = context.get("original_task", "")[:100]

        logger.warning("[Escalation] Notifying user: PM %s %s — %s",
                       task_id, dec_str, dec_reason[:80])

        try:
            from runtime.event_bus import event_bus, Event, EventType
            event_bus.emit(Event(
                type=EventType.SYSTEM_EVENT,
                source="pm_escalation",
                payload={
                    "event": "PM_ESCALATION_NOTIFY",
                    "task_id": task_id,
                    "decision": dec_str,
                    "reason": reason[:200],
                    "decision_reason": dec_reason[:200],
                    "original_task": original_task,
                    "notify": True,  # Flag for frontend to show notification
                },
            ))
        except Exception as e:
            logger.debug("[Escalation] Notify event failed: %s", e)

        # Also record in audit log
        try:
            from runtime.audit_events import audit_events
            audit_events.record(
                event_type="pm_escalation_notify",
                source="pm_escalation",
                summary=f"PM {task_id} {dec_str}: {dec_reason[:100]}",
                severity="warning" if dec_str == "cancel" else "info",
                task_id=task_id,
                details={
                    "decision": dec_str,
                    "reason": reason[:300],
                    "original_task": original_task,
                },
            )
        except Exception:
            pass

    def _auto_resolve(self, task_id: str, reason: str, context: dict) -> dict:
        """Use LLM to auto-decide how to handle the escalation.

        V3.1: Now receives enriched context from PM auto-diagnosis, including
        error_type, known_solution, web_suggestions. This gives the LLM enough
        information to make informed decisions instead of blindly defaulting to 'continue'.
        """
        try:
            import concurrent.futures
            from runtime.model_router import model_router

            original_task = context.get("original_task", "?")[:300]
            failures = context.get("failures", 0)
            steps_executed = context.get("steps_executed", 0)
            current_step = context.get("current_step", "?")[:200]
            last_error = context.get("last_error", "")[:500]

            # V3.1: Build diagnosis section for the prompt
            _diag_section = ""
            diagnosis = context.get("diagnosis")
            if diagnosis:
                _diag_section = (
                    f"\n--- 自动诊断结果 ---\n"
                    f"错误类型: {diagnosis.get('error_type', 'unknown')}\n"
                    f"错误摘要: {diagnosis.get('error_summary', '')[:200]}\n"
                )
                if diagnosis.get("known_solution"):
                    sol = diagnosis["known_solution"]
                    _diag_section += f"已知修复方案: {sol.get('fix_action', '')[:150]}\n"
                if diagnosis.get("web_suggestions"):
                    suggestions = diagnosis["web_suggestions"][:3]
                    _diag_section += "Web搜索建议:\n"
                    for s in suggestions:
                        if isinstance(s, str) and s.strip():
                            _diag_section += f"  - {s[:150]}\n"
                        elif isinstance(s, dict):
                            _diag_section += f"  - {str(s)[:150]}\n"
                _diag_section += f"诊断状态: {diagnosis.get('repair_status', 'no_fix')}\n"
                _diag_section += "---\n"

            prompt = (
                f"PM Agent在执行任务时遇到问题，需要你做出决定。\n\n"
                f"任务: {original_task}\n"
                f"问题: {reason}\n"
                f"当前步骤: {current_step}\n"
                f"已执行步骤: {steps_executed}\n"
                f"失败次数: {failures}\n"
            )
            if last_error:
                prompt += f"最后错误: {last_error[:300]}\n"
            if _diag_section:
                prompt += _diag_section
            prompt += (
                f"\n请根据以上信息（尤其是诊断结果）做出决定:\n"
                f"1. continue — 继续执行(有修复方案或错误可忽略时)\n"
                f"2. skip_step — 跳过当前步骤(此步非必要时)\n"
                f"3. cancel — 取消整个任务(错误无法绕过，如Cloudflare拦截、DNS解析失败、认证失败等)\n\n"
                f"注意:\n"
                f"- 如果是 http_403/cloudflare_blocked/dns_failure 等网络层问题，重试无意义，应 cancel 或 skip_step\n"
                f"- 如果有已知修复方案(known_solution)，建议 continue\n"
                f"- 如果是临时性错误(timeout/rate_limit)，可以 continue 重试\n\n"
                f'只回复JSON: {{"decision": "continue|skip_step|cancel", "reason": "简短原因"}}'
            )

            def _call_llm():
                return model_router.complete(
                    prompt=prompt,
                    system="你是项目管理主管。根据情况快速决策。只回复JSON。",
                    max_tokens=256,
                    task_type="general",
                    budget="low",
                )

            # Timeout guard: prevent LLM hang from blocking PM worker forever
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(_call_llm)
                resp = future.result(timeout=60)  # 60s hard timeout

            text = resp.content.strip()
            # Strip think tags
            import re
            text = re.sub(r'<think>[\s\S]*?</think>\s*', '', text).strip()

            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                data = json.loads(text[start:end])
                decision = data.get("decision", "continue")
                if decision not in ("continue", "skip_step", "cancel"):
                    decision = "continue"
                return {"decision": decision, "reason": data.get("reason", "")}

        except concurrent.futures.TimeoutError:
            logger.warning("[Escalation] Auto-resolve timed out (60s), defaulting to continue")
        except Exception as e:
            logger.warning("[Escalation] Auto-resolve failed: %s, defaulting to continue", e)

        return {"decision": "continue", "reason": "Auto-resolve failed, continuing"}


# Singleton
pm_escalation = PMEscalationManager()
