"""Multiplayer integration contract: one shared engine, per-game rules.

Each game implements its OWN server-authoritative multiplayer behavior
through a small, frozen spec registered below. The match engine
(`services/matches.py`) handles invitations, lobby lifecycle, persistence,
ranking, and XP identically for every game; only scoring direction and
tie-breaking differ per game.

To add a game (Crash Predictor is the worked example in docs/MULTIPLAYER.md):
  1. Add a `MultiplayerSpec` entry to REGISTRY (modes, direction, duration).
  2. Store that game's validated per-player score via the existing solo
     finish flow; the match layer only links finished solo sessions.
  3. Nothing else: invites, lobby, sync, ranking, rewards, and history are
     inherited automatically.

Games with a shared round target (Perfect Second) additionally override
`shared_target_ms`: every seat resolves the same target deterministically
from the match id, and both the solo start (match-linked) and the match
submit validate against it.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import uuid

MODES = frozenset({"duel", "ffa", "tournament"})

# Minimum seats per mode. Maximums are per-match (host-chosen, capped).
MODE_MIN_PLAYERS: dict[str, int] = {"duel": 2, "ffa": 3, "tournament": 5}
MODE_DEFAULT_MAX: dict[str, int] = {"duel": 2, "ffa": 8, "tournament": 16}
ABSOLUTE_MAX_PLAYERS = 32


@dataclass(frozen=True)
class MultiplayerSpec:
    """Per-game multiplayer behavior. Pure data + pure functions only."""

    game_type: str
    modes: frozenset[str]
    higher_is_better: bool
    match_minutes: int
    difficulties: frozenset[str] = frozenset({"easy", "medium", "hard"})

    def tiebreak_key(self, *, metadata: dict, ended_at: datetime | None) -> tuple:
        """Smaller sorts earlier (better) AFTER the primary score direction
        is applied by rank_participants. Must be total and deterministic."""
        raise NotImplementedError

    def shared_target_ms(self, *, match_id: uuid.UUID, difficulty: str) -> int | None:
        """Shared round target for one match, or None.

        Games whose round must be identical for every seat (Perfect Second)
        override this with a deterministic derivation from the match id.
        Games with independent per-player content return None.
        """
        return None


@dataclass(frozen=True)
class _NumberGuessingSpec(MultiplayerSpec):
    def tiebreak_key(self, *, metadata: dict, ended_at: datetime | None) -> tuple:
        # Fewest attempts wins; earlier finish breaks ties. Private guesses
        # never enter the key (or any match view).
        ended = ended_at.isoformat() if ended_at is not None else ""
        return (ended,)


@dataclass(frozen=True)
class _ColorSequenceSpec(MultiplayerSpec):
    def tiebreak_key(self, *, metadata: dict, ended_at: datetime | None) -> tuple:
        # Most levels wins; earlier finish breaks ties.
        ended = ended_at.isoformat() if ended_at is not None else ""
        return (ended,)


@dataclass(frozen=True)
class _ReflexRushSpec(MultiplayerSpec):
    def tiebreak_key(self, *, metadata: dict, ended_at: datetime | None) -> tuple:
        # Most points wins; lower average reaction breaks ties, then time.
        avg = metadata.get("avg_ms")
        avg_key = avg if isinstance(avg, int) else 10**12
        ended = ended_at.isoformat() if ended_at is not None else ""
        return (avg_key, ended)


@dataclass(frozen=True)
class _PerfectSecondSpec(MultiplayerSpec):
    def tiebreak_key(self, *, metadata: dict, ended_at: datetime | None) -> tuple:
        # Smallest absolute error wins (primary score is the rounded error).
        # The exact measured error breaks rounded ties, then finish time.
        err = metadata.get("error_ms")
        err_key = err if isinstance(err, (int, float)) else 10**12
        ended = ended_at.isoformat() if ended_at is not None else ""
        return (err_key, ended)

    def shared_target_ms(self, *, match_id: uuid.UUID, difficulty: str) -> int | None:
        from brainrush.game import perfect_second as perfect

        return perfect.match_target_ms(match_id, difficulty)


@dataclass(frozen=True)
class _MazeRaceSpec(MultiplayerSpec):
    def tiebreak_key(self, *, metadata: dict, ended_at: datetime | None) -> tuple:
        # Completion time (ms) is the primary score; earlier finish breaks ties.
        # Wrong turns / backtracking are already reflected in elapsed time.
        ms = metadata.get("elapsed_ms")
        ms_key = ms if isinstance(ms, (int, float)) else 10**12
        ended = ended_at.isoformat() if ended_at is not None else ""
        return (ms_key, ended)


REGISTRY: dict[str, MultiplayerSpec] = {
    "number_guessing": _NumberGuessingSpec(
        game_type="number_guessing",
        modes=frozenset({"duel", "ffa", "tournament"}),
        higher_is_better=False,
        match_minutes=30,
    ),
    "color_sequence": _ColorSequenceSpec(
        game_type="color_sequence",
        modes=frozenset({"duel", "ffa", "tournament"}),
        higher_is_better=True,
        match_minutes=30,
    ),
    "reflex_rush": _ReflexRushSpec(
        game_type="reflex_rush",
        modes=frozenset({"duel", "ffa", "tournament"}),
        higher_is_better=True,
        match_minutes=45,
    ),
    "perfect_second": _PerfectSecondSpec(
        game_type="perfect_second",
        modes=frozenset({"duel", "ffa", "tournament"}),
        higher_is_better=False,
        match_minutes=30,
    ),
    "maze_race": _MazeRaceSpec(
        game_type="maze_race",
        modes=frozenset({"duel", "ffa", "tournament"}),
        higher_is_better=False,
        match_minutes=30,
    ),
}


def spec_for(game_type: str) -> MultiplayerSpec:
    """Fetch a game's spec or raise ValueError (HTTP 422) for unknown games."""
    try:
        return REGISTRY[game_type]
    except KeyError:
        raise ValueError(
            f"game_type must be one of {sorted(REGISTRY)}"
        ) from None


def rank_participants(
    entries: list[dict],
) -> list[dict]:
    """Dense rank finished entries by score (+adapter tiebreak).

    Each entry: {user_id, score, tiebreak: tuple}. Equal (score, tiebreak)
    shares one rank (never invent a winner); rank 1..N dense. Returns new
    dicts with a `rank` key, best first.
    """
    ordered = sorted(
        entries,
        key=lambda e: (
            -e["score"] if e["higher_is_better"] else e["score"],
            e["tiebreak"] if isinstance(e["tiebreak"], tuple) else (e["tiebreak"],),
            str(e["user_id"]),
        ),
    )
    out: list[dict] = []
    last_key: tuple | None = None
    rank = 0
    for e in ordered:
        key = (e["score"], e["tiebreak"] if isinstance(e["tiebreak"], tuple) else (e["tiebreak"],))
        if key != last_key:
            rank += 1
            last_key = key
        row = dict(e)
        row["rank"] = rank
        out.append(row)
    return out
