# -*- coding: utf-8 -*-
"""
ArcMind — Referee / Pre-Act + Post-Act Gate
=============================================
移植自 ARCHILLX v1.0 verify/referee.py。

Pre-Act Gate rejects if:
  - 越權: dangerous commands (rm -rf /, drop database)
  - 受保護文件: governor.py, main.py, schema.py, .env
  - 邏輯跳步: no backup before migrate, no dry-run before apply

Post-Act Gate flags if:
  - 執行失敗 / 返回碼非零
  - 輸出為空
  - 幻覺占位符
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger("arcmind.referee")


@dataclass
class GateResult:
    passed: bool = True
    reason: str = ""
    gate_type: str = ""       # pre_act | post_act
    violations: list[str] = field(default_factory=list)
    severity: str = "info"    # info | warn | block


_DANGEROUS_COMMANDS = [
    re.compile(r"\brm\s+-rf\s+/", re.IGNORECASE),
    re.compile(r"\bdel\s+/[sq]", re.IGNORECASE),
    re.compile(r"\bformat\s+[a-z]:", re.IGNORECASE),
    re.compile(r"\bdrop\s+database\b", re.IGNORECASE),
    re.compile(r"\bdrop\s+table\b", re.IGNORECASE),
    re.compile(r"\btruncate\s+table\b", re.IGNORECASE),
    re.compile(r"\bshutdown\b", re.IGNORECASE),
    re.compile(r"\breboot\b", re.IGNORECASE),
    re.compile(r"\bsystemctl\s+stop\b", re.IGNORECASE),
    re.compile(r"\bkill\s+-9\s+1\b", re.IGNORECASE),
]

_PROTECTED_FILES = [
    "governor.py", "main.py", "main_loop.py", "schema.py",
    "config.py", "lifecycle.py", ".env",
]

_SKIP_STEP_PATTERNS = {
    "migrate": ["backup", "dump", "export"],
    "apply": ["dry-run", "plan", "preview", "diff"],
    "deploy": ["test", "build", "verify"],
    "delete": ["backup", "confirm"],
}


class Referee:
    """Dual gate: Pre-Act + Post-Act verification."""

    def pre_act_check(self, action: dict, task_context: dict | None = None) -> GateResult:
        """Pre-Act Gate: check before execution."""
        violations = []
        ctx = task_context or {}
        action_type = action.get("action", "")
        command = action.get("command", "")
        path = action.get("path", "")

        # 1. Dangerous command
        if command:
            for pat in _DANGEROUS_COMMANDS:
                if pat.search(command):
                    violations.append(f"危險命令: {command[:80]}")

        # 2. Protected file
        if path:
            for pf in _PROTECTED_FILES:
                if path.endswith(pf) and action_type in ("file_write", "shell_exec"):
                    violations.append(f"受保護文件: {pf}")

        # 3. Logic skip
        prev_steps = ctx.get("previous_steps", [])
        prev_actions = [s.get("action", "") for s in prev_steps] if prev_steps else []
        for trigger, prereqs in _SKIP_STEP_PATTERNS.items():
            if trigger in command.lower() or trigger in action_type.lower():
                has_prereq = any(
                    any(p in pa.lower() for p in prereqs)
                    for pa in prev_actions
                )
                if not has_prereq and prev_steps:
                    violations.append(f"邏輯跳步: {trigger} 前應先做 {'/'.join(prereqs)}")

        if violations:
            severity = "block" if any("危險" in v or "受保護" in v for v in violations) else "warn"
            logger.warning("[Referee] Pre-Act FAILED: %s", "; ".join(violations))
            return GateResult(
                passed=severity != "block",
                reason="; ".join(violations),
                gate_type="pre_act",
                violations=violations,
                severity=severity,
            )
        return GateResult(passed=True, gate_type="pre_act", reason="OK")

    def post_act_check(self, action: dict, result: dict,
                       task_context: dict | None = None) -> GateResult:
        """Post-Act Gate: verify after execution."""
        violations = []
        output = result.get("output", "")
        error = result.get("error", "")

        if error or result.get("status") in (False, "failed"):
            violations.append(f"執行失敗: {(error or 'unknown')[:100]}")

        rc = result.get("return_code", result.get("rc"))
        if rc is not None and rc != 0:
            violations.append(f"返回碼非零: rc={rc}")

        if not output and not error and action.get("action") not in ("done", "file_write"):
            violations.append("輸出為空: 可疑")

        _HALL = ["模型名称", "名稱X", "[待定]", "示例结果", "placeholder"]
        if output and any(p in output for p in _HALL):
            violations.append("幻覺指標: 輸出包含占位符")

        if violations:
            logger.warning("[Referee] Post-Act FAILED: %s", "; ".join(violations))
            return GateResult(
                passed=False, reason="; ".join(violations),
                gate_type="post_act", violations=violations, severity="warn",
            )
        return GateResult(passed=True, gate_type="post_act", reason="OK")


# Singleton
referee = Referee()
