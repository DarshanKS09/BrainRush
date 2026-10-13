"""Game sessions: start/finish with result + profile + activity in one txn.

No scoring rules live here: callers pass the final `score`, `outcome`, and
`xp_earned`, plus an optional explicit `new_level`. Streak handling is generic
(win extends, loss resets, draw leaves untouched).
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from brainrush.db.errors import ConflictError, NotFoundError
from brainrush.db.models import DailyActivity, GameResult, GameSession, PlayerProfile
from brainrush.db.repository import (
    OUTCOMES,
    DailyActivityRepository,
    GameResultRepository,
    GameSessionRepository,
    PlayerProfileRepository,
    UserRepository,
)
from brainrush.services import require_aware_moment, utcnow


class GameSessionService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.users = UserRepository(session)
        self.sessions = GameSessionRepository(session)
        self.results = GameResultRepository(session)
        self.profiles = PlayerProfileRepository(session)
        self.activities = DailyActivityRepository(session)

    async def start_session(
        self, *, user_id: uuid.UUID, game_type: str
    ) -> GameSession:
        async with self.session.begin():
            if await self.users.get_by_id(user_id) is None:
                raise NotFoundError("user not found")
            return await self.sessions.create(user_id=user_id, game_type=game_type)

    async def finish_session(
        self,
        *,
        session_id: uuid.UUID,
        outcome: str,
        score: int,
        xp_earned: int,
        metadata: dict | None = None,
        new_level: int | None = None,
        played_at: datetime | None = None,
    ) -> tuple[GameSession, GameResult, PlayerProfile, DailyActivity]:
        if outcome not in OUTCOMES:
            raise ValueError(f"outcome must be one of {sorted(OUTCOMES)}")
        moment = require_aware_moment(played_at, field="played_at") or utcnow()

        async with self.session.begin():
            row = await self.sessions.get_by_id(session_id)
            if row is None:
                raise NotFoundError("game session not found")
            user_id = row.user_id
            started_at = row.started_at
            duration = _duration_seconds(started_at, moment)

            session = await self.sessions.finish(
                session_id=session_id,
                status="completed",
                score=score,
                ended_at=moment,
                duration_seconds=duration,
            )
            result = await self.results.record(
                session_id=session_id,
                score=score,
                outcome=outcome,
                xp_earned=xp_earned,
                metadata=metadata,
            )
            won = True if outcome == "win" else (False if outcome == "loss" else None)
            profile = await self.profiles.record_game(
                user_id=user_id, xp_earned=xp_earned, won=won, new_level=new_level
            )
            activity = await self.activities.add_play(
                user_id=user_id, day=moment.date(), xp_earned=xp_earned
            )
            return session, result, profile, activity

    async def abandon_session(
        self, *, session_id: uuid.UUID, played_at: datetime | None = None
    ) -> GameSession:
        moment = require_aware_moment(played_at, field="played_at") or utcnow()
        async with self.session.begin():
            return await self.sessions.abandon(
                session_id=session_id, ended_at=moment
            )

    async def abandon_stale_sessions(
        self, *, user_id: uuid.UUID
    ) -> list[GameSession]:
        """Abandon every `started` row (e.g. orphaned by a restart) atomically.

        One transaction for list + all abandons: no autobegun SELECT is ever
        left dangling on the caller's session, so a later `begin()` on the
        same session cannot raise "transaction already begun". Rows that
        vanished or finished concurrently are skipped, never fatal.
        """
        async with self.session.begin():
            stale = await self.sessions.list_by_user(
                user_id=user_id, status="started"
            )
            abandoned: list[GameSession] = []
            for row in stale:
                try:
                    abandoned.append(
                        await self.sessions.abandon(
                            session_id=row.id, ended_at=utcnow()
                        )
                    )
                except (NotFoundError, ConflictError):
                    continue
            return abandoned


def _duration_seconds(started_at: datetime | None, ended_at: datetime) -> int | None:
    if started_at is None:
        return None
    if started_at.tzinfo is None:
        return None
    delta = (ended_at - started_at).total_seconds()
    return max(0, int(delta))
