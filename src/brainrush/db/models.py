"""Initial production-ready schema (tables only, no game logic).

Tables: users, player_profiles, game_sessions, game_results, daily_activities,
referral_codes, referral_attributions, friend_codes, friendships.
Primary keys are UUID; Telegram user IDs stay BIGINT. All timestamps are
timezone-aware. Status/outcome use CHECK constraints instead of PG ENUMs so
future value additions are non-destructive (no ALTER TYPE ... ADD VALUE).
"""
from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    UUID,
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from brainrush.db.base import Base


def _tz_now() -> DateTime:
    return DateTime(timezone=True)


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, default=uuid.uuid4)
    telegram_id: Mapped[int] = mapped_column(
        BigInteger, unique=True, index=True, nullable=False
    )
    username: Mapped[str | None] = mapped_column(String(32), index=True, nullable=True)
    display_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        _tz_now(), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        _tz_now(), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    profile: Mapped[PlayerProfile | None] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        single_parent=True,
        uselist=False,
    )
    sessions: Mapped[list[GameSession]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    activities: Mapped[list[DailyActivity]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class PlayerProfile(Base):
    __tablename__ = "player_profiles"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_player_profiles_user_id"),
        CheckConstraint("total_xp >= 0", name="total_xp_non_negative"),
        CheckConstraint("current_level >= 1", name="current_level_min_1"),
        CheckConstraint("games_played >= 0", name="games_played_non_negative"),
        CheckConstraint("wins >= 0", name="wins_non_negative"),
        CheckConstraint("losses >= 0", name="losses_non_negative"),
        CheckConstraint("current_streak >= 0", name="current_streak_non_negative"),
        CheckConstraint("longest_streak >= 0", name="longest_streak_non_negative"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    total_xp: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    current_level: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    games_played: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    wins: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    losses: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    current_streak: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    longest_streak: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        _tz_now(), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        _tz_now(), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    user: Mapped[User] = relationship(back_populates="profile")


class GameSession(Base):
    __tablename__ = "game_sessions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('started', 'completed', 'abandoned', 'expired')",
            name="status_allowed_values",
        ),
        CheckConstraint("score >= 0", name="score_non_negative"),
        CheckConstraint(
            "duration_seconds IS NULL OR duration_seconds >= 0",
            name="duration_non_negative",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    game_type: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="started", nullable=False)
    score: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        _tz_now(), server_default=func.now(), nullable=False
    )
    ended_at: Mapped[datetime | None] = mapped_column(_tz_now(), nullable=True)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)

    user: Mapped[User] = relationship(back_populates="sessions")
    result: Mapped[GameResult | None] = relationship(
        back_populates="session", cascade="all, delete-orphan", uselist=False
    )


class GameResult(Base):
    __tablename__ = "game_results"
    __table_args__ = (
        UniqueConstraint("session_id", name="uq_game_results_session_id"),
        CheckConstraint("score >= 0", name="result_score_non_negative"),
        CheckConstraint(
            "outcome IN ('win', 'loss', 'draw')", name="outcome_allowed_values"
        ),
        CheckConstraint("xp_earned >= 0", name="xp_earned_non_negative"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("game_sessions.id", ondelete="CASCADE"), nullable=False
    )
    score: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    xp_earned: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    result_metadata: Mapped[dict] = mapped_column(
        "metadata", JSONB, default=dict, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        _tz_now(), server_default=func.now(), nullable=False
    )

    session: Mapped[GameSession] = relationship(back_populates="result")


class DailyActivity(Base):
    __tablename__ = "daily_activities"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "activity_date", name="uq_daily_activities_user_date"
        ),
        CheckConstraint("games_played >= 0", name="activity_games_non_negative"),
        CheckConstraint("xp_earned >= 0", name="activity_xp_non_negative"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    activity_date: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    games_played: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    xp_earned: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        _tz_now(), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        _tz_now(), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    user: Mapped[User] = relationship(back_populates="activities")


class ReferralCode(Base):
    """Stable per-user referral code. One row per referrer, created on demand."""

    __tablename__ = "referral_codes"

    code: Mapped[str] = mapped_column(String(32), primary_key=True)
    referrer_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        _tz_now(), server_default=func.now(), nullable=False
    )


class ReferralAttribution(Base):
    """One credited referral per referred user. Unique referred_user_id makes
    double-claims (including races) impossible at the database level."""

    __tablename__ = "referral_attributions"

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(
        ForeignKey("referral_codes.code", ondelete="RESTRICT"), nullable=False
    )
    referrer_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    referred_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    referrer_xp: Mapped[int] = mapped_column(Integer, nullable=False)
    referred_xp: Mapped[int] = mapped_column(Integer, nullable=False)
    credited_at: Mapped[datetime] = mapped_column(
        _tz_now(), server_default=func.now(), nullable=False
    )


class FriendCode(Base):
    """Stable per-user friend code. One row per user, created on demand.

    Separate from referral codes on purpose: friendships never grant XP and
    must never interact with referral attribution.
    """

    __tablename__ = "friend_codes"

    code: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        _tz_now(), server_default=func.now(), nullable=False
    )


class Friendship(Base):
    """One row per unordered user pair (canonical user_low/user_high order).

    Unique(user_low, user_high) plus the ordering makes duplicate friendships
    (including concurrent inserts and A-adds-B vs B-adds-A races) impossible
    at the database level. The relationship is symmetric: queries match
    either side.
    """

    __tablename__ = "friendships"
    __table_args__ = (
        UniqueConstraint("user_low", "user_high", name="uq_friendships_pair"),
        CheckConstraint("user_low != user_high", name="no_self_friendship"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, default=uuid.uuid4)
    user_low: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    user_high: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        _tz_now(), server_default=func.now(), nullable=False
    )


class WebappGameState(Base):
    """Server-side in-progress state for Mini App games.

    Why a table: the bot's in-memory ActiveGameStore is single-process, but
    HTTP requests may hit any worker and must survive restarts. The secret,
    difficulty, and per-guess idempotency keys live here until completion, at
    which point finish writes the result row and this row is deleted. The
    secret is never serialized to clients (see the API layer's public view).
    """

    __tablename__ = "webapp_game_states"
    __table_args__ = (
        UniqueConstraint("session_id", name="uq_webapp_game_states_session_id"),
        CheckConstraint(
            "difficulty IN ('easy', 'medium', 'hard')",
            name="difficulty_allowed_values",
        ),
        CheckConstraint("max_attempts >= 1", name="max_attempts_min_1"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("game_sessions.id", ondelete="CASCADE"), nullable=False
    )
    game_type: Mapped[str] = mapped_column(String(64), nullable=False)
    difficulty: Mapped[str] = mapped_column(
        String(16), default="hard", nullable=False
    )
    secret: Mapped[int] = mapped_column(Integer, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    guesses: Mapped[list] = mapped_column(
        "guesses", JSONB, default=list, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        _tz_now(), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        _tz_now(), server_default=func.now(), onupdate=func.now(), nullable=False
    )
