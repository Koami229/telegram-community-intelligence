"""
Tests: GET /api/groups/{id}/members endpoint.
Uses dependency_overrides to avoid touching psycopg/DB engine.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.db.database import get_db_session
from app.main import app
from app.models.models import GroupType, MemberStatus


def _mock_group(id: int = 1) -> MagicMock:
    g = MagicMock()
    g.id = id
    g.telegram_group_id = -1001234567890
    g.title = "Test Group"
    g.username = "testgroup"
    g.group_type = GroupType.SUPERGROUP
    g.is_active = True
    g.member_count = 500
    g.first_synced_at = None
    g.last_synced_at = None
    g.created_at = datetime.now(tz=timezone.utc)
    return g


def _make_fake_session(total: int = 0, rows: list | None = None):
    """Build a mock AsyncSession for the members endpoint."""
    mock_session = AsyncMock()

    mock_total_result = MagicMock()
    mock_total_result.scalar_one.return_value = total

    mock_rows_result = MagicMock()
    mock_rows_result.all.return_value = rows or []

    mock_session.execute = AsyncMock(side_effect=[mock_total_result, mock_rows_result])
    return mock_session


def _override_db(session):
    """Return a FastAPI dependency override that yields ``session``."""
    async def _dep():
        yield session
    return _dep


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_list_members_group_not_found(client: TestClient) -> None:
    with patch("app.api.members.get_group_by_id", new_callable=AsyncMock, return_value=None):
        response = client.get("/api/groups/999/members")
    assert response.status_code == 404


def test_list_members_empty() -> None:
    mock_session = _make_fake_session(total=0)
    mock_group = _mock_group()

    app.dependency_overrides[get_db_session] = _override_db(mock_session)
    try:
        with (
            TestClient(app, headers={"X-API-Key": "test-ingestion-key"}) as c,
            patch("app.api.members.get_group_by_id", new_callable=AsyncMock, return_value=mock_group),
        ):
            response = c.get("/api/groups/1/members")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 0
    assert body["items"] == []
    assert body["page"] == 1
    assert body["pages"] == 1


def test_list_members_pagination_params() -> None:
    mock_session = _make_fake_session(total=0)
    mock_group = _mock_group()

    app.dependency_overrides[get_db_session] = _override_db(mock_session)
    try:
        with (
            TestClient(app, headers={"X-API-Key": "test-ingestion-key"}) as c,
            patch("app.api.members.get_group_by_id", new_callable=AsyncMock, return_value=mock_group),
        ):
            response = c.get("/api/groups/1/members?page=2&page_size=25")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["page"] == 2
    assert body["page_size"] == 25


def test_list_members_invalid_page_size(client: TestClient) -> None:
    """page_size > 200 is rejected by FastAPI validation."""
    with patch("app.api.members.get_group_by_id", new_callable=AsyncMock, return_value=_mock_group()):
        response = client.get("/api/groups/1/members?page_size=9999")
    assert response.status_code == 422


def test_list_members_search_param() -> None:
    mock_session = _make_fake_session(total=0)
    mock_group = _mock_group()

    app.dependency_overrides[get_db_session] = _override_db(mock_session)
    try:
        with (
            TestClient(app, headers={"X-API-Key": "test-ingestion-key"}) as c,
            patch("app.api.members.get_group_by_id", new_callable=AsyncMock, return_value=mock_group),
        ):
            response = c.get("/api/groups/1/members?search=alice")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
