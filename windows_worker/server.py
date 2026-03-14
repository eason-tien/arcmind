import sys
import os
import subprocess
import json
import hmac
import logging
from fastapi import FastAPI, Request, HTTPException, Header
from typing import Optional
import uvicorn

# Configure minimal logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("windows_worker")

# Auth key loaded from environment — MUST be set in production
_WORKER_API_KEY = os.environ.get("ARCMIND_WORKER_API_KEY", "")

app = FastAPI(title="ArcMind Windows Worker", version="1.0.0")


def _verify_worker_auth(x_api_key: Optional[str]) -> None:
    """Verify worker API key. Fail-closed: no key configured = all requests rejected."""
    if not _WORKER_API_KEY:
        raise HTTPException(status_code=503, detail="Worker API key not configured. Set ARCMIND_WORKER_API_KEY env var.")
    if not x_api_key:
        raise HTTPException(status_code=401, detail="Missing X-API-Key header")
    if not hmac.compare_digest(_WORKER_API_KEY, x_api_key):
        raise HTTPException(status_code=401, detail="Invalid API key")


@app.post("/v1/execute_task")
async def execute_task(
    request: Request,
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
):
    """
    Receives a task payload from the macOS CEO and executes it locally.
    Requires X-API-Key header matching ARCMIND_WORKER_API_KEY env var.
    Expected JSON payload:
    {
        "title": "Short description of the task",
        "command": "The actual command or python code to run",
        "task_type": "shell" | "python",
        "parent_task_id": 123
    }
    """
    _verify_worker_auth(x_api_key)

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
    if not _WORKER_API_KEY:
        logger.error("ARCMIND_WORKER_API_KEY not set. Refusing to start without authentication.")
        sys.exit(1)
    _bind_host = os.environ.get("ARCMIND_WORKER_HOST", "127.0.0.1")  # Default to loopback
    logger.info("Starting ArcMind Windows Worker on %s:8101...", _bind_host)
    uvicorn.run(app, host=_bind_host, port=8101)
