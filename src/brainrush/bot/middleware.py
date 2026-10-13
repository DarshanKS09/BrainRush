"""aiogram middleware: exactly one AsyncSession per update, always closed.

Registered on `dp.update.outer_middleware`, so every update (messages,
callbacks, ...) gets a fresh session in `data["session"]`. Handlers pass it to
the service layer, which owns transactions. The `async with` block guarantees
the session is closed even when a handler raises; sessions are never shared
between concurrent updates.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject


class DbSessionMiddleware(BaseMiddleware):
    def __init__(self, session_factory: Callable[[], Any]) -> None:
        self._factory = session_factory

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        async with self._factory() as session:
            data["session"] = session
            return await handler(event, data)
