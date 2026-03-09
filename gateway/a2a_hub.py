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
        # Maps task_id to (asyncio.Future, client_id) for awaiting responses
        self.pending_tasks: Dict[str, tuple[asyncio.Future, str]] = {}

    async def connect(self, client_id: str, websocket: WebSocket):
        await websocket.accept()
        self.active_connections[client_id] = websocket
        logger.info("[A2AHub] Edge Agent connected: %s", client_id)

    def disconnect(self, client_id: str):
        if client_id in self.active_connections:
            del self.active_connections[client_id]
            logger.info("[A2AHub] Edge Agent disconnected: %s", client_id)

            # Cancel all pending tasks for this client so callers don't hang forever
            orphaned = []
            for task_id, (future, owner) in list(self.pending_tasks.items()):
                if owner == client_id and not future.done():
                    future.set_exception(
                        ConnectionError(f"Edge Agent '{client_id}' disconnected")
                    )
                    orphaned.append(task_id)
            for task_id in orphaned:
                self.pending_tasks.pop(task_id, None)
            if orphaned:
                logger.warning("[A2AHub] Cancelled %d orphaned tasks for %s",
                               len(orphaned), client_id)

    async def listen_to_client(self, client_id: str, websocket: WebSocket):
        try:
            while True:
                data = await websocket.receive_text()
                try:
                    payload = json.loads(data)
                    logger.debug("[A2AHub] Received from %s: %s", client_id, payload)

                    msg_type = payload.get("type")
                    if msg_type == "a2a_response":
                        task_id = payload.get("task_id")
                        if task_id and task_id in self.pending_tasks:
                            future, _ = self.pending_tasks.pop(task_id)
                            if not future.done():
                                future.set_result(payload)
                    elif msg_type == "heartbeat":
                        # Respond to heartbeat to keep connection alive
                        try:
                            await websocket.send_text(json.dumps({"type": "heartbeat_ack"}))
                        except Exception:
                            pass
                    else:
                        logger.warning("[A2AHub] Unhandled message type: %s", msg_type)
                except json.JSONDecodeError:
                    logger.warning("[A2AHub] Invalid JSON from %s", client_id)
        except WebSocketDisconnect:
            self.disconnect(client_id)
        except Exception as e:
            logger.error("[A2AHub] Error in client loop %s: %s", client_id, e)
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
        self.pending_tasks[task_id] = (future, client_id)

        try:
            await websocket.send_text(json.dumps(payload))
            logger.info("[A2AHub] Dispatched task %s (%s) to %s", task_id, action, client_id)

            # Wait for the response
            response = await asyncio.wait_for(future, timeout=timeout)
            return response.get("content", {"error": "No content field in response"})
        except asyncio.TimeoutError:
            self.pending_tasks.pop(task_id, None)
            return {"error": f"Task timed out after {timeout} seconds."}
        except ConnectionError as ce:
            return {"error": str(ce)}
        except Exception as e:
            self.pending_tasks.pop(task_id, None)
            return {"error": f"Failed to dispatch task: {str(e)}"}

# Global singleton
a2a_hub = A2AHub()
