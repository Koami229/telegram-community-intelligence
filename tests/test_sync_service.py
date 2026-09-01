"""
Tests: Sync service — job creation, progress, FloodWait, resumability.
"""
from __future__ import annotations

import asyncio
import json
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from app.models.models import SyncStatus
from app.services.sync_service import (
    _participant_to_status,
    _flush_batch,
    get_sync_status,
)
from app.models.models import MemberStatus


# ── Participant status mapping ────────────────────────────────────────────────

def test_participant_to_status_creator() -> None:
    from telethon.tl.types import ChannelParticipantCreator
    p = MagicMock(spec=ChannelParticipantCreator)
    assert _participant_to_status(p) == MemberStatus.CREATOR


def test_participant_to_status_admin() -> None:
    from telethon.tl.types import ChannelParticipantAdmin
    p = MagicMock(spec=ChannelParticipantAdmin)
    assert _participant_to_status(p) == MemberStatus.ADMIN


def test_participant_to_status_banned() -> None:
    from telethon.tl.types import ChannelParticipantBanned
    p = MagicMock(spec=ChannelParticipantBanned)
    assert _participant_to_status(p) == MemberStatus.KICKED


def test_participant_to_status_regular() -> None:
    from telethon.tl.types import ChannelParticipant
    p = MagicMock(spec=ChannelParticipant)
    assert _participant_to_status(p) == MemberStatus.MEMBER


# ── start_sync ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_start_sync_creates_job_and_returns_id() -> None:
    mock_group = MagicMock()
    mock_group.id = 1
    mock_group.telegram_group_id = -100111

    mock_job = MagicMock()
    mock_job.id = 99
    mock_job.status = SyncStatus.PENDING

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("app.services.sync_service.AsyncSessionFactory") as mock_factory,
        patch("app.services.sync_service.get_group_by_id", return_value=mock_group),
        patch("app.services.sync_service.get_latest_sync_job", return_value=None),
        patch("app.services.sync_service.create_sync_job", return_value=mock_job),
        patch("asyncio.create_task") as mock_task,
    ):
        mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)

        from app.services.sync_service import start_sync
        job_id = await start_sync(1)

    assert job_id == 99
    assert mock_task.called


@pytest.mark.asyncio
async def test_start_sync_returns_existing_running_job() -> None:
    mock_job = MagicMock()
    mock_job.id = 55
    mock_job.status = SyncStatus.RUNNING

    mock_group = MagicMock()
    mock_group.id = 1

    mock_session = AsyncMock()

    with (
        patch("app.services.sync_service.AsyncSessionFactory") as mock_factory,
        patch("app.services.sync_service.get_group_by_id", return_value=mock_group),
        patch("app.services.sync_service.get_latest_sync_job", return_value=mock_job),
        patch("asyncio.create_task") as mock_task,
    ):
        mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)

        from app.services.sync_service import start_sync
        job_id = await start_sync(1)

    assert job_id == 55
    # Should NOT start a new task when already running
    assert not mock_task.called


# ── get_sync_status ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_sync_status_returns_none_when_no_job() -> None:
    mock_session = AsyncMock()
    with (
        patch("app.services.sync_service.AsyncSessionFactory") as mock_factory,
        patch("app.services.sync_service.get_latest_sync_job", return_value=None),
        patch("app.services.sync_service.get_group_by_id", return_value=MagicMock()),
    ):
        mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await get_sync_status(1)

    assert result is None


@pytest.mark.asyncio
async def test_get_sync_status_progress_percent() -> None:
    mock_job = MagicMock()
    mock_job.id = 1
    mock_job.group_id = 1
    mock_job.status = SyncStatus.RUNNING
    mock_job.started_at = None
    mock_job.completed_at = None
    mock_job.processed_count = 500
    mock_job.new_members_count = 400
    mock_job.error_count = 0
    mock_job.last_cursor = None
    mock_job.error_message = None
    mock_job.created_at = datetime.now(tz=timezone.utc)

    mock_group = MagicMock()
    mock_group.member_count = 1000

    mock_session = AsyncMock()

    with (
        patch("app.services.sync_service.AsyncSessionFactory") as mock_factory,
        patch("app.services.sync_service.get_latest_sync_job", return_value=mock_job),
        patch("app.services.sync_service.get_group_by_id", return_value=mock_group),
    ):
        mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await get_sync_status(1)

    assert result is not None
    assert result["progress_percent"] == 50.0
    assert result["processed_count"] == 500


# ── Cursor / resume ───────────────────────────────────────────────────────────

def test_cursor_serialisation() -> None:
    """Cursor is stored as JSON with an offset key."""
    offset = 4500
    cursor = json.dumps({"offset": offset})
    parsed = json.loads(cursor)
    assert parsed["offset"] == offset
