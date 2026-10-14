"""Color Sequence: pure game rules (no Telegram, no database).

Gameplay: the server holds a color sequence (values 0-3). The player must
repeat the first `level` colors by tapping. Each completed level appends one
new random color and level+1, up to `max_level`. A wrong tap ends the run.

XP RULE (applied only when a game completes; abandoned games award nothing):
  win  -> max_level * xp_per_level + win_bonus
  loss -> levels_completed * xp_per_level (0 when the first level fails)
Score persisted = levels_completed (higher is better).
Playback speed (playback_ms) is a display concern; the backend enforces only
sequence lengths, and the frontend must read timing from the catalog.

All knobs live in ColorSequenceConfig so difficulties stay data-driven.
"""
from __future__ import annotations

import random
from dataclasses import dataclass

COLORS = (0, 1, 2, 3)


class InvalidTapError(ValueError):
    """Tap input is unusable (does not advance or consume anything)."""


@dataclass(frozen=True)
class ColorSequenceConfig:
    start_length: int = 3
    max_level: int = 8
    xp_per_level: int = 6
    win_bonus: int = 30
    playback_ms: int = 650


COLOR_DIFFICULTIES: dict[str, ColorSequenceConfig] = {
    # DB check constraint allows only easy/medium/hard ids; the frontend
    # labels medium as "Normal".
    "easy": ColorSequenceConfig(),
    "medium": ColorSequenceConfig(
        start_length=4, max_level=10, xp_per_level=8, win_bonus=50,
        playback_ms=500,
    ),
    "hard": ColorSequenceConfig(
        start_length=6, max_level=12, xp_per_level=10, win_bonus=80,
        playback_ms=380,
    ),
}


def roll_color(rng=None) -> int:
    """Draw one color index. `rng` is injectable for deterministic tests."""
    source = rng if rng is not None else random
    return source.randint(0, 3)


def new_sequence(length: int, rng=None) -> list[int]:
    if length < 1:
        raise ValueError("length must be >= 1")
    return [roll_color(rng) for _ in range(length)]


def parse_tap(value) -> int:
    """Validate a tapped color index. Raises InvalidTapError."""
    if isinstance(value, bool) or not isinstance(value, int) or value not in COLORS:
        raise InvalidTapError("tap must be a color index 0-3")
    return value


def check_tap(sequence: list[int], position: int, color: int) -> bool:
    """True when the tap matches the expected next color (pure, no mutation)."""
    if position < 0 or position >= len(sequence):
        raise InvalidTapError("tap position out of range")
    return sequence[position] == color


def xp_for_color_result(
    *, levels_completed: int, won: bool,
    config: ColorSequenceConfig = ColorSequenceConfig(),
) -> int:
    if not isinstance(levels_completed, int) or levels_completed < 0:
        raise ValueError("levels_completed must be an int >= 0")
    if won:
        return config.max_level * config.xp_per_level + config.win_bonus
    return levels_completed * config.xp_per_level
