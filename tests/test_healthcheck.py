"""Health-check tests with mocked engine (no real DB connection)."""
from unittest.mock import AsyncMock

from brainrush.config import Settings
from brainrush.healthcheck import health_check


def _settings() -> Settings:
    return Settings(
        BOT_TOKEN="123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11",
        DATABASE_URL="postgresql+asyncpg://user:password@localhost:5432/brainrush",
    )


async def test_health_check_db_skipped():
    report = await health_check(_settings(), check_db=False)
    assert report.config_ok
    assert report.db_ok is None
    assert report.ok


async def test_health_check_db_success_monkeypatched(monkeypatch):
    import brainrush.healthcheck as hc

    async def fake_ok(engine, timeout=10.0):
        return True

    async def fake_engine(url):
        return None

    monkeypatch.setattr(hc, "check_connection", fake_ok)

    class FakeEngine:
        async def dispose(self):
            return None

    monkeypatch.setattr(hc, "create_engine", lambda url: FakeEngine())
    report = await health_check(_settings(), check_db=True)
    assert report.ok
    assert report.db_ok is True


async def test_health_check_db_failure_monkeypatched(monkeypatch):
    import brainrush.healthcheck as hc

    async def fake_fail(engine, timeout=10.0):
        return False

    class FakeEngine:
        async def dispose(self):
            return None

    monkeypatch.setattr(hc, "check_connection", fake_fail)
    monkeypatch.setattr(hc, "create_engine", lambda url: FakeEngine())
    report = await health_check(_settings(), check_db=True)
    assert not report.ok
    assert report.db_ok is False


async def test_check_connection_returns_false_without_db():
    from brainrush.db.session import check_connection, create_engine

    engine = create_engine("postgresql+asyncpg://user:bad@localhost:5432/no_db_xyz")
    try:
        assert await check_connection(engine, timeout=2.0) is False
    finally:
        await engine.dispose()
