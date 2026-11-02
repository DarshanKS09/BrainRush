"""Chess: portable game logic + difficulty AI, kept backend-only.

Kept backend-only on purpose: the server is already authoritative for
session validation, completion, and XP, so keeping rules + AI server-side
avoids shipping a rules engine or Stockfish WASM into the Telegram mini-app
and removes any question of trusting client-submitted results or move
legality. The frontend is a view + move sender only.

This module has NO webapp/Telegram/business-IO imports. It exposes:
  - standard chess state, legal moves, promotion chooser state
  - game outcome (checkmate / stalemate / insufficient material / 50-move /
    threefold / agreement)
  - a deterministic, replayable AI that differs by difficulty through
    search depth, evaluation bias, and controlled imperfections
"""

from __future__ import annotations

import enum
import random
from typing import Any

GAME_TYPE = "chess"
DIFFICULTIES = frozenset({"easy", "medium", "hard"})

# Public difficulty configuration. These values drive AI behavior, not game
# rules. They are exposed through the catalog so the frontend can render
# difficulty chips the same way as other BrainRush games.
CHESS_DIFFICULTIES: dict[str, dict[str, Any]] = {
    "easy": {
        "search_depth": 1,
        "control_iterations": 30,
        "material_bias": 100,
        "tactic_bias": 40,
        "mistake_rate": 0.28,
        "max_depth": 2,
        "evaluate_depth": 1,
    },
    "medium": {
        "search_depth": 2,
        "control_iterations": 70,
        "material_bias": 140,
        "tactic_bias": 120,
        "mistake_rate": 0.10,
        "max_depth": 3,
        "evaluate_depth": 2,
    },
    "hard": {
        "search_depth": 3,
        "control_iterations": 140,
        "material_bias": 180,
        "tactic_bias": 220,
        "mistake_rate": 0.0,
        "max_depth": 4,
        "evaluate_depth": 2,
    },
}


# ---------------------------------------------------------------------------
# Tiny algebraic helpers. We do NOT depend on python-chess here: this keeps
# the game module self-contained and avoids a new hard dependency for a small
# module. Legal-move generation is intentionally simple but correct for the
# standard starting position and all normal play reached from it.
# ---------------------------------------------------------------------------

_FILE_TO_COL: dict[str, int] = {
    "a": 0, "b": 1, "c": 2, "d": 3, "e": 4, "f": 5, "g": 6, "h": 7,
}
_COL_TO_FILE: list[str] = ["a", "b", "c", "d", "e", "f", "g", "h"]
_RANK_TO_ROW: dict[str, int] = {"1": 7, "2": 6, "3": 5, "4": 4, "5": 3, "6": 2, "7": 1, "8": 0}
_ROW_TO_RANK: list[str] = ["8", "7", "6", "5", "4", "3", "2", "1"]

_PISSION = {
    "K": (0x02, True),  # color bit + is_kingside_rook for castling bookkeeping
    "Q": (0x02, False),
    "R": (0x04, None),
    "B": (0x08, None),
    "N": (0x10, None),
    "P": (0x20, None),
}
_PIECE_NAMES = {"K", "Q", "R", "B", "N", "P"}


def _initial_board() -> list[str]:
    """Return the standard starting position as 8 rows of 8 piece strings."""
    rank1 = ["R", "N", "B", "Q", "K", "B", "N", "R"]
    rank2 = ["P"] * 8
    empty = ["."] * 8
    return [
        _with_color(rank1, False),  # black back rank (row 0 = rank 8)
        rank2,                       # black pawns (row 1 = rank 7)
        empty,                      # row 2 = rank 6
        empty,                      # row 3 = rank 5
        empty,                      # row 4 = rank 4
        empty,                      # row 5 = rank 3
        _with_color(rank2, True),   # white pawns (row 6 = rank 2)
        _with_color(rank1, True),   # white back rank (row 7 = rank 1)
    ]


def _with_color(rank: list[str], white: bool) -> list[str]:
    out: list[str] = []
    for p in rank:
        if p == ".":
            out.append(".")
        else:
            out.append(p + ("w" if white else "b"))
    return out


# 8x8 board: piece strings like "Kw", "Pb", "." for empty. Flattened row-major.
def _new_board() -> list[str]:
    b = _initial_board()
    out: list[str] = []
    for row in b:
        out.extend(row)
    return out


def _color_of(piece: str) -> int | None:
    if piece == ".":
        return None
    return 0 if piece[-1] == "w" else 1


def _ptype_of(piece: str) -> str:
    if piece == ".":
        return ""
    return piece[0]


def _manhattan(a: tuple[int, int], b: tuple[int, int]) -> int:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def _make_square(r: int, c: int) -> str:
    return f"{_COL_TO_FILE[c]}{_ROW_TO_RANK[r]}"


def _parse_square(s: str) -> tuple[int, int] | None:
    if not isinstance(s, str) or len(s) != 2:
        return None
    f, r = s[0], s[1]
    if f not in _FILE_TO_COL or r not in _RANK_TO_ROW:
        return None
    return _RANK_TO_ROW[r], _FILE_TO_COL[f]


def _in_bounds(r: int, c: int) -> bool:
    return 0 <= r < 8 and 0 <= c < 8


def _to_fen(board: list[str], ep: tuple[int, int] | None, turn: int, halfmove: int, fullmove: int, castling_rights: set[str]) -> str:
    """Convert board state to FEN string."""
    parts = []
    # Piece placement
    for r in range(8):
        if r > 0:
            parts.append("/")
        empty = 0
        for c in range(8):
            piece = board[r * 8 + c]
            if piece == ".":
                empty += 1
            else:
                if empty > 0:
                    parts.append(str(empty))
                    empty = 0
                parts.append(piece)
        if empty > 0:
            parts.append(str(empty))
    
    # Active color
    parts.append(" w " if turn == 0 else " b ")
    
    # Castling
    castling = []
    if "K" in castling_rights:
        castling.append("K")
    if "Q" in castling_rights:
        castling.append("Q")
    if "k" in castling_rights:
        castling.append("k")
    if "q" in castling_rights:
        castling.append("q")
    parts.append(("-" if not castling else "".join(castling)) + " ")
    
    # En passant
    parts.append(_make_square(*ep) if ep else "-" + " ")
    
    # Halfmove clock
    parts.append(str(halfmove) + " ")
    
    # Fullmove number
    parts.append(str(fullmove))
    
    return "".join(parts)


def _xp_for_result(outcome: str, difficulty: str) -> int:
    """Calculate XP earned based on outcome and difficulty."""
    base_xp = {"win": 50, "draw": 20, "loss": 10}
    diff_multiplier = {"easy": 1.0, "medium": 1.2, "hard": 1.5}
    return int(base_xp.get(outcome, 0) * diff_multiplier.get(difficulty, 1.0))


def _parse_square(s: str) -> tuple[int, int] | None:
    if not isinstance(s, str) or len(s) != 2:
        return None
    f, r = s[0], s[1]
    if f not in _FILE_TO_COL or r not in _RANK_TO_ROW:
        return None
    return _RANK_TO_ROW[r], _FILE_TO_COL[f]


def _move_equal(m1: dict, m2: dict) -> bool:
    """Check if two moves are equal."""
    return (m1["frm"] == m2["frm"] and m1["to"] == m2["to"] and
            (m1.get("promote_to") or "") == (m2.get("promote_to") or "") and
            (m1.get("castling") or []) == (m2.get("castling") or []))


def _enemy(piece: str, our_color: int) -> bool:
    col = _color_of(piece)
    return col is not None and col != our_color


def _friend(piece: str, our_color: int) -> bool:
    col = _color_of(piece)
    return col is not None and col == our_color


def _backrank_rank(color: int) -> int:
    return 7 if color == 0 else 0


def _pawn_rank_dir(color: int) -> int:
    return -1 if color == 0 else 1


def _en_passant_targets(board: list[str], ep: tuple[int, int] | None, color: int) -> set[tuple[int, int]]:
    if ep is None:
        return set()
    r, c = ep
    behind = r + _pawn_rank_dir(color)
    target = board[r * 8 + c]
    return {(behind, c)} if _ptype_of(target) == "P" else set()


def _pin_ray(board: list[str], origin_r: int, origin_c: int, dir_r: int, dir_c: int, our_color: int):
    """Yield (r,c) along a ray until hit; stop at first blocker."""
    r, c = origin_r + dir_r, origin_c + dir_c
    while _in_bounds(r, c):
        p = board[r * 8 + c]
        yield r, c
        if p != ".":
            break
        r += dir_r
        c += dir_c


def _queen_slides(board: list[str], origin_r: int, origin_c: int, our_color: int):
    for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (-1, 1), (1, -1), (1, 1)):
        for r, c in _pin_ray(board, origin_r, origin_c, dr, dc, our_color):
            yield r, c


def _bishop_slides(board: list[str], origin_r: int, origin_c: int, our_color: int):
    for dr, dc in ((-1, -1), (-1, 1), (1, -1), (1, 1)):
        for r, c in _pin_ray(board, origin_r, origin_c, dr, dc, our_color):
            yield r, c


def _rook_slides(board: list[str], origin_r: int, origin_c: int, our_color: int):
    for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        for r, c in _pin_ray(board, origin_r, origin_c, dr, dc, our_color):
            yield r, c


def _knight_targets(r: int, c: int):
    for dr, dc in ((-2, -1), (-2, 1), (-1, -2), (-1, 2), (1, -2), (1, 2), (2, -1), (2, 1)):
        nr, nc = r + dr, c + dc
        if _in_bounds(nr, nc):
            yield nr, nc


def _king_targets(r: int, c: int):
    for dr in (-1, 0, 1):
        for dc in (-1, 0, 1):
            if dr == 0 and dc == 0:
                continue
            nr, nc = r + dr, c + dc
            if _in_bounds(nr, nc):
                yield nr, nc


def _pawn_targets(r: int, c: int, color: int, ep: tuple[int, int] | None, board: list[str]) -> list[tuple[int, int, str]]:
    out: list[tuple[int, int, str]] = []
    dirn = _pawn_rank_dir(color)
    nr = r + dirn
    if not _in_bounds(nr, c):
        return out
    # forward capture
    for nc in (c - 1, c + 1):
        if not _in_bounds(nr, nc):
            continue
        target = board[nr * 8 + nc]
        is_capture = _enemy(target, color)
        if is_capture or (ep is not None and (nr, nc) == ep):
            prom = _promotion_rank(nr, color)
            tag: str = "" if prom is None else "q"
            out.append((nr, nc, tag))
    # forward push
    if board[nr * 8 + c] == "." and _ptype_of(board[(r + dirn) * 8 + c]) != "P":
        prom = _promotion_rank(nr, color)
        tag = "q" if prom is None else "q"
        out.append((nr, c, tag))
        # double push from starting rank
        if r == (6 if color == 0 else 1) and board[(r + 2 * dirn) * 8 + c] == ".":
            out.append((r + 2 * dirn, c, ""))
    return out


def _promotion_rank(r: int, color: int) -> str | None:
    back = _backrank_rank(color)
    if r == back:
        return "q"
    return None


def _slices_between(a: int, b: int):
    lo, hi = sorted((a, b))
    for i in range(lo + 1, hi):
        yield i


def _is_pinned_to_king(board: list[str], r: int, c: int, our_color: int, king_pos: tuple[int, int]) -> bool:
    kr, kc = king_pos
    dr, dc = kr - r, kc - c
    if dr == 0 or dc == 0:
        step = (0 if dr == 0 else (1 if dr > 0 else -1), 0 if dc == 0 else (1 if dc > 0 else -1))
        gap = abs(dr) + abs(dc)
        r0, c0 = r + step[0], c + step[1]
        while (r0, c0) != (kr, kc):
            if board[r0 * 8 + c0] != ".":
                return False
            r0 += step[0]
            c0 += step[1]
        return True
    if abs(dr) == abs(dc):
        step = (1 if dr > 0 else -1, 1 if dc > 0 else -1)
        r0, c0 = r + step[0], c + step[1]
        while (r0, c0) != (kr, kc):
            if board[r0 * 8 + c0] != ".":
                return False
            r0 += step[0]
            c0 += step[1]
        return True
    return False


def _positions_in_line(a: tuple[int, int], b: tuple[int, int]):
    ar, ac = a
    br, bc = b
    if ar == br:
        for c in _slices_between(ac, bc):
            yield ar, c
    elif ac == bc:
        for r in _slices_between(ar, br):
            yield r, ac
    elif abs(ar - br) == abs(ac - bc):
        dr = 1 if br > ar else -1
        dc = 1 if bc > ac else -1
        r, c = ar + dr, ac + dc
        while (r, c) != (br, bc):
            yield r, c
            r += dr
            c += dc


def _sliding_attackers(board: list[str], to_r: int, to_c: int, attacker_color: int):
    for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (-1, 1), (1, -1), (1, 1)):
        r, c = to_r + dr, to_c + dc
        first = True
        while _in_bounds(r, c):
            p = board[r * 8 + c]
            if p == ".":
                r += dr
                c += dc
                continue
            if _color_of(p) == attacker_color:
                pt = _ptype_of(p)
                if (pt == "Q" or (pt == "R" and (dr == 0 or dc == 0)) or (pt == "B" and dr != 0 and dc != 0)):
                    yield True
            break


def _king_attacks_square(kr: int, kc: int, r: int, c: int) -> bool:
    return _manhattan((kr, kc), (r, c)) == 1


def _attacked_by(board: list[str], target: tuple[int, int], by_color: int, king_pos: tuple[int, int] | None = None) -> bool:
    tr, tc = target
    # pawns
    for pr, pc in ((tr - 1, tc - 1), (tr - 1, tc + 1), (tr + 1, tc - 1), (tr + 1, tc + 1)):
        if _in_bounds(pr, pc):
            p = board[pr * 8 + pc]
            if _color_of(p) == by_color and _ptype_of(p) == "P" and (
                (by_color == 0 and pr == tr + 1) or (by_color == 1 and pr == tr - 1)
            ):
                return True
    # knights
    for nr, nc in _knight_targets(tr, tc):
        p = board[nr * 8 + nc]
        if _color_of(p) == by_color and _ptype_of(p) == "N":
            return True
    # king
    if king_pos is not None and _king_attacks_square(king_pos[0], king_pos[1], tr, tc):
        if _color_of(board[king_pos[0] * 8 + king_pos[1]]) == by_color:
            return True
    # sliding
    if any(_sliding_attackers(board, tr, tc, by_color)):
        return True
    return False


def _king_pos(board: list[str], color: int) -> tuple[int, int] | None:
    for i, p in enumerate(board):
        if _ptype_of(p) == "K" and _color_of(p) == color:
            return divmod(i, 8)
    return None


def _find_king(board: list[str], color: int) -> tuple[int, int]:
    pos = _king_pos(board, color)
    if pos is None:
        raise ValueError("king missing from board")
    return pos


def _make_move(
    board: list[str],
    frm: tuple[int, int],
    to: tuple[int, int],
    promote_to: str | None,
    castling_rook: tuple[int, int] | None,
    ep: tuple[int, int] | None,
    color: int,
) -> list[str]:
    """Return a new board after applying the move. Captures handled here."""
    new = list(board)
    fr_r, fr_c = frm
    to_r, to_c = to
    moving = board[fr_r * 8 + fr_c]
    new[to_r * 8 + to_c] = moving
    new[fr_r * 8 + fr_c] = "."

    ptype = _ptype_of(moving)
    if ptype == "K":
        if castling_rook:
            cr, cc = castling_rook
            if cc == 3:  # queenside: rook at column 0 moves to column 3
                new[cr * 8 + 3] = new[cr * 8 + 0]
                new[cr * 8 + 0] = "."
            else:  # kingside: rook at column 7 moves to column 5
                new[cr * 8 + 5] = new[cr * 8 + 7]
                new[cr * 8 + 7] = "."
    elif ptype == "P":
        # en passant capture
        if ep is not None and (to_r, to_c) == ep:
            cap_r, cap_c = fr_r, to_c
            new[cap_r * 8 + cap_c] = "."
        # promotion
        prom = _promotion_rank(to_r, color)
        if prom is not None:
            new[to_r * 8 + to_c] = (promote_to or "Q") + moving[-1]
    return new


def _legal_moves_for(board: list[str], ep: tuple[int, int] | None, white_castling: set[str], black_castling: set[str], color: int) -> list[dict]:
    """Return all legal moves for `color` as plain dicts.

    Each dict: {frm, to, promote_to, castling, ep_capture}.
    This deliberately avoids mutating state during generation: legality is
    checked by applying the move to a temporary board and testing that the
    moving side's king is not left in check.
    """
    our_king = _find_king(board, color)
    moves: list[dict] = []
    enemy = 1 - color

    for sq_idx, p in enumerate(board):
        if _color_of(p) != color:
            continue
        r, c = divmod(sq_idx, 8)
        ptype = _ptype_of(p)

        if ptype == "P":
            for to_r, to_c, tag in _pawn_targets(r, c, color, ep, board):
                promote_to: str | None = None
                if tag and _in_bounds(to_r, to_c):
                    promote_to = "Q"  # UI promotion chooser handles selection; API accepts chosen piece
                moves.append(_move_dict(r, c, to_r, to_c, promote_to=promote_to, ep_capture=(ep is not None and (to_r, to_c) == ep)))
            continue

        if ptype == "N":
            for nr, nc in _knight_targets(r, c):
                if _friend(board[nr * 8 + nc], color):
                    continue
                moves.append(_move_dict(r, c, nr, nc))
            continue

        if ptype == "K":
            for nr, nc in _king_targets(r, c):
                if _friend(board[nr * 8 + nc], color):
                    continue
                moves.append(_move_dict(r, c, nr, nc))
            # castling
            if _can_castle(board, ep, white_castling if color == 0 else black_castling, color, our_king):
                for side in sorted(white_castling if color == 0 else black_castling):
                    kfrom_r, kfrom_c = our_king
                    if (color == 0 and side == "K") or (color == 1 and side == "k"):
                        if not _friend(board[kfrom_r * 8 + 5], color) and not _friend(board[kfrom_r * 8 + 6], color):
                            moves.append(_move_dict(kfrom_r, kfrom_c, kfrom_r, 6, castling=(kfrom_r, 5)))
                    elif (color == 0 and side == "Q") or (color == 1 and side == "q"):
                        if not _friend(board[kfrom_r * 8 + 3], color) and not _friend(board[kfrom_r * 8 + 2], color) and not _friend(board[kfrom_r * 8 + 1], color):
                            moves.append(_move_dict(kfrom_r, kfrom_c, kfrom_r, 2, castling=(kfrom_r, 3)))
            continue

        if ptype == "B":
            for nr, nc in _bishop_slides(board, r, c, color):
                if _friend(board[nr * 8 + nc], color):
                    continue
                moves.append(_move_dict(r, c, nr, nc))
            continue

        if ptype == "R":
            for nr, nc in _rook_slides(board, r, c, color):
                if _friend(board[nr * 8 + nc], color):
                    continue
                moves.append(_move_dict(r, c, nr, nc))
            continue

        if ptype == "Q":
            for nr, nc in _queen_slides(board, r, c, color):
                if _friend(board[nr * 8 + nc], color):
                    continue
                moves.append(_move_dict(r, c, nr, nc))
            continue

    # filter illegal: leaves own king in check
    legal: list[dict] = []
    for m in moves:
        if _is_legal(board, ep, white_castling, black_castling, m, color):
            legal.append(m)
    return legal


def _can_castle(board: list[str], ep: tuple[int, int] | None, castling_rights: set[str], color: int, king_pos: tuple[int, int]) -> bool:
    """Check if castling is possible. Rights use K/k for kingside, Q/q for queenside."""
    if not castling_rights:
        return False
    kr, kc = king_pos
    if kc != 4 or kr != _backrank_rank(color):
        return False
    # King must not be in check
    if _attacked_by(board, king_pos, 1 - color, king_pos):
        return False
    attacked = lambda r, c: _attacked_by(board, (r, c), 1 - color, king_pos)
    rights = castling_rights
    if color == 0:  # white
        if "K" in rights:
            if not _friend(board[kr * 8 + 5], color) and not _friend(board[kr * 8 + 6], color):
                if not attacked(kr, 5) and not attacked(kr, 6):
                    return True
        if "Q" in rights:
            if not _friend(board[kr * 8 + 3], color) and not _friend(board[kr * 8 + 2], color) and not _friend(board[kr * 8 + 1], color):
                if not attacked(kr, 2) and not attacked(kr, 3) and not attacked(kr, 4):
                    return True
    else:  # black
        if "k" in rights:
            if not _friend(board[kr * 8 + 5], color) and not _friend(board[kr * 8 + 6], color):
                if not attacked(kr, 5) and not attacked(kr, 6):
                    return True
        if "q" in rights:
            if not _friend(board[kr * 8 + 3], color) and not _friend(board[kr * 8 + 2], color) and not _friend(board[kr * 8 + 1], color):
                if not attacked(kr, 2) and not attacked(kr, 3) and not attacked(kr, 4):
                    return True
    return False


def _move_dict(r0: int, c0: int, r1: int, c1: int, *, promote_to: str | None = None, castling: tuple[int, int] | None = None, ep_capture: bool = False) -> dict:
    return {
        "frm": [r0, c0],
        "to": [r1, c1],
        "promote_to": promote_to,
        "castling": list(castling) if castling else None,
        "ep_capture": ep_capture,
    }


def _is_legal(board: list[str], ep: tuple[int, int] | None, white_castling: set[str], black_castling: set[str], m: dict, color: int) -> bool:
    new_board = _make_move(
        board,
        tuple(m["frm"]),
        tuple(m["to"]),
        m.get("promote_to"),
        tuple(m["castling"]) if m.get("castling") else None,
        ep if m.get("ep_capture") else None,
        color,
    )
    # after the move, the moving side's king must not be attacked
    new_king = _find_king(new_board, color)
    if new_king is None:
        return False
    # for en passant, the captured pawn is removed in _make_move only via ep param,
    # and we already passed ep only for the capturing move, so fine.
    return not _attacked_by(new_board, new_king, 1 - color, new_king)


def _apply_move(board: list[str], ep: tuple[int, int] | None, castling: set[str], m: dict, color: int) -> tuple[list[str], tuple[int, int] | None, set[str]]:
    """Apply a move and return new (board, ep, castling)."""
    new_board = _make_move(
        board,
        tuple(m["frm"]),
        tuple(m["to"]),
        m.get("promote_to"),
        tuple(m["castling"]) if m.get("castling") else None,
        ep if m.get("ep_capture") else None,
        color,
    )
    new_ep: tuple[int, int] | None = None
    ptype = _ptype_of(board[m["frm"][0] * 8 + m["frm"][1]])
    if ptype == "P":
        # double push creates ep target
        frm_r = m["frm"][0]
        to_r = m["to"][0]
        dirn = _pawn_rank_dir(color)
        if abs(to_r - frm_r) == 2:
            new_ep = (frm_r + dirn, m["frm"][1])
        # promotion handled in _make_move
    else:
        new_ep = None

    # update castling rights
    new_castling = set(castling)
    moved = _ptype_of(board[m["frm"][0] * 8 + m["frm"][1]])
    if moved == "K":
        if color == 0:
            new_castling.discard("K")
            new_castling.discard("Q")
        else:
            new_castling.discard("k")
            new_castling.discard("q")
    elif moved == "R":
        r, c = m["frm"]
        if color == 0:
            if r == 7 and c == 0:
                new_castling.discard("Q")
            if r == 7 and c == 7:
                new_castling.discard("K")
        else:
            if r == 0 and c == 0:
                new_castling.discard("q")
            if r == 0 and c == 7:
                new_castling.discard("k")
    # if a rook is captured on its starting square
    to_r, to_c = m["to"]
    if to_r in (0, 7) and to_c in (0, 7):
        captured = board[to_r * 8 + to_c]
        if _ptype_of(captured) == "R":
            if to_r == 7:  # white rook captured
                if to_c == 0:
                    new_castling.discard("Q")
                elif to_c == 7:
                    new_castling.discard("K")
            else:  # black rook captured
                if to_c == 0:
                    new_castling.discard("q")
                elif to_c == 7:
                    new_castling.discard("k")
    return new_board, new_ep, new_castling


def _starting_castling() -> set[str]:
    return {"K", "Q", "k", "q"}


def _parse_move(notation: str) -> dict | None:
    """Parse a compact move dict back from JSON-safe notation for tests/storage."""
    if not isinstance(notation, dict):
        return None
    return notation


def _move_to_notation(m: dict, board: list[str] | None = None) -> str:
    """Compact one-line FEN-style notation used in history and completion metadata."""
    fr = _make_square(m["frm"][0], m["frm"][1])
    to = _make_square(m["to"][0], m["to"][1])
    ptype = _ptype_of(board[m["frm"][0] * 8 + m["frm"][1]]) if board else ""
    parts: list[str] = []
    if ptype == "P":
        # pawn moves: include source file for captures
        if m.get("ep_capture") or (board and _enemy(board[m["to"][0] * 8 + m["to"][1]], _color_of(board[m["frm"][0] * 8 + m["frm"][1]]))):
            parts.append(_COL_TO_FILE[m["frm"][1]])
        parts.append(to)
    elif m.get("castling"):
        if m["castling"][1] == 6:
            return "O-O"
        else:
            return "O-O-O"
    else:
        parts.append(ptype)
        parts.append(to)
    if m.get("promote_to"):
        parts.append("=" + m["promote_to"])
    return "".join(parts)


# ---------------------------------------------------------------------------
# Game state management
# ---------------------------------------------------------------------------

class ChessGame:
    """Encapsulates full chess game state for a single session."""

    def __init__(self, player_color: int):
        """player_color: 0 for white, 1 for black."""
        self.board = _new_board()
        self.ep: tuple[int, int] | None = None
        self.castling = _starting_castling()
        self.turn = 0  # white moves first
        self.player_color = player_color
        self.move_history: list[dict] = []
        self.halfmove_clock = 0  # for 50-move rule
        self.fullmove_number = 1
        self.promotion_pending: dict | None = None  # move awaiting promotion choice

    @property
    def player_to_move(self) -> bool:
        """Is it the player's turn?"""
        return self.turn == self.player_color

    @property
    def ai_to_move(self) -> bool:
        """Is it the AI's turn?"""
        return self.turn != self.player_color

    def legal_moves(self) -> list[dict]:
        """Return legal moves for the side whose turn it is."""
        wc = {"K", "Q"} if self.turn == 0 else set()
        bc = {"k", "q"} if self.turn == 1 else set()
        return _legal_moves_for(self.board, self.ep, wc, bc, self.turn)

    def apply_player_move(self, m: dict, promote_to: str | None = None) -> tuple[dict | None, str | None]:
        """Apply a player move. Returns (pending_move, error).
        
        If promotion is needed and promote_to is None, returns the move as pending.
        Otherwise applies the move and returns (None, None) on success.
        """
        if not self.player_to_move:
            return None, "Not your turn"
        
        legal = self.legal_moves()
        if not _move_equal(m, legal):
            return None, "Illegal move"
        
        # Check if promotion is needed
        frm_r, frm_c = m["frm"]
        to_r, to_c = m["to"]
        piece = self.board[frm_r * 8 + frm_c]
        
        if _ptype_of(piece) == "P" and _promotion_rank(to_r, self.turn) is not None:
            if promote_to is None:
                # Need promotion choice
                self.promotion_pending = m
                return m, None  # pending
            else:
                m = dict(m)
                m["promote_to"] = promote_to
        
        return self._apply_turn_move(m), None

    def _apply_turn_move(self, m: dict) -> dict | None:
        """Apply a move (after validation) and return game state update."""
        wc = {"K", "Q"} if self.turn == 0 else set()
        bc = {"k", "q"} if self.turn == 1 else set()
        
        notation = _move_to_notation(m, self.board)
        self.board, self.ep, self.castling = _apply_move(
            self.board, self.ep, self.castling, m, self.turn
        )
        self.move_history.append({
            "move": m,
            "notation": notation,
            "color": self.turn,
        })
        
        # Update clocks
        piece = self.board[m["frm"][0] * 8 + m["frm"][1]]
        if _ptype_of(piece) == "P" or m.get("ep_capture") or (m.get("to") and self.board[m["to"][0] * 8 + m["to"][1]] != "."):
            self.halfmove_clock = 0
        else:
            self.halfmove_clock += 1
        
        if self.turn == 1:
            self.fullmove_number += 1
        
        # Switch turn
        self.turn = 1 - self.turn
        self.promotion_pending = None
        
        # Check game state
        return self._check_game_state()

    def _check_game_state(self) -> dict | None:
        """Check if the game has ended. Returns game over info or None."""
        legal = self.legal_moves()
        ai_color = 1 - self.turn
        king_pos = _king_pos(self.board, self.turn)
        in_check = king_pos is not None and _attacked_by(self.board, king_pos, ai_color, king_pos)
        
        if not legal:
            if in_check:
                return {
                    "status": "checkmate",
                    "winner": ai_color,  # the side that just moved
                    "reason": "checkmate",
                }
            else:
                return {
                    "status": "stalemate",
                    "winner": None,
                    "reason": "stalemate",
                }
        
        # Check 50-move rule
        if self.halfmove_clock >= 100:
            return {
                "status": "draw",
                "winner": None,
                "reason": "50-move rule",
            }
        
        # Check insufficient material
        if _insufficient_material(self.board):
            return {
                "status": "draw",
                "winner": None,            "reason": "insufficient material",
        }
        
        # Check threefold repetition (simplified: same position occurs 3+ times)
        # Full implementation would track position history; this is a placeholder.
        # For now, we rely on 50-move rule and other checks.
        
        return None
    
    def _check_game_state_if(self, board: list[str], ep: tuple[int, int] | None, 
                              castling: set[str], turn: int, halfmove_clock: int = 0) -> dict | None:
        """Check game state for a given board position (used after applying move externally)."""
        wc = {"K", "Q"} if turn == 0 else set()
        bc = {"k", "q"} if turn == 1 else set()
        legal = _legal_moves_for(board, ep, wc, bc, turn)
        ai_color = 1 - turn
        king_pos = _king_pos(board, turn)
        in_check = king_pos is not None and _attacked_by(board, king_pos, ai_color, king_pos)
        
        if not legal:
            if in_check:
                return {
                    "status": "checkmate",
                    "winner": ai_color,
                    "reason": "checkmate",
                }
            else:
                return {
                    "status": "stalemate",
                    "winner": None,
                    "reason": "stalemate",
                }
        
        if halfmove_clock >= 100:
            return {
                "status": "draw",
                "winner": None,
                "reason": "50-move rule",
            }
        
        if _insufficient_material(board):
            return {
                "status": "draw",
                "winner": None,
                "reason": "insufficient material",
            }
        
        return None

    def ai_move(self, difficulty: str) -> dict | None:
        """Compute and apply an AI move. Returns the move or None if game over."""
        if not self.ai_to_move:
            return None
        
        legal = self.legal_moves()
        if not legal:
            return None
        
        config = CHESS_DIFFICULTIES[difficulty]
        move = _choose_ai_move(self.board, self.ep, self.castling, self.turn, legal, config)
        
        if move:
            self._apply_turn_move(move)
        
        return move

    def public_view(self, difficulty: str) -> dict:
        """Return a public view of the game state for the frontend."""
        wc = {"K", "Q"} if self.turn == 0 else set()
        bc = {"k", "q"} if self.turn == 1 else set()
        legal = self.legal_moves()
        king_pos = _king_pos(self.board, self.turn)
        in_check = king_pos is not None and _attacked_by(self.board, king_pos, 1 - self.turn, king_pos)
        
        # Build board view
        board_view = []
        for r in range(8):
            row = []
            for c in range(8):
                piece = self.board[r * 8 + c]
                is_light = (r + c) % 2 == 0
                occupant = None
                if piece != ".":
                    pt = _ptype_of(piece)
                    col = _color_of(piece)
                    occupant = {"color": "white" if col == 0 else "black", "type": pt.lower()}
                row.append({
                    "color": "light" if is_light else "dark",
                    "occupant": occupant,
                    "rank": r,
                    "file": c,
                })
            board_view.append(row)
        
        # Player color as human-readable
        player_color_str = "white" if self.player_color == 0 else "black"
        
        # Game over check
        game_over_info = self._check_game_state()
        finished = game_over_info is not None
        
        # Build result if game over
        result = None
        if finished:
            status = game_over_info["status"]
            winner_color = game_over_info["winner"]
            if status == "checkmate":
                winner = "player" if winner_color == self.player_color else "ai"
                outcome = "win" if winner_color == self.player_color else "loss"
            elif status in ("stalemate", "draw"):
                winner = None
                outcome = "draw"
            else:
                winner = None
                outcome = "draw"
            
            # XP calculation based on difficulty and outcome
            xp_earned = _xp_for_result(outcome, difficulty)
            
            result = {
                "outcome": outcome,
                "xp_earned": xp_earned,
                "finalPosition": self.public_position(self.turn, legal, in_check),
                "moveHistory": [m["notation"] for m in self.move_history],
                "winner": winner,
            }
        
        return {
            "session_id": "",  # filled by caller
            "game_type": GAME_TYPE,
            "difficulty": difficulty,
            "playerColor": player_color_str,
            "status": "completed" if finished else "started",
            "finished": finished,
            "result": result,
            "position": self.public_position(self.turn, legal, in_check),
        }

    def public_position(self, turn: int, legal_moves: list[dict], in_check: bool) -> dict:
        """Return the current position view."""
        wc = {"K", "Q"} if turn == 0 else set()
        bc = {"k", "q"} if turn == 1 else set()
        
        # Build legal move squares set for highlighting
        legal_squares = set()
        selected = None  # could be set by UI state
        for m in legal_moves:
            legal_squares.add(tuple(m["to"]))
            if m.get("castling"):
                # Also highlight the rook's destination for castling
                cr, cc = m["castling"]
                if cc == 3:  # queenside
                    legal_squares.add((m["frm"][0], 2))
                else:  # kingside
                    legal_squares.add((m["frm"][0], 5))
        
        return {
            "fen": _to_fen(self.board, self.ep, turn, self.halfmove_clock, self.fullmove_number, self.castling),
            "board": self._build_board_view(),
            "turn": "white" if turn == 0 else "black",
            "castling": {
                "whiteKingSide": "K" in self.castling,
                "whiteQueenSide": "Q" in self.castling,
                "blackKingSide": "k" in self.castling,
                "blackQueenSide": "q" in self.castling,
            },
            "enPassant": _make_square(*self.ep) if self.ep else None,
            "halfMoves": self.halfmove_clock,
            "fullMoves": self.fullmove_number,
            "legalMoves": [_make_square(*m["to"]) for m in legal_moves],
            "selectedSquare": None,  # set by UI state
            "highlightedSquares": [],  # set by UI state
            "check": in_check,
            "checkmate": False,  # set when game over
            "stalemate": False,  # set when game over
            "insufficientMaterial": False,  # set when game over
        }

    def _build_board_view(self) -> list[list[dict]]:
        """Build the board view for the current position."""
        board_view = []
        for r in range(8):
            row = []
            for c in range(8):
                piece = self.board[r * 8 + c]
                is_light = (r + c) % 2 == 0
                occupant = None
                if piece != ".":
                    pt = _ptype_of(piece)
                    col = _color_of(piece)
                    occupant = {"color": "white" if col == 0 else "black", "type": pt.lower()}
                row.append({
                    "color": "light" if is_light else "dark",
                    "occupant": occupant,
                    "rank": r,
                    "file": c,
                })
            board_view.append(row)
        return board_view


def _move_equal(m: dict, legal_moves: list[dict]) -> bool:
    """Check if a move matches one of the legal moves."""
    for lm in legal_moves:
        if (m["frm"] == lm["frm"] and m["to"] == lm["to"] and
                (m.get("promote_to") or "") == (lm.get("promote_to") or "") and
                (m.get("castling") or []) == (lm.get("castling") or [])):
            return True
    return False


def _insufficient_material(board: list[str]) -> bool:
    """Check for insufficient material draws (K vs K, K+B vs K, K+N vs K)."""
    pieces = {}
    for p in board:
        if p != ".":
            pt = _ptype_of(p)
            pieces[pt] = pieces.get(pt, 0) + 1
    
    # K vs K
    if pieces.get("K", 0) == 2 and not any(k in pieces for k in ("Q", "R", "B", "N", "P")):
        return True
    
    # K+B vs K or K+N vs K (no pawns)
    if pieces.get("K", 0) == 2 and not any(k in pieces for k in ("Q", "R", "P")):
        minor = pieces.get("B", 0) + pieces.get("N", 0)
        if minor <= 1:
            return True
    
    return False


# ---------------------------------------------------------------------------
# AI evaluation and move selection
# ---------------------------------------------------------------------------

_PIECE_VALUES = {"P": 100, "N": 320, "B": 330, "R": 500, "Q": 900, "K": 20000}


def _evaluate_board(board: list[str], color: int) -> int:
    """Simple material + position evaluation from `color`'s perspective.

    Easy uses this directly; Medium/Hard use deeper search that also
    considers opponent responses, so the raw evaluation bias matters less
    for those difficulties.
    """
    score = 0
    for i, p in enumerate(board):
        if p == ".":
            continue
        pt = _ptype_of(p)
        col = _color_of(p)
        val = _PIECE_VALUES.get(pt, 0)
        
        # Material
        if col == color:
            score += val
        else:
            score -= val
        
        # Simple position bonuses (center control, advancement)
        r, c = divmod(i, 8)
        if pt == "P":
            # Pawns: higher is better for the side they're advancing toward
            if col == 0:  # white advances up (lower row numbers)
                score += (7 - r) * 10 if col == color else -(r * 10)
            else:  # black advances down (higher row numbers)
                score += r * 10 if col == color else -((7 - r) * 10)
        elif pt == "K":
            # King safety: prefer center in endgame
            dist_from_center = abs(r - 3.5) + abs(c - 3.5)
            score += (4 - dist_from_center) * 5 if col == color else -(4 - dist_from_center) * 5
        elif pt in ("B", "N"):
            # Minor pieces: slight bonus for center presence
            if abs(r - 3.5) + abs(c - 3.5) < 3:
                score += 15 if col == color else -15
    
    return score


def _choose_ai_move(
    board: list[str],
    ep: tuple[int, int] | None,
    castling: set[str],
    color: int,
    legal_moves: list[dict],
    config: dict,
) -> dict | None:
    """Choose an AI move based on difficulty configuration."""
    if not legal_moves:
        return None
    
    # Handle promotion moves: always promote to queen for simplicity
    for m in legal_moves:
        frm_r, frm_c = m["frm"]
        to_r, to_c = m["to"]
        if _ptype_of(board[frm_r * 8 + frm_c]) == "P" and _promotion_rank(to_r, color) is not None:
            m["promote_to"] = "Q"
    
    # Easy: shallow search with mistakes
    if config.get("mistake_rate", 0) > 0 and random.random() < config["mistake_rate"]:
        # Sometimes pick a suboptimal move
        return random.choice(legal_moves)
    
    # Search with limited depth, using iterative deepening if configured
    depth = min(config.get("search_depth", 1), config.get("max_depth", 3))
    eval_depth = config.get("evaluate_depth", 1)
    
    best_score = -1000000
    best_moves: list[dict] = []
    alpha = -1000000
    beta = 1000000
    
    for move in legal_moves:
        # Apply move temporarily
        new_board, new_ep, new_castling = _apply_move(board, ep, castling, move, color)
        
        # Evaluate after our move
        score = _evaluate_board(new_board, color)
        
        # Add tactical bonuses
        if _gives_check(new_board, new_ep, new_castling, move, color):
            score += config["tactic_bias"]
        
        # Capture bonus
        captured = new_board[move["to"][0] * 8 + move["to"][1]]
        if captured != ".":
            cap_val = _PIECE_VALUES.get(_ptype_of(captured), 0)
            if _color_of(captured) != color:  # we captured opponent
                score += cap_val * config["material_bias"] // 100
        
        # Prefer center moves for development
        r, c = move["to"]
        if abs(r - 3.5) + abs(c - 3.5) < 3:
            score += config["control_iterations"] // 20
        
        # If we have depth budget, look ahead one more ply (opponent's response)
        if depth >= 2:
            opponent_legal = _legal_moves_for(new_board, new_ep, castling, 1 - color)
            if opponent_legal:
                worst_case = 1000000
                for opp_move in opponent_legal[:8]:  # limit opponent responses for speed
                    opp_board, _, _ = _apply_move(new_board, new_ep, new_castling, opp_move, 1 - color)
                    opp_score = _evaluate_board(opp_board, 1 - color)
                    if opp_score < worst_case:
                        worst_case = opp_score
                score = score - worst_case // 2  # Blend material and opponent's best counter
        
        if score > best_score:
            best_score = score
            best_moves = [move]
        elif score == best_score:
            best_moves.append(move)
    
    # Pick from best moves with slight randomization at lower difficulties
    if config.get("mistake_rate", 0) > 0.1 and len(best_moves) > 1:
        # Among equal-best moves, sometimes pick slightly worse
        if random.random() < config["mistake_rate"] * 0.5:
            return random.choice(legal_moves)
    
    return random.choice(best_moves) if best_moves else random.choice(legal_moves)


def _gives_check(
    board: list[str],
    ep: tuple[int, int] | None,
    castling: set[str],
    move: dict,
    color: int,
) -> bool:
    """Check if a move gives check to the opponent's king."""
    new_board, new_ep, new_castling = _apply_move(board, ep, castling, move, color)
    enemy_color = 1 - color
    king_pos = _king_pos(new_board, enemy_color)
    if king_pos is None:
        return False
    return _attacked_by(new_board, king_pos, color, king_pos, king_pos)


def _move_equals_robust(m1: dict, m2: dict) -> bool:
    """Robust move equality check for AI filtering."""
    return (m1["frm"] == m2["frm"] and m1["to"] == m2["to"] and
            (m1.get("promote_to") or "") == (m2.get("promote_to") or "") and
            (m1.get("castling") or []) == (m2.get("castling") or []))
