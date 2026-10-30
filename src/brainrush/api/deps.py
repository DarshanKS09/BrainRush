"""Request dependencies: one AsyncSession per request + verified Telegram user."""
from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from brainrush.api.auth import AuthError, parse_and_verify
from brainrush.api.ratelimit import (
    AUTH_LIMITER,
    EXPENSIVE_LIMITER,
    INVITE_LIMITER,
    ROOM_LIMITER,
)
from brainrush.config import Settings
from brainrush.services.users import UserService

log = logging.getLogger("brainrush.api")


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_session_factory(request: Request):
    return request.app.state.session_factory


async def get_session(request: Request) -> AsyncGenerator[AsyncSession, None]:
    factory = get_session_factory(request)
    async with factory() as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_session)]


def _client_ip(request: Request) -> str:
    """Best-effort client ip for unauthenticated rate limiting."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _rate_limit(limiter, request: Request, key: str) -> None:
    allowed, remaining = limiter.check(key)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail="rate limit exceeded",
            headers={"Retry-After": "60"},
        )
    request.state.rate_limit_remaining = remaining


async def get_verified_identity(
    request: Request,
    session: SessionDep,
    init_data: Annotated[str, Header(alias="X-Telegram-Init-Data")] = "",
) -> dict:
    """Verify initData and register the player. Raises AuthError -> 401.

    Registration commits its own short transaction first; route handlers open
    their own afterwards (sequential begins on one session, same as the bot).
    """
    settings: Settings = get_settings(request)
    identity = parse_and_verify(
        init_data,
        bot_token=settings.BOT_TOKEN,
        max_age_seconds=settings.INIT_DATA_MAX_AGE,
        allow_dev=settings.ALLOW_DEV_AUTH,
        dev_telegram_id=settings.DEV_AUTH_TELEGRAM_ID,
    )
    # [diag] TEMPORARY: validation succeeded (no payload/token logged; the
    # access log right after shows method/path/status/latency + user uuid).
    log.info("[diag] initData verification OK")
    user, _ = await UserService(session).get_or_register(
        telegram_id=identity["telegram_id"],
        username=identity["username"],
        display_name=identity["display_name"],
    )
    request.state.telegram_id = identity["telegram_id"]
    _rate_limit(AUTH_LIMITER, request, f"auth:{user.id}")
    return {"user_id": user.id, **identity}


async def get_verified_telegram_identity(
    request: Request,
    init_data: Annotated[str, Header(alias="X-Telegram-Init-Data")] = "",
) -> dict:
    """Verify initData WITHOUT touching the database.

    Used by the referral claim endpoint, which must distinguish genuinely
    new identities from existing ones inside its own transaction. Every
    other route keeps using get_verified_identity (verify + register).
    """
    settings: Settings = get_settings(request)
    identity = parse_and_verify(
        init_data,
        bot_token=settings.BOT_TOKEN,
        max_age_seconds=settings.INIT_DATA_MAX_AGE,
        allow_dev=settings.ALLOW_DEV_AUTH,
        dev_telegram_id=settings.DEV_AUTH_TELEGRAM_ID,
    )
    request.state.telegram_id = identity["telegram_id"]
    _rate_limit(AUTH_LIMITER, request, f"auth:{identity['telegram_id']}")
    return identity


# -- Route-scoped rate limit dependencies -----------------------------------

async def rate_limit_auth(request: Request) -> None:
    """General authenticated API rate limit (keyed by verified user id)."""
    tid = getattr(request.state, "telegram_id", None)
    key = f"auth:{tid}" if tid else f"ip:{_client_ip(request)}"
    _rate_limit(AUTH_LIMITER, request, key)


async def rate_limit_room(request: Request) -> None:
    """Match room create/join rate limit."""
    tid = getattr(request.state, "telegram_id", None)
    key = f"room:{tid}" if tid else f"ip:{_client_ip(request)}"
    _rate_limit(ROOM_LIMITER, request, key)


async def rate_limit_invite(request: Request) -> None:
    """Invitation rate limit."""
    tid = getattr(request.state, "telegram_id", None)
    key = f"invite:{tid}" if tid else f"ip:{_client_ip(request)}"
    _rate_limit(INVITE_LIMITER, request, key)


async def rate_limit_expensive(request: Request) -> None:
    """Expensive endpoint rate limit (leaderboard, large history pages)."""
    tid = getattr(request.state, "telegram_id", None)
    key = f"expensive:{tid}" if tid else f"ip:{_client_ip(request)}"
    _rate_limit(EXPENSIVE_LIMITER, request, key)


RateLimitDep = Annotated[None, Depends(rate_limit_auth)]
RoomLimitDep = Annotated[None, Depends(rate_limit_room)]
InviteLimitDep = Annotated[None, Depends(rate_limit_invite)]
ExpensiveLimitDep = Annotated[None, Depends(rate_limit_expensive)]
