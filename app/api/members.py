"""
Members API — paginated member list for a monitored group.
"""
from __future__ import annotations

import logging
import math
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.database import get_db_session
from app.db.repositories.repos import get_group_by_id
from app.models.models import Group, GroupMember, MemberStatus, User
from app.schemas.member import GroupMemberResponse, MemberListResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/groups", tags=["Members"])


@router.get(
    "/{group_id}/members",
    response_model=MemberListResponse,
    summary="List group members (paginated)",
)
async def list_members(
    group_id: int,
    page: int = Query(default=1, ge=1, description="Page number (1-based)"),
    page_size: int = Query(default=50, ge=1, le=200, description="Members per page"),
    status_filter: Optional[MemberStatus] = Query(default=None, alias="status", description="Filter by member status"),
    search: Optional[str] = Query(default=None, description="Search by username or first/last name"),
    session: AsyncSession = Depends(get_db_session),
) -> MemberListResponse:
    """
    Return a paginated list of members for a monitored group.

    Supports filtering by status and text search on username/name.
    """
    group = await get_group_by_id(session, group_id)
    if group is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Group id={group_id} not found",
        )

    # Build base query joining GroupMember → User
    base_q = (
        select(GroupMember, User)
        .join(User, GroupMember.user_id == User.id)
        .where(GroupMember.group_id == group_id)
    )

    if status_filter is not None:
        base_q = base_q.where(GroupMember.status == status_filter)

    if search:
        term = f"%{search.lower()}%"
        base_q = base_q.where(
            (func.lower(User.username).like(term))
            | (func.lower(User.first_name).like(term))
            | (func.lower(User.last_name).like(term))
        )

    # Count total
    count_q = select(func.count()).select_from(base_q.subquery())
    total_result = await session.execute(count_q)
    total = total_result.scalar_one()

    # Paginate
    offset = (page - 1) * page_size
    rows_result = await session.execute(
        base_q.order_by(GroupMember.first_seen_at.desc().nulls_last(), GroupMember.id.asc())
        .offset(offset)
        .limit(page_size)
    )
    rows = rows_result.all()

    items = []
    for gm, user in rows:
        items.append(
            GroupMemberResponse(
                id=gm.id,
                user_id=user.id,
                group_id=gm.group_id,
                telegram_id=user.telegram_id,
                username=user.username,
                first_name=user.first_name,
                last_name=user.last_name,
                is_bot=user.is_bot,
                status=gm.status,
                first_seen_at=gm.first_seen_at,
                last_seen_at=gm.last_seen_at,
                joined_at=gm.joined_at,
                left_at=gm.left_at,
            )
        )

    pages = max(1, math.ceil(total / page_size))

    return MemberListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        pages=pages,
    )
