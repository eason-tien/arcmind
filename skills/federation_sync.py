# -*- coding: utf-8 -*-
"""
Skill: federation_sync
同步聯邦 peer 的可用能力列表。

定期從每個 peer 拉取 /v1/federation/capabilities，
更新 FederationBridge 的本地快取，使 Delegator 能路由到遠端 Agent。

驅動方式：
  Cron interval — 每 5 分鐘執行一次
"""
from __future__ import annotations

import asyncio
import logging
import time

logger = logging.getLogger("arcmind.skill.federation_sync")


def run(inputs: dict) -> dict:
    """
    Cron entry point: 同步所有 peer 的 capabilities + health。
    """
    try:
        from config.settings import settings
        if not settings.federation_enabled:
            return {"message": "Federation disabled", "synced": 0}
    except Exception:
        return {"message": "Federation settings unavailable", "synced": 0}

    from runtime.federation import federation_bridge

    if not federation_bridge._peers:
        return {"message": "No peers configured", "synced": 0}

    results = []

    # 用 asyncio 執行異步操作
    async def _sync_all():
        for url, peer in federation_bridge._peers.items():
            t0 = time.time()
            try:
                # Health check
                healthy = await federation_bridge.health_check(url)
                if not healthy:
                    results.append({
                        "peer": url,
                        "status": "unhealthy",
                        "capabilities": [],
                    })
                    continue

                # Capabilities sync
                caps = await federation_bridge.query_capabilities(url)
                elapsed = round(time.time() - t0, 2)

                results.append({
                    "peer": url,
                    "instance_id": peer.instance_id,
                    "status": "synced",
                    "capabilities": len(caps),
                    "elapsed_s": elapsed,
                })
                logger.info("[FederationSync] Synced %s: %d capabilities (%.1fs)",
                            url, len(caps), elapsed)

            except Exception as e:
                results.append({
                    "peer": url,
                    "status": "error",
                    "error": str(e),
                })
                logger.warning("[FederationSync] Failed to sync %s: %s", url, e)

    # 嘗試在已有的 event loop 中執行
    try:
        loop = asyncio.get_running_loop()
        # 已有 loop — 創建 task（cron 在 thread 中執行，需要新 loop）
        future = asyncio.run_coroutine_threadsafe(_sync_all(), loop)
        future.result(timeout=60)
    except RuntimeError:
        # 沒有 running loop — 創建新的
        asyncio.run(_sync_all())

    synced = sum(1 for r in results if r.get("status") == "synced")
    total = len(results)

    summary = f"Synced {synced}/{total} peers"
    logger.info("[FederationSync] %s", summary)

    return {
        "message": summary,
        "synced": synced,
        "total": total,
        "peers": results,
    }
