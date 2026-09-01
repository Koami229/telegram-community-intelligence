"""
Pydantic Settings — centralised configuration.
All values are loaded from environment variables or a .env file.
Secrets are never hard-coded here.

.env resolution strategy
------------------------
The .env file lives at the PROJECT ROOT (one level above ``backend/``).
We resolve its absolute path at import time so the configuration works
correctly regardless of the current working directory:

  - python scripts/auth_telegram.py          (CWD = backend/)
  - uvicorn app.main:app                     (CWD = backend/)
  - docker compose run backend ...           (CWD = /app inside container)
  - pytest tests/                            (CWD = backend/)

The search order is:
  1. The directory that contains this file:   backend/app/core/
  2. One level up:                            backend/app/
  3. Two levels up (= backend/):              backend/
  4. Three levels up (= project root):        telegram-community-intelligence/  ← .env lives here
  5. Fall back to CWD if none of the above has a .env file.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import List

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _find_env_file() -> str:
    """
    Walk up from this source file until we find a ``.env`` file or exhaust
    the directory tree.  Returns the absolute path to the first ``.env``
    found, or the string ``".env"`` as a fallback (pydantic-settings will
    then look in CWD, which is the original behaviour).
    """
    here = Path(__file__).resolve().parent          # backend/app/core
    search = [here, here.parent, here.parent.parent, here.parent.parent.parent]
    for candidate in search:
        env_path = candidate / ".env"
        if env_path.is_file():
            return str(env_path)
    # Docker / fallback: look in /app/.env and /app/../.env
    for docker_path in [Path("/app/.env"), Path("/app/../.env")]:
        if docker_path.is_file():
            return str(docker_path)
    return ".env"  # pydantic-settings default — resolves against CWD


_ENV_FILE = _find_env_file()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_ENV_FILE,
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Telegram ────────────────────────────────────────────────────────────
    telegram_api_id: int = 0
    telegram_api_hash: str = ""
    telegram_session_name: str = "tci_session"
    telegram_phone: str = ""

    # ── Session ─────────────────────────────────────────────────────────────
    # Directory where .session files are stored (relative to backend/)
    telegram_session_path: str = "sessions"

    # ── Database ────────────────────────────────────────────────────────────
    # Default points to localhost for local dev; Docker overrides via env var
    database_url: str = "postgresql+psycopg://tci_user:tci_password@localhost:5433/tci_db"

    # ── Redis ────────────────────────────────────────────────────────────────
    redis_url: str = "redis://localhost:6379/0"

    # ── Application ──────────────────────────────────────────────────────────
    secret_key: str = ""
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = False

    # ── CORS ─────────────────────────────────────────────────────────────────
    # Stored as a plain string to avoid pydantic-settings JSON auto-parsing.
    # Use the `allowed_origins_list` property or `parse_origins()` to get a list.
    allowed_origins: str = "http://localhost:3000,http://localhost:5173"

    @property
    def allowed_origins_list(self) -> List[str]:
        """Return CORS origins as a list."""
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]

    # ── Convenience helpers ──────────────────────────────────────────────────
    @property
    def telegram_configured(self) -> bool:
        """True when the minimum Telegram credentials are present."""
        return bool(self.telegram_api_id and self.telegram_api_hash)

    @property
    def safe_repr(self) -> dict:
        """Return non-sensitive config for logging / health endpoints."""
        return {
            "env_file_resolved": _ENV_FILE,
            "telegram_session_name": self.telegram_session_name,
            "telegram_configured": self.telegram_configured,
            "database_url": self._mask_db_url(),
            "redis_url": self.redis_url,
            "debug": self.debug,
            "port": self.port,
        }

    def _mask_db_url(self) -> str:
        """Replace password in the DB URL before logging."""
        try:
            from urllib.parse import urlparse, urlunparse
            parsed = urlparse(self.database_url)
            if parsed.password:
                netloc = parsed.netloc.replace(parsed.password, "***")
                return urlunparse(parsed._replace(netloc=netloc))
        except Exception:
            pass
        return self.database_url


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached application settings instance."""
    return Settings()
