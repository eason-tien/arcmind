# -*- coding: utf-8 -*-
"""
ArcMind — Lightweight Governor
================================
移植自 ARCHILLX v1.1 governor.py。
規則型風險評估 + 幻覺偵測 + 自適應閾值。

模式：off | audit_only | soft_block | hard_block

v1.1 — Adaptive thresholds:
  Every N evaluations, analyse recent audit history and nudge
  warn_threshold ±5 (clamped [20, 80]) to reduce chronic
  false-positive block rates.
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("arcmind.governor")

# ── 高風險行為關鍵字 ─────────────────────────────────────────────────────────
_HIGH_RISK_ACTIONS = {
    "delete", "rm ", "rmdir", "drop table", "truncate",
    "format", "shutdown", "reboot", "kill", "terminate",
    "exec(", "eval(", "__import__",
}

_MEDIUM_RISK_ACTIONS = {
    "write", "modify", "update", "patch", "post",
    "send", "deploy", "push", "publish",
    "code_exec", "subprocess",
}

_SENSITIVE_PATHS = {
    "/etc/", "/usr/", "/bin/", "/sbin/",
    "~/.ssh", "~/.config", "/root/",
}

# ── 幻覺/妄想偵測 ────────────────────────────────────────────────────────────
_HALLUCINATION_CLAIM_PATTERNS = {
    "我已经买入", "我已买入", "已成功买入", "已执行买入",
    "我已经卖出", "我已卖出", "已成功卖出",
    "已完成交易", "交易成功", "持仓更新", "帮你买了", "帮你卖了",
    "已经下单", "订单已提交", "已转账", "转账成功", "付款成功",
    "已发送邮件", "邮件已发送", "已发布", "已部署",
    "我已执行", "操作成功完成", "任务已完成", "已帮你完成",
    "i have bought", "i have sold", "trade executed",
    "order placed", "transaction completed", "payment sent",
    "email sent", "i deployed", "i executed", "task completed",
}

_REAL_EXEC_SKILLS = {
    "shell_exec", "code_exec", "file_ops", "system_control",
    "browser_open", "screenshot", "clipboard",
    "http_request", "web_search", "cron_management",
}

_STRICT_ENFORCEMENT_SKILLS = {
    "file_ops", "code_exec", "shell_exec",
    "skill_creator", "trade_executor", "agent_management",
}


@dataclass
class GovDecision:
    decision: str       # APPROVED | WARNED | BLOCKED
    risk_score: int     # 0–100
    reason: str
    action: str
    context: dict


class Governor:
    """
    輕量 Governor — 同步風險評估。

    Modes:
      off        → 永遠 APPROVED
      audit_only → 記錄但不阻擋
      soft_block → 高風險 WARNED，超閾值 BLOCKED
      hard_block → 風險 > warn 即 BLOCKED
    """

    _ADAPT_EVERY     = 20
    _ADAPT_STEP      = 5
    _BLOCK_RATE_HIGH = 0.40
    _BLOCK_RATE_LOW  = 0.05

    def __init__(self, mode: str = "soft_block",
                 warn_threshold: int = 40,
                 block_threshold: int = 70):
        self.mode = os.getenv("GOVERNOR_MODE", mode)
        self.block_threshold = int(os.getenv("GOVERNOR_BLOCK_THRESHOLD", str(block_threshold)))
        raw_warn = int(os.getenv("GOVERNOR_WARN_THRESHOLD", str(warn_threshold)))
        self.warn_threshold = max(20, min(80, raw_warn))
        if self.warn_threshold != raw_warn:
            logger.warning("[Governor] warn_threshold clamped: %d → %d (valid range: 20-80)",
                           raw_warn, self.warn_threshold)
        self._eval_count = 0
        self._audit_history: list[str] = []
        logger.info("[Governor] mode=%s warn=%d block=%d",
                    self.mode, self.warn_threshold, self.block_threshold)

    def evaluate(self, action: str,
                 context: dict | None = None) -> GovDecision:
        ctx = context or {}

        if self.mode == "off":
            return GovDecision("APPROVED", 0, "governor_off", action, ctx)

        score = self._score(action, ctx)
        decision, reason = self._decide(score)

        self._log(action, decision, score, reason, ctx)

        # Adaptive threshold
        self._eval_count += 1
        if self._eval_count % self._ADAPT_EVERY == 0:
            self._adapt_thresholds()

        return GovDecision(decision=decision, risk_score=score,
                           reason=reason, action=action, context=ctx)

    def _score(self, action: str, ctx: dict) -> int:
        score = 0
        action_lower = action.lower()
        ctx_str = json.dumps(ctx).lower()
        command = ctx.get("command", "").lower()

        for kw in _HIGH_RISK_ACTIONS:
            if kw in action_lower or kw in ctx_str:
                score += 35
                break

        for kw in _MEDIUM_RISK_ACTIONS:
            if kw in action_lower:
                score += 20
                break

        for sp in _SENSITIVE_PATHS:
            if sp in ctx_str:
                score += 30
                break

        if ctx.get("source") == "cron":
            score += 10

        skill = ctx.get("skill", "")
        if skill == "code_exec":
            score += 25
        elif skill == "file_ops":
            op = ctx.get("operation", "")
            if op in ("delete", "write"):
                score += 20

        if skill in _STRICT_ENFORCEMENT_SKILLS:
            score += 10

        # ── 幻覺偵測 ──
        _has_hallucination = any(
            p in command or p in action_lower
            for p in _HALLUCINATION_CLAIM_PATTERNS
        )
        if _has_hallucination and skill not in _REAL_EXEC_SKILLS:
            score += 45
            logger.warning(
                "[Governor] HALLUCINATION: command claims execution "
                "but skill='%s' is not real exec. score+45", skill
            )

        return min(score, 100)

    def _decide(self, score: int) -> tuple[str, str]:
        if self.mode == "audit_only":
            return "APPROVED", f"audit_only (score={score})"

        if score >= self.block_threshold:
            if self.mode in ("soft_block", "hard_block"):
                return "BLOCKED", f"risk={score} >= block={self.block_threshold}"
            return "WARNED", f"risk={score} (audit_only)"

        if score >= self.warn_threshold:
            if self.mode == "hard_block":
                return "BLOCKED", f"risk={score} >= warn={self.warn_threshold} (hard)"
            return "WARNED", f"risk={score} — proceed with caution"

        return "APPROVED", f"risk={score} — ok"

    def _adapt_thresholds(self) -> None:
        if self.mode in ("off", "audit_only"):
            return
        if len(self._audit_history) < 10:
            return
        recent = self._audit_history[-100:]
        total = len(recent)
        blocked = sum(1 for d in recent if d == "BLOCKED")
        rate = blocked / total

        nudge = 0
        if rate > self._BLOCK_RATE_HIGH:
            nudge = +self._ADAPT_STEP
        elif rate < self._BLOCK_RATE_LOW:
            nudge = -self._ADAPT_STEP

        if nudge:
            old = self.warn_threshold
            self.warn_threshold = max(20, min(80, self.warn_threshold + nudge))
            logger.info("[Governor] adaptive: warn %d → %d (block_rate=%.2f)",
                        old, self.warn_threshold, rate)

    def _log(self, action: str, decision: str, score: int,
             reason: str, ctx: dict) -> None:
        self._audit_history.append(decision)
        if len(self._audit_history) > 200:
            self._audit_history = self._audit_history[-100:]

        log_fn = logger.warning if decision != "APPROVED" else logger.debug
        log_fn("[Governor] %s: action=%s score=%d reason=%s",
               decision, action[:80], score, reason)

        # V3: Persistent audit event
        try:
            from runtime.audit_events import audit_events
            audit_events.record(
                event_type="governor_decision",
                source="governor",
                summary=f"{decision}: {action[:100]}",
                severity="warning" if decision != "APPROVED" else "info",
                decision=decision,
                risk_score=score,
                task_id=ctx.get("task_id", ""),
                session_id=ctx.get("session_id", ""),
                details={"action": action[:200], "reason": reason, "skill": ctx.get("skill", "")},
            )
        except Exception:
            pass

        # JSONL audit file (legacy, kept for backward compat)
        try:
            audit_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "logs", "governor_audit.jsonl"
            )
            os.makedirs(os.path.dirname(audit_path), exist_ok=True)
            rec = json.dumps({
                "ts": time.time(),
                "action": action[:120],
                "decision": decision,
                "risk_score": score,
                "skill": ctx.get("skill", ""),
            }, ensure_ascii=False)
            with open(audit_path, "a", encoding="utf-8") as f:
                f.write(rec + "\n")
        except Exception:
            pass

        # Write to memory as causal
        if decision == "BLOCKED":
            try:
                from memory.memory_store import memory_store
                memory_store.add_causal(
                    cause=f"Action '{action[:80]}' scored {score}",
                    effect=f"Governor BLOCKED: {reason[:100]}",
                    confidence=min(score / 100.0, 1.0),
                )
            except Exception:
                pass

    def evaluate_with_policy(self, action: str, context: dict | None = None) -> GovDecision:
        """
        V3: Enhanced evaluate with PolicyEngine integration.
        First runs Governor risk scoring, then PolicyEngine rule evaluation.
        If policy says 'approval_required', creates ApprovalGate.
        """
        gov_decision = self.evaluate(action, context)
        ctx = context or {}

        # Only invoke policy engine for non-trivial actions
        if gov_decision.risk_score < 10:
            return gov_decision

        try:
            from runtime.policy_engine import policy_engine
            skill = ctx.get("skill", "generic_execute")
            policy_result = policy_engine.evaluate(
                action_type=skill,
                risk_score=gov_decision.risk_score,
                role=ctx.get("role", "user"),
                context=ctx,
            )

            if policy_result["decision"] == "deny":
                gov_decision.decision = "BLOCKED"
                gov_decision.reason = f"policy_deny: {policy_result['reason']}"
            elif policy_result["decision"] == "approval_required" and gov_decision.decision != "BLOCKED":
                gov_decision.decision = "APPROVAL_REQUIRED"
                gov_decision.reason = f"policy: {policy_result['reason']}"

                # Create approval gate
                try:
                    from runtime.approval_gate import approval_gate
                    approval_gate.create(
                        task_id=ctx.get("task_id", ""),
                        project_id=ctx.get("project_id"),
                        session_id=ctx.get("session_id", ""),
                        trigger_reason=f"Policy requires approval: {policy_result['reason']}",
                        risk_score=gov_decision.risk_score,
                        requested_by="governor",
                    )
                except Exception as gate_err:
                    logger.debug("[Governor] ApprovalGate creation failed: %s", gate_err)

        except ImportError:
            pass
        except Exception as pe:
            logger.debug("[Governor] PolicyEngine check skipped: %s", pe)

        return gov_decision


# Singleton
governor = Governor()
