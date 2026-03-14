"""
OpenClaw Gateway 相容層（可選接入）。
ArcMind 不依賴 OpenClaw，但若 OPENCLAW_URL 有設定，可選接入。
"""
from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from config.settings import settings

logger = logging.getLogger("arcmind.openclaw_adapter")


class OpenClawAdapter:
    """
    OpenClaw REST/WS Gateway 客戶端。
    僅在 settings.openclaw_enabled = True 時使用。
    """

    def __init__(self):
        self._base = settings.openclaw_url.rstrip("/") if settings.openclaw_url else ""
        self._enabled = settings.openclaw_enabled and bool(settings.openclaw_url)

    @property
    def enabled(self) -> bool:
        return self._enabled

    def _require_enabled(self):
        if not self._enabled:
            raise RuntimeError("OpenClaw adapter is disabled. Set OPENCLAW_URL and OPENCLAW_ENABLED=true.")

    # ── Health ────────────────────────────────────────────────────────────────

    def healthz(self) -> dict:
        self._require_enabled()
        try:
            r = httpx.get(f"{self._base}/oc/healthz", timeout=10)
            return r.json()
        except Exception as e:
            return {"error": str(e), "offline": True}

    def is_online(self) -> bool:
        if not self._enabled:
            return False
        result = self.healthz()
        return "error" not in result

    # ── Skill 呼叫 ────────────────────────────────────────────────────────────

    def invoke_skill(self, skill_name: str, inputs: dict | None = None,
                     timeout: int = 60) -> dict:
        """
        透過 OpenClaw Gateway 呼叫遠端 Skill。
        格式相容 ArcMind 本地 Skill 呼叫格式。
        """
        self._require_enabled()
        try:
            r = httpx.post(
                f"{self._base}/oc/tools/invoke",
                json={"tool": skill_name, "inputs": inputs or {}},
                timeout=timeout,
            )
            if r.status_code >= 400:
                return {"success": False, "error": r.text[:256], "output": None}
            return {**r.json(), "success": True, "source": "openclaw"}
        except Exception as e:
            logger.error("OpenClaw invoke_skill error: %s", e)
            return {"success": False, "error": str(e), "output": None}

    def list_skills(self) -> list[dict]:
        """列出 OpenClaw 上的所有 Skills"""
        self._require_enabled()
        try:
            r = httpx.get(f"{self._base}/oc/tools/list", timeout=10)
            return r.json().get("skills", [])
        except Exception as e:
            logger.warning("OpenClaw list_skills failed: %s", e)
            return []

    # ── 任務派單（相容 MGIS PDE DispatchContract）────────────────────────────

    def dispatch(self, contract: dict) -> dict:
        """
        向 OpenClaw 派送一個 DispatchContract 格式任務。
        """
        self._require_enabled()
        try:
            r = httpx.post(
                f"{self._base}/oc/dispatch",
                json=contract,
                timeout=60,
            )
            if r.status_code >= 400:
                return {"success": False, "error": r.text[:256]}
            return {**r.json(), "success": True}
        except Exception as e:
            logger.error("OpenClaw dispatch error: %s", e)
            return {"success": False, "error": str(e)}

    # ── WS Gateway（Stub，可用 websockets 庫擴充）────────────────────────────

    def ws_url(self) -> str:
        if not self._base:
            return ""
        return self._base.replace("http://", "ws://").replace("https://", "wss://") + "/gateway/ws"


# 全域單例
openclaw = OpenClawAdapter()
