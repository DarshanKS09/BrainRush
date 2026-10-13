"""User registration: Telegram identity -> User row + PlayerProfile row."""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from brainrush.db.models import PlayerProfile, User
from brainrush.db.repository import PlayerProfileRepository, UserRepository


class UserService:
    """Get-or-register flow. Owns one transaction per call."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.users = UserRepository(session)
        self.profiles = PlayerProfileRepository(session)

    async def get_or_register(
        self,
        *,
        telegram_id: int,
        username: str | None = None,
        display_name: str | None = None,
    ) -> tuple[User, PlayerProfile]:
        async with self.session.begin():
            user, _ = await self.users.get_or_create(
                telegram_id=telegram_id,
                username=username,
                display_name=display_name,
            )
            profile, _ = await self.profiles.get_or_create(user_id=user.id)
            return user, profile
