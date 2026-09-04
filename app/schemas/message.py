"""Schemas for authorized Telegram message ingestion and retrieval."""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field

from app.models.models import MediaDownloadStatus, MediaType


class MessageIngestRequest(BaseModel):
    limit: int = Field(default=100, ge=1, le=1000)
    min_id: Optional[int] = Field(default=None, ge=1)
    max_id: Optional[int] = Field(default=None, ge=1)


class MediaResponse(BaseModel):
    id: int
    media_index: int
    media_type: MediaType
    file_name: Optional[str]
    mime_type: Optional[str]
    size_bytes: Optional[int]
    remote_reference: Optional[str]
    local_path: Optional[str]
    sha256: Optional[str]
    download_status: MediaDownloadStatus

    model_config = {"from_attributes": True}


class MessageResponse(BaseModel):
    id: int
    group_id: int
    telegram_message_id: int
    author_telegram_id: Optional[int]
    message_date: datetime
    text: Optional[str]
    content_hash: Optional[str]
    media: List[MediaResponse]

    model_config = {"from_attributes": True}


class MessageIngestResponse(BaseModel):
    group_id: int
    processed_messages: int
    media_downloaded: int = 0
    message: str