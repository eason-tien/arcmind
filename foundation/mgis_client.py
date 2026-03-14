"""
MGIS Foundation Client
連接 MGIS 所有 API 能力：治理、記憶、規劃、主動需求引擎。
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any, Optional

import httpx

from config.settings import settings

logger = logging.getLogger("arcmind.mgis_client")

# Suppress repeated MGIS offline warnings — log once per interval
_MGIS_OFFLINE_LOG_INTERVAL = 300  # seconds


class MGISError(Exception):
    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"MGIS {status_code}: {detail}")


class MGISClient:
    """
    MGIS REST API 客戶端。
    涵蓋：governance, memory, planner, proactive, brain, causal, ops
    """

    def __init__(self):
        self._base = settings.mgis_url.rstrip("/")
        self._headers = {
            "Content-Type": "application/json",
        }
        if settings.mgis_api_key:
            self._headers["X-API-Key"] = settings.mgis_api_key
        if settings.mgis_admin_token:
            self._headers["Authorization"] = f"Bearer {settings.mgis_admin_token}"
        self._last_offline_log: float = 0.0

    def _log_offline(self, msg: str, *args) -> None:
        """Log MGIS unreachable at most once per interval to avoid spam."""
        now = time.monotonic()
        if now - self._last_offline_log >= _MGIS_OFFLINE_LOG_INTERVAL:
            logger.warning(msg, *args)
            self._last_offline_log = now

    # ── 底層請求 ──────────────────────────────────────────────────────────────

    def _get(self, path: str, params: dict | None = None) -> dict:
        url = f"{self._base}{path}"
        try:
            r = httpx.get(url, headers=self._headers, params=params,
                          timeout=min(settings.mgis_timeout, 30))
            if r.status_code >= 400:
                raise MGISError(r.status_code, r.text[:512])
            self._last_offline_log = 0.0  # reset on success
            try:
                return r.json()
            except (ValueError, json.JSONDecodeError):
                logger.warning("MGIS returned non-JSON response for %s", path)
                return {"error": "Invalid JSON response", "offline": True}
        except httpx.RequestError as e:
            self._log_offline("MGIS unreachable: %s", e)
            return {"error": str(e), "offline": True}

    def _post(self, path: str, body: dict) -> dict:
        url = f"{self._base}{path}"
        try:
            r = httpx.post(url, headers=self._headers, json=body,
                           timeout=min(settings.mgis_timeout, 30))
            if r.status_code >= 400:
                raise MGISError(r.status_code, r.text[:512])
            self._last_offline_log = 0.0  # reset on success
            try:
                return r.json()
            except (ValueError, json.JSONDecodeError):
                logger.warning("MGIS returned non-JSON response for %s", path)
                return {"error": "Invalid JSON response", "offline": True}
        except httpx.RequestError as e:
            self._log_offline("MGIS unreachable: %s", e)
            return {"error": str(e), "offline": True}

    # ── Health ────────────────────────────────────────────────────────────────

    def healthz(self) -> dict:
        return self._get("/healthz")

    def is_online(self) -> bool:
        result = self.healthz()
        return "error" not in result and "offline" not in result

    # ── Governance ────────────────────────────────────────────────────────────

    def audit(self, action: str, context: dict, actor: str = "arcmind") -> dict:
        """
        呼叫 MGIS Master Governor 審計一個行動。
        回傳: {approved: bool, risk_score: float, reason: str}
        """
        return self._post("/v1/governance/audit", {
            "action": action,
            "context": context,
            "actor": actor,
        })

    def governance_status(self) -> dict:
        return self._get("/v1/governance/status")

    # ── Memory (LMF) ──────────────────────────────────────────────────────────

    def memory_add(self, content: str, tags: list[str] | None = None,
                   source: str = "arcmind", metadata: dict | None = None) -> dict:
        """寫入記憶"""
        return self._post("/v1/memory/add", {
            "content": content,
            "tags": tags or [],
            "source": source,
            "metadata": metadata or {},
        })

    def memory_query(self, query: str, top_k: int = 5,
                     tags: list[str] | None = None) -> dict:
        """查詢語意相關記憶"""
        return self._post("/v1/memory/query", {
            "query": query,
            "top_k": top_k,
            "tags": tags or [],
        })

    def memory_list(self, limit: int = 20, offset: int = 0) -> dict:
        return self._get("/v1/memory/list", {"limit": limit, "offset": offset})

    # ── Planner ───────────────────────────────────────────────────────────────

    def plan(self, goal: str, context: dict | None = None,
             constraints: list[str] | None = None) -> dict:
        """
        呼叫 MGIS Goal-Driven Planner 生成 TaskGraph。
        回傳: {task_graph: [...], estimated_steps: int}
        """
        return self._post("/v1/planner/plan", {
            "goal": goal,
            "context": context or {},
            "constraints": constraints or [],
        })

    def planner_status(self) -> dict:
        return self._get("/v1/planner/status")

    # ── Proactive Engine V2 ───────────────────────────────────────────────────

    def proactive_status(self) -> dict:
        """取得主動需求引擎狀態與當前 project"""
        return self._get("/v1/proactive/status")

    def proactive_projects(self) -> dict:
        return self._get("/v1/proactive/projects")

    def proactive_project_get(self, project_id: str) -> dict:
        return self._get(f"/v1/proactive/projects/{project_id}")

    def proactive_project_create(self, name: str, description: str = "",
                                  owner: str = "arcmind") -> dict:
        return self._post("/v1/proactive/projects", {
            "name": name,
            "description": description,
            "owner": owner,
        })

    def proactive_classify(self, messages: list[dict]) -> dict:
        """分類訊息（USER_INTENT/EXEC_OUTPUT/LOG_DUMP 等）"""
        return self._post("/v1/proactive/classify", {"messages": messages})

    def proactive_daily_run(self, project_id: str,
                             messages: list[dict] | None = None) -> dict:
        """觸發每日 Tomorrow Pack 生成"""
        return self._post("/v1/proactive/daily/run", {
            "project_id": project_id,
            "messages": messages or [],
        })

    def proactive_weekly_run(self, project_id: str) -> dict:
        """觸發每週 Sprint Plan 生成"""
        return self._post("/v1/proactive/weekly/run", {
            "project_id": project_id,
        })

    def proactive_tomorrow_pack(self, project_id: str) -> dict:
        """取得最新 Tomorrow Pack"""
        return self._get(f"/v1/proactive/projects/{project_id}/tomorrow")

    # ── Brain (SharedBrain) ───────────────────────────────────────────────────

    def brain_status(self) -> dict:
        return self._get("/v1/brain/status")

    def brain_query(self, query: str, context: dict | None = None) -> dict:
        """向 SharedBrain 查詢"""
        return self._post("/v1/brain/query", {
            "query": query,
            "context": context or {},
        })

    # ── Causal ────────────────────────────────────────────────────────────────

    def causal_log(self, cause: str, effect: str, confidence: float = 1.0,
                   tags: list[str] | None = None) -> dict:
        """記錄因果關係"""
        return self._post("/v1/causal/log", {
            "cause": cause,
            "effect": effect,
            "confidence": confidence,
            "tags": tags or [],
        })

    def causal_query(self, event: str, top_k: int = 5) -> dict:
        """查詢某事件的因果"""
        return self._post("/v1/causal/query", {
            "event": event,
            "top_k": top_k,
        })

    # ── Ops / 系統 ────────────────────────────────────────────────────────────

    def system_info(self) -> dict:
        return self._get("/v1/ops/info")

    def system_version(self) -> dict:
        return self._get("/v1/ops/version")


# 全域單例
mgis = MGISClient()
