import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../api';
import type { WebAppContext } from '../telegram';
import { ErrorNotice, Loading } from '../components/ui';

import { MatchSubmitBanner } from '../components/MatchSubmit';

type Color = 'red' | 'blue' | 'green' | 'yellow';
type Shape = 'circle' | 'square' | 'triangle' | 'diamond';

function ShapeButton({
  color,
  shape,
  onTap,
  isCorrect,
  isWrong,
  isDisabled,
}: {
  color: Color;
  shape: Shape;
  onTap: () => void;
  isCorrect?: boolean;
  isWrong?: boolean;
  isDisabled?: boolean;
}) {
  const colorBg: Record<Color, string> = {
    red: 'bg-rose-600',
    blue: 'bg-sky-600',
    green: 'bg-emerald-600',
    yellow: 'bg-amber-500',
  };
  const shapeClass: Record<Shape, string> = {
    circle: 'rounded-full',
    square: 'rounded-md',
    triangle: 'rotate-6',
    diamond: 'rotate-45',
  };

  const base = 'rounded-2xl p-3 shadow-md transition-transform hover:scale-[1.05]';

  return (
    <button
      onClick={onTap}
      disabled={isDisabled || isWrong}
      className={`${base} ${colorBg[color]} ${shapeClass[shape]} text-white flex items-center justify-center`}
      aria-label={isWrong ? 'Incorrect tap' : 'Tap shape'}
    >
      <svg
        className="w-6 h-6"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        {shape === 'circle' && <circle cx="12" cy="12" r="9" />}
        {shape === 'square' && <rect x="3" y="3" width="18" height="18" rx="2" />}
        {shape === 'triangle' && (
          <polygon
            points="12 3 3 21 21 21"
            fill="none"
            stroke="currentColor"
            strokeWidth="3"
          />
        )}
        {shape === 'diamond' && (
          <polygon
            points="12 3 19 12 12 21 5 12"
            fill="none"
            stroke="currentColor"
            strokeWidth="3"
          />
        )}
      </svg>
      {isCorrect && (
        <svg
          className="absolute -top-1 -right-1 w-4 h-4 text-green-400"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="3.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <path d="M20 6L9 17l-5-5" />
        </svg>
      )}
      {isWrong && (
        <svg
          className="absolute -top-1 -right-1 w-4 h-4 text-rose-400"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="3.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <circle cx="12" cy="12" r="10" />
          <line x1="15" y1="15" x2="9" y2="9" />
        </svg>
      )}
    </button>
  );
}

export default function FocusPlayScreen({
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
  const [state, setState] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const stateRef = useRef<any>(null);
  stateRef.current = state;

  const load = useCallback(() => {
    setError('');
    api
      .state(ctx.initData, sessionId)
      .then(setState)
      .catch((e: Error) => setError(e.message));
  }, [ctx.initData, sessionId]);

  useEffect(load, [load]);

  const submit = useCallback(
    async (raw: string) => {
      const current = stateRef.current;
      if (!current || current.finished || busy || raw === '') return;
      setBusy(true);
      try {
        if (current.game_type === 'focus_rush') {
          // For Focus Rush, submit a tap on the current target
          const target_color = current.target_color || 'blue';
          const target_shape = current.target_shape || 'circle';
          const next = await api.focus_tap(ctx.initData, sessionId, target_color, target_shape, 'client-1');
          setState(next);
        } else {
          // For other games, use guess
          const next = await api.guess(ctx.initData, sessionId, Number(raw), 'client-1');
          setState(next);
        }
      } catch (e) {
        /* ignore guess error */
      } finally {
        setBusy(false);
      }
    },
    [busy, ctx.initData, sessionId],
  );

  const onKey = useCallback(
    (key: string) => {
      if (key === 'enter') {
        submit('');
        return;
      }
    },
    [submit],
  );

  useEffect(() => {
    const onKeyboard = (e: KeyboardEvent) => {
      if (/^[0-9]$/.test(e.key)) onKey(e.key);
      else if (e.key === 'Backspace') onKey('back');
      else if (e.key === 'Enter') onKey('enter');
    };
    window.addEventListener('keydown', onKeyboard);
    return () => window.removeEventListener('keydown', onKeyboard);
  }, [onKey]);

  const cancel = async () => {
    try {
      await api.cancel(ctx.initData, sessionId);
    } catch {
      /* already gone: still exit */
    }
    onExit();
  };

  if (error && !state) return <ErrorNotice message={error} onRetry={load} />;
  if (!state) return <Loading label="Loading game…" />;

  if (state.finished && state.result) {
    const won = state.result.outcome === 'win';
    return (
      <div className={`rounded-3xl p-6 text-center shadow-card animate-pop ${won ? 'bg-panel animate-pulseWin' : 'bg-panel'}`}>
        <div className="text-5xl" aria-hidden>
          {won ? '🏆' : '💪'}
        </div>
        <h2 className="mt-2 text-2xl font-bold text-white">
          {won ? 'You won!' : 'Out of lives!'}
        </h2>
        <p className="mt-1 text-sm text-slate-300">
          {won ? (
            <>
              Solved in {state.result.score} {state.result.score === 1 ? 'try' : 'tries'} ·
              <b className="text-neon-cyan">+{state.result.xp_earned} XP</b>
            </>
          ) : (
            <>
              The final round was {state.result.instruction} ·
              <b className="text-neon-cyan">+{state.result.xp_earned} XP for playing</b>
            </>
          )}
        </p>
        <div className="mt-4 flex gap-2">
          <button onClick={onExit} className="flex-1 rounded-xl bg-navy py-2.5 text-sm font-bold text-slate-200 active:scale-95">
            Lobby
          </button>
          <button
            onClick={async () => {
              const s = await api.start(ctx.initData, 'focus_rush', 'medium');
              onReplay(s.session_id);
            }}
            className="flex-1 rounded-xl bg-gradient-to-r from-neon-purple to-neon-cyan py-2.5 text-sm font-bold text-slate-200 active:scale-95"
          >
            Replay
          </button>
        </div>
        {matchId && onBackToMatch && (
          <MatchSubmitBanner ctx={ctx} matchId={matchId} sessionId={sessionId} onBackToMatch={onBackToMatch} />
        )}
      </div>
    );
  }

  const instruction =
    state.instruction ||
    'Tap only ' +
      (state.target_color || 'blue') +
      ' ' +
      (state.target_shape || 'circle');

  const displayTargets = state.display_targets || [];
  const targetColor = state.target_color || 'blue';
  const targetShape = state.target_shape || 'circle';

  // Build the grid of shapes to display
  const shapes: Shape[] = ['circle', 'square', 'triangle', 'diamond'];
  const colors: Color[] = ['red', 'blue', 'green', 'yellow'];

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <button onClick={onExit} className="rounded-xl bg-panel px-3 py-1.5 text-sm font-semibold text-slate-300 active:scale-95" aria-label="Back to lobby">
          ← Lobby
        </button>
        <span className="rounded-full bg-panel px-3 py-1 text-xs font-bold uppercase tracking-wider text-neon-cyan">
          {state.difficulty}
        </span>
        <button onClick={cancel} className="rounded-xl bg-panel px-3 py-1.5 text-sm font-semibold text-rose-300 active:scale-95" aria-label="Cancel game">
          ✕ Give up
        </button>
      </div>

      <div className="rounded-3xl bg-panel p-5 text-center shadow-card">
        <p className="text-xs uppercase tracking-widest text-slate-400">
          Focus Rush · {state.difficulty}
        </p>

        {/* Instruction display */}
        <div className="mt-3 text-lg font-bold text-white">
          {instruction}
        </div>

        {/* Shape grid - 4x4 grid of clickable shapes */}
        <div className="mt-4 grid grid-cols-4 gap-2 max-w-md mx-auto">
          {displayTargets.map((t: any, idx: number) => {
            const color = t.color || targetColor;
            const shape = t.shape || targetShape;
            const isTarget =
              (color === targetColor || color === (state.target_color || 'blue')) &&
              (shape === targetShape || shape === (state.target_shape || 'circle'));

            return (
              <ShapeButton
                key={idx}
                color={color as Color}
                shape={shape as Shape}
                onTap={() => submit(shape)}
                isCorrect={isTarget && !state.finished}
                isWrong={!isTarget && !state.finished}
                isDisabled={state.finished}
              />
            );
          })}

          {/* Add distractors to fill a 4x4 grid (16 total) */}
          {displayTargets.length < 16 && shapes.map((shape, sIdx) => {
            // Pick a color different from the target color if possible
            const targetC = targetColor;
            const availableColors = colors.filter(
              (c) => c !== targetC
            );
            const color = availableColors[sIdx % availableColors.length];

            return (
              <ShapeButton
                key={sIdx}
                color={color}
                shape={shape}
                onTap={() => submit(shape)}
                isWrong={true}
                isDisabled={state.finished}
              />
            );
          })}

          {/* Fill remaining spots with random distractors */}
          {displayTargets.length < 16 && colors
            .slice(displayTargets.length)
            .slice(0, 16 - displayTargets.length)
            .map((color, cIdx) => (
              <ShapeButton
                key={cIdx}
                color={color}
                shape='circle'
                onTap={() => void submit('circle')}
                isWrong={true}
                isDisabled={state.finished}
              />
            ))}
        </div>

        {/* Lives and timer */}
        <div className="mt-4 flex justify-between text-sm text-slate-300">
          <span>Lives: {state.lives !== undefined ? state.lives : 3}</span>
          <span>Time: {state.time_remaining !== undefined ? state.time_remaining : 60}s</span>
        </div>

        {/* Submit / Next Round button */}
        {(!state.finished || state.next_round) && (
          <button
            onClick={() => void submit('')}
            disabled={busy}
            className="mt-3 w-full rounded-xl bg-gradient-to-r from-neon-purple to-neon-cyan py-3 text-base font-bold text-white shadow-glow active:scale-[0.99] disabled:opacity-40"
          >
            {busy ? 'Processing…' : 'Next Round'}
          </button>
        )}
      </div>

      <div className="rounded-2xl bg-panel p-3 shadow-card">
        {state.instruction && (
          <p className="text-white font-medium">{state.instruction}</p>
        )}
      </div>
    </div>
  );
}