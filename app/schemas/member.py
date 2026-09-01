"""
Pydantic schemas for User/Member API responses.
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel

from app.models.models import MemberStatus


class UserResponse(BaseModel):
    """Serialised User returned by the API."""

    id: int
    telegram_id: int
    username: Optional[str]
    first_name: Optional[str]
    last_name: Optional[str]
    is_bot: bool
    first_seen_at: Optional[datetime]
    last_seen_at: Optional[datetime]
    created_at: datetime

    model_config = {"from_attributes": True}


class GroupMemberResponse(BaseModel):
    """A User's membership in a specific Group."""

    id: int
    user_id: int
    group_id: int
    telegram_id: int
    username: Optional[str]
    first_name: Optional[str]
    last_name: Optional[str]
    is_bot: bool
    status: MemberStatus
    first_seen_at: Optional[datetime]
    last_seen_at: Optional[datetime]
    joined_at: Optional[datetime]
    left_at: Optional[datetime]

    model_config = {"from_attributes": True}


class MemberListResponse(BaseModel):
    """Paginated member list."""

    items: List[GroupMemberResponse]
    total: int
    page: int
    page_size: int
    pages: int
