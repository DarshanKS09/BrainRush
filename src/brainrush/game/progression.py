"""Player progression: pure XP/level math (no database).

Level rule (cumulative XP thresholds, quadratic growth):
  xp_to_reach(level) = 100 * level * (level - 1) // 2
  L1: 0, L2: 100, L3: 300, L4: 600, L5: 1000, ...

`level_for_xp` inverts the curve; `progress_for_xp` returns the values the
dashboard needs: current level, XP into the level, and XP required to finish
it. Stored `current_level` is refreshed on every completed game via the
existing `new_level` parameter (no schema change).
"""
from __future__ import annotations


def xp_to_reach(level: int) -> int:
    if not isinstance(level, int) or isinstance(level, bool) or level < 1:
        raise ValueError("level must be an int >= 1")
    return 100 * level * (level - 1) // 2


def level_for_xp(total_xp: int) -> int:
    if not isinstance(total_xp, int) or isinstance(total_xp, bool) or total_xp < 0:
        raise ValueError("total_xp must be an int >= 0")
    level = 1
    while xp_to_reach(level + 1) <= total_xp:
        level += 1
    return level


def progress_for_xp(total_xp: int) -> dict[str, int]:
    """Return {level, xp_into_level, xp_for_next} for dashboard progress bars."""
    level = level_for_xp(total_xp)
    base = xp_to_reach(level)
    top = xp_to_reach(level + 1)
    return {
        "level": level,
        "xp_into_level": total_xp - base,
        "xp_for_next": top - base,
    }
