import { useCallback, useEffect, useRef, useState } from 'react';
import { api, newClientGuessId, type PerfectState } from '../api';
import type { WebAppContext } from '../telegram';
import { formatSeconds, perfectVerdict } from '../gameutil';
import { ErrorNotice, Loading } from '../components/ui';
import { MatchSubmitBanner } from '../components/MatchSubmit';
import { haptic } from '../telegram';

type Phase = 'ready' | 'running';

function formatElapsed(ms: number): string {
  return `${(ms / 1000).toFixed(2)} s`;
}

export function PerfectPlayScreen({
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
  const [view, setView] = useState<PerfectState | null>(null);
  const [best, setBest] = useState<number | null>(null);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [phase, setPhase] = useState<Phase>('ready');
  const [elapsed, setElapsed] = useState(0);
  const [submitting, setSubmitting] = useState(false);
  const [replaying, setReplaying] = useState(false);

  // Monotonic clock base. rAF is display-only; the STOP handler reads
  // performance.now() directly, so background throttling cannot skew it.
  const startedAt = useRef(0);
  const raf = useRef(0);
  const submitted = useRef(false);
  const submissionId = useRef(newClientGuessId());
  const phaseRef = useRef(phase);
  phaseRef.current = phase;
  const runningRef = useRef(false);

  const stopLoop = () => {
    runningRef.current = false;
    cancelAnimationFrame(raf.current);
  };

  useEffect(() => stopLoop, []);

  const load = useCallback(() => {
    setError('');
    Promise.all([api.perfectState(ctx.initData, sessionId), api.me(ctx.initData)])
      .then(([state, me]) => {
        setView(state);
        setBest(me.best_perfect_error_ms ?? null);
        // A resumed attempt restarts the clock with the same server target.
        setPhase('ready');
        setElapsed(0);
      })
      .catch((e: Error) => setError(e.message));
  }, [ctx.initData, sessionId]);

  useEffect(load, [load]);

  const tick = useCallback(() => {
    if (!runningRef.current) return;
    setElapsed(performance.now() - startedAt.current);
    raf.current = requestAnimationFrame(tick);
  }, []);

  const begin = useCallback(() => {
    submitted.current = false;
    setNotice('');
    setElapsed(0);
    startedAt.current = performance.now();
    runningRef.current = true;
    setPhase('running');
    raf.current = requestAnimationFrame(tick);
    haptic('light');
  }, [tick]);

  // Hidden tabs freeze rAF; the monotonic base is unaffected, so just
  // resume rendering when visible again.
  useEffect(() => {
    const onVis = () => {
      if (document.visibilityState === 'visible' && phaseRef.current === 'running' && !runningRef.current) {
        runningRef.current = true;
        raf.current = requestAnimationFrame(tick);
      }
    };
    document.addEventListener('visibilitychange', onVis);
    return () => document.removeEventListener('visibilitychange', onVis);
  }, [tick]);

  const stop = useCallback(async () => {
    if (phaseRef.current !== 'running' || submitted.current || submitting || !view || view.finished) return;
    // Capture the stopping time immediately; the guard below prevents
    // double STOP submissions from double taps or key repeats.
    const finalMs = performance.now() - startedAt.current;
    submitted.current = true;
    stopLoop();
    setSubmitting(true);
    setNotice('');
    try {
      const done = await api.stopPerfect(ctx.initData, sessionId, finalMs, submissionId.current);
      setView(done);
      haptic(done.result && done.result.accuracy_percent >= 90 ? 'success' : 'error');
    } catch (e) {
      // Retry reuses the same submission id; the backend replay path keeps
      // it idempotent, and the phase stays running so the clock continues.
      submitted.current = false;
      startedAt.current = performance.now() - finalMs;
      runningRef.current = true;
      raf.current = requestAnimationFrame(tick);
      setNotice(e instanceof Error ? e.message : 'Submit failed. Try again.');
    } finally {
      setSubmitting(false);
    }
  }, [ctx.initData, sessionId, submitting, tick, view]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === ' ' || e.key === 'Enter') {
        e.preventDefault();
        if (e.repeat) return;
        if (phaseRef.current === 'ready' && view && !view.finished) begin();
        else void stop();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [begin, stop, view]);

  const cancel = async () => {
    stopLoop();
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
      // Replay always mints a fresh random target server-side.
      const s = await api.start(ctx.initData, 'perfect_second', view.difficulty);
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
    const isBest = best !== null && r.score < best;
    const perfect = r.accuracy_percent >= 100;
    return (
      <div className={`rounded-3xl bg-panel p-6 text-center shadow-card animate-pop ${perfect ? 'animate-pulseWin' : ''}`}>
        <div className="text-5xl" aria-hidden>
          {perfect ? '🏆' : r.outcome === 'win' ? '🎯' : '💪'}
        </div>
        <h2 className="mt-2 text-2xl font-bold text-white">{perfectVerdict(r.accuracy_percent)}</h2>
        <div className="mx-auto mt-3 max-w-xs space-y-1 text-sm" aria-label="Attempt results">
          <div className="flex justify-between rounded-xl bg-navy px-3 py-1.5">
            <span className="text-slate-400">Target</span>
            <b className="text-white">{formatSeconds(r.target_ms, view.difficulty)}</b>
          </div>
          <div className="flex justify-between rounded-xl bg-navy px-3 py-1.5">
            <span className="text-slate-400">You stopped at</span>
            <b className="text-white">{formatSeconds(r.actual_ms, view.difficulty)}</b>
          </div>
          <div className="flex justify-between rounded-xl bg-navy px-3 py-1.5">
            <span className="text-slate-400">Error</span>
            <b className="text-white">{formatSeconds(r.error_ms, view.difficulty)}</b>
          </div>
          <div className="flex justify-between rounded-xl bg-navy px-3 py-1.5">
            <span className="text-slate-400">Accuracy</span>
            <b className="text-neon-cyan">{r.accuracy_percent.toFixed(1)}%</b>
          </div>
          <div className="flex justify-between rounded-xl bg-navy px-3 py-1.5">
            <span className="text-slate-400">XP earned</span>
            <b className="text-neon-cyan">+{r.xp_earned} XP</b>
          </div>
        </div>
        {isBest && <p className="mt-2 text-sm font-bold text-amber-300">🎉 New personal best!</p>}
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
            Games
          </button>
          <button
            onClick={replay}
            disabled={replaying}
            className="flex-1 rounded-xl bg-gradient-to-r from-neon-purple to-neon-cyan py-2.5 text-sm font-bold text-white shadow-glow active:scale-95 disabled:opacity-50"
          >
            {replaying ? 'Starting…' : '↻ Play again'}
          </button>
        </div>
        {matchId && onBackToMatch && (
          <MatchSubmitBanner ctx={ctx} matchId={matchId} sessionId={sessionId} onBackToMatch={onBackToMatch} />
        )}
      </div>
    );
  }

  const targetText = formatSeconds(view.target_ms, view.difficulty);
  // Hard mode hides the running readout: the clock runs internally, but no
  // changing numeric value may appear until after STOP. The target stays
  // visible in every mode; this branch is phase-driven so reconnects and
  // result transitions cannot leak the timer either.
  const hideRunning = view.difficulty === 'hard' && phase === 'running';

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
          {view.difficulty} · 🎯 {targetText}
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
        <p className="text-xs uppercase tracking-widest text-slate-400">Target time</p>
        <div className="mt-1 text-5xl font-black tabular-nums text-neon-cyan" aria-live="polite">
          {targetText}
        </div>
        <div
          className="mx-auto mt-3 flex h-24 max-w-xs items-center justify-center rounded-2xl bg-abyss text-5xl font-black tabular-nums text-white"
          aria-live="polite"
          aria-label={hideRunning ? 'Elapsed time hidden until you stop' : `Elapsed time ${formatElapsed(elapsed)}`}
        >
          {phase === 'running' ? (hideRunning ? '– – . – –' : formatElapsed(elapsed)) : '0.00 s'}
        </div>
        {hideRunning && (
          <p className="mt-1 text-xs text-slate-400">Hard mode: trust your sense of time — no live readout.</p>
        )}
        {best !== null && (
          <p className="mt-2 text-xs text-slate-400">⏱️ Personal best error: {formatSeconds(best, view.difficulty)}</p>
        )}
        {notice && (
          <p className="mt-2 text-sm text-amber-300" role="alert">
            {notice}
          </p>
        )}
        {phase === 'ready' ? (
          <>
            <p className="mx-auto mt-2 max-w-xs text-sm text-slate-300">
              Tap START, then tap STOP exactly when you believe {targetText} have passed.
              {view.difficulty === 'hard' && ' The live timer stays hidden — feel the seconds.'}
            </p>
            <button
              onClick={begin}
              className="mt-3 w-full rounded-xl bg-gradient-to-r from-neon-purple to-neon-cyan py-3 text-base font-bold text-white shadow-glow active:scale-[0.99]"
            >
              ▶ Start clock
            </button>
          </>
        ) : (
          <button
            onClick={() => void stop()}
            disabled={submitting}
            className="mt-3 w-full rounded-xl bg-rose-500 py-4 text-xl font-black text-white shadow-card active:scale-[0.99] disabled:opacity-60"
          >
            {submitting ? 'Stopping…' : '■ STOP'}
          </button>
        )}
      </div>
      <p className="text-center text-[11px] text-slate-500">
        Space / Enter starts and stops · the clock is high-resolution and pauses safely in background
      </p>
    </div>
  );
}
