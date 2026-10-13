"""Player statistics: reads and safe counter/XP updates."""
from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from brainrush.db.errors import NotFoundError
from brainrush.db.models import PlayerProfile
from brainrush.db.repository import OUTCOMES, PlayerProfileRepository


class ProfileService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.profiles = PlayerProfileRepository(session)

    async def get_stats(self, *, user_id: uuid.UUID) -> PlayerProfile:
        # Read-only, but still inside begin(): even a SELECT autobegins a
        # transaction on AsyncSession, and leaving it open would break any
        # later begin() on the same session.
        async with self.session.begin():
            profile = await self.profiles.get_by_user_id(user_id)
        if profile is None:
            raise NotFoundError("player profile not found")
        return profile

    async def add_xp(self, *, user_id: uuid.UUID, amount: int) -> PlayerProfile:
        async with self.session.begin():
            return await self.profiles.add_xp(user_id=user_id, amount=amount)

    async def record_game(
        self,
        *,
        user_id: uuid.UUID,
        outcome: str,
        xp_earned: int,
        new_level: int | None = None,
    ) -> PlayerProfile:
        """Apply an outcome. Level is set only when explicitly provided."""
        if outcome not in OUTCOMES:
            raise ValueError(f"outcome must be one of {sorted(OUTCOMES)}")
        won = True if outcome == "win" else (False if outcome == "loss" else None)
        async with self.session.begin():
            return await self.profiles.record_game(
                user_id=user_id, xp_earned=xp_earned, won=won, new_level=new_level
            )
