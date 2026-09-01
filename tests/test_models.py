"""
Tests: SQLAlchemy model instantiation and relationships (no DB connection needed).
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.models.models import (
    Group,
    GroupMember,
    GroupType,
    MemberStatus,
    SyncJob,
    SyncStatus,
    User,
)


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


# ── User ─────────────────────────────────────────────────────────────────────

def test_user_creation() -> None:
    user = User(
        telegram_id=123456789,
        username="johndoe",
        first_name="John",
        last_name="Doe",
        is_bot=False,
        first_seen_at=_utcnow(),
    )
    assert user.telegram_id == 123456789
    assert user.username == "johndoe"
    assert user.is_bot is False


def test_user_bot_flag() -> None:
    bot = User(telegram_id=9999, username="my_bot", is_bot=True)
    assert bot.is_bot is True


def test_user_repr() -> None:
    user = User(telegram_id=111, username="alice")
    assert "111" in repr(user)
    assert "alice" in repr(user)


# ── Group ─────────────────────────────────────────────────────────────────────

def test_group_creation() -> None:
    group = Group(
        telegram_group_id=-1001234567890,
        title="Test Group",
        username="testgroup",
        group_type=GroupType.SUPERGROUP,
        is_active=True,
        member_count=250,
    )
    assert group.telegram_group_id == -1001234567890
    assert group.group_type == GroupType.SUPERGROUP
    assert group.is_active is True


def test_group_repr() -> None:
    group = Group(telegram_group_id=-100111, title="My Group")
    assert "-100111" in repr(group)


def test_group_type_enum_values() -> None:
    assert GroupType.GROUP == "group"
    assert GroupType.SUPERGROUP == "supergroup"
    assert GroupType.CHANNEL == "channel"
    assert GroupType.UNKNOWN == "unknown"


# ── GroupMember ───────────────────────────────────────────────────────────────

def test_group_member_creation() -> None:
    member = GroupMember(
        group_id=1,
        user_id=42,
        status=MemberStatus.MEMBER,
        first_seen_at=_utcnow(),
    )
    assert member.group_id == 1
    assert member.user_id == 42
    assert member.status == MemberStatus.MEMBER


def test_member_status_enum_values() -> None:
    assert MemberStatus.MEMBER == "member"
    assert MemberStatus.ADMIN == "admin"
    assert MemberStatus.CREATOR == "creator"
    assert MemberStatus.LEFT == "left"
    assert MemberStatus.KICKED == "kicked"


# ── SyncJob ───────────────────────────────────────────────────────────────────

def test_sync_job_creation() -> None:
    job = SyncJob(
        group_id=1,
        status=SyncStatus.PENDING,
        processed_count=0,
        new_members_count=0,
        error_count=0,
    )
    assert job.group_id == 1
    assert job.status == SyncStatus.PENDING
    assert job.processed_count == 0


def test_sync_status_enum_values() -> None:
    assert SyncStatus.PENDING == "pending"
    assert SyncStatus.RUNNING == "running"
    assert SyncStatus.COMPLETED == "completed"
    assert SyncStatus.FAILED == "failed"
    assert SyncStatus.INTERRUPTED == "interrupted"


def test_sync_job_repr() -> None:
    job = SyncJob(id=7, group_id=3, status=SyncStatus.RUNNING)
    assert "7" in repr(job)
    assert "running" in repr(job)
