import { useCallback, useEffect, useRef, useState } from 'react';
import { api, newClientGuessId, type GameState } from '../api';
import { keypadReducer } from '../gameutil';
import type { WebAppContext } from '../telegram';
import { AttemptPips, GuessHistory, Keypad } from '../components/game';
import { ErrorNotice, Loading } from '../components/ui';
import { haptic } from '../telegram';

export function PlayScreen({
  ctx,
  sessionId,
  onExit,
  onReplay,
}: {
  ctx: WebAppContext;
  sessionId: string;
  onExit: () => void;
  onReplay: (sessionId: string) => void;
}) {
  const [state, setState] = useState<GameState | null>(null);
  const [buffer, setBuffer] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const stateRef = useRef<GameState | null>(null);
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
      setNotice('');
      try {
        const next = await api.guess(ctx.initData, sessionId, Number(raw), newClientGuessId());
        setState(next);
        setBuffer('');
        if (next.finished) haptic(next.result?.outcome === 'win' ? 'success' : 'error');
        else haptic('light');
      } catch (e) {
        setNotice(e instanceof Error ? e.message : 'Guess failed. Try again.');
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
      setBuffer((b) => keypadReducer(b, key));
    },
    [buffer, submit],
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
        <h2 className="mt-2 text-2xl font-bold text-white">{won ? 'You won!' : 'Out of guesses!'}</h2>
        <p className="mt-1 text-sm text-slate-300">
          {won ? (
            <>Solved in {state.result.score} {state.result.score === 1 ? 'try' : 'tries'} · <b className="text-neon-cyan">+{state.result.xp_earned} XP</b></>
          ) : (
            <>The number was <b className="text-white">{state.result.secret}</b> · <b className="text-neon-cyan">+{state.result.xp_earned} XP</b> for playing</>
          )}
        </p>
        <GuessHistory guesses={state.guesses} />
        <div className="mt-4 flex gap-2">
          <button onClick={onExit} className="flex-1 rounded-xl bg-navy py-2.5 text-sm font-bold text-slate-200 active:scale-95">
            Lobby
          </button>
          <ReplayButton ctx={ctx} onReplay={onReplay} />
        </div>
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
        <p className="text-xs uppercase tracking-widest text-slate-400">Guess the number · 1–100</p>
        <div className="mx-auto mt-2 flex h-16 max-w-[200px] items-center justify-center rounded-2xl bg-abyss text-4xl font-bold tracking-widest text-white" aria-live="polite">
          {buffer || <span className="text-slate-600">?</span>}
        </div>
        <div className="mt-3">
          <AttemptPips used={state.attempts_used} max={state.max_attempts} />
          <p className="mt-1 text-xs text-slate-400">{state.attempts_left} attempts left</p>
        </div>
        {notice && (
          <p className="mt-2 text-sm text-amber-300" role="alert">
            {notice}
          </p>
        )}
        <button
          onClick={() => void submit(buffer)}
          disabled={busy || buffer === ''}
          className="mt-3 w-full rounded-xl bg-gradient-to-r from-neon-purple to-neon-cyan py-3 text-base font-bold text-white shadow-glow active:scale-[0.99] disabled:opacity-40"
        >
          {busy ? 'Sending…' : 'Guess'}
        </button>
      </div>

      <Keypad onKey={onKey} disabled={busy} />

      <div className="rounded-2xl bg-panel p-3 shadow-card">
        <GuessHistory guesses={state.guesses} />
      </div>
    </div>
  );
}

function ReplayButton({ ctx, onReplay }: { ctx: WebAppContext; onReplay: (id: string) => void }) {
  const [busy, setBusy] = useState(false);
  return (
    <button
      onClick={async () => {
        setBusy(true);
        try {
          // Replay keeps it simple: medium difficulty rematch.
          const s = await api.start(ctx.initData, 'number_guessing', 'medium');
          onReplay(s.session_id);
        } finally {
          setBusy(false);
        }
      }}
      disabled={busy}
      className="flex-1 rounded-xl bg-gradient-to-r from-neon-purple to-neon-cyan py-2.5 text-sm font-bold text-white shadow-glow active:scale-95 disabled:opacity-50"
    >
      {busy ? 'Starting…' : '↻ Play again'}
    </button>
  );
}
