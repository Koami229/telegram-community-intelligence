"""
Tests: Groups and Sync API endpoints.
"""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.models.models import GroupType, SyncStatus


# ── Helper ────────────────────────────────────────────────────────────────────

def _mock_group(
    id: int = 1,
    tg_id: int = -1001234567890,
    title: str = "Test Group",
    username: str = "testgroup",
    group_type: GroupType = GroupType.SUPERGROUP,
    member_count: int = 500,
) -> MagicMock:
    g = MagicMock()
    g.id = id
    g.telegram_group_id = tg_id
    g.title = title
    g.username = username
    g.group_type = group_type
    g.is_active = True
    g.collection_authorized = True
    g.collection_authorized_at = datetime.now(tz=timezone.utc)
    g.member_count = member_count
    g.first_synced_at = None
    g.last_synced_at = None
    g.created_at = datetime.now(tz=timezone.utc)
    return g


# ── POST /api/groups ──────────────────────────────────────────────────────────

def test_add_group_success(client: TestClient) -> None:
    mock_group = _mock_group()
    mock_group.media_download_authorized = True

    with (
        patch("app.api.groups.resolve_and_save_group", return_value=(mock_group, True)) as mock_resolve,
        patch("app.api.groups.get_db_session"),
    ):
        response = client.post("/api/groups", json={"identifier": "@testgroup"})

    assert response.status_code == 201
    body = response.json()
    assert body["telegram_group_id"] == -1001234567890
    assert body["title"] == "Test Group"
    assert body["group_type"] == "supergroup"


def test_add_group_access_error(client: TestClient) -> None:
    from app.services.group_service import GroupAccessError

    with patch(
        "app.api.groups.resolve_and_save_group",
        side_effect=GroupAccessError("Not a member"),
    ):
        response = client.post("/api/groups", json={"identifier": "@private"})

    assert response.status_code == 403
    assert "Not a member" in response.json()["detail"]


def test_add_group_resolution_error(client: TestClient) -> None:
    from app.services.group_service import GroupResolutionError

    with patch(
        "app.api.groups.resolve_and_save_group",
        side_effect=GroupResolutionError("Username does not exist"),
    ):
        response = client.post("/api/groups", json={"identifier": "@doesnotexist"})

    assert response.status_code == 422
    assert "does not exist" in response.json()["detail"]


def test_add_group_empty_identifier(client: TestClient) -> None:
    response = client.post("/api/groups", json={"identifier": ""})
    assert response.status_code == 422  # Pydantic validation


def test_add_group_missing_identifier(client: TestClient) -> None:
    response = client.post("/api/groups", json={})
    assert response.status_code == 422


# ── GET /api/groups ───────────────────────────────────────────────────────────

def test_list_groups_empty(client: TestClient) -> None:
    with patch("app.api.groups.get_all_groups", return_value=[]):
        response = client.get("/api/groups")
    assert response.status_code == 200
    assert response.json() == []


def test_list_groups_returns_groups(client: TestClient) -> None:
    mock_groups = [_mock_group(id=1), _mock_group(id=2, tg_id=-100999)]
    with patch("app.api.groups.get_all_groups", return_value=mock_groups):
        response = client.get("/api/groups")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 2


# ── GET /api/groups/{id} ──────────────────────────────────────────────────────

def test_get_group_found(client: TestClient) -> None:
    mock_group = _mock_group(id=5)
    with patch("app.api.groups.get_group_by_id", return_value=mock_group):
        response = client.get("/api/groups/5")
    assert response.status_code == 200
    assert response.json()["id"] == 5


def test_get_group_not_found(client: TestClient) -> None:
    with patch("app.api.groups.get_group_by_id", return_value=None):
        response = client.get("/api/groups/999")
    assert response.status_code == 404


# ── POST /api/groups/{id}/sync ────────────────────────────────────────────────

def test_trigger_sync_success(client: TestClient) -> None:
    mock_group = _mock_group(id=1)
    mock_job = MagicMock()
    mock_job.id = 7
    mock_job.status = SyncStatus.PENDING

    with (
        patch("app.api.sync.get_group_by_id", return_value=mock_group),
        patch("app.api.sync.start_sync", return_value=7),
        patch("app.api.sync.get_latest_sync_job", return_value=mock_job),
    ):
        response = client.post("/api/groups/1/sync")

    assert response.status_code == 202
    body = response.json()
    assert body["job_id"] == 7
    assert body["group_id"] == 1


def test_trigger_sync_group_not_found(client: TestClient) -> None:
    with patch("app.api.sync.get_group_by_id", return_value=None):
        response = client.post("/api/groups/999/sync")
    assert response.status_code == 404


# ── GET /api/groups/{id}/sync/status ─────────────────────────────────────────

def test_sync_status_running(client: TestClient) -> None:
    mock_group = _mock_group(id=1)
    status_data = {
        "job_id": 3,
        "group_id": 1,
        "status": "running",
        "started_at": None,
        "completed_at": None,
        "processed_count": 200,
        "new_members_count": 150,
        "error_count": 0,
        "total_member_count": 500,
        "progress_percent": 40.0,
        "last_cursor": None,
        "error_message": None,
        "created_at": datetime.now(tz=timezone.utc),
    }
    with (
        patch("app.api.sync.get_group_by_id", return_value=mock_group),
        patch("app.api.sync.get_sync_status", return_value=status_data),
    ):
        response = client.get("/api/groups/1/sync/status")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "running"
    assert body["progress_percent"] == 40.0
    assert body["processed_count"] == 200


def test_sync_status_no_job(client: TestClient) -> None:
    mock_group = _mock_group(id=1)
    with (
        patch("app.api.sync.get_group_by_id", return_value=mock_group),
        patch("app.api.sync.get_sync_status", return_value=None),
    ):
        response = client.get("/api/groups/1/sync/status")
    assert response.status_code == 404


def test_authorization_audit_returns_typed_records(client: TestClient) -> None:
    record = SimpleNamespace(
        id=4,
        group_id=1,
        collection_authorized=True,
        media_download_authorized=False,
        actor_label="operator-1",
        reason="Owner approval",
        created_at=datetime.now(tz=timezone.utc),
    )
    with (
        patch("app.api.groups.get_group_by_id", new_callable=AsyncMock, return_value=_mock_group()),
        patch("app.api.groups.get_authorization_audits", new_callable=AsyncMock, return_value=[record]),
    ):
        response = client.get("/api/groups/1/authorization/audit")

    assert response.status_code == 200
    body = response.json()
    assert body[0]["actor_label"] == "operator-1"
    assert body[0]["media_download_authorized"] is False


def test_authorization_reason_is_length_limited(client: TestClient) -> None:
    response = client.post(
        "/api/groups/1/authorization",
        json={"confirmed": True, "reason": "x" * 2001},
    )
    assert response.status_code == 422
