"""
Group service — resolves a Telegram group and persists it to the database.

Responsibilities:
  - Accept a user-supplied identifier (@username, t.me link, or numeric ID)
  - Use Telethon to resolve and validate the entity
  - Determine the group type
  - Insert/update the Group row in PostgreSQL
  - Never access groups the authenticated account cannot see
"""
from __future__ import annotations

import logging
import re
from typing import Optional

from telethon.errors import (
    ChannelInvalidError,
    ChannelPrivateError,
    FloodWaitError,
    InviteHashExpiredError,
    InviteHashInvalidError,
    UsernameInvalidError,
    UsernameNotOccupiedError,
)
from telethon.tl.types import (
    Channel,
    Chat,
    InputPeerChannel,
    InputPeerChat,
)

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.repos import create_or_get_group
from app.models.models import Group, GroupType
from app.telegram.client import telegram_service

logger = logging.getLogger(__name__)


class GroupResolutionError(Exception):
    """Raised when the group cannot be resolved via Telegram."""


class GroupAccessError(Exception):
    """Raised when the account does not have access to the group."""


def _parse_identifier(raw: str) -> str:
    """
    Normalise user-supplied group identifier to a form Telethon accepts.

    Supported inputs:
      - @username         → username (strip @)
      - https://t.me/username → username
      - https://t.me/joinchat/... → full URL (Telethon handles join links)
      - -100XXXXXXXXXX    → integer string (kept as-is, cast to int later)
    """
    raw = raw.strip()

    # Numeric ID (positive or negative)
    if re.match(r"^-?\d+$", raw):
        return raw

    # t.me invite link — return full URL for Telethon
    if "t.me/joinchat/" in raw or "t.me/+" in raw:
        if not raw.startswith("http"):
            return "https://" + raw
        return raw

    # t.me/username → extract username
    m = re.match(r"https?://t\.me/([A-Za-z0-9_]+)$", raw)
    if m:
        return m.group(1)

    # @username → strip @
    if raw.startswith("@"):
        return raw[1:]

    return raw


def _determine_group_type(entity: object) -> GroupType:
    """Map a Telethon entity type to our GroupType enum."""
    if isinstance(entity, Channel):
        if getattr(entity, "broadcast", False):
            return GroupType.CHANNEL
        return GroupType.SUPERGROUP
    if isinstance(entity, Chat):
        return GroupType.GROUP
    return GroupType.UNKNOWN


async def resolve_and_save_group(
    session: AsyncSession,
    identifier: str,
    collection_authorized: Optional[bool] = None,
    media_download_authorized: Optional[bool] = None,
) -> tuple[Group, bool]:
    """
    Resolve ``identifier`` via Telegram and persist the group.

    Returns (group, created).
    Raises GroupResolutionError or GroupAccessError on failure.
    """
    if not telegram_service.is_connected() or not await telegram_service.is_authorized():
        raise GroupAccessError(
            "Telegram account is not authenticated. "
            "Run scripts/auth_telegram.py first."
        )

    client = telegram_service.get_client()
    parsed = _parse_identifier(identifier)

    logger.info("Resolving group identifier: %r (parsed: %r)", identifier, parsed)

    try:
        # Cast numeric string to int so Telethon resolves by ID
        lookup: object = int(parsed) if re.match(r"^-?\d+$", parsed) else parsed
        entity = await client.get_entity(lookup)
    except (UsernameInvalidError, UsernameNotOccupiedError) as exc:
        raise GroupResolutionError(
            f"Username '{parsed}' is invalid or does not exist."
        ) from exc
    except ChannelPrivateError as exc:
        raise GroupAccessError(
            "This group is private and your account is not a member."
        ) from exc
    except ChannelInvalidError as exc:
        raise GroupResolutionError(f"Invalid channel/group reference: {exc}") from exc
    except (InviteHashInvalidError, InviteHashExpiredError) as exc:
        raise GroupResolutionError(
            "The invite link is invalid or has expired."
        ) from exc
    except FloodWaitError as exc:
        raise GroupResolutionError(
            f"Telegram rate limit hit. Please wait {exc.seconds}s before retrying."
        ) from exc
    except Exception as exc:
        raise GroupResolutionError(f"Could not resolve group '{parsed}': {exc}") from exc

    # Extract metadata
    entity_id: int = entity.id  # type: ignore[union-attr]
    title: Optional[str] = getattr(entity, "title", None)
    username: Optional[str] = getattr(entity, "username", None)
    group_type = _determine_group_type(entity)

    # For supergroups/channels Telegram uses access_hash-qualified IDs.
    # The canonical storage form is the negative int (-100 prefix).
    if isinstance(entity, Channel):
        entity_id = int(f"-100{entity.id}")

    member_count: Optional[int] = None
    if hasattr(entity, "participants_count"):
        member_count = entity.participants_count

    logger.info(
        "Group resolved — title=%r type=%s telegram_id=%s members=%s",
        title,
        group_type.value,
        entity_id,
        member_count,
    )

    group, created = await create_or_get_group(
        session,
        telegram_group_id=entity_id,
        title=title,
        username=username,
        group_type=group_type,
        member_count=member_count,
        collection_authorized=collection_authorized,
        media_download_authorized=media_download_authorized,
    )
    return group, created
