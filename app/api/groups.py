"""
Groups API — add, list, and inspect monitored Telegram groups.
"""
from __future__ import annotations

import logging
from typing import List

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db_session
from app.db.repositories.repos import (
    get_all_groups,
    get_group_by_id,
    get_authorization_audits,
    create_authorization_audit,
    set_collection_authorization,
)
from app.schemas.group import GroupAddRequest, GroupResponse
from app.schemas.authorization import (
    AuthorizationAuditResponse,
    CollectionAuthorizationRequest,
)
from app.core.security import require_ingestion_key
from app.services.group_service import (
    GroupAccessError,
    GroupResolutionError,
    resolve_and_save_group,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/groups",
    tags=["Groups"],
    dependencies=[Depends(require_ingestion_key)],
)


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
        group, created = await resolve_and_save_group(
            session,
            payload.identifier,
            collection_authorized=payload.collection_authorized,
            media_download_authorized=payload.media_download_authorized,
        )
        await session.commit()
    except GroupAccessError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        )
    except GroupResolutionError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
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


@router.post(
    "/{group_id}/authorization",
    response_model=GroupResponse,
    summary="Record collection authorization for a group",
)
async def authorize_group_collection(
    group_id: int,
    payload: CollectionAuthorizationRequest,
    x_actor_label: str | None = Header(default=None),
    session: AsyncSession = Depends(get_db_session),
) -> GroupResponse:
    """Record or revoke the local collection authorization decision."""
    group = await set_collection_authorization(
        session,
        group_id,
        authorized=payload.confirmed,
        media_download_authorized=payload.media_download_confirmed,
    )
    if group is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Group id={group_id} not found",
        )
    actor_label = (x_actor_label or "unknown")[:255]
    await create_authorization_audit(
        session,
        group_id=group_id,
        collection_authorized=group.collection_authorized,
        media_download_authorized=group.media_download_authorized,
        actor_label=actor_label,
        reason=payload.reason,
    )
    await session.commit()
    return GroupResponse.model_validate(group)


@router.get(
    "/{group_id}/authorization/audit",
    response_model=list[AuthorizationAuditResponse],
    summary="List authorization audit records",
)
async def list_authorization_audit(
    group_id: int,
    limit: int = Query(default=100, ge=1, le=500),
    session: AsyncSession = Depends(get_db_session),
) -> list[AuthorizationAuditResponse]:
    if await get_group_by_id(session, group_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group not found")
    records = await get_authorization_audits(session, group_id=group_id, limit=limit)
    return [AuthorizationAuditResponse.model_validate(record) for record in records]
