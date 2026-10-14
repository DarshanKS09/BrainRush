import { useCallback, useEffect, useRef, useState } from 'react';
import { api, newClientGuessId, type ReflexState } from '../api';
import type { WebAppContext } from '../telegram';
import { formatMs } from '../gameutil';
import {
  REFLEX_ROUNDS,
  countFalseStarts,
  randomWaitMs,
  reflexAverage,
  reflexBest,
  waitWindow,
  type LocalRound,
} from '../reflexutil';
import { ErrorNotice, Loading } from '../components/ui';
import { haptic } from '../telegram';

type Phase = 'waiting' | 'active';

export function ReflexPlayScreen({
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
  const [view, setView] = useState<ReflexState | null>(null);
  const [best, setBest] = useState<number | null>(null);
  const [wait, setWait] = useState({ min: 1000, max: 3000 });
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [started, setStarted] = useState(false);
  const [roundIndex, setRoundIndex] = useState(0);
  const [phase, setPhase] = useState<Phase>('waiting');
  const [rounds, setRounds] = useState<LocalRound[]>([]);
  const [lastMs, setLastMs] = useState<number | null>(null);
  const [lastFalse, setLastFalse] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [replaying, setReplaying] = useState(false);
  const [reducedMotion, setReducedMotion] = useState(false);

  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const activeSince = useRef(0);
  const submitted = useRef(false);
  const submissionId = useRef(newClientGuessId());
  const locked = useRef(false);
  const stateRef = useRef({ roundIndex, phase, started });
  stateRef.current = { roundIndex, phase, started };

  const clearTimer = () => {
    if (timer.current) {
      clearTimeout(timer.current);
      timer.current = null;
    }
  };

  useEffect(() => {
    try {
      const mq = window.matchMedia?.('(prefers-reduced-motion: reduce)');
      setReducedMotion(!!mq?.matches);
    } catch {
      /* decoration only */
    }
  }, []);

  // All outstanding timers die with the component.
  useEffect(() => clearTimer, []);

  const load = useCallback(() => {
    setError('');
    Promise.all([api.reflexState(ctx.initData, sessionId), api.me(ctx.initData), api.games(ctx.initData)])
      .then(([state, me, games]) => {
        setView(state);
        setBest(me.best_reflex_score ?? null);
        const entry = games.games.find((g) => g.id === 'reflex_rush');
        if (entry) setWait(waitWindow(entry.difficulties, state.difficulty));
        if (state.finished || (state.rounds_played ?? 0) > 0) setStarted(true);
      })
      .catch((e: Error) => setError(e.message));
  }, [ctx.initData, sessionId]);

  useEffect(load, [load]);

  const scheduleWait = useCallback(
    (index: number) => {
      clearTimer();
      locked.current = false;
      setPhase('waiting');
      setRoundIndex(index);
      const ms = randomWaitMs(wait.min, wait.max);
      timer.current = setTimeout(() => {
        activeSince.current = performance.now();
        setPhase('active');
      }, ms);
    },
    [wait],
  );

  const begin = () => {
    setStarted(true);
    setRounds([]);
    setLastMs(null);
    setLastFalse(false);
    scheduleWait(0);
  };

  const submit = useCallback(
    async (finalRounds: LocalRound[]) => {
      if (submitted.current || submitting) return;
      submitted.current = true;
      setSubmitting(true);
      setNotice('');
      try {
        const done = await api.finishReflex(ctx.initData, sessionId, finalRounds, submissionId.current);
        setView(done);
        haptic(done.result?.outcome === 'win' ? 'success' : 'error');
      } catch (e) {
        // Retry reuses the same submission id: the backend replay path
        // makes this idempotent (no double XP on success-then-retry).
        submitted.current = false;
        setNotice(e instanceof Error ? e.message : 'Submit failed. Try again.');
      } finally {
        setSubmitting(false);
      }
    },
    [ctx.initData, sessionId, submitting],
  );

  const advance = useCallback(
    (next: LocalRound[]) => {
      if (next.length >= REFLEX_ROUNDS) {
        clearTimer();
        void submit(next);
        return;
      }
      // Brief beat so the per-round result is readable, then next wait.
      clearTimer();
      timer.current = setTimeout(() => scheduleWait(next.length), 900);
    },
    [scheduleWait, submit],
  );

  const tap = useCallback(() => {
    const s = stateRef.current;
    if (!s.started || submitting || view?.finished || rounds.length >= REFLEX_ROUNDS) return;
    if (locked.current) return; // one tap scores each round
    if (s.phase === 'waiting') {
      locked.current = true;
      clearTimer();
      const next: LocalRound[] = [...rounds, { reaction_ms: null, false_start: true }];
      setRounds(next);
      setLastMs(null);
      setLastFalse(true);
      haptic('error');
      advance(next);
      return;
    }
    locked.current = true;
    const ms = Math.max(1, Math.round(performance.now() - activeSince.current));
    const next: LocalRound[] = [...rounds, { reaction_ms: ms, false_start: false }];
    setRounds(next);
    setLastMs(ms);
    setLastFalse(false);
    haptic('light');
    advance(next);
  }, [advance, rounds, submitting, view]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === ' ' || e.key === 'Enter') {
        e.preventDefault();
        tap();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [tap]);

  const cancel = async () => {
    clearTimer();
    try {
      await api.cancel(ctx.initData, sessionId);
    } catch {
      /* already gone: still exit */
    }
    onExit();
  };

  const replay = async () => {
    if (!view || replaying) return;
    setReplaying(true);
    try {
      const s = await api.start(ctx.initData, 'reflex_rush', view.difficulty);
      onReplay(s.session_id);
    } catch (e) {
      setNotice(e instanceof Error ? e.message : 'Could not start a new game.');
    } finally {
      setReplaying(false);
    }
  };

  if (error && !view) return <ErrorNotice message={error} onRetry={load} />;
  if (!view) return <Loading label="Loading game…" />;

  if (view.finished && view.result) {
    const r = view.result;
    const isBest = best !== null && r.score > best;
    return (
      <div className="rounded-3xl bg-panel p-6 text-center shadow-card animate-pop">
        <div className="text-5xl" aria-hidden>
          {r.outcome === 'win' ? '⚡' : '💪'}
        </div>
        <h2 className="mt-2 text-2xl font-bold text-white">
          {r.outcome === 'win' ? 'Lightning reflexes!' : 'Run complete!'}
        </h2>
        <p className="mt-1 text-sm text-slate-300">
          Avg <b className="text-white">{formatMs(r.avg_ms)}</b> · Best{' '}
          <b className="text-white">{formatMs(r.best_ms)}</b> · Score{' '}
          <b className="text-neon-cyan">{r.score}</b> · <b className="text-neon-cyan">+{r.xp_earned} XP</b>
        </p>
        {r.false_starts > 0 && (
          <p className="mt-1 text-xs text-amber-300">
            {r.false_starts} false start{r.false_starts === 1 ? '' : 's'} (0 pts each)
          </p>
        )}
        {isBest && <p className="mt-1 text-sm font-bold text-amber-300">🎉 New personal best!</p>}
        <ul className="mx-auto mt-3 max-w-xs space-y-1" aria-label="Round results">
          {r.rounds.map((rd, i) => (
            <li
              key={i}
              className="flex justify-between rounded-xl bg-navy px-3 py-1.5 text-xs text-slate-300"
            >
              <span>Round {i + 1}</span>
              <span className={rd.false_start ? 'font-bold text-amber-300' : 'font-bold text-emerald-300'}>
                {rd.false_start ? 'False start' : `${rd.reaction_ms} ms`}
              </span>
            </li>
          ))}
        </ul>
        {notice && (
          <p className="mt-2 text-sm text-amber-300" role="alert">
            {notice}
          </p>
        )}
        <div className="mt-4 flex gap-2">
          <button
            onClick={onExit}
            className="flex-1 rounded-xl bg-navy py-2.5 text-sm font-bold text-slate-200 active:scale-95"
          >
            Lobby
          </button>
          <button
            onClick={replay}
            disabled={replaying}
            className="flex-1 rounded-xl bg-gradient-to-r from-neon-purple to-neon-cyan py-2.5 text-sm font-bold text-white shadow-glow active:scale-95 disabled:opacity-50"
          >
            {replaying ? 'Starting…' : '↻ Play again'}
          </button>
        </div>
      </div>
    );
  }

  if (!started) {
    return (
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <button
            onClick={onExit}
            className="rounded-xl bg-panel px-3 py-1.5 text-sm font-semibold text-slate-300 active:scale-95"
            aria-label="Back to lobby"
          >
            ← Lobby
          </button>
          <span className="rounded-full bg-panel px-3 py-1 text-xs font-bold uppercase tracking-wider text-neon-cyan">
            {view.difficulty} · 5 rounds
          </span>
          <button
            onClick={cancel}
            className="rounded-xl bg-panel px-3 py-1.5 text-sm font-semibold text-rose-300 active:scale-95"
            aria-label="Cancel game"
          >
            ✕ Give up
          </button>
        </div>
        <div className="rounded-3xl bg-panel p-6 text-center shadow-card animate-pop">
          <div className="text-5xl" aria-hidden>
            ⚡
          </div>
          <h2 className="mt-3 text-xl font-bold text-white">Wait for green, then tap as fast as you can.</h2>
          <p className="mx-auto mt-2 max-w-xs text-sm text-slate-300">
            Five rounds. Tapping before the target turns green is a false start: that round scores 0
            points but still counts. Faster valid taps earn more points and XP.
          </p>
          {best !== null && <p className="mt-2 text-xs text-slate-400">⚡ Personal best score: {best}</p>}
          <button
            onClick={begin}
            className="mt-4 w-full rounded-xl bg-gradient-to-r from-neon-purple to-neon-cyan py-3 text-base font-bold text-white shadow-glow active:scale-[0.99]"
          >
            ▶ Start Game
          </button>
        </div>
      </div>
    );
  }

  const avg = reflexAverage(rounds);
  const bestSoFar = reflexBest(rounds);
  const done = rounds.length >= REFLEX_ROUNDS;

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <button
          onClick={onExit}
          className="rounded-xl bg-panel px-3 py-1.5 text-sm font-semibold text-slate-300 active:scale-95"
          aria-label="Back to lobby"
        >
          ← Lobby
        </button>
        <span className="rounded-full bg-panel px-3 py-1 text-xs font-bold uppercase tracking-wider text-neon-cyan">
          {view.difficulty} · Round {Math.min(roundIndex + 1, REFLEX_ROUNDS)}/{REFLEX_ROUNDS}
        </span>
        <button
          onClick={cancel}
          className="rounded-xl bg-panel px-3 py-1.5 text-sm font-semibold text-rose-300 active:scale-95"
          aria-label="Cancel game"
        >
          ✕ Give up
        </button>
      </div>

      <div className="rounded-3xl bg-panel p-5 text-center shadow-card">
        <div className="flex justify-center gap-1.5" aria-label={`Round progress ${rounds.length} of ${REFLEX_ROUNDS}`}>
          {Array.from({ length: REFLEX_ROUNDS }).map((_, i) => (
            <span key={i} className={`h-2 w-6 rounded-full ${i < rounds.length ? 'bg-neon-cyan' : 'bg-navy'}`} />
          ))}
        </div>
        <p className="mt-2 text-xs uppercase tracking-widest text-slate-400" aria-live="polite">
          {submitting || done
            ? 'Submitting your time…'
            : phase === 'waiting'
              ? '🔴 Wait for green…'
              : '🟢 TAP NOW!'}
        </p>
        {lastMs !== null && !lastFalse && (
          <p className="mt-1 text-sm font-bold text-emerald-300" aria-live="polite">
            ✅ {lastMs} ms — nice!
          </p>
        )}
        {lastFalse && (
          <p className="mt-1 text-sm font-bold text-amber-300" aria-live="polite">
            ⚠️ False start — 0 pts for that round.
          </p>
        )}
        <div className="mt-1 flex justify-center gap-4 text-xs text-slate-400">
          <span>
            Avg: <b className="text-white">{avg === null ? '—' : `${avg} ms`}</b>
          </span>
          <span>
            Best: <b className="text-white">{bestSoFar === null ? '—' : `${bestSoFar} ms`}</b>
          </span>
          <span>
            False starts: <b className="text-white">{countFalseStarts(rounds)}</b>
          </span>
        </div>
        {notice && (
          <div className="mt-2">
            <p className="text-sm text-amber-300" role="alert">
              {notice}
            </p>
            <button
              onClick={() => void submit(rounds)}
              className="mt-1 rounded-xl bg-navy px-4 py-1.5 text-sm font-bold text-white active:scale-95"
            >
              Retry submit
            </button>
          </div>
        )}
      </div>

      <button
        onClick={tap}
        disabled={submitting || done}
        aria-label={phase === 'active' ? 'Tap now' : 'Wait for green'}
        className={`flex h-64 w-full items-center justify-center rounded-3xl text-2xl font-black text-white shadow-card transition-colors disabled:opacity-80 ${
          phase === 'active' ? 'bg-emerald-400 text-emerald-950' : 'bg-rose-600'
        } ${reducedMotion ? '' : 'active:scale-[0.98]'}`}
      >
        {submitting || done ? '…' : phase === 'active' ? 'TAP!' : 'WAIT…'}
      </button>
      <p className="text-center text-[11px] text-slate-500">
        Space / Enter works too · one tap per round · timers are cleaned up if you leave
      </p>
    </div>
  );
}
