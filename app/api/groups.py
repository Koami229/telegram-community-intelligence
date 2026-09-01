"""
Groups API — add, list, and inspect monitored Telegram groups.
"""
from __future__ import annotations

import logging
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db_session
from app.db.repositories.repos import get_all_groups, get_group_by_id
from app.schemas.group import GroupAddRequest, GroupResponse
from app.services.group_service import (
    GroupAccessError,
    GroupResolutionError,
    resolve_and_save_group,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/groups", tags=["Groups"])


# ── POST /api/groups ──────────────────────────────────────────────────────────

@router.post(
    "",
    response_model=GroupResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add a Telegram group to monitor",
)
async def add_group(
    payload: GroupAddRequest,
    session: AsyncSession = Depends(get_db_session),
) -> GroupResponse:
    """
    Resolve a Telegram group by identifier and register it for monitoring.

    Accepted ``identifier`` formats:
    - ``@username``
    - ``https://t.me/username``
    - ``https://t.me/joinchat/...`` (if already a member)
    - Numeric Telegram group ID (e.g. ``-1001234567890``)

    Returns the persisted group record.  If the group already exists,
    the existing record is updated and returned (idempotent).
    """
    try:
        group, created = await resolve_and_save_group(session, payload.identifier)
        await session.commit()
    except GroupAccessError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        )
    except GroupResolutionError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )

    action = "registered" if created else "already registered (updated)"
    logger.info("Group %s — %s", group.telegram_group_id, action)

    # Notify the monitoring worker about the new group
    if created:
        from app.workers.monitoring import monitoring_worker
        monitoring_worker.add_group(group.telegram_group_id)

    return GroupResponse.model_validate(group)


# ── GET /api/groups ───────────────────────────────────────────────────────────

@router.get(
    "",
    response_model=List[GroupResponse],
    summary="List all monitored groups",
)
async def list_groups(
    session: AsyncSession = Depends(get_db_session),
) -> List[GroupResponse]:
    """Return all active groups registered for monitoring."""
    groups = await get_all_groups(session)
    return [GroupResponse.model_validate(g) for g in groups]


# ── GET /api/groups/{id} ──────────────────────────────────────────────────────

@router.get(
    "/{group_id}",
    response_model=GroupResponse,
    summary="Get group details",
)
async def get_group(
    group_id: int,
    session: AsyncSession = Depends(get_db_session),
) -> GroupResponse:
    """Return details for a single monitored group."""
    group = await get_group_by_id(session, group_id)
    if group is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Group id={group_id} not found",
        )
    return GroupResponse.model_validate(group)
