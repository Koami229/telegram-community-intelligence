"""
Tests: Telegram authentication service (no real Telegram connection).
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.telegram.auth import AuthenticationError, TelegramAuthService


@pytest.mark.asyncio
async def test_authenticate_raises_when_not_configured() -> None:
    auth = TelegramAuthService()
    mock_settings = MagicMock()
    mock_settings.telegram_configured = False
    auth._settings = mock_settings
    with pytest.raises(AuthenticationError, match="TELEGRAM_API_ID"):
        await auth.authenticate()


@pytest.mark.asyncio
async def test_authenticate_returns_true_if_already_authorized() -> None:
    mock_me = MagicMock()
    mock_me.id = 42

    mock_client = AsyncMock()
    mock_client.connect = AsyncMock()
    mock_client.is_connected.return_value = True
    mock_client.is_user_authorized = AsyncMock(return_value=True)
    mock_client.get_me = AsyncMock(return_value=mock_me)
    mock_client.disconnect = AsyncMock()

    auth = TelegramAuthService(prompt_fn=lambda _: "")
    with (
        patch("app.telegram.auth.TelegramClient", return_value=mock_client),
        patch.object(auth, "_settings") as ms,
    ):
        ms.telegram_configured = True
        ms.telegram_api_id = 123
        ms.telegram_api_hash = "hash"
        ms.telegram_session_path = "sessions"
        ms.telegram_session_name = "test"
        ms.telegram_phone = "+33600000000"

        result = await auth.authenticate()

    assert result is True


@pytest.mark.asyncio
async def test_authenticate_invalid_code() -> None:
    from telethon.errors import PhoneCodeInvalidError

    mock_result = MagicMock()
    mock_result.phone_code_hash = "abc123"

    mock_client = AsyncMock()
    mock_client.connect = AsyncMock()
    mock_client.is_connected.return_value = True
    mock_client.is_user_authorized = AsyncMock(return_value=False)
    mock_client.send_code_request = AsyncMock(return_value=mock_result)
    mock_client.sign_in = AsyncMock(side_effect=PhoneCodeInvalidError(None))
    mock_client.disconnect = AsyncMock()

    prompts = iter(["+33600000000", "12345"])
    auth = TelegramAuthService(prompt_fn=lambda _: next(prompts))

    with (
        patch("app.telegram.auth.TelegramClient", return_value=mock_client),
        patch.object(auth, "_settings") as ms,
    ):
        ms.telegram_configured = True
        ms.telegram_api_id = 123
        ms.telegram_api_hash = "hash"
        ms.telegram_session_path = "sessions"
        ms.telegram_session_name = "test"
        ms.telegram_phone = ""

        with pytest.raises(AuthenticationError, match="incorrect"):
            await auth.authenticate()


@pytest.mark.asyncio
async def test_check_session_not_configured() -> None:
    auth = TelegramAuthService()
    with patch.object(auth, "_settings") as ms:
        ms.telegram_configured = False
        result = await auth.check_session()
    assert result["authenticated"] is False
    assert result["reason"] == "credentials_not_configured"


@pytest.mark.asyncio
async def test_check_session_not_authorized() -> None:
    mock_client = AsyncMock()
    mock_client.connect = AsyncMock()
    mock_client.is_connected.return_value = True
    mock_client.is_user_authorized = AsyncMock(return_value=False)
    mock_client.disconnect = AsyncMock()

    auth = TelegramAuthService()
    with (
        patch("app.telegram.auth.TelegramClient", return_value=mock_client),
        patch.object(auth, "_settings") as ms,
    ):
        ms.telegram_configured = True
        ms.telegram_api_id = 123
        ms.telegram_api_hash = "hash"
        ms.telegram_session_path = "sessions"
        ms.telegram_session_name = "test"

        result = await auth.check_session()

    assert result["authenticated"] is False
    assert result["reason"] == "not_authorized"
