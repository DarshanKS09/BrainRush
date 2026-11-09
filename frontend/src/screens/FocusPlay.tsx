import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../api';
import type { WebAppContext } from '../telegram';
import { ErrorNotice, Loading } from '../components/ui';
import { haptic } from '../telegram';
import { MatchSubmitBanner } from '../components/MatchSubmit';

function ReplayButton({ ctx, onReplay }: { ctx: WebAppContext; onReplay: (sessionId: string) => void }) {
  return (
    <button
      onClick={async () => {
        const s = await api.start(ctx.initData, 'focus_rush', 'medium');
        onReplay(s.session_id);
      }}
      className="flex-1 rounded-xl bg-gradient-to-r from-neon-purple to-neon-cyan py-2.5 text-sm font-bold text-slate-200 active:scale-95"
    >
      Replay
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
  const [buffer, setBuffer] = useState('');
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
        const next = await api.guess(ctx.initData, sessionId, Number(raw), 'client-1');
        setState(next);
        setBuffer('');
        if (next.finished) haptic(next.result?.outcome === 'win' ? 'success' : 'error');
        else haptic('light');
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
        void submit(buffer);
        return;
      }
      setBuffer((b) => b + key);
    },
    [submit, buffer],
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
        <h2 className="mt-2 text-2xl font-bold text-white">{won ? 'You won!' : 'Out of lives!'}</h2>
        <p className="mt-1 text-sm text-slate-300">
          {won ? (
            <>
              Solved in {state.result.score} {state.result.score === 1 ? 'try' : 'tries'} ·
              <b className="text-neon-cyan">+{state.result.xp_earned} XP</b>
            </>
          ) : (
            <>The final round was {state.result.instruction} · <b className="text-neon-cyan">+{state.result.xp_earned} XP for playing</b></>
          )}
        </p>
        <div className="mt-4 flex gap-2">
          <button onClick={onExit} className="flex-1 rounded-xl bg-navy py-2.5 text-sm font-bold text-slate-200 active:scale-95">
            Lobby
          </button>
          <ReplayButton ctx={ctx} onReplay={onReplay} />
        </div>
        {matchId && onBackToMatch && (
          <MatchSubmitBanner ctx={ctx} matchId={matchId} sessionId={sessionId} onBackToMatch={onBackToMatch} />
        )}
      </div>
    );
  }

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
        <div className="mx-auto mt-2 flex h-16 max-w-[200px] items-center justify-center rounded-2xl bg-abyss text-4xl font-bold tracking-widest text-white" aria-live="polite">
          {buffer || <span className="text-slate-600">?</span>}
        </div>
        <div className="mt-3">
          {state.lives !== undefined && (
            <p className="text-slate-400">Lives: {state.lives}</p>
          )}
          {state.time_remaining !== undefined && (
            <p className="text-slate-400">Time: {state.time_remaining}s</p>
          )}
        </div>
        <button
          onClick={() => void submit(buffer)}
          disabled={busy || buffer === ''}
          className="mt-3 w-full rounded-xl bg-gradient-to-r from-neon-purple to-neon-cyan py-3 text-base font-bold text-white shadow-glow active:scale-[0.99] disabled:opacity-40"
        >
          {busy ? 'Processing…' : 'Submit'}
        </button>
      </div>

      <div className="rounded-2xl bg-panel p-3 shadow-card">
        {state.instruction && (
          <p className="text-white font-medium">{state.instruction}</p>
        )}
      </div>
    </div>
  );
}