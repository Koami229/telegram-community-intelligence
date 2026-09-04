"""Authenticated API for authorized Telegram message metadata ingestion."""
from __future__ import annotations

import os

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import require_ingestion_key
from app.db.database import get_db_session
from app.db.repositories.repos import (
    delete_telegram_media,
    get_group_by_id,
    get_telegram_messages,
)
from app.schemas.message import (
    MessageIngestRequest,
    MessageIngestResponse,
    MessageResponse,
    MediaResponse,
)
from app.services.message_ingestion_service import (
    IngestionError,
    ingest_messages,
    purge_expired_media,
)
from app.services.message_ingestion_service import download_media_file

router = APIRouter(prefix="/api/groups", tags=["Messages"])


@router.post(
    "/{group_id}/messages/ingest",
    response_model=MessageIngestResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_ingestion_key)],
)
async def ingest_group_messages(
    group_id: int,
    payload: MessageIngestRequest,
    session: AsyncSession = Depends(get_db_session),
) -> MessageIngestResponse:
    """Ingest accessible message/media metadata without downloading binaries."""
    try:
        processed = await ingest_messages(
            session,
            group_id=group_id,
            limit=payload.limit,
            min_id=payload.min_id,
            max_id=payload.max_id,
        )
    except IngestionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    return MessageIngestResponse(
        group_id=group_id,
        processed_messages=processed,
        message="Message metadata ingestion completed",
    )


@router.get(
    "/{group_id}/messages",
    response_model=list[MessageResponse],
    dependencies=[Depends(require_ingestion_key)],
)
async def list_group_messages(
    group_id: int,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    session: AsyncSession = Depends(get_db_session),
) -> list[MessageResponse]:
    """List previously stored message and media metadata."""
    if await get_group_by_id(session, group_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group not found")
    messages = await get_telegram_messages(
        session, group_id=group_id, offset=offset, limit=limit
    )
    return [MessageResponse.model_validate(message) for message in messages]


@router.post(
    "/{group_id}/messages/media/{media_id}/download",
    response_model=MediaResponse,
    dependencies=[Depends(require_ingestion_key)],
)
async def download_group_media(
    group_id: int,
    media_id: int,
    session: AsyncSession = Depends(get_db_session),
) -> MediaResponse:
    """Download one indexed media item when policy and limits allow it."""
    try:
        return await download_media_file(session, group_id=group_id, media_id=media_id)
    except IngestionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc


@router.delete(
    "/{group_id}/messages/media/retention",
    dependencies=[Depends(require_ingestion_key)],
)
async def purge_group_media(
    group_id: int,
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, int]:
    """Delete expired local media for one group; Telegram is never modified."""
    if await get_group_by_id(session, group_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group not found")
    return {"deleted_media": await purge_expired_media(session, group_id=group_id)}


@router.delete(
    "/{group_id}/messages/media/{media_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_ingestion_key)],
)
async def delete_group_media(
    group_id: int,
    media_id: int,
    session: AsyncSession = Depends(get_db_session),
) -> None:
    """Delete one locally archived media item, without changing Telegram."""
    media = await delete_telegram_media(session, group_id=group_id, media_id=media_id)
    if media is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Media not found")
    if media.local_path and os.path.isfile(media.local_path):
        os.remove(media.local_path)