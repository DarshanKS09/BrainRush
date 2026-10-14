"""Async repositories (SQLAlchemy 2.x).

Rules:
  - No `commit()` / `rollback()` / `begin()` in here; the service layer owns
    transactions. Repositories may `flush()` so defaults/PKs populate.
  - Counter and XP changes are single-statement `UPDATE ... SET col = col + n`
    operations (atomic at the database level).
  - Get-or-create paths use `ON CONFLICT DO NOTHING` + re-SELECT so concurrent
    requests cannot create duplicates; uniqueness is enforced by DB constraints.
  - Inputs are validated (`ValueError`); missing rows surface as `None` and
    services translate that into `NotFoundError`.
"""
from __future__ import annotations

import uuid
from datetime import date
from typing import Any, Generic, TypeVar

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from brainrush.db.base import Base
from brainrush.db.errors import ConflictError, NotFoundError
from brainrush.db.models import (
    DailyActivity,
    GameResult,
    GameSession,
    PlayerProfile,
    ReferralAttribution,
    ReferralCode,
    User,
    WebappGameState,
)

T = TypeVar("T", bound=Base)

SESSION_STATUSES: frozenset[str] = frozenset(
    {"started", "completed", "abandoned", "expired"}
)
TERMINAL_STATUSES: frozenset[str] = frozenset({"completed", "abandoned", "expired"})
OUTCOMES: frozenset[str] = frozenset({"win", "loss", "draw"})


class BaseRepository(Generic[T]):
    """Thin wrapper to keep session handling consistent in later milestones."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session


def _require_telegram_id(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value == 0:
        raise ValueError("telegram_id must be a non-zero int")
    return value


def _require_name(value: Any, *, field: str, limit: int) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string or None")
    value = value.strip()
    if len(value) > limit:
        raise ValueError(f"{field} must be at most {limit} characters")
    return value


def _require_non_negative_int(value: Any, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field} must be an int >= 0")
    return value


class UserRepository(BaseRepository[User]):
    async def get_by_id(self, user_id: uuid.UUID) -> User | None:
        return await self.session.get(User, user_id)

    async def get_by_telegram_id(self, telegram_id: int) -> User | None:
        _require_telegram_id(telegram_id)
        result = await self.session.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        return result.scalar_one_or_none()

    async def create(
        self,
        *,
        telegram_id: int,
        username: str | None = None,
        display_name: str | None = None,
    ) -> User:
        _require_telegram_id(telegram_id)
        username = _require_name(username, field="username", limit=32)
        display_name = _require_name(display_name, field="display_name", limit=128)
        user = User(
            telegram_id=telegram_id, username=username, display_name=display_name
        )
        self.session.add(user)
        await self.session.flush()
        return user

    async def get_or_create(
        self,
        *,
        telegram_id: int,
        username: str | None = None,
        display_name: str | None = None,
    ) -> tuple[User, bool]:
        """Return (user, created). Safe under concurrency via ON CONFLICT."""
        _require_telegram_id(telegram_id)
        username = _require_name(username, field="username", limit=32)
        display_name = _require_name(display_name, field="display_name", limit=128)

        existing = await self.get_by_telegram_id(telegram_id)
        if existing is not None:
            changed = False
            if username is not None and existing.username != username:
                existing.username = username
                changed = True
            if display_name is not None and existing.display_name != display_name:
                existing.display_name = display_name
                changed = True
            if changed:
                await self.session.flush()
            return existing, False

        result = await self.session.execute(
            pg_insert(User)
            .values(
                telegram_id=telegram_id,
                username=username,
                display_name=display_name,
            )
            .on_conflict_do_nothing(index_elements=["telegram_id"])
        )
        created = result.rowcount == 1
        await self.session.flush()
        user = await self.get_by_telegram_id(telegram_id)
        if user is None:  # pragma: no cover - defensive; constraint guarantees a row
            raise NotFoundError("user row missing right after upsert")
        return user, created


class PlayerProfileRepository(BaseRepository[PlayerProfile]):
    async def get_by_user_id(self, user_id: uuid.UUID) -> PlayerProfile | None:
        result = await self.session.execute(
            select(PlayerProfile).where(PlayerProfile.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def create(self, *, user_id: uuid.UUID) -> PlayerProfile:
        profile = PlayerProfile(user_id=user_id)
        self.session.add(profile)
        await self.session.flush()
        return profile

    async def get_or_create(self, *, user_id: uuid.UUID) -> tuple[PlayerProfile, bool]:
        existing = await self.get_by_user_id(user_id)
        if existing is not None:
            return existing, False
        result = await self.session.execute(
            pg_insert(PlayerProfile)
            .values(user_id=user_id)
            .on_conflict_do_nothing(index_elements=["user_id"])
        )
        created = result.rowcount == 1
        await self.session.flush()
        profile = await self.get_by_user_id(user_id)
        if profile is None:  # pragma: no cover - defensive
            raise NotFoundError("profile row missing right after upsert")
        return profile, created

    async def top_by_xp(
        self, *, limit: int = 20, offset: int = 0
    ) -> list[tuple[PlayerProfile, User]]:
        """Stable leaderboard page: total_xp DESC, then user_id ASC.

        Single joined query (no N+1): profile + owning user per row.
        """
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise ValueError("limit must be an int in 1..100")
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise ValueError("offset must be an int >= 0")
        result = await self.session.execute(
            select(PlayerProfile, User)
            .join(User, User.id == PlayerProfile.user_id)
            .order_by(PlayerProfile.total_xp.desc(), PlayerProfile.user_id.asc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.all())

    async def rank_by_xp(self, *, total_xp: int) -> int:
        """1-based rank: 1 + number of profiles strictly above total_xp."""
        _require_non_negative_int(total_xp, field="total_xp")
        result = await self.session.execute(
            select(func.count())
            .select_from(PlayerProfile)
            .where(PlayerProfile.total_xp > total_xp)
        )
        return 1 + (result.scalar_one_or_none() or 0)

    async def set_level(self, *, user_id: uuid.UUID, level: int) -> PlayerProfile:
        if isinstance(level, bool) or not isinstance(level, int) or level < 1:
            raise ValueError("level must be an int >= 1")
        result = await self.session.execute(
            update(PlayerProfile)
            .where(PlayerProfile.user_id == user_id)
            .values(current_level=level)
        )
        if result.rowcount != 1:
            raise NotFoundError("player profile not found")
        await self.session.flush()
        profile = await self.get_by_user_id(user_id)
        if profile is None:  # pragma: no cover - defensive
            raise NotFoundError("player profile not found")
        return profile

    async def add_xp(self, *, user_id: uuid.UUID, amount: int) -> PlayerProfile:
        """Atomically add XP; caller owns level policy. Returns fresh profile."""
        _require_non_negative_int(amount, field="amount")
        await self.session.execute(
            update(PlayerProfile)
            .where(PlayerProfile.user_id == user_id)
            .values(total_xp=PlayerProfile.total_xp + amount)
        )
        await self.session.flush()
        profile = await self.get_by_user_id(user_id)
        if profile is None:
            raise NotFoundError("player profile not found")
        return profile

    async def record_game(
        self,
        *,
        user_id: uuid.UUID,
        xp_earned: int,
        won: bool | None,
        new_level: int | None = None,
    ) -> PlayerProfile:
        """Apply one finished game atomically. `won=None` means draw.

        Level is set explicitly when `new_level` is given; level-up rules live
        outside this layer.
        """
        _require_non_negative_int(xp_earned, field="xp_earned")
        if won not in (True, False, None):
            raise ValueError("won must be True, False, or None")
        if new_level is not None and (
            isinstance(new_level, bool)
            or not isinstance(new_level, int)
            or new_level < 1
        ):
            raise ValueError("new_level must be an int >= 1 or None")

        values: dict[str, Any] = {
            "total_xp": PlayerProfile.total_xp + xp_earned,
            "games_played": PlayerProfile.games_played + 1,
        }
        if won is True:
            values["wins"] = PlayerProfile.wins + 1
            values["current_streak"] = PlayerProfile.current_streak + 1
            values["longest_streak"] = func.greatest(
                PlayerProfile.longest_streak, PlayerProfile.current_streak + 1
            )
        elif won is False:
            values["losses"] = PlayerProfile.losses + 1
            values["current_streak"] = 0
        if new_level is not None:
            values["current_level"] = new_level

        result = await self.session.execute(
            update(PlayerProfile).where(PlayerProfile.user_id == user_id).values(**values)
        )
        if result.rowcount != 1:
            raise NotFoundError("player profile not found")
        await self.session.flush()
        profile = await self.get_by_user_id(user_id)
        if profile is None:  # pragma: no cover - defensive
            raise NotFoundError("player profile not found")
        return profile


class GameSessionRepository(BaseRepository[GameSession]):
    async def get_by_id(self, session_id: uuid.UUID) -> GameSession | None:
        return await self.session.get(GameSession, session_id)

    async def list_by_user(
        self,
        *,
        user_id: uuid.UUID,
        status: str | None = None,
        limit: int = 50,
    ) -> list[GameSession]:
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= 200
        ):
            raise ValueError("limit must be an int in 1..200")
        stmt = (
            select(GameSession)
            .where(GameSession.user_id == user_id)
            .order_by(GameSession.started_at.desc())
            .limit(limit)
        )
        if status is not None:
            if status not in SESSION_STATUSES:
                raise ValueError(f"unknown status: {status}")
            stmt = stmt.where(GameSession.status == status)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def history_by_user(
        self,
        *,
        user_id: uuid.UUID,
        limit: int = 20,
        offset: int = 0,
    ) -> list[tuple[GameSession, GameResult | None]]:
        """Recent sessions with their results in one query (outer join)."""
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= 100
        ):
            raise ValueError("limit must be an int in 1..100")
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise ValueError("offset must be an int >= 0")
        result = await self.session.execute(
            select(GameSession, GameResult)
            .outerjoin(GameResult, GameResult.session_id == GameSession.id)
            .where(GameSession.user_id == user_id)
            .order_by(GameSession.started_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.all())

    async def create(self, *, user_id: uuid.UUID, game_type: str) -> GameSession:
        game_type = _require_name(game_type, field="game_type", limit=64)
        assert game_type is not None
        row = GameSession(user_id=user_id, game_type=game_type, status="started")
        self.session.add(row)
        await self.session.flush()
        return row

    async def finish(
        self,
        *,
        session_id: uuid.UUID,
        status: str,
        score: int,
        ended_at: Any,
        duration_seconds: int | None,
    ) -> GameSession:
        """Transition a started session to a terminal status. Returns fresh row."""
        if status not in TERMINAL_STATUSES:
            raise ValueError(f"status must be one of {sorted(TERMINAL_STATUSES)}")
        _require_non_negative_int(score, field="score")
        if duration_seconds is not None:
            _require_non_negative_int(duration_seconds, field="duration_seconds")

        row = await self.get_by_id(session_id)
        if row is None:
            raise NotFoundError("game session not found")
        if row.status != "started":
            raise ConflictError(f"session is already {row.status}")

        await self.session.execute(
            update(GameSession)
            .where(GameSession.id == session_id)
            .where(GameSession.status == "started")
            .values(
                status=status,
                score=score,
                ended_at=ended_at,
                duration_seconds=duration_seconds,
            )
        )
        await self.session.flush()
        fresh = await self.get_by_id(session_id)
        if fresh is None:  # pragma: no cover - defensive
            raise NotFoundError("game session not found")
        return fresh

    async def abandon(self, *, session_id: uuid.UUID, ended_at: Any) -> GameSession:
        """Abandon without recording a result or stats. Returns fresh row."""
        return await self.finish(
            session_id=session_id,
            status="abandoned",
            score=0,
            ended_at=ended_at,
            duration_seconds=None,
        )


class GameResultRepository(BaseRepository[GameResult]):
    async def get_by_session(self, session_id: uuid.UUID) -> GameResult | None:
        result = await self.session.execute(
            select(GameResult).where(GameResult.session_id == session_id)
        )
        return result.scalar_one_or_none()

    async def best_win_score(
        self, *, user_id: uuid.UUID, game_type: str | None = None
    ) -> int | None:
        """Fewest attempts in any won game (personal best), or None.

        Pass game_type to scope the best to one game; None keeps the legacy
        cross-game behavior.
        """
        stmt = (
            select(func.min(GameResult.score))
            .join(GameSession, GameSession.id == GameResult.session_id)
            .where(GameSession.user_id == user_id, GameResult.outcome == "win")
        )
        if game_type is not None:
            stmt = stmt.where(GameSession.game_type == game_type)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def best_score_for_game(
        self, *, user_id: uuid.UUID, game_type: str
    ) -> int | None:
        """Highest score in any completed game of one type (personal best).

        Used by games where higher is better (e.g. Color Sequence levels).
        Abandoned sessions have no result row and never count.
        """
        result = await self.session.execute(
            select(func.max(GameResult.score))
            .join(GameSession, GameSession.id == GameResult.session_id)
            .where(
                GameSession.user_id == user_id,
                GameSession.game_type == game_type,
                GameSession.status == "completed",
            )
        )
        return result.scalar_one_or_none()

    async def record(
        self,
        *,
        session_id: uuid.UUID,
        score: int,
        outcome: str,
        xp_earned: int,
        metadata: dict | None = None,
    ) -> GameResult:
        _require_non_negative_int(score, field="score")
        _require_non_negative_int(xp_earned, field="xp_earned")
        if outcome not in OUTCOMES:
            raise ValueError(f"outcome must be one of {sorted(OUTCOMES)}")
        if metadata is not None and not isinstance(metadata, dict):
            raise ValueError("metadata must be a dict or None")
        row = GameResult(
            session_id=session_id,
            score=score,
            outcome=outcome,
            xp_earned=xp_earned,
            result_metadata=dict(metadata) if metadata else {},
        )
        self.session.add(row)
        await self.session.flush()
        return row


class DailyActivityRepository(BaseRepository[DailyActivity]):
    async def get(
        self, *, user_id: uuid.UUID, day: date
    ) -> DailyActivity | None:
        if not isinstance(day, date):
            raise ValueError("day must be a datetime.date")
        result = await self.session.execute(
            select(DailyActivity).where(
                DailyActivity.user_id == user_id,
                DailyActivity.activity_date == day,
            )
        )
        return result.scalar_one_or_none()

    async def get_or_create(
        self, *, user_id: uuid.UUID, day: date
    ) -> tuple[DailyActivity, bool]:
        if not isinstance(day, date):
            raise ValueError("day must be a datetime.date")
        existing = await self.get(user_id=user_id, day=day)
        if existing is not None:
            return existing, False
        result = await self.session.execute(
            pg_insert(DailyActivity)
            .values(user_id=user_id, activity_date=day)
            .on_conflict_do_nothing(
                constraint="uq_daily_activities_user_date"
            )
        )
        created = result.rowcount == 1
        await self.session.flush()
        row = await self.get(user_id=user_id, day=day)
        if row is None:  # pragma: no cover - defensive
            raise NotFoundError("daily activity row missing right after upsert")
        return row, created

    async def add_play(
        self, *, user_id: uuid.UUID, day: date, xp_earned: int
    ) -> DailyActivity:
        """Ensure today's row exists, then atomically bump counters."""
        _require_non_negative_int(xp_earned, field="xp_earned")
        await self.get_or_create(user_id=user_id, day=day)
        await self.session.execute(
            update(DailyActivity)
            .where(
                DailyActivity.user_id == user_id,
                DailyActivity.activity_date == day,
            )
            .values(
                games_played=DailyActivity.games_played + 1,
                xp_earned=DailyActivity.xp_earned + xp_earned,
            )
        )
        await self.session.flush()
        row = await self.get(user_id=user_id, day=day)
        if row is None:  # pragma: no cover - defensive
            raise NotFoundError("daily activity not found")
        return row


class WebappStateRepository(BaseRepository[WebappGameState]):
    """Server-side in-progress game rows. No commits; services own txns."""

    async def get_for_update(
        self, *, session_id: uuid.UUID
    ) -> WebappGameState | None:
        """Load with a row lock: concurrent guesses serialize here."""
        result = await self.session.execute(
            select(WebappGameState)
            .where(WebappGameState.session_id == session_id)
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def list_active_by_user(
        self, *, user_id: uuid.UUID
    ) -> list[tuple[WebappGameState, GameSession]]:
        """State rows whose session is still `started` (single query)."""
        result = await self.session.execute(
            select(WebappGameState, GameSession)
            .join(GameSession, GameSession.id == WebappGameState.session_id)
            .where(
                WebappGameState.user_id == user_id,
                GameSession.status == "started",
            )
        )
        return list(result.all())

    async def create(
        self,
        *,
        user_id: uuid.UUID,
        session_id: uuid.UUID,
        game_type: str,
        difficulty: str,
        secret: int,
        max_attempts: int,
    ) -> WebappGameState:
        row = WebappGameState(
            user_id=user_id,
            session_id=session_id,
            game_type=game_type,
            difficulty=difficulty,
            secret=secret,
            max_attempts=max_attempts,
            guesses=[],
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def delete(self, row: WebappGameState) -> None:
        await self.session.delete(row)
        await self.session.flush()


def _require_code(value: Any) -> str:
    import re

    if not isinstance(value, str):
        raise ValueError("referral code must be a string")
    code = value.strip()
    if not re.fullmatch(r"[A-Za-z0-9]{4,32}", code):
        raise ValueError("invalid referral code")
    return code


def _new_referral_code() -> str:
    import secrets
    import string

    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(10))


class ReferralRepository(BaseRepository[ReferralCode]):
    """Referral codes + attributions. No commits; services own txns."""

    async def get_or_create_code(self, *, user_id: uuid.UUID) -> tuple[ReferralCode, bool]:
        """Stable per-user code: repeated calls never mint extras."""
        result = await self.session.execute(
            select(ReferralCode).where(ReferralCode.referrer_user_id == user_id)
        )
        existing = result.scalar_one_or_none()
        if existing is not None:
            return existing, False
        # 62^10 space makes collisions practically impossible; a leftover
        # IntegrityError propagates and rolls back via the service txn.
        row = ReferralCode(code=_new_referral_code(), referrer_user_id=user_id)
        self.session.add(row)
        await self.session.flush()
        return row, True

    async def get_by_code(self, *, code: str) -> ReferralCode | None:
        code = _require_code(code)
        result = await self.session.execute(
            select(ReferralCode).where(ReferralCode.code == code)
        )
        return result.scalar_one_or_none()

    async def get_attribution_for(
        self, *, referred_user_id: uuid.UUID
    ) -> ReferralAttribution | None:
        result = await self.session.execute(
            select(ReferralAttribution).where(
                ReferralAttribution.referred_user_id == referred_user_id
            )
        )
        return result.scalar_one_or_none()

    async def record_attribution(
        self,
        *,
        code: str,
        referrer_user_id: uuid.UUID,
        referred_user_id: uuid.UUID,
        referrer_xp: int,
        referred_xp: int,
    ) -> ReferralAttribution:
        """Insert one attribution row. Unique(referred_user_id) makes a second
        claim for the same newcomer fail atomically (IntegrityError)."""
        _require_non_negative_int(referrer_xp, field="referrer_xp")
        _require_non_negative_int(referred_xp, field="referred_xp")
        row = ReferralAttribution(
            code=code,
            referrer_user_id=referrer_user_id,
            referred_user_id=referred_user_id,
            referrer_xp=referrer_xp,
            referred_xp=referred_xp,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def count_credited(self, *, referrer_user_id: uuid.UUID) -> int:
        result = await self.session.execute(
            select(func.count())
            .select_from(ReferralAttribution)
            .where(ReferralAttribution.referrer_user_id == referrer_user_id)
        )
        return result.scalar_one_or_none() or 0

    async def sum_referrer_xp(self, *, referrer_user_id: uuid.UUID) -> int:
        result = await self.session.execute(
            select(func.coalesce(func.sum(ReferralAttribution.referrer_xp), 0))
            .select_from(ReferralAttribution)
            .where(ReferralAttribution.referrer_user_id == referrer_user_id)
        )
        return result.scalar_one_or_none() or 0
