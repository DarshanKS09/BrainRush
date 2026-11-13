"""Focus Rush: a falling-shapes attention arcade (pure rules, no DB/Telegram).

Gameplay
--------
A target instruction (one colour + one shape) is displayed for the whole
instruction window. Coloured shapes continuously fall from the top of the play
area toward the bottom. The player taps exactly the falling objects that match
the target; everything else is a distractor and must be ignored.

Rules implemented here (all server-authoritative):

* Objects spawn on a server timeline with independent lanes, speeds and spawn
  times. The client only animates the objects the server generated; it never
  invents one.
* Tapping a matching object removes it and awards ``hit_points`` plus a combo
  bonus (capped at ``max_combo_bonus``).
* Tapping a distractor awards nothing, costs no life, and resets the combo.
  Lives are only lost by letting a *target* fall past the bottom.
* A target that reaches the bottom untapped costs one life and increments the
  missed-target counter. Three misses end the run.
* Objects in flight when the target changes are marked ``stale``: they can no
  longer award points or cost lives, so an old object can never score under a
  new instruction.
* Duplicate taps are harmless: processed objects are remembered by id and a
  second tap scores nothing again.

The service layer persists score/XP; this module owns the numbers.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any, Iterable

GAME_TYPE = "focus_rush"

MAX_LIVES = 3
STATE_VERSION = 2

# Five colours and five shapes: easy/medium use subsets, hard uses all.
COLORS: tuple[str, ...] = ("red", "blue", "green", "yellow", "purple")
SHAPES: tuple[str, ...] = ("circle", "square", "triangle", "diamond", "star")

# Horizontal spawn lanes (fraction of play-area width). Independent objects,
# but lanes keep shapes from stacking into one unreadable column.
LANES: tuple[float, ...] = (0.09, 0.27, 0.45, 0.63, 0.81)
LANE_BUSY_PROGRESS = 0.45

# A client that stops polling (background tab, network drop) must not come
# back to three instant misses: after this gap the timeline is rebased and
# in-flight objects are dropped without penalty.
STALL_RESET_MS = 6_000
MAX_CATCHUP_SPAWNS = 24
# Objects are generated this far ahead of their spawn instant so a client
# polling about once a second still receives each shape before it enters the
# top of the play area (no mid-screen pop-in).
SPAWN_LOOKAHEAD_MS = 2_500
# No targets during the first moment of a run: the player needs a beat to read
# the instruction after pressing Start. Shapes still fall, so the screen is
# alive; the first target cannot land before WARMUP_MS + fall_ms.
WARMUP_MS = 1_200
PROCESSED_ID_MEMORY = 60
TARGET_CHANGE_LEAD_MS = 500


@dataclass(frozen=True)
class FocusConfig:
    """Difficulty knobs. Timing/speed differences are real, not cosmetic."""

    id: str
    fall_ms: int  # time for one object to travel the full play area
    fall_jitter: float  # per-object speed variation (fraction of fall_ms)
    spawn_interval_ms: int  # base gap between spawns
    spawn_jitter: float  # spawn gap variation
    max_objects: int  # simultaneous objects cap
    target_ratio: float  # chance a random spawn is a target
    target_every_ms: int  # guaranteed target at least this often
    target_change_ms: int  # how long one instruction stays active
    colors: tuple[str, ...]
    shapes: tuple[str, ...]
    hit_points: int
    max_combo_bonus: int
    win_score: int
    xp_multiplier: float


FOCUS_DIFFICULTIES: dict[str, FocusConfig] = {
    # Slow fall, sparse spawns, small palette, long instruction window.
    "easy": FocusConfig(
        id="easy",
        fall_ms=5_200,
        fall_jitter=0.10,
        spawn_interval_ms=1_200,
        spawn_jitter=0.20,
        max_objects=6,
        target_ratio=0.34,
        target_every_ms=2_000,
        target_change_ms=20_000,
        colors=COLORS[:3],
        shapes=SHAPES[:3],
        hit_points=10,
        max_combo_bonus=5,
        win_score=120,
        xp_multiplier=1.0,
    ),
    # Faster fall, denser spawns, one more colour and shape.
    "medium": FocusConfig(
        id="medium",
        fall_ms=3_600,
        fall_jitter=0.14,
        spawn_interval_ms=780,
        spawn_jitter=0.28,
        max_objects=7,
        target_ratio=0.30,
        target_every_ms=1_700,
        target_change_ms=15_000,
        colors=COLORS[:4],
        shapes=SHAPES[:4],
        hit_points=14,
        max_combo_bonus=6,
        win_score=200,
        xp_multiplier=1.25,
    ),
    # Fast fall, high spawn rate, full palette, shortest instruction window.
    "hard": FocusConfig(
        id="hard",
        fall_ms=2_400,
        fall_jitter=0.18,
        spawn_interval_ms=460,
        spawn_jitter=0.35,
        max_objects=10,
        target_ratio=0.28,
        target_every_ms=1_400,
        target_change_ms=11_000,
        colors=COLORS,
        shapes=SHAPES,
        hit_points=18,
        max_combo_bonus=8,
        win_score=300,
        xp_multiplier=1.5,
    ),
}


def config_for(difficulty: str) -> FocusConfig:
    """Difficulty config or ValueError (HTTP 422/400 at the route)."""
    try:
        return FOCUS_DIFFICULTIES[difficulty]
    except KeyError:
        raise ValueError(
            f"difficulty must be one of {sorted(FOCUS_DIFFICULTIES)}"
        ) from None


def instruction_for(target: dict[str, str]) -> str:
    return f"TAP {target['color'].upper()} {target['shape'].upper()}S"


def public_config(difficulty: str) -> dict[str, Any]:
    """Config echoed to the client so timing constants live in one place."""
    try:
        cfg = config_for(difficulty)
    except ValueError:
        cfg = FOCUS_DIFFICULTIES["medium"]
    return {
        "fall_ms": cfg.fall_ms,
        "spawn_interval_ms": cfg.spawn_interval_ms,
        "max_objects": cfg.max_objects,
        "target_change_ms": cfg.target_change_ms,
        "colors": list(cfg.colors),
        "shapes": list(cfg.shapes),
        "max_lives": MAX_LIVES,
    }


# ---------------------------------------------------------------------------
# State creation
# ---------------------------------------------------------------------------


def _rng(rng: random.Random | None) -> random.Random:
    return rng if rng is not None else random.Random()


def _roll_target(
    cfg: FocusConfig,
    rng: random.Random,
    *,
    exclude: dict[str, str] | None = None,
) -> dict[str, str]:
    for _ in range(20):
        candidate = {"color": rng.choice(cfg.colors), "shape": rng.choice(cfg.shapes)}
        if exclude is None or candidate != exclude:
            return candidate
    # Single-colour/single-shape edge: flip only the shape if possible.
    return {
        "color": rng.choice([c for c in cfg.colors if exclude is None or c != exclude["color"]] or list(cfg.colors)),
        "shape": rng.choice([s for s in cfg.shapes if exclude is None or s != exclude["shape"]] or list(cfg.shapes)),
    }


def new_state(
    difficulty: str,
    now_ms: int,
    rng: random.Random | None = None,
) -> dict[str, Any]:
    """Fresh run, paused so the instruction can be read before time starts."""
    cfg = config_for(difficulty)
    source = _rng(rng)
    target = _roll_target(cfg, source)
    return {
        "version": STATE_VERSION,
        "game": GAME_TYPE,
        "difficulty": cfg.id,
        "lives": MAX_LIVES,
        "score": 0,
        "combo": 0,
        "best_combo": 0,
        "hits": 0,
        "missed_targets": 0,
        "wrong_taps": 0,
        "distractors_passed": 0,
        "targets_spawned": 0,
        "accuracy_correct": 0,
        "accuracy_total": 0,
        "target": target,
        "target_changed_ms": now_ms,
        "next_target_change_ms": now_ms + cfg.target_change_ms,
        "objects": [],
        "seq": 0,
        "next_spawn_ms": now_ms,
        "next_target_ms": now_ms + WARMUP_MS + 300,
        "started_ms": now_ms,
        "ended_ms": None,
        "last_advance_ms": now_ms,
        "paused": True,
        "paused_at_ms": now_ms,
        "paused_total_ms": 0,
        "processed_ids": [],
        "recent_moves": [],
        "finished": False,
        "game_over": False,
        "result": None,
    }


# ---------------------------------------------------------------------------
# Timeline advance (resolve falls -> change target -> spawn)
# ---------------------------------------------------------------------------


def is_target_object(obj: dict[str, Any]) -> bool:
    return bool(obj.get("is_target")) and not bool(obj.get("stale"))


def _accuracy(state: dict[str, Any]) -> float:
    total = state.get("accuracy_total", 0)
    if total <= 0:
        return 0.0
    return round(state.get("accuracy_correct", 0) / total * 100, 1)


def _end(state: dict[str, Any], now_ms: int) -> None:
    if state.get("finished"):
        return
    state["finished"] = True
    state["game_over"] = True
    state["ended_ms"] = now_ms
    state["objects"] = []
    state["combo"] = 0


def _resolve_falls(state: dict[str, Any], now_ms: int) -> None:
    still_falling: list[dict[str, Any]] = []
    for obj in state["objects"]:
        if obj["spawned_at_ms"] + obj["fall_ms"] > now_ms:
            still_falling.append(obj)
            continue
        if is_target_object(obj):
            state["lives"] = max(0, state["lives"] - 1)
            state["missed_targets"] += 1
            state["accuracy_total"] += 1
            state["combo"] = 0
            obj["outcome"] = "missed"
            if state["lives"] <= 0:
                state["objects"] = still_falling
                _end(state, now_ms)
                return
        else:
            state["distractors_passed"] += 1
            obj["outcome"] = "passed"
    state["objects"] = still_falling


def _has_live_target(state: dict[str, Any], now_ms: int) -> bool:
    """A target the player can actually tap right now (not a scheduled one)."""
    return any(
        is_target_object(obj) and obj["spawned_at_ms"] <= now_ms
        for obj in state["objects"]
    )


def _visible_count(state: dict[str, Any], now_ms: int) -> int:
    """Objects already on screen; scheduled ones don't consume the cap."""
    return sum(1 for obj in state["objects"] if obj["spawned_at_ms"] <= now_ms)


def _alive_at(state: dict[str, Any], at_ms: int) -> int:
    """How many objects would be on screen at ``at_ms``.

    Used to enforce ``max_objects`` for shapes scheduled ahead: the cap is
    about simultaneity, not about how far ahead generation runs.
    """
    return sum(
        1
        for obj in state["objects"]
        if obj["spawned_at_ms"] <= at_ms < obj["spawned_at_ms"] + obj["fall_ms"]
    )


def _lane_for(state: dict[str, Any], at_ms: int, rng: random.Random) -> float:
    busy: set[int] = set()
    for obj in state["objects"]:
        elapsed = max(0, at_ms - obj["spawned_at_ms"])
        if elapsed / max(1, obj["fall_ms"]) >= LANE_BUSY_PROGRESS:
            continue
        # Nearest lane index to this object's x.
        busy.add(min(range(len(LANES)), key=lambda i: abs(LANES[i] - obj["x"])))
    free = [i for i in range(len(LANES)) if i not in busy]
    if free:
        return LANES[rng.choice(free)]
    return LANES[rng.randrange(len(LANES))]


def _roll_distractor(
    target: dict[str, str], cfg: FocusConfig, rng: random.Random
) -> dict[str, str]:
    for _ in range(20):
        color = rng.choice(cfg.colors)
        shape = rng.choice(cfg.shapes)
        if color != target["color"] or shape != target["shape"]:
            return {"color": color, "shape": shape}
    # Palette of one: flip only one attribute.
    if len(cfg.shapes) > 1:
        return {
            "color": target["color"],
            "shape": rng.choice([s for s in cfg.shapes if s != target["shape"]]),
        }
    return {
        "color": rng.choice([c for c in cfg.colors if c != target["color"]] or list(cfg.colors)),
        "shape": target["shape"],
    }


def _spawn(
    state: dict[str, Any],
    cfg: FocusConfig,
    at_ms: int,
    rng: random.Random,
    *,
    force_target: bool = False,
) -> dict[str, Any]:
    state["seq"] += 1
    warming_up = at_ms - int(state.get("started_ms", at_ms)) < WARMUP_MS
    target_match = (not warming_up) and (
        force_target or rng.random() < cfg.target_ratio
    )
    if target_match:
        spec = {
            "color": state["target"]["color"],
            "shape": state["target"]["shape"],
        }
        state["targets_spawned"] += 1
    else:
        spec = _roll_distractor(state["target"], cfg, rng)
    fall_ms = int(
        cfg.fall_ms * (1 + rng.uniform(-cfg.fall_jitter, max(0.0, cfg.fall_jitter)))
    )
    obj = {
        "id": f"o{state['seq']}",
        "color": spec["color"],
        "shape": spec["shape"],
        "x": round(_lane_for(state, at_ms, rng), 4),
        "spawned_at_ms": int(at_ms),
        "fall_ms": max(600, fall_ms),
        "is_target": bool(target_match),
        "stale": False,
        "outcome": None,
    }
    state["objects"].append(obj)
    return obj


def _change_target_if_due(
    state: dict[str, Any], cfg: FocusConfig, now_ms: int, rng: random.Random
) -> None:
    if now_ms < state["next_target_change_ms"]:
        return
    state["target"] = _roll_target(cfg, rng, exclude=state["target"])
    state["target_changed_ms"] = now_ms
    state["next_target_change_ms"] = now_ms + cfg.target_change_ms
    # In-flight objects were classified under the old instruction: neutral.
    for obj in state["objects"]:
        obj["stale"] = True
    state["next_target_ms"] = min(
        state.get("next_target_ms", now_ms), now_ms + TARGET_CHANGE_LEAD_MS
    )


def _spawn_due(
    state: dict[str, Any], cfg: FocusConfig, now_ms: int, rng: random.Random
) -> None:
    horizon = now_ms + SPAWN_LOOKAHEAD_MS
    # Never schedule shapes past an instruction change: they would be
    # classified under the outgoing target and stale the instant they appear.
    horizon = min(horizon, int(state.get("next_target_change_ms", horizon)))
    spawned = 0
    while state["next_spawn_ms"] <= horizon and spawned < MAX_CATCHUP_SPAWNS:
        at_ms = state["next_spawn_ms"]
        # Far behind (freeze/tab switch): don't dump a backlog of shapes.
        if now_ms - at_ms > cfg.spawn_interval_ms * 2:
            at_ms = now_ms
        gap = cfg.spawn_interval_ms * (
            1 + rng.uniform(-cfg.spawn_jitter, cfg.spawn_jitter)
        )
        if _alive_at(state, at_ms) >= cfg.max_objects:
            # Cap reached for that instant: skip this slot instead of
            # stacking a burst of shapes on top of each other.
            state["next_spawn_ms"] = int(at_ms + max(180, gap))
            spawned += 1
            continue
        _spawn(state, cfg, at_ms, rng)
        state["next_spawn_ms"] = int(at_ms + max(180, gap))
        spawned += 1

    # Warm-up: never force a target into the opening second.
    warmup_until = int(state.get("started_ms", now_ms)) + WARMUP_MS
    if now_ms >= state["next_target_ms"]:
        if now_ms < warmup_until:
            state["next_target_ms"] = warmup_until + 300
        elif not _has_live_target(state, now_ms):
            if _alive_at(state, now_ms) < cfg.max_objects:
                _spawn(state, cfg, now_ms, rng, force_target=True)
                state["next_target_ms"] = now_ms + cfg.target_every_ms
            else:
                state["next_target_ms"] = now_ms + 250
        else:
            state["next_target_ms"] = now_ms + cfg.target_every_ms


def _rebase_after_stall(
    state: dict[str, Any], cfg: FocusConfig, now_ms: int
) -> None:
    """Drop unseeable objects and restart the timeline (no life penalty)."""
    for obj in state["objects"]:
        obj["outcome"] = "dropped"
    state["objects"] = []
    state["next_spawn_ms"] = now_ms + 350
    state["next_target_ms"] = now_ms + 900
    state["next_target_change_ms"] = now_ms + cfg.target_change_ms
    state["last_advance_ms"] = now_ms


def advance(
    state: dict[str, Any],
    now_ms: int,
    rng: random.Random | None = None,
) -> None:
    """Move the run forward to ``now_ms`` (idempotent for the same instant)."""
    if state.get("finished"):
        return
    if state.get("paused"):
        # A paused run has no live clock; keep the anchor fresh.
        state["last_advance_ms"] = now_ms
        return
    cfg = config_for(state["difficulty"])
    source = _rng(rng)
    if now_ms - int(state.get("last_advance_ms", now_ms)) > STALL_RESET_MS:
        _rebase_after_stall(state, cfg, now_ms)
    _resolve_falls(state, now_ms)
    if state.get("finished"):
        state["last_advance_ms"] = now_ms
        return
    _change_target_if_due(state, cfg, now_ms, source)
    _spawn_due(state, cfg, now_ms, source)
    state["last_advance_ms"] = now_ms


# ---------------------------------------------------------------------------
# Pause / resume
# ---------------------------------------------------------------------------


def pause(state: dict[str, Any], now_ms: int) -> None:
    if state.get("finished") or state.get("paused"):
        return
    state["paused"] = True
    state["paused_at_ms"] = now_ms
    state["last_advance_ms"] = now_ms


def resume(state: dict[str, Any], now_ms: int) -> None:
    """Unfreeze and shift the whole timeline by the server-measured pause."""
    if not state.get("paused"):
        return
    paused_at = int(state.get("paused_at_ms") or now_ms)
    delta = max(0, now_ms - paused_at)
    if delta:
        for obj in state["objects"]:
            obj["spawned_at_ms"] += delta
        for key in ("next_spawn_ms", "next_target_ms", "next_target_change_ms", "started_ms"):
            if isinstance(state.get(key), int):
                state[key] += delta
        state["target_changed_ms"] = int(state.get("target_changed_ms", 0)) + delta
        state["paused_total_ms"] = int(state.get("paused_total_ms", 0)) + delta
    state["paused"] = False
    state["paused_at_ms"] = None
    state["last_advance_ms"] = now_ms


# ---------------------------------------------------------------------------
# Taps
# ---------------------------------------------------------------------------


def _remember_processed(state: dict[str, Any], object_id: str) -> None:
    ids = list(state.get("processed_ids") or [])
    ids.append(object_id)
    state["processed_ids"] = ids[-PROCESSED_ID_MEMORY:]


def tap(
    state: dict[str, Any],
    object_id: str,
    now_ms: int,
    rng: random.Random | None = None,
) -> dict[str, Any]:
    """Validate and apply one tap. Never raises for stale/unknown ids.

    Returns ``{outcome, object_id, points}`` where outcome is one of
    ``hit``, ``wrong``, ``duplicate``, ``expired``, ``paused``, ``finished``.
    """
    if not isinstance(object_id, str) or not object_id.strip():
        raise ValueError("object_id must be a non-empty string")
    if state.get("finished"):
        return {"outcome": "finished", "object_id": object_id, "points": 0}
    if state.get("paused"):
        return {"outcome": "paused", "object_id": object_id, "points": 0}

    advance(state, now_ms, rng)
    if state.get("finished"):
        return {"outcome": "finished", "object_id": object_id, "points": 0}

    if object_id in (state.get("processed_ids") or []):
        return {"outcome": "duplicate", "object_id": object_id, "points": 0}

    obj = next((o for o in state["objects"] if o["id"] == object_id), None)
    if obj is None:
        # Fell (and was resolved) before this tap landed, or never existed.
        return {"outcome": "expired", "object_id": object_id, "points": 0}
    if obj["spawned_at_ms"] > now_ms:
        # Scheduled shape tapped before it entered the play area.
        return {"outcome": "too_early", "object_id": object_id, "points": 0}

    cfg = config_for(state["difficulty"])
    state["objects"] = [o for o in state["objects"] if o["id"] != object_id]
    _remember_processed(state, object_id)
    state["accuracy_total"] += 1

    if not is_target_object(obj):
        state["wrong_taps"] += 1
        state["combo"] = 0
        return {"outcome": "wrong", "object_id": object_id, "points": 0}

    state["hits"] += 1
    state["accuracy_correct"] += 1
    state["combo"] += 1
    state["best_combo"] = max(int(state.get("best_combo", 0)), state["combo"])
    points = cfg.hit_points + min(state["combo"], cfg.max_combo_bonus)
    state["score"] += points
    return {"outcome": "hit", "object_id": object_id, "points": points}


# ---------------------------------------------------------------------------
# Scoring / results
# ---------------------------------------------------------------------------


def accuracy_percent(state: dict[str, Any]) -> float:
    return _accuracy(state)


def xp_for_run(
    *, score: int, accuracy_percent: float, hits: int, difficulty: str
) -> int:
    """XP from server-owned counters (client-submitted score is never used)."""
    cfg = config_for(difficulty)
    base = max(0, score) // 15
    accuracy_bonus = min(12, int(max(0.0, accuracy_percent) // 10))
    hit_bonus = min(20, max(0, hits))
    return max(1, int((base + accuracy_bonus + hit_bonus) * cfg.xp_multiplier))


def finish(state: dict[str, Any], now_ms: int) -> dict[str, Any]:
    """End the run (if needed) and return the persisted result payload."""
    if not state.get("finished"):
        _end(state, now_ms)
    if state.get("result"):
        return state["result"]
    cfg = config_for(state["difficulty"])
    accuracy = accuracy_percent(state)
    xp = xp_for_run(
        score=int(state.get("score", 0)),
        accuracy_percent=accuracy,
        hits=int(state.get("hits", 0)),
        difficulty=cfg.id,
    )
    won = int(state.get("score", 0)) >= cfg.win_score
    started = int(state.get("started_ms", now_ms))
    played_ms = max(0, int(state.get("ended_ms") or now_ms) - started - int(state.get("paused_total_ms", 0)))
    result = {
        "outcome": "win" if won else "loss",
        "score": int(state.get("score", 0)),
        "xp_earned": xp,
        "accuracy_percent": accuracy,
        "hits": int(state.get("hits", 0)),
        "missed_targets": int(state.get("missed_targets", 0)),
        "wrong_taps": int(state.get("wrong_taps", 0)),
        "best_combo": int(state.get("best_combo", 0)),
        "duration_ms": played_ms,
        "difficulty": cfg.id,
    }
    state["result"] = result
    return result


# ---------------------------------------------------------------------------
# Public view
# ---------------------------------------------------------------------------


def public_objects(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Only what the client needs to animate and hit-test an object."""
    return [
        {
            "id": obj["id"],
            "color": obj["color"],
            "shape": obj["shape"],
            "x": obj["x"],
            "spawned_at_ms": obj["spawned_at_ms"],
            "fall_ms": obj["fall_ms"],
            "stale": bool(obj.get("stale")),
        }
        for obj in state.get("objects", [])
    ]


def public_view(
    state: dict[str, Any],
    now_ms: int,
    *,
    session_id: str,
    last_tap: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """State the frontend renders. Derives nothing the server doesn't own."""
    cfg = config_for(state["difficulty"])
    target = state["target"]
    result = state.get("result")
    return {
        "session_id": session_id,
        "game_type": GAME_TYPE,
        "difficulty": cfg.id,
        "target": {"color": target["color"], "shape": target["shape"]},
        "instruction": instruction_for(target),
        "score": int(state.get("score", 0)),
        "lives": int(state.get("lives", MAX_LIVES)),
        "max_lives": MAX_LIVES,
        "combo": int(state.get("combo", 0)),
        "best_combo": int(state.get("best_combo", 0)),
        "hits": int(state.get("hits", 0)),
        "missed": int(state.get("missed_targets", 0)),
        "wrong_taps": int(state.get("wrong_taps", 0)),
        "targets_spawned": int(state.get("targets_spawned", 0)),
        "accuracy_percent": accuracy_percent(state),
        "objects": public_objects(state),
        "config": public_config(cfg.id),
        "now_ms": int(now_ms),
        "target_changes_in_ms": max(
            0, int(state.get("next_target_change_ms", now_ms)) - now_ms
        ),
        "paused": bool(state.get("paused")),
        "finished": bool(state.get("finished")),
        "game_over": bool(state.get("game_over")),
        "result": result,
        "last_tap": last_tap,
    }


def iter_targets(objects: Iterable[dict[str, Any]]) -> Iterable[dict[str, Any]]:
    return (obj for obj in objects if is_target_object(obj))
