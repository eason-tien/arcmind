"""
ArcMind FastAPI 應用程式
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from config.settings import settings

logger = logging.getLogger("arcmind.server")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ──────────────────────────────────────────────────────────────
    logger.info("ArcMind starting up (port=%d)...", settings.arcmind_port)

    # DB 初始化
    from db.schema import init_db
    init_db()

    # Skill Manager 掃描
    from runtime.skill_manager import skill_manager
    skill_manager.startup()

    # Cron 排程器啟動（從 DB 恢復）
    from runtime.cron import cron_system
    cron_system.startup()

    # ── Auto-register iteration CRON jobs (if not already present) ──
    try:
        existing_jobs = {j["name"] for j in cron_system.list_jobs()}

        if "weekly-agent-meeting" not in existing_jobs:
            cron_system.add_cron(
                name="weekly-agent-meeting",
                cron_expr="0 22 * * 0",  # 每週日 22:00
                skill_name="self_iteration",
                input_data={"phase": "meeting"},
                governor_required=False,
            )
            logger.info("📅 Registered CRON: weekly-agent-meeting (Sun 22:00)")

        if "iteration-daily-check" not in existing_jobs:
            cron_system.add_cron(
                name="iteration-daily-check",
                cron_expr="0 9 * * 1-5",  # 週一到週五 09:00
                skill_name="self_iteration",
                input_data={"phase": "daily_check"},
                governor_required=False,
            )
            logger.info("📅 Registered CRON: iteration-daily-check (Mon-Fri 09:00)")

        if "daily-morning-report" not in existing_jobs:
            cron_system.add_cron(
                name="daily-morning-report",
                cron_expr="0 6 * * *",  # 每天 06:00
                skill_name="daily_report",
                input_data={"action": "report"},
                governor_required=False,
            )
            logger.info("📅 Registered CRON: daily-morning-report (Daily 06:00)")

        if "env-scan" not in existing_jobs:
            cron_system.add_cron(
                name="env-scan",
                cron_expr="0 */12 * * *",  # 每 12 小時
                skill_name="env_discovery",
                input_data={"action": "full_scan"},
                governor_required=False,
            )
            logger.info("📅 Registered CRON: env-scan (Every 12h)")
    except Exception as e:
        logger.warning("Failed to register iteration CRONs: %s", e)

    # Gateway session manager (log active sessions on startup)
    from gateway.session_manager import session_manager
    logger.info("ArcMind Gateway ready. MGIS=%s, Sessions=%d",
                settings.mgis_url, session_manager.active_count())

    # ── Channel Supervisor: 同步啟動所有通道（像 OpenClaw 一樣） ──
    from channels.supervisor import ChannelSupervisor
    supervisor = ChannelSupervisor()

    # Telegram Channel（從 settings/env 讀取 token）
    if settings.telegram_bot_token:
        try:
            from channels.telegram import TelegramChannel
            tg = TelegramChannel(
                token=settings.telegram_bot_token,
                chat_id=settings.telegram_chat_id,
            )
            supervisor.register(tg)
            logger.info("📱 Telegram channel registered (chat_id=%s)",
                        settings.telegram_chat_id or "any")
        except Exception as e:
            logger.warning("Telegram channel failed to register: %s", e)

    # 啟動 Supervisor（背景 asyncio task — 不會 block）
    import asyncio

    async def _run_supervisor():
        try:
            await supervisor.start_all()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("Channel Supervisor error: %s", e)

    supervisor_task = asyncio.create_task(_run_supervisor(), name="channel_supervisor")
    app.state.channel_supervisor = supervisor
    app.state.supervisor_task = supervisor_task
    logger.info("🔗 Channel Supervisor started (%d channels)", len(supervisor._channels))

    yield

    # ── Shutdown ─────────────────────────────────────────────────────────────
    logger.info("ArcMind shutting down...")

    # 停止 Channel Supervisor
    supervisor._shutdown_event.set()  # Signal supervisor to stop
    supervisor_task.cancel()
    try:
        await supervisor_task
    except asyncio.CancelledError:
        pass
    logger.info("✅ Channel Supervisor stopped")

    cron_system.shutdown()


def create_app() -> FastAPI:
    app = FastAPI(
        title="ArcMind",
        description="MGIS-based Autonomous Intelligence System",
        version="0.2.0",
        lifespan=lifespan,
    )

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Health (lightweight for watchdog) ──────────────────────────────────
    @app.get("/health")
    def health():
        return {"status": "ok"}

    # ── Healthz ──────────────────────────────────────────────────────────────
    @app.get("/healthz")
    def healthz():
        from foundation.mgis_client import mgis
        from runtime.skill_manager import skill_manager
        from runtime.lifecycle import lifecycle
        from runtime.cron import cron_system

        from runtime.model_router import model_router
        mgis_online = mgis.is_online()
        return {
            "status": "ok",
            "version": "0.2.0",
            "mgis_online": mgis_online,
            "mgis_url": settings.mgis_url,
            "skills_loaded": len(skill_manager.list_skills()),
            "cron_jobs": len(cron_system.list_jobs()),
            "lifecycle": lifecycle.summary(),
            "openclaw_enabled": settings.openclaw_enabled,
            "ai_providers": model_router.list_providers(),
        }

    @app.get("/mgis/status")
    def mgis_status():
        from foundation.mgis_client import mgis
        return {
            "online": mgis.is_online(),
            "healthz": mgis.healthz(),
            "version": mgis.system_version(),
        }

    @app.get("/v1/models")
    def list_models():
        """列出所有可用 AI Provider 與建議模型"""
        from runtime.model_router import model_router
        providers = model_router.list_providers()
        # 每個 provider 的建議模型清單
        recommended = {
            "anthropic": [
                "anthropic:claude-opus-4-6",
                "anthropic:claude-sonnet-4-6",
                "anthropic:claude-haiku-4-5-20251001",
            ],
            "openai": ["openai:gpt-4o", "openai:gpt-4o-mini", "openai:o1"],
            "google": [
                "google:gemini-2.0-flash",
                "google:gemini-2.0-flash-lite",
                "google:gemini-1.5-pro",
            ],
            "groq": [
                "groq:llama-3.3-70b-versatile",
                "groq:llama-3.1-8b-instant",
                "groq:mixtral-8x7b-32768",
            ],
            "mistral": [
                "mistral:mistral-large-latest",
                "mistral:mistral-small-latest",
                "mistral:codestral-latest",
            ],
            "ollama": [
                f"ollama:{settings.ollama_default_model}",
                "ollama:llama3.2",
                "ollama:qwen2.5:7b",
                "ollama:deepseek-r1:7b",
                "ollama:phi4",
            ],
        }
        return {
            "available_providers": providers,
            "recommended_models": {
                p["provider"]: recommended.get(p["provider"], [])
                for p in providers
            },
        }

    # ── Routers ───────────────────────────────────────────────────────────────
    from api.routes.agent_routes import router as agent_router
    from api.routes.skill_routes import router as skill_router
    from api.routes.cron_routes import router as cron_router
    from api.routes.session_routes import router as session_router
    from api.routes.github_routes import router as github_router

    app.include_router(agent_router, prefix="/v1/agent", tags=["agent"])
    app.include_router(skill_router, prefix="/v1/skills", tags=["skills"])
    app.include_router(cron_router,  prefix="/v1/cron",   tags=["cron"])
    app.include_router(session_router, prefix="/v1",      tags=["sessions"])
    app.include_router(github_router, prefix="/v1/github", tags=["github"])

    # ── Gateway (WebSocket + Chat) ────────────────────────────────────────
    from gateway.server import router as gateway_router
    app.include_router(gateway_router, tags=["gateway"])

    # ── Voice WebSocket ───────────────────────────────────────────────────
    try:
        from channels.voice_ws import router as voice_ws_router
        app.include_router(voice_ws_router, tags=["voice"])
        logger.info("[App] Voice WebSocket endpoint registered: /ws/voice")
    except ImportError as e:
        logger.warning("[App] Voice WebSocket not available: %s", e)

    # ── Global error handler ──────────────────────────────────────────────────
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        logger.exception("Unhandled error: %s", exc)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"error": str(exc)},
        )

    return app
