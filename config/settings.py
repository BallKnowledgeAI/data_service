"""
config/settings.py — Centralised environment-driven configuration.

All connection details are read from environment variables (populated via
.env using python-dotenv).  No other module should call os.environ or
load_dotenv directly — import from here instead.

Usage:
    from config.settings import settings
    factory = get_session_factory(settings.postgres_url)
    store   = MatchStateRedisStore(
                  host=settings.redis_host,
                  port=settings.redis_port,
                  password=settings.redis_password or None,
              )
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# Load .env from the project root (two levels up from this file).
# python-dotenv is a soft dependency — if it's missing we fall back to
# whatever the shell already exported (works fine in Docker/CI).
try:
    from dotenv import load_dotenv

    _env_file = Path(__file__).resolve().parent.parent / ".env"
    if _env_file.exists():
        load_dotenv(_env_file)
except ImportError:
    pass  # dotenv not installed — rely on pre-set env vars


def _require(name: str) -> str:
    """Return env var *name*, raising a clear error if absent."""
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(
            f"Required environment variable '{name}' is not set. "
            "Copy .env.example → .env and fill in the values."
        )
    return value


@dataclass(frozen=True)
class Settings:
    # --- Postgres ---
    postgres_host: str
    postgres_port: int
    postgres_db: str
    postgres_user: str
    postgres_password: str

    # --- Redis ---
    redis_host: str
    redis_port: int
    redis_password: str  # empty string means no-auth

    @property
    def postgres_url(self) -> str:
        """SQLAlchemy-compatible DSN for psycopg2."""
        return (
            f"postgresql+psycopg2://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def redis_auth(self) -> str | None:
        """None when no password is configured (redis-py requires None, not '')."""
        return self.redis_password if self.redis_password else None


def _load() -> Settings:
    return Settings(
        postgres_host=os.environ.get("POSTGRES_HOST", "localhost"),
        postgres_port=int(os.environ.get("POSTGRES_PORT", "5432")),
        postgres_db=_require("POSTGRES_DB"),
        postgres_user=_require("POSTGRES_USER"),
        postgres_password=_require("POSTGRES_PASSWORD"),
        redis_host=os.environ.get("REDIS_HOST", "localhost"),
        redis_port=int(os.environ.get("REDIS_PORT", "6379")),
        redis_password=os.environ.get("REDIS_PASSWORD", ""),
    )


# Module-level singleton — evaluated once on first import.
settings: Settings = _load()
