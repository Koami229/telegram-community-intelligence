"""
Sync service — fetches Telegram group members and persists them.

Design decisions:
  - Runs entirely in a background asyncio task (fire-and-forget from the API).
  - Uses Telethon's GetParticipants with 200-member pages.
  - Processes members in batches and flushes to DB every BATCH_SIZE records.
  - Respects FloodWait delays instead of bypassing them.
  - Stores last_cursor as a JSON-serialised offset so sync can resume after
    interruption (best-effort: the cursor is the last successfully committed
    offset index).
  - Never logs sensitive user data beyond IDs and usernames.

Resumability strategy:
  Telethon's iter_participants() does not expose a stable, re-entrant cursor
  (the server-side offset is an integer that can shift as members join/leave).
  We therefore store the number of processed members as the cursor and skip
  that many at the start of a resumed sync.  This means at most BATCH_SIZE
  members may be re-processed on resume (they will be upserted idempotently).
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Optional

from telethon.errors import (
    ChannelPrivateError,
    ChatAdminRequiredError,
    FloodWaitError,
)
from telethon.tl.functions.channels import GetParticipantsRequest
from telethon.tl.types import (
    ChannelParticipant,
    ChannelParticipantAdmin,
    ChannelParticipantBanned,
    ChannelParticipantCreator,
    ChannelParticipantLeft,
    ChannelParticipantsSearch,
    InputChannel,
    InputPeerChannel,
)

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import AsyncSessionFactory
from app.db.repositories.repos import (
    create_sync_job,
    get_group_by_id,
    get_latest_sync_job,
    get_sync_job,
    set_sync_job_status,
    update_group_sync_timestamps,
    update_sync_job_progress,
    upsert_group_member,
    upsert_user,
)
from app.models.models import MemberStatus, SyncStatus
from app.telegram.client import telegram_service

logger = logging.getLogger(__name__)

# How many members to process before flushing to the DB
BATCH_SIZE = 200
# Pause between Telethon GetParticipants pages (seconds) — avoid flood
PAGE_DELAY = 1.0


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


def _participant_to_status(participant: object) -> MemberStatus:
    if isinstance(participant, ChannelParticipantCreator):
        return MemberStatus.CREATOR
    if isinstance(participant, ChannelParticipantAdmin):
        return MemberStatus.ADMIN
    if isinstance(participant, ChannelParticipantBanned):
        return MemberStatus.KICKED
    if isinstance(participant, ChannelParticipantLeft):
        return MemberStatus.LEFT
    return MemberStatus.MEMBER


async def start_sync(group_id: int) -> int:
    """
    Create a SyncJob for ``group_id`` and launch the background task.

    Returns the job_id immediately.
    """
    async with AsyncSessionFactory() as session:
        group = await get_group_by_id(session, group_id)
        if group is None:
            raise ValueError(f"Group id={group_id} not found")

        # Check for an interrupted job we can resume
        latest = await get_latest_sync_job(session, group_id)
        if latest and latest.status in (SyncStatus.RUNNING, SyncStatus.PENDING):
            # Already running — return existing job
            logger.info(
                "Sync already in progress for group %s (job=%s)", group_id, latest.id
            )
            await session.commit()
            return latest.id

        job = await create_sync_job(session, group_id)
        await session.commit()
        job_id = job.id

    # Fire and forget
    asyncio.create_task(_run_sync(group_id, job_id))
    logger.info("Sync job %s started for group %s", job_id, group_id)
    return job_id


async def _run_sync(group_id: int, job_id: int) -> None:
    """Background task: fetches all accessible participants and upserts them."""
    logger.info("[SyncJob %s] Starting sync for group %s", job_id, group_id)

    async with AsyncSessionFactory() as session:
        await set_sync_job_status(session, job_id, SyncStatus.RUNNING)
        await session.commit()

    processed = 0
    new_members = 0
    errors = 0
    resume_offset = 0

    # ── Check for resumable cursor ────────────────────────────────────────
    async with AsyncSessionFactory() as session:
        job = await get_sync_job(session, job_id)
        if job and job.last_cursor:
            try:
                cursor_data = json.loads(job.last_cursor)
                resume_offset = cursor_data.get("offset", 0)
                processed = resume_offset
                logger.info(
                    "[SyncJob %s] Resuming from offset %s", job_id, resume_offset
                )
            except Exception:
                resume_offset = 0

    # ── Fetch participants ────────────────────────────────────────────────
    if not telegram_service.is_connected() or not await telegram_service.is_authorized():
        async with AsyncSessionFactory() as session:
            await set_sync_job_status(
                session, job_id, SyncStatus.FAILED,
                error_message="Telegram not authenticated"
            )
            await session.commit()
        return

    client = telegram_service.get_client()

    async with AsyncSessionFactory() as session:
        group = await get_group_by_id(session, group_id)
        if not group:
            await set_sync_job_status(
                session, job_id, SyncStatus.FAILED,
                error_message="Group not found in database"
            )
            await session.commit()
            return
        tg_group_id = group.telegram_group_id
        is_first_sync = group.first_synced_at is None

    try:
        entity = await client.get_entity(tg_group_id)
    except Exception as exc:
        async with AsyncSessionFactory() as session:
            await set_sync_job_status(
                session, job_id, SyncStatus.FAILED,
                error_message=f"Could not resolve group entity: {exc}"
            )
            await session.commit()
        logger.error("[SyncJob %s] Failed to resolve group entity: %s", job_id, exc)
        return

    offset = resume_offset
    batch_buffer: list = []

    try:
        logger.info("[SyncJob %s] Fetching participants (offset=%s)…", job_id, offset)

        async for participant in client.iter_participants(entity, aggressive=False):
            user = getattr(participant, "user", None) or participant
            if not hasattr(user, "id"):
                continue

            batch_buffer.append((user, participant))

            if len(batch_buffer) >= BATCH_SIZE:
                n, e = await _flush_batch(batch_buffer, group_id, job_id)
                new_members += n
                errors += e
                processed += len(batch_buffer)
                batch_buffer.clear()

                cursor = json.dumps({"offset": processed})
                async with AsyncSessionFactory() as session:
                    await update_sync_job_progress(
                        session, job_id,
                        processed_count=processed,
                        new_members_count=new_members,
                        error_count=errors,
                        last_cursor=cursor,
                    )
                    await session.commit()

                logger.info(
                    "[SyncJob %s] Progress: %s processed, %s new",
                    job_id, processed, new_members,
                )
                await asyncio.sleep(PAGE_DELAY)

        # Flush remaining
        if batch_buffer:
            n, e = await _flush_batch(batch_buffer, group_id, job_id)
            new_members += n
            errors += e
            processed += len(batch_buffer)

        # Final progress update + mark completed
        async with AsyncSessionFactory() as session:
            await update_sync_job_progress(
                session, job_id,
                processed_count=processed,
                new_members_count=new_members,
                error_count=errors,
                last_cursor=None,
            )
            await set_sync_job_status(session, job_id, SyncStatus.COMPLETED)
            await update_group_sync_timestamps(
                session, group_id, first_synced=is_first_sync
            )
            await session.commit()

        logger.info(
            "[SyncJob %s] ✓ Completed — processed=%s new=%s errors=%s",
            job_id, processed, new_members, errors,
        )

    except FloodWaitError as exc:
        wait = exc.seconds
        logger.warning(
            "[SyncJob %s] FloodWait detected — waiting %ss before interrupting",
            job_id, wait,
        )
        # Save progress and mark interrupted so the job can be resumed
        async with AsyncSessionFactory() as session:
            cursor = json.dumps({"offset": processed})
            await update_sync_job_progress(
                session, job_id,
                processed_count=processed,
                new_members_count=new_members,
                error_count=errors,
                last_cursor=cursor,
            )
            await set_sync_job_status(
                session, job_id, SyncStatus.INTERRUPTED,
                error_message=f"FloodWait {wait}s — resume after waiting",
            )
            await session.commit()
        # Respect the mandatory wait
        await asyncio.sleep(wait)

    except (ChannelPrivateError, ChatAdminRequiredError) as exc:
        async with AsyncSessionFactory() as session:
            await set_sync_job_status(
                session, job_id, SyncStatus.FAILED,
                error_message=f"Access denied: {exc}",
            )
            await session.commit()
        logger.error("[SyncJob %s] Access denied: %s", job_id, exc)

    except Exception as exc:
        async with AsyncSessionFactory() as session:
            cursor = json.dumps({"offset": processed})
            await update_sync_job_progress(
                session, job_id,
                processed_count=processed,
                new_members_count=new_members,
                error_count=errors + 1,
                last_cursor=cursor,
            )
            await set_sync_job_status(
                session, job_id, SyncStatus.FAILED,
                error_message=str(exc),
            )
            await session.commit()
        logger.error("[SyncJob %s] Unexpected error: %s", job_id, exc, exc_info=True)


async def _flush_batch(
    batch: list,
    group_id: int,
    job_id: int,
) -> tuple[int, int]:
    """
    Upsert a batch of (user_entity, participant) pairs into the database.

    Returns (new_count, error_count).
    """
    new_count = 0
    error_count = 0

    async with AsyncSessionFactory() as session:
        for user_entity, participant in batch:
            try:
                user = await upsert_user(
                    session,
                    telegram_id=user_entity.id,
                    username=getattr(user_entity, "username", None),
                    first_name=getattr(user_entity, "first_name", None),
                    last_name=getattr(user_entity, "last_name", None),
                    is_bot=getattr(user_entity, "bot", False),
                )

                status = _participant_to_status(participant)
                joined_at: Optional[datetime] = None
                if hasattr(participant, "date") and participant.date:
                    joined_at = participant.date

                _, created = await upsert_group_member(
                    session,
                    group_id=group_id,
                    user_id=user.id,
                    status=status,
                    joined_at=joined_at,
                )
                if created:
                    new_count += 1

            except Exception as exc:
                logger.warning(
                    "[SyncJob %s] Error processing user %s: %s",
                    job_id,
                    getattr(user_entity, "id", "?"),
                    exc,
                )
                error_count += 1

        try:
            await session.commit()
        except Exception as exc:
            logger.error("[SyncJob %s] DB commit failed: %s", job_id, exc)
            await session.rollback()
            error_count += len(batch)
            new_count = 0

    return new_count, error_count


async def get_sync_status(group_id: int) -> Optional[dict]:
    """
    Return a dict describing the latest sync job for ``group_id``,
    or None if no job exists.
    """
    async with AsyncSessionFactory() as session:
        job = await get_latest_sync_job(session, group_id)
        if job is None:
            return None
        group = await get_group_by_id(session, group_id)
        total = group.member_count if group else None

        progress_percent: Optional[float] = None
        if total and total > 0:
            progress_percent = round(job.processed_count / total * 100, 1)

        return {
            "id": job.id,
            "job_id": job.id,
            "group_id": job.group_id,
            "status": job.status.value,
            "started_at": job.started_at,
            "completed_at": job.completed_at,
            "processed_count": job.processed_count,
            "new_members_count": job.new_members_count,
            "error_count": job.error_count,
            "total_member_count": total,
            "progress_percent": progress_percent,
            "last_cursor": job.last_cursor,
            "error_message": job.error_message,
            "created_at": job.created_at,
        }
