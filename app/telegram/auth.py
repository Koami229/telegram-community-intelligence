"""
Telegram authentication helpers.

Provides a reusable async function that handles the full Telethon
interactive sign-in flow:

    1. Connect to Telegram
    2. Send the verification code to the phone
    3. Accept the code
    4. Handle 2FA (password) if enabled
    5. Persist the session to disk

Never prints or logs API_HASH, passwords, or session strings.
"""
from __future__ import annotations

import logging
import os
from typing import Callable, Optional

from telethon import TelegramClient
from telethon.errors import (
    FloodWaitError,
    PhoneCodeExpiredError,
    PhoneCodeInvalidError,
    PhoneNumberBannedError,
    PhoneNumberInvalidError,
    SessionPasswordNeededError,
)

from app.core.config import get_settings

logger = logging.getLogger(__name__)


class AuthenticationError(Exception):
    """Raised when the Telegram authentication flow fails."""


class TelegramAuthService:
    """
    Handles the interactive Telethon sign-in flow.

    Designed to be used both from the CLI script and — in future — from a
    web-based auth endpoint.

    The ``prompt_fn`` parameter allows injecting a custom input function
    (useful for testing without stdin).
    """

    def __init__(
        self,
        prompt_fn: Optional[Callable[[str], str]] = None,
    ) -> None:
        self._prompt = prompt_fn or input
        self._settings = get_settings()

    def _session_path(self) -> str:
        return os.path.join(
            self._settings.telegram_session_path,
            self._settings.telegram_session_name,
        )

    async def authenticate(self) -> bool:
        """
        Run the full interactive authentication flow.

        Returns True when the session is successfully authenticated.
        Raises AuthenticationError on unrecoverable failures.
        """
        if not self._settings.telegram_configured:
            raise AuthenticationError(
                "TELEGRAM_API_ID and TELEGRAM_API_HASH must be set in .env"
            )

        # Ensure the sessions directory exists
        os.makedirs(self._settings.telegram_session_path, exist_ok=True)

        client = TelegramClient(
            session=self._session_path(),
            api_id=self._settings.telegram_api_id,
            api_hash=self._settings.telegram_api_hash,
        )

        try:
            await client.connect()

            if await client.is_user_authorized():
                me = await client.get_me()
                logger.info(
                    "✓ Already authenticated — user_id: %s",
                    me.id if me else "unknown",
                )
                return True

            # ── Step 1: Resolve phone number ─────────────────────────────
            phone = self._settings.telegram_phone
            if not phone:
                phone = self._prompt("Enter your Telegram phone number (e.g. +33612345678): ").strip()

            if not phone:
                raise AuthenticationError("Phone number is required.")

            logger.info("Sending verification code to phone (last 4 digits: …%s)…", phone[-4:])

            try:
                result = await client.send_code_request(phone)
            except PhoneNumberInvalidError:
                raise AuthenticationError(f"Phone number '{phone[-4:]}…' is not valid.")
            except PhoneNumberBannedError:
                raise AuthenticationError("This phone number has been banned by Telegram.")
            except FloodWaitError as e:
                raise AuthenticationError(
                    f"Telegram rate limit hit. Please wait {e.seconds}s before retrying."
                )

            # ── Step 2: Enter the code ────────────────────────────────────
            code = self._prompt("Enter the Telegram verification code: ").strip()
            if not code:
                raise AuthenticationError("Verification code cannot be empty.")

            try:
                await client.sign_in(phone=phone, code=code, phone_code_hash=result.phone_code_hash)
                logger.info("✓ Telegram authentication successful")
                return True

            except PhoneCodeInvalidError:
                raise AuthenticationError("The verification code is incorrect.")
            except PhoneCodeExpiredError:
                raise AuthenticationError("The verification code has expired. Please restart the auth flow.")
            except SessionPasswordNeededError:
                # ── Step 3: 2FA password ──────────────────────────────────
                logger.info("Two-factor authentication (2FA) is enabled on this account.")
                password = self._prompt("Enter your 2FA password: ").strip()
                if not password:
                    raise AuthenticationError("2FA password cannot be empty.")
                try:
                    await client.sign_in(password=password)
                    logger.info("✓ Telegram 2FA authentication successful")
                    return True
                except Exception as exc:
                    raise AuthenticationError(f"2FA authentication failed: {exc}") from exc

        except AuthenticationError:
            raise
        except Exception as exc:
            raise AuthenticationError(f"Unexpected error during authentication: {exc}") from exc
        finally:
            # Always disconnect the temporary auth client — the main
            # TelegramClientService will reconnect using the saved session.
            if client.is_connected():
                await client.disconnect()

    async def check_session(self) -> dict:
        """
        Check the current session status without modifying it.

        Returns a dict with keys: authenticated, user_id, username.
        """
        if not self._settings.telegram_configured:
            return {"authenticated": False, "reason": "credentials_not_configured"}

        client = TelegramClient(
            session=self._session_path(),
            api_id=self._settings.telegram_api_id,
            api_hash=self._settings.telegram_api_hash,
        )
        try:
            await client.connect()
            if not await client.is_user_authorized():
                return {"authenticated": False, "reason": "not_authorized"}
            me = await client.get_me()
            return {
                "authenticated": True,
                "user_id": me.id if me else None,
                "username": me.username if me else None,
            }
        except Exception as exc:
            return {"authenticated": False, "reason": str(exc)}
        finally:
            if client.is_connected():
                await client.disconnect()
