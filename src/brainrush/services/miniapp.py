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
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from brainrush.db.errors import ConflictError, NotFoundError
from brainrush.db.models import GameSession
from brainrush.db.repository import (
    DailyActivityRepository,
    GameResultRepository,
    GameSessionRepository,
    MatchParticipantRepository,
    MatchRepository,
    PlayerProfileRepository,
    UserRepository,
    WebappStateRepository,
)
from brainrush.game import number_guessing as guessing
from brainrush.game import color_sequence as colors
from brainrush.game import perfect_second as perfect
from brainrush.game import reflex_rush as reflex
from brainrush.game import multiplayer as mp
from brainrush.game.progression import level_for_xp
from brainrush.services import utcnow

GAME_TYPE_NUMBER_GUESSING = "number_guessing"
GAME_TYPE_COLOR_SEQUENCE = "color_sequence"
GAME_TYPE_REFLEX_RUSH = "reflex_rush"
GAME_TYPE_PERFECT_SECOND = perfect.GAME_TYPE

# Sessions left `started` longer than this are dead (app closed, failed
# submit, lobby exit without cancel): genuinely active games finish in
# minutes, so a day is conservative. Expired rows keep their history.
STALE_SESSION_TTL = timedelta(hours=24)

PLAYABLE_GAME_TYPES = frozenset({GAME_TYPE_NUMBER_GUESSING, GAME_TYPE_COLOR_SEQUENCE, GAME_TYPE_REFLEX_RUSH, GAME_TYPE_PERFECT_SECOND})

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
        "id": "color_sequence",
        "title": "Color Sequence",
        "description": "Watch the flashing colors, then repeat the sequence. Survive to the final level.",
        "playable": True,
        "difficulties": [
            {
                "id": did,
                "max_attempts": cfg.max_level,
                "start_length": cfg.start_length,
                "playback_ms": cfg.playback_ms,
            }
            for did, cfg in colors.COLOR_DIFFICULTIES.items()
        ],
    },
    {
        "id": "reflex_rush",
        "title": "Reflex Rush",
        "description": "Wait for green, then tap fast. Five rounds against the clock.",
        "playable": True,
        "difficulties": [
            {
                "id": did,
                "max_attempts": cfg.rounds,
                "wait_min_ms": cfg.wait_min_ms,
                "wait_max_ms": cfg.wait_max_ms,
            }
            for did, cfg in reflex.REFLEX_DIFFICULTIES.items()
        ],
    },
    {
        "id": "perfect_second",
        "title": "Perfect Second",
        "description": "Start the clock, then tap STOP exactly on the target time.",
        "playable": True,
        "difficulties": [
            {
                "id": did,
                "max_attempts": 1,
                "target_min_ms": cfg.min_target_ms,
                "target_max_ms": cfg.max_target_ms,
                "target_step_ms": cfg.step_ms,
            }
            for did, cfg in perfect.PERFECT_DIFFICULTIES.items()
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


def _color_public_view(state, data: dict) -> dict:
    """Public Color Sequence state: only the prefix the player must repeat.

    Future colors do not exist yet server-side (appended per completed
    level), so nothing beyond the current prefix can leak.
    """
    level = data["level"]
    return {
        "session_id": str(state.session_id),
        "game_type": state.game_type,
        "difficulty": state.difficulty,
        "max_attempts": state.max_attempts,
        "display": list(data["sequence"][:level]),
        "position": data["position"],
        "level": level,
        "max_level": state.max_attempts,
        "levels_completed": data["levels_completed"],
        "moves": list(data["log"]),
        "status": "started",
        "finished": False,
        "result": None,
    }


def _new_color_data(config: colors.ColorSequenceConfig, rng=None) -> dict:
    return {
        "sequence": colors.new_sequence(config.start_length, rng),
        "position": 0,
        "level": config.start_length,
        "levels_completed": 0,
        "log": [],
    }


def _reflex_public_view(state) -> dict:
    """Public Reflex Rush state: lobby info only, no timing secrets.

    Reaction timing is measured client-side per round and submitted once
    at the end, so there is nothing to leak mid-game beyond the config.
    """
    return {
        "session_id": str(state.session_id),
        "game_type": state.game_type,
        "difficulty": state.difficulty,
        "max_attempts": state.max_attempts,
        "rounds_total": state.max_attempts,
        "rounds_played": 0,
        "status": "started",
        "finished": False,
        "result": None,
    }


def _perfect_public_view(state) -> dict:
    """Public Perfect Second state: the target is VISIBLE by design.

    The clock runs client-side from the player's own START tap; the server
    only stores the target (in `secret`) and scores the submitted stop time.
    """
    return {
        "session_id": str(state.session_id),
        "game_type": state.game_type,
        "difficulty": state.difficulty,
        "target_ms": state.secret,
        "max_attempts": 1,
        "attempts_used": 0,
        "attempts_left": 1,
        "status": "started",
        "finished": False,
        "result": None,
    }


def _active_view(state) -> dict:
    """Public view for a resumed game, dispatched by game type."""
    if state.game_type == GAME_TYPE_COLOR_SEQUENCE:
        return _color_public_view(state, dict(state.guesses or {}))
    if state.game_type == GAME_TYPE_REFLEX_RUSH:
        return _reflex_public_view(state)
    if state.game_type == GAME_TYPE_PERFECT_SECOND:
        return _perfect_public_view(state)
    return _public_view(state, list(state.guesses or []))


def _completed_view(session_row: GameSession, result_row, guesses: list[dict]) -> dict:
    meta = dict(result_row.result_metadata or {})
    if meta.get("game") == GAME_TYPE_COLOR_SEQUENCE:
        rendered = [
            {"value": g["value"], "hint": "hit" if g.get("hit") else "miss"}
            for g in guesses
            if isinstance(g, dict)
        ]
    elif meta.get("game") == GAME_TYPE_REFLEX_RUSH:
        rendered = [
            {
                "reaction_ms": g.get("reaction_ms"),
                "false_start": bool(g.get("false_start", False)),
            }
            for g in guesses
            if isinstance(g, dict)
        ]
    else:
        rendered = [
            {"value": g["value"] if isinstance(g, dict) else g,
             "hint": _hint(g["value"] if isinstance(g, dict) else g,
                           meta.get("secret", 0))}
            for g in guesses
        ]
    result: dict = {
        "outcome": result_row.outcome,
        "score": result_row.score,
        "xp_earned": result_row.xp_earned,
        "secret": meta.get("secret"),
    }
    if meta.get("game") == GAME_TYPE_REFLEX_RUSH:
        result.update({
            "avg_ms": meta.get("avg_ms"),
            "best_ms": meta.get("best_ms"),
            "false_starts": meta.get("false_starts", 0),
            "rounds": rendered,
        })
    if meta.get("game") == GAME_TYPE_PERFECT_SECOND:
        result.update({
            "target_ms": meta.get("target_ms"),
            "actual_ms": meta.get("actual_ms"),
            "error_ms": meta.get("error_ms"),
            "accuracy_percent": meta.get("accuracy_percent"),
        })
    return {
        "session_id": str(session_row.id),
        "game_type": meta.get("game", GAME_TYPE_NUMBER_GUESSING),
        "difficulty": meta.get("difficulty", "hard"),
        "max_attempts": meta.get("max_attempts"),
        "attempts_used": meta.get("attempts", session_row.score),
        "attempts_left": 0,
        "guesses": rendered,
        "status": session_row.status,
        "finished": True,
        "result": result,
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

    async def _expire_stale_locked(self, *, user_id: uuid.UUID) -> int:
        """Expire the user's long-unfinished sessions (no new transaction:
        callers invoke this inside their own `begin()` block)."""
        cutoff = utcnow() - STALE_SESSION_TTL
        expired = await self.sessions.expire_stale_started(
            user_id=user_id, before=cutoff
        )
        if expired:
            await self.states.delete_for_expired_sessions(user_id=user_id)
        return expired

    async def start_game(
        self, *, user_id: uuid.UUID, difficulty: str = "hard",
        game_type: str = GAME_TYPE_NUMBER_GUESSING,
        match_id: uuid.UUID | None = None,
    ) -> dict:
        """Abandon leftover webapp games, then start fresh. Returns public view.

        `match_id` links the attempt to an active multiplayer match: the
        caller must be a participant and the game/difficulty must equal the
        match's, so a smuggled difficulty or foreign match can never mint a
        favorable session. Games whose multiplayer spec defines a shared
        target (Perfect Second) resolve it deterministically from the match
        instead of rolling a fresh one.
        """
        if game_type not in PLAYABLE_GAME_TYPES:
            raise ValueError(f"game_type must be one of {sorted(PLAYABLE_GAME_TYPES)}")
        if game_type == GAME_TYPE_COLOR_SEQUENCE:
            if difficulty not in colors.COLOR_DIFFICULTIES:
                raise ValueError(
                    f"difficulty must be one of {sorted(colors.COLOR_DIFFICULTIES)}"
                )
        elif game_type == GAME_TYPE_REFLEX_RUSH:
            if difficulty not in reflex.REFLEX_DIFFICULTIES:
                raise ValueError(
                    f"difficulty must be one of {sorted(reflex.REFLEX_DIFFICULTIES)}"
                )
        elif game_type == GAME_TYPE_PERFECT_SECOND:
            if difficulty not in perfect.PERFECT_DIFFICULTIES:
                raise ValueError(
                    f"difficulty must be one of {sorted(perfect.PERFECT_DIFFICULTIES)}"
                )
        else:
            _config_for(difficulty)  # fail fast, before any DB work
        async with self.session.begin():
            await self._expire_stale_locked(user_id=user_id)
            if await self.users.get_by_id(user_id) is None:
                raise NotFoundError("user not found")
            target_override: int | None = None
            if match_id is not None:
                target_override = await self._match_target_for(
                    user_id=user_id, match_id=match_id,
                    game_type=game_type, difficulty=difficulty,
                )
            for state, _ in await self.states.list_active_by_user(user_id=user_id):
                await self.sessions.abandon(session_id=state.session_id, ended_at=utcnow())
                await self.states.delete(state)
            db_row = await self.sessions.create(
                user_id=user_id, game_type=game_type
            )
            if game_type == GAME_TYPE_COLOR_SEQUENCE:
                return await self._start_color(
                    user_id=user_id, db_row=db_row, difficulty=difficulty
                )
            if game_type == GAME_TYPE_REFLEX_RUSH:
                return await self._start_reflex(
                    user_id=user_id, db_row=db_row, difficulty=difficulty
                )
            if game_type == GAME_TYPE_PERFECT_SECOND:
                return await self._start_perfect(
                    user_id=user_id, db_row=db_row, difficulty=difficulty,
                    target_ms=target_override,
                )
            config = _config_for(difficulty)
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

    async def _start_color(self, *, user_id, db_row, difficulty: str) -> dict:
        try:
            config = colors.COLOR_DIFFICULTIES[difficulty]
        except KeyError:
            raise ValueError(
                f"difficulty must be one of {sorted(colors.COLOR_DIFFICULTIES)}"
            ) from None
        # No single secret exists for a memory game; the column is NOT NULL
        # so it stores 0 (unused) while the real state lives in `guesses`.
        state = await self.states.create(
            user_id=user_id,
            session_id=db_row.id,
            game_type=GAME_TYPE_COLOR_SEQUENCE,
            difficulty=difficulty,
            secret=0,
            max_attempts=config.max_level,
        )
        data = _new_color_data(config)
        state.guesses = data
        await self.session.flush()
        return _color_public_view(state, data)

    async def _match_target_for(
        self, *, user_id, match_id, game_type: str, difficulty: str
    ) -> int | None:
        """Shared multiplayer target for this attempt, or None.

        Call inside an open transaction. The match must be active, the
        caller a participant, and the requested game/difficulty must equal
        the match's own — otherwise the session could smuggle a different
        target or difficulty into a match seat.
        """
        matches = MatchRepository(self.session)
        parts = MatchParticipantRepository(self.session)
        match = await matches.get_by_id(match_id)
        if match is None:
            raise NotFoundError("match not found")
        if match.status != "active":
            raise ConflictError("match has not started")
        if await parts.get(match_id=match.id, user_id=user_id) is None:
            raise NotFoundError("match not found")
        if match.game_type != game_type or match.difficulty != difficulty:
            raise ValueError("session must use the match's game and difficulty")
        return mp.spec_for(game_type).shared_target_ms(
            match_id=match.id, difficulty=match.difficulty
        )

    async def _start_perfect(
        self, *, user_id, db_row, difficulty: str, target_ms: int | None = None,
    ) -> dict:
        config = perfect.PERFECT_DIFFICULTIES[difficulty]
        target = target_ms if target_ms is not None else perfect.roll_target_ms(config)
        # The target lives in `secret` (NOT NULL int, exact ms). It is
        # public by design: the player must see it during the attempt.
        state = await self.states.create(
            user_id=user_id,
            session_id=db_row.id,
            game_type=GAME_TYPE_PERFECT_SECOND,
            difficulty=difficulty,
            secret=target,
            max_attempts=1,
        )
        return _perfect_public_view(state)

    async def stop_perfect(
        self,
        *,
        session_id: uuid.UUID,
        user_id: uuid.UUID,
        actual_ms,
        client_submission_id: str,
    ) -> dict:
        """Submit the single STOP time for a Perfect Second attempt.

        Error and XP are computed server-side from the stored target and
        the validated submission; client values are never trusted for XP.
        Replays (same or retried submission after completion) return the
        stored completed view without awarding XP twice: the state row is
        deleted in the same transaction as the result.
        """
        if (not isinstance(client_submission_id, str)
                or not client_submission_id.strip()):
            raise ValueError("client_submission_id must be a non-empty string")
        try:
            actual = perfect.parse_actual_ms(actual_ms)
        except ValueError as exc:
            raise ValueError(str(exc)) from None
        async with self.session.begin():
            state = await self.states.get_for_update(session_id=session_id)
            if state is None or state.user_id != user_id:
                return await self._replay_or_missing(session_id, user_id)
            if state.game_type != GAME_TYPE_PERFECT_SECOND:
                raise ValueError("this game uses its own stop endpoint")
            scored = perfect.score_result(target_ms=state.secret, actual_ms=actual)
            return await self._complete_perfect(state, scored)

    async def _complete_perfect(self, state, scored: dict):
        from brainrush.services import utcnow as _utcnow

        moment = _utcnow()
        won = bool(scored["won"])
        metadata = {
            "game": GAME_TYPE_PERFECT_SECOND,
            "difficulty": state.difficulty,
            "target_ms": state.secret,
            "actual_ms": scored["actual_ms"],
            "error_ms": scored["error_ms"],
            "error_percent": scored["error_percent"],
            "accuracy_percent": scored["accuracy_percent"],
        }
        session_row = await self.sessions.finish(
            session_id=state.session_id,
            status="completed",
            score=scored["score_ms"],
            ended_at=moment,
            duration_seconds=None,
        )
        result_row = await self.results.record(
            session_id=state.session_id,
            score=scored["score_ms"],
            outcome="win" if won else "loss",
            xp_earned=scored["xp"],
            metadata=metadata,
        )
        profile = await self.profiles.record_game(
            user_id=state.user_id,
            xp_earned=scored["xp"],
            won=won,
            new_level=None,
        )
        await self.profiles.set_level(
            user_id=state.user_id, level=level_for_xp(profile.total_xp)
        )
        await self.activities.add_play(
            user_id=state.user_id, day=moment.date(), xp_earned=scored["xp"]
        )
        await self.states.delete(state)
        return _completed_view(session_row, result_row, [])

    async def _start_reflex(self, *, user_id, db_row, difficulty: str) -> dict:
        try:
            config = reflex.REFLEX_DIFFICULTIES[difficulty]
        except KeyError:
            raise ValueError(
                f"difficulty must be one of {sorted(reflex.REFLEX_DIFFICULTIES)}"
            ) from None
        # Reaction timing is measured client-side; the server stores no
        # secret. `secret` is NOT NULL so it holds 0 (unused); per-round
        # times arrive once via finish_reflex and are validated there.
        state = await self.states.create(
            user_id=user_id,
            session_id=db_row.id,
            game_type=GAME_TYPE_REFLEX_RUSH,
            difficulty=difficulty,
            secret=0,
            max_attempts=config.rounds,
        )
        return _reflex_public_view(state)

    async def finish_reflex(
        self,
        *,
        session_id: uuid.UUID,
        user_id: uuid.UUID,
        rounds: list[dict],
        client_submission_id: str,
    ) -> dict:
        """Submit the final 5-round Reflex Rush result.

        Score and XP are computed server-side from the submitted times;
        client values are validated, never trusted for XP. Duplicate
        submissions (same or different id, e.g. retries) return the stored
        completed view without awarding XP twice: the state row is deleted
        in the same transaction as the result, so a replay hits
        _replay_or_missing.
        """
        if (not isinstance(client_submission_id, str)
                or not client_submission_id.strip()):
            raise ValueError("client_submission_id must be a non-empty string")
        async with self.session.begin():
            state = await self.states.get_for_update(session_id=session_id)
            if state is None or state.user_id != user_id:
                return await self._replay_or_missing(session_id, user_id)
            if state.game_type != GAME_TYPE_REFLEX_RUSH:
                raise ValueError("this game uses its own finish endpoint")
            try:
                config = reflex.REFLEX_DIFFICULTIES[state.difficulty]
            except KeyError:
                raise ValueError("stored difficulty is invalid") from None
            try:
                normalized = reflex.validate_rounds(rounds, config)
            except ValueError as exc:
                raise ValueError(str(exc)) from None
            return await self._complete_reflex(
                state, normalized, config=config
            )

    async def _complete_reflex(self, state, rounds, *, config):
        from brainrush.services import utcnow as _utcnow

        moment = _utcnow()
        agg = reflex.aggregate(rounds, config)
        metadata = {
            "game": GAME_TYPE_REFLEX_RUSH,
            "difficulty": state.difficulty,
            "rounds": list(rounds),
            "avg_ms": agg["avg_ms"],
            "best_ms": agg["best_ms"],
            "false_starts": agg["false_starts"],
            "valid_taps": agg["valid_taps"],
        }
        session_row = await self.sessions.finish(
            session_id=state.session_id,
            status="completed",
            score=agg["score"],
            ended_at=moment,
            duration_seconds=None,
        )
        result_row = await self.results.record(
            session_id=state.session_id,
            score=agg["score"],
            outcome="win" if agg["won"] else "loss",
            xp_earned=agg["xp"],
            metadata=metadata,
        )
        profile = await self.profiles.record_game(
            user_id=state.user_id,
            xp_earned=agg["xp"],
            won=bool(agg["won"]),
            new_level=None,
        )
        await self.profiles.set_level(
            user_id=state.user_id, level=level_for_xp(profile.total_xp)
        )
        await self.activities.add_play(
            user_id=state.user_id, day=moment.date(), xp_earned=agg["xp"]
        )
        await self.states.delete(state)
        return _completed_view(session_row, result_row, list(rounds))

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
            if state.game_type != GAME_TYPE_NUMBER_GUESSING:
                raise ValueError("this game uses the move/finish endpoint, not guesses")
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

    async def tap(
        self,
        *,
        session_id: uuid.UUID,
        user_id: uuid.UUID,
        color: int,
        client_move_id: str,
    ) -> dict:
        """Submit one Color Sequence tap. Idempotent per client_move_id.

        Correct taps advance within the level; completing a level appends a
        new color (generated server-side, so future colors never leak). A
        wrong tap ends the run immediately.
        """
        if not isinstance(client_move_id, str) or not client_move_id.strip():
            raise ValueError("client_move_id must be a non-empty string")
        try:
            color = colors.parse_tap(color)
        except colors.InvalidTapError as exc:
            raise ValueError(str(exc)) from None
        async with self.session.begin():
            state = await self.states.get_for_update(session_id=session_id)
            if state is None or state.user_id != user_id:
                return await self._replay_or_missing(session_id, user_id)
            if state.game_type != GAME_TYPE_COLOR_SEQUENCE:
                raise ValueError("this game uses the guess/finish endpoint, not moves")
            try:
                config = colors.COLOR_DIFFICULTIES[state.difficulty]
            except KeyError:
                raise ValueError("stored difficulty is invalid") from None
            data = dict(state.guesses or {})
            sequence = list(data.get("sequence", []))
            position = int(data.get("position", 0))
            level = int(data.get("level", config.start_length))
            completed = int(data.get("levels_completed", 0))
            log = list(data.get("log", []))
            if any(entry.get("id") == client_move_id for entry in log):
                return _color_public_view(state, data)
            hit = (
                0 <= position < len(sequence) and sequence[position] == color
            )
            entry = {"id": client_move_id, "value": color, "hit": bool(hit)}
            if not hit:
                return await self._complete_color(
                    state, data, entry, completed_levels=completed,
                    won=False, config=config,
                )
            position += 1
            if position < level:
                data.update({"position": position, "log": [*log, entry]})
                state.guesses = data
                await self.session.flush()
                return _color_public_view(state, data)
            # Level complete: score it, then grow or win.
            completed += 1
            if level >= config.max_level:
                return await self._complete_color(
                    state, data, entry, completed_levels=completed,
                    won=True, config=config,
                )
            sequence = [*sequence, colors.roll_color()]
            data.update({
                "sequence": sequence,
                "position": 0,
                "level": level + 1,
                "levels_completed": completed,
                "log": [*log, entry],
            })
            state.guesses = data
            await self.session.flush()
            return _color_public_view(state, data)

    async def _complete_color(
        self, state, data, entry, *, completed_levels: int, won: bool, config,
    ):
        from brainrush.services import utcnow as _utcnow

        moment = _utcnow()
        xp = colors.xp_for_color_result(
            levels_completed=completed_levels, won=won, config=config
        )
        log = [*data.get("log", []), entry]
        metadata = {
            "game": GAME_TYPE_COLOR_SEQUENCE,
            "difficulty": state.difficulty,
            "max_level": config.max_level,
            "start_length": config.start_length,
            "levels_completed": completed_levels,
            "guesses": log,
        }
        session_row = await self.sessions.finish(
            session_id=state.session_id,
            status="completed",
            score=completed_levels,
            ended_at=moment,
            duration_seconds=None,
        )
        result_row = await self.results.record(
            session_id=state.session_id,
            score=completed_levels,
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
        return _completed_view(session_row, result_row, log)

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
        if meta.get("game") == GAME_TYPE_COLOR_SEQUENCE:
            stored = [
                g for g in meta.get("guesses", [])
                if isinstance(g, dict) and "value" in g
            ]
        elif meta.get("game") == GAME_TYPE_REFLEX_RUSH:
            stored = [
                g for g in meta.get("rounds", [])
                if isinstance(g, dict)
            ]
        else:
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
                if state.game_type == GAME_TYPE_COLOR_SEQUENCE:
                    return _color_public_view(state, dict(state.guesses or {}))
                if state.game_type == GAME_TYPE_REFLEX_RUSH:
                    return _reflex_public_view(state)
                if state.game_type == GAME_TYPE_PERFECT_SECOND:
                    return _perfect_public_view(state)
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
            await self._expire_stale_locked(user_id=user_id)
            user = await self.users.get_by_id(user_id)
            if user is None:
                raise NotFoundError("user not found")
            profile = await self.profiles.get_by_user_id(user_id)
            if profile is None:
                raise NotFoundError("player profile not found")
            today = await self.activities.get(
                user_id=user_id, day=utc_today()
            )
            best = await self.results.best_win_score(
                user_id=user_id, game_type=GAME_TYPE_NUMBER_GUESSING
            )
            best_color = await self.results.best_score_for_game(
                user_id=user_id, game_type=GAME_TYPE_COLOR_SEQUENCE
            )
            best_reflex = await self.results.best_score_for_game(
                user_id=user_id, game_type=GAME_TYPE_REFLEX_RUSH
            )
            best_perfect = await self.results.best_win_score(
                user_id=user_id, game_type=GAME_TYPE_PERFECT_SECOND
            )
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
                "best_color_level": best_color,
                "best_reflex_score": best_reflex,
                "best_perfect_error_ms": best_perfect,
                "rank": rank,
                "active_games": [
                    _active_view(state) for state, _ in actives
                ],
            }

    async def history(
        self, *, user_id: uuid.UUID, limit: int = 20, offset: int = 0
    ) -> list[dict]:
        async with self.session.begin():
            await self._expire_stale_locked(user_id=user_id)
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
