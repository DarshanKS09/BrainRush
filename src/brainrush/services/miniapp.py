"""Mini App game orchestration: one transaction per method, same as services.

Reuses the existing repositories (users, sessions, results, profiles,
activities) plus the new webapp state rows. Game math (secret compare, XP,
levels) comes from brainrush.game; this module only orchestrates.

Safety properties:
  - Secret, difficulty, and attempt limits are read from the server-side state
    row, never from the request (frontend values are only echoed for UX).
  - Each guess runs under SELECT ... FOR UPDATE on the state row, so
    concurrent guesses serialize; the loser's view is rebuilt from fresh data.
  - `client_guess_id` makes retries idempotent: a repeated id returns the
    current public view without consuming an attempt or awarding XP twice.
  - Terminal guesses finish (session + result + profile + activity) and delete
    the state row in the same transaction; replays return the stored result.
  - Abandoned games record no result and award no XP.
"""
from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from brainrush.db.errors import ConflictError, NotFoundError
from brainrush.db.models import GameSession
from brainrush.db.repository import (
    DailyActivityRepository,
    GameResultRepository,
    GameSessionRepository,
    PlayerProfileRepository,
    UserRepository,
    WebappStateRepository,
)
from brainrush.game import number_guessing as guessing
from brainrush.game.progression import level_for_xp
from brainrush.services import utcnow

GAME_TYPE_NUMBER_GUESSING = "number_guessing"

DIFFICULTIES: dict[str, guessing.NumberGuessingConfig] = {
    "easy": guessing.NumberGuessingConfig(max_attempts=15),
    "medium": guessing.NumberGuessingConfig(max_attempts=10),
    "hard": guessing.NumberGuessingConfig(),
}

CATALOG = [
    {
        "id": "number_guessing",
        "title": "Number Guessing",
        "description": "Find the secret number from 1 to 100 before you run out of guesses.",
        "playable": True,
        "difficulties": [
            {"id": did, "max_attempts": cfg.max_attempts}
            for did, cfg in DIFFICULTIES.items()
        ],
    },
    {
        "id": "memory_match",
        "title": "Memory Match",
        "description": "Flip cards and match every pair.",
        "playable": False,
        "difficulties": [],
    },
    {
        "id": "reaction_test",
        "title": "Reaction Test",
        "description": "Tap the moment the screen changes.",
        "playable": False,
        "difficulties": [],
    },
    {
        "id": "math_challenge",
        "title": "Math Challenge",
        "description": "Solve arithmetic against the clock.",
        "playable": False,
        "difficulties": [],
    },
    {
        "id": "word_puzzle",
        "title": "Word Puzzle",
        "description": "Unscramble the hidden word.",
        "playable": False,
        "difficulties": [],
    },
]


def _config_for(difficulty: str) -> guessing.NumberGuessingConfig:
    try:
        return DIFFICULTIES[difficulty]
    except KeyError:
        raise ValueError(f"difficulty must be one of {sorted(DIFFICULTIES)}") from None


def _hint(value: int, secret: int) -> str:
    return "high" if value > secret else "low"


def _public_view(state, guesses: list[dict]) -> dict:
    used = len(guesses)
    return {
        "session_id": str(state.session_id),
        "game_type": state.game_type,
        "difficulty": state.difficulty,
        "max_attempts": state.max_attempts,
        "attempts_used": used,
        "attempts_left": max(0, state.max_attempts - used),
        "guesses": [
            {"value": g["value"], "hint": _hint(g["value"], state.secret)}
            for g in guesses
        ],
        "status": "started",
        "finished": False,
        "result": None,
    }


def _completed_view(session_row: GameSession, result_row, guesses: list[dict]) -> dict:
    meta = dict(result_row.result_metadata or {})
    return {
        "session_id": str(session_row.id),
        "game_type": meta.get("game", GAME_TYPE_NUMBER_GUESSING),
        "difficulty": meta.get("difficulty", "hard"),
        "max_attempts": meta.get("max_attempts"),
        "attempts_used": meta.get("attempts", session_row.score),
        "attempts_left": 0,
        "guesses": [
            {"value": g["value"] if isinstance(g, dict) else g,
             "hint": _hint(g["value"] if isinstance(g, dict) else g,
                           meta.get("secret", 0))}
            for g in guesses
        ],
        "status": session_row.status,
        "finished": True,
        "result": {
            "outcome": result_row.outcome,
            "score": result_row.score,
            "xp_earned": result_row.xp_earned,
            "secret": meta.get("secret"),
        },
    }


class MiniappGameService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.users = UserRepository(session)
        self.sessions = GameSessionRepository(session)
        self.results = GameResultRepository(session)
        self.profiles = PlayerProfileRepository(session)
        self.activities = DailyActivityRepository(session)
        self.states = WebappStateRepository(session)

    async def start_game(
        self, *, user_id: uuid.UUID, difficulty: str = "hard"
    ) -> dict:
        """Abandon leftover webapp games, then start fresh. Returns public view."""
        config = _config_for(difficulty)
        async with self.session.begin():
            if await self.users.get_by_id(user_id) is None:
                raise NotFoundError("user not found")
            for state, _ in await self.states.list_active_by_user(user_id=user_id):
                await self.sessions.abandon(session_id=state.session_id, ended_at=utcnow())
                await self.states.delete(state)
            db_row = await self.sessions.create(
                user_id=user_id, game_type=GAME_TYPE_NUMBER_GUESSING
            )
            secret = guessing.roll_secret(config)
            state = await self.states.create(
                user_id=user_id,
                session_id=db_row.id,
                game_type=GAME_TYPE_NUMBER_GUESSING,
                difficulty=difficulty,
                secret=secret,
                max_attempts=config.max_attempts,
            )
            return _public_view(state, [])

    async def guess(
        self,
        *,
        session_id: uuid.UUID,
        user_id: uuid.UUID,
        value: int,
        client_guess_id: str,
    ) -> dict:
        """Submit one guess. Idempotent per client_guess_id; secret enforced."""
        if not isinstance(client_guess_id, str) or not client_guess_id.strip():
            raise ValueError("client_guess_id must be a non-empty string")
        async with self.session.begin():
            state = await self.states.get_for_update(session_id=session_id)
            if state is None or state.user_id != user_id:
                # Either finished (state deleted) or foreign: replay stored
                # result when owned+completed, else 404 without leaking.
                return await self._replay_or_missing(session_id, user_id)
            config = _config_for(state.difficulty)
            try:
                guessing.parse_guess(str(value), config)
            except guessing.InvalidGuessError as exc:
                raise ValueError(str(exc)) from None
            guesses = list(state.guesses or [])
            if any(g.get("id") == client_guess_id for g in guesses):
                return _public_view(state, guesses)
            tentative = [g["value"] for g in guesses] + [value]
            if value == state.secret:
                return await self._complete(
                    state, guesses, value, client_guess_id, won=True, config=config
                )
            if len(tentative) >= state.max_attempts:
                return await self._complete(
                    state, guesses, value, client_guess_id, won=False, config=config
                )
            state.guesses = [*guesses, {"id": client_guess_id, "value": value}]
            await self.session.flush()
            return _public_view(state, state.guesses)

    async def _complete(self, state, guesses, value, client_guess_id, *, won, config):
        from brainrush.services import utcnow as _utcnow

        moment = _utcnow()
        attempts_used = len(guesses) + 1
        xp = guessing.xp_for_result(
            won=won, attempts_used=attempts_used, config=config
        )
        metadata = {
            "game": GAME_TYPE_NUMBER_GUESSING,
            "difficulty": state.difficulty,
            "max_attempts": state.max_attempts,
            "secret": state.secret,
            "guesses": [g["value"] for g in guesses] + [value],
            "attempts": attempts_used,
            "range": [config.min_value, config.max_value],
        }
        session_row = await self.sessions.finish(
            session_id=state.session_id,
            status="completed",
            score=attempts_used,
            ended_at=moment,
            duration_seconds=None,
        )
        result_row = await self.results.record(
            session_id=state.session_id,
            score=attempts_used,
            outcome="win" if won else "loss",
            xp_earned=xp,
            metadata=metadata,
        )
        profile = await self.profiles.record_game(
            user_id=state.user_id,
            xp_earned=xp,
            won=won,
            new_level=None,
        )
        await self.profiles.set_level(
            user_id=state.user_id, level=level_for_xp(profile.total_xp)
        )
        await self.activities.add_play(
            user_id=state.user_id, day=moment.date(), xp_earned=xp
        )
        await self.states.delete(state)
        return _completed_view(
            session_row, result_row, [*guesses, {"id": client_guess_id, "value": value}]
        )

    async def _replay_or_missing(self, session_id, user_id) -> dict:
        session_row = await self.sessions.get_by_id(session_id)
        if session_row is None or session_row.user_id != user_id:
            raise NotFoundError("game session not found")
        if session_row.status != "completed":
            raise NotFoundError("game session not found")
        result_row = await self.results.get_by_session(session_id)
        if result_row is None:  # pragma: no cover - defensive
            raise NotFoundError("game result not found")
        meta = dict(result_row.result_metadata or {})
        stored = [
            {"id": f"past-{i}", "value": v}
            for i, v in enumerate(meta.get("guesses", []))
        ]
        return _completed_view(session_row, result_row, stored)

    async def get_state(self, *, session_id: uuid.UUID, user_id: uuid.UUID) -> dict:
        async with self.session.begin():
            state = await self.states.get_for_update(session_id=session_id)
            if state is not None:
                if state.user_id != user_id:
                    raise NotFoundError("game session not found")
                return _public_view(state, list(state.guesses or []))
            return await self._replay_or_missing(session_id, user_id)

    async def cancel(self, *, session_id: uuid.UUID, user_id: uuid.UUID) -> dict:
        """Abandon without result or XP. Idempotent: already-gone is fine."""
        async with self.session.begin():
            state = await self.states.get_for_update(session_id=session_id)
            if state is not None:
                if state.user_id != user_id:
                    raise NotFoundError("game session not found")
                try:
                    await self.sessions.abandon(
                        session_id=session_id, ended_at=utcnow()
                    )
                except (NotFoundError, ConflictError):
                    pass
                await self.states.delete(state)
                return {"session_id": str(session_id), "status": "abandoned"}
            session_row = await self.sessions.get_by_id(session_id)
            if session_row is None or session_row.user_id != user_id:
                raise NotFoundError("game session not found")
            return {"session_id": str(session_id), "status": session_row.status}

    async def dashboard(self, *, user_id: uuid.UUID) -> dict:
        """One read transaction: user, profile + level progress, today, best."""
        from brainrush.game.progression import progress_for_xp
        from brainrush.services import utc_today

        async with self.session.begin():
            user = await self.users.get_by_id(user_id)
            if user is None:
                raise NotFoundError("user not found")
            profile = await self.profiles.get_by_user_id(user_id)
            if profile is None:
                raise NotFoundError("player profile not found")
            today = await self.activities.get(
                user_id=user_id, day=utc_today()
            )
            best = await self.results.best_win_score(user_id=user_id)
            rank = await self.profiles.rank_by_xp(total_xp=profile.total_xp)
            actives = await self.states.list_active_by_user(user_id=user_id)
            progress = progress_for_xp(profile.total_xp)
            return {
                "user": {
                    "telegram_id": user.telegram_id,
                    "username": user.username,
                    "display_name": user.display_name,
                },
                "profile": {
                    "level": progress["level"],
                    "total_xp": profile.total_xp,
                    "xp_into_level": progress["xp_into_level"],
                    "xp_for_next": progress["xp_for_next"],
                    "games_played": profile.games_played,
                    "wins": profile.wins,
                    "losses": profile.losses,
                    "current_streak": profile.current_streak,
                    "longest_streak": profile.longest_streak,
                },
                "today": {
                    "games_played": today.games_played if today else 0,
                    "xp_earned": today.xp_earned if today else 0,
                },
                "best_win_attempts": best,
                "rank": rank,
                "active_games": [
                    _public_view(state, list(state.guesses or []))
                    for state, _ in actives
                ],
            }

    async def history(
        self, *, user_id: uuid.UUID, limit: int = 20, offset: int = 0
    ) -> list[dict]:
        async with self.session.begin():
            rows = await self.sessions.history_by_user(
                user_id=user_id, limit=limit, offset=offset
            )
            out = []
            for session_row, result_row in rows:
                out.append(
                    {
                        "session_id": str(session_row.id),
                        "game_type": session_row.game_type,
                        "status": session_row.status,
                        "score": session_row.score,
                        "started_at": session_row.started_at.isoformat(),
                        "ended_at": session_row.ended_at.isoformat()
                        if session_row.ended_at
                        else None,
                        "outcome": result_row.outcome if result_row else None,
                        "xp_earned": result_row.xp_earned if result_row else 0,
                    }
                )
            return out

    async def leaderboard(
        self, *, limit: int = 20, offset: int = 0, user_id: uuid.UUID | None = None
    ) -> dict:
        async with self.session.begin():
            rows = await self.profiles.top_by_xp(limit=limit, offset=offset)
            entries = []
            for i, (profile, user) in enumerate(rows, start=offset + 1):
                entries.append(
                    {
                        "rank": i,
                        "display_name": user.display_name or user.username or "Player",
                        "username": user.username,
                        "level": level_for_xp(profile.total_xp),
                        "total_xp": profile.total_xp,
                        "wins": profile.wins,
                    }
                )
            my_rank = None
            if user_id is not None:
                mine = await self.profiles.get_by_user_id(user_id)
                if mine is not None:
                    my_rank = await self.profiles.rank_by_xp(
                        total_xp=mine.total_xp
                    )
            return {"entries": entries, "my_rank": my_rank}
