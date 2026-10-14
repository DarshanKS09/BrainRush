"""Reflex Rush: pure game rules (no Telegram, no database).

Gameplay: 5 rounds. Each round the client waits a random interval
(wait_min_ms..wait_max_ms, chosen client-side from the catalog range),
shows an active signal, then measures reaction time with a monotonic
high-resolution clock (performance.now). A tap before the signal is a
false start.

FALSE-START RULE (documented, enforced in scoring):
  A false-started round scores 0 points and 0 XP but still consumes one
  of the 5 rounds. It never contributes to the average/best times.

SCORING (applied only on completion; abandoned games award nothing):
  round points = max(0, max_counted_ms - reaction_ms), 0 on false start.
  total score  = sum of round points (higher is better, persisted as
  GameSession.score).
  round XP tiers: <= perfect_ms -> xp_perfect, <= good_ms -> xp_good,
  <= max_counted_ms -> xp_slow, slower valid tap -> 1 XP (participation).
  total XP = sum of round XP + win_bonus when the run wins.
  win = at least 4 valid taps, at most 1 false start, and the average of
  valid taps <= win_avg_ms. Everything else that completes is a loss
  (still earns its round XP, no bonus).

FAIRNESS NOTE: browser timing is measured client-side and is not
cryptographically verified. The server validates round counts, difficulty,
timing ranges, and result structure, computes score/XP itself from the
submitted times, and protects against duplicate submissions via the
single-terminal-transition + replay path in MiniappGameService. Do not
treat submitted times as tamper-proof.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any

ROUNDS = 5
MIN_REACTION_MS = 1
MAX_REACTION_MS = 10_000


@dataclass(frozen=True)
class ReflexConfig:
    rounds: int = ROUNDS
    wait_min_ms: int = 1000
    wait_max_ms: int = 3000
    perfect_ms: int = 180
    good_ms: int = 450
    max_counted_ms: int = 1200
    xp_perfect: int = 15
    xp_good: int = 10
    xp_slow: int = 4
    win_bonus: int = 25
    win_avg_ms: int = 550


REFLEX_DIFFICULTIES: dict[str, ReflexConfig] = {
    # DB check constraint allows only easy/medium/hard ids; the frontend
    # labels medium as "Normal". Timing contract per mode:
    # easy = one fixed wait every round (predictable), medium = uniform
    # wait inside a defined range, hard = uniform wait inside a WIDER range.
    "easy": ReflexConfig(
        wait_min_ms=2000, wait_max_ms=2000,
        perfect_ms=200, good_ms=500, max_counted_ms=1200,
        xp_perfect=12, xp_good=8, xp_slow=3,
        win_bonus=15, win_avg_ms=650,
    ),
    "medium": ReflexConfig(),
    "hard": ReflexConfig(
        wait_min_ms=500, wait_max_ms=3500,
        perfect_ms=150, good_ms=400, max_counted_ms=1000,
        xp_perfect=20, xp_good=12, xp_slow=5,
        win_bonus=40, win_avg_ms=500,
    ),
}


def random_wait_ms(config: ReflexConfig = ReflexConfig(), rng=None) -> int:
    """Random pre-signal wait. `rng` injectable for deterministic tests."""
    source = rng if rng is not None else random
    return source.randint(config.wait_min_ms, config.wait_max_ms)


def parse_reaction_ms(value: Any) -> int:
    """Validate one measured reaction time in ms. Raises ValueError."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("reaction_ms must be an int in "
                         f"{MIN_REACTION_MS}..{MAX_REACTION_MS}")
    if not MIN_REACTION_MS <= value <= MAX_REACTION_MS:
        raise ValueError("reaction_ms must be an int in "
                         f"{MIN_REACTION_MS}..{MAX_REACTION_MS}")
    return value


def validate_rounds(rounds: Any, config: ReflexConfig) -> list[dict]:
    """Validate the 5-round submission shape. Returns normalized rounds."""
    if not isinstance(rounds, list) or len(rounds) != config.rounds:
        raise ValueError(f"rounds must be a list of exactly {config.rounds}")
    normalized: list[dict] = []
    for entry in rounds:
        if not isinstance(entry, dict):
            raise ValueError("each round must be {reaction_ms, false_start}")
        false_start = entry.get("false_start", False)
        if not isinstance(false_start, bool):
            raise ValueError("false_start must be a boolean")
        reaction_ms = entry.get("reaction_ms")
        if false_start:
            if reaction_ms is not None:
                raise ValueError("false-start rounds must have reaction_ms null")
            normalized.append({"reaction_ms": None, "false_start": True})
        else:
            normalized.append({
                "reaction_ms": parse_reaction_ms(reaction_ms),
                "false_start": False,
            })
    return normalized


def round_points(*, reaction_ms: int | None, false_start: bool,
                 config: ReflexConfig = ReflexConfig()) -> int:
    """Points for one round (higher is better). False start = 0."""
    if false_start:
        return 0
    assert reaction_ms is not None
    return max(0, config.max_counted_ms - reaction_ms)


def round_xp(*, reaction_ms: int | None, false_start: bool,
             config: ReflexConfig = ReflexConfig()) -> int:
    """XP for one round. False start = 0."""
    if false_start:
        return 0
    assert reaction_ms is not None
    if reaction_ms <= config.perfect_ms:
        return config.xp_perfect
    if reaction_ms <= config.good_ms:
        return config.xp_good
    if reaction_ms <= config.max_counted_ms:
        return config.xp_slow
    return 1


def aggregate(rounds: list[dict],
              config: ReflexConfig = ReflexConfig()) -> dict:
    """Score a validated 5-round run. Returns avg/best/score/xp/won."""
    valid = [r["reaction_ms"] for r in rounds
             if not r["false_start"] and r["reaction_ms"] is not None]
    false_starts = sum(1 for r in rounds if r["false_start"])
    best_ms = min(valid) if valid else None
    avg_ms = round(sum(valid) / len(valid)) if valid else None
    total_score = sum(
        round_points(reaction_ms=r["reaction_ms"],
                     false_start=r["false_start"], config=config)
        for r in rounds
    )
    total_xp = sum(
        round_xp(reaction_ms=r["reaction_ms"],
                 false_start=r["false_start"], config=config)
        for r in rounds
    )
    won = (
        len(valid) >= config.rounds - 1
        and false_starts <= 1
        and avg_ms is not None
        and avg_ms <= config.win_avg_ms
    )
    if won:
        total_xp += config.win_bonus
    return {
        "rounds": config.rounds,
        "valid_taps": len(valid),
        "false_starts": false_starts,
        "avg_ms": avg_ms,
        "best_ms": best_ms,
        "score": total_score,
        "xp": total_xp,
        "won": won,
    }
