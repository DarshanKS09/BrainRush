/** Chess game screen: board visualization with move selection, AI opponent,
 * promotion chooser, move history, and undo/restart. Renders a responsive
 * chess board that works on desktop and mobile.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { api, newClientGuessId, type ChessState, type ChessMove, type ChessSquare, type ChessPiece } from '../api';
import type { WebAppContext } from '../telegram';
import { ErrorNotice, Loading } from '../components/ui';
import { haptic } from '../telegram';

const MIN_BOARD_SIZE = 280;

type PromotionPiece = 'knight' | 'bishop' | 'rook' | 'queen';

function squareFromRankFile(r: number, c: number): string {
  const files = 'abcdefgh';
  const ranks = '87654321';
  return `${files[c]}${ranks[r]}`;
}

function rankFileFromSquare(sq: string): { r: number; c: number } | null {
  if (typeof sq !== 'string' || sq.length !== 2) return null;
  const file = sq[0];
  const rank = sq[1];
  if (file < 'a' || file > 'h' || rank < '1' || rank > '8') return null;
  return { r: 8 - parseInt(rank, 10), c: file.charCodeAt(0) - 'a'.charCodeAt(0) };
}

/**
 * The backend stores the chess board as a flat `string[]` of 64 piece
 * strings (e.g. `"Rw"`, `"Pb"`, `"."`) in row-major order. The frontend
 * `ChessSquare` type expects an 8×8 grid with `color`, `occupant`, `rank`,
 * and `file` per square. Convert the flat storage format into the view
 * format the board renderer needs.
 */
function flatBoardToSquares(board: string[]): ChessSquare[][] {
  const squares: ChessSquare[][] = [];
  for (let r = 0; r < 8; r++) {
    const row: ChessSquare[] = [];
    for (let c = 0; c < 8; c++) {
      const pieceStr = board[r * 8 + c];
      const isLight = (r + c) % 2 === 0;
      let occupant: ChessPiece | null = null;
      if (pieceStr && pieceStr !== '.') {
        const color = pieceStr.endsWith('w') ? 'white' : 'black';
        const type = pieceStr[0].toLowerCase() as ChessPiece['type'];
        occupant = { color, type };
      }
      row.push({
        color: isLight ? 'light' : 'dark',
        occupant,
        rank: r,
        file: c,
      });
    }
    squares.push(row);
  }
  return squares;
}

/**
 * Compute the legal destination squares for the piece on `from`, using only
 * the board geometry and turn. This is a best-effort frontend validator: it
 * does not handle castling, en passant, or pinned-piece detection — the
 * backend is authoritative and will reject illegal moves. It is sufficient
 * to enable piece selection and legal-move highlighting even though the
 * backend's `position.legalMoves` is not populated.
 */
function legalMovesForSquare(
  board: ChessSquare[][],
  from: string,
  turn: 'white' | 'black',
): string[] {
  const pos = rankFileFromSquare(from);
  if (!pos) return [];
  const piece = board[pos.r][pos.c].occupant;
  if (!piece || piece.color !== turn) return [];

  const moves: string[] = [];
  const { r: sr, c: sc } = pos;

  const step = (dr: number, dc: number, max: number, jump: boolean) => {
    for (let i = 1; i <= max; i++) {
      const nr = sr + dr * i;
      const nc = sc + dc * i;
      if (nr < 0 || nr > 7 || nc < 0 || nc > 7) break;
      const target = board[nr][nc];
      const sq = squareFromRankFile(nr, nc);
      if (!sq) break;
      if (target.occupant) {
        if (target.occupant.color !== turn) moves.push(sq);
        break;
      }
      moves.push(sq);
      if (jump) break;
    }
  };

  switch (piece.type) {
    case 'pawn':
      // White moves toward rank 1 (row decreases), black toward rank 8 (row increases).
      const dir = piece.color === 'white' ? -1 : 1;
      const startRow = piece.color === 'white' ? 6 : 1;
      // One step forward
      const one = sr + dir;
      if (one >= 0 && one < 8 && !board[one][sc].occupant) {
        moves.push(squareFromRankFile(one, sc));
        // Two steps from starting rank
        if (sr === startRow) {
          const two = sr + dir * 2;
          if (two >= 0 && two < 8 && !board[two][sc].occupant) {
            moves.push(squareFromRankFile(two, sc));
          }
        }
      }
      // Captures
      for (const dc of [-1, 1]) {
        const nr = sr + dir;
        const nc = sc + dc;
        if (nr >= 0 && nr < 8 && nc >= 0 && nc < 8) {
          const target = board[nr][nc];
          if (target.occupant && target.occupant.color !== turn) {
            moves.push(squareFromRankFile(nr, nc));
          }
        }
      }
      break;
    case 'knight':
      for (const [dr, dc] of [
        [-2, -1], [-2, 1], [-1, -2], [-1, 2],
        [1, -2], [1, 2], [2, -1], [2, 1],
      ]) step(dr, dc, 1, true);
      break;
    case 'bishop':
      for (const [dr, dc] of [[-1, -1], [-1, 1], [1, -1], [1, 1]]) step(dr, dc, 7, false);
      break;
    case 'rook':
      for (const [dr, dc] of [[-1, 0], [1, 0], [0, -1], [0, 1]]) step(dr, dc, 7, false);
      break;
    case 'queen':
      for (const [dr, dc] of [
        [-1, -1], [-1, 1], [1, -1], [1, 1],
        [-1, 0], [1, 0], [0, -1], [0, 1],
      ]) step(dr, dc, 7, false);
      break;
    case 'king':
      for (const [dr, dc] of [
        [-1, -1], [-1, 0], [-1, 1],
        [0, -1],           [0, 1],
        [1, -1],  [1, 0],  [1, 1],
      ]) step(dr, dc, 1, true);
      break;
  }
  return moves;
}

export function ChessPlayScreen({
  ctx,
  sessionId,
  onExit,
  onBackToMatch,
}: {
  ctx: WebAppContext;
  sessionId: string;
  onExit: () => void;
  onBackToMatch?: () => void;
}) {
  const [state, setState] = useState<ChessState | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [selectedSquare, setSelectedSquare] = useState<string | null>(null);
  const [promotionPending, setPromotionPending] = useState<{ from: string; to: string; move: ChessMove } | null>(null);
  const [showPromotionChooser, setShowPromotionChooser] = useState(false);

  const stateRef = useRef<ChessState | null>(null);
  stateRef.current = state;

  const boardRef = useRef<HTMLDivElement>(null);

  const load = useCallback(() => {
    setError('');
    api
      .chessState(ctx.initData, sessionId)
      .then((s) => {
        setState(s);
        setSelectedSquare(null);
        setPromotionPending(null);    setShowPromotionChooser(false);
        // Keep any derived board/turn/legal state refreshed.
      })
      .catch((e: Error) => setError(e.message));
  }, [ctx.initData, sessionId]);

  useEffect(load, [load]);

  const animateDeselection = useCallback(() => {
    // Deselection animation placeholder; visual feedback handled by CSS transitions.
  }, []);

  const getBoard = useCallback((): ChessSquare[][] | null => {
    const s = stateRef.current;
    if (!s || !s.position) return null;
    const rawBoard = s.position.board;
    if (!Array.isArray(rawBoard)) return null;
    // Backend stores board as a flat string[] of 64 piece strings; convert to 8×8 grid.
    if (rawBoard.length === 64 && typeof rawBoard[0] === 'string') {
      return flatBoardToSquares(rawBoard as unknown as string[]);
    }
    // Already an 8×8 ChessSquare[][] grid.
    if (rawBoard.length === 8 && Array.isArray(rawBoard[0])) {
      return rawBoard as ChessSquare[][];
    }
    return null;
  }, [state]);

  const getTurn = useCallback((): 'white' | 'black' => {
    const s = stateRef.current;
    if (!s) return 'white';
    if (s.position && typeof s.position.turn === 'string') return s.position.turn;
    return s.turn === 0 ? ('white' as const) : ('black' as const);
  }, [state]);

  const getLegalMoves = useCallback((): string[] => {
    const s = stateRef.current;
    if (!s) return [];
    const board = getBoard();
    if (!board) return [];
    const selected = selectedSquare;
    if (!selected) return [];
    const turn = getTurn();
    return legalMovesForSquare(board, selected, turn);
  }, [state, selectedSquare, getBoard, getTurn]);

  const isLegalMove = useCallback((from: string, to: string): boolean => {
    const board = getBoard();
    if (!board) return false;
    const turn = getTurn();
    return legalMovesForSquare(board, from, turn).includes(to);
  }, [getBoard, getTurn]);

  const isHighlightedSquare = useCallback((sq: string): boolean => {
    if (!selectedSquare) return false;
    const legal = getLegalMoves();
    return legal.includes(sq);
  }, [selectedSquare, getLegalMoves]);

  const handleSquareClick = useCallback((sq: string) => {
    const current = stateRef.current;
    if (!current || current.finished || busy) return;

    const board = getBoard();
    if (!board) return;

    const sqPos = rankFileFromSquare(sq);
    if (!sqPos) return;

    const turn = getTurn();

    // If a promotion chooser is open, only the promotion piece buttons should
    // be interactive; ignore board taps while the chooser is open.
    if (showPromotionChooser) return;

    // If no square is selected, select this one if it has a piece of the right color
    if (!selectedSquare) {
      const piece = board[sqPos.r][sqPos.c].occupant;
      if (piece && piece.color === turn) {
        setSelectedSquare(sq);
      }
      return;
    }

    // If the same square is clicked, deselect it
    if (selectedSquare === sq) {
      setSelectedSquare(null);
      return;
    }

    // Check if this is a legal move from the selected square
    if (isLegalMove(selectedSquare, sq)) {
      const fromPos = rankFileFromSquare(selectedSquare);
      if (!fromPos) return;

      const piece = board[fromPos.r][fromPos.c].occupant;
      // Promotion: pawn reaching the back rank
      if (piece && piece.type === 'pawn') {
        const isPromotion = (turn === 'white' && sqPos.r === 0) || (turn === 'black' && sqPos.r === 7);
        if (isPromotion) {
          setPromotionPending({ from: selectedSquare, to: sq, move: { from: selectedSquare, to: sq } as ChessMove });
          setShowPromotionChooser(true);
          return;
        }
      }

      // Execute the move
      executeMove(selectedSquare, sq);
    } else {
      // Select a different piece or deselect
      const piece = board[sqPos.r][sqPos.c].occupant;
      if (piece && piece.color === turn) {
        setSelectedSquare(sq);
      } else {
        setSelectedSquare(null);
      }
    }
  }, [state, selectedSquare, busy, showPromotionChooser, getBoard, getTurn, getLegalMoves, isLegalMove, animateDeselection]);

  const executeMove = useCallback(async (from: string, to: string, promotion?: PromotionPiece) => {
    const current = stateRef.current;
    if (!current || current.finished || busy) return;

    setBusy(true);
    try {
      const promotionVal: 'knight' | 'bishop' | 'rook' | 'queen' | null = promotion ?? null;
      const next = await api.chessMove(ctx.initData, sessionId, from, to, promotionVal, newClientGuessId());
      setState(next);
      setSelectedSquare(null);
      setPromotionPending(null);
      setShowPromotionChooser(false);

      if (next.finished) {
        haptic(next.result_public === 'win' ? 'success' : 'error');
      } else {
        haptic('light');
      }
    } catch (e) {
      haptic('error');
    } finally {
      setBusy(false);
    }
  }, [ctx.initData, sessionId, busy]);

  const handlePromotionChoice = useCallback((piece: PromotionPiece) => {
    if (!promotionPending) return;
    setShowPromotionChooser(false);
    executeMove(promotionPending.from, promotionPending.to, piece);
  }, [promotionPending, executeMove]);

  const getMoveHistory = useCallback((): string[] => {
    const s = stateRef.current;
    if (!s) return [];
    if (Array.isArray(s.move_history)) {
      return s.move_history.map((m) => m.notation);
    }
    return [];
  }, [state]);

  const handleUndo = useCallback(async () => {
    const current = stateRef.current;
    if (!current || current.finished || busy) return;

    setBusy(true);
    try {
      await api.chessUndo(ctx.initData, sessionId);
      load();
    } catch (e) {
      haptic('error');
    } finally {
      setBusy(false);
    }
  }, [ctx.initData, sessionId, busy, load]);

  const handleRestart = useCallback(async () => {
    const current = stateRef.current;
    if (!current || busy) return;

    setBusy(true);
    try {
      const next = await api.chessRestart(ctx.initData, sessionId);
      setState(next);
      setSelectedSquare(null);
      setPromotionPending(null);
      setShowPromotionChooser(false);
      haptic('light');
    } catch (e) {
      haptic('error');
    } finally {
      setBusy(false);
    }
  }, [ctx.initData, sessionId, busy]);

  const cancel = useCallback(async () => {
    try {
      await api.cancel(ctx.initData, sessionId);
    } catch {
      /* already gone: still exit */
    }
    onExit();
    onBackToMatch?.();
  }, [ctx.initData, sessionId, onExit, onBackToMatch]);

  if (error && !state) return <ErrorNotice message={error} onRetry={load} />;
  if (!state) return <Loading label="Loading chess…" />;

  const game = state;

  // Result screen
  if (game.finished) {
    const r = game.result;
    const outcome = game.result_public ?? r?.outcome ?? 'draw';
    const outcomeText = outcome === 'win' ? 'Victory!' : outcome === 'loss' ? 'Defeat' : 'Draw';
    const emoji = outcome === 'win' ? '�' : outcome === 'loss' ? '😔' : '�';
    const xp = r?.xp_earned ?? 0;

    return (
      <div className="rounded-3xl bg-panel p-6 text-center shadow-card animate-pop">
        <div className="text-5xl" aria-hidden>{emoji}</div>
        <h2 className="mt-2 text-2xl font-bold text-white">{outcomeText}</h2>
        <p className="mt-1 text-sm text-slate-300">
          {outcome === 'win' ? (
            <>Checkmate · <b className="text-neon-cyan">+{xp} XP</b></>
          ) : outcome === 'loss' ? (
            <>Checkmate · <b className="text-neon-cyan">+{xp} XP</b> for playing</>
          ) : (
            <>Draw · <b className="text-neon-cyan">+{xp} XP</b></>
          )}
        </p>
        <div className="mt-4 flex gap-2">
          <button onClick={handleRestart} disabled={busy} className="flex-1 rounded-xl bg-navy py-2.5 text-sm font-bold text-slate-200 active:scale-95 disabled:opacity-50">
            {busy ? '…' : '↻ Play again'}
          </button>
          <button onClick={onExit} className="flex-1 rounded-xl bg-panel py-2.5 text-sm font-bold text-slate-300 active:scale-95">
            Lobby
          </button>
        </div>
      </div>
  );
  }

  // Promotion chooser modal
  if (showPromotionChooser && promotionPending) {
    const pieces: { type: PromotionPiece; label: string; unicode: string }[] = [
      { type: 'queen', label: 'Queen', unicode: '♕' },
      { type: 'rook', label: 'Rook', unicode: '♖' },
      { type: 'bishop', label: 'Bishop', unicode: '♗' },
      { type: 'knight', label: 'Knight', unicode: '♘' },
    ];

    const isWhite = getTurn() === 'white';

    return (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4" onClick={() => {}}>
        <div className="rounded-2xl bg-panel p-4 shadow-card w-full max-w-[280px] animate-pop" onClick={(e) => e.stopPropagation()}>
          <h3 className="text-center text-lg font-bold text-white mb-3">Promote to:</h3>
          <div className="grid grid-cols-4 gap-2">
              {pieces.map((p) => (
                <button
                  key={p.type}
                  onClick={() => handlePromotionChoice(p.type)}
                  disabled={busy}
                  className={`rounded-xl p-3 text-3xl font-bold transition-transform active:scale-95 disabled:opacity-50 ${
                    isWhite
                      ? 'bg-white text-black shadow-glow'
                      : 'bg-black text-white shadow-glow'
                  }`}
                  aria-label={p.label}
                >
                  <span className="block text-center text-4xl">{p.unicode}</span>
                  <span className="block text-xs mt-1 text-center">{p.label}</span>
                </button>
              ))}
            </div>
            <button
              onClick={() => { setShowPromotionChooser(false); setPromotionPending(null); }}
              className="mt-3 w-full rounded-xl bg-navy py-2 text-sm font-bold text-slate-300 active:scale-95"
            >
              Cancel
            </button>
          </div>
        </div>
      );
    }

    // Main game screen
    return (
      <div><div className="space-y-3">
        <div className="flex items-center justify-between">
          <button onClick={onExit} className="rounded-xl bg-panel px-3 py-1.5 text-sm font-semibold text-slate-300 active:scale-95" aria-label="Back to lobby">
            � Lobby
          </button>
          <div className="flex items-center gap-2">
            <span className="rounded-full bg-panel px-3 py-1 text-xs font-bold uppercase tracking-wider text-neon-cyan">
              {game.difficulty.charAt(0).toUpperCase() + game.difficulty.slice(1).replace('reflex', 'Reflex')}
            </span>
            <span className="rounded-full bg-panel px-3 py-1 text-xs font-bold text-slate-400">
              {getTurn()} to move
            </span>
          </div>
          <div className="flex items-center gap-2">
            <button onClick={handleUndo} disabled={busy || game.position.halfMoves < 2} className="rounded-xl bg-panel px-3 py-1.5 text-sm font-semibold text-slate-300 active:scale-95 disabled:opacity-40" aria-label="Undo">
              ↩ Undo
            </button>
            <button onClick={cancel} className="rounded-xl bg-panel px-3 py-1.5 text-sm font-semibold text-rose-300 active:scale-95" aria-label="Cancel game">
              ✕ Give up
            </button>
          </div>
        </div>
      </div>
      <div className="flex justify-center">
        <div
          ref={boardRef}
          className="rounded-2xl overflow-hidden shadow-card border-2 border-navy"
          style={{ width: '100%', maxWidth: MIN_BOARD_SIZE, aspectRatio: '1' }}
        >
          <div className="grid grid-cols-8 grid-rows-8 w-full h-full">
            {getBoard()?.map((row, ri) =>
              row.map((square, ci) => {
                const sq = squareFromRankFile(ri, ci);
                const isSelected = selectedSquare === sq;
                const isHighlighted = isHighlightedSquare(sq);
                const isLegal = isLegalMove(selectedSquare ?? '', sq);

                const bgColor = square.color === 'light'
                  ? (isSelected ? 'bg-yellow-300' : isHighlighted ? 'bg-neon-cyan/40' : 'bg-[#f0d9b5]')
                  : (isSelected ? 'bg-yellow-400' : isHighlighted ? 'bg-neon-cyan/30' : 'bg-[#b58863]');

                const piece = square.occupant;
                const pieceUnicode = piece ? (piece.color === 'white' ? WHITE_PIECES[piece.type] : BLACK_PIECES[piece.type]) : '';

                return (
                  <button
                    key={sq}
                    onClick={() => handleSquareClick(sq)}
                    disabled={busy || game.finished}
                    className={`w-full h-full flex items-center justify-center text-3xl font-bold select-none transition-colors duration-100 ${bgColor} ${
                      isLegal && !isSelected ? 'ring-2 ring-neon-cyan/60 rounded-sm' : ''
                    }`}
                    aria-label={`${sq}${piece ? ` ${piece.color} ${piece.type}` : ' empty'}`}
                  >
                    {pieceUnicode}
                  </button>
                );              })
            )}
          </div>
      </div>
    </div>

      {/* Move history */}
      <div className="rounded-2xl bg-panel p-3 shadow-card max-h-[140px] overflow-y-auto">
        <h4 className="text-xs font-bold text-slate-400 uppercase tracking-wider mb-2">Move History</h4>
        {getMoveHistory().length === 0 ? (
          <p className="text-sm text-slate-500 text-center py-2">No moves yet</p>
        ) : (
          <div className="flex flex-wrap gap-1">
            {getMoveHistory().map((move, i) => (
              <span
                key={i}
                className={`rounded-lg px-2 py-0.5 text-xs font-mono ${
                  i % 2 === 0 ? 'bg-navy/50 text-slate-200' : 'bg-navy/30 text-slate-300'
                }`}
              >
                {i % 2 === 0 ? `${Math.floor(i / 2) + 1}. ` : ''}{move}
              </span>
            ))}
          </div>
        )}
      </div>

      {/* Status bar */}
      <div className="flex items-center justify-between text-xs text-slate-400">
        <div className="flex items-center gap-2">
          <span className="w-3 h-3 rounded-full" style={{ backgroundColor: getTurn() === 'white' ? '#fff' : '#000' }} />
          <span>{getTurn()} to move</span>
        </div>
        {(() => {
          const s = stateRef.current;
          if (!s) return null;
          if (s.position && typeof s.position.check === 'boolean') return s.position.check ? (
            <span className="text-rose-400 font-bold animate-pulse">⚠ Check!</span>
          ) : null;
          return null;
        })()}
      </div>

      {/* Promotion pending notice */}
      {promotionPending && !showPromotionChooser && (
        <div className="rounded-xl bg-amber-500/20 p-3 text-center shadow-card">
          <p className="text-sm text-amber-300 font-semibold">
            Choose a piece to promote to:
          </p>
        </div>
      )}

      {/* Restart button */}
      <div className="flex gap-2">
        <button
          onClick={handleRestart}
          disabled={busy}
          className="flex-1 rounded-xl bg-panel py-2 text-xs font-bold text-slate-300 active:scale-95 disabled:opacity-50"
        >
          ↻ Restart
        </button>
      </div>

      <p className="text-[10px] text-center text-slate-500">
        Tap a piece to select it, then tap a highlighted square to move. Ctrl+Z to undo, Ctrl+R to restart.
      </p>

    </div>
  );
}

// Piece Unicode characters
const WHITE_PIECES: Record<string, string> = {
  king: '♔',
  queen: '♕',
  rook: '♖',
  bishop: '♗',
  knight: '♘',
  pawn: '♙',
};

const BLACK_PIECES: Record<string, string> = {
  king: '♚',
  queen: '♛',
  rook: '♜',
  bishop: '♝',
  knight: '♞',
  pawn: '♟',
};

