"""
ArcMind FastAPI 應用程式
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import hmac

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from config.settings import settings
from version import __version__ as _arcmind_version

logger = logging.getLogger("arcmind.server")

# ── Lifespan Guard ──────────────────────────────────────────────────────────
# uvicorn 可能觸發多次 lifespan（reload mode、worker mode、或 app instance 衝突）。
# 只允許第一次 lifespan 執行 startup/shutdown 邏輯，
# 後續重複調用直接 yield 不做任何事，避免全局 singleton 被錯殺。
_lifespan_active = False


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _lifespan_active

    if _lifespan_active:
        logger.warning("⚠️ Duplicate lifespan detected — skipping startup/shutdown to protect global singletons")
        yield
        return

    _lifespan_active = True

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

        # V3: Approval Gate sweep — DISABLED (not needed in v0.9.3)
        # if "approval-gate-sweep" not in existing_jobs:
        #     cron_system.add_interval(
        #         name="approval-gate-sweep",
        #         seconds=300,
        #         skill_name="approval_gate_sweep",
        #         input_data={},
        #         governor_required=False,
        #     )

        # Worker Heartbeat — DISABLED (event-driven, no polling needed)
        # if "worker-heartbeat" not in existing_jobs:
        #     cron_system.add_interval(
        #         name="worker-heartbeat",
        #         seconds=300,
        #         skill_name="worker_heartbeat",
        #         input_data={},
        #         governor_required=False,
        #     )

        # P4-2: Memory Compressor — daily compress episodic → semantic
        if "memory-compress" not in existing_jobs:
            cron_system.add_cron(
                name="memory-compress",
                cron_expr="0 3 * * *",  # 每天 03:00
                skill_name="memory_compress",
                input_data={"days_old": 7, "max_batch": 50},
                governor_required=False,
            )
            logger.info("📅 Registered CRON: memory-compress (Daily 03:00)")

    except Exception as e:
        logger.warning("Failed to register iteration CRONs: %s", e)

    # ── V3: Governance 初始化 ──
    try:
        from runtime.policy_engine import policy_engine
        policy_engine.seed_defaults()
        logger.info("🛡️ V3 PolicyEngine initialized (default rules seeded)")
    except Exception as e:
        logger.warning("V3 PolicyEngine init failed (non-fatal): %s", e)

    # ── EventBus 啟動 (Event-Driven 混合驅動) ──
    from runtime.event_bus import event_bus
    import loop.event_handlers  # Ensure decorators run and handlers are registered
    try:
        import runtime.event_handlers  # V3: Register SYSTEM_EVENT/IAMP handlers
    except ImportError:
        pass
    await event_bus.start()
    logger.info("⚡ EventBus started (event-driven hybrid mode)")

    # ── PM Agent: Register progress notifier for Telegram push ──
    try:
        from runtime.progress_notifier import progress_notifier
        progress_notifier.register()
        logger.info("📢 PM ProgressNotifier registered")
    except Exception as e:
        logger.warning("PM ProgressNotifier registration failed: %s", e)

    # Gateway session manager (log active sessions on startup)
    from gateway.session_manager import session_manager
    logger.info("ArcMind Gateway ready. MGIS=%s, Sessions=%d",
                settings.mgis_url, session_manager.active_count())

    # ── Channel Supervisor: 同步啟動所有通道（像 OpenClaw 一樣） ──
    from channels.supervisor import channel_supervisor as supervisor

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


    # ── Federation Bridge: 跨實例協作 ──
    if settings.federation_enabled:
        from runtime.federation import federation_bridge
        federation_bridge.startup()

        # 註冊 federation-sync cron
        try:
            if "federation-sync" not in existing_jobs:
                cron_system.add_interval(
                    name="federation-sync",
                    seconds=300,  # 每 5 分鐘同步 peer capabilities
                    skill_name="federation_sync",
                    input_data={},
                    governor_required=False,
                )
                logger.info("📅 Registered CRON: federation-sync (Every 300s)")
        except Exception as e:
            logger.warning("Failed to register federation-sync cron: %s", e)

        logger.info("🔗 Federation enabled (instance=%s, peers=%d)",
                     settings.federation_instance_id, len(federation_bridge._peers))

    # ── P3: MCP Server session manager ──
    _mcp_session_ctx = None
    try:
        from gateway.mcp_server import create_mcp_server
        _mcp_srv = create_mcp_server()
        if _mcp_srv is not None:
            _mcp_session_ctx = _mcp_srv.session_manager.run()
            await _mcp_session_ctx.__aenter__()
            app.state.mcp_server = _mcp_srv
            logger.info("🔌 MCP Server session manager started")
    except Exception as e:
        logger.warning("MCP Server startup failed (non-fatal): %s", e)

    yield

    # ── P3: MCP Server session manager shutdown ──
    if _mcp_session_ctx is not None:
        try:
            await _mcp_session_ctx.__aexit__(None, None, None)
            logger.info("🔌 MCP Server session manager stopped")
        except Exception:
            pass

    # ── Shutdown ─────────────────────────────────────────────────────────────
    logger.info("ArcMind shutting down...")


    # 停止 EventBus
    await event_bus.stop()
    logger.info("EventBus stopped")

    # 停止 Channel Supervisor
    supervisor._shutdown_event.set()  # Signal supervisor to stop
    supervisor_task.cancel()
    try:
        await supervisor_task
    except asyncio.CancelledError:
        pass
    logger.info("✅ Channel Supervisor stopped")

    cron_system.shutdown()

    # Graceful session manager shutdown
    session_manager.stop()
    logger.info("✅ Session manager stopped")

    _lifespan_active = False


def create_app() -> FastAPI:
    app = FastAPI(
        title="ArcMind",
        description="MGIS-based Autonomous Intelligence System",
        version=_arcmind_version,
        lifespan=lifespan,
    )

    # CORS — restrict to configured origins (default: localhost only)
    cors_origins = settings.cors_allowed_origins if hasattr(settings, 'cors_allowed_origins') and settings.cors_allowed_origins else [
        "http://localhost:8100",
        "http://localhost:5173",
        "http://127.0.0.1:8100",
        "http://127.0.0.1:5173",
    ]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization", "X-Session-ID"],
    )

    # ── API Key Authentication Middleware ────────────────────────────────
    _PUBLIC_PATHS = {"/health", "/healthz", "/docs", "/openapi.json", "/redoc"}

    class APIKeyAuthMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            path = request.url.path
            # Allow public endpoints, static UI, webhook, and federation endpoints without main API key auth
            # (federation routes use their own X-Federation-Key authentication)
            if (path in _PUBLIC_PATHS
                    or path.startswith("/ui")
                    or path.startswith("/v1/webhooks")
                    or path.startswith("/v1/federation")):
                return await call_next(request)

            # Check Authorization header or X-API-Key header
            api_key = settings.arcmind_api_key
            if not api_key:
                # Fail-closed: no API key configured = reject all non-public requests
                if settings.arcmind_env == "production":
                    return JSONResponse(
                        status_code=503,
                        content={"detail": "ARCMIND_API_KEY not configured. Server refusing requests in production mode."},
                    )
                # In development, warn but allow (logged)
                logger.warning("[Auth] No API key configured — allowing request in dev mode. Set ARCMIND_API_KEY for production.")
                return await call_next(request)

            auth_header = request.headers.get("Authorization", "")
            x_api_key = request.headers.get("X-API-Key", "")
            token = ""
            if auth_header.startswith("Bearer "):
                token = auth_header[7:]
            elif x_api_key:
                token = x_api_key

            if not token or not hmac.compare_digest(token, api_key):
                return JSONResponse(
                    status_code=401,
                    content={"detail": "Invalid or missing API key. Set Authorization: Bearer <key> or X-API-Key header."},
                )
            return await call_next(request)

    app.add_middleware(APIKeyAuthMiddleware)

    # ── Health (lightweight for watchdog) ──────────────────────────────────
    @app.get("/api/tasks/active")
    async def get_active_tasks(session_id: int = None):
        """Get active PM tasks."""
        from runtime.task_tracker import task_tracker
        if session_id:
            tasks = task_tracker.get_active_for_session(session_id)
        else:
            tasks = task_tracker.get_all_active()
        return {
            "tasks": [
                {
                    "task_id": t.task_id,
                    "command": t.command[:80],
                    "status": t.status.value,
                    "progress": t.progress_pct,
                    "steps": len(t.steps),
                    "current_step": t.current_step,
                }
                for t in tasks
            ]
        }

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
        from runtime.event_bus import event_bus as _eb

        # Governance stats (non-fatal)
        _gov_stats = {}
        try:
            from runtime.approval_gate import approval_gate
            _gov_stats = {
                "pending_approvals": len(approval_gate.get_pending()),
            }
        except Exception:
            _gov_stats = {"error": "governance not available"}

        return {
            "status": "ok",
            "version": _arcmind_version,
            "mgis_online": mgis_online,
            "mgis_url": settings.mgis_url,
            "skills_loaded": len(skill_manager.list_skills()),
            "cron_jobs": len(cron_system.list_jobs()),
            "lifecycle": lifecycle.summary(),
            "openclaw_enabled": settings.openclaw_enabled,
            "ai_providers": model_router.list_providers(),
            "event_bus": _eb.stats(),
            "federation": _get_federation_summary(),
            "governance_v3": _gov_stats,
        }

    def _get_federation_summary():
        if not settings.federation_enabled:
            return {"enabled": False}
        try:
            from runtime.federation import federation_bridge
            return federation_bridge.summary()
        except Exception:
            return {"enabled": True, "error": "not initialized"}

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
                "anthropic:claude-3-7-sonnet-20250219",
                "anthropic:claude-sonnet-4-6",
                "anthropic:claude-haiku-4-5-20251001",
            ],
            "openai": ["openai:gpt-4o", "openai:o3-mini", "openai:o1"],
            "google": [
                "google:gemini-2.0-flash",
                "google:gemini-2.5-flash",
                "google:gemini-1.5-pro",
            ],
            "deepseek": ["deepseek:deepseek-chat", "deepseek:deepseek-reasoner"],
            "xai": ["xai:grok-3", "xai:grok-3-mini"],
            "groq": [
                "groq:llama-3.3-70b-versatile",
                "groq:llama-3.1-8b-instant",
            ],
            "mistral": [
                "mistral:mistral-large-latest",
                "mistral:codestral-latest",
            ],
            "minimax": ["minimax:MiniMax-M2.5"],
            "moonshot": ["moonshot:moonshot-v1-auto"],
            "zhipu": ["zhipu:glm-4-plus"],
            "siliconflow": ["siliconflow:Qwen/Qwen2.5-72B-Instruct"],
            "openrouter": ["openrouter:auto"],
            "ollama": [
                f"ollama:{settings.ollama_default_model}",
                "ollama:llama3.2",
                "ollama:qwen2.5:7b",
                "ollama:deepseek-r1:7b",
            ],
            "ollama_remote": [
                f"ollama_remote:{settings.ollama_remote_default_model}",
            ],
        }
        return {
            "available_providers": providers,
            "recommended_models": {
                p["provider"]: recommended.get(p["provider"], [])
                for p in providers
            },
            "default_model": model_router._rules.default
        }

    from pydantic import BaseModel

    class DefaultModelReq(BaseModel):
        model: str

    @app.post("/v1/models/default")
    def set_default_model(req: DefaultModelReq):
        from runtime.model_router import model_router
        import yaml
        
        path = settings.routing_rules_path
        try:
            with open(path, "r") as f:
                data = yaml.safe_load(f) or {}
        except Exception:
            data = {}
            
        data["default"] = req.model
        with open(path, "w") as f:
            yaml.dump(data, f, sort_keys=False, allow_unicode=True)
            
        # reload the rules in memory
        model_router._rules.default = req.model
        return {"status": "ok", "default_model": req.model}

    # ── Routers ───────────────────────────────────────────────────────────────
    from api.routes.agent_routes import router as agent_router
    from api.routes.skill_routes import router as skill_router
    from api.routes.cron_routes import router as cron_router
    from api.routes.session_routes import router as session_router
    from api.routes.github_routes import router as github_router
    from api.routes.webhook_routes import router as webhook_router
    from api.routes.heartbeat_routes import router as heartbeat_router
    from api.routes.iteration_routes import router as iteration_router

    app.include_router(agent_router, prefix="/v1/agent", tags=["agent"])
    app.include_router(skill_router, prefix="/v1/skills", tags=["skills"])
    app.include_router(cron_router,  prefix="/v1/cron",   tags=["cron"])
    app.include_router(session_router, prefix="/v1",      tags=["sessions"])
    app.include_router(github_router, prefix="/v1/github", tags=["github"])
    app.include_router(webhook_router, prefix="/v1/webhook", tags=["webhook"])
    app.include_router(heartbeat_router, tags=["heartbeat"])
    app.include_router(iteration_router, prefix="/v1", tags=["iterations"])

    # ── Project Management (V2 Phase 1) ─────────────────────────────────
    try:
        from api.routes.project_routes import router as project_router
        app.include_router(project_router, tags=["projects"])
        logger.info("[App] Project routes registered")
    except ImportError:
        logger.debug("[App] Project routes not available")

    # V2 Phase 2: Escalation routes
    try:
        from api.routes.escalation_routes import router as escalation_router
        app.include_router(escalation_router, tags=["escalation"])
        logger.info("[App] Escalation routes registered")
    except ImportError:
        pass

    # V3: Governance routes (policies, approvals, audit, releases, knowledge graph)
    try:
        from api.routes.governance_routes import router as governance_router
        app.include_router(governance_router, tags=["governance"])
        logger.info("[App] V3 Governance routes registered at /v1/governance")
    except ImportError:
        logger.debug("[App] V3 Governance routes not available")

    # ── Federation (ArcMind ↔ ArcMind 跨實例協作) ────────────────────────
    if settings.federation_enabled:
        from api.routes.federation_routes import router as federation_router
        app.include_router(federation_router, prefix="/v1/federation", tags=["federation"])
        logger.info("[App] Federation routes registered at /v1/federation")

    # ── P3: MCP Server (對外暴露工具) ──────────────────────────────────────
    try:
        _mcp_srv = getattr(app.state, 'mcp_server', None)
        if _mcp_srv is not None:
            _mcp_srv.settings.streamable_http_path = "/"
            app.mount("/mcp", _mcp_srv.streamable_http_app())
            logger.info("🔌 MCP Server mounted at /mcp")
    except Exception as e:
        logger.warning("Failed to mount MCP Server (non-fatal): %s", e)

    # ── P3: A2A Agent Card ──────────────────────────────────────────────────
    @app.get("/.well-known/agent.json", include_in_schema=False)
    def a2a_agent_card():
        """A2A Protocol Agent Card for agent discovery."""
        from gateway.mcp_server import get_agent_card
        host = getattr(settings, 'arcmind_host', 'localhost')
        port = getattr(settings, 'arcmind_port', 8000)
        return get_agent_card(host=host, port=port)

    # ── P4-1: A2A Task Endpoint (JSON-RPC) ────────────────────────────────
    @app.post("/a2a", include_in_schema=False)
    async def a2a_task_endpoint(request: Request):
        """
        A2A Protocol tasks/send endpoint.
        Accepts JSON-RPC 2.0 requests and routes to ArcMind's OODA loop.
        """
        import uuid as _uuid
        try:
            body = await request.json()
            method = body.get("method", "")
            params = body.get("params", {})
            rpc_id = body.get("id", str(_uuid.uuid4()))

            if method == "tasks/send":
                message_text = ""
                # Extract text from A2A message parts
                a2a_message = params.get("message", {})
                for part in a2a_message.get("parts", []):
                    if part.get("type") == "text":
                        message_text += part.get("text", "")

                if not message_text:
                    return JSONResponse(content={
                        "jsonrpc": "2.0",
                        "id": rpc_id,
                        "error": {"code": -32602, "message": "No text content in message parts"},
                    })

                # Route through standard pipeline
                from gateway.router import InboundMessage
                from gateway.server import process_message
                task_id = params.get("id") or str(_uuid.uuid4())
                msg = InboundMessage.from_api(
                    command=message_text,
                    user_id="a2a_agent",
                    session_id=f"a2a_{task_id[:12]}",
                )
                response = await process_message(msg)

                return JSONResponse(content={
                    "jsonrpc": "2.0",
                    "id": rpc_id,
                    "result": {
                        "id": task_id,
                        "status": {"state": "completed"},
                        "artifacts": [{
                            "parts": [{"type": "text", "text": response.text}],
                        }],
                    },
                })

            elif method == "tasks/get":
                return JSONResponse(content={
                    "jsonrpc": "2.0",
                    "id": rpc_id,
                    "error": {"code": -32601, "message": "tasks/get not yet implemented"},
                })

            else:
                return JSONResponse(content={
                    "jsonrpc": "2.0",
                    "id": rpc_id,
                    "error": {"code": -32601, "message": f"Method '{method}' not found"},
                })

        except Exception as e:
            logger.exception("[A2A] error: %s", e)
            return JSONResponse(content={
                "jsonrpc": "2.0",
                "id": "error",
                "error": {"code": -32603, "message": str(e)},
            })

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

    # ── Web UI (React Frontend) ───────────────────────────────────────────
    import os
    from fastapi.staticfiles import StaticFiles
    from fastapi.responses import FileResponse
    
    ui_dist_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "ui", "dist")
    if os.path.exists(ui_dist_path):
        app.mount("/ui/assets", StaticFiles(directory=os.path.join(ui_dist_path, "assets")), name="ui_assets")
        
        @app.get("/ui", include_in_schema=False)
        @app.get("/ui/{catchall:path}", include_in_schema=False)
        def serve_ui(catchall: str = ""):
            # SPA routing fallback — with path traversal protection
            if catchall:
                file_path = os.path.normpath(os.path.join(ui_dist_path, catchall))
                # Ensure resolved path stays within ui_dist_path
                if not file_path.startswith(os.path.normpath(ui_dist_path)):
                    return JSONResponse(status_code=403, content={"error": "Forbidden"})
                if os.path.exists(file_path) and os.path.isfile(file_path):
                    return FileResponse(file_path)
            return FileResponse(os.path.join(ui_dist_path, "index.html"))
            
        logger.info("[App] Web UI registered at /ui")
    else:
        logger.warning("[App] Web UI dist folder not found at %s. Did you run 'npm run build'?", ui_dist_path)

    # ── Global error handler ──────────────────────────────────────────────────
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        logger.exception("Unhandled error: %s", exc)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"error": "Internal server error"},
        )

    return app
