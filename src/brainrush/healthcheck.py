"""Startup validation: config + optional DB connectivity check."""
from __future__ import annotations

from dataclasses import dataclass

from brainrush.config import Settings
from brainrush.db.session import check_connection, create_engine


@dataclass(frozen=True)
class HealthReport:
    config_ok: bool
    config_error: str | None
    db_ok: bool | None
    db_error: str | None = None

    @property
    def ok(self) -> bool:
        if not self.config_ok:
            return False
        # db_ok=None means "not checked"; only fail when explicitly False.
        return self.db_ok is not False


def validate_config_only(raw: dict[str, str] | None = None) -> HealthReport:
    """Validate BOT_TOKEN/DATABASE_URL without touching the network or DB."""
    try:
        Settings(**(raw or {}))
        return HealthReport(config_ok=True, config_error=None, db_ok=None)
    except Exception as exc:
        return HealthReport(config_ok=False, config_error=str(exc), db_ok=None)


async def health_check(settings: Settings, check_db: bool = True) -> HealthReport:
    """Full startup check. Set check_db=False for offline validation."""
    config_report = validate_config_only(
        {"BOT_TOKEN": settings.BOT_TOKEN, "DATABASE_URL": settings.DATABASE_URL}
    )
    if not config_report.config_ok:
        return config_report
    if not check_db:
        return HealthReport(config_ok=True, config_error=None, db_ok=None)
    engine = create_engine(settings.DATABASE_URL)
    try:
        timeout = getattr(settings, "DB_CONNECT_TIMEOUT", 10.0)
        ok = await check_connection(engine, timeout=timeout)
        if ok:
            return HealthReport(config_ok=True, config_error=None, db_ok=True)
        return HealthReport(
            config_ok=True, config_error=None, db_ok=False,
            db_error="Could not execute SELECT 1 (see logs / DATABASE_URL).",
        )
    finally:
        await engine.dispose()
