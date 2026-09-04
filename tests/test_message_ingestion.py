"""Tests for authorized, metadata-only message ingestion."""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.message_ingestion_service import (
    IngestionError,
    download_media_file,
    ingest_messages,
    purge_expired_media,
)
from app.api.messages import delete_group_media


def test_message_endpoints_require_api_key(client: TestClient) -> None:
    response = client.get("/api/groups/1/messages", headers={"X-API-Key": ""})
    assert response.status_code == 401


def test_all_data_routers_require_api_key(client: TestClient) -> None:
    requests = (
        ("get", "/api/groups"),
        ("get", "/api/groups/1/members"),
        ("post", "/api/groups/1/sync"),
    )
    for method, path in requests:
        response = getattr(client, method)(path, headers={"X-API-Key": "wrong-key"})
        assert response.status_code == 401, f"{method.upper()} {path} was not protected"


@pytest.mark.asyncio
async def test_ingestion_rejects_unauthorized_telegram() -> None:
    session = AsyncMock()
    with patch("app.services.message_ingestion_service.telegram_service") as telegram:
        telegram.is_connected.return_value = False
        telegram.is_authorized = AsyncMock(return_value=False)

        with pytest.raises(IngestionError, match="not authenticated"):
            await ingest_messages(session, group_id=1)


@pytest.mark.asyncio
async def test_ingestion_rejects_inactive_group() -> None:
    session = AsyncMock()
    group = MagicMock(is_active=False)
    with (
        patch("app.services.message_ingestion_service.telegram_service") as telegram,
        patch("app.services.message_ingestion_service.get_group_by_id", new_callable=AsyncMock, return_value=group),
    ):
        telegram.is_connected.return_value = True
        telegram.is_authorized = AsyncMock(return_value=True)

        with pytest.raises(IngestionError, match="not registered or active"):
            await ingest_messages(session, group_id=1)


@pytest.mark.asyncio
async def test_ingestion_rejects_group_without_collection_authorization() -> None:
    session = AsyncMock()
    group = SimpleNamespace(is_active=True, collection_authorized=False)
    with (
        patch("app.services.message_ingestion_service.telegram_service") as telegram,
        patch("app.services.message_ingestion_service.get_group_by_id", new_callable=AsyncMock, return_value=group),
    ):
        telegram.is_connected.return_value = True
        telegram.is_authorized = AsyncMock(return_value=True)

        with pytest.raises(IngestionError, match="authorization"):
            await ingest_messages(session, group_id=1)


@pytest.mark.asyncio
async def test_media_download_is_disabled_by_default() -> None:
    session = AsyncMock()
    settings = MagicMock(media_download_enabled=False)
    with patch("app.services.message_ingestion_service.get_settings", return_value=settings):
        with pytest.raises(IngestionError, match="disabled by configuration"):
            await download_media_file(session, group_id=1, media_id=1)


@pytest.mark.asyncio
async def test_media_retention_is_disabled_by_default() -> None:
    session = AsyncMock()
    settings = MagicMock(media_retention_days=0)
    with patch("app.services.message_ingestion_service.get_settings", return_value=settings):
        assert await purge_expired_media(session, group_id=1) == 0
    session.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_ingestion_stores_message_and_media_metadata() -> None:
    from telethon.tl.types import DocumentAttributeFilename

    async def messages(*args, **kwargs):
        yield SimpleNamespace(
            id=42,
            date=datetime.now(timezone.utc),
            sender_id=7,
            message="Monthly report",
            photo=None,
            document=SimpleNamespace(
                id=99,
                mime_type="application/pdf",
                size=1234,
                attributes=[DocumentAttributeFilename(file_name="report.pdf")],
            ),
        )

    group = SimpleNamespace(
        id=1,
        telegram_group_id=-100123,
        is_active=True,
        collection_authorized=True,
    )
    stored_message = SimpleNamespace(id=8)
    client = MagicMock()
    client.get_entity = AsyncMock(return_value=object())
    client.iter_messages = messages

    with (
        patch("app.services.message_ingestion_service.telegram_service") as telegram,
        patch("app.services.message_ingestion_service.get_group_by_id", new_callable=AsyncMock, return_value=group),
        patch("app.services.message_ingestion_service.upsert_telegram_message", new_callable=AsyncMock, return_value=(stored_message, True)) as save_message,
        patch("app.services.message_ingestion_service.upsert_telegram_media", new_callable=AsyncMock) as save_media,
    ):
        telegram.is_connected.return_value = True
        telegram.is_authorized = AsyncMock(return_value=True)
        telegram.get_client.return_value = client

        processed = await ingest_messages(AsyncMock(), group_id=1, limit=10)

    assert processed == 1
    assert save_message.await_count == 1
    assert save_media.await_count == 1
    assert save_media.await_args.kwargs["mime_type"] == "application/pdf"


@pytest.mark.asyncio
async def test_delete_media_removes_local_copy(tmp_path) -> None:
    local_file = tmp_path / "42-0.pdf"
    local_file.write_bytes(b"archived media")
    media = SimpleNamespace(local_path=str(local_file))
    with patch("app.api.messages.delete_telegram_media", new_callable=AsyncMock, return_value=media):
        await delete_group_media(1, 9, AsyncMock())
    assert not local_file.exists()