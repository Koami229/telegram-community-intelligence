"""
Tests: Group service — identifier parsing and mock-based resolution.
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.group_service import (
    GroupAccessError,
    GroupResolutionError,
    _parse_identifier,
    _determine_group_type,
    resolve_and_save_group,
)
from app.models.models import GroupType


# ── Identifier parsing ────────────────────────────────────────────────────────

def test_parse_identifier_username_with_at() -> None:
    assert _parse_identifier("@mygroup") == "mygroup"


def test_parse_identifier_username_without_at() -> None:
    assert _parse_identifier("mygroup") == "mygroup"


def test_parse_identifier_tme_url() -> None:
    assert _parse_identifier("https://t.me/mygroup") == "mygroup"


def test_parse_identifier_numeric_id() -> None:
    assert _parse_identifier("-1001234567890") == "-1001234567890"


def test_parse_identifier_strips_whitespace() -> None:
    assert _parse_identifier("  @hello  ") == "hello"


def test_parse_identifier_joinchat_link() -> None:
    result = _parse_identifier("https://t.me/joinchat/AAABBB")
    assert "joinchat" in result


def test_parse_identifier_joinchat_without_https() -> None:
    result = _parse_identifier("t.me/joinchat/AAABBB")
    assert result.startswith("https://")


# ── Group type detection ──────────────────────────────────────────────────────

def test_determine_group_type_supergroup() -> None:
    from telethon.tl.types import Channel
    entity = MagicMock(spec=Channel)
    entity.broadcast = False
    assert _determine_group_type(entity) == GroupType.SUPERGROUP


def test_determine_group_type_channel() -> None:
    from telethon.tl.types import Channel
    entity = MagicMock(spec=Channel)
    entity.broadcast = True
    assert _determine_group_type(entity) == GroupType.CHANNEL


def test_determine_group_type_chat() -> None:
    from telethon.tl.types import Chat
    entity = MagicMock(spec=Chat)
    assert _determine_group_type(entity) == GroupType.GROUP


def test_determine_group_type_unknown() -> None:
    assert _determine_group_type(object()) == GroupType.UNKNOWN


# ── resolve_and_save_group ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_resolve_raises_when_not_authenticated() -> None:
    mock_session = AsyncMock()
    with patch("app.services.group_service.telegram_service") as mock_tg:
        mock_tg.is_connected.return_value = False
        mock_tg.is_authorized = AsyncMock(return_value=False)
        with pytest.raises(GroupAccessError, match="not authenticated"):
            await resolve_and_save_group(mock_session, "@somegroup")


@pytest.mark.asyncio
async def test_resolve_saves_group_to_db() -> None:
    from telethon.tl.types import Channel

    mock_entity = MagicMock(spec=Channel)
    mock_entity.id = 1234567890
    mock_entity.title = "Test Group"
    mock_entity.username = "testgroup"
    mock_entity.broadcast = False
    mock_entity.participants_count = 500

    mock_client = AsyncMock()
    mock_client.get_entity = AsyncMock(return_value=mock_entity)

    mock_group = MagicMock()
    mock_group.id = 1
    mock_group.telegram_group_id = -1001234567890
    mock_group.title = "Test Group"
    mock_group.username = "testgroup"
    mock_group.group_type = GroupType.SUPERGROUP
    mock_group.is_active = True
    mock_group.member_count = 500
    mock_group.first_synced_at = None
    mock_group.last_synced_at = None
    mock_group.created_at = None

    mock_session = AsyncMock()

    with (
        patch("app.services.group_service.telegram_service") as mock_tg,
        patch("app.services.group_service.create_or_get_group", return_value=(mock_group, True)) as mock_repo,
    ):
        mock_tg.is_connected.return_value = True
        mock_tg.is_authorized = AsyncMock(return_value=True)
        mock_tg.get_client.return_value = mock_client

        group, created = await resolve_and_save_group(mock_session, "@testgroup")

    assert created is True
    assert mock_repo.called
    call_kwargs = mock_repo.call_args.kwargs
    assert call_kwargs["title"] == "Test Group"
    assert call_kwargs["group_type"] == GroupType.SUPERGROUP
