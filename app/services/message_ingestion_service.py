"""Authorized, metadata-first Telegram message ingestion."""
from __future__ import annotations

import hashlib
import mimetypes
import os
import tempfile
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from telethon.errors import FloodWaitError
from telethon.tl.types import DocumentAttributeAudio, DocumentAttributeFilename, DocumentAttributeVideo

from app.db.repositories.repos import (
    get_group_by_id,
    upsert_telegram_media,
    upsert_telegram_message,
)
from app.models.models import Group, MediaType
from app.models.models import MediaDownloadStatus, TelegramMedia, TelegramMessage
from app.core.config import get_settings
from app.telegram.client import telegram_service


class IngestionError(Exception):
    """Raised when an authorized ingestion cannot proceed."""


def _media_type(message: object) -> Optional[MediaType]:
    if getattr(message, "photo", None) is not None:
        return MediaType.PHOTO
    document = getattr(message, "document", None)
    if document is None:
        return None
    attributes = getattr(document, "attributes", [])
    if any(isinstance(item, DocumentAttributeAudio) for item in attributes):
        return MediaType.VOICE if getattr(document, "mime_type", "") == "audio/ogg" else MediaType.AUDIO
    if any(isinstance(item, DocumentAttributeVideo) for item in attributes):
        return MediaType.VIDEO
    if getattr(document, "mime_type", "") == "application/x-tgsticker":
        return MediaType.STICKER
    return MediaType.DOCUMENT


def _media_metadata(message: object, media_type: MediaType) -> dict:
    media = getattr(message, "document", None) or getattr(message, "photo", None)
    attributes = getattr(media, "attributes", []) if media else []
    file_name = next(
        (getattr(item, "file_name", None) for item in attributes if isinstance(item, DocumentAttributeFilename)),
        None,
    )
    mime_type = getattr(media, "mime_type", None) if media else None
    if mime_type is None and media_type == MediaType.PHOTO:
        mime_type = "image/jpeg"
    return {
        "media_type": media_type,
        "file_name": file_name,
        "mime_type": mime_type or mimetypes.guess_type(file_name or "")[0],
        "size_bytes": getattr(media, "size", None) if media else None,
        "remote_reference": str(getattr(media, "id", "")) if media else None,
    }


async def ingest_messages(
    session: AsyncSession,
    *,
    group_id: int,
    limit: int = 100,
    min_id: Optional[int] = None,
    max_id: Optional[int] = None,
) -> int:
    """Store accessible message/media metadata for a registered group.

    This function deliberately does not call ``download_media``. Telegram
    access checks remain enforced by the authenticated client.
    """
    if not 1 <= limit <= 1000:
        raise ValueError("limit must be between 1 and 1000")
    if not telegram_service.is_connected() or not await telegram_service.is_authorized():
        raise IngestionError("Telegram account is not authenticated")

    group: Optional[Group] = await get_group_by_id(session, group_id)
    if group is None or not group.is_active:
        raise IngestionError("Group is not registered or active")
    if not group.collection_authorized:
        raise IngestionError("Collection authorization has not been confirmed for this group")

    client = telegram_service.get_client()
    try:
        entity = await client.get_entity(group.telegram_group_id)
        count = 0
        async for telegram_message in client.iter_messages(
            entity, limit=limit, min_id=min_id, max_id=max_id
        ):
            message_date = getattr(telegram_message, "date", None) or datetime.now(timezone.utc)
            text = getattr(telegram_message, "message", None) or None
            content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest() if text else None
            stored, _ = await upsert_telegram_message(
                session,
                group_id=group_id,
                telegram_message_id=telegram_message.id,
                message_date=message_date,
                author_telegram_id=getattr(telegram_message, "sender_id", None),
                text=text,
                content_hash=content_hash,
            )
            detected_type = _media_type(telegram_message)
            if detected_type is not None:
                await upsert_telegram_media(
                    session,
                    message_id=stored.id,
                    media_index=0,
                    **_media_metadata(telegram_message, detected_type),
                )
            count += 1
        await session.commit()
        return count
    except FloodWaitError as exc:
        await session.rollback()
        raise IngestionError(f"Telegram rate limit hit; retry after {exc.seconds}s") from exc
    except Exception:
        await session.rollback()
        raise


async def download_media_file(
    session: AsyncSession,
    *,
    group_id: int,
    media_id: int,
) -> TelegramMedia:
    """Download one previously indexed media item under explicit safeguards."""
    settings = get_settings()
    if not settings.media_download_enabled:
        raise IngestionError("Media downloads are disabled by configuration")
    if not telegram_service.is_connected() or not await telegram_service.is_authorized():
        raise IngestionError("Telegram account is not authenticated")

    result = await session.execute(
        select(TelegramMedia)
        .join(TelegramMessage)
        .options(selectinload(TelegramMedia.message))
        .where(
            TelegramMedia.id == media_id,
            TelegramMessage.id == TelegramMedia.message_id,
            TelegramMessage.group_id == group_id,
        )
    )
    media = result.scalar_one_or_none()
    if media is None:
        raise IngestionError("Media record not found for this group")
    if media.size_bytes and media.size_bytes > settings.media_max_size_bytes:
        media.download_status = MediaDownloadStatus.REJECTED
        await session.commit()
        raise IngestionError("Media exceeds the configured size limit")
    if not media.mime_type or media.mime_type.lower() not in settings.media_allowed_mime_types_list:
        media.download_status = MediaDownloadStatus.REJECTED
        await session.commit()
        raise IngestionError("Media MIME type is not allowed")

    group = await get_group_by_id(session, group_id)
    if group is None or not group.is_active:
        raise IngestionError("Group is not registered or active")
    if not group.collection_authorized:
        raise IngestionError("Collection authorization has not been confirmed for this group")
    if not group.media_download_authorized:
        raise IngestionError("Media download authorization has not been confirmed for this group")

    client = telegram_service.get_client()
    entity = await client.get_entity(group.telegram_group_id)
    message = await client.get_messages(entity, ids=media.message.telegram_message_id)
    if message is None or not getattr(message, "media", None):
        raise IngestionError("Media is no longer accessible through Telegram")

    storage_root = os.path.abspath(settings.media_storage_path)
    target_dir = os.path.join(storage_root, str(group_id))
    os.makedirs(target_dir, exist_ok=True)
    extension = mimetypes.guess_extension(media.mime_type or "") or ".bin"
    target_path = os.path.join(
        target_dir,
        f"{media.message.telegram_message_id}-{media.media_index}{extension}",
    )
    fd, temp_path = tempfile.mkstemp(prefix=".telegram-media-", dir=target_dir)
    os.close(fd)
    media.download_status = MediaDownloadStatus.PENDING
    await session.commit()
    try:
        downloaded_path = await client.download_media(message, file=temp_path)
        if not downloaded_path or not os.path.isfile(temp_path):
            raise IngestionError("Telegram did not return a media file")
        actual_size = os.path.getsize(temp_path)
        if actual_size > settings.media_max_size_bytes:
            raise IngestionError("Downloaded media exceeds the configured size limit")
        digest = hashlib.sha256()
        with open(temp_path, "rb") as downloaded_file:
            for chunk in iter(lambda: downloaded_file.read(1024 * 1024), b""):
                digest.update(chunk)
        os.replace(temp_path, target_path)
        media.local_path = target_path
        media.sha256 = digest.hexdigest()
        media.size_bytes = actual_size
        media.download_status = MediaDownloadStatus.DOWNLOADED
        await session.commit()
        return media
    except Exception:
        if os.path.exists(temp_path):
            os.remove(temp_path)
        media.download_status = MediaDownloadStatus.FAILED
        await session.commit()
        raise


async def purge_expired_media(
    session: AsyncSession,
    *,
    group_id: Optional[int] = None,
) -> int:
    """Delete locally archived media older than the configured retention period."""
    settings = get_settings()
    if settings.media_retention_days <= 0:
        return 0

    cutoff = datetime.now(timezone.utc) - timedelta(days=settings.media_retention_days)
    query = (
        select(TelegramMedia)
        .join(TelegramMessage)
        .where(
            TelegramMedia.created_at < cutoff,
            TelegramMedia.local_path.is_not(None),
            TelegramMessage.group_id == group_id if group_id is not None else True,
        )
    )
    result = await session.execute(query)
    media_items = result.scalars().all()
    removed = 0
    for media in media_items:
        if media.local_path and os.path.isfile(media.local_path):
            os.remove(media.local_path)
        await session.delete(media)
        removed += 1
    await session.commit()
    return removed