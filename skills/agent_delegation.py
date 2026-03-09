"""
Skill: agent_delegation
Allows the primary Agent (CEO) to delegate tasks to specialized Sub-Agents (e.g. researcher, engineer).
Registers a sub-task in the lifecycle manager for asynchronous execution by a heartbeat worker.
"""
from __future__ import annotations
import logging

from runtime.lifecycle import lifecycle
from runtime.agent_registry import agent_registry

logger = logging.getLogger("arcmind.skill.agent_delegation")

def delegate_task(inputs: dict) -> dict:
    """
    inputs:
      - assignee (str): The role of the sub-agent (e.g., 'researcher', 'engineer')
      - title (str): Short description of the delegated task.
      - task_data (dict): Detailed instructions or context for the sub-agent.
      - parent_task_id (int): ID of the current task delegating the work.
    returns:
      - task_id (int): The ID of the spawned sub-task.
      - message (str): Status message.
    """
    assignee = inputs.get("assignee", "").strip()
    title = inputs.get("title", "").strip()
    task_data = inputs.get("task_data", {})
    parent_task_id = inputs.get("parent_task_id")

    if not assignee or not title:
        return {"error": "assignee and title are required fields."}

    # Validate assignee role
    persona = agent_registry.get(assignee)
    if not persona:
        valid_roles = ", ".join(agent_registry.list_roles())
        return {"error": f"Invalid assignee '{assignee}'. Valid roles are: {valid_roles}"}

    try:
        # Create a new "created" task assigned to the sub-agent
        sub_task_id = lifecycle.tasks.create(
            title=title,
            task_type="delegated",
            input_data=task_data,
            assigned_to=assignee,
            parent_task_id=parent_task_id
        )
        
        logger.info(f"Task {sub_task_id} delegated to {assignee} (Parent: {parent_task_id})")
        
        return {
            "task_id": sub_task_id,
            "assignee": assignee,
            "status": "created",
            "message": f"Successfully delegated task to {assignee}. It will be picked up by the background worker."
        }
    except Exception as e:
        logger.error(f"Failed to delegate task: {e}")
        return {"error": str(e)}
