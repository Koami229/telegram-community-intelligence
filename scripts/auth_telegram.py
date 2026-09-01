#!/usr/bin/env python
"""
Interactive Telegram authentication script.

Run this once before starting the backend to create a persistent session:

    cd backend
    python scripts/auth_telegram.py

Requirements:
  - TELEGRAM_API_ID and TELEGRAM_API_HASH set in .env (or environment)
  - Your Telegram phone number ready

The session file will be saved in the directory specified by
TELEGRAM_SESSION_PATH (default: sessions/).

Security notes:
  - This script will NEVER display or log your API_HASH, password, or session.
  - The .session file grants full access to your Telegram account — protect it.
  - Add sessions/ to .gitignore (already done in this project).
"""
from __future__ import annotations

import asyncio
import logging
import sys

# Allow running from the backend/ directory
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.telegram.auth import TelegramAuthService, AuthenticationError
from app.core.config import get_settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
)
logger = logging.getLogger(__name__)


async def main() -> None:
    settings = get_settings()

    print("\n" + "=" * 60)
    print("  Telegram Community Intelligence — Authentication")
    print("=" * 60)

    if not settings.telegram_configured:
        print("\n❌  TELEGRAM_API_ID or TELEGRAM_API_HASH is not set.")
        print("    1. Go to https://my.telegram.org/apps")
        print("    2. Create an application")
        print("    3. Set TELEGRAM_API_ID and TELEGRAM_API_HASH in .env")
        sys.exit(1)

    print(f"\n  Session directory : {settings.telegram_session_path}")
    print(f"  Session name      : {settings.telegram_session_name}")
    print()

    auth = TelegramAuthService()

    # First check if already authenticated
    status = await auth.check_session()
    if status.get("authenticated"):
        print(f"✓ Already authenticated (user_id: {status.get('user_id')})")
        print("  No action needed. You can start the backend now.\n")
        return

    print("  Starting authentication flow…\n")

    try:
        success = await auth.authenticate()
        if success:
            print("\n✓ Authentication successful!")
            print("  You can now start the backend with:")
            print("    uvicorn app.main:app --reload\n")
        else:
            print("\n✗ Authentication failed.")
            sys.exit(1)
    except AuthenticationError as e:
        print(f"\n✗ Authentication error: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n\n  Aborted by user.")
        sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main())
