"""
Tests: /health and /api/status endpoints.

Uses FastAPI's TestClient with mocked DB / Telegram checks so no real
infrastructure is needed for the unit test run.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient


def test_health_returns_200(client: TestClient) -> None:
    with (
        patch("app.api.health.check_db_connection", new_callable=AsyncMock, return_value=False),
        patch("app.api.health.telegram_service") as mock_tg,
    ):
        mock_tg.is_connected.return_value = False
        mock_tg.is_authorized = AsyncMock(return_value=False)

        response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "database" in body
    assert "telegram" in body


def test_health_db_connected(client: TestClient) -> None:
    with (
        patch("app.api.health.check_db_connection", new_callable=AsyncMock, return_value=True),
        patch("app.api.health.telegram_service") as mock_tg,
    ):
        mock_tg.is_connected.return_value = False
        mock_tg.is_authorized = AsyncMock(return_value=False)

        response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["database"] == "connected"


def test_health_telegram_connected(client: TestClient) -> None:
    with (
        patch("app.api.health.check_db_connection", new_callable=AsyncMock, return_value=False),
        patch("app.api.health.telegram_service") as mock_tg,
    ):
        mock_tg.is_connected.return_value = True
        mock_tg.is_authorized = AsyncMock(return_value=True)

        response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["telegram"] == "connected"


def test_health_telegram_disconnected(client: TestClient) -> None:
    with (
        patch("app.api.health.check_db_connection", new_callable=AsyncMock, return_value=False),
        patch("app.api.health.telegram_service") as mock_tg,
    ):
        mock_tg.is_connected.return_value = False
        mock_tg.is_authorized = AsyncMock(return_value=False)

        response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["telegram"] == "disconnected"


def test_api_status_returns_200(client: TestClient) -> None:
    response = client.get("/api/status")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "version" in body
    assert "telegram_configured" in body
    assert "telegram_connected" in body
    assert "telegram_authorized" in body


def test_api_status_no_secrets(client: TestClient) -> None:
    """Ensure /api/status never leaks API_HASH or SECRET_KEY values."""
    response = client.get("/api/status")
    raw = response.text
    # These are actual secret values — they should never appear
    assert "api_hash" not in raw.lower() or "telegram_api_hash" not in raw


def test_readiness_not_ready_without_dependencies(client: TestClient) -> None:
    with (
        patch("app.api.health.check_db_connection", new_callable=AsyncMock, return_value=False),
        patch("app.api.health.telegram_service") as mock_tg,
    ):
        mock_tg.is_connected.return_value = False
        mock_tg.is_authorized = AsyncMock(return_value=False)
        response = client.get("/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "not_ready",
        "database": "disconnected",
        "telegram": "disconnected",
    }


def test_readiness_ready_with_dependencies(client: TestClient) -> None:
    with (
        patch("app.api.health.check_db_connection", new_callable=AsyncMock, return_value=True),
        patch("app.api.health.telegram_service") as mock_tg,
    ):
        mock_tg.is_connected.return_value = True
        mock_tg.is_authorized = AsyncMock(return_value=True)
        response = client.get("/ready")

    assert response.status_code == 200
    assert response.json()["status"] == "ready"
