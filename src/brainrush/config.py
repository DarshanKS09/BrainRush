"""Application configuration with startup validation.

Only two settings are required at foundation stage:
  - BOT_TOKEN: Telegram token (non-empty placeholder check only).
  - DATABASE_URL: SQLAlchemy async URL, must use postgresql+asyncpg:// scheme.
"""
from __future__ import annotations

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    BOT_TOKEN: str = Field(default="", description="Telegram Bot API token")
    DATABASE_URL: str = Field(
        default="",
        description="Async SQLAlchemy URL, e.g. postgresql+asyncpg://user:pass@localhost:5432/brainrush",
    )
    DB_CONNECT_TIMEOUT: float = Field(
        default=10.0,
        ge=0.5,
        le=120.0,
        description="Seconds to wait for the startup SELECT 1 database check",
    )
    WEBAPP_URL: str = Field(
        default="",
        description="Public HTTPS URL of the Mini App frontend (enables WebApp buttons)",
    )
    API_HOST: str = Field(default="127.0.0.1")
    API_PORT: int = Field(default=8000, ge=1, le=65535)
    PORT: int | None = Field(
        default=None,
        ge=1,
        le=65535,
        description="Hosting-provider port override (Render/Railway/Fly inject PORT)",
    )
    API_CORS_ORIGINS: str = Field(
        default="",
        description="Comma-separated allowed CORS origins for the API",
    )
    INIT_DATA_MAX_AGE: int = Field(
        default=86400, ge=60, le=604800,
        description="Max age in seconds for Telegram initData",
    )
    ALLOW_DEV_AUTH: bool = Field(
        default=False,
        description="NEVER enable in production: allows a mock dev identity",
    )
    DEV_AUTH_TELEGRAM_ID: int = Field(
        default=0,
        description="Telegram user id used only when ALLOW_DEV_AUTH is true",
    )

    @field_validator("BOT_TOKEN")
    @classmethod
    def _token_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("BOT_TOKEN must not be empty")
        return v.strip()

    @field_validator("DATABASE_URL")
    @classmethod
    def _db_url_scheme(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("DATABASE_URL must not be empty")
        v = v.strip()
        if not v.startswith("postgresql+asyncpg://"):
            raise ValueError("DATABASE_URL must start with 'postgresql+asyncpg://'")
        return v

    def masked(self) -> dict[str, str]:
        token = self.BOT_TOKEN
        masked_token = token[:4] + "..." + token[-4:] if len(token) > 8 else "***"
        return {"BOT_TOKEN": masked_token, "DATABASE_URL": self.DATABASE_URL}


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def validate_settings(settings: Settings | None = None) -> Settings:
    """Validate config; raises ValueError with a clear message on failure."""
    return settings or Settings()


def api_listen(settings: Settings) -> tuple[str, int]:
    """Effective (host, port) for the API server.

    Hosting providers inject PORT; it takes precedence over API_PORT so the
    same image runs locally and on Render/Railway/Fly without edits.
    """
    return settings.API_HOST, settings.PORT or settings.API_PORT
