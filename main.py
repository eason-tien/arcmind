"""
ArcMind — 入口點
啟動 FastAPI 服務，以 MGIS 為骨幹。

使用方式:
  python main.py              # 前台啟動（開發模式）
  python main.py --port 8100  # 指定 port

環境變數（.env 或 shell export）:
  MGIS_URL=http://localhost:8000
  MGIS_API_KEY=your-mgis-key
  ANTHROPIC_API_KEY=your-api-key
  ARCMIND_PORT=8100
"""
from __future__ import annotations

import argparse
import logging
import logging.handlers
import sys
from pathlib import Path

import uvicorn

from config.settings import settings

LOG_DIR = Path(__file__).parent / "logs"


def setup_logging() -> None:
    LOG_DIR.mkdir(exist_ok=True)

    fmt = "%(asctime)s [%(levelname)s] %(name)s — %(message)s"
    formatter = logging.Formatter(fmt)

    # Rotating file handler: 5 MB per file, keep 3 backups
    file_handler = logging.handlers.RotatingFileHandler(
        LOG_DIR / "arcmind.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    handlers: list[logging.Handler] = [file_handler]

    # Console handler — only when running in a real terminal (not daemon/launchd).
    # Under launchd, stdout may be redirected to the same log file, causing duplicates.
    if sys.stdout.isatty():
        console = logging.StreamHandler(sys.stdout)
        console.setFormatter(formatter)
        handlers.append(console)

    logging.basicConfig(
        level=logging.INFO,
        format=fmt,
        handlers=handlers,
    )


def main() -> None:
    setup_logging()
    logger = logging.getLogger("arcmind")

    parser = argparse.ArgumentParser(description="ArcMind Server")
    parser.add_argument("--host", default=settings.arcmind_host)
    parser.add_argument("--port", type=int, default=settings.arcmind_port)
    parser.add_argument("--reload", action="store_true",
                        help="Enable auto-reload (development)")
    args = parser.parse_args()

    logger.info("=" * 60)
    from version import __version__
    logger.info("  ArcMind v%s (Zero-Human Company)", __version__)
    logger.info("  MGIS Foundation: %s", settings.mgis_url)
    logger.info("  Listen: http://%s:%d", args.host, args.port)
    logger.info("  Gateway: WebSocket /ws + REST /v1/chat")
    logger.info("  OpenClaw: %s", "enabled" if settings.openclaw_enabled else "disabled")
    logger.info("=" * 60)

    from api.server import create_app
    app = create_app()

    # ── Startup: check for recent incidents from watchdog repair ──
    try:
        from ops.incident_logger import get_recent_incidents
        incidents = get_recent_incidents(limit=3)
        if incidents:
            logger.warning("=" * 60)
            logger.warning("  ⚠️  Recent system incidents detected:")
            for inc in incidents:
                content = inc.get("content", inc.get("cause", ""))
                logger.warning("    → %s", content[:120])
            logger.warning("  主 Agent 將嘗試後續完整修復...")
            logger.warning("=" * 60)
    except Exception:
        pass

    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
        log_config=None,  # Prevent uvicorn from adding duplicate handlers to root logger
    )


if __name__ == "__main__":
    main()
