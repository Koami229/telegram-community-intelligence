"""
Health and status endpoints.
"""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from app.db.database import check_db_connection
from app.telegram.client import telegram_service
from app.core.version import APP_VERSION

router = APIRouter(tags=["Health"])


# ─────────────────────────────────────────────────────────────────────────────
# Response schemas
# ─────────────────────────────────────────────────────────────────────────────

class HealthResponse(BaseModel):
    status: str
    database: str
    telegram: str


class StatusResponse(BaseModel):
    status: str
    version: str
    telegram_configured: bool
    telegram_connected: bool
    telegram_authorized: bool


class ReadinessResponse(BaseModel):
    status: str
    database: str
    telegram: str


# ─────────────────────────────────────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/health", response_model=HealthResponse, summary="Basic health check")
async def health() -> HealthResponse:
    """
    Returns the current health status of the application.

    * ``database`` — whether PostgreSQL is reachable.
    * ``telegram`` — whether the Telethon session is connected and authorised.

    Always returns HTTP 200 so orchestrators (Docker, k8s) only use this for
    liveness.  Use ``/api/status`` for detailed readiness information.
    """
    db_status = "connected" if await check_db_connection() else "disconnected"

    if telegram_service.is_connected() and await telegram_service.is_authorized():
        tg_status = "connected"
    elif telegram_service.is_connected():
        tg_status = "connected_not_authorized"
    else:
        tg_status = "disconnected"

    return HealthResponse(
        status="ok",
        database=db_status,
        telegram=tg_status,
    )


@router.get("/api/status", response_model=StatusResponse, summary="Detailed application status")
async def api_status() -> StatusResponse:
    """
    Returns detailed information about the application state.
    Never returns secrets or credentials.
    """
    from app.core.config import get_settings
    cfg = get_settings()

    return StatusResponse(
        status="ok",
        version=APP_VERSION,
        telegram_configured=cfg.telegram_configured,
        telegram_connected=telegram_service.is_connected(),
        telegram_authorized=await telegram_service.is_authorized(),
    )


@router.get("/ready", response_model=ReadinessResponse, summary="Readiness check")
async def readiness() -> ReadinessResponse:
    """Report whether required dependencies are ready for data operations."""
    database_ready = await check_db_connection()
    telegram_ready = (
        telegram_service.is_connected()
        and await telegram_service.is_authorized()
    )
    return ReadinessResponse(
        status="ready" if database_ready and telegram_ready else "not_ready",
        database="connected" if database_ready else "disconnected",
        telegram="connected" if telegram_ready else "disconnected",
    )
