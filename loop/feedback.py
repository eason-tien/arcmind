"""
ArcMind 結果學習回饋引擎
任務完成後，將結果、成因、教訓寫回 MGIS LMF。
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

from config.settings import settings

logger = logging.getLogger("arcmind.feedback")


class FeedbackEngine:
    """
    結果學習回饋：
    1. 任務成功/失敗 → 寫入 MGIS memory
    2. 因果關係 → 寫入 MGIS causal
    3. 重要決策 → 寫入本地 evidence 日誌
    """

    def on_task_success(self, task_id: int, title: str, skill_name: str,
                        output_summary: str, tokens_used: int = 0,
                        tags: list[str] | None = None) -> None:
        """任務成功後回饋"""
        from foundation.mgis_client import mgis

        content = (
            f"[ArcMind] Task SUCCESS — {title}\n"
            f"Skill: {skill_name} | Tokens: {tokens_used}\n"
            f"Output: {output_summary[:300]}"
        )
        mgis.memory_add(
            content=content,
            tags=["arcmind", "task_success", skill_name] + (tags or []),
            source="arcmind",
            metadata={
                "task_id": task_id,
                "skill": skill_name,
                "tokens": tokens_used,
                "ts": datetime.utcnow().isoformat(),
            },
        )
        self._write_evidence("task_success", {
            "task_id": task_id,
            "title": title,
            "skill_name": skill_name,
            "tokens_used": tokens_used,
            "output_summary": output_summary,
        })
        logger.info("Feedback: task %d success recorded.", task_id)

    def on_task_failure(self, task_id: int, title: str, skill_name: str,
                        error_msg: str, tags: list[str] | None = None) -> None:
        """任務失敗後回饋"""
        from foundation.mgis_client import mgis

        content = (
            f"[ArcMind] Task FAILED — {title}\n"
            f"Skill: {skill_name}\n"
            f"Error: {error_msg[:300]}"
        )
        mgis.memory_add(
            content=content,
            tags=["arcmind", "task_failure", skill_name] + (tags or []),
            source="arcmind",
            metadata={
                "task_id": task_id,
                "skill": skill_name,
                "error": error_msg,
                "ts": datetime.utcnow().isoformat(),
            },
        )
        # 記錄因果關係：此操作 → 此失敗
        mgis.causal_log(
            cause=f"Execute skill:{skill_name} on task:{title}",
            effect=f"Failure: {error_msg[:100]}",
            confidence=1.0,
            tags=["arcmind", "failure"],
        )
        self._write_evidence("task_failure", {
            "task_id": task_id,
            "title": title,
            "skill_name": skill_name,
            "error_msg": error_msg,
        })
        logger.info("Feedback: task %d failure recorded.", task_id)

    def on_governor_blocked(self, action: str, reason: str,
                            context: dict | None = None) -> None:
        """Governor 攔截後回饋"""
        from foundation.mgis_client import mgis
        mgis.memory_add(
            content=f"[ArcMind] Governor BLOCKED — {action}\nReason: {reason}",
            tags=["arcmind", "governor_blocked"],
            source="arcmind",
            metadata={"action": action, "reason": reason, "context": context},
        )
        self._write_evidence("governor_blocked", {
            "action": action,
            "reason": reason,
            "context": context or {},
        })

    def on_goal_progress(self, goal_id: int, title: str,
                          old_progress: float, new_progress: float,
                          note: str = "") -> None:
        """目標進度更新回饋"""
        from foundation.mgis_client import mgis
        mgis.memory_add(
            content=(
                f"[ArcMind] Goal progress update — {title}\n"
                f"{old_progress:.0%} → {new_progress:.0%}\n"
                f"{note}"
            ),
            tags=["arcmind", "goal_progress", f"goal:{goal_id}"],
            source="arcmind",
        )

    def _write_evidence(self, event_type: str, data: dict) -> None:
        """寫入本地 evidence 日誌"""
        log_dir = settings.evidence_dir / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        today = datetime.utcnow().strftime("%Y-%m-%d")
        log_file = log_dir / f"{today}.jsonl"

        entry = {
            "ts": datetime.utcnow().isoformat(),
            "type": event_type,
            "data": data,
        }
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")


feedback = FeedbackEngine()
