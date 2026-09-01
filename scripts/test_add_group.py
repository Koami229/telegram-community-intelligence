"""
scripts/test_add_group.py — Test direct de resolve_and_save_group sans HTTP.
Usage: cd backend/ && python scripts/test_add_group.py <identifier>
"""
import asyncio
import selectors
import sys
import os
import traceback

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.core.config import get_settings
from app.db.database import AsyncSessionFactory


async def test_add(identifier: str) -> None:
    print(f"Testing resolve_and_save_group('{identifier}')")
    print()

    # Import here so the event loop is already set
    from app.telegram.client import telegram_service
    from app.services.group_service import resolve_and_save_group, GroupResolutionError, GroupAccessError

    # Connect Telegram
    print("Connecting Telegram...")
    ok = await telegram_service.connect()
    if not ok:
        print("ERROR: Telegram not connected. Run auth script first.")
        return
    print(f"  Telegram connected: {ok}")

    # Open DB session
    async with AsyncSessionFactory() as session:
        try:
            print(f"Calling resolve_and_save_group(session, '{identifier}')...")
            group, created = await resolve_and_save_group(session, identifier)
            await session.commit()
            print()
            print("SUCCESS!")
            print(f"  id              = {group.id}")
            print(f"  telegram_group_id = {group.telegram_group_id}")
            print(f"  title           = {group.title!r}")
            print(f"  username        = {group.username!r}")
            print(f"  group_type      = {group.group_type}")
            print(f"  member_count    = {group.member_count}")
            print(f"  created         = {created}")
        except GroupAccessError as e:
            print(f"GroupAccessError: {e}")
        except GroupResolutionError as e:
            print(f"GroupResolutionError: {e}")
        except Exception as e:
            print(f"Unexpected error: {type(e).__name__}: {e}")
            traceback.print_exc()

    await telegram_service.disconnect()


def main() -> None:
    identifier = sys.argv[1] if len(sys.argv) > 1 else "4492780640"
    print(f"[debug_add_group] identifier = {identifier!r}")
    print()

    loop = asyncio.SelectorEventLoop(selectors.SelectSelector())
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(test_add(identifier))
    finally:
        pending = asyncio.all_tasks(loop)
        if pending:
            loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        loop.close()


if __name__ == "__main__":
    main()
