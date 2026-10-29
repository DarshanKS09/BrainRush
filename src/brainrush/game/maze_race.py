"""Maze Race: pure game rules + procedural maze generation (no Telegram, no DB).

Gameplay: the player navigates a top-down maze from start to exit. Movement is
automatic through straight corridors; at junctions, turns, and dead ends the
player chooses the next valid direction. Wrong turns and backtracking consume
time. The server generates the maze, enforces movement rules, and scores the
completed run.

Maze representation:
  - Grid of cells (rows x cols). Each cell has walls on N/E/S/W sides.
  - Cell (r, c) is indexed as r * cols + c.
  - Wall bitmask: 1=N, 2=E, 4=S, 8=W.
  - Start is top-left (0, 0); exit is bottom-right (rows-1, cols-1).
  - Generation: randomized depth-first search with a configurable
    "branching" pass that carves extra passages to create alternative routes
    and misleading dead ends.

Difficulty parameters:
  - Easy:   9x9 grid, low branching, short solution.
  - Medium: 13x13 grid, moderate branching, more branches/dead ends.
  - Hard:   17x17 grid, high branching, many branches and dead ends.

XP rule (applied only on completion; abandoned games award nothing):
  - Base completion XP scales with difficulty and solution length.
  - Time efficiency bonus: faster than par time earns extra XP.
  - Path efficiency: fewer moves than the solution length earns bonus.
  - Minimum participation XP for finishing.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any

GAME_TYPE = "maze_race"

# Wall bitmasks per cardinal direction.
WALL_N = 1
WALL_E = 2
WALL_S = 4
WALL_W = 8

# Opposite wall for each direction.
OPPOSITE = {WALL_N: WALL_S, WALL_S: WALL_N, WALL_E: WALL_W, WALL_W: WALL_E}

# Direction vectors: (dr, dc, wall_bit).
DIRECTIONS = [
    (-1, 0, WALL_N),  # North / Up
    (0, 1, WALL_E),   # East / Right
    (1, 0, WALL_S),   # South / Down
    (0, -1, WALL_W),  # West / Left
]

DIRECTION_NAMES = {WALL_N: "up", WALL_E: "right", WALL_S: "down", WALL_W: "left"}
DIRECTION_OPPOSITE_NAME = {"up": "down", "down": "up", "left": "right", "right": "left"}


@dataclass(frozen=True)
class MazeConfig:
    rows: int
    cols: int
    # Extra passages carved beyond the DFS spanning tree (0 = perfect maze,
    # higher = more loops / alternative routes / dead ends).
    branching: int
    # Par time in seconds for the difficulty (used for time-efficiency XP).
    par_time_s: int
    # Base XP for completing the maze.
    base_xp: int
    # Max time-efficiency bonus XP.
    time_bonus_xp: int
    # Max path-efficiency bonus XP.
    path_bonus_xp: int


MAZE_DIFFICULTIES: dict[str, MazeConfig] = {
    "easy": MazeConfig(
        rows=9, cols=9, branching=2, par_time_s=60,
        base_xp=40, time_bonus_xp=20, path_bonus_xp=10,
    ),
    "medium": MazeConfig(
        rows=13, cols=13, branching=6, par_time_s=120,
        base_xp=70, time_bonus_xp=35, path_bonus_xp=20,
    ),
    "hard": MazeConfig(
        rows=17, cols=17, branching=12, par_time_s=200,
        base_xp=100, time_bonus_xp=50, path_bonus_xp=30,
    ),
}


class InvalidMoveError(ValueError):
    """Requested direction is not available from the current cell."""


def _rng_for(config: MazeConfig, rng=None) -> random.Random:
    return rng if rng is not None else random


def generate_maze(config: MazeConfig, rng=None) -> list[int]:
    """Generate a perfect maze using randomized DFS, then add branching.

    Returns a flat list of wall bitmasks, one per cell.
    Every cell is reachable; the exit is always reachable from the start.
    """
    source = _rng_for(config, rng)
    rows, cols = config.rows, config.cols
    walls = [WALL_N | WALL_E | WALL_S | WALL_W] * (rows * cols)
    visited = [[False] * cols for _ in range(rows)]

    def carve(r: int, c: int) -> None:
        visited[r][c] = True
        dirs = list(DIRECTIONS)
        source.shuffle(dirs)
        for dr, dc, bit in dirs:
            nr, nc = r + dr, c + dc
            if 0 <= nr < rows and 0 <= nc < cols and not visited[nr][nc]:
                walls[r * cols + c] &= ~bit
                walls[nr * cols + nc] &= ~OPPOSITE[bit]
                carve(nr, nc)

    carve(0, 0)

    # Branching pass: carve extra passages from random visited cells to
    # create loops and alternative routes. Bounded so the maze stays fair.
    for _ in range(config.branching):
        r = source.randrange(rows)
        c = source.randrange(cols)
        dirs = list(DIRECTIONS)
        source.shuffle(dirs)
        for dr, dc, bit in dirs:
            nr, nc = r + dr, c + dc
            if 0 <= nr < rows and 0 <= nc < cols:
                cell_bit = walls[r * cols + c]
                neighbor_bit = walls[nr * cols + nc]
                # Only carve if both cells still have the wall between them
                # and the neighbor isn't already fully open on that side.
                if cell_bit & bit and neighbor_bit & OPPOSITE[bit]:
                    walls[r * cols + c] &= ~bit
                    walls[nr * cols + nc] &= ~OPPOSITE[bit]
                    break

    # Guarantee start has at least one exit and exit has at least one entrance.
    start = walls[0]
    if start & WALL_S:
        walls[0] &= ~WALL_S
        walls[cols] &= ~WALL_N
    elif start & WALL_E:
        walls[0] &= ~WALL_E
        walls[1] &= ~WALL_W

    exit_idx = (rows - 1) * cols + (cols - 1)
    exit_cell = walls[exit_idx]
    if exit_cell & WALL_N:
        walls[exit_idx] &= ~WALL_N
        walls[exit_idx - cols] &= ~WALL_S
    elif exit_cell & WALL_W:
        walls[exit_idx] &= ~WALL_W
        walls[exit_idx - 1] &= ~WALL_E

    return walls


def solve_maze(walls: list[int], config: MazeConfig) -> list[tuple[int, int]]:
    """Return the shortest path from start to exit as a list of (r, c) cells.

    BFS guarantees the shortest route in an unweighted grid. Used to compute
    par time, path-efficiency bonus, and to validate solvability.
    """
    from collections import deque

    rows, cols = config.rows, config.cols
    start = (0, 0)
    exit_cell = (rows - 1, cols - 1)
    queue = deque([start])
    parent: dict[tuple[int, int], tuple[int, int] | None] = {start: None}

    while queue:
        r, c = queue.popleft()
        if (r, c) == exit_cell:
            break
        cell_walls = walls[r * cols + c]
        for dr, dc, bit in DIRECTIONS:
            if cell_walls & bit:
                continue
            nr, nc = r + dr, c + dc
            if 0 <= nr < rows and 0 <= nc < cols and (nr, nc) not in parent:
                parent[(nr, nc)] = (r, c)
                queue.append((nr, nc))

    if exit_cell not in parent:
        return []  # unsolvable (should never happen with valid generation)

    path: list[tuple[int, int]] = []
    cur: tuple[int, int] | None = exit_cell
    while cur is not None:
        path.append(cur)
        cur = parent[cur]
    path.reverse()
    return path


def valid_directions(
    walls: list[int], config: MazeConfig, r: int, c: int
) -> list[str]:
    """Return movement directions available from cell (r, c)."""
    rows, cols = config.rows, config.cols
    cell_walls = walls[r * cols + c]
    out: list[str] = []
    for dr, dc, bit in DIRECTIONS:
        nr, nc = r + dr, c + dc
        if 0 <= nr < rows and 0 <= nc < cols and not (cell_walls & bit):
            out.append(DIRECTION_NAMES[bit])
    return out


def move_player(
    walls: list[int], config: MazeConfig, r: int, c: int, direction: str
) -> tuple[int, int, bool]:
    """Attempt to move the player in `direction` from (r, c).

    Returns (new_r, new_c, moved). `moved` is False if the direction is
    invalid (wall or out of bounds). Movement advances exactly one cell per
    call; straight-corridor continuation is handled by the caller repeatedly
    calling this until a junction/dead end is reached.
    """
    bit_for = {"up": WALL_N, "right": WALL_E, "down": WALL_S, "left": WALL_W}
    delta = {"up": (-1, 0), "right": (0, 1), "down": (1, 0), "left": (0, -1)}
    bit = bit_for.get(direction)
    if bit is None:
        raise InvalidMoveError(f"unknown direction: {direction}")
    cell_walls = walls[r * config.cols + c]
    if cell_walls & bit:
        raise InvalidMoveError("wall blocks that direction")
    dr, dc = delta[direction]
    nr, nc = r + dr, c + dc
    if not (0 <= nr < config.rows and 0 <= nc < config.cols):
        raise InvalidMoveError("cannot move outside the maze")
    return nr, nc, True


def xp_for_completion(
    *,
    elapsed_ms: int,
    moves_used: int,
    solution_length: int,
    config: MazeConfig,
) -> dict[str, int]:
    """Compute XP for a completed maze run.

    - base_xp: guaranteed for finishing.
    - time_bonus: scaled by how far under par_time the player finished.
    - path_bonus: scaled by how few moves vs. the optimal solution length.
    """
    elapsed_s = max(0, elapsed_ms / 1000.0)
    par_s = max(1, config.par_time_s)

    # Time efficiency: linear falloff from 1.0 at 0s to 0.0 at par_time.
    time_ratio = max(0.0, min(1.0, 1.0 - elapsed_s / par_s))
    time_bonus = int(config.time_bonus_xp * time_ratio)

    # Path efficiency: fewer moves than optimal = bonus.
    optimal = max(1, solution_length - 1)  # cells - 1 = moves
    if moves_used <= optimal:
        path_bonus = config.path_bonus_xp
    else:
        # Fall off linearly as moves exceed optimal by up to 2x.
        ratio = max(0.0, 1.0 - (moves_used - optimal) / max(1, optimal))
        path_bonus = int(config.path_bonus_xp * ratio)

    total = config.base_xp + time_bonus + path_bonus
    return {
        "base": config.base_xp,
        "time_bonus": time_bonus,
        "path_bonus": path_bonus,
        "total": total,
    }


def serialize_maze(walls: list[int], config: MazeConfig) -> dict[str, Any]:
    """Convert wall bitmasks into a JSON-friendly maze definition."""
    cells = []
    for r in range(config.rows):
        for c in range(config.cols):
            cell_walls = walls[r * config.cols + c]
            cells.append(
                {
                    "r": r,
                    "c": c,
                    "walls": {
                        "up": bool(cell_walls & WALL_N),
                        "right": bool(cell_walls & WALL_E),
                        "down": bool(cell_walls & WALL_S),
                        "left": bool(cell_walls & WALL_W),
                    },
                }
            )
    return {
        "rows": config.rows,
        "cols": config.cols,
        "start": [0, 0],
        "exit": [config.rows - 1, config.cols - 1],
        "cells": cells,
    }


def deserialize_maze(data: dict[str, Any]) -> list[int]:
    """Rebuild wall bitmasks from a serialized maze definition."""
    rows = data["rows"]
    cols = data["cols"]
    walls = [0] * (rows * cols)
    for cell in data["cells"]:
        r, c = cell["r"], cell["c"]
        bit = 0
        if cell["walls"].get("up"):
            bit |= WALL_N
        if cell["walls"].get("right"):
            bit |= WALL_E
        if cell["walls"].get("down"):
            bit |= WALL_S
        if cell["walls"].get("left"):
            bit |= WALL_W
        walls[r * cols + c] = bit
    return walls
