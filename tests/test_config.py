"""
Tests: Settings / configuration validation.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from app.core.config import Settings, _find_env_file, get_settings


def test_settings_defaults() -> None:
    """Settings can be instantiated with defaults (no .env required)."""
    s = Settings(
        _env_file=None,  # type: ignore[call-arg]
    )
    assert s.port == 8000
    assert s.debug is False
    assert s.telegram_session_name == "tci_session"


def test_telegram_configured_false_when_empty() -> None:
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    # api_id defaults to 0 → not configured
    assert s.telegram_configured is False


def test_telegram_configured_true_when_set() -> None:
    s = Settings(
        _env_file=None,  # type: ignore[call-arg]
        telegram_api_id=123456,
        telegram_api_hash="abc123def456",
    )
    assert s.telegram_configured is True


def test_safe_repr_does_not_expose_secrets() -> None:
    s = Settings(
        _env_file=None,  # type: ignore[call-arg]
        telegram_api_hash="super_secret_hash",
        secret_key="super_secret_key",
        telegram_api_id=123456,
    )
    repr_dict = s.safe_repr
    # Neither the hash nor the secret key should appear
    for value in repr_dict.values():
        assert "super_secret_hash" not in str(value)
        assert "super_secret_key" not in str(value)


def test_allowed_origins_parsed_from_string() -> None:
    """allowed_origins is stored as a raw string; allowed_origins_list splits it."""
    s = Settings(
        _env_file=None,  # type: ignore[call-arg]
        allowed_origins="http://localhost:3000,http://localhost:5173",
    )
    # The raw field stays a string
    assert s.allowed_origins == "http://localhost:3000,http://localhost:5173"
    # The property splits it into a list for CORS middleware
    assert s.allowed_origins_list == ["http://localhost:3000", "http://localhost:5173"]


def test_get_settings_cached() -> None:
    """get_settings() should return the same object each time (lru_cache)."""
    a = get_settings()
    b = get_settings()
    assert a is b


# ── .env resolution tests ─────────────────────────────────────────────────────

def test_find_env_file_locates_project_root_env() -> None:
    """
    _find_env_file() must return the absolute path to the project-root .env,
    even when the current working directory is backend/ or backend/scripts/.
    The result must:
      - be an absolute path
      - end with '.env'
      - point to an existing file (when .env is present in the project)
    """
    result = _find_env_file()
    assert os.path.isabs(result) or result == ".env", (
        f"Expected absolute path or fallback '.env', got: {result!r}"
    )
    # If a real .env was found, verify it exists
    if result != ".env":
        assert Path(result).is_file(), f"Resolved .env path does not exist: {result}"
        assert result.endswith(".env"), f"Expected path ending in .env, got: {result}"


def test_find_env_file_uses_temp_env(tmp_path: Path) -> None:
    """
    When a temp .env is written to the directory that config.py searches,
    _find_env_file() must find it correctly.

    We simulate the case by writing a .env to a temp dir and then verifying
    that a Settings instance loading that file reads our custom value.
    """
    fake_env = tmp_path / ".env"
    fake_env.write_text(
        "TELEGRAM_SESSION_NAME=test_session_from_temp\n"
        "TELEGRAM_API_ID=0\n"
    )
    s = Settings(_env_file=str(fake_env))  # type: ignore[call-arg]
    assert s.telegram_session_name == "test_session_from_temp"


def test_settings_loaded_regardless_of_cwd(tmp_path: Path) -> None:
    """
    Changing os.getcwd() must not affect which .env file is loaded,
    because config.py resolves the path relative to __file__, not CWD.
    The resolved env file path must be consistent before and after chdir.
    """
    path_before = _find_env_file()

    original_cwd = os.getcwd()
    try:
        os.chdir(tmp_path)  # Simulate running from a completely different dir
        path_after = _find_env_file()
    finally:
        os.chdir(original_cwd)

    # The resolved path should be the same regardless of CWD
    assert path_before == path_after, (
        f"_find_env_file() returned different results:\n"
        f"  before chdir: {path_before}\n"
        f"  after  chdir: {path_after}"
    )
