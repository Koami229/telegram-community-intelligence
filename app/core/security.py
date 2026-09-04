"""Shared API security dependencies."""
from __future__ import annotations

import secrets

from fastapi import Header, HTTPException, status

from app.core.config import get_settings


async def require_ingestion_key(
    x_api_key: str | None = Header(default=None),
) -> None:
    """Require an explicitly configured API key for data operations."""
    expected = get_settings().ingestion_api_key
    if not expected or not x_api_key or not secrets.compare_digest(x_api_key, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Valid X-API-Key required",
        )