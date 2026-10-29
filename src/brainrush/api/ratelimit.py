"""Simple in-memory rate limiter (sliding window).

BrainRush runs a single backend instance (single Telegram poller rule), so a
process-local store is sufficient and avoids adding infrastructure. Keys are
scoped by a caller-supplied identifier (e.g. verified user id or client IP).
Windows expire on access; memory stays bounded because old entries are
overwritten lazily.
"""
from __future__ import annotations

import time
from collections import defaultdict


class RateLimiter:
    """Token-bucket style sliding window limiter.

    `limit` requests per `window_seconds`. Returns (allowed, remaining).
    """

    def __init__(self, limit: int, window_seconds: float) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        # key -> list of timestamps within the current window
        self._hits: dict[str, list[float]] = defaultdict(list)

    def check(self, key: str) -> tuple[bool, int]:
        now = time.monotonic()
        cutoff = now - self.window_seconds
        hits = self._hits[key]
        # Drop stale timestamps.
        while hits and hits[0] <= cutoff:
            hits.pop(0)
        remaining = max(0, self.limit - len(hits))
        if remaining <= 0:
            return False, 0
        hits.append(now)
        return True, remaining - 1


# Per-endpoint limiters (requests per minute unless noted).
# Authenticated endpoints are keyed by user_id; unauthenticated by client ip.
AUTH_LIMITER = RateLimiter(limit=60, window_seconds=60)      # general API
ROOM_LIMITER = RateLimiter(limit=30, window_seconds=60)      # match create/join
INVITE_LIMITER = RateLimiter(limit=20, window_seconds=60)    # invitations
EXPENSIVE_LIMITER = RateLimiter(limit=30, window_seconds=60) # leaderboard/history large pages

# Cleanup guard: bound memory by pruning keys that haven't been touched.
_MAX_KEYS = 50_000


def _maybe_prune() -> None:
    for limiter in (AUTH_LIMITER, ROOM_LIMITER, INVITE_LIMITER, EXPENSIVE_LIMITER):
        if len(limiter._hits) > _MAX_KEYS:
            now = time.monotonic()
            cutoff = now - limiter.window_seconds
            stale = [k for k, hits in limiter._hits.items()
                     if not hits or hits[-1] <= cutoff]
            for k in stale:
                del limiter._hits[k]
