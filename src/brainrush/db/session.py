"""Async engine helpers. No connection is opened at import time."""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine


def create_engine(database_url: str) -> AsyncEngine:
    return create_async_engine(database_url, pool_pre_ping=True)


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker:
    return async_sessionmaker(engine, expire_on_commit=False)


async def check_connection(engine: AsyncEngine, timeout: float = 10.0) -> bool:
    """Return True when `SELECT 1` succeeds, else False. Never raises."""
    import asyncio

    try:
        async def _ping() -> None:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))

        # wait_for works on 3.10+ (asyncio.timeout is 3.11+ only).
        await asyncio.wait_for(_ping(), timeout=timeout)
        return True
    except Exception:
        return False
