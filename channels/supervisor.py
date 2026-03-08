# -*- coding: utf-8 -*-
"""
ArcMind Channels — Channel Supervisor
=======================================
獨立的通道監督器：管理所有 Channel 的生命週期。
移植自 ARCHILLX v0.44 gateway.py 的監督邏輯。

特性：
- 每個 Channel 獨立運行
- 崩潰自動重啟（指數退避，最大 60 秒）
- SIGTERM/SIGINT 統一關閉
- 健康檢查日誌

使用方式：
  supervisor = ChannelSupervisor()
  supervisor.register(TelegramChannel(...))
  supervisor.register(CLIChannel())
  await supervisor.start_all()
"""
from __future__ import annotations

import asyncio
import logging
import signal
import time
from typing import Any

from channels.base import Channel

logger = logging.getLogger("arcmind.channels.supervisor")


class ChannelSupervisor:
    """
    Manages the lifecycle of all registered channels.
    Migrated from ARCHILLX v0.44 gateway.py _channel_supervisor().
    Upgraded from threads to asyncio.
    """

    def __init__(self):
        self._channels: list[Channel] = []
        self._tasks: dict[str, asyncio.Task] = {}
        self._shutdown_event = asyncio.Event()
        self._health_interval = 300  # 5 minutes

    def register(self, channel: Channel) -> None:
        """Register a channel for supervision."""
        self._channels.append(channel)
        logger.info("[Supervisor] registered channel: %s (enabled=%s)",
                     channel.name, channel.enabled)

    async def start_all(self) -> None:
        """Start all enabled channels with supervision."""
        logger.info("=" * 60)
        logger.info("ArcMind Channel Supervisor starting")
        logger.info("Registered: %s",
                     ", ".join(c.name for c in self._channels))
        logger.info("=" * 60)

        # Setup signal handlers
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, self._signal_handler)

        active = [c for c in self._channels if c.enabled]
        if not active:
            logger.error("[Supervisor] No enabled channels! Exiting.")
            return

        # Start supervisor tasks
        for channel in active:
            task = asyncio.create_task(
                self._supervise(channel),
                name=f"supervisor_{channel.name}",
            )
            self._tasks[channel.name] = task

        # Health check loop
        health_task = asyncio.create_task(self._health_loop())

        # Wait for shutdown
        await self._shutdown_event.wait()

        # Cleanup
        logger.info("[Supervisor] Shutdown signal received, stopping all channels...")
        health_task.cancel()

        for channel in active:
            try:
                await channel.stop()
            except Exception as e:
                logger.warning("[Supervisor] Error stopping %s: %s", channel.name, e)

        # Wait for all supervisor tasks
        for name, task in self._tasks.items():
            task.cancel()
            try:
                await asyncio.wait_for(task, timeout=10)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass

        logger.info("[Supervisor] All channels stopped. Supervisor shutdown complete.")

    async def _supervise(self, channel: Channel) -> None:
        """
        Supervise a single channel: restart on crash with exponential backoff.
        Migrated from ARCHILLX v0.44 _channel_supervisor().
        """
        backoff = 5
        attempt = 0

        while not self._shutdown_event.is_set():
            attempt += 1
            logger.info("[Supervisor/%s] Starting session #%d", channel.name, attempt)

            t0 = time.monotonic()
            try:
                await channel.start()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("[Supervisor/%s] Session #%d crashed: %s",
                            channel.name, attempt, e, exc_info=True)

            elapsed = time.monotonic() - t0

            if self._shutdown_event.is_set():
                break

            if elapsed < 10:
                # Quick crash → exponential backoff
                wait = min(backoff, 60)
                logger.warning(
                    "[Supervisor/%s] Session #%d ended in %.1fs — retry in %ds",
                    channel.name, attempt, elapsed, wait,
                )
                backoff = min(backoff * 2, 60)
                try:
                    await asyncio.wait_for(
                        self._shutdown_event.wait(), timeout=wait
                    )
                except asyncio.TimeoutError:
                    pass
            else:
                # Normal exit → quick restart
                backoff = 5
                logger.info(
                    "[Supervisor/%s] Session #%d ended after %.1fs — restarting",
                    channel.name, attempt, elapsed,
                )
                try:
                    await asyncio.wait_for(
                        self._shutdown_event.wait(), timeout=2
                    )
                except asyncio.TimeoutError:
                    pass

        logger.info("[Supervisor/%s] Supervisor exited after %d sessions.",
                     channel.name, attempt)

    async def _health_loop(self) -> None:
        """Periodic health check logging."""
        while not self._shutdown_event.is_set():
            try:
                await asyncio.wait_for(
                    self._shutdown_event.wait(),
                    timeout=self._health_interval,
                )
            except asyncio.TimeoutError:
                statuses = [c.status() for c in self._channels if c.enabled]
                running = sum(1 for s in statuses if s["running"])
                logger.info("[Supervisor] Health: %d/%d channels running",
                             running, len(statuses))

    def _signal_handler(self) -> None:
        logger.info("[Supervisor] Signal received, initiating shutdown")
        self._shutdown_event.set()

    def stop(self) -> None:
        """Trigger shutdown from outside."""
        self._shutdown_event.set()

    def list_channels(self) -> list[dict]:
        return [c.status() for c in self._channels]

    def summary(self) -> dict:
        channels = self.list_channels()
        return {
            "total": len(channels),
            "running": sum(1 for c in channels if c["running"]),
            "channels": channels,
        }


# ── Singleton ──
channel_supervisor = ChannelSupervisor()
