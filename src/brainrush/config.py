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
        default="https://brainrush-w9tp.onrender.com",
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
    REFERRER_XP: int = Field(
        default=100, ge=0, le=100000,
        description="XP awarded to the referrer for each qualified referral",
    )
    REFERRED_XP: int = Field(
        default=25, ge=0, le=100000,
        description="XP awarded to a newly referred user",
    )
    TELEGRAM_BOT_USERNAME: str = Field(
        default="",
        description="Bot username without @, for building referral deep links",
    )
    MINIAPP_SHORT_NAME: str = Field(
        default="",
        description="Mini App short name from BotFather, for referral links",
    )
    MATCH_COMPLETION_XP: int = Field(
        default=10, ge=0, le=100000,
        description="XP per finished multiplayer match participant",
    )
    MATCH_WIN_BONUS: int = Field(
        default=10, ge=0, le=100000,
        description="Extra XP for multiplayer match winner(s)",
    )
    MATCH_DAILY_XP_CAP: int = Field(
        default=500, ge=0, le=1000000,
        description="Max multiplayer XP per user per UTC day (anti-farming)",
    )
    MATCH_LOBBY_TTL_HOURS: int = Field(
        default=24, ge=1, le=720,
        description="Lobby auto-expiry: unstarted matches older than this",
    )
    MATCH_INVITE_TTL_DAYS: int = Field(
        default=7, ge=1, le=90,
        description="Share-link invite token validity window",
    )
    MATCH_DEFAULT_MINUTES: int = Field(
        default=60, ge=5, le=1440,
        description="Authoritative match deadline length when adapters set none",
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
        # Mask the database password so logs/debug output never leak it.
        db_url = self.DATABASE_URL
        if "@" in db_url and "://" in db_url:
            scheme, rest = db_url.split("://", 1)
            if "@" in rest:
                creds, hostpart = rest.rsplit("@", 1)
                if ":" in creds:
                    user, _ = creds.split(":", 1)
                    db_url = f"{scheme}://{user}:***@{hostpart}"
        return {"BOT_TOKEN": masked_token, "DATABASE_URL": db_url}


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
