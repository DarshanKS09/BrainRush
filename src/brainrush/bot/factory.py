"""aiogram factory helpers (bot creation is lazy; no network calls at import)."""
from collections.abc import Callable
from typing import Any

from aiogram import Bot, Dispatcher, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from brainrush.bot.handlers import configure_webapp
from brainrush.bot.handlers import router as command_router
from brainrush.bot.middleware import DbSessionMiddleware


def create_bot(token: str) -> Bot:
    return Bot(
        token=token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )


def create_dispatcher(
    session_factory: Callable[[], Any] | None = None,
    router: Router | None = None,
    webapp_url: str = "",
) -> Dispatcher:
    """Build a Dispatcher. A custom `router` keeps tests isolated: aiogram
    forbids attaching one Router to several Dispatchers in one process."""
    configure_webapp(webapp_url)
    dp = Dispatcher()
    if session_factory is not None:
        dp.update.outer_middleware(DbSessionMiddleware(session_factory))
    dp.include_router(router if router is not None else command_router)
    return dp
