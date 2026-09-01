"""
Pydantic schemas for Group API.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, field_validator

from app.models.models import GroupType


# ── Request ───────────────────────────────────────────────────────────────────

class GroupAddRequest(BaseModel):
    """Payload for POST /api/groups."""

    identifier: str
    """
    How to identify the group.  Accepted formats:
      - @username          (public groups)
      - https://t.me/...   (public invite link)
      - -100XXXXXXXXXX     (Telegram group ID as string)
    """

    @field_validator("identifier")
    @classmethod
    def identifier_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("identifier must not be empty")
        return v


# ── Response ──────────────────────────────────────────────────────────────────

class GroupResponse(BaseModel):
    """Serialised Group returned by the API."""

    id: int
    telegram_group_id: int
    title: Optional[str]
    username: Optional[str]
    group_type: GroupType
    is_active: bool
    member_count: Optional[int]
    first_synced_at: Optional[datetime]
    last_synced_at: Optional[datetime]
    created_at: datetime

    model_config = {"from_attributes": True}
