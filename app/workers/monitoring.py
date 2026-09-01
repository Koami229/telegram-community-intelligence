"""
Continuous monitoring worker — listens for new Telegram events in monitored groups.

After a group's initial sync is complete, this worker registers event handlers
that detect new members and left-member events in real time.

Design:
  - Uses Telethon's event system (ChatAction events)
  - Starts automatically on app startup if Telegram is authenticated
  - Gracefully handles reconnections and errors
  - Never bypasses Telegram rate limits or privacy settings
  - Only processes events for groups already registered in the database

ChatActionService.start_monitoring() is called from the FastAPI lifespan.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional, Set

from telethon import events
from telethon.tl.types import (
    MessageActionChatAddUser,
    MessageActionChatDeleteUser,
    MessageActionChatJoinedByLink,
    MessageActionChatJoinedByRequest,
)

from app.db.database import AsyncSessionFactory
from app.db.repositories.repos import (
    get_all_groups,
    upsert_group_member,
    upsert_user,
)
from app.models.models import MemberStatus
from app.telegram.client import telegram_service  # module-level for testability

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


class MonitoringWorker:
    """
    Registers Telethon event handlers for monitored groups.

    Usage::

        worker = MonitoringWorker()
        await worker.start()   # called in app lifespan
        ...
        await worker.stop()    # called on shutdown
    """

    def __init__(self) -> None:
        self._running = False
        self._monitored_group_ids: Set[int] = set()

    async def start(self) -> None:
        """
        Load monitored groups from DB and attach Telethon event handlers.
        Safe to call even when Telegram is not yet authenticated (no-op).
        """
        if not telegram_service.is_connected() or not await telegram_service.is_authorized():
            logger.info(
                "MonitoringWorker: Telegram not authenticated — "
                "monitoring will start after authentication."
            )
            return

        client = telegram_service.get_client()

        # Load the set of known group telegram IDs
        try:
            async with AsyncSessionFactory() as session:
                groups = await get_all_groups(session)
                self._monitored_group_ids = {g.telegram_group_id for g in groups}
        except Exception as exc:
            logger.warning("MonitoringWorker: Could not load groups: %s", exc)
            return

        if not self._monitored_group_ids:
            logger.info("MonitoringWorker: No monitored groups yet — nothing to watch.")

        # Register event handler for chat actions (join/leave)
        @client.on(events.ChatAction())
        async def _handle_chat_action(event: events.ChatAction.Event) -> None:
            try:
                await self._process_chat_action(event)
            except Exception as exc:
                logger.error("MonitoringWorker: Error processing event: %s", exc)

        self._running = True
        logger.info(
            "✓ MonitoringWorker started — watching %d group(s)",
            len(self._monitored_group_ids),
        )

    async def stop(self) -> None:
        """Stop the monitoring worker."""
        self._running = False
        logger.info("MonitoringWorker stopped.")

    def add_group(self, telegram_group_id: int) -> None:
        """Register a newly added group for monitoring."""
        self._monitored_group_ids.add(telegram_group_id)
        logger.info(
            "MonitoringWorker: Added group %s to watchlist (%d total)",
            telegram_group_id,
            len(self._monitored_group_ids),
        )

    async def _process_chat_action(
        self, event: events.ChatAction.Event
    ) -> None:
        """
        Process a Telegram chat action event.

        Handles:
        - User joined (via link, request, or direct add)
        - User left or was kicked
        """
        chat_id = event.chat_id

        # Only process events from monitored groups
        if chat_id not in self._monitored_group_ids:
            return

        # Determine what happened
        action = getattr(event.action_message, "action", None) if event.action_message else None

        if action is None:
            return

        now = _utcnow()

        # ── User joined ──────────────────────────────────────────────────────
        if isinstance(action, (
            MessageActionChatAddUser,
            MessageActionChatJoinedByLink,
            MessageActionChatJoinedByRequest,
        )):
            user_ids = getattr(action, "users", [])
            if not user_ids and event.user_id:
                user_ids = [event.user_id]

            for uid in user_ids:
                await self._upsert_member_from_event(
                    chat_id=chat_id,
                    user_id=uid,
                    status=MemberStatus.MEMBER,
                    joined_at=now,
                    event_type="joined",
                )

        # ── User left / kicked ───────────────────────────────────────────────
        elif isinstance(action, MessageActionChatDeleteUser):
            uid = getattr(action, "user_id", None) or event.user_id
            if uid:
                await self._upsert_member_from_event(
                    chat_id=chat_id,
                    user_id=uid,
                    status=MemberStatus.LEFT,
                    joined_at=None,
                    event_type="left",
                    left_at=now,
                )

    async def _upsert_member_from_event(
        self,
        *,
        chat_id: int,
        user_id: int,
        status: MemberStatus,
        joined_at: Optional[datetime],
        event_type: str,
        left_at: Optional[datetime] = None,
    ) -> None:
        """Fetch user info from Telegram and upsert into the database."""
        if not telegram_service.is_connected():
            return

        client = telegram_service.get_client()

        try:
            tg_user = await client.get_entity(user_id)
        except Exception as exc:
            logger.warning(
                "MonitoringWorker: Could not fetch user %s: %s", user_id, exc
            )
            return

        try:
            async with AsyncSessionFactory() as session:
                # Find the group's internal DB id
                from sqlalchemy import select as sa_select
                from app.models.models import Group
                result = await session.execute(
                    sa_select(Group).where(Group.telegram_group_id == chat_id)
                )
                group = result.scalar_one_or_none()
                if group is None:
                    logger.warning(
                        "MonitoringWorker: Group telegram_id=%s not in DB, skipping.",
                        chat_id,
                    )
                    return

                user = await upsert_user(
                    session,
                    telegram_id=tg_user.id,
                    username=getattr(tg_user, "username", None),
                    first_name=getattr(tg_user, "first_name", None),
                    last_name=getattr(tg_user, "last_name", None),
                    is_bot=getattr(tg_user, "bot", False),
                )

                member, created = await upsert_group_member(
                    session,
                    group_id=group.id,
                    user_id=user.id,
                    status=status,
                    joined_at=joined_at,
                )

                if left_at and member:
                    member.left_at = left_at

                await session.commit()

            action_label = "joined" if event_type == "joined" else "left"
            logger.info(
                "MonitoringWorker: user %s (@%s) %s group %s %s",
                tg_user.id,
                getattr(tg_user, "username", "?"),
                action_label,
                chat_id,
                "(new)" if created else "(updated)",
            )

        except Exception as exc:
            logger.error(
                "MonitoringWorker: DB error for user %s in group %s: %s",
                user_id, chat_id, exc,
            )


# Module-level singleton
monitoring_worker = MonitoringWorker()
