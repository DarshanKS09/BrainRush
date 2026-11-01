"""Perfect Second: pure game rules (no Telegram, no database).

Gameplay: the server holds a target duration; the player starts a clock and
taps STOP when they believe the elapsed time matches the target. The target
is public (shown during the attempt); only the player's timing skill matters.

Difficulties (all ranges configurable below, never zero/negative):
  easy   - whole-second targets, e.g. 5, 7, 10, 12 s.
  medium - half-second targets, e.g. 4.5, 5.5, 7.5 s (never hundredths).
  hard   - hundredth-second targets, e.g. 5.34, 6.76 s.

XP RULE (applied only when an attempt completes; abandoned games award
nothing). There is NO flat participation award: XP is strictly proportional
to how close the stop lands on the target, and only an exact stop earns the
maximum. The backend computes and persists it (client values never trusted):
  error_ms   = abs(actual_ms - target_ms)          (full precision)
  earnedXP   = max(0, floor(20 * (1 - error_ms / target_ms)))
Exact match -> 20; 5% error -> 19; 10% -> 18; 30% -> 14; 50% -> 10;
>=100% error -> 0. Always an integer in [0, 20]; a near miss NEVER earns 20.

FULL PRECISION RULE: the stopwatch's measured time is a full-precision
float from the monotonic clock, and NOTHING is rounded before scoring.
Error, accuracy, XP, the perfect test (100% accuracy only for an exact
stop), and the win test all derive from the raw measured time. Rounding
happens only for display (the client formats seconds on screen). The one
integer conversion is the persisted leaderboard score, round(error_ms),
purely because the score column is an integer; smaller is better and
ranking order is unaffected.

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
    """Score one finished attempt at full precision (backend-authoritative).

    The measured time is used raw: error, accuracy, XP, and the win test
    all derive from the full-precision float, so rounding happens only for
    display and never before scoring. Only an exact stop (error 0.0) is
    100% accurate / perfect.
    """
    if not isinstance(target_ms, int) or isinstance(target_ms, bool):
        raise ValueError("target_ms must be a positive int")
    if target_ms <= 0:
        raise ValueError("target_ms must be a positive int")
    actual = parse_actual_ms(actual_ms)
    error_ms = abs(actual - target_ms)
    error_percent = error_ms / target_ms * 100.0
    accuracy_percent = max(0.0, 100.0 - error_percent)
    xp = xp_for_error(error_ms=error_ms, target_ms=target_ms)
    # Win test in multiplicative form (error * 10 <= target): exact at the
    # 10% boundary without a float division.
    won = error_ms * 10 <= target_ms
    return {
        "actual_ms": actual,
        "error_ms": error_ms,
        "error_percent": error_percent,
        "accuracy_percent": accuracy_percent,
        # Leaderboard storage only: the score column is an integer, so the
        # error is rounded here — XP/accuracy above use the raw value.
        "score_ms": int(round(error_ms)),
        "xp": xp,
        "won": won,
    }


def xp_for_error(*, error_ms: float, target_ms: int) -> int:
    """0..20 XP: ``max(0, floor(20 * (1 - |actual - target| / target)))``.

    Implemented as the algebraically identical
    ``floor(20 * (target - error) / target)`` so exact percentages land on
    exact integers instead of drifting through an intermediate float
    division (a 5% miss must be exactly 19 XP, never 18). Exact stop ->
    20; error >= target -> 0.
    """
    if not isinstance(target_ms, int) or isinstance(target_ms, bool):
        raise ValueError("target_ms must be a positive int")
    if target_ms <= 0:
        raise ValueError("target_ms must be a positive int")
    if isinstance(error_ms, bool) or not isinstance(error_ms, (int, float)):
        raise ValueError("error_ms must be a non-negative number")
    if not math.isfinite(error_ms) or error_ms < 0:
        raise ValueError("error_ms must be a non-negative number")
    return max(0, math.floor(20 * (target_ms - error_ms) / target_ms))
