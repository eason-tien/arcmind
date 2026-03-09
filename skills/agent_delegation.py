"""
Skill: agent_delegation
零人類公司 CEO 任務委派引擎。

支援：
  - 單一 Agent 委派 (delegate_task)
  - 多 Agent 協作委派 (delegate_multi)
  - 任務升級 (escalate_task)
  - 任務交接 (handoff_task)

所有委派都通過 IAMP (Inter-Agent Message Protocol) 發送結構化訊息，
並在 lifecycle 中追蹤任務狀態。
"""
from __future__ import annotations

import logging

from runtime.agent_registry import agent_registry
from runtime.iamp import message_bus, shared_memory_manager, MessageType
from runtime.lifecycle import lifecycle

logger = logging.getLogger("arcmind.skill.agent_delegation")


def delegate_task(inputs: dict) -> dict:
    """
    Single-agent delegation.

    inputs:
      - assignee (str): Agent id (e.g., 'code', 'search', 'qa', 'devops', 'pm')
      - title (str): Short description of the delegated task.
      - task_data (dict): Detailed instructions or context for the sub-agent.
      - parent_task_id (int): ID of the current task delegating the work.
      - priority (str): "low" | "medium" | "high" | "critical" (default: "medium")
    """
    assignee = inputs.get("assignee", "").strip()
    title = inputs.get("title", "").strip()
    task_data = inputs.get("task_data", {})
    parent_task_id = inputs.get("parent_task_id")
    priority = inputs.get("priority", "medium")

    if not assignee or not title:
        return {"error": "assignee and title are required fields."}

    persona = agent_registry.get(assignee)
    if not persona:
        valid_roles = ", ".join(agent_registry.list_roles())
        return {"error": f"Invalid assignee '{assignee}'. Valid roles are: {valid_roles}"}

    if not persona.enabled:
        return {"error": f"Agent '{assignee}' is currently disabled."}

    try:
        sub_task_id = lifecycle.tasks.create(
            title=title,
            task_type="delegated",
            input_data=task_data,
            assigned_to=assignee,
            parent_task_id=parent_task_id,
        )

        # Send structured message via IAMP
        message_bus.send(
            sender="main",
            receiver=assignee,
            msg_type=MessageType.TASK_ASSIGN,
            payload={
                "title": title,
                "task_data": task_data,
                "priority": priority,
                "parent_task_id": parent_task_id,
            },
            task_id=str(sub_task_id),
        )

        logger.info("Task %s delegated to %s (parent=%s, priority=%s)",
                     sub_task_id, assignee, parent_task_id, priority)

        return {
            "task_id": sub_task_id,
            "assignee": assignee,
            "status": "created",
            "priority": priority,
            "message": f"Successfully delegated task to {persona.name}.",
        }
    except Exception as e:
        logger.error("Failed to delegate task: %s", e)
        return {"error": str(e)}


def delegate_multi(inputs: dict) -> dict:
    """
    Multi-agent sequential delegation (pipeline).

    inputs:
      - title (str): Overall task title
      - steps (list[dict]): Ordered list of steps, each with:
          - assignee (str): Agent id
          - instruction (str): What this agent should do
      - parent_task_id (int): Parent task ID
      - priority (str): "low" | "medium" | "high" | "critical"

    Example:
      steps: [
        {"assignee": "search", "instruction": "調研 React 18 新特性"},
        {"assignee": "code", "instruction": "基於調研結果寫一個範例"},
        {"assignee": "qa", "instruction": "測試範例代碼"}
      ]
    """
    title = inputs.get("title", "").strip()
    steps = inputs.get("steps", [])
    parent_task_id = inputs.get("parent_task_id")
    priority = inputs.get("priority", "medium")

    if not title or not steps:
        return {"error": "title and steps are required."}

    if len(steps) > 5:
        return {"error": "Maximum 5 steps per multi-agent delegation."}

    # Validate all assignees first
    for i, step in enumerate(steps):
        assignee = step.get("assignee", "")
        persona = agent_registry.get(assignee)
        if not persona:
            return {"error": f"Step {i + 1}: Invalid assignee '{assignee}'."}
        if not persona.enabled:
            return {"error": f"Step {i + 1}: Agent '{assignee}' is disabled."}

    try:
        # Create parent pipeline task
        pipeline_task_id = lifecycle.tasks.create(
            title=f"[Pipeline] {title}",
            task_type="pipeline",
            input_data={"steps": steps, "total_steps": len(steps)},
            assigned_to="main",
            parent_task_id=parent_task_id,
        )

        # Create individual step tasks
        step_task_ids = []
        for i, step in enumerate(steps):
            assignee = step["assignee"]
            instruction = step.get("instruction", title)

            step_task_id = lifecycle.tasks.create(
                title=f"[Step {i + 1}/{len(steps)}] {instruction}",
                task_type="delegated",
                input_data={
                    "instruction": instruction,
                    "step_index": i,
                    "total_steps": len(steps),
                    "pipeline_id": pipeline_task_id,
                },
                assigned_to=assignee,
                parent_task_id=pipeline_task_id,
            )
            step_task_ids.append(step_task_id)

            message_bus.send(
                sender="main",
                receiver=assignee,
                msg_type=MessageType.TASK_ASSIGN,
                payload={
                    "title": instruction,
                    "step_index": i,
                    "total_steps": len(steps),
                    "pipeline_id": pipeline_task_id,
                    "priority": priority,
                },
                task_id=str(step_task_id),
            )

        # Initialize shared memory for the pipeline
        mem = shared_memory_manager.get(str(pipeline_task_id))
        mem.write("main", "pipeline_config", {
            "title": title,
            "steps": steps,
            "step_task_ids": step_task_ids,
        })

        logger.info("Pipeline %s created: %d steps, tasks=%s",
                     pipeline_task_id, len(steps), step_task_ids)

        return {
            "pipeline_id": pipeline_task_id,
            "step_task_ids": step_task_ids,
            "steps": len(steps),
            "status": "created",
            "message": f"Multi-agent pipeline created with {len(steps)} steps.",
        }
    except Exception as e:
        logger.error("Failed to create pipeline: %s", e)
        return {"error": str(e)}


def escalate_task(inputs: dict) -> dict:
    """
    Sub-agent escalates a task back to CEO (beyond capability).

    inputs:
      - task_id (int): Current task ID
      - reason (str): Why the task is being escalated
      - partial_result (str): Any partial work done
    """
    task_id = inputs.get("task_id")
    reason = inputs.get("reason", "")
    partial_result = inputs.get("partial_result", "")

    if not task_id or not reason:
        return {"error": "task_id and reason are required."}

    message_bus.send(
        sender="unknown",  # Will be filled by the caller's context
        receiver="main",
        msg_type=MessageType.TASK_ESCALATE,
        payload={
            "reason": reason,
            "partial_result": partial_result,
        },
        task_id=str(task_id),
    )

    logger.info("Task %s escalated: %s", task_id, reason[:100])

    return {
        "task_id": task_id,
        "status": "escalated",
        "message": f"Task escalated to CEO. Reason: {reason}",
    }


def handoff_task(inputs: dict) -> dict:
    """
    Hand off a task from one agent to another (mid-pipeline).

    inputs:
      - task_id (int): Current task ID
      - from_agent (str): Current agent
      - to_agent (str): Next agent
      - context (str): Handoff context/results to pass along
    """
    task_id = inputs.get("task_id")
    from_agent = inputs.get("from_agent", "")
    to_agent = inputs.get("to_agent", "")
    context = inputs.get("context", "")

    if not task_id or not to_agent:
        return {"error": "task_id and to_agent are required."}

    persona = agent_registry.get(to_agent)
    if not persona:
        return {"error": f"Invalid target agent '{to_agent}'."}

    # Store handoff context in shared memory
    mem = shared_memory_manager.get(str(task_id))
    mem.write(from_agent, "handoff_context", context)

    message_bus.send(
        sender=from_agent,
        receiver=to_agent,
        msg_type=MessageType.HANDOFF,
        payload={
            "context": context,
            "from_agent": from_agent,
        },
        task_id=str(task_id),
    )

    logger.info("Task %s handed off: %s → %s", task_id, from_agent, to_agent)

    return {
        "task_id": task_id,
        "from": from_agent,
        "to": to_agent,
        "status": "handed_off",
        "message": f"Task handed off from {from_agent} to {persona.name}.",
    }


# ── Skill entry point (backward compat) ──

def run(inputs: dict) -> dict:
    """Unified entry point for the skill."""
    operation = inputs.get("operation", "delegate")

    if operation == "delegate":
        return delegate_task(inputs)
    elif operation == "delegate_multi":
        return delegate_multi(inputs)
    elif operation == "escalate":
        return escalate_task(inputs)
    elif operation == "handoff":
        return handoff_task(inputs)
    else:
        return {"error": f"Unknown operation: {operation}"}
