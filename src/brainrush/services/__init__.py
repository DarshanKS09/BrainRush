"""Service layer: business orchestration with transaction ownership.

Transaction policy: services open exactly one transaction per public method
(`async with session.begin():`); repositories never commit/rollback/begin.
This includes read-only methods: even a SELECT autobegins a transaction on
AsyncSession, so repository calls must never run outside a service-owned
`begin()` block, or the next `begin()` on that session will raise
"transaction already begun".

Date/time policy: every timestamp is stored in UTC. Daily activity buckets use
the UTC calendar date (`utc_today()`), so streaks and leaderboards are stable
regardless of the player's local timezone. Callers may pass an explicit
timezone-aware `played_at`; naive datetimes are rejected.
"""
from __future__ import annotations

from datetime import date, datetime, timezone


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def utc_today() -> date:
    return utcnow().date()


def require_aware_moment(value: datetime | None, *, field: str) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError(f"{field} must be a timezone-aware datetime or None")
    return value.astimezone(timezone.utc)
