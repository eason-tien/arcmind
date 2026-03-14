# -*- coding: utf-8 -*-
"""
Progress Notifier — Subscribes to PM events on EventBus,
pushes milestone notifications to Telegram.
"""
from __future__ import annotations

import logging

logger = logging.getLogger("arcmind.progress_notifier")


class ProgressNotifier:
    """Listens to EventBus PM events, pushes Telegram notifications."""

    def __init__(self):
        self._registered = False

    def register(self) -> None:
        if self._registered:
            return
        try:
            from runtime.event_bus import event_bus, EventType
            event_bus.subscribe(EventType.SYSTEM_EVENT, self._on_event)
            # V2 Phase 2: Also subscribe to PM_RESULT_READY
            event_bus.subscribe(EventType.PM_RESULT_READY, self._on_event)
            self._registered = True
            logger.info("[ProgressNotifier] Registered for PM events")
        except Exception as e:
            logger.warning("[ProgressNotifier] Registration failed: %s", e)

    async def _on_event(self, event) -> None:
        try:
            payload = event.payload if hasattr(event, "payload") else event
            if not isinstance(payload, dict):
                return
            event_name = payload.get("event", "")
            if not event_name.startswith("pm_") and not event_name.startswith("project_"):
                return

            task_id = payload.get("task_id", "?")
            # Extract per-user chat_id from session_id (e.g., "tg_123456" → "123456")
            session_id = payload.get("session_id", "")

            if event_name == "pm_started":
                msg = f"\U0001f4cb PM [{task_id}] 任务已启动..."
            elif event_name in ("pm_plan_created", "pm_step_start"):
                # Silent — user only wants start + result
                logger.info("[ProgressNotifier] %s %s (silent)", event_name, task_id)
                return
            elif event_name == "pm_completed":
                # V2 Phase 2: Skip the preview-only notification;
                # full result is sent via pm_result_ready event
                return
            elif event_name == "pm_result_ready":
                # V2 Phase 2: Full result delivery to Telegram
                result = payload.get("result", "")
                # Strip <think> tags from LLM response
                import re as _re
                result = _re.sub(r'<think>[\s\S]*?</think>\s*', '', result).strip()
                project_id = payload.get("project_id")
                header = f"\u2705 PM [{task_id}] 任务完成"
                if project_id:
                    header += f" (项目 #{project_id})"
                # Telegram message limit is ~4096 chars
                msg = f"{header}\n\n{result[:3800]}"
                if len(result) > 3800:
                    msg += "\n\n... (结果已截断，完整报告已保存到数据库)"

                # P1-1: 同時推送到 delivery_queue（WebSocket/HTTP 用戶）
                if session_id:
                    try:
                        from gateway.server import delivery_queue
                        from gateway.router import OutboundMessage
                        import asyncio
                        out_msg = OutboundMessage(
                            session_id=session_id,
                            text=f"{header}\n\n{result[:3800]}",
                            channel="",  # delivery_queue 會根據 session 找到對應通道
                            metadata={
                                "pm_result": True,
                                "task_id": task_id,
                                "project_id": project_id,
                            },
                        )
                        await delivery_queue.put(out_msg)
                        logger.info("[ProgressNotifier] PM result pushed to delivery_queue (session=%s)", session_id)
                    except Exception as dq_err:
                        logger.warning("[ProgressNotifier] delivery_queue push failed: %s", dq_err)
            elif event_name == "pm_failed":
                error = payload.get("error", "")[:100]
                msg = f"\u274c PM [{task_id}] 任务失败: {error}"
            # V2: Project events — only notify on completion
            elif event_name in ("project_created", "project_status_changed"):
                logger.info("[ProgressNotifier] %s (silent)", event_name)
                return
            elif event_name == "project_completed":
                name = payload.get("name", "?")
                pid = payload.get("project_id", "?")
                msg = f"\U0001f389 项目 [{pid}] \"{name}\" 已完成!"
            else:
                return

            # Determine target chat_id: per-user from session_id, or fallback to global
            target_chat_id = None
            if session_id and session_id.startswith("tg_"):
                target_chat_id = session_id[3:]  # "tg_123456" → "123456"
            await self._send_telegram(msg, chat_id_override=target_chat_id)
        except Exception as e:
            logger.warning("[ProgressNotifier] Error: %s", e)

    @staticmethod
    async def _send_telegram(message: str, chat_id_override: str = None) -> None:
        try:
            from config.settings import settings
            chat_id = chat_id_override or settings.telegram_chat_id
            bot_token = settings.telegram_bot_token
            if not chat_id or not bot_token:
                logger.warning("[ProgressNotifier] Telegram not configured (no chat_id or token)")
                return

            import aiohttp
            import ssl
            import certifi
            ssl_ctx = ssl.create_default_context(cafile=certifi.where())
            conn = aiohttp.TCPConnector(ssl=ssl_ctx)
            url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
            async with aiohttp.ClientSession(connector=conn) as session:
                resp = await session.post(url, json={
                    "chat_id": chat_id,
                    "text": message,
                })
                if resp.status != 200:
                    body = await resp.text()
                    logger.warning("[ProgressNotifier] Telegram API %d: %s", resp.status, body[:200])
            logger.info("[ProgressNotifier] Telegram sent to chat=%s: %s", chat_id, message[:50])
        except Exception as e:
            logger.warning("[ProgressNotifier] Telegram failed: %s", e)


# Singleton
progress_notifier = ProgressNotifier()
