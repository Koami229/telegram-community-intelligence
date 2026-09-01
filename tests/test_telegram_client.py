"""
Tests: TelegramClientService unit tests — no real Telegram connection.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.telegram.client import TelegramClientService


@pytest.mark.asyncio
async def test_connect_returns_false_when_not_configured() -> None:
    """connect() must return False and not raise when credentials are missing."""
    service = TelegramClientService()
    with patch("app.telegram.client.settings") as mock_settings:
        mock_settings.telegram_configured = False
        result = await service.connect()
    assert result is False
    assert not service.is_connected()


@pytest.mark.asyncio
async def test_connect_returns_false_when_not_authorized() -> None:
    """connect() returns False when session exists but is not authorized."""
    service = TelegramClientService()

    mock_client = AsyncMock()
    mock_client.connect = AsyncMock()
    mock_client.is_connected.return_value = True
    mock_client.is_user_authorized = AsyncMock(return_value=False)

    with (
        patch("app.telegram.client.settings") as mock_settings,
        patch("app.telegram.client.TelegramClient", return_value=mock_client),
    ):
        mock_settings.telegram_configured = True
        mock_settings.telegram_api_id = 12345
        mock_settings.telegram_api_hash = "fakehash"
        mock_settings.telegram_session_name = "test_session"

        result = await service.connect()

    assert result is False


@pytest.mark.asyncio
async def test_connect_returns_true_when_authorized() -> None:
    """connect() returns True when the session is authorized."""
    service = TelegramClientService()

    mock_me = MagicMock()
    mock_me.id = 999

    mock_client = AsyncMock()
    mock_client.connect = AsyncMock()
    mock_client.is_connected.return_value = True
    mock_client.is_user_authorized = AsyncMock(return_value=True)
    mock_client.get_me = AsyncMock(return_value=mock_me)

    with (
        patch("app.telegram.client.settings") as mock_settings,
        patch("app.telegram.client.TelegramClient", return_value=mock_client),
    ):
        mock_settings.telegram_configured = True
        mock_settings.telegram_api_id = 12345
        mock_settings.telegram_api_hash = "fakehash"
        mock_settings.telegram_session_name = "test_session"

        result = await service.connect()

    assert result is True


@pytest.mark.asyncio
async def test_disconnect_safe_when_not_connected() -> None:
    """disconnect() must not raise when called before connect()."""
    service = TelegramClientService()
    await service.disconnect()  # Should not raise
    assert not service.is_connected()


def test_get_client_raises_when_not_connected() -> None:
    """get_client() must raise RuntimeError before connect()."""
    service = TelegramClientService()
    with pytest.raises(RuntimeError, match="not connected"):
        service.get_client()


@pytest.mark.asyncio
async def test_is_authorized_returns_false_when_no_client() -> None:
    service = TelegramClientService()
    result = await service.is_authorized()
    assert result is False
