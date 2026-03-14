# -*- coding: utf-8 -*-
"""
ArcMind API — Federation Routes (跨實例協作)
=============================================
接收來自遠端 ArcMind peer 的任務請求與結果回調。
所有端點使用 X-Federation-Key HMAC 認證。

Endpoints:
  POST /v1/federation/task          — 接收遠端任務
  POST /v1/federation/result        — 接收遠端結果回調
  GET  /v1/federation/capabilities  — 暴露本地可用能力
  GET  /v1/federation/health        — 健康檢查
"""
from __future__ import annotations

import hmac
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, Header

from config.settings import settings

logger = logging.getLogger("arcmind.federation.routes")
router = APIRouter()


def _verify_federation_key(x_federation_key: Optional[str]) -> None:
    """驗證 X-Federation-Key header。Fail-closed: 未設定 key 則拒絕所有請求。"""
    expected = settings.federation_api_key
    if not expected:
        raise HTTPException(
            status_code=503,
            detail="Federation API key not configured. Set FEDERATION_API_KEY env var to enable federation.",
        )
    if not x_federation_key:
        raise HTTPException(status_code=401, detail="Missing X-Federation-Key header")
    if not hmac.compare_digest(expected, x_federation_key):
        raise HTTPException(status_code=401, detail="Invalid federation key")


@router.post("/task")
async def receive_task(
    request: Request,
    x_federation_key: Optional[str] = Header(None, alias="X-Federation-Key"),
):
    """
    接收遠端 ArcMind 實例的任務請求。
    異步執行後通過 callback_url 回傳結果。
    """
    _verify_federation_key(x_federation_key)

    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    command = payload.get("command", "")
    origin = payload.get("origin_instance_id", "unknown")
    task_id = payload.get("task_id", "")

    logger.info("[Federation] Inbound task from %s (task=%s): %s",
                origin, task_id, command[:80])

    try:
        from runtime.federation import federation_bridge
        result = await federation_bridge.handle_inbound_task(payload)
        return result
    except Exception as e:
        logger.error("[Federation] handle_inbound_task error: %s", e)
        raise HTTPException(status_code=500, detail=f"Internal error: {e}")


@router.post("/result")
async def receive_result(
    request: Request,
    x_federation_key: Optional[str] = Header(None, alias="X-Federation-Key"),
):
    """
    接收遠端 ArcMind 實例的任務結果回調。
    """
    _verify_federation_key(x_federation_key)

    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    task_id = payload.get("task_id", "")
    responder = payload.get("responder_instance_id", "unknown")

    logger.info("[Federation] Result callback: task=%s from=%s", task_id, responder)

    try:
        from runtime.federation import federation_bridge
        await federation_bridge.handle_result_callback(payload)
        return {"status": "accepted", "task_id": task_id}
    except Exception as e:
        logger.error("[Federation] handle_result_callback error: %s", e)
        raise HTTPException(status_code=500, detail=f"Internal error: {e}")


@router.get("/capabilities")
async def get_capabilities(
    x_federation_key: Optional[str] = Header(None, alias="X-Federation-Key"),
):
    """
    暴露本地可用的 agent capabilities + skill 列表。
    遠端 peer 定期拉取此端點以了解本實例的能力。
    """
    _verify_federation_key(x_federation_key)

    from runtime.federation import federation_bridge
    return {
        "instance_id": federation_bridge.instance_id,
        "capabilities": federation_bridge.local_capabilities(),
    }


@router.get("/health")
async def federation_health(
    x_federation_key: Optional[str] = Header(None, alias="X-Federation-Key"),
):
    """Federation 健康檢查。"""
    _verify_federation_key(x_federation_key)

    from runtime.federation import federation_bridge
    return {
        "status": "ok",
        "instance_id": federation_bridge.instance_id,
        "federation": federation_bridge.summary(),
    }
