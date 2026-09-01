"""
Telegram client service — wraps Telethon with lifecycle management.

Sessions are stored as SQLite files in the directory configured by
TELEGRAM_SESSION_PATH (default: backend/sessions/).  The file is
excluded from Git via .gitignore.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

from telethon import TelegramClient
from telethon.errors import AuthKeyError

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


def _session_path() -> str:
    """Return the full session path: <session_dir>/<session_name>"""
    return os.path.join(settings.telegram_session_path, settings.telegram_session_name)


class TelegramClientService:
    """
    Thin wrapper around a Telethon TelegramClient.

    Usage::

        service = TelegramClientService()
        await service.connect()
        client = service.get_client()
        ...
        await service.disconnect()
    """

    def __init__(self) -> None:
        self._client: Optional[TelegramClient] = None

    # ── Lifecycle ────────────────────────────────────────────────────────────

    async def connect(self) -> bool:
        """
        Initialise and connect the Telethon client.

        Returns True on success, False if credentials are missing or
        connection fails.  Never logs API_HASH or SECRET_KEY.
        """
        if not settings.telegram_configured:
            logger.warning(
                "Telegram credentials not configured — set TELEGRAM_API_ID "
                "and TELEGRAM_API_HASH in your .env file."
            )
            return False

        try:
            self._client = TelegramClient(
                session=_session_path(),
                api_id=settings.telegram_api_id,
                # api_hash is intentionally not logged anywhere in this service
                api_hash=settings.telegram_api_hash,
            )
            await self._client.connect()

            if not await self._client.is_user_authorized():
                logger.info(
                    "Telegram session '%s' is not yet authorized. "
                    "Run the interactive auth script to complete login.",
                    settings.telegram_session_name,
                )
                return False

            me = await self._client.get_me()
            logger.info(
                "✓ Telegram connected — session: %s  user_id: %s",
                settings.telegram_session_name,
                me.id if me else "unknown",
            )
            return True

        except AuthKeyError:
            logger.error(
                "Telegram auth key is invalid or revoked. "
                "Delete the .session file and re-authenticate."
            )
            self._client = None
            return False
        except Exception as exc:
            logger.error("Telegram connection failed: %s", exc)
            self._client = None
            return False

    async def disconnect(self) -> None:
        """Gracefully close the Telethon connection."""
        if self._client and self._client.is_connected():
            await self._client.disconnect()
            logger.info("Telegram client disconnected.")
        self._client = None

    # ── Status ───────────────────────────────────────────────────────────────

    def is_connected(self) -> bool:
        """Return True if the client exists and reports connected."""
        return bool(self._client and self._client.is_connected())

    async def is_authorized(self) -> bool:
        """Return True if the active session is fully authenticated."""
        if not self._client:
            return False
        try:
            return await self._client.is_user_authorized()
        except Exception:
            return False

    # ── Accessor ─────────────────────────────────────────────────────────────

    def get_client(self) -> TelegramClient:
        """Return the underlying TelegramClient (raises if not connected)."""
        if not self._client:
            raise RuntimeError(
                "TelegramClientService is not connected. Call connect() first."
            )
        return self._client


# Module-level singleton — shared across the FastAPI app lifetime
telegram_service = TelegramClientService()
