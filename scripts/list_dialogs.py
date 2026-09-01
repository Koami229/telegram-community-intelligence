"""
scripts/list_dialogs.py — Liste les groupes/supergroups/channels accessibles.

Lecture seule. Ne modifie rien. N'enregistre rien en base.
Affiche uniquement les informations non-sensibles.

Usage:
    cd backend/
    python scripts/list_dialogs.py
    python scripts/list_dialogs.py --type group
    python scripts/list_dialogs.py --type supergroup
    python scripts/list_dialogs.py --type channel
    python scripts/list_dialogs.py --limit 50
"""
from __future__ import annotations

import argparse
import asyncio
import selectors
import sys
import os

# Force UTF-8 output on Windows to avoid cp1252 UnicodeEncodeError
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from telethon import TelegramClient
from telethon.tl.types import Channel, Chat

from app.core.config import get_settings


LABELS = {
    "supergroup": "[SUPERGROUP]",
    "group":      "[GROUP]     ",
    "channel":    "[CHANNEL]   ",
    "bot":        "[BOT]       ",
    "user":       "[USER]      ",
}

SECTION_HEADERS = {
    "supergroup": "SUPERGROUPS / PRIVATE GROUPS",
    "group":      "CLASSIC GROUPS (Chat)",
    "channel":    "CHANNELS",
}


async def list_dialogs(filter_type: str | None, limit: int) -> None:
    settings = get_settings()

    if not settings.telegram_configured:
        print("[ERROR] Telegram credentials not configured. Check your .env file.")
        sys.exit(1)

    session_path = os.path.join(
        os.path.dirname(__file__), "..", settings.telegram_session_path,
        settings.telegram_session_name,
    )

    client = TelegramClient(
        session_path,
        settings.telegram_api_id,
        settings.telegram_api_hash,
    )

    try:
        await client.connect()

        if not await client.is_user_authorized():
            print("[ERROR] Session not authorized. Run scripts/auth_telegram.py first.")
            return

        me = await client.get_me()
        print()
        print("=" * 65)
        print("  Telegram Community Intelligence -- Dialog List")
        print("=" * 65)
        print(f"  Connected as : {(me.first_name or '')} {(me.last_name or '')}".strip())
        print(f"  User ID      : {me.id}")
        if me.username:
            print(f"  Username     : @{me.username}")
        print("=" * 65)
        print()

        buckets: dict[str, list[dict]] = {
            "supergroup": [],
            "group": [],
            "channel": [],
            "user": [],
            "bot": [],
        }

        print(f"Fetching up to {limit} dialogs from Telegram...")
        dialogs = await client.get_dialogs(limit=limit)
        print(f"  -> Received {len(dialogs)} dialogs.")
        print()

        for dialog in dialogs:
            entity = dialog.entity

            if isinstance(entity, Channel):
                if entity.megagroup or entity.gigagroup:
                    dtype = "supergroup"
                else:
                    dtype = "channel"
            elif isinstance(entity, Chat):
                dtype = "group"
            else:
                if getattr(entity, 'bot', False):
                    dtype = "bot"
                else:
                    dtype = "user"

            title = (
                getattr(entity, 'title', None)
                or f"{getattr(entity,'first_name','') or ''} {getattr(entity,'last_name','') or ''}".strip()
                or "(no title)"
            )

            info = {
                "id":            entity.id,
                "title":         title,
                "username":      getattr(entity, 'username', None),
                "type":          dtype,
                "members_count": getattr(entity, 'participants_count', None),
            }
            buckets[dtype].append(info)

        # ── Display ──────────────────────────────────────────────────────────
        show_types = [filter_type] if filter_type else ["supergroup", "group", "channel"]

        total = 0
        for dtype in show_types:
            items = buckets.get(dtype, [])
            header = SECTION_HEADERS.get(dtype, dtype.upper())
            print(f"--- {header} ({len(items)}) ---")
            if not items:
                print("  (none)")
            else:
                for item in items:
                    uid     = item["id"]
                    title   = item["title"]
                    uname   = f"@{item['username']}" if item.get("username") else "(no username)"
                    members = item.get("members_count")
                    m_str   = f"  [{members:,} members]" if members else ""
                    label   = LABELS.get(dtype, "          ")
                    print(f"  {label} ID={uid:<15}  {title:<40} {uname}{m_str}")
                    total += 1
            print()

        print(f"Total shown: {total} group/channel dialogs")
        print()
        print("To add a group to TCI, use:")
        print("  Numeric ID  (e.g. -1001234567890  or just  1234567890)")
        print("  @username   (e.g. @mygroupname)")
        print("  t.me URL    (e.g. https://t.me/mygroupname)")
        print()

    finally:
        # Disconnect properly so Telethon can cancel its internal tasks cleanly
        try:
            await client.disconnect()
        except Exception:
            pass


def main() -> None:
    parser = argparse.ArgumentParser(
        description="List Telegram dialogs accessible to the authenticated account."
    )
    parser.add_argument(
        "--type",
        choices=["group", "supergroup", "channel"],
        default=None,
        help="Filter by dialog type (default: show supergroups + groups + channels)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Maximum number of dialogs to fetch (default: 100)",
    )
    args = parser.parse_args()

    loop = asyncio.SelectorEventLoop(selectors.SelectSelector())
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(list_dialogs(args.type, args.limit))
    finally:
        # Give pending Telethon tasks a moment to clean up
        pending = asyncio.all_tasks(loop)
        if pending:
            loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        loop.close()


if __name__ == "__main__":
    main()
