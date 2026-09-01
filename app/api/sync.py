"""
Sync API — start and monitor member synchronisation jobs.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db_session
from app.db.repositories.repos import get_group_by_id, get_latest_sync_job
from app.schemas.sync import SyncJobResponse, SyncStartResponse
from app.services.sync_service import get_sync_status, start_sync
from app.models.models import SyncStatus

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/groups", tags=["Sync"])


# ── POST /api/groups/{id}/sync ────────────────────────────────────────────────

@router.post(
    "/{group_id}/sync",
    response_model=SyncStartResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start or resume member synchronisation",
)
async def trigger_sync(
    group_id: int,
    session: AsyncSession = Depends(get_db_session),
) -> SyncStartResponse:
    """
    Launch a background sync job to fetch all accessible members of the group.

    - Returns **202 Accepted** immediately with a ``job_id``.
    - If a sync is already running, returns the existing job.
    - A previously interrupted sync will resume from its last checkpoint.
    - Poll ``GET /api/groups/{id}/sync/status`` to track progress.
    """
    group = await get_group_by_id(session, group_id)
    if group is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Group id={group_id} not found",
        )

    try:
        job_id = await start_sync(group_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )

    # Fetch the fresh job record for the response
    latest = await get_latest_sync_job(session, group_id)
    job_status = latest.status if latest else SyncStatus.PENDING
    already_running = latest and latest.id == job_id and job_status == SyncStatus.RUNNING

    return SyncStartResponse(
        job_id=job_id,
        group_id=group_id,
        status=job_status,
        message=(
            "Sync already in progress"
            if already_running
            else "Sync started in background"
        ),
    )


# ── GET /api/groups/{id}/sync/status ─────────────────────────────────────────

@router.get(
    "/{group_id}/sync/status",
    response_model=SyncJobResponse,
    summary="Get latest sync job status",
)
async def sync_status(
    group_id: int,
    session: AsyncSession = Depends(get_db_session),
) -> SyncJobResponse:
    """
    Return the status and progress of the most-recent sync job for the group.

    ``progress_percent`` is populated when the group's ``member_count`` is known.
    """
    group = await get_group_by_id(session, group_id)
    if group is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Group id={group_id} not found",
        )

    data = await get_sync_status(group_id)
    if data is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No sync job found for group id={group_id}",
        )

    return SyncJobResponse(**data)
