"""Friend codes + symmetric friendships. One transaction per public method.

Friendships are immediate (no request/accept flow) and award NO XP: this
system is fully separate from referrals and never touches referral
attribution or the XP ledger beyond reading profiles for display.

Safety properties (all enforced here, never in the frontend):
  - Identity comes from the caller (verified Telegram identity's user_id);
    client-supplied user ids are never accepted.
  - Each unordered pair is stored once (canonical low/high order + unique
    pair constraint). Concurrent duplicate adds collapse to one row
    (IntegrityError → idempotent "already friends", no duplicate rows).
  - Self-friendship is rejected explicitly (and by a DB CHECK constraint).
  - Unknown codes surface as NotFoundError (HTTP 404), never as valid users.
  - Friend views expose only public display data (no Telegram ids).
"""
from __future__ import annotations

import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from brainrush.db.errors import ConflictError, NotFoundError
from brainrush.db.repository import (
    FriendRepository,
    PlayerProfileRepository,
    UserRepository,
)
from brainrush.game.progression import level_for_xp


class FriendService:
    """Friend codes, friendships, and friends lists. Owns one txn per call."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.users = UserRepository(session)
        self.profiles = PlayerProfileRepository(session)
        self.friends = FriendRepository(session)

    async def my_code(self, *, user_id: uuid.UUID) -> dict:
        async with self.session.begin():
            if await self.users.get_by_id(user_id) is None:
                raise NotFoundError("user not found")
            row, _ = await self.friends.get_or_create_code(user_id=user_id)
            return {"code": row.code}

    async def add_friend(self, *, user_id: uuid.UUID, code: str) -> dict:
        """Create the friendship immediately. Idempotent: an existing pair
        returns the friend view with added=False instead of erroring, so
        retries and double-taps never duplicate rows or award anything."""
        async with self.session.begin():
            code_row = await self.friends.get_by_code(code=code)
            if code_row is None:
                raise NotFoundError("Friend code not found. Please check the code.")
            me = await self.users.get_by_id(user_id)
            if me is None:
                raise NotFoundError("user not found")
            target = await self.users.get_by_id(code_row.user_id)
            if target is None:
                raise NotFoundError("Friend code not found. Please check the code.")
            if target.id == me.id:
                raise ConflictError("You cannot add yourself as a friend.")

            existing = await self.friends.get_pair(me.id, target.id)
            if existing is not None:
                return {
                    "added": False,
                    "already": True,
                    "friend": await self._public_view(target.id),
                }
            try:
                await self.friends.record_pair(me.id, target.id)
            except IntegrityError:
                # Lost a concurrent insert race: the row now exists, so the
                # retry-safe answer is the idempotent one (no double data).
                existing = await self.friends.get_pair(me.id, target.id)
                if existing is None:  # pragma: no cover - defensive
                    raise ConflictError("You are already friends.") from None
                return {
                    "added": False,
                    "already": True,
                    "friend": await self._public_view(target.id),
                }
            return {
                "added": True,
                "already": False,
                "friend": await self._public_view(target.id),
            }

    async def list_friends(self, *, user_id: uuid.UUID) -> list[dict]:
        async with self.session.begin():
            if await self.users.get_by_id(user_id) is None:
                raise NotFoundError("user not found")
            pairs = await self.friends.list_pairs(user_id=user_id)
            friend_ids = [
                p.user_high if p.user_low == user_id else p.user_low
                for p in pairs
            ]
            if not friend_ids:
                return []
            users = {u.id: u for u in await self.users.list_by_ids(friend_ids)}
            profiles = {
                p.user_id: p
                for p in await self.profiles.list_by_user_ids(friend_ids)
            }
            out = []
            for fid in friend_ids:
                user = users.get(fid)
                if user is None:  # pragma: no cover - defensive (FK CASCADE)
                    continue
                profile = profiles.get(fid)
                total_xp = profile.total_xp if profile is not None else 0
                out.append(
                    {
                        "display_name": user.display_name,
                        "username": user.username,
                        "level": level_for_xp(total_xp),
                        "total_xp": total_xp,
                    }
                )
            return out

    async def _public_view(self, friend_id: uuid.UUID) -> dict:
        user = await self.users.get_by_id(friend_id)
        if user is None:  # pragma: no cover - defensive
            raise NotFoundError("user not found")
        profile = await self.profiles.get_by_user_id(friend_id)
        total_xp = profile.total_xp if profile is not None else 0
        return {
            "display_name": user.display_name,
            "username": user.username,
            "level": level_for_xp(total_xp),
            "total_xp": total_xp,
        }
