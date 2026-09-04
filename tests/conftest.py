"""
pytest configuration: shared fixtures for the test suite.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import app


@pytest.fixture(scope="session")
def client() -> TestClient:
    """Synchronous TestClient — no real DB or Telegram required."""
    get_settings().ingestion_api_key = "test-ingestion-key"
    with TestClient(app, raise_server_exceptions=True) as c:
        c.headers.update({"X-API-Key": "test-ingestion-key"})
        yield c
