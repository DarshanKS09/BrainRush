"""Perfect Second: pure game rules (no Telegram, no database).

Gameplay: the server holds a target duration; the player starts a clock and
taps STOP when they believe the elapsed time matches the target. The target
is public (shown during the attempt); only the player's timing skill matters.

Difficulties (all ranges configurable below, never zero/negative):
  easy   - whole-second targets, e.g. 5, 7, 10, 12 s.
  medium - half-second targets, e.g. 4.5, 5.5, 7.5 s (never hundredths).
  hard   - hundredth-second targets, e.g. 5.34, 6.76 s.

XP RULE (applied only when an attempt completes; abandoned games award
nothing). Maximum 100 base XP for a perfect stop, reduced proportionally:
  error_ms       = abs(actual_ms - target_ms)          (full precision)
  error_percent  = error_ms / target_ms * 100
  accuracy       = max(0, 100 - error_percent)
  earnedXP       = clamp(roundHalfUp(accuracy / 10) * 10, 0, 100)
Exact match -> 100; 10% error -> 90; 30% -> 70; 50% -> 50; >=100% -> 0.
Rounding uses exact integer math (hundredths of accuracy points), so binary
float representation can never flip a halfway case.

WIN RULE: error within 10% of the target (accuracy >= 90). Wins feed the
existing wins/losses/streak counters via the standard finish flow.
Score persisted = round(error_ms) as int (smaller is better).

MULTIPLAYER: every seat in one match shares a single target, derived
deterministically from the match id (see match_target_ms). Same target for
all participants, fresh per match (match ids are random), unpredictable
without the id. Players each run their own clock; the server validates the
submitted time against the shared target, membership, bounds, and
one-submit-per-seat. Client timing is self-measured (as with Reflex Rush)
and NOT tamper-proof; bounds + target + idempotency are the enforcement.

FAIRNESS NOTE: elapsed time is measured client-side with a monotonic clock
and is not cryptographically verified. The server validates the shape and
bounds of the submission, computes error/XP itself, and protects against
duplicate submissions via the single-terminal-transition + replay path in
MiniappGameService. Do not treat submitted times as tamper-proof.
"""
from __future__ import annotations

import hashlib
import math
import random
import uuid
from dataclasses import dataclass
from typing import Any

GAME_TYPE = "perfect_second"

# Abuse bound for a single submitted stop. Genuine attempts finish in
# seconds; anything beyond ten minutes is junk, never skill.
MAX_ACTUAL_MS = 600_000.0

# Win = stop within 10% of the target (accuracy >= 90).
WIN_ERROR_PERCENT = 10.0


@dataclass(frozen=True)
class PerfectSecondConfig:
    min_target_ms: int = 3_000
    max_target_ms: int = 15_000
    step_ms: int = 1_000


PERFECT_DIFFICULTIES: dict[str, PerfectSecondConfig] = {
    # DB check constraint allows only easy/medium/hard ids.
    "easy": PerfectSecondConfig(),
    "medium": PerfectSecondConfig(
        min_target_ms=3_000, max_target_ms=12_000, step_ms=500,
    ),
    "hard": PerfectSecondConfig(
        min_target_ms=2_000, max_target_ms=10_000, step_ms=10,
    ),
}


def _steps(config: PerfectSecondConfig) -> int:
    return (config.max_target_ms - config.min_target_ms) // config.step_ms + 1


def roll_target_ms(config: PerfectSecondConfig = PerfectSecondConfig(),
                   rng=None) -> int:
    """Draw a fresh random target. `rng` is injectable for deterministic tests."""
    if config.step_ms <= 0:
        raise ValueError("step_ms must be positive")
    if config.min_target_ms <= 0:
        raise ValueError("min_target_ms must be positive")
    if config.max_target_ms < config.min_target_ms:
        raise ValueError("max_target_ms must be >= min_target_ms")
    source = rng if rng is not None else random
    index = source.randrange(_steps(config))
    return config.min_target_ms + index * config.step_ms


def match_target_ms(match_id: uuid.UUID, difficulty: str) -> int:
    """The shared multiplayer target for one match.

    Deterministic in (match id, difficulty): every seat resolves the same
    target without coordination races or extra storage, and a rematch (new
    id) always gets a fresh target. SHA-256 makes it unpredictable without
    the id; players never need the id early since the target is public
    once their attempt starts.
    """
    try:
        config = PERFECT_DIFFICULTIES[difficulty]
    except KeyError:
        raise ValueError(
            f"difficulty must be one of {sorted(PERFECT_DIFFICULTIES)}"
        ) from None
    digest = hashlib.sha256(
        f"{GAME_TYPE}:{match_id}:{difficulty}".encode("ascii")
    ).digest()
    index = int.from_bytes(digest[:8], "big") % _steps(config)
    return config.min_target_ms + index * config.step_ms


def parse_actual_ms(value: Any) -> float:
    """Validate one submitted stop time in ms. Raises ValueError."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(
            f"actual_ms must be a number in 0..{MAX_ACTUAL_MS:g}"
        )
    actual = float(value)
    if not math.isfinite(actual) or actual < 0 or actual > MAX_ACTUAL_MS:
        raise ValueError(
            f"actual_ms must be a number in 0..{MAX_ACTUAL_MS:g}"
        )
    return actual


def score_result(*, target_ms: int, actual_ms: float) -> dict:
    """Score one finished attempt from full-precision inputs.

    Never rounds the elapsed time first: error uses the exact measured
    value; only the persisted score (int ms) and the XP are rounded.
    """
    if not isinstance(target_ms, int) or isinstance(target_ms, bool):
        raise ValueError("target_ms must be a positive int")
    if target_ms <= 0:
        raise ValueError("target_ms must be a positive int")
    error_ms = abs(float(actual_ms) - target_ms)
    error_percent = error_ms / target_ms * 100.0
    accuracy_percent = max(0.0, 100.0 - error_percent)
    xp = xp_for_accuracy(accuracy_percent)
    # Win test in multiplicative form (error * 10 <= target): exact at the
    # 10% boundary, where the divided form can round to 10.000000000000002.
    won = error_ms * 10.0 <= float(target_ms)
    return {
        "error_ms": error_ms,
        "error_percent": error_percent,
        "accuracy_percent": accuracy_percent,
        "score_ms": int(round(error_ms)),
        "xp": xp,
        "won": won,
    }


def xp_for_accuracy(accuracy_percent: float) -> int:
    """0..100 XP: accuracy rounded half-up to the nearest multiple of 10.

    Exact integer math on hundredths of a point: n = floor((A + 500)/1000)
    with A = accuracy * 100, then 10 * n clamped to [0, 100].
    """
    hundredths = int(round(accuracy_percent * 100))
    units = (hundredths + 500) // 1000 if hundredths >= 0 else -1
    return max(0, min(100, 10 * units))
