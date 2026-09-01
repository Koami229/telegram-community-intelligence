"""
Health and status endpoints.
"""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from app.db.database import check_db_connection
from app.telegram.client import telegram_service

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
        version="0.1.0",
        telegram_configured=cfg.telegram_configured,
        telegram_connected=telegram_service.is_connected(),
        telegram_authorized=await telegram_service.is_authorized(),
    )
