# -*- coding: utf-8 -*-
"""
ArcMind — Harness LLM Tools
==============================
暴露 HarnessEngine 能力為 LLM 可呼叫的工具。
Agent 自己可以建立、查詢、控制長時間任務。
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

logger = logging.getLogger("arcmind.harness_tool")


def _run_async(coro):
    """Run async coroutine from sync context."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            future = pool.submit(asyncio.run, coro)
            return future.result(timeout=660)
    else:
        return asyncio.run(coro)


def tool_harness_create(
    title: str,
    steps: list[dict[str, str]],
    goal_id: int | None = None,
    retry_max: int = 3,
    timeout_s: int = 600,
    **kwargs,
) -> str:
    """
    Create a new long-running harness plan and start execution.

    Args:
        title: 任務標題
        steps: Step 清單，每項需包含 {"name": "步驟名", "command": "指令"}
        goal_id: 可選，綁定到 GoalTracker 的目標 ID
        retry_max: 每步最大重試次數（預設 3）
        timeout_s: 每步超時秒數（預設 600）
    """
    from runtime.harness import harness_engine

    try:
        # Validate steps
        if not steps or not isinstance(steps, list):
            return json.dumps({"error": "steps 必須是非空列表"}, ensure_ascii=False)

        for i, s in enumerate(steps):
            if "command" not in s:
                return json.dumps(
                    {"error": f"步驟 {i} 缺少 'command' 欄位"},
                    ensure_ascii=False,
                )
            if "name" not in s:
                s["name"] = f"step_{i}"

        run_id = _run_async(harness_engine.create_run(
            title=title,
            plan=steps,
            goal_id=goal_id,
            retry_max=retry_max,
            timeout_s=timeout_s,
        ))

        # Start execution in background
        async def _bg_execute():
            await harness_engine.execute_run(run_id)

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_bg_execute())
        except RuntimeError:
            # No running loop — run synchronously
            _run_async(harness_engine.execute_run(run_id))

        return json.dumps({
            "status": "created",
            "run_id": run_id,
            "title": title,
            "steps_count": len(steps),
            "message": f"長時間任務已建立並開始執行 (run_id={run_id})",
        }, ensure_ascii=False)

    except Exception as e:
        logger.error("[HarnessTool] create failed: %s", e)
        return json.dumps({"error": str(e)}, ensure_ascii=False)


def tool_harness_status(
    run_id: str | None = None,
    list_all: bool = False,
    status_filter: str | None = None,
    **kwargs,
) -> str:
    """
    Query harness run status.

    Args:
        run_id: 查看特定 run 的詳細狀態
        list_all: 設為 true 列出所有 runs
        status_filter: 依狀態過濾 (running/completed/failed/paused)
    """
    from runtime.harness import harness_engine

    try:
        if run_id:
            result = harness_engine.get_run(run_id)
        elif list_all or status_filter:
            result = harness_engine.list_runs(status=status_filter)
        else:
            # Default: show active runs
            result = harness_engine.list_runs(status="running")
            if not result:
                result = harness_engine.list_runs(limit=5)

        return json.dumps(result, ensure_ascii=False, default=str)

    except Exception as e:
        logger.error("[HarnessTool] status failed: %s", e)
        return json.dumps({"error": str(e)}, ensure_ascii=False)


def tool_harness_control(
    run_id: str,
    action: str,
    **kwargs,
) -> str:
    """
    Control a harness run lifecycle.

    Args:
        run_id: 目標 run ID
        action: 操作方式 — pause / resume / cancel / retry
    """
    from runtime.harness import harness_engine

    try:
        action = action.lower().strip()
        if action == "pause":
            result = _run_async(harness_engine.pause_run(run_id))
        elif action == "resume":
            result = _run_async(harness_engine.resume_run(run_id))
        elif action == "cancel":
            result = _run_async(harness_engine.cancel_run(run_id))
        elif action == "retry":
            result = _run_async(harness_engine.retry_run(run_id))
        else:
            result = {"error": f"未知操作: {action}。支援: pause/resume/cancel/retry"}

        return json.dumps(result, ensure_ascii=False, default=str)

    except Exception as e:
        logger.error("[HarnessTool] control failed: %s", e)
        return json.dumps({"error": str(e)}, ensure_ascii=False)


# ── Tool Schemas (for ToolRegistry) ─────────────────────────────────────────

HARNESS_TOOL_SCHEMAS = {
    "harness_create": {
        "description": (
            "建立並啟動一個長時間運行任務。將複雜任務拆分為多個步驟，"
            "每個步驟會依序執行，支援失敗重試和斷點恢復。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "任務標題",
                },
                "steps": {
                    "type": "array",
                    "description": "步驟清單，每項需包含 name 和 command",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "description": "步驟名稱"},
                            "command": {"type": "string", "description": "要執行的指令"},
                            "skill_hint": {"type": "string", "description": "可選的 skill 提示"},
                        },
                        "required": ["name", "command"],
                    },
                },
                "goal_id": {
                    "type": "integer",
                    "description": "可選，綁定到 GoalTracker 的目標 ID",
                },
                "retry_max": {
                    "type": "integer",
                    "description": "每步最大重試次數（預設 3）",
                },
                "timeout_s": {
                    "type": "integer",
                    "description": "每步超時秒數（預設 600）",
                },
            },
            "required": ["title", "steps"],
        },
        "handler": tool_harness_create,
    },
    "harness_status": {
        "description": "查詢長時間任務的執行狀態。可查看特定 run 或列出所有 runs。",
        "input_schema": {
            "type": "object",
            "properties": {
                "run_id": {
                    "type": "string",
                    "description": "查看特定 run 的詳細狀態",
                },
                "list_all": {
                    "type": "boolean",
                    "description": "設為 true 列出所有 runs",
                },
                "status_filter": {
                    "type": "string",
                    "description": "依狀態過濾: running/completed/failed/paused",
                },
            },
        },
        "handler": tool_harness_status,
    },
    "harness_control": {
        "description": "控制長時間任務的生命週期：暫停 (pause)、恢復 (resume)、取消 (cancel)、重試 (retry)。",
        "input_schema": {
            "type": "object",
            "properties": {
                "run_id": {
                    "type": "string",
                    "description": "目標 run ID",
                },
                "action": {
                    "type": "string",
                    "description": "操作方式: pause / resume / cancel / retry",
                    "enum": ["pause", "resume", "cancel", "retry"],
                },
            },
            "required": ["run_id", "action"],
        },
        "handler": tool_harness_control,
    },
}
