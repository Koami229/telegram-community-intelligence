"""
Repository pattern for User, Group, GroupMember, and SyncJob.

All database access goes through these functions.  Services call
repositories — they never use the session directly.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional, Sequence

from sqlalchemy import delete, select, update
from sqlalchemy.orm import selectinload
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import (
    Group,
    GroupMember,
    GroupType,
    MemberStatus,
    SyncJob,
    SyncStatus,
    User,
    MediaDownloadStatus,
    MediaType,
    TelegramMedia,
    TelegramMessage,
    AuthorizationAudit,
)

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


# ─────────────────────────────────────────────────────────────────────────────
# User repository
# ─────────────────────────────────────────────────────────────────────────────

async def upsert_user(
    session: AsyncSession,
    *,
    telegram_id: int,
    username: Optional[str],
    first_name: Optional[str],
    last_name: Optional[str],
    is_bot: bool = False,
    profile_photo_reference: Optional[str] = None,
) -> User:
    """
    Insert or update a User by telegram_id.

    If the user already exists, only non-None fields are updated so that
    a partial update never overwrites good data with NULL.
    Returns the persisted User instance.
    """
    now = _utcnow()

    # Try to find existing user
    result = await session.execute(
        select(User).where(User.telegram_id == telegram_id)
    )
    user = result.scalar_one_or_none()

    if user is None:
        user = User(
            telegram_id=telegram_id,
            username=username,
            first_name=first_name,
            last_name=last_name,
            is_bot=is_bot,
            profile_photo_reference=profile_photo_reference,
            first_seen_at=now,
            last_seen_at=now,
        )
        session.add(user)
        await session.flush()  # get user.id without full commit
        logger.debug("Created user telegram_id=%s", telegram_id)
    else:
        # Update only fields that have a value in this batch
        if username is not None:
            user.username = username
        if first_name is not None:
            user.first_name = first_name
        if last_name is not None:
            user.last_name = last_name
        if profile_photo_reference is not None:
            user.profile_photo_reference = profile_photo_reference
        user.last_seen_at = now
        logger.debug("Updated user telegram_id=%s", telegram_id)

    return user


async def get_user_by_telegram_id(
    session: AsyncSession, telegram_id: int
) -> Optional[User]:
    result = await session.execute(
        select(User).where(User.telegram_id == telegram_id)
    )
    return result.scalar_one_or_none()


# ─────────────────────────────────────────────────────────────────────────────
# Group repository
# ─────────────────────────────────────────────────────────────────────────────

async def create_or_get_group(
    session: AsyncSession,
    *,
    telegram_group_id: int,
    title: Optional[str],
    username: Optional[str],
    group_type: GroupType,
    member_count: Optional[int] = None,
    collection_authorized: Optional[bool] = None,
    media_download_authorized: Optional[bool] = None,
) -> tuple[Group, bool]:
    """
    Return (group, created) where created is True if the group was inserted.
    """
    result = await session.execute(
        select(Group).where(Group.telegram_group_id == telegram_group_id)
    )
    group = result.scalar_one_or_none()

    if group is None:
        group = Group(
            telegram_group_id=telegram_group_id,
            title=title,
            username=username,
            group_type=group_type,
            is_active=True,
            collection_authorized=bool(collection_authorized),
            collection_authorized_at=_utcnow() if collection_authorized else None,
            media_download_authorized=bool(media_download_authorized),
            member_count=member_count,
        )
        session.add(group)
        await session.flush()
        return group, True

    # Update mutable fields
    group.title = title or group.title
    group.username = username or group.username
    group.is_active = True
    if collection_authorized is not None:
        group.collection_authorized = collection_authorized
        group.collection_authorized_at = _utcnow() if collection_authorized else None
        if not collection_authorized:
            group.media_download_authorized = False
    if media_download_authorized is not None and group.collection_authorized:
        group.media_download_authorized = media_download_authorized
    if member_count is not None:
        group.member_count = member_count
    return group, False


async def get_group_by_id(
    session: AsyncSession, group_id: int
) -> Optional[Group]:
    result = await session.execute(select(Group).where(Group.id == group_id))
    return result.scalar_one_or_none()


async def get_all_groups(session: AsyncSession) -> Sequence[Group]:
    result = await session.execute(
        select(Group).where(Group.is_active == True).order_by(Group.created_at.desc())  # noqa: E712
    )
    return result.scalars().all()


async def update_group_sync_timestamps(
    session: AsyncSession,
    group_id: int,
    *,
    first_synced: bool = False,
) -> None:
    now = _utcnow()
    values: dict = {"last_synced_at": now}
    if first_synced:
        values["first_synced_at"] = now
    await session.execute(
        update(Group).where(Group.id == group_id).values(**values)
    )


async def set_collection_authorization(
    session: AsyncSession,
    group_id: int,
    *,
    authorized: bool,
    media_download_authorized: bool = False,
) -> Optional[Group]:
    """Record an explicit collection authorization decision for a group."""
    result = await session.execute(select(Group).where(Group.id == group_id))
    group = result.scalar_one_or_none()
    if group is None:
        return None
    group.collection_authorized = authorized
    group.collection_authorized_at = _utcnow() if authorized else None
    group.media_download_authorized = (
        media_download_authorized if authorized else False
    )
    await session.flush()
    return group


async def create_authorization_audit(
    session: AsyncSession,
    *,
    group_id: int,
    collection_authorized: bool,
    media_download_authorized: bool,
    actor_label: Optional[str],
    reason: Optional[str],
) -> AuthorizationAudit:
    audit = AuthorizationAudit(
        group_id=group_id,
        collection_authorized=collection_authorized,
        media_download_authorized=media_download_authorized,
        actor_label=actor_label,
        reason=reason,
    )
    session.add(audit)
    await session.flush()
    return audit


async def get_authorization_audits(
    session: AsyncSession,
    *,
    group_id: int,
    limit: int = 100,
) -> Sequence[AuthorizationAudit]:
    result = await session.execute(
        select(AuthorizationAudit)
        .where(AuthorizationAudit.group_id == group_id)
        .order_by(AuthorizationAudit.created_at.desc(), AuthorizationAudit.id.desc())
        .limit(limit)
    )
    return result.scalars().all()


async def upsert_telegram_message(
    session: AsyncSession,
    *,
    group_id: int,
    telegram_message_id: int,
    message_date: datetime,
    author_telegram_id: Optional[int],
    text: Optional[str],
    content_hash: Optional[str],
) -> tuple[TelegramMessage, bool]:
    """Insert or update message metadata without creating duplicates."""
    result = await session.execute(
        select(TelegramMessage).where(
            TelegramMessage.group_id == group_id,
            TelegramMessage.telegram_message_id == telegram_message_id,
        )
    )
    message = result.scalar_one_or_none()
    if message is None:
        message = TelegramMessage(
            group_id=group_id,
            telegram_message_id=telegram_message_id,
            message_date=message_date,
            author_telegram_id=author_telegram_id,
            text=text,
            content_hash=content_hash,
        )
        session.add(message)
        await session.flush()
        return message, True

    message.message_date = message_date
    message.author_telegram_id = author_telegram_id
    message.text = text
    message.content_hash = content_hash
    return message, False


async def upsert_telegram_media(
    session: AsyncSession,
    *,
    message_id: int,
    media_index: int,
    media_type: MediaType,
    file_name: Optional[str],
    mime_type: Optional[str],
    size_bytes: Optional[int],
    remote_reference: Optional[str],
) -> TelegramMedia:
    """Persist media metadata; never marks a file as downloaded."""
    result = await session.execute(
        select(TelegramMedia).where(
            TelegramMedia.message_id == message_id,
            TelegramMedia.media_index == media_index,
        )
    )
    media = result.scalar_one_or_none()
    if media is None:
        media = TelegramMedia(
            message_id=message_id,
            media_index=media_index,
            media_type=media_type,
            file_name=file_name,
            mime_type=mime_type,
            size_bytes=size_bytes,
            remote_reference=remote_reference,
            download_status=MediaDownloadStatus.NOT_REQUESTED,
        )
        session.add(media)
        await session.flush()
        return media

    media.media_type = media_type
    media.file_name = file_name
    media.mime_type = mime_type
    media.size_bytes = size_bytes
    media.remote_reference = remote_reference
    return media


async def get_telegram_messages(
    session: AsyncSession,
    *,
    group_id: int,
    offset: int = 0,
    limit: int = 50,
) -> Sequence[TelegramMessage]:
    """Return stored message metadata with its optional media records."""
    result = await session.execute(
        select(TelegramMessage)
        .options(selectinload(TelegramMessage.media))
        .where(TelegramMessage.group_id == group_id)
        .order_by(TelegramMessage.message_date.desc(), TelegramMessage.id.desc())
        .offset(offset)
        .limit(limit)
    )
    return result.scalars().all()


async def delete_telegram_media(
    session: AsyncSession,
    *,
    group_id: int,
    media_id: int,
) -> Optional[TelegramMedia]:
    """Remove one local media record belonging to the requested group."""
    result = await session.execute(
        select(TelegramMedia)
        .join(TelegramMessage)
        .where(
            TelegramMedia.id == media_id,
            TelegramMessage.id == TelegramMedia.message_id,
            TelegramMessage.group_id == group_id,
        )
    )
    media = result.scalar_one_or_none()
    if media is None:
        return None
    await session.delete(media)
    await session.flush()
    return media


# ─────────────────────────────────────────────────────────────────────────────
# GroupMember repository
# ─────────────────────────────────────────────────────────────────────────────

async def upsert_group_member(
    session: AsyncSession,
    *,
    group_id: int,
    user_id: int,
    status: MemberStatus,
    joined_at: Optional[datetime] = None,
) -> tuple[GroupMember, bool]:
    """
    Insert or update a GroupMember row.

    Returns (member, created).
    """
    now = _utcnow()
    result = await session.execute(
        select(GroupMember).where(
            GroupMember.group_id == group_id,
            GroupMember.user_id == user_id,
        )
    )
    member = result.scalar_one_or_none()

    if member is None:
        member = GroupMember(
            group_id=group_id,
            user_id=user_id,
            status=status,
            first_seen_at=now,
            last_seen_at=now,
            joined_at=joined_at,
        )
        session.add(member)
        await session.flush()
        return member, True

    # Update
    member.status = status
    member.last_seen_at = now
    if joined_at and not member.joined_at:
        member.joined_at = joined_at
    return member, False


# ─────────────────────────────────────────────────────────────────────────────
# SyncJob repository
# ─────────────────────────────────────────────────────────────────────────────

async def create_sync_job(session: AsyncSession, group_id: int) -> SyncJob:
    job = SyncJob(
        group_id=group_id,
        status=SyncStatus.PENDING,
        processed_count=0,
        new_members_count=0,
        error_count=0,
    )
    session.add(job)
    await session.flush()
    return job


async def get_sync_job(
    session: AsyncSession, job_id: int
) -> Optional[SyncJob]:
    result = await session.execute(select(SyncJob).where(SyncJob.id == job_id))
    return result.scalar_one_or_none()


async def get_latest_sync_job(
    session: AsyncSession, group_id: int
) -> Optional[SyncJob]:
    """Return the most-recently-created SyncJob for a group."""
    result = await session.execute(
        select(SyncJob)
        .where(SyncJob.group_id == group_id)
        .order_by(SyncJob.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def update_sync_job_progress(
    session: AsyncSession,
    job_id: int,
    *,
    processed_count: int,
    new_members_count: int,
    error_count: int,
    last_cursor: Optional[str] = None,
) -> None:
    values: dict = {
        "processed_count": processed_count,
        "new_members_count": new_members_count,
        "error_count": error_count,
    }
    if last_cursor is not None:
        values["last_cursor"] = last_cursor
    await session.execute(
        update(SyncJob).where(SyncJob.id == job_id).values(**values)
    )


async def set_sync_job_status(
    session: AsyncSession,
    job_id: int,
    status: SyncStatus,
    *,
    error_message: Optional[str] = None,
) -> None:
    now = _utcnow()
    values: dict = {"status": status}
    if status == SyncStatus.RUNNING:
        values["started_at"] = now
    elif status in (SyncStatus.COMPLETED, SyncStatus.FAILED, SyncStatus.INTERRUPTED):
        values["completed_at"] = now
    if error_message:
        values["error_message"] = error_message
    await session.execute(
        update(SyncJob).where(SyncJob.id == job_id).values(**values)
    )
