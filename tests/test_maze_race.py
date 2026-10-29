"""Maze Race game logic tests: maze generation, solvability, movement, XP."""
import pytest

from brainrush.game.maze_race import (
    GAME_TYPE,
    generate_maze,
    solve_maze,
    valid_directions,
    move_player,
    InvalidMoveError,
    xp_for_completion,
    serialize_maze,
    deserialize_maze,
    MAZE_DIFFICULTIES,
    MazeConfig,
    WALL_N, WALL_E, WALL_S, WALL_W,
)


def test_maze_generation_easy():
    cfg = MAZE_DIFFICULTIES["easy"]
    walls = generate_maze(cfg)
    assert len(walls) == cfg.rows * cfg.cols
    # Every cell has at least one opening (no isolated cells).
    for r in range(cfg.rows):
        for c in range(cfg.cols):
            cell = walls[r * cfg.cols + c]
            # Start and exit have at least one wall removed; interior cells too.
            open_dirs = sum(1 for bit in (WALL_N, WALL_E, WALL_S, WALL_W) if not (cell & bit))
            assert open_dirs >= 1, f"cell ({r},{c}) is fully walled"


def test_maze_generation_medium():
    cfg = MAZE_DIFFICULTIES["medium"]
    walls = generate_maze(cfg)
    assert len(walls) == cfg.rows * cfg.cols


def test_maze_generation_hard():
    cfg = MAZE_DIFFICULTIES["hard"]
    walls = generate_maze(cfg)
    assert len(walls) == cfg.rows * cfg.cols


def test_maze_is_solvable_all_difficulties():
    for diff, cfg in MAZE_DIFFICULTIES.items():
        walls = generate_maze(cfg)
        path = solve_maze(walls, cfg)
        assert path, f"{diff} maze is unsolvable"
        assert path[0] == (0, 0), f"{diff} path doesn't start at (0,0)"
        assert path[-1] == (cfg.rows - 1, cfg.cols - 1), f"{diff} path doesn't reach exit"
        # Path steps are adjacent.
        for i in range(len(path) - 1):
            r1, c1 = path[i]
            r2, c2 = path[i + 1]
            assert abs(r1 - r2) + abs(c1 - c2) == 1, f"{diff} path has non-adjacent step"


def test_maze_difficulty_complexity():
    """Hard mazes should be larger and more branched than easy mazes."""
    easy_walls = generate_maze(MAZE_DIFFICULTIES["easy"])
    hard_walls = generate_maze(MAZE_DIFFICULTIES["hard"])
    easy_path = solve_maze(easy_walls, MAZE_DIFFICULTIES["easy"])
    hard_path = solve_maze(hard_walls, MAZE_DIFFICULTIES["hard"])
    assert len(hard_path) > len(easy_path), "hard maze solution should be longer"
    assert MAZE_DIFFICULTIES["hard"].rows > MAZE_DIFFICULTIES["easy"].rows
    assert MAZE_DIFFICULTIES["hard"].branching > MAZE_DIFFICULTIES["easy"].branching


def test_valid_directions_at_start():
    cfg = MAZE_DIFFICULTIES["easy"]
    walls = generate_maze(cfg)
    # Start cell (0,0) should have at least one valid direction.
    dirs = valid_directions(walls, cfg, 0, 0)
    assert len(dirs) >= 1
    assert all(d in ("up", "right", "down", "left") for d in dirs)


def test_valid_directions_respect_walls():
    # Build a tiny maze: 1x2, start at (0,0), exit at (0,1), no wall between.
    cfg = MazeConfig(rows=1, cols=2, branching=0, par_time_s=10, base_xp=10, time_bonus_xp=5, path_bonus_xp=5)
    walls = [WALL_N | WALL_E | WALL_S | WALL_W, WALL_N | WALL_E | WALL_S | WALL_W]
    # Carve between (0,0) and (0,1): remove E from (0,0), W from (0,1).
    walls[0] &= ~WALL_E
    walls[1] &= ~WALL_W
    dirs = valid_directions(walls, cfg, 0, 0)
    assert "right" in dirs
    assert "left" not in dirs  # out of bounds
    assert "up" not in dirs  # out of bounds
    assert "down" not in dirs  # out of bounds


def test_move_player_valid():
    cfg = MazeConfig(rows=1, cols=2, branching=0, par_time_s=10, base_xp=10, time_bonus_xp=5, path_bonus_xp=5)
    walls = [WALL_N | WALL_S | WALL_W, WALL_N | WALL_S | WALL_E]  # open between them
    walls[0] &= ~WALL_E
    walls[1] &= ~WALL_W
    nr, nc, moved = move_player(walls, cfg, 0, 0, "right")
    assert moved
    assert (nr, nc) == (0, 1)


def test_move_player_blocked_by_wall():
    cfg = MazeConfig(rows=1, cols=2, branching=0, par_time_s=10, base_xp=10, time_bonus_xp=5, path_bonus_xp=5)
    walls = [WALL_N | WALL_E | WALL_S | WALL_W, WALL_N | WALL_E | WALL_S | WALL_W]
    with pytest.raises(InvalidMoveError):
        move_player(walls, cfg, 0, 0, "right")


def test_move_player_out_of_bounds():
    cfg = MazeConfig(rows=1, cols=2, branching=0, par_time_s=10, base_xp=10, time_bonus_xp=5, path_bonus_xp=5)
    walls = [0, 0]
    with pytest.raises(InvalidMoveError):
        move_player(walls, cfg, 0, 0, "left")


def test_xp_for_completion():
    cfg = MAZE_DIFFICULTIES["easy"]
    # Fast completion, optimal path.
    result = xp_for_completion(
        elapsed_ms=1000, moves_used=5, solution_length=6, config=cfg,
    )
    assert result["base"] == cfg.base_xp
    assert result["total"] >= cfg.base_xp
    assert result["time_bonus"] > 0  # well under par time

    # Very slow completion: no time bonus.
    result2 = xp_for_completion(
        elapsed_ms=cfg.par_time_s * 1000 * 2, moves_used=5, solution_length=6, config=cfg,
    )
    assert result2["time_bonus"] == 0

    # Many moves: no path bonus.
    result3 = xp_for_completion(
        elapsed_ms=1000, moves_used=100, solution_length=6, config=cfg,
    )
    assert result3["path_bonus"] == 0


def test_serialize_deserialize_maze():
    cfg = MAZE_DIFFICULTIES["medium"]
    walls = generate_maze(cfg)
    data = serialize_maze(walls, cfg)
    assert data["rows"] == cfg.rows
    assert data["cols"] == cfg.cols
    assert len(data["cells"]) == cfg.rows * cfg.cols
    restored = deserialize_maze(data)
    assert restored == walls


def test_game_type_constant():
    assert GAME_TYPE == "maze_race"
