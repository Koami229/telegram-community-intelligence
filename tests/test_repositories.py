"""
Tests: Repository logic — upsert semantics (in-memory, no DB connection).
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.models import GroupType, MemberStatus, SyncStatus


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


# ── upsert_user ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_upsert_user_creates_new() -> None:
    from app.db.repositories.repos import upsert_user

    # Simulate no existing user
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.add = MagicMock()
    mock_session.flush = AsyncMock()

    user = await upsert_user(
        mock_session,
        telegram_id=12345,
        username="alice",
        first_name="Alice",
        last_name="Smith",
        is_bot=False,
    )

    assert user.telegram_id == 12345
    assert user.username == "alice"
    mock_session.add.assert_called_once()
    mock_session.flush.assert_called_once()


@pytest.mark.asyncio
async def test_upsert_user_updates_existing() -> None:
    from app.db.repositories.repos import upsert_user

    existing_user = MagicMock()
    existing_user.telegram_id = 12345
    existing_user.username = "old_name"

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = existing_user

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.add = MagicMock()

    user = await upsert_user(
        mock_session,
        telegram_id=12345,
        username="new_name",
        first_name="Alice",
        last_name=None,
        is_bot=False,
    )

    assert user.username == "new_name"
    # add() should NOT be called when updating
    mock_session.add.assert_not_called()


# ── create_or_get_group ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_group_when_not_exists() -> None:
    from app.db.repositories.repos import create_or_get_group

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.add = MagicMock()
    mock_session.flush = AsyncMock()

    group, created = await create_or_get_group(
        mock_session,
        telegram_group_id=-1001234567890,
        title="My Group",
        username="mygroup",
        group_type=GroupType.SUPERGROUP,
        member_count=100,
    )

    assert created is True
    assert group.telegram_group_id == -1001234567890
    mock_session.add.assert_called_once()


@pytest.mark.asyncio
async def test_get_group_returns_existing() -> None:
    from app.db.repositories.repos import create_or_get_group

    existing = MagicMock()
    existing.telegram_group_id = -1001234567890
    existing.title = "Old Title"
    existing.username = None
    existing.is_active = True

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = existing

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.add = MagicMock()

    group, created = await create_or_get_group(
        mock_session,
        telegram_group_id=-1001234567890,
        title="New Title",
        username="newusr",
        group_type=GroupType.SUPERGROUP,
    )

    assert created is False
    assert group.title == "New Title"
    mock_session.add.assert_not_called()


@pytest.mark.asyncio
async def test_updating_group_without_authorization_fields_preserves_consent() -> None:
    from app.db.repositories.repos import create_or_get_group

    existing = MagicMock()
    existing.telegram_group_id = -1001234567890
    existing.title = "Existing"
    existing.username = "existing"
    existing.is_active = True
    existing.collection_authorized = True
    existing.collection_authorized_at = datetime.now(tz=timezone.utc)
    existing.media_download_authorized = True

    result = MagicMock()
    result.scalar_one_or_none.return_value = existing
    session = AsyncMock()
    session.execute = AsyncMock(return_value=result)

    group, created = await create_or_get_group(
        session,
        telegram_group_id=existing.telegram_group_id,
        title="Updated",
        username="updated",
        group_type=GroupType.SUPERGROUP,
    )

    assert created is False
    assert group.collection_authorized is True
    assert group.media_download_authorized is True


@pytest.mark.asyncio
async def test_authorization_audit_stores_actor_and_reason_without_secret() -> None:
    from app.db.repositories.repos import create_authorization_audit

    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()

    record = await create_authorization_audit(
        session,
        group_id=1,
        collection_authorized=True,
        media_download_authorized=False,
        actor_label="operator-1",
        reason="Written owner authorization",
    )

    assert record.actor_label == "operator-1"
    assert record.reason == "Written owner authorization"
    assert not hasattr(record, "api_key")
    session.add.assert_called_once_with(record)


# ── upsert_group_member ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_upsert_group_member_creates() -> None:
    from app.db.repositories.repos import upsert_group_member

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.add = MagicMock()
    mock_session.flush = AsyncMock()

    member, created = await upsert_group_member(
        mock_session,
        group_id=1,
        user_id=42,
        status=MemberStatus.MEMBER,
    )

    assert created is True
    assert member.group_id == 1
    assert member.user_id == 42
    mock_session.add.assert_called_once()


@pytest.mark.asyncio
async def test_upsert_group_member_no_duplicate() -> None:
    from app.db.repositories.repos import upsert_group_member

    existing = MagicMock()
    existing.group_id = 1
    existing.user_id = 42
    existing.status = MemberStatus.MEMBER
    existing.joined_at = None

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = existing

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.add = MagicMock()

    member, created = await upsert_group_member(
        mock_session,
        group_id=1,
        user_id=42,
        status=MemberStatus.ADMIN,
    )

    assert created is False
    assert member.status == MemberStatus.ADMIN
    mock_session.add.assert_not_called()


# ── SyncJob ───────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_sync_job() -> None:
    from app.db.repositories.repos import create_sync_job

    mock_session = AsyncMock()
    mock_session.add = MagicMock()
    mock_session.flush = AsyncMock()

    job = await create_sync_job(mock_session, group_id=5)

    assert job.group_id == 5
    assert job.status == SyncStatus.PENDING
    assert job.processed_count == 0
    mock_session.add.assert_called_once()
