import sys
import os
import subprocess
import json
import logging
from fastapi import FastAPI, Request
import uvicorn

# Configure minimal logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("windows_worker")

app = FastAPI(title="ArcMind Windows Worker", version="1.0.0")

@app.post("/v1/execute_task")
async def execute_task(request: Request):
    """
    Receives a task payload from the macOS CEO and executes it locally.
    Expected JSON payload:
    {
        "title": "Short description of the task",
        "command": "The actual command or python code to run",
        "task_type": "shell" | "python",
        "parent_task_id": 123
    }
    """
    data = await request.json()
    logger.info(f"Received task: {data.get('title', 'Unknown')}")
    
    command = data.get("command", "")
    task_type = data.get("task_type", "shell")
    
    if not command:
        return {"success": False, "error": "No command provided"}
        
    try:
        if task_type == "shell":
            # Execute in powershell or cmd
            result = subprocess.run(
                ["powershell", "-Command", command],
                capture_output=True,
                text=True,
                timeout=300 # 5 minute timeout
            )
            return {
                "success": result.returncode == 0,
                "stdout": result.stdout[:5000],  # Clip extremely long outputs
                "stderr": result.stderr[:5000],
                "exit_code": result.returncode
            }
        elif task_type == "python":
            # Execute python code
            result = subprocess.run(
                [sys.executable, "-c", command],
                capture_output=True,
                text=True,
                timeout=300
            )
            return {
                "success": result.returncode == 0,
                "stdout": result.stdout[:5000],
                "stderr": result.stderr[:5000],
                "exit_code": result.returncode
            }
        else:
            return {"success": False, "error": f"Unknown task_type: {task_type}"}
            
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "Execution timed out (300s)"}
    except Exception as e:
        logger.error(f"Execution error: {e}")
        return {"success": False, "error": str(e)}

@app.get("/health")
def health_check():
    return {"status": "ok", "platform": "windows"}

if __name__ == "__main__":
    logger.info("Starting ArcMind Windows Worker on 0.0.0.0:8101...")
    uvicorn.run(app, host="0.0.0.0", port=8101)
