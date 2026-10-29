/** Maze Race game screen: top-down 2D maze navigation with swipe, D-pad,
 * keyboard, and multiplayer support. Uses SVG for crisp rendering and
 * requestAnimationFrame for smooth player movement without high-frequency
 * React state updates.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { api, newClientGuessId, type MazeState } from '../api';
import type { WebAppContext } from '../telegram';
import { formatMs } from '../gameutil';
import { ErrorNotice, Loading } from '../components/ui';
import { MatchSubmitBanner } from '../components/MatchSubmit';
import { haptic } from '../telegram';

const CELL_SIZE = 40;
const MOVE_ANIMATION_MS = 220;
const INACTIVITY_TIMEOUT_MS = 300_000; // 5 minutes

type Phase = 'intro' | 'playing' | 'paused' | 'finished';

export function MazePlayScreen({
  ctx,
  sessionId,
  onExit,
  onReplay,
  matchId,
  onBackToMatch,
}: {
  ctx: WebAppContext;
  sessionId: string;
  onExit: () => void;
  onReplay: (sessionId: string) => void;
  matchId?: string | null;
  onBackToMatch?: () => void;
}) {
  const [view, setView] = useState<MazeState | null>(null);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const [replaying, setReplaying] = useState(false);
  const [showDpad, setShowDpad] = useState(true);
  const [phase, setPhase] = useState<Phase>('intro');

  // Animation state (kept out of React render loop): interpolated player
  // position for smooth movement between cells.
  const animRef = useRef({
    r: 0, c: 0, targetR: 0, targetC: 0, startTime: 0, animating: false,
  });
  const rafRef = useRef(0);
  const moveLockRef = useRef(false); // one move at a time
  const lastMoveTimeRef = useRef(0);
  const inactivityTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const viewRef = useRef<MazeState | null>(null);
  viewRef.current = view;

  const stopAnimation = () => {
    if (rafRef.current) cancelAnimationFrame(rafRef.current);
    rafRef.current = 0;
    animRef.current.animating = false;
  };

  const clearInactivity = () => {
    if (inactivityTimerRef.current) {
      clearTimeout(inactivityTimerRef.current);
      inactivityTimerRef.current = null;
    }
  };

  const setInactivity = () => {
    clearInactivity();
    inactivityTimerRef.current = setTimeout(() => {
      if (phase === 'playing') setPhase('paused');
    }, INACTIVITY_TIMEOUT_MS);
  };

  // Clean up everything on unmount.
  useEffect(() => {
    return () => {
      stopAnimation();
      clearInactivity();
      window.removeEventListener('keydown', onKey);
      window.removeEventListener('visibilitychange', onVisibility);
      document.removeEventListener('touchstart', onTouchStart as EventListener);
      document.removeEventListener('touchmove', onTouchMove as EventListener);
      document.removeEventListener('touchend', onTouchEnd as EventListener);
    };
  }, []);

  const onVisibility = () => {
    if (document.visibilityState === 'hidden' && phase === 'playing') {
      setPhase('paused');
    } else if (document.visibilityState === 'visible' && phase === 'paused') {
      setPhase('playing');
    }
  };

  document.addEventListener('visibilitychange', onVisibility);

  const load = useCallback(() => {
    setError('');
    setPhase('intro');
    stopAnimation();
    api
      .mazeState(ctx.initData, sessionId)
      .then((state) => {
        setView(state);
        viewRef.current = state;
        animRef.current = {
          r: state.player.r, c: state.player.c,
          targetR: state.player.r, targetC: state.player.c,
          startTime: 0, animating: false,
        };
        if (state.finished) setPhase('finished');
        else if (state.moves > 0) setPhase('playing');
        setInactivity();
      })
      .catch((e: Error) => setError(e.message));
  }, [ctx.initData, sessionId]);

  useEffect(load, [load]);

  // Smooth movement animation: interpolates player position using rAF,
  // without touching React state each frame.
  const tick = useCallback(() => {
    const a = animRef.current;
    if (!a.animating) return;
    const now = performance.now();
    const elapsed = now - a.startTime;
    const t = Math.min(1, elapsed / MOVE_ANIMATION_MS);
    if (t >= 1) {
      a.r = a.targetR;
      a.c = a.targetC;
      a.animating = false;
      stopAnimation();
      void syncState();
    } else {
      rafRef.current = requestAnimationFrame(tick);
    }
  }, []);

  const syncState = async () => {
    try {
      const next = await api.mazeState(ctx.initData, sessionId);
      setView(next);
      viewRef.current = next;
      if (next.finished) {
        setPhase('finished');
        stopAnimation();
        clearInactivity();
        haptic('success');
      } else {
        setPhase('playing');
        setInactivity();
      }
    } catch {
      /* keep last known view on sync failure */
    }
  };

  const attemptMove = useCallback(
    async (direction: string) => {
      const v = viewRef.current;
      if (!v || v.finished || busy || phase !== 'playing' || moveLockRef.current) return;
      if (!v.valid_directions.includes(direction)) return;
      moveLockRef.current = true;
      setBusy(true);
      setNotice('');
      try {
        const next = await api.mazeMove(
          ctx.initData, sessionId, direction, newClientGuessId(),
        );
        setView(next);
        viewRef.current = next;
        animRef.current = {
          r: v.player.r, c: v.player.c,
          targetR: next.player.r, targetC: next.player.c,
          startTime: performance.now(), animating: true,
        };
        lastMoveTimeRef.current = performance.now();
        if (next.finished) {
          setPhase('finished');
          stopAnimation();
          clearInactivity();
          haptic('success');
        } else {
          rafRef.current = requestAnimationFrame(tick);
          setInactivity();
        }
      } catch (e) {
        setNotice(e instanceof Error ? e.message : 'Move failed. Try again.');
        haptic('error');
      } finally {
        setBusy(false);
        moveLockRef.current = false;
      }
    },
    [busy, ctx.initData, sessionId, phase, tick],
  );

  const onKey = useCallback(
    (e: KeyboardEvent) => {
      if (phase !== 'playing' && phase !== 'paused') return;
      let dir: string | null = null;
      if (e.key === 'ArrowUp' || e.key === 'w' || e.key === 'W') dir = 'up';
      else if (e.key === 'ArrowDown' || e.key === 's' || e.key === 'S') dir = 'down';
      else if (e.key === 'ArrowLeft' || e.key === 'a' || e.key === 'A') dir = 'left';
      else if (e.key === 'ArrowRight' || e.key === 'd' || e.key === 'D') dir = 'right';
      else if (e.key === ' ' || e.key === 'Escape') {
        e.preventDefault();
        setPhase((p) => (p === 'paused' ? 'playing' : 'paused'));
        return;
      }
      if (dir) {
        e.preventDefault();
        void attemptMove(dir);
      }
    },
    [attemptMove, phase],
  );

  window.addEventListener('keydown', onKey);

  // Touch/swipe handling.
  let touchStartX = 0;
  let touchStartY = 0;
  let touchStartTime = 0;

  const onTouchStart = (e: TouchEvent) => {
    if (phase !== 'playing') return;
    const t = e.touches[0];
    touchStartX = t.clientX;
    touchStartY = t.clientY;
    touchStartTime = performance.now();
  };

  const onTouchMove = (e: TouchEvent) => {
    if (phase === 'playing') e.preventDefault();
  };

  const onTouchEnd = (e: TouchEvent) => {
    if (phase !== 'playing') return;
    const now = performance.now();
    if (now - touchStartTime > 400) return;
    const t = e.changedTouches[0];
    const dx = t.clientX - touchStartX;
    const dy = t.clientY - touchStartY;
    const dist = Math.hypot(dx, dy);
    if (dist < 30) return;
    const dir = Math.abs(dx) > Math.abs(dy) ? (dx > 0 ? 'right' : 'left') : dy > 0 ? 'down' : 'up';
    void attemptMove(dir);
  };

  document.addEventListener('touchstart', onTouchStart as EventListener);
  document.addEventListener('touchmove', onTouchMove as EventListener);
  document.addEventListener('touchend', onTouchEnd as EventListener);

  const cancel = async () => {
    stopAnimation();
    clearInactivity();
    try {
      await api.cancel(ctx.initData, sessionId);
    } catch {
      /* already gone: still exit */
    }
    onExit();
  };

  const restart = async () => {
    stopAnimation();
    setPhase('intro');
    setNotice('');
    try {
      const s = await api.mazeState(ctx.initData, sessionId);
      if (s.finished) {
        const ns = await api.start(ctx.initData, 'maze_race', viewRef.current?.difficulty ?? 'medium');
        onReplay(ns.session_id);
        return;
      }
      setView(s);
      viewRef.current = s;
      animRef.current = {
        r: s.player.r, c: s.player.c,
        targetR: s.player.r, targetC: s.player.c,
        startTime: 0, animating: false,
      };
      setPhase('playing');
      setInactivity();
    } catch (e) {
      setNotice(e instanceof Error ? e.message : 'Could not restart.');
    }
  };

  const replay = async () => {
    if (!view || replaying) return;
    setReplaying(true);
    try {
      const s = await api.start(ctx.initData, 'maze_race', view.difficulty);
      onReplay(s.session_id);
    } catch (e) {
      setNotice(e instanceof Error ? e.message : 'Could not start a new game.');
    } finally {
      setReplaying(false);
    }
  };

  if (error && !view) return <ErrorNotice message={error} onRetry={load} />;
  if (!view) return <Loading label="Generating maze…" />;

  const config = view.maze;
  const cellPx = Math.min(CELL_SIZE, Math.floor(Math.min(window.innerWidth, 400) / config.cols));
  const mazePx = cellPx * config.cols;

  // --- Results screen ---
  if (view.finished && view.result) {
    const r = view.result;
    return (
      <div className="rounded-3xl bg-panel p-6 text-center shadow-card animate-pop">
        <div className="text-5xl" aria-hidden>🏁</div>
        <h2 className="mt-2 text-2xl font-bold text-white">Maze completed!</h2>
        <div className="mx-auto mt-3 max-w-xs space-y-1 text-sm" aria-label="Run results">
          <div className="flex justify-between rounded-xl bg-navy px-3 py-1.5">
            <span className="text-slate-400">Difficulty</span>
            <b className="text-white">{view.difficulty.charAt(0).toUpperCase() + view.difficulty.slice(1)}</b>
          </div>
          <div className="flex justify-between rounded-xl bg-navy px-3 py-1.5">
            <span className="text-slate-400">Time</span>
            <b className="text-neon-cyan">{formatMs(r.score)}</b>
          </div>
          <div className="flex justify-between rounded-xl bg-navy px-3 py-1.5">
            <span className="text-slate-400">Moves</span>
            <b className="text-white">{r.moves}</b>
          </div>
          <div className="flex justify-between rounded-xl bg-navy px-3 py-1.5">
            <span className="text-slate-400">Base XP</span>
            <b className="text-white">+{r.xp_breakdown.base}</b>
          </div>
          {r.xp_breakdown.time_bonus > 0 && (
            <div className="flex justify-between rounded-xl bg-navy px-3 py-1.5">
              <span className="text-slate-400">Time bonus</span>
              <b className="text-emerald-300">+{r.xp_breakdown.time_bonus}</b>
            </div>
          )}
          {r.xp_breakdown.path_bonus > 0 && (
            <div className="flex justify-between rounded-xl bg-navy px-3 py-1.5">
              <span className="text-slate-400">Efficiency bonus</span>
              <b className="text-emerald-300">+{r.xp_breakdown.path_bonus}</b>
            </div>
          )}
          <div className="flex justify-between rounded-xl bg-navy px-3 py-1.5 font-bold">
            <span className="text-slate-400">Total XP</span>
            <b className="text-neon-cyan">+{r.xp_earned}</b>
          </div>
        </div>
        {notice && (
          <p className="mt-2 text-sm text-amber-300" role="alert">{notice}</p>
        )}
        <div className="mt-5 flex gap-2 flex-wrap">
          <button
            onClick={restart}
            className="flex-1 rounded-xl bg-navy py-2.5 text-sm font-bold text-slate-200 active:scale-95 disabled:opacity-50"
            disabled={busy}
          >
            {busy ? '…' : '↻ Play again'}
          </button>
          <button
            onClick={replay}
            disabled={replaying}
            className="flex-1 rounded-xl bg-gradient-to-r from-neon-purple to-neon-cyan py-2.5 text-sm font-bold text-white shadow-glow active:scale-95 disabled:opacity-50"
          >
            {replaying ? 'Starting…' : 'New maze'}
          </button>
          <button onClick={onExit} className="flex-1 rounded-xl bg-panel py-2.5 text-sm font-bold text-slate-300 active:scale-95">
            Lobby
          </button>
        </div>
        {matchId && onBackToMatch && (
          <MatchSubmitBanner ctx={ctx} matchId={matchId} sessionId={sessionId} onBackToMatch={onBackToMatch} />
        )}
      </div>
    );
  }

  // --- Intro screen ---
  if (phase === 'intro') {
    return (
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <button onClick={onExit} className="rounded-xl bg-panel px-3 py-1.5 text-sm font-semibold text-slate-300 active:scale-95" aria-label="Back to lobby">
            ← Lobby
          </button>
          <span className="rounded-full bg-panel px-3 py-1 text-xs font-bold uppercase tracking-wider text-neon-cyan">
            {view.difficulty.charAt(0).toUpperCase() + view.difficulty.slice(1)}
          </span>
          <button onClick={cancel} className="rounded-xl bg-panel px-3 py-1.5 text-sm font-semibold text-rose-300 active:scale-95" aria-label="Cancel game">
            ✕ Give up
          </button>
        </div>
        <div className="rounded-3xl bg-panel p-6 text-center shadow-card animate-pop">
          <div className="text-5xl" aria-hidden>🌀</div>
          <h2 className="mt-3 text-xl font-bold text-white">Maze Race</h2>
          <p className="mx-auto mt-2 max-w-xs text-sm text-slate-300">
            Navigate from the top-left entrance to the bottom-right exit.
            Move through corridors; at junctions pick your direction.
            Wrong turns and backtracking cost time.
          </p>
          <div className="mx-auto mt-4 max-w-xs space-y-1 text-xs text-slate-400">
            <p>📐 {config.rows}×{config.cols} grid</p>
            <p>🎯 Reach the exit · fewer moves = more XP</p>
          </div>
          <button
            onClick={() => setPhase('playing')}
            className="mt-5 w-full rounded-xl bg-gradient-to-r from-neon-purple to-neon-cyan py-3 text-base font-bold text-white shadow-glow active:scale-[0.99]"
          >
            ▶ Start Race
          </button>
        </div>
      </div>
    );
  }

  // --- Paused screen ---
  if (phase === 'paused') {
    return (
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <button onClick={onExit} className="rounded-xl bg-panel px-3 py-1.5 text-sm font-semibold text-slate-300 active:scale-95" aria-label="Back to lobby">
            ← Lobby
          </button>
          <button onClick={() => setPhase('playing')} className="rounded-xl bg-panel px-3 py-1.5 text-sm font-semibold text-neon-cyan active:scale-95">
            Resume
          </button>
          <button onClick={cancel} className="rounded-xl bg-panel px-3 py-1.5 text-sm font-semibold text-rose-300 active:scale-95" aria-label="Cancel game">
            ✕ Give up
          </button>
        </div>
        <div className="rounded-3xl bg-panel p-6 text-center shadow-card animate-pop">
          <div className="text-5xl" aria-hidden>⏸️</div>
          <h2 className="mt-2 text-2xl font-bold text-white">Paused</h2>
          <p className="mt-1 text-sm text-slate-300">Tap Resume to continue your run.</p>
          <div className="mt-4 flex gap-2">
            <button
              onClick={() => setPhase('playing')}
              className="flex-1 rounded-xl bg-gradient-to-r from-neon-purple to-neon-cyan py-2.5 text-sm font-bold text-white shadow-glow active:scale-95"
            >
              ▶ Resume
            </button>
            <button onClick={restart} className="flex-1 rounded-xl bg-navy py-2.5 text-sm font-bold text-slate-300 active:scale-95">
              ↻ Restart
            </button>
          </div>
          <button onClick={onExit} className="mt-2 w-full rounded-xl bg-panel py-2 text-sm font-bold text-slate-300 active:scale-95">
            ← Lobby
          </button>
        </div>
      </div>
    );
  }

  // --- Playing screen ---
  const elapsedMs = view.elapsed_ms ?? 0;
  const totalCells = config.rows * config.cols;
  const progressPct = totalCells > 0 ? Math.min(100, ((view.moves + 1) / totalCells) * 100) : 0;

  const animatedPos = animRef.current.animating ? animRef.current : view.player;

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <button onClick={() => setPhase('paused')} className="rounded-xl bg-panel px-3 py-1.5 text-sm font-semibold text-slate-300 active:scale-95" aria-label="Pause">
          ⏸
        </button>
        <span className="rounded-full bg-panel px-3 py-1 text-xs font-bold uppercase tracking-wider text-neon-cyan">
          {view.difficulty.charAt(0).toUpperCase() + view.difficulty.slice(1)}
        </span>
        <button onClick={cancel} className="rounded-xl bg-panel px-3 py-1.5 text-sm font-semibold text-rose-300 active:scale-95" aria-label="Cancel game">
          ✕ Give up
        </button>
      </div>

      <div className="rounded-3xl bg-panel p-3 shadow-card">
        <div className="flex justify-between gap-2 mb-2 text-xs text-slate-400">
          <span>⏱ {formatMs(elapsedMs)}</span>
          <span>👣 {view.moves}</span>
        </div>
        <div
          className="mx-auto h-2 w-full overflow-hidden rounded-full bg-navy"
          role="progressbar"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={Math.round(progressPct)}
          aria-label="Progress through maze"
        >
          <div
            className="h-full rounded-full bg-gradient-to-r from-neon-purple to-neon-cyan"
            style={{ width: `${Math.round(progressPct)}%`, transition: 'width 200ms linear' }}
          />
        </div>
        <div className="flex items-center justify-center">
          <svg
            width={mazePx + 20}
            height={mazePx + 20}
            viewBox={`-10 -10 ${mazePx + 20} ${mazePx + 20}`}
            className="block overflow-visible"
          >
            {/* Walls */}
            {config.cells.map((cell) => {
              const x = cell.c * cellPx;
              const y = cell.r * cellPx;
              const s = cellPx;
              const w = cell.walls;
              return (
                <g key={`${cell.r}-${cell.c}`} stroke="#ef4444" strokeWidth={Math.max(2, cellPx / 10)} strokeLinecap="round" fill="none">
                  {w.up && <line x1={x} y1={y} x2={x + s} y2={y} />}
                  {w.right && <line x1={x + s} y1={y} x2={x + s} y2={y + s} />}
                  {w.down && <line x1={x} y1={y + s} x2={x + s} y2={y + s} />}
                  {w.left && <line x1={x} y1={y} x2={x} y2={y + s} />}
                </g>
              );
            })}
            {/* Start marker */}
            <circle
              cx={cellPx / 2}
              cy={cellPx / 2}
              r={cellPx * 0.35}
              fill="#10b981"
              stroke="#ffffff"
              strokeWidth={2}
            />
            {/* Exit marker */}
            <circle
              cx={(config.cols - 1) * cellPx + cellPx / 2}
              cy={(config.rows - 1) * cellPx + cellPx / 2}
              r={cellPx * 0.35}
              fill="#f59e0b"
              stroke="#ffffff"
              strokeWidth={2}
            />
            {/* Player */}
            <circle
              cx={animatedPos.c * cellPx + cellPx / 2}
              cy={animatedPos.r * cellPx + cellPx / 2}
              r={cellPx * 0.3}
              fill="#22d3ee"
              stroke="#ffffff"
              strokeWidth={2}
              className="drop-shadow-[0_0_8px_rgba(34,211,238,0.8)]"
            />
          </svg>
        </div>
        {notice && (
          <p className="mt-1 text-xs text-amber-300 text-center" role="alert">{notice}</p>
        )}
      </div>

      <div className="mt-2 text-xs text-slate-400 text-center">
        {phase === 'playing' ? 'Swipe or tap a direction · arrow keys / WASD' : 'Paused'}
        {showDpad && (
          <p className="mt-1 text-[10px] text-slate-500">Hide D-pad to use swipe only</p>
        )}
      </div>

      {showDpad && (
        <div className="mt-3 grid grid-cols-3 gap-2 w-48 mx-auto">
          <div />
          <button
            onClick={() => void attemptMove('up')}
            disabled={busy || !view.valid_directions.includes('up')}
            aria-label="Move up"
            className={`h-14 rounded-xl flex items-center justify-center text-sm font-bold text-white shadow-card disabled:opacity-40 disabled:cursor-not-allowed ${
              view.valid_directions.includes('up')
                ? 'bg-gradient-to-br from-neon-purple to-neon-cyan active:scale-95'
                : 'bg-navy text-slate-500'
            }`}
          >
            ▲
          </button>
          <div />
          <button
            onClick={() => void attemptMove('left')}
            disabled={busy || !view.valid_directions.includes('left')}
            aria-label="Move left"
            className={`h-14 rounded-xl flex items-center justify-center text-sm font-bold text-white shadow-card disabled:opacity-40 disabled:cursor-not-allowed ${
              view.valid_directions.includes('left')
                ? 'bg-gradient-to-br from-neon-purple to-neon-cyan active:scale-95'
                : 'bg-navy text-slate-500'
            }`}
          >
            ◀
          </button>
          <button
            onClick={() => void attemptMove('down')}
            disabled={busy || !view.valid_directions.includes('down')}
            aria-label="Move down"
            className={`h-14 rounded-xl flex items-center justify-center text-sm font-bold text-white shadow-card disabled:opacity-40 disabled:cursor-not-allowed ${
              view.valid_directions.includes('down')
                ? 'bg-gradient-to-br from-neon-purple to-neon-cyan active:scale-95'
                : 'bg-navy text-slate-500'
            }`}
          >
            ▼
          </button>
          <button
            onClick={() => void attemptMove('right')}
            disabled={busy || !view.valid_directions.includes('right')}
            aria-label="Move right"
            className={`h-14 rounded-xl flex items-center justify-center text-sm font-bold text-white shadow-card disabled:opacity-40 disabled:cursor-not-allowed ${
              view.valid_directions.includes('right')
                ? 'bg-gradient-to-br from-neon-purple to-neon-cyan active:scale-95'
                : 'bg-navy text-slate-500'
            }`}
          >
            ▶
          </button>
          <div />
        </div>
      )}

      <div className="mt-2 flex gap-2">
        <button
          onClick={() => setShowDpad((v) => !v)}
          className="flex-1 rounded-xl bg-navy py-1.5 text-[11px] font-bold text-slate-300 active:scale-95"
        >
          {showDpad ? 'Hide controls' : 'Show D-pad'}
        </button>
        <button
          onClick={restart}
          disabled={busy}
          className="flex-1 rounded-xl bg-panel py-1.5 text-[11px] font-bold text-rose-300 active:scale-95 disabled:opacity-50"
        >
          ↻ Restart
        </button>
      </div>
      <p className="text-[11px] text-center text-slate-500">
        Swipe to move · tap D-pad · arrow keys/WASD · space pauses
      </p>
    </div>
  );
}
