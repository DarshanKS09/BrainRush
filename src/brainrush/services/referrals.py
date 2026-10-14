"""Referral attribution + rewards. One transaction per public method.

Flow: an existing player shares a stable personal code; a genuinely new
player opens the Mini App with that code and claims exactly once.

Safety properties (all enforced here, never in the frontend):
  - Rewards use configured amounts (REFERRER_XP / REFERRED_XP) only.
  - Only genuinely new identities are rewarded: the claim runs inside the
    SAME transaction that creates the user row, using get_or_create's
    `created` flag. A pre-existing user is never rewarded — not even if they
    open a referral link.
  - Self-referral is rejected explicitly.
  - `referral_attributions.referred_user_id` is UNIQUE, so concurrent or
    retried claims for the same newcomer collapse to a single credit
    (IntegrityError → ConflictError → HTTP 409, no double XP).
  - Repeat claims by an already-credited newcomer return the stored
    attribution as idempotent success instead of erroring.
  - Abandoned/cancelled games are unrelated: referrals never touch scores.

Race note: if identity verification succeeds but the claim request is
retried, the retry finds either no user row (first attempt never committed
→ treated as a fresh claim, still single-credit via the UNIQUE constraint)
or the credited attribution (returned as idempotent success).
"""
from __future__ import annotations

import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from brainrush.db.errors import ConflictError, NotFoundError
from brainrush.db.repository import (
    PlayerProfileRepository,
    ReferralRepository,
    UserRepository,
)


class ReferralService:
    """Referral codes, attribution, and stats. Owns one txn per call."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        referrer_xp: int,
        referred_xp: int,
    ) -> None:
        if referrer_xp < 0 or referred_xp < 0:
            raise ValueError("referral XP amounts must be >= 0")
        self.session = session
        self.referrer_xp = referrer_xp
        self.referred_xp = referred_xp
        self.users = UserRepository(session)
        self.profiles = PlayerProfileRepository(session)
        self.referrals = ReferralRepository(session)

    async def get_or_create_code(self, *, user_id: uuid.UUID) -> dict:
        async with self.session.begin():
            if await self.users.get_by_id(user_id) is None:
                raise NotFoundError("user not found")
            row, _ = await self.referrals.get_or_create_code(user_id=user_id)
            return {"code": row.code}

    async def build_link(
        self, *, user_id: uuid.UUID, bot_username: str, app_short_name: str
    ) -> dict:
        """Personal deep link, or link=None when the bot/app names are not
        configured (the code itself is still returned)."""
        data = await self.get_or_create_code(user_id=user_id)
        code = data["code"]
        link = None
        if bot_username.strip() and app_short_name.strip():
            link = (
                f"https://t.me/{bot_username.strip()}/{app_short_name.strip()}"
                f"?startapp={code}"
            )
        return {"code": code, "link": link}

    async def claim(
        self,
        *,
        code: str,
        telegram_id: int,
        username: str | None = None,
        display_name: str | None = None,
    ) -> dict:
        """Attribute a newcomer and credit both sides, atomically."""
        async with self.session.begin():
            code_row = await self.referrals.get_by_code(code=code)
            if code_row is None:
                raise NotFoundError("invalid referral code")
            referrer = await self.users.get_by_id(code_row.referrer_user_id)
            if referrer is None:
                raise NotFoundError("invalid referral code")

            user, created = await self.users.get_or_create(
                telegram_id=telegram_id,
                username=username,
                display_name=display_name,
            )
            if not created:
                prior = await self.referrals.get_attribution_for(
                    referred_user_id=user.id
                )
                if (
                    prior is not None
                    and prior.code == code_row.code
                    and prior.referrer_user_id == referrer.id
                ):
                    return self._credited_view(prior, already=True)
                raise ConflictError("referral already claimed or ineligible")
            if user.telegram_id == referrer.telegram_id:
                raise ConflictError("self-referral is not rewarded")

            await self.profiles.get_or_create(user_id=user.id)
            try:
                row = await self.referrals.record_attribution(
                    code=code_row.code,
                    referrer_user_id=referrer.id,
                    referred_user_id=user.id,
                    referrer_xp=self.referrer_xp,
                    referred_xp=self.referred_xp,
                )
            except IntegrityError:
                raise ConflictError("referral already claimed") from None
            await self.profiles.get_or_create(user_id=referrer.id)
            await self.profiles.add_xp(
                user_id=referrer.id, amount=self.referrer_xp
            )
            await self.profiles.add_xp(user_id=user.id, amount=self.referred_xp)
            return self._credited_view(row, already=False)

    async def stats(self, *, user_id: uuid.UUID) -> dict:
        async with self.session.begin():
            if await self.users.get_by_id(user_id) is None:
                raise NotFoundError("user not found")
            return {
                "referrals": await self.referrals.count_credited(
                    referrer_user_id=user_id
                ),
                "referral_xp": await self.referrals.sum_referrer_xp(
                    referrer_user_id=user_id
                ),
            }

    @staticmethod
    def _credited_view(row, *, already: bool) -> dict:
        return {
            "credited": True,
            "already": already,
            "code": row.code,
            "referrer_xp": row.referrer_xp,
            "referred_xp": row.referred_xp,
        }
