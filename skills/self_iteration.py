# -*- coding: utf-8 -*-
"""
ArcMind Skill: Self-Iteration
每週自我迭代技能 — CRON 觸發入口。
"""
from __future__ import annotations

import logging

logger = logging.getLogger("arcmind.skills.self_iteration")


def run(inputs: dict) -> dict:
    """
    CRON-triggered self-iteration entry point.

    inputs:
      phase: "meeting" — run full weekly meeting
             "daily_check" — check & execute pending iteration tasks
    """
    phase = inputs.get("phase", "meeting")

    if phase == "meeting":
        from runtime.iteration_engine import run_weekly_meeting
        logger.info("[SelfIteration] Starting weekly agent meeting...")
        return run_weekly_meeting()

    elif phase == "daily_check":
        from runtime.iteration_engine import execute_daily_check
        logger.info("[SelfIteration] Running daily iteration check...")
        return execute_daily_check()

    else:
        return {"error": f"Unknown phase: {phase}"}
