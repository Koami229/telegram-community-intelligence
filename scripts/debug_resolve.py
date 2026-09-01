"""
scripts/debug_resolve.py — Test de résolution d'entité Telegram (debug).
Usage: cd backend/ && python scripts/debug_resolve.py
"""
import asyncio
import selectors
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from telethon import TelegramClient
from app.core.config import get_settings


async def debug_resolve() -> None:
    settings = get_settings()
    session_path = os.path.join(
        os.path.dirname(__file__), "..", "sessions", settings.telegram_session_name
    )

    client = TelegramClient(
        session_path,
        settings.telegram_api_id,
        settings.telegram_api_hash,
    )

    try:
        await client.connect()
        me = await client.get_me()
        print(f"Connected as: {me.first_name} (id={me.id})")
        print()

        TARGET_ID = 4492780640

        # Test 1: raw positive int
        print(f"Test 1: get_entity({TARGET_ID}) as raw int...")
        try:
            entity = await client.get_entity(TARGET_ID)
            title = getattr(entity, "title", None)
            uname = getattr(entity, "username", None)
            print(f"  OK -> type={type(entity).__name__}  title={title!r}  username={uname!r}  id={entity.id}")
        except Exception as e:
            print(f"  FAIL: {type(e).__name__}: {e}")

        # Test 2: -100 prefix
        neg_id = int(f"-100{TARGET_ID}")
        print(f"\nTest 2: get_entity({neg_id}) as -100 prefix...")
        try:
            entity = await client.get_entity(neg_id)
            title = getattr(entity, "title", None)
            print(f"  OK -> type={type(entity).__name__}  title={title!r}  id={entity.id}")
        except Exception as e:
            print(f"  FAIL: {type(e).__name__}: {e}")

        # Test 3: find in dialog cache then use entity directly
        print(f"\nTest 3: find in dialogs cache (limit=50)...")
        dialogs = await client.get_dialogs(limit=50)
        found_entity = None
        for d in dialogs:
            if d.entity.id == TARGET_ID:
                found_entity = d.entity
                break
        if found_entity:
            title = getattr(found_entity, "title", None)
            etype = type(found_entity).__name__
            print(f"  Found in dialogs: type={etype}  title={title!r}  id={found_entity.id}")
            print(f"  broadcast={getattr(found_entity,'broadcast',None)}  megagroup={getattr(found_entity,'megagroup',None)}")

            print(f"\nTest 4: get_entity(found_entity) from dialog...")
            try:
                entity = await client.get_entity(found_entity)
                title = getattr(entity, "title", None)
                print(f"  OK -> type={type(entity).__name__}  title={title!r}  id={entity.id}")
            except Exception as e:
                print(f"  FAIL: {type(e).__name__}: {e}")

            print(f"\nTest 5: get_participants on found entity (limit=10)...")
            try:
                from telethon.tl.functions.channels import GetParticipantsRequest
                from telethon.tl.types import ChannelParticipantsRecent
                participants = await client.get_participants(found_entity, limit=10)
                print(f"  OK -> got {len(participants)} participants")
                for p in participants[:5]:
                    fn = getattr(p, "first_name", None) or ""
                    ln = getattr(p, "last_name", None) or ""
                    un = getattr(p, "username", None)
                    print(f"    id={p.id}  name={fn} {ln}  @{un}")
            except Exception as e:
                print(f"  FAIL: {type(e).__name__}: {e}")
        else:
            print(f"  Not found in dialogs cache (total dialogs: {len(dialogs)})")

    finally:
        try:
            await client.disconnect()
        except Exception:
            pass


def main() -> None:
    loop = asyncio.SelectorEventLoop(selectors.SelectSelector())
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(debug_resolve())
    finally:
        pending = asyncio.all_tasks(loop)
        if pending:
            loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        loop.close()


if __name__ == "__main__":
    main()
