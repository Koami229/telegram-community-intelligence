"""
pytest configuration: shared fixtures for the test suite.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="session")
def client() -> TestClient:
    """Synchronous TestClient — no real DB or Telegram required."""
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c
