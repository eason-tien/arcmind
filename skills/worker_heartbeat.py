"""
Skill: worker_heartbeat
零人類公司背景工作引擎。

定時檢查待處理的委派任務，使用對應 Agent 的 persona 執行。
支援：
  - 單一委派任務處理
  - Pipeline 多步驟任務處理（Step 間自動傳遞 context）
  - 透過 IAMP 回報任務完成/失敗
  - 共享記憶讀寫
"""
from __future__ import annotations

import json
import logging

from runtime.agent_registry import agent_registry
from runtime.iamp import message_bus, shared_memory_manager, MessageType
from runtime.lifecycle import lifecycle

logger = logging.getLogger("arcmind.skill.worker_heartbeat")

_MAX_TASKS_PER_HEARTBEAT = 10


def _process_single_task(task_info: dict) -> dict:
    """Process a single delegated task."""
    task_id = task_info["id"]
    assignee_role = task_info.get("assigned_to")
    parent_task_id = task_info.get("parent_task_id")
    input_data = task_info.get("input_data", {})

    persona = agent_registry.get(assignee_role)
    if not persona:
        lifecycle.tasks.fail(task_id, f"Agent '{assignee_role}' not found in registry.")
        return {"task_id": task_id, "status": "failed", "error": "agent_not_found"}

    if not persona.enabled:
        lifecycle.tasks.fail(task_id, f"Agent '{assignee_role}' is disabled.")
        return {"task_id": task_id, "status": "failed", "error": "agent_disabled"}

    logger.info("[Worker] Processing task %s as '%s'", task_id, assignee_role)
    lifecycle.tasks.start_executing(task_id)

    # Build command with context
    command = task_info["title"]
    if input_data:
        details = {k: v for k, v in input_data.items()
                   if k not in ("step_index", "total_steps", "pipeline_id")}
        if details:
            command += "\n\nDetails: " + json.dumps(details, ensure_ascii=False)

    # For pipeline steps, inject prior step results from shared memory
    pipeline_id = input_data.get("pipeline_id")
    prior_context = None
    if pipeline_id:
        mem = shared_memory_manager.get(str(pipeline_id))
        step_index = input_data.get("step_index", 0)
        if step_index > 0:
            prior_key = f"step_{step_index - 1}_result"
            prior_context = mem.read(prior_key)

    if prior_context:
        command = (
            f"## 前一步驟的結果\n{prior_context}\n\n"
            f"## 你的任務\n{command}"
        )

    context = {
        "sub_agent_role": persona.role,
        "system_prompt_override": persona.system_prompt,
        "allowed_tools": persona.allowed_tools,
        "parent_task_id": parent_task_id,
    }

    try:
        from loop.main_loop import MainLoop, LoopInput

        loop_input = LoopInput(
            command=command,
            source="worker_heartbeat",
            task_type="delegated",
            model_hint=persona.default_model,
            context=context,
        )

        loop = MainLoop()
        result = loop.run(loop_input)

        if result.success:
            output = result.output or ""
            lifecycle.tasks.close(
                task_id,
                output_data={"result": output},
                tokens_used=result.tokens_used,
            )

            # Store result in shared memory for pipeline handoff
            if pipeline_id:
                step_index = input_data.get("step_index", 0)
                mem = shared_memory_manager.get(str(pipeline_id))
                mem.write(assignee_role, f"step_{step_index}_result", output)

            # Send completion message via IAMP
            message_bus.send(
                sender=assignee_role,
                receiver="main",
                msg_type=MessageType.TASK_COMPLETE,
                payload={"output": output[:500], "tokens": result.tokens_used},
                task_id=str(task_id),
            )

            logger.info("[Worker] Task %s completed.", task_id)
            return {"task_id": task_id, "status": "completed"}
        else:
            error_msg = result.error or "Unknown execution error."
            lifecycle.tasks.fail(task_id, error_msg=error_msg)

            message_bus.send(
                sender=assignee_role,
                receiver="main",
                msg_type=MessageType.TASK_ESCALATE,
                payload={"reason": error_msg},
                task_id=str(task_id),
            )

            logger.warning("[Worker] Task %s failed: %s", task_id, error_msg)
            return {"task_id": task_id, "status": "failed", "error": error_msg}

    except Exception as e:
        logger.error("[Worker] Exception on task %s: %s", task_id, e)
        lifecycle.tasks.fail(task_id, error_msg=str(e))
        return {"task_id": task_id, "status": "error", "error": str(e)}


def _check_pipeline_completion(pipeline_id: int, open_tasks: list):
    """Check if all steps in a pipeline are done and close the pipeline task."""
    step_tasks = [
        t for t in open_tasks
        if t.get("input_data", {}).get("pipeline_id") == pipeline_id
    ]

    # If no more open step tasks, the pipeline is complete
    if not step_tasks:
        try:
            mem = shared_memory_manager.get(str(pipeline_id))
            all_results = mem.read_all()
            lifecycle.tasks.close(
                pipeline_id,
                output_data={"results": all_results},
            )
            shared_memory_manager.cleanup(str(pipeline_id))
            logger.info("[Worker] Pipeline %s completed.", pipeline_id)
        except Exception as e:
            logger.error("[Worker] Failed to close pipeline %s: %s", pipeline_id, e)


def run(inputs: dict) -> dict:
    """
    Heartbeat entry point. Processes pending delegated tasks.
    """
    logger.info("Worker heartbeat started.")
    open_tasks = lifecycle.tasks.list_open()

    # Filter: created tasks assigned to sub-agents (not main/ceo)
    pending_tasks = [
        t for t in open_tasks
        if t["status"] == "created"
        and t.get("assigned_to", "main") not in ("main", "ceo")
        and t.get("task_type") != "pipeline"
    ]

    if not pending_tasks:
        return {"message": "No pending delegated tasks.", "processed": 0}

    logger.info("Found %d pending tasks.", len(pending_tasks))

    # Process tasks (limit per heartbeat to avoid overload)
    results = []
    for task_info in pending_tasks[:_MAX_TASKS_PER_HEARTBEAT]:
        result = _process_single_task(task_info)
        results.append(result)

    # Check if any pipelines completed
    pipeline_ids = set()
    for task_info in pending_tasks[:_MAX_TASKS_PER_HEARTBEAT]:
        pid = task_info.get("input_data", {}).get("pipeline_id")
        if pid:
            pipeline_ids.add(pid)

    # Re-fetch open tasks to check pipeline status
    if pipeline_ids:
        refreshed_open = lifecycle.tasks.list_open()
        for pid in pipeline_ids:
            _check_pipeline_completion(pid, refreshed_open)

    processed = len(results)
    succeeded = sum(1 for r in results if r.get("status") == "completed")

    return {
        "message": f"Processed {processed} tasks ({succeeded} succeeded).",
        "processed": processed,
        "succeeded": succeeded,
        "results": results,
    }
