import asyncio
import json
import logging
import uuid
from typing import Dict, Any, Optional

from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger("arcmind.gateway.a2a_hub")

class A2AHub:
    """
    Manages Agent-to-Agent (A2A) WebSocket connections from Edge nodes (e.g., Android phones).
    Exposes methods for the PC Agent to dispatch tasks and await results.
    """
    def __init__(self):
        # Maps client_id to WebSocket
        self.active_connections: Dict[str, WebSocket] = {}
        # Maps task_id to asyncio.Future for awaiting responses
        self.pending_tasks: Dict[str, asyncio.Future] = {}

    async def connect(self, client_id: str, websocket: WebSocket):
        await websocket.accept()
        self.active_connections[client_id] = websocket
        logger.info(f"[A2AHub] Edge Agent connected: {client_id}")

    def disconnect(self, client_id: str):
        if client_id in self.active_connections:
            del self.active_connections[client_id]
            logger.info(f"[A2AHub] Edge Agent disconnected: {client_id}")

            # Cancel any pending tasks for this client
            for task_id, future in list(self.pending_tasks.items()):
                # We don't have a strict client_id check per task in this simple version,
                # but we could just cancel all tasks if we only expect 1 client.
                # Here we just log it. The futures will timeout anyway.
                pass

    async def listen_to_client(self, client_id: str, websocket: WebSocket):
        try:
            while True:
                data = await websocket.receive_text()
                try:
                    payload = json.loads(data)
                    logger.debug(f"[A2AHub] Received from {client_id}: {payload}")
                    
                    msg_type = payload.get("type")
                    if msg_type == "a2a_response":
                        task_id = payload.get("task_id")
                        if task_id and task_id in self.pending_tasks:
                            future = self.pending_tasks.pop(task_id)
                            if not future.done():
                                future.set_result(payload)
                    else:
                        logger.warning(f"[A2AHub] Unhandled message type: {msg_type}")
                except json.JSONDecodeError:
                    logger.warning(f"[A2AHub] Invalid JSON from {client_id}: {data}")
        except WebSocketDisconnect:
            self.disconnect(client_id)
        except Exception as e:
            logger.error(f"[A2AHub] Error in client loop {client_id}: {e}")
            self.disconnect(client_id)

    async def dispatch_task(self, client_id: str, action: str, tool_args: Dict[str, Any], timeout: float = 30.0) -> Dict[str, Any]:
        """
        Dispatches a tool execution task to the connected Edge Agent and waits for the response.
        """
        if client_id not in self.active_connections:
            return {"error": f"Edge Agent '{client_id}' is not connected."}

        websocket = self.active_connections[client_id]
        task_id = str(uuid.uuid4())
        
        payload = {
            "type": "a2a_task",
            "task_id": task_id,
            "action": action,
            "tool_args": tool_args
        }

        loop = asyncio.get_running_loop()
        future = loop.create_future()
        self.pending_tasks[task_id] = future

        try:
            await websocket.send_text(json.dumps(payload))
            logger.info(f"[A2AHub] Dispatched task {task_id} ({action}) to {client_id}")
            
            # Wait for the response
            response = await asyncio.wait_for(future, timeout=timeout)
            return response.get("content", {"result": "No content field in response"})
        except asyncio.TimeoutError:
            self.pending_tasks.pop(task_id, None)
            return {"error": f"Task timed out after {timeout} seconds."}
        except Exception as e:
            self.pending_tasks.pop(task_id, None)
            return {"error": f"Failed to dispatch task: {str(e)}"}

# Global singleton
a2a_hub = A2AHub()
