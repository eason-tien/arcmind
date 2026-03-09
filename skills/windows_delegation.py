"""
Skill: windows_delegation
Allows the macOS ArcMind (CEO) to assign shell/python tasks to the Windows PC (192.168.1.151) via REST API.
This requires the Windows PC to be running `windows_worker/server.py`.
"""
from __future__ import annotations
import logging
import json
import httpx

logger = logging.getLogger("arcmind.skill.windows_delegation")
# Hardcoded Windows PC IP for now, as specified in prompt
WINDOWS_WORKER_URL = "http://192.168.1.151:8101/v1/execute_task"

def run(inputs: dict) -> dict:
    """
    inputs:
      - title (str): Short description of the task
      - command (str): The powershell command or python script to run on the Windows node
      - task_type (str): "shell" or "python" (default: "shell")
    returns:
      - success (bool): Did the execution succeed?
      - stdout (str): Standard output from the execution
      - stderr (str): Standard error from the execution
    """
    title = inputs.get("title", "").strip()
    command = inputs.get("command", "").strip()
    task_type = inputs.get("task_type", "shell").strip()

    if not command:
        return {"error": "command is required."}

    logger.info(f"[Windows Delegation] Sending task '{title}' to {WINDOWS_WORKER_URL}")
    
    payload = {
        "title": title,
        "command": command,
        "task_type": task_type
    }
    
    try:
        # Use httpx to send a POST request with a reasonable timeout for execution
        with httpx.Client(timeout=300.0) as client:
            response = client.post(WINDOWS_WORKER_URL, json=payload)
            response.raise_for_status()
            
            result = response.json()
            if result.get("success", False):
                logger.info(f"[Windows Delegation] Success: {result.get('stdout', '')[:100]}...")
            else:
                logger.warning(f"[Windows Delegation] Failed on remote: {result.get('error') or result.get('stderr')}")
                
            return result
            
    except httpx.ConnectError:
        error_msg = f"Connection refused. Please ensure the Windows Worker (server.py) is running on 192.168.1.151:8101"
        logger.error(f"[Windows Delegation] {error_msg}")
        return {"error": error_msg, "success": False}
    except Exception as e:
        logger.error(f"[Windows Delegation] Execution failed: {e}")
        return {"error": str(e), "success": False}
