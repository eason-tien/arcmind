# -*- coding: utf-8 -*-
"""
ArcMind — Federation Bridge (跨實例協作)
==========================================
讓多個 ArcMind 實例透過 HTTP 互相分工協作。

架構：
  ArcMind-A ←── HTTP POST ──→ ArcMind-B
  FederationBridge 管理 peer 連接、任務發送/接收、斷路器保護。

認證：HMAC X-Federation-Key header（與 webhook_routes 同模式）
傳輸：httpx async/sync，複用 mgis_client 的節流日誌模式
防迴圈：每個任務帶 origin_instance_id，同源不再轉發

用法：
  from runtime.federation import federation_bridge

  # 發送任務到 peer
  result = await federation_bridge.send_task(peer_url, {
      "task_id": "abc123",
      "command": "部署到伺服器",
      "context": {...},
  })
"""
from __future__ import annotations

import asyncio
import hmac
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

import httpx

from config.settings import settings

logger = logging.getLogger("arcmind.federation")

_OFFLINE_LOG_INTERVAL = 300  # 每 peer 每 300s 最多一條離線日誌


# ── Circuit Breaker ──────────────────────────────────────────────────────────

class CircuitState(str, Enum):
    CLOSED = "closed"        # 正常運行
    OPEN = "open"            # 斷路（暫停請求）
    HALF_OPEN = "half_open"  # 試探性恢復


@dataclass
class PeerCircuitBreaker:
    """
    Per-peer 斷路器：連續 N 次失敗 → 冷卻期 → 試探恢復。
    """
    max_failures: int = 3
    reset_timeout: float = 60.0  # 秒

    state: CircuitState = CircuitState.CLOSED
    failure_count: int = 0
    last_failure_time: float = 0.0
    last_success_time: float = 0.0

    def record_success(self) -> None:
        self.failure_count = 0
        self.state = CircuitState.CLOSED
        self.last_success_time = time.monotonic()

    def record_failure(self) -> None:
        self.failure_count += 1
        self.last_failure_time = time.monotonic()
        if self.failure_count >= self.max_failures:
            self.state = CircuitState.OPEN
            logger.warning("[CircuitBreaker] OPEN — %d consecutive failures", self.failure_count)

    def allow_request(self) -> bool:
        if self.state == CircuitState.CLOSED:
            return True
        if self.state == CircuitState.OPEN:
            elapsed = time.monotonic() - self.last_failure_time
            if elapsed >= self.reset_timeout:
                self.state = CircuitState.HALF_OPEN
                logger.info("[CircuitBreaker] HALF_OPEN — trying recovery")
                return True
            return False
        # HALF_OPEN: allow one probe request
        return True

    def status(self) -> dict:
        return {
            "state": self.state.value,
            "failure_count": self.failure_count,
            "last_failure": self.last_failure_time,
            "last_success": self.last_success_time,
        }


# ── Peer Info ────────────────────────────────────────────────────────────────

@dataclass
class PeerInfo:
    """Remote ArcMind peer state."""
    url: str
    instance_id: str = ""
    capabilities: list[str] = field(default_factory=list)
    last_seen: float = 0.0
    circuit: PeerCircuitBreaker = field(default_factory=PeerCircuitBreaker)

    def is_healthy(self) -> bool:
        return self.circuit.allow_request()


# ── Pending Tasks (for async callback tracking) ─────────────────────────────

@dataclass
class PendingTask:
    """Tracks an outbound task waiting for remote result callback."""
    task_id: str
    peer_url: str
    command: str
    session_id: str = ""
    channel: str = ""
    created_at: float = field(default_factory=time.time)
    future: Optional[asyncio.Future] = None


# ── Federation Bridge ────────────────────────────────────────────────────────

class FederationBridge:
    """
    Singleton — 管理所有 peer 連接、跨實例任務發送/接收。
    """

    def __init__(self):
        self._peers: dict[str, PeerInfo] = {}
        self._pending_tasks: dict[str, PendingTask] = {}  # task_id → PendingTask
        self._enabled = settings.federation_enabled
        self._instance_id = settings.federation_instance_id
        self._api_key = settings.federation_api_key
        self._timeout = settings.federation_timeout
        self._last_offline_log: dict[str, float] = {}

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def instance_id(self) -> str:
        return self._instance_id

    def startup(self) -> None:
        """解析 FEDERATION_PEERS 環境變量，初始化 peer 列表。"""
        if not self._enabled:
            return

        peers_str = settings.federation_peers.strip()
        if not peers_str:
            logger.warning("[Federation] Enabled but no peers configured (FEDERATION_PEERS is empty)")
            return

        for raw_url in peers_str.split(","):
            url = raw_url.strip().rstrip("/")
            if url and url not in self._peers:
                self._peers[url] = PeerInfo(url=url)
                logger.info("[Federation] Peer registered: %s", url)

        logger.info("[Federation] Startup complete: instance=%s, peers=%d",
                     self._instance_id, len(self._peers))

    # ── 出站：發送任務到遠端 ──────────────────────────────────────────────────

    async def send_task(
        self,
        peer_url: str,
        task: dict,
        session_id: str = "",
        channel: str = "",
    ) -> dict:
        """
        POST peer/v1/federation/task — 發送任務到遠端 peer。

        Args:
            peer_url: Peer base URL
            task: {command, context, agent_hint, ...}
            session_id: 原始用戶 session（用於回調投遞）
            channel: 原始 channel（用於回調投遞）

        Returns:
            {accepted: bool, remote_task_id: str, error: str}
        """
        peer = self._peers.get(peer_url)
        if not peer:
            return {"accepted": False, "error": f"Unknown peer: {peer_url}"}

        if not peer.circuit.allow_request():
            return {"accepted": False, "error": f"Peer {peer_url} circuit OPEN (cooling down)"}

        task_id = task.get("task_id") or f"fed-{uuid.uuid4().hex[:8]}"
        callback_url = f"http://{settings.arcmind_host}:{settings.arcmind_port}/v1/federation/result"

        payload = {
            "task_id": task_id,
            "command": task.get("command", ""),
            "context": task.get("context", {}),
            "agent_hint": task.get("agent_hint", ""),
            "origin_instance_id": self._instance_id,
            "callback_url": callback_url,
            "session_id": session_id,
            "channel": channel,
        }

        # Track pending task
        pending = PendingTask(
            task_id=task_id,
            peer_url=peer_url,
            command=task.get("command", ""),
            session_id=session_id,
            channel=channel,
        )
        self._pending_tasks[task_id] = pending

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                r = await client.post(
                    f"{peer_url}/v1/federation/task",
                    json=payload,
                    headers=self._make_headers(),
                )
                if r.status_code >= 400:
                    peer.circuit.record_failure()
                    self._pending_tasks.pop(task_id, None)
                    return {"accepted": False, "error": f"HTTP {r.status_code}: {r.text[:256]}"}

                peer.circuit.record_success()
                peer.last_seen = time.time()
                result = r.json()
                return {
                    "accepted": True,
                    "task_id": task_id,
                    "remote_task_id": result.get("remote_task_id", task_id),
                }

        except Exception as e:
            peer.circuit.record_failure()
            self._pending_tasks.pop(task_id, None)
            self._log_offline(peer_url, "[Federation] send_task failed to %s: %s", peer_url, e)
            return {"accepted": False, "error": str(e)}

    async def query_capabilities(self, peer_url: str) -> list[str]:
        """GET peer/v1/federation/capabilities — 取得遠端可用能力列表。"""
        peer = self._peers.get(peer_url)
        if not peer or not peer.circuit.allow_request():
            return []

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.get(
                    f"{peer_url}/v1/federation/capabilities",
                    headers=self._make_headers(),
                )
                if r.status_code == 200:
                    data = r.json()
                    caps = data.get("capabilities", [])
                    peer.capabilities = caps
                    peer.instance_id = data.get("instance_id", "")
                    peer.last_seen = time.time()
                    peer.circuit.record_success()
                    return caps
                else:
                    peer.circuit.record_failure()
                    return []
        except Exception as e:
            peer.circuit.record_failure()
            self._log_offline(peer_url, "[Federation] query_capabilities failed for %s: %s", peer_url, e)
            return []

    async def health_check(self, peer_url: str) -> bool:
        """GET peer/v1/federation/health — 檢查遠端 peer 健康狀態。"""
        peer = self._peers.get(peer_url)
        if not peer:
            return False

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(
                    f"{peer_url}/v1/federation/health",
                    headers=self._make_headers(),
                )
                healthy = r.status_code == 200
                if healthy:
                    peer.circuit.record_success()
                    peer.last_seen = time.time()
                else:
                    peer.circuit.record_failure()
                return healthy
        except Exception as e:
            peer.circuit.record_failure()
            self._log_offline(peer_url, "[Federation] health_check failed for %s: %s", peer_url, e)
            return False

    # ── 入站：處理遠端請求 ────────────────────────────────────────────────────

    async def handle_inbound_task(self, payload: dict) -> dict:
        """
        收到遠端任務請求 → 本地 Delegator 執行 → POST callback 回傳結果。

        payload: {task_id, command, context, agent_hint, origin_instance_id, callback_url, session_id, channel}
        """
        task_id = payload.get("task_id", f"fed-in-{uuid.uuid4().hex[:8]}")
        command = payload.get("command", "")
        callback_url = payload.get("callback_url", "")
        origin = payload.get("origin_instance_id", "unknown")

        # 防迴圈：如果 origin 是自己，拒絕
        if origin == self._instance_id:
            logger.warning("[Federation] Loop detected: task %s originated from self, rejecting", task_id)
            return {"accepted": False, "error": "Federation loop detected"}

        logger.info("[Federation] Inbound task %s from %s: %s", task_id, origin, command[:80])

        # 異步執行 + 回調
        asyncio.create_task(
            self._execute_and_callback(task_id, command, payload, callback_url),
            name=f"federation_task_{task_id}",
        )

        return {"accepted": True, "remote_task_id": task_id}

    async def _execute_and_callback(
        self, task_id: str, command: str, payload: dict, callback_url: str
    ) -> None:
        """在本地執行任務，完成後 POST 結果到 callback_url。"""
        t0 = time.time()
        result = {"success": False, "output": "", "error": ""}

        try:
            from runtime.delegator import delegator

            # 嘗試用 delegator 路由到最佳 agent
            match = delegator.route(command)
            if match:
                result = delegator.execute(match, command)
            else:
                # 無匹配 agent → CEO 直接處理
                from runtime.tool_loop import agentic_complete
                raw = agentic_complete(
                    prompt=command,
                    system="你是 ArcMind，正在協助遠端 ArcMind 實例處理委派任務。",
                    task_type="federation",
                )
                result = {
                    "success": True,
                    "output": raw.get("content", ""),
                    "tokens": raw.get("total_tokens", 0),
                }

        except Exception as e:
            logger.error("[Federation] Task %s execution failed: %s", task_id, e)
            result = {"success": False, "output": "", "error": str(e)}

        elapsed = round(time.time() - t0, 2)
        logger.info("[Federation] Task %s completed in %.1fs (success=%s)",
                     task_id, elapsed, result.get("success"))

        # POST 結果回調
        if callback_url:
            await self._send_result_callback(callback_url, {
                "task_id": task_id,
                "origin_instance_id": payload.get("origin_instance_id", ""),
                "responder_instance_id": self._instance_id,
                "session_id": payload.get("session_id", ""),
                "channel": payload.get("channel", ""),
                "result": {
                    "success": result.get("success", False),
                    "output": str(result.get("output", ""))[:10000],
                    "error": result.get("error", ""),
                    "elapsed_s": elapsed,
                    "tokens": result.get("tokens", 0),
                    "agent_id": result.get("agent_id", "ceo"),
                },
            })

    async def _send_result_callback(self, callback_url: str, payload: dict) -> None:
        """POST 執行結果到遠端 callback URL。"""
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                r = await client.post(
                    callback_url,
                    json=payload,
                    headers=self._make_headers(),
                )
                if r.status_code >= 400:
                    logger.warning("[Federation] Callback to %s failed: HTTP %d",
                                   callback_url, r.status_code)
                else:
                    logger.info("[Federation] Callback sent to %s (task=%s)",
                                callback_url, payload.get("task_id"))
        except Exception as e:
            logger.error("[Federation] Callback to %s error: %s", callback_url, e)

    async def handle_result_callback(self, payload: dict) -> None:
        """
        收到遠端執行結果回調 → emit EventBus FEDERATION_RESULT 事件。

        payload: {task_id, responder_instance_id, session_id, channel, result: {...}}
        """
        task_id = payload.get("task_id", "")
        responder = payload.get("responder_instance_id", "unknown")
        result = payload.get("result", {})

        logger.info("[Federation] Result callback: task=%s from=%s success=%s",
                     task_id, responder, result.get("success"))

        # 清除 pending task
        pending = self._pending_tasks.pop(task_id, None)

        # Emit EventBus event for delivery
        try:
            from runtime.event_bus import event_bus, Event, EventType, EventPriority
            event_bus.emit(Event(
                type=EventType.FEDERATION_RESULT,
                source=f"federation:{responder}",
                payload={
                    "task_id": task_id,
                    "session_id": payload.get("session_id", pending.session_id if pending else ""),
                    "channel": payload.get("channel", pending.channel if pending else ""),
                    "responder": responder,
                    "result": result,
                },
                priority=EventPriority.HIGH,
            ))
        except Exception as e:
            logger.error("[Federation] Failed to emit FEDERATION_RESULT: %s", e)

    # ── 能力查詢 ──────────────────────────────────────────────────────────────

    def local_capabilities(self) -> list[str]:
        """列出本地可用的 agent capabilities + skill 名稱。"""
        caps = []

        # Agent capabilities
        try:
            from runtime.agent_registry import agent_registry
            for agent in agent_registry.list_all():
                if agent.enabled and agent.id != "main":
                    caps.extend(agent.capabilities)
        except Exception:
            pass

        # Skills
        try:
            from runtime.skill_manager import skill_manager
            for skill in skill_manager.list_skills():
                caps.append(f"skill:{skill.get('name', '')}")
        except Exception:
            pass

        return list(set(caps))

    # ── Peer 管理 ─────────────────────────────────────────────────────────────

    def list_peers(self) -> list[dict]:
        """列出所有已知 peer 及其狀態。"""
        return [
            {
                "url": p.url,
                "instance_id": p.instance_id,
                "capabilities": p.capabilities,
                "last_seen": p.last_seen,
                "healthy": p.is_healthy(),
                "circuit": p.circuit.status(),
            }
            for p in self._peers.values()
        ]

    def find_peer_for_capability(self, capability: str) -> Optional[PeerInfo]:
        """找到擁有指定能力且健康的 peer。"""
        for peer in self._peers.values():
            if peer.is_healthy() and capability in peer.capabilities:
                return peer
        return None

    def find_any_healthy_peer(self) -> Optional[PeerInfo]:
        """找到任一健康的 peer（用於負載分擔）。"""
        for peer in self._peers.values():
            if peer.is_healthy():
                return peer
        return None

    # ── 工具方法 ──────────────────────────────────────────────────────────────

    def _make_headers(self) -> dict:
        """生成 Federation 認證 headers。"""
        headers = {
            "Content-Type": "application/json",
            "X-Instance-ID": self._instance_id,
        }
        if self._api_key:
            headers["X-Federation-Key"] = self._api_key
        return headers

    def _log_offline(self, peer_url: str, msg: str, *args) -> None:
        """節流離線日誌（每 peer 每 300s 最多一次）。"""
        now = time.monotonic()
        last = self._last_offline_log.get(peer_url, 0.0)
        if now - last >= _OFFLINE_LOG_INTERVAL:
            logger.warning(msg, *args)
            self._last_offline_log[peer_url] = now

    def summary(self) -> dict:
        """Federation 狀態摘要。"""
        peers = self.list_peers()
        return {
            "enabled": self._enabled,
            "instance_id": self._instance_id,
            "total_peers": len(peers),
            "healthy_peers": sum(1 for p in peers if p["healthy"]),
            "pending_tasks": len(self._pending_tasks),
            "peers": peers,
        }


# ── Global Singleton ─────────────────────────────────────────────────────────
federation_bridge = FederationBridge()
