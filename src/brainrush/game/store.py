"""In-memory registry of active games, keyed by internal user id.

One entry per user: a user's guesses can never touch another user's game.
Each entry carries the database session row id so completion/cancellation can
persist through GameSessionService (which owns its transactions).

Entries are ephemeral: a restart orphans the in-memory side while the DB row
stays `started`. `/play` abandons such stale rows before starting fresh, so no
schema change is needed for crash recovery.

Double-completion safety is layered:
  1. per-user asyncio lock serializes concurrent updates for the same player;
  2. finished entries are removed from the store before/while persisting;
  3. GameSessionRepository.finish() only transitions `started -> terminal`;
  4. `game_results.session_id` is UNIQUE, so even a cross-process race can
     never record two results or award XP twice (the loser gets IntegrityError
     and the service transaction rolls back).
"""
from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from typing import Any


@dataclass
class ActiveGame:
    user_id: uuid.UUID
    session_id: uuid.UUID
    game_type: str
    game: Any


class ActiveGameStore:
    def __init__(self) -> None:
        self._games: dict[uuid.UUID, ActiveGame] = {}
        self._locks: dict[uuid.UUID, asyncio.Lock] = {}

    def lock_for(self, user_id: uuid.UUID) -> asyncio.Lock:
        """Per-user lock. Single-threaded asyncio makes lazy creation safe."""
        lock = self._locks.get(user_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[user_id] = lock
        return lock

    def get(self, user_id: uuid.UUID) -> ActiveGame | None:
        return self._games.get(user_id)

    def put(self, game: ActiveGame) -> None:
        self._games[game.user_id] = game

    def remove(self, user_id: uuid.UUID) -> ActiveGame | None:
        return self._games.pop(user_id, None)

    def __len__(self) -> int:
        return len(self._games)
