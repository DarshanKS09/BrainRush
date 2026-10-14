"""Request dependencies: one AsyncSession per request + verified Telegram user."""
from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from brainrush.api.auth import AuthError, parse_and_verify
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
    user, _ = await UserService(session).get_or_register(
        telegram_id=identity["telegram_id"],
        username=identity["username"],
        display_name=identity["display_name"],
    )
    request.state.telegram_id = identity["telegram_id"]
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
    return identity
