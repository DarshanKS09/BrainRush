"""Focus Rush: pure game rules (no Telegram, no database).

Gameplay: an attention game where the player must tap only the shapes
matching the current instruction (e.g., "Tap only BLUE CIRCLES") while
ignoring all other shapes. 60-second session with 3 lives.

Difficulty progressively increases: more colors, more shapes, more
distractors, faster rounds, changing instructions, similar-looking targets.

FAIRNESS: all game state (target, instruction, timing) is server-authoritative.
Frontend only renders what the server provides; client tap values are validated
server-side. Duplicate taps are idempotent per client_move_id.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Core types
# ---------------------------------------------------------------------------

Shape = str  # "circle", "square", "triangle", "diamond"
Color = str  # "red", "blue", "green", "yellow"

TargetSpec = Tuple[Color, Shape]  # (color, shape) pair e.g. ("blue", "circle")

# ---------------------------------------------------------------------------
# Difficulty configurations
# ---------------------------------------------------------------------------

# Each difficulty step adds more colors, shapes, and distractors.
# The instruction always specifies exactly one (color, shape) pair to tap.

FOCUS_DIFFICULTIES: dict[str, dict[str, Any]] = {
    # Level 1: simplest — 1 color, 1 shape, 4 total targets
    "level_1": {
        "num_colors": 1,
        "num_shapes": 1,
        "total_targets": 4,
        "distractor_ratio": 3,  # 3 distractors for every target
        "instruction_ttl_ms": 5_000,  # instruction stays visible 5s min
        "round_ms": 3_000,  # round duration before instruction changes
        "combo_threshold": 5,  # combo multiplier activates after 5 correct
        "correct_bonus": 10,
        "incorrect_penalty_life": 1,
        "miss_penalty_life": 0.5,  # fractional life loss for missed targets
    },
    # Level 2: 2 colors, 2 shapes, 8 total targets
    "level_2": {
        "num_colors": 2,
        "num_shapes": 2,
        "total_targets": 8,
        "distractor_ratio": 3,
        "instruction_ttl_ms": 4_000,
        "round_ms": 2_500,
        "combo_threshold": 5,
        "correct_bonus": 10,
        "incorrect_penalty_life": 1,
        "miss_penalty_life": 0.5,
    },
    # Level 3: 3 colors, 2 shapes, 12 total targets, faster
    "level_3": {
        "num_colors": 3,
        "num_shapes": 2,
        "total_targets": 12,
        "distractor_ratio": 3,
        "instruction_ttl_ms": 3_500,
        "round_ms": 2_000,
        "combo_threshold": 5,
        "correct_bonus": 10,
        "incorrect_penalty_life": 1,
        "miss_penalty_life": 0.5,
    },
    # Level 4: 3 colors, 3 shapes, 15 total targets
    "level_4": {
        "num_colors": 3,
        "num_shapes": 3,
        "total_targets": 15,
        "distractor_ratio": 4,  # more distractors
        "instruction_ttl_ms": 3_000,
        "round_ms": 1_500,
        "combo_threshold": 7,
        "correct_bonus": 10,
        "incorrect_penalty_life": 1,
        "miss_penalty_life": 0.5,
    },
    # Level 5: 4 colors, 3 shapes, 20 total targets, faster
    "level_5": {
        "num_colors": 4,
        "num_shapes": 3,
        "total_targets": 20,
        "distractor_ratio": 4,
        "instruction_ttl_ms": 2_500,
        "round_ms": 1_200,
        "combo_threshold": 7,
        "correct_bonus": 10,
        "incorrect_penalty_life": 1,
        "miss_penalty_life": 0.5,
    },
    # Level 6: 4 colors, 4 shapes, 25 total targets, fastest
    "level_6": {
        "num_colors": 4,
        "num_shapes": 4,
        "total_targets": 25,
        "distractor_ratio": 4,
        "instruction_ttl_ms": 2_000,
        "round_ms": 1_000,
        "combo_threshold": 10,
        "correct_bonus": 10,
        "incorrect_penalty_life": 1,
        "miss_penalty_life": 0.5,
    },
}


def difficulty_id(level: int) -> str:
    """Return the difficulty id for a given level (1-indexed)."""
    mapping = {1: "level_1", 2: "level_2", 3: "level_3", 4: "level_4", 5: "level_5", 6: "level_6"}
    return mapping.get(level, "level_1")


def difficulties() -> list[str]:
    """Return ordered list of difficulty ids."""
    return list(FOCUS_DIFFICULTIES.keys())


# ---------------------------------------------------------------------------
# Target generation
# ---------------------------------------------------------------------------


COLORS: list[Color] = ["red", "blue", "green", "yellow"]
SHAPES: list[Shape] = ["circle", "square", "triangle", "diamond"]


def all_possible_targets(num_colors: int, num_shapes: int) -> list[TargetSpec]:
    """Generate the full grid of (color, shape) specs for the given palette."""
    colors = COLORS[:num_colors]
    shapes = SHAPES[:num_shapes]
    targets: list[TargetSpec] = []
    for c in colors:
        for s in shapes:
            targets.append((c, s))
    return targets


def generate_instruction(
    level: int,
    rng: random.Random | None = None,
) -> dict[str, Any]:
    """Generate a random (instruction, target) pair for the given level.

    Returns {
        "instruction": "Tap only BLUE CIRCLES.",
        "target_color": "blue",
        "target_shape": "circle",
        "valid_targets": [("blue", "circle")],  # always exactly one
    }
    """
    cfg = FOCUS_DIFFICULTIES[f"level_{level}"]
    num_colors = cfg["num_colors"]
    num_shapes = cfg["num_shapes"]

    # Choose the target (color, shape) pair
    targets = all_possible_targets(num_colors, num_shapes)
    target = rng.choice(targets) if rng else random.choice(targets)
    target_color, target_shape = target

    # Build the full grid of display targets (including distractors)
    # We need total_targets tiles, with exactly one being the correct target.
    # The rest are distractors: random (color, shape) pairs that are NOT the target.
    display_targets: list[TargetSpec] = [target]  # start with the correct one

    # Fill the rest with distractors
    all_combos = all_possible_targets(num_colors, num_shapes)
    # Remove the true target from the pool so it can't appear as a distractor
    remaining = [t for t in all_combos if t != target]

    # If we don't have enough distractors, allow repeats (rare at high levels)
    while len(display_targets) < cfg["total_targets"]:
        d = random.choice(remaining) if remaining else random.choice(all_combos)
        display_targets.append(d)

    # Shuffle the display order
    if rng:
        rng.shuffle(display_targets)
    else:
        random.shuffle(display_targets)

    instruction = f"Tap only {target_color.upper()} {target_shape.upper()}S."

    return {
        "instruction": instruction,
        "target_color": target_color,
        "target_shape": target_shape,
        "display_targets": display_targets,  # list of (color, shape) tuples
        "num_targets": cfg["total_targets"],
    }


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def compute_score(
    correct: bool,
    combo: int,
    combo_threshold: int,
    base_bonus: int = 10,
) -> int:
    """Compute points for a tap.

    - Base: base_bonus (default 10)
    - Combo multiplier: 1x up to threshold, then +1x per additional correct
    """
    score = base_bonus
    if correct and combo >= combo_threshold:
        # Bonus: +1 point per combo beyond the threshold, capped at 3 extra
        score += min(combo - combo_threshold, 3)
    return score


def life_penalty(
    is_incorrect: bool,
    is_missed: bool,
    config: dict[str, Any],
) -> float:
    """Return life penalty. Positive = lose life(s)."""
    if is_incorrect:
        return config["incorrect_penalty_life"]
    if is_missed:
        return config["miss_penalty_life"]
    return 0.0


# ---------------------------------------------------------------------------
# Combo logic
# ---------------------------------------------------------------------------

def update_combo(
    correct: bool,
    combo: int,
    combo_threshold: int,
) -> int:
    """Update combo count.

    - Correct tap: increment combo
    - Incorrect/missed: reset combo to 0
    """
    if correct:
        return combo + 1
    return 0


# ---------------------------------------------------------------------------
# Round/progression state
# ---------------------------------------------------------------------------

@dataclass
class FocusRoundState:
    """State for one round of Focus Rush (sequential shape display)."""

    instruction: str
    target_color: Color
    target_shape: Shape
    active_shape: Optional[TargetSpec] = None  # Currently visible (color, shape), None if gap
    phase: str = 'showing'  # 'showing', 'gap', 'complete'
    shapes_shown: int = 0  # how many shapes have been shown this round
    shapes_per_round: int = 5  # from difficulty config (5/8/12)
    round_number: int = 1
    round_start_ms: int = 0  # when this round started
    instruction_change_ms: int = 0  # when the instruction was last changed
    finished: bool = False

    def elapsed_ms(self, now_ms: int) -> int:
        return now_ms - self.round_start_ms

    def instruction_elapsed_ms(self, now_ms: int) -> int:
        return now_ms - self.instruction_change_ms

    def is_showing(self) -> bool:
        return self.phase == 'showing' and self.active_shape is not None

    def is_gap(self) -> bool:
        return self.phase == 'gap'

    def is_complete(self) -> bool:
        return self.phase == 'complete' or self.shapes_shown >= self.shapes_per_round


# ---------------------------------------------------------------------------
# Game session state (what we store server-side)
# ---------------------------------------------------------------------------

@dataclass
class FocusSessionState:
    """Server-side state for a Focus Rush game session."""

    session_id: str
    game_type: str = "focus_rush"
    difficulty: str = "level_1"  # tracks current level
    level: int = 1
    time_remaining: int = 60  # seconds
    lives: int = 3
    score: int = 0
    combo: int = 0
    highest_round: int = 0
    accuracy_correct: int = 0
    accuracy_total: int = 0
    best_combo: int = 0
    rounds_completed: int = 0
    current_round: Optional[FocusRoundState] = None
    game_over: bool = False
    finished: bool = False
    last_instruction_change: int = 0  # epoch ms for instruction TTL

    def to_public(self) -> dict:
        """Return the public view for the frontend."""
        return {
            "session_id": self.session_id,
            "game_type": self.game_type,
            "difficulty": self.difficulty,
            "level": self.level,
            "time_remaining": max(0, self.time_remaining),
            "lives": max(0, self.lives),
            "score": self.score,
            "combo": self.combo,
            "highest_round": self.highest_round,
            "accuracy_percent": round(
                self.accuracy_correct / self.accuracy_total * 100, 1
            )
            if self.accuracy_total > 0
            else 0,
            "best_combo": self.best_combo,
            "rounds_completed": self.rounds_completed,
            "game_over": self.game_over,
            "finished": self.finished,
        }

    def is_active(self) -> bool:
        return not self.finished and self.lives > 0 and self.time_remaining > 0


# ---------------------------------------------------------------------------
# Core game logic functions (pure, no DB)
# ---------------------------------------------------------------------------

def start_new_session(session_id: str) -> FocusSessionState:
    """Create a fresh session state."""
    return FocusSessionState(session_id=session_id)


def process_tap(
    state: FocusSessionState,
    tap_color: str,
    tap_shape: Shape,
    client_move_id: str,
    now_ms: int,
) -> dict[str, Any]:
    """Process a player tap and return the result payload.

    This is the core game logic function. It validates the tap against
    the current instruction, updates state, and returns a result dict.
    """
    if state.finished or state.game_over:
        return {"game_over": True, "finished": True, "result": state.to_public()}

    # Get current round
    round_state = state.current_round
    if round_state is None:
        # No round started yet — shouldn't happen, but safety first
        return {"error": "no_active_round"}

    cfg = FOCUS_DIFFICULTIES[state.difficulty]

    # Check if instruction has been visible long enough
    instruction_elapsed = round_state.instruction_elapsed_ms(now_ms)
    if instruction_elapsed > cfg["instruction_ttl_ms"]:
        # Instruction changed — this is a new round effectively
        # (handled by the server scheduling instruction changes)
        pass

    # Determine if the tap is correct
    is_correct = (
        tap_color == round_state.target_color
        and tap_shape == round_state.target_shape
    )

    # Count toward accuracy
    state.accuracy_total += 1
    if is_correct:
        state.accuracy_correct += 1

    # Update combo
    new_combo = update_combo(is_correct, state.combo, cfg["combo_threshold"])
    state.combo = new_combo

    # Check for missed target (no tap within round time)
    round_elapsed = round_state.elapsed_ms(now_ms)
    round_duration = cfg["round_ms"]

    # Determine if this tap was "missed" (too late)
    is_missed = round_elapsed > round_duration and not round_state.finished

    # If round is already finished (e.g. from timeout), just return
    if round_state.finished:
        return {"game_over": state.game_over, "finished": True, "result": state.to_public()}

    # Process the tap result
    # life_penalty returns positive value for losing life
    # Pass the actual correctness status: incorrect tap = not is_correct
    life_delta = life_penalty(not is_correct, is_missed, cfg)

    if is_correct:
        # Correct tap: add points
        points = compute_score(
            correct=True,
            combo=new_combo,
            combo_threshold=cfg["combo_threshold"],
            base_bonus=cfg["correct_bonus"],
        )
        state.score += points

        # Check for combo-based level progression
        if new_combo >= cfg["combo_threshold"] and state.rounds_completed > 0:
            # Chance to advance level based on combo
            if random.random() < 0.1:  # 10% chance per combo threshold met
                state.level = min(6, state.level + 1)
                state.difficulty = difficulty_id(state.level)

        # If we hit the combo threshold and haven't maxed level, possibly advance
        if new_combo >= cfg["combo_threshold"] and state.level < 6:
            # Advance level if enough rounds completed
            if state.rounds_completed >= 3 and random.random() < 0.05:
                state.level = min(6, state.level + 1)
                state.difficulty = difficulty_id(state.level)

    if not is_correct:
        # Incorrect tap: lose life
        state.lives = max(0, state.lives - life_delta)

    # Check if missed (no valid tap in time)
    if is_missed:
        # Missed target penalty: lose a life
        state.lives = max(0, state.lives - 0.5)  # fractional to allow 0.5 check

    # Update highest round
    if state.rounds_completed > state.highest_round:
        state.highest_round = state.rounds_completed

    # Check if round is complete (timer expired)
    round_complete = round_elapsed >= round_duration

    if round_complete and not round_state.finished:
        # Advance to next round (new instruction, new target)
        state.rounds_completed += 1
        if state.rounds_completed > state.highest_round:
            state.highest_round = state.rounds_completed

        # Create next round
        state.current_round = _new_round(state.level, now_ms)
        state.instruction_change_ms = now_ms
        round_state.finished = True  # mark old round finished

        # Check level progression after rounds completed
        _check_level_progression(state)

    # Check game over conditions
    if state.lives <= 0:
        state.game_over = True
        state.finished = True

    if state.time_remaining <= 0:
        state.finished = True
        state.game_over = True

    return {
        "game_over": state.game_over,
        "finished": state.finished,
        "result": state.to_public(),
        "correct": is_correct,
        "combo": state.combo,
        "life_lost": life_delta > 0,
        "points_earned": (
            compute_score(correct=True, combo=new_combo, combo_threshold=cfg["combo_threshold"], base_bonus=cfg["correct_bonus"])
            if is_correct
            else 0
        ),
    }

def _new_round(level: int, now_ms: int) -> FocusRoundState:
    """Create a new round with a fresh instruction and target."""
    instruction_data = generate_instruction(level)
    return FocusRoundState(
        instruction=instruction_data["instruction"],
        target_color=instruction_data["target_color"],
        target_shape=instruction_data["target_shape"],
        active_shape=(instruction_data["target_color"], instruction_data["target_shape"]),
        phase='showing',
        shapes_shown=0,
        shapes_per_round=instruction_data.get("num_targets", 5),
        round_number=1,
        round_start_ms=now_ms,
        instruction_change_ms=now_ms,
        finished=False,
    )


def _check_level_progression(state: FocusSessionState) -> None:
    """Check if the player should advance to a harder level."""
    # Convert easy/medium/hard difficulty to level number for FOCUS_DIFFICULTIES lookup
    difficulty = state.difficulty
    level_map = {"easy": 1, "medium": 3, "hard": 6}
    level = level_map.get(difficulty, 1)
    cfg = FOCUS_DIFFICULTIES[f"level_{level}"]

    # Advance level every few rounds based on performance
    if state.rounds_completed >= 5 and state.level < 6:
        # If they've been surviving, increase difficulty
        state.level = min(6, state.level + 1)
        state.difficulty = difficulty_id(state.level)


def end_session(state: FocusSessionState) -> dict[str, Any]:
    """Finalize a session and return the result payload."""
    state.finished = True
    state.game_over = True

    # Compute accuracy
    accuracy_percent = (
        round(state.accuracy_correct / state.accuracy_total * 100, 1)
        if state.accuracy_total > 0
        else 0
    )

    result = {
        "session_id": state.session_id,
        "game_type": state.game_type,
        "difficulty": state.difficulty,
        "level": state.level,
        "score": state.score,
        "time_remaining": max(0, state.time_remaining),
        "lives": max(0, state.lives),
        "combo": state.best_combo,
        "highest_round": state.highest_round,
        "accuracy_percent": accuracy_percent,
        "best_combo": state.best_combo,
        "rounds_completed": state.rounds_completed,
        "game_over": state.game_over,
        "finished": True,
    }

    return result


# ---------------------------------------------------------------------------
# XP computation (reuse pattern from other games)
# ---------------------------------------------------------------------------

def xp_for_focus_rush(
    score: int,
    accuracy_percent: float,
    best_combo: int,
    rounds_completed: int,
    level: int,
) -> int:
    """Compute XP earned for a completed Focus Rush session.

    XP formula:
    - Base: score / 10 (per 10 points = 1 XP)
    - Accuracy bonus: floor(accuracy_percent / 5) capped at 10
    - Combo bonus: best_combo // 2 capped at 5
    - Round completion: 5 * rounds_completed capped at 25
    - Difficulty multiplier: 1.0 for level_1, 1.2 for level_2, 1.4 for level_3, etc.
    """
    base_xp = score // 10
    accuracy_bonus = min(10, int(accuracy_percent // 5))
    combo_bonus = min(5, best_combo // 2)
    round_bonus = min(25, 5 * rounds_completed)

    # Difficulty multiplier
    level_multipliers = {
        "level_1": 1.0,
        "level_2": 1.2,
        "level_3": 1.4,
        "level_4": 1.6,
        "level_5": 1.8,
        "level_6": 2.0,
    }
    multiplier = level_multipliers.get(level, 1.0)

    total = int((base_xp + accuracy_bonus + combo_bonus + round_bonus) * multiplier)
    return max(1, total)  # at least 1 XP for playing


# ---------------------------------------------------------------------------
# Shared target for multiplayer (like perfect_second.match_target_ms)
# ---------------------------------------------------------------------------

def focus_rush_shared_target_ms(match_id: str, difficulty: str) -> int:
    """Deterministic shared target for a multiplayer match.

    Same as perfect_second.match_target_ms: every seat in one match
    resolves the same target without coordination races.
    """
    import hashlib
    digest = hashlib.sha256(f"focus_rush:{match_id}:{difficulty}".encode("ascii")).digest()
    index = int.from_bytes(digest[:4], "big") % 6  # 6 difficulty levels
    return index + 1  # level_1 through level_6
