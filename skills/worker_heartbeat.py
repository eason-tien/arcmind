"""
Skill: worker_heartbeat
Background worker for Paperclip-style multi-agent orchestration.
Runs on an interval, checks for delegated tasks in 'created' state,
and executes them using the corresponding sub-agent's persona and constraints.
"""
from __future__ import annotations
import logging
import json

from runtime.lifecycle import lifecycle
from runtime.agent_registry import agent_registry

logger = logging.getLogger("arcmind.skill.worker_heartbeat")

def run(inputs: dict) -> dict:
    """
    inputs: (None required)
    returns:
      - processed_tasks: list of resolved task IDs.
    """
    logger.info("Worker heartbeat started. Checking for delegated tasks...")
    open_tasks = lifecycle.tasks.list_open()
    
    # Filter for tasks that are "created" and assigned to a sub-agent (not ceo)
    pending_tasks = [
        t for t in open_tasks 
        if t["status"] == "created" and t.get("assigned_to", "ceo") != "ceo"
    ]
    
    if not pending_tasks:
        return {"message": "No pending delegated tasks found.", "processed": 0}
        
    logger.info(f"Worker heartbeat found {len(pending_tasks)} pending delegated tasks.")
    
    processed_count = 0
    # Lazy import to avoid circular dependency
    from loop.main_loop import MainLoop, LoopInput
    
    for task_info in pending_tasks:
        task_id = task_info["id"]
        assignee_role = task_info.get("assigned_to")
        parent_task_id = task_info.get("parent_task_id")
        
        persona = agent_registry.get(assignee_role)
        if not persona:
            lifecycle.tasks.fail(task_id, f"Agent role '{assignee_role}' not found in registry.")
            continue
            
        logger.info(f"[Worker] Processing Task {task_id} as '{assignee_role}'")
        
        # Mark as executing
        lifecycle.tasks.start_executing(task_id)
        
        # Prepare the input for MainLoop but inject the persona's persona
        command = task_info["title"]
        if task_info.get("input_data"):
            command += "\n\nDetails: " + json.dumps(task_info["input_data"])
            
        # We append a system prompt override to the command temporarily, 
        # or we could rely on a new field in LoopInput. 
        # For now, we inject it directly into the context to guide the prompt formatting.
        context = {
            "sub_agent_role": persona.role,
            "system_prompt_override": persona.system_prompt,
            "allowed_tools": persona.allowed_tools,
            "parent_task_id": parent_task_id
        }
        
        loop_input = LoopInput(
            command=command,
            source="worker_heartbeat",
            task_type="delegated",
            model_hint=persona.default_model,
            context=context
        )
        
        try:
            # We instantiate a fresh MainLoop instance
            loop = MainLoop()
            result = loop.run(loop_input)
            
            if result.success:
                lifecycle.tasks.close(task_id, output_data={"result": result.output}, tokens_used=result.tokens_used)
                logger.info(f"[Worker] Task {task_id} completed successfully.")
            else:
                lifecycle.tasks.fail(task_id, error_msg=result.error or "Unknown execution error.")
                logger.warning(f"[Worker] Task {task_id} failed: {result.error}")
            processed_count += 1
            
        except Exception as e:
            logger.error(f"[Worker] Exception processing tasks {task_id}: {e}")
            lifecycle.tasks.fail(task_id, error_msg=str(e))
            
    return {"message": f"Processed {processed_count} tasks.", "processed": processed_count}
