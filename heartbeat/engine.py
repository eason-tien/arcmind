# -*- coding: utf-8 -*-
"""
ArcMind Heartbeat — Context-Aware Proactive Engine
=====================================================
OpenClaw 風格的 Heartbeat：不只是 Cron 定時任務，而是
**上下文感知**的主動推送引擎。

與 ARCHILLX 原有 Cron 的區別：
- Cron: 無狀態定時任務（每次獨立執行）
- Heartbeat: 有上下文的主動檢查（知道最近發生了什麼）

Heartbeat 檢查流程：
1. 定期喚醒
2. 收集上下文（最近的 Session 活動、MGIS 記憶等）
3. 判斷是否有值得主動推送的資訊
4. 通過 Gateway → Channel 送出主動推送

整合點：
- 與 runtime/cron.py 協調（避免重複觸發）
- 通過 Gateway delivery queue 發送推送
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Callable

from gateway.session_manager import session_manager
from gateway.router import OutboundMessage
from gateway.server import delivery_queue

logger = logging.getLogger("arcmind.heartbeat")


class HeartbeatCheck:
    """A single heartbeat check function."""

    def __init__(
        self,
        name: str,
        check_fn: Callable[..., Any],
        interval_s: int = 300,
        enabled: bool = True,
    ):
        self.name = name
        self.check_fn = check_fn
        self.interval_s = interval_s
        self.enabled = enabled
        self.last_run: str = ""
        self.last_result: str = ""
        self.run_count: int = 0


class HeartbeatEngine:
    """
    Context-aware proactive push engine.
    Higher-level than Cron: knows about session context.
    """

    def __init__(self):
        self._checks: list[HeartbeatCheck] = []
        self._running = False
        self._tasks: list[asyncio.Task] = []
        logger.info("[Heartbeat] initialized")

    def register(
        self,
        name: str,
        check_fn: Callable,
        interval_s: int = 300,
        enabled: bool = True,
    ) -> None:
        """Register a heartbeat check."""
        self._checks.append(HeartbeatCheck(
            name=name,
            check_fn=check_fn,
            interval_s=interval_s,
            enabled=enabled,
        ))
        logger.info("[Heartbeat] registered check: %s (every %ds)", name, interval_s)

    async def start(self) -> None:
        """Start all heartbeat check loops."""
        self._running = True
        logger.info("[Heartbeat] Starting %d checks", len(self._checks))

        for check in self._checks:
            if check.enabled:
                task = asyncio.create_task(
                    self._run_check_loop(check),
                    name=f"heartbeat_{check.name}",
                )
                self._tasks.append(task)

    async def stop(self) -> None:
        """Stop all heartbeat checks."""
        self._running = False
        for task in self._tasks:
            task.cancel()
        self._tasks.clear()
        logger.info("[Heartbeat] stopped")

    async def _run_check_loop(self, check: HeartbeatCheck) -> None:
        """Run a single check on its interval."""
        while self._running:
            try:
                await asyncio.sleep(check.interval_s)
                if not self._running:
                    break

                # Gather context
                context = self._gather_context()

                # Run check
                if asyncio.iscoroutinefunction(check.check_fn):
                    result = await check.check_fn(context)
                else:
                    result = check.check_fn(context)

                check.run_count += 1
                check.last_run = datetime.now(timezone.utc).isoformat()
                check.last_result = str(result)[:200] if result else ""

                # If check returns a message, push it
                if result and isinstance(result, str) and result.strip():
                    await self._push_to_active_sessions(check.name, result)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("[Heartbeat/%s] check error: %s", check.name, e)

    def _gather_context(self) -> dict:
        """Gather current system context for heartbeat checks."""
        sessions = session_manager.list_sessions()
        return {
            "active_sessions": len(sessions),
            "sessions": sessions,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    async def _push_to_active_sessions(self, source: str, message: str) -> None:
        """Push a proactive message to all active sessions."""
        sessions = session_manager.list_sessions()
        pushed = 0
        for s in sessions:
            session_id = s["session_id"]
            msg = OutboundMessage(
                session_id=session_id,
                text=f"💡 [{source}] {message}",
                channel=s.get("channel", ""),
                metadata={"source": "heartbeat", "check": source},
            )
            await delivery_queue.put(msg)
            pushed += 1

        if pushed > 0:
            logger.info("[Heartbeat/%s] pushed to %d sessions", source, pushed)

    def list_checks(self) -> list[dict]:
        return [
            {
                "name": c.name,
                "interval_s": c.interval_s,
                "enabled": c.enabled,
                "run_count": c.run_count,
                "last_run": c.last_run,
            }
            for c in self._checks
        ]

    def summary(self) -> dict:
        return {
            "running": self._running,
            "checks": self.list_checks(),
        }


# ── Singleton ──
heartbeat_engine = HeartbeatEngine()
