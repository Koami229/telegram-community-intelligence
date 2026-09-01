"""
FastAPI application — entry point.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.groups import router as groups_router
from app.api.health import router as health_router
from app.api.members import router as members_router
from app.api.sync import router as sync_router
from app.core.config import get_settings
from app.db.database import check_db_connection
from app.telegram.client import telegram_service
from app.workers.monitoring import monitoring_worker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)
settings = get_settings()


# ─────────────────────────────────────────────────────────────────────────────
# Lifespan
# ─────────────────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Startup / shutdown hooks."""
    logger.info("Starting Telegram Community Intelligence backend…")

    # Database ping
    db_ok = await check_db_connection()
    if db_ok:
        logger.info("✓ Database connection successful")
    else:
        logger.warning("✗ Database not reachable — check DATABASE_URL")

    # Telegram (non-blocking — app starts even if Telegram is not yet authed)
    tg_ok = await telegram_service.connect()
    if tg_ok:
        logger.info("✓ Telegram connection successful")
        await monitoring_worker.start()
    else:
        logger.info("  Telegram not connected (run auth script to authenticate)")

    logger.info("✓ Application ready — listening on %s:%s", settings.host, settings.port)

    yield  # ← application runs here

    # Shutdown
    await monitoring_worker.stop()
    await telegram_service.disconnect()
    logger.info("Application shutdown complete.")


# ─────────────────────────────────────────────────────────────────────────────
# App factory
# ─────────────────────────────────────────────────────────────────────────────

def create_app() -> FastAPI:
    app = FastAPI(
        title="Telegram Community Intelligence",
        description="Monitor and analyse Telegram groups you have legitimate access to.",
        version="0.1.0",
        lifespan=lifespan,
    )

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Routers
    app.include_router(health_router)
    app.include_router(groups_router)
    app.include_router(members_router)
    app.include_router(sync_router)

    return app


app = create_app()


# ── Version bump ──────────────────────────────────────────────────────────────
VERSION = "0.2.0"
