# -*- coding: utf-8 -*-
"""
ArcMind API — Generic Webhook Routes
======================================
接收外部 Webhook 回調（N8N、Zapier、自定義服務等），
轉發到 EventBus 走 OODA Loop 處理。

Endpoint: POST /v1/webhook
Endpoint: POST /v1/webhook/{source}  (帶來源標識)
"""
from __future__ import annotations

import hashlib
import hmac
import logging
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request, Header

logger = logging.getLogger("arcmind.webhook")
router = APIRouter()


@router.post("")
@router.post("/{source}")
async def receive_webhook(
    request: Request,
    source: str = "external",
    x_webhook_secret: Optional[str] = Header(None, alias="X-Webhook-Secret"),
):
    """
    通用 Webhook 接收端點。
    接收 JSON payload 後發佈到 EventBus (EventType.WEBHOOK)，
    由 event_handlers.handle_webhook 走 OODA Loop 處理。

    Headers:
      X-Webhook-Secret: 可選簽名驗證
    """
    # Parse body
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    # Webhook signature verification — fail-closed when secret is configured
    from config.settings import settings
    secret = getattr(settings, "webhook_secret", "")
    if secret:
        if not x_webhook_secret:
            raise HTTPException(status_code=401, detail="Missing webhook secret header")
        if not hmac.compare_digest(secret, x_webhook_secret):
            raise HTTPException(status_code=401, detail="Invalid webhook secret")

    logger.info("[Webhook] Received from source=%s keys=%s",
                source, list(payload.keys()) if isinstance(payload, dict) else type(payload).__name__)

    # Emit to EventBus
    try:
        from runtime.event_bus import event_bus, Event, EventType, EventPriority
        event_bus.emit(Event(
            type=EventType.WEBHOOK,
            source=f"webhook:{source}",
            payload={
                "source": source,
                "data": payload,
                "headers": {
                    k: v for k, v in request.headers.items()
                    if k.lower().startswith("x-")
                },
            },
            priority=EventPriority.NORMAL,
        ))
        return {"status": "accepted", "source": source}
    except Exception as e:
        logger.error("[Webhook] EventBus emit failed: %s", e)
        raise HTTPException(status_code=500, detail="Failed to process webhook")
