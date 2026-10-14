"""Multiplayer match engine: one shared flow for every game.

Each game plugs in through `game/multiplayer.py` (scoring direction +
tie-breaks); everything else here is game-agnostic: lobbies, invitations,
joins, synchronized starts, solo-session linking, finalization, ranking,
and exactly-once rewards. One transaction per public method.

Safety properties (all enforced here, never in the frontend):
  - Match membership gates every read and write (non-participants get 404,
    never a leak or a hint that the match exists).
  - Only the host invites/starts/cancels; anyone may join via a valid token,
    leave a lobby, trigger finalization, or rematch a completed game.
  - Solo sessions are validated on submit: owned by the caller, completed,
    same game, started after the match, and attached to no other match.
    A different session for the same seat is rejected (one attempt each);
    resubmitting the same session replays the current view.
  - Shared-target games (Perfect Second) additionally require the
    session's target to equal the match's deterministic target.
  - Scores/XP/outcomes come from persisted solo results, never the request.
  - Match XP flows only through the `match_rewards` ledger (ON CONFLICT DO
    NOTHING) plus `add_xp`, so retries and concurrent finalizations can
    never double-pay. Daily caps bound farming.
  - Match games never touch games_played/wins/losses/streaks/daily
    activity: those stay purely single-player. Match history lives on
    matches/participants, separate from solo history and the XP leaderboard.
  - Unfinished players at finalization rank after all finished players
    with 0 XP (explicit rule, documented in docs/MULTIPLAYER.md).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from brainrush.db.errors import ConflictError, NotFoundError
from brainrush.db.repository import (
    DailyActivityRepository,
    FriendRepository,
    GameResultRepository,
    GameSessionRepository,
    MatchInvitationRepository,
    MatchParticipantRepository,
    MatchRepository,
    MatchRewardRepository,
    PlayerProfileRepository,
    UserRepository,
)
from brainrush.game import multiplayer as mp
from brainrush.game.progression import level_for_xp
from brainrush.services import utcnow

# A polled client is "online" if seen within this window.
ONLINE_WINDOW = timedelta(seconds=90)


class MatchService:
    """Match lifecycle + rewards. Owns one transaction per public method."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        completion_xp: int,
        win_bonus: int,
        daily_cap: int,
        lobby_ttl_hours: int,
        invite_ttl_days: int,
        default_minutes: int,
    ) -> None:
        for name, value in (
            ("completion_xp", completion_xp),
            ("win_bonus", win_bonus),
            ("daily_cap", daily_cap),
        ):
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError(f"{name} must be an int >= 0")
        self.session = session
        self.completion_xp = completion_xp
        self.win_bonus = win_bonus
        self.daily_cap = daily_cap
        self.lobby_ttl = timedelta(hours=lobby_ttl_hours)
        self.invite_ttl = timedelta(days=invite_ttl_days)
        self.default_minutes = default_minutes
        self.users = UserRepository(session)
        self.profiles = PlayerProfileRepository(session)
        self.sessions = GameSessionRepository(session)
        self.results = GameResultRepository(session)
        self.activities = DailyActivityRepository(session)
        self.matches = MatchRepository(session)
        self.parts = MatchParticipantRepository(session)
        self.invites = MatchInvitationRepository(session)
        self.rewards = MatchRewardRepository(session)
        self.friends = FriendRepository(session)

    # -- helpers ---------------------------------------------------------

    def _lobby_ttl(self) -> timedelta:
        return self.lobby_ttl

    async def _people(
        self, parts, host_id: uuid.UUID, me_id: uuid.UUID | None = None
    ) -> tuple[list[dict], dict]:
        """Batch-resolve display data (no N+1): one users + one profiles query."""
        ids = list({p.user_id for p in parts})
        users = {u.id: u for u in await self.users.list_by_ids(ids)} if ids else {}
        profiles = (
            {p.user_id: p for p in await self.profiles.list_by_user_ids(ids)}
            if ids
            else {}
        )
        now = utcnow()
        out = []
        for p in parts:
            u = users.get(p.user_id)
            prof = profiles.get(p.user_id)
            total = prof.total_xp if prof is not None else 0
            seen = p.last_seen_at
            out.append(
                {
                    "user_id": str(p.user_id),
                    "display_name": (u.display_name if u else None)
                    or (u.username if u else None)
                    or "Player",
                    "username": u.username if u else None,
                    "level": level_for_xp(total),
                    "is_host": p.user_id == host_id,
                    "is_me": me_id is not None and p.user_id == me_id,
                    "finished": p.finished_at is not None,
                    "score": p.score if p.finished_at is not None else None,
                    "rank": p.rank,
                    "xp_earned": p.xp_earned,
                    "online": seen is not None
                    and (now - seen) <= ONLINE_WINDOW,
                    "joined_at": p.joined_at.isoformat() if p.joined_at else None,
                }
            )
        by_id = {p.user_id: p for p in parts}
        return out, by_id

    async def _view(self, match, *, me_id: uuid.UUID) -> dict:
        parts = await self.parts.list_by_match(match_id=match.id)
        people, _ = await self._people(parts, match.host_user_id, me_id)
        base = {            "match_id": str(match.id),
            "game_type": match.game_type,
            "mode": match.mode,
            "difficulty": match.difficulty,
            "status": match.status,
            "host_user_id": str(match.host_user_id),
            "count": len(parts),
            "min_players": match.min_players,
            "max_players": match.max_players,
            "room_code": match.room_code,
            "token_expires_at": match.token_expires_at.isoformat()
            if match.token_expires_at
            else None,
            "created_at": match.created_at.isoformat() if match.created_at else None,
            "started_at": match.started_at.isoformat() if match.started_at else None,
            "deadline": match.deadline.isoformat() if match.deadline else None,
            "finished_at": match.finished_at.isoformat() if match.finished_at else None,
            "participants": people,
        }
        # Shared round target (Perfect Second): public once the attempt
        # starts, so the lobby can show it. Independent-content games omit it.
        try:
            base["target_ms"] = mp.spec_for(match.game_type).shared_target_ms(
                match_id=match.id, difficulty=match.difficulty
            )
        except ValueError:
            base["target_ms"] = None
        return base

    async def _touch_seen(self, *, match_id: uuid.UUID, user_id: uuid.UUID) -> None:
        me = await self.parts.get(match_id=match_id, user_id=user_id)
        if me is not None:
            me.last_seen_at = utcnow()
            await self.session.flush()

    async def _maybe_expire_locked(self, match) -> None:
        """Lobby past TTL -> expired. Call inside an open transaction."""
        if (
            match.status == "lobby"
            and match.created_at is not None
            and utcnow() - match.created_at > self._lobby_ttl()
        ):
            match.status = "expired"
            await self.session.flush()

    async def _maybe_finalize_locked(self, match) -> dict | None:
        """Finalize when every seat finished or the deadline passed.

        Returns the completed view, or None when the match must stay active.
        """
        if match.status != "active":
            return None
        parts = await self.parts.list_by_match(match_id=match.id)
        all_done = parts and all(p.finished_at is not None for p in parts)
        past_deadline = (
            match.deadline is not None and utcnow() >= match.deadline
        )
        if not all_done and not past_deadline:
            return None
        return await self._finalize_locked(match, parts)

    async def _finalize_locked(self, match, parts) -> dict:
        spec = mp.spec_for(match.game_type)
        session_ids = [p.session_id for p in parts if p.session_id is not None]
        results = (
            await self.results.list_by_session_ids(session_ids=session_ids)
            if session_ids
            else {}
        )
        entries = []
        for p in parts:
            if p.finished_at is None:
                continue
            res = results.get(p.session_id) if p.session_id else None
            meta = dict(res.result_metadata or {}) if res else {}
            ended = res.created_at if res else None
            entries.append(
                {
                    "user_id": p.user_id,
                    "score": p.score,
                    "higher_is_better": spec.higher_is_better,
                    "tiebreak": spec.tiebreak_key(
                        metadata=meta,
                        ended_at=ended,
                    ),
                }
            )
        ranked = mp.rank_participants(entries)
        by_user = {e["user_id"]: e for e in ranked}
        # Unfinished seats all share the next rank (a did-not-finish tie).
        next_rank = (max((e["rank"] for e in ranked), default=0)) + 1
        for p in parts:
            if p.finished_at is None:
                by_user[p.user_id] = {"rank": next_rank}

        day_start = datetime.combine(
            utcnow().date(), datetime.min.time(), tzinfo=timezone.utc
        )
        used = await self.rewards.sum_since_many(
            user_ids=[p.user_id for p in parts], since=day_start
        )
        for p in parts:
            if p.finished_at is None:
                await self.parts.set_rank_xp(
                    match_id=match.id, user_id=p.user_id,
                    rank=by_user[p.user_id]["rank"], xp=0,
                )
                continue
            rank = by_user[p.user_id]["rank"]
            budget = max(0, self.daily_cap - used.get(p.user_id, 0))
            pay = min(self.completion_xp, budget)
            if await self.rewards.award_once(
                match_id=match.id, user_id=p.user_id, kind="participation", xp=pay
            ):
                if pay:
                    await self.profiles.add_xp(user_id=p.user_id, amount=pay)
            bonus = 0
            if rank == 1:
                bonus = min(self.win_bonus, max(0, budget - pay))
                if await self.rewards.award_once(
                    match_id=match.id, user_id=p.user_id, kind="win", xp=bonus
                ):
                    if bonus:
                        await self.profiles.add_xp(user_id=p.user_id, amount=bonus)
            if pay or bonus:
                fresh = await self.profiles.get_by_user_id(p.user_id)
                if fresh is not None:
                    await self.profiles.set_level(
                        user_id=p.user_id, level=level_for_xp(fresh.total_xp)
                    )
            await self.parts.set_rank_xp(
                match_id=match.id, user_id=p.user_id,
                rank=rank, xp=pay + bonus,
            )
        match.status = "completed"
        match.finished_at = utcnow()
        await self.session.flush()
        fresh = await self.matches.get_by_id(match.id)
        return await self._completed_view(fresh or match)

    async def _completed_view(self, match) -> dict:
        parts = await self.parts.list_by_match(match_id=match.id)
        people, _ = await self._people(parts, match.host_user_id, None)
        people.sort(key=lambda p: (p["rank"] is None, p["rank"] or 0))
        return {
            "match_id": str(match.id),
            "game_type": match.game_type,
            "mode": match.mode,
            "difficulty": match.difficulty,
            "status": match.status,
            "finished_at": match.finished_at.isoformat() if match.finished_at else None,
            "participants": people,
            "count": len(people),
        }

    # -- lifecycle -------------------------------------------------------

    async def create_match(
        self,
        *,
        host_user_id: uuid.UUID,
        game_type: str,
        mode: str,
        difficulty: str = "hard",
        max_players: int | None = None,
    ) -> dict:
        spec = mp.spec_for(game_type)
        if mode not in mp.MODES or mode not in spec.modes:
            raise ValueError(
                f"mode must be one of {sorted(spec.modes)} for {game_type}"
            )
        if difficulty not in ("easy", "medium", "hard"):
            raise ValueError("difficulty must be easy, medium or hard")
        lo, default_hi = mp.MODE_MIN_PLAYERS[mode], mp.MODE_DEFAULT_MAX[mode]
        hi = default_hi if max_players is None else max_players
        if not isinstance(hi, int) or isinstance(hi, bool):
            raise ValueError("max_players must be an int")
        if mode == "duel" and hi != 2:
            raise ValueError("duel matches hold exactly 2 players")
        if not lo <= hi <= mp.ABSOLUTE_MAX_PLAYERS:
            raise ValueError(
                f"max_players must be {lo}..{mp.ABSOLUTE_MAX_PLAYERS} for {mode}"
            )
        async with self.session.begin():
            if await self.users.get_by_id(host_user_id) is None:
                raise NotFoundError("user not found")
            now = utcnow()
            match = await self.matches.create(
                game_type=game_type,
                mode=mode,
                host_user_id=host_user_id,
                max_players=hi,
                min_players=lo,
                difficulty=difficulty,
                token_expires_at=now + self.invite_ttl,
            )
            await self.parts.add(match_id=match.id, user_id=host_user_id)
            return await self._view(match, me_id=host_user_id)

    async def get_match(self, *, user_id: uuid.UUID, match_id: uuid.UUID) -> dict:
        async with self.session.begin():
            match = await self.matches.get_by_id(match_id)
            if match is None:
                raise NotFoundError("match not found")
            me = await self.parts.get(match_id=match.id, user_id=user_id)
            if me is None:
                raise NotFoundError("match not found")
            await self._maybe_expire_locked(match)
            if match.status == "active":
                done = await self._maybe_finalize_locked(match)
                if done is not None:
                    return done
            await self._touch_seen(match_id=match.id, user_id=user_id)
            if match.status == "completed":
                return await self._completed_view(match)
            return await self._view(match, me_id=user_id)

    async def join_match(self, *, user_id: uuid.UUID, match_id: uuid.UUID) -> dict:
        async with self.session.begin():
            match = await self.matches.get_for_update(match_id)
            if match is None:
                raise NotFoundError("match not found")
            await self._maybe_expire_locked(match)
            if match.status not in ("lobby", "active"):
                raise ConflictError("match is already finished")
            if await self.users.get_by_id(user_id) is None:
                raise NotFoundError("user not found")
            existing = await self.parts.get(match_id=match.id, user_id=user_id)
            if existing is not None:
                await self.invites.set_status(
                    match_id=match.id, invited_user_id=user_id, status="accepted"
                )
                return await self._view(match, me_id=user_id)
            if await self.parts.count_by_match(match_id=match.id) >= match.max_players:
                raise ConflictError("match is full")
            try:
                await self.parts.add(match_id=match.id, user_id=user_id)
            except IntegrityError:
                raise ConflictError("already in match — refresh") from None
            await self.invites.set_status(
                match_id=match.id, invited_user_id=user_id, status="accepted"
            )
            return await self._view(match, me_id=user_id)

    async def join_by_token(self, *, user_id: uuid.UUID, token: str) -> dict:
        if not isinstance(token, str) or not token.startswith("m-"):
            raise NotFoundError("invite not found")
        async with self.session.begin():
            match = await self.matches.get_by_token(token=token)
            if match is None:
                raise NotFoundError("invite not found")
            if (
                match.token_expires_at is not None
                and utcnow() >= match.token_expires_at
            ):
                raise NotFoundError("invite expired")
            # Reuse the seat logic with the row locked.
            locked = await self.matches.get_for_update(match.id)
            if locked is None:  # pragma: no cover - defensive
                raise NotFoundError("invite not found")
            await self._maybe_expire_locked(locked)
            if locked.status not in ("lobby", "active"):
                raise ConflictError("match is already finished")
            if await self.users.get_by_id(user_id) is None:
                raise NotFoundError("user not found")
            existing = await self.parts.get(match_id=locked.id, user_id=user_id)
            if existing is not None:
                return await self._view(locked, me_id=user_id)
            if (
                await self.parts.count_by_match(match_id=locked.id)
                >= locked.max_players
            ):
                raise ConflictError("match is full")
            try:
                await self.parts.add(match_id=locked.id, user_id=user_id)
            except IntegrityError:
                raise ConflictError("already in match — refresh") from None
            await self.invites.set_status(
                match_id=locked.id, invited_user_id=user_id, status="accepted"
            )
            return await self._view(locked, me_id=user_id)

    async def join_by_code(self, *, user_id: uuid.UUID, room_code: str) -> dict:
        """Join via the human-readable room code (manual entry).

        Same seat guarantees as share-link joins (idempotent, capacity and
        lifecycle enforced, row-locked). Room codes never expire on their own;
        lobby TTL and match status still apply. The code is not an
        authorization secret: membership is derived from the verified identity.
        """
        async with self.session.begin():
            match = await self.matches.get_by_room_code(room_code=room_code)
            if match is None:
                raise NotFoundError("Room not found. Please check the code.")
            locked = await self.matches.get_for_update(match.id)
            if locked is None:  # pragma: no cover - defensive
                raise NotFoundError("Room not found. Please check the code.")
            await self._maybe_expire_locked(locked)
            if locked.status == "expired":
                raise ConflictError("This room has expired.")
            if locked.status in ("completed", "cancelled"):
                raise ConflictError("This match is already finished.")
            if locked.status not in ("lobby", "active"):
                raise ConflictError("This match is already finished.")
            if await self.users.get_by_id(user_id) is None:
                raise NotFoundError("user not found")
            existing = await self.parts.get(match_id=locked.id, user_id=user_id)
            if existing is not None:
                return await self._view(locked, me_id=user_id)
            if (
                await self.parts.count_by_match(match_id=locked.id)
                >= locked.max_players
            ):
                raise ConflictError("Room is full.")
            try:
                await self.parts.add(match_id=locked.id, user_id=user_id)
            except IntegrityError:
                raise ConflictError("already in match — refresh") from None
            await self.invites.set_status(
                match_id=locked.id, invited_user_id=user_id, status="accepted"
            )
            return await self._view(locked, me_id=user_id)

    async def invite_friend(
        self, *, host_user_id: uuid.UUID, match_id: uuid.UUID, friend_user_id: uuid.UUID
    ) -> dict:
        async with self.session.begin():
            match = await self.matches.get_by_id(match_id)
            if match is None:
                raise NotFoundError("match not found")
            await self._maybe_expire_locked(match)
            if match.status != "lobby":
                raise ConflictError("invites are lobby-only")
            if match.host_user_id != host_user_id:
                raise ConflictError("only the host can invite")
            friend = await self.users.get_by_id(friend_user_id)
            if friend is None:
                raise NotFoundError("user not found")
            if friend_user_id == host_user_id:
                raise ConflictError("you cannot invite yourself")
            if await self.friends.get_pair(host_user_id, friend_user_id) is None:
                raise ConflictError("you are not friends")
            if await self.parts.count_by_match(match_id=match.id) >= match.max_players:
                raise ConflictError("match is full")
            row, created = await self.invites.invite(
                match_id=match.id,
                invited_user_id=friend_user_id,
                invited_by_user_id=host_user_id,
            )
            return {
                "match_id": str(match.id),
                "invited": created,
                "already": not created,
                "status": row.status,
            }

    async def start_match(self, *, host_user_id: uuid.UUID, match_id: uuid.UUID) -> dict:
        async with self.session.begin():
            match = await self.matches.get_for_update(match_id)
            if match is None:
                raise NotFoundError("match not found")
            await self._maybe_expire_locked(match)
            if match.status != "lobby":
                raise ConflictError(f"match is already {match.status}")
            if match.host_user_id != host_user_id:
                raise ConflictError("only the host can start the match")
            count = await self.parts.count_by_match(match_id=match.id)
            spec = mp.spec_for(match.game_type)
            need = mp.MODE_MIN_PLAYERS[match.mode]
            if match.mode == "duel" and count != 2:
                raise ConflictError("duel needs exactly 2 players to start")
            if count < need:
                raise ConflictError(f"need at least {need} players to start")
            started = utcnow()
            minutes = spec.match_minutes or self.default_minutes
            moved = await self.matches.start_match(
                match_id=match.id,
                started_at=started,
                deadline=started + timedelta(minutes=minutes),
            )
            if moved is None:  # pragma: no cover - raced start
                raise ConflictError("match already started")
            return await self._view(moved, me_id=host_user_id)

    async def submit_result(
        self, *, user_id: uuid.UUID, match_id: uuid.UUID, session_id: uuid.UUID
    ) -> dict:
        """Attach one finished solo session to the caller's seat.

        Exactly one session per seat: resubmitting the same session replays
        the current view; a different session is rejected.
        """
        async with self.session.begin():
            match = await self.matches.get_by_id(match_id)
            if match is None:
                raise NotFoundError("match not found")
            me = await self.parts.get(match_id=match.id, user_id=user_id)
            if me is None:
                raise NotFoundError("match not found")
            if match.status == "completed":
                return await self._completed_view(match)
            if match.status != "active":
                raise ConflictError("match has not started")
            if me.session_id is not None:
                if me.session_id == session_id:
                    return await self._view(match, me_id=user_id)
                raise ConflictError("result already submitted for this match")
            solo = await self.sessions.get_by_id(session_id)
            if solo is None or solo.user_id != user_id:
                raise NotFoundError("game session not found")
            if solo.game_type != match.game_type:
                raise ConflictError("session is for a different game")
            if solo.status != "completed":
                raise ConflictError("finish your game first")
            if solo.started_at is not None and match.started_at is not None:
                if solo.started_at < match.started_at:
                    raise ConflictError("session predates the match")
            taken = await self.parts.get_by_session(session_id=session_id)
            if taken is not None:
                raise ConflictError("session already submitted to a match")
            res = await self.results.get_by_session(session_id)
            if res is None:  # pragma: no cover - defensive (finish records)
                raise NotFoundError("game result not found")
            expected_target = mp.spec_for(match.game_type).shared_target_ms(
                match_id=match.id, difficulty=match.difficulty
            )
            if expected_target is not None:
                # Shared-target games: the seat only counts when the player
                # stopped against the match's own target (match-linked solo
                # starts resolve it server-side; foreign solo sessions with
                # a different random target are rejected here).
                meta = dict(res.result_metadata or {})
                if meta.get("target_ms") != expected_target:
                    raise ConflictError(
                        "session target does not match the match target"
                    )
            stats = _stats_snapshot(match.game_type, res)
            await self.parts.attach_result(
                match_id=match.id,
                user_id=user_id,
                session_id=session_id,
                score=solo.score,
                stats=stats,
            )
            parts = await self.parts.list_by_match(match_id=match.id)
            if all(p.finished_at is not None for p in parts):
                return await self._finalize_locked(match, parts)
            return await self._view(match, me_id=user_id)

    async def finalize_match(self, *, user_id: uuid.UUID, match_id: uuid.UUID) -> dict:
        """Settle a stalled match: any participant may trigger finalization
        once everyone finished or the deadline passed."""
        async with self.session.begin():
            match = await self.matches.get_for_update(match_id)
            if match is None:
                raise NotFoundError("match not found")
            if await self.parts.get(match_id=match.id, user_id=user_id) is None:
                raise NotFoundError("match not found")
            if match.status == "completed":
                return await self._completed_view(match)
            done = await self._maybe_finalize_locked(match)
            if done is None:
                raise ConflictError("match not ready to finalize")
            return done

    async def cancel_match(self, *, host_user_id: uuid.UUID, match_id: uuid.UUID) -> dict:
        async with self.session.begin():
            match = await self.matches.get_for_update(match_id)
            if match is None:
                raise NotFoundError("match not found")
            if match.status != "lobby":
                raise ConflictError("only lobbies can be cancelled")
            if match.host_user_id != host_user_id:
                raise ConflictError("only the host can cancel the match")
            match.status = "cancelled"
            await self.session.flush()
            return {"match_id": str(match.id), "status": "cancelled"}

    async def leave_match(self, *, user_id: uuid.UUID, match_id: uuid.UUID) -> dict:
        """Leave a lobby seat. Active matches can't be left formally: an
        unfinished player simply counts as abandoned at finalization."""
        async with self.session.begin():
            match = await self.matches.get_for_update(match_id)
            if match is None:
                raise NotFoundError("match not found")
            me = await self.parts.get(match_id=match.id, user_id=user_id)
            if me is None:
                raise NotFoundError("match not found")
            if match.status != "lobby":
                raise ConflictError("match already started")
            await self.parts.remove(match_id=match.id, user_id=user_id)
            remaining = await self.parts.list_by_match(match_id=match.id)
            if not remaining:
                match.status = "cancelled"
                await self.session.flush()
                return {"match_id": str(match.id), "status": "cancelled"}
            if match.host_user_id == user_id:
                await self.matches.set_host(
                    match_id=match.id, host_user_id=remaining[0].user_id
                )
            return {"match_id": str(match.id), "status": "lobby"}

    async def rematch(self, *, user_id: uuid.UUID, match_id: uuid.UUID) -> dict:
        """Fresh match, same settings. Prior participants are auto-invited;
        nobody is auto-joined, so no one reopens anything by accident."""
        async with self.session.begin():
            match = await self.matches.get_by_id(match_id)
            if match is None:
                raise NotFoundError("match not found")
            if await self.parts.get(match_id=match.id, user_id=user_id) is None:
                raise NotFoundError("match not found")
            if match.status != "completed":
                raise ConflictError("only completed matches can rematch")
            others = [
                p.user_id
                for p in await self.parts.list_by_match(match_id=match.id)
                if p.user_id != user_id
            ]
            now = utcnow()
            fresh = await self.matches.create(
                game_type=match.game_type,
                mode=match.mode,
                host_user_id=user_id,
                max_players=match.max_players,
                min_players=match.min_players,
                difficulty=match.difficulty,
                token_expires_at=now + self.invite_ttl,
            )
            await self.parts.add(match_id=fresh.id, user_id=user_id)
            for other in others:
                await self.invites.invite(
                    match_id=fresh.id,
                    invited_user_id=other,
                    invited_by_user_id=user_id,
                )
            return await self._view(fresh, me_id=user_id)

    async def my_matches(
        self, *, user_id: uuid.UUID, limit: int = 20, offset: int = 0
    ) -> list[dict]:
        async with self.session.begin():
            await self._expire_lobbies_locked(user_id=user_id)
            out = []
            for match in await self.matches.list_by_user(
                user_id=user_id, limit=limit, offset=offset
            ):
                mine = await self.parts.get(match_id=match.id, user_id=user_id)
                count = await self.parts.count_by_match(match_id=match.id)
                out.append(
                    {
                        "match_id": str(match.id),
                        "game_type": match.game_type,
                        "mode": match.mode,
                        "difficulty": match.difficulty,
                        "status": match.status,
                        "my_rank": mine.rank if mine else None,
                        "participants": count,
                        "max_players": match.max_players,
                        "finished_at": match.finished_at.isoformat()
                        if match.finished_at
                        else None,
                        "created_at": match.created_at.isoformat()
                        if match.created_at
                        else None,
                    }
                )
            return out

    async def my_invites(self, *, user_id: uuid.UUID) -> list[dict]:
        async with self.session.begin():
            out = []
            for inv, match in await self.invites.list_pending_with_matches(
                user_id=user_id
            ):
                if match.status != "lobby":
                    continue
                if (
                    match.token_expires_at is not None
                    and utcnow() >= match.token_expires_at
                ):
                    continue
                host = await self.users.get_by_id(match.host_user_id)
                count = await self.parts.count_by_match(match_id=match.id)
                out.append(
                    {
                        "match_id": str(match.id),
                        "game_type": match.game_type,
                        "mode": match.mode,
                        "difficulty": match.difficulty,
                        "host_display_name": (
                            host.display_name or host.username or "Player"
                        )
                        if host
                        else "Player",
                        "participants": count,
                        "max_players": match.max_players,
                        "invited_at": inv.created_at.isoformat()
                        if inv.created_at
                        else None,
                    }
                )
            return out

    async def build_match_link(
        self, *, match_id: uuid.UUID, user_id: uuid.UUID,
        bot_username: str, app_short_name: str,
    ) -> dict:
        """Shareable lobby link, or link=None when bot names are unconfigured.
        Same URL scheme as referrals; match tokens carry an `m-` prefix."""
        async with self.session.begin():
            match = await self.matches.get_by_id(match_id)
            if match is None:
                raise NotFoundError("match not found")
            if await self.parts.get(match_id=match.id, user_id=user_id) is None:
                raise NotFoundError("match not found")
            bot = bot_username.strip()
            app = app_short_name.strip()
            link = None
            if bot and app:
                link = f"https://t.me/{bot}/{app}?startapp={match.invite_token}"
            elif bot:
                link = f"https://t.me/{bot}?startapp={match.invite_token}"
            return {"token": match.invite_token, "link": link}

    async def _expire_lobbies_locked(self, *, user_id: uuid.UUID) -> int:
        """Expire this user's stale lobbies. My-matches must never show a
        joinable lobby that can no longer start."""
        cutoff = utcnow() - self.lobby_ttl
        return await self.matches.expire_old_lobbies(
            user_id=user_id, before=cutoff
        )


def _stats_snapshot(game_type: str, res) -> dict:
    """Small per-game performance summary for result screens."""
    meta = dict(res.result_metadata or {})
    if game_type == "reflex_rush":
        return {
            "avg_ms": meta.get("avg_ms"),
            "best_ms": meta.get("best_ms"),
            "false_starts": meta.get("false_starts", 0),
        }
    if game_type == "color_sequence":
        return {"levels": res.score}
    if game_type == "perfect_second":
        return {
            "error_ms": meta.get("error_ms"),
            "accuracy_percent": meta.get("accuracy_percent"),
        }
    return {"attempts": res.score}
