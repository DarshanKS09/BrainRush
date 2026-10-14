import { useCallback, useEffect, useRef, useState } from 'react';
import { api, newClientGuessId, type ColorState } from '../api';
import type { WebAppContext } from '../telegram';
import { MatchSubmitBanner } from '../components/MatchSubmit';
import { ErrorNotice, Loading } from '../components/ui';
import { haptic } from '../telegram';

/** Gap between a completed round and the next level's playback. */
export const ROUND_TRANSITION_MS = 2000;
const TRANSITION_TICK_MS = 100;

const COLORS = [
  { name: 'Red', base: 'bg-rose-700', lit: 'bg-rose-300 scale-[1.06] brightness-150 ring-4 ring-rose-100/80 shadow-[0_0_64px_rgba(251,113,133,1)]' },
  { name: 'Green', base: 'bg-emerald-700', lit: 'bg-emerald-200 scale-[1.06] brightness-150 ring-4 ring-emerald-100/80 shadow-[0_0_64px_rgba(110,231,183,1)]' },
  { name: 'Blue', base: 'bg-sky-700', lit: 'bg-sky-200 scale-[1.06] brightness-150 ring-4 ring-sky-100/80 shadow-[0_0_64px_rgba(125,211,252,1)]' },
  { name: 'Yellow', base: 'bg-amber-600', lit: 'bg-amber-100 scale-[1.06] brightness-150 ring-4 ring-amber-100/80 shadow-[0_0_64px_rgba(252,211,77,1)]' },
];
const FREQS = [261.6, 329.6, 392.0, 523.3];

function beep(index: number, ms: number): void {
  try {
    const Ctx = window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (!Ctx) return;
    const ctx = new Ctx();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = 'sine';
    osc.frequency.value = FREQS[index] ?? 440;
    gain.gain.setValueAtTime(0.12, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + ms / 1000);
    osc.connect(gain).connect(ctx.destination);
    osc.start();
    osc.stop(ctx.currentTime + ms / 1000);
    void ctx.resume?.();
  } catch {
    /* audio is decoration only */
  }
}

export function ColorPlayScreen({
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
  const [view, setView] = useState<ColorState | null>(null);
  const [playbackMs, setPlaybackMs] = useState(500);
  const [best, setBest] = useState<number | null>(null);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [showing, setShowing] = useState(false);
  const [flash, setFlash] = useState<number | null>(null);
  const [replaying, setReplaying] = useState(false);
  const [started, setStarted] = useState(false);
  const [transitionMs, setTransitionMs] = useState<number | null>(null);
  // Taps accepted but not yet confirmed by the server. Added to the
  // displayed progress immediately (optimistic); the server view remains
  // authoritative and every terminal/error path resets this to 0.
  const [pending, setPending] = useState(0);
  const viewRef = useRef<ColorState | null>(null);
  viewRef.current = view;
  const playedLevel = useRef<string>('');
  const tapFlashTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Rapid-tap queue: taps are accepted immediately and sent strictly one
  // at a time (order preserved, so the server always validates the tap the
  // player intended). No cooldown, no busy-gating.
  const queueRef = useRef<{ color: number; id: string }[]>([]);
  const pumpingRef = useRef(false);
  const mountedRef = useRef(true);

  // Tap acknowledgment timers must not outlive the component.
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      if (tapFlashTimer.current) clearTimeout(tapFlashTimer.current);
    };
  }, []);

  const load = useCallback(() => {
    setError('');
    Promise.all([
      api.colorState(ctx.initData, sessionId),
      api.me(ctx.initData),
      api.games(ctx.initData),
    ])
      .then(([state, me, games]) => {
        setView(state);
        setBest(me.best_color_level);
        const colorGame = games.games.find((g) => g.id === 'color_sequence');
        const diff = colorGame?.difficulties.find((d) => d.id === state.difficulty);
        if (diff?.playback_ms) setPlaybackMs(diff.playback_ms);
        // Resumed mid-run games skip the instructions.
        if (state.moves.length > 0 || state.levels_completed > 0) {
          setStarted(true);
        }
      })
      .catch((e: Error) => setError(e.message));
  }, [ctx.initData, sessionId]);

  useEffect(load, [load]);

  // Round transition: single chained timeout, cleaned up on unmount,
  // restart, or when a new transition supersedes it.
  useEffect(() => {
    if (transitionMs === null) return;
    if (transitionMs <= 0) {
      setTransitionMs(null);
      return;
    }
    const t = setTimeout(() => {
      setTransitionMs((ms) => (ms === null ? null : ms - TRANSITION_TICK_MS));
    }, TRANSITION_TICK_MS);
    return () => clearTimeout(t);
  }, [transitionMs]);

  // Play back the level's prefix when a new level arrives, once the
  // player has pressed Start and no transition is running. The key tracks
  // session + level only: mid-level taps must NOT replay (the server keeps
  // advancing position, so a replay would invite repeating from the start
  // and get a correct color rejected).
  useEffect(() => {
    if (!view || view.finished || !started || transitionMs !== null) return;
    const key = `${view.session_id}:${view.level}`;
    if (playedLevel.current === key) return;
    playedLevel.current = key;
    setShowing(true);
    setFlash(null);
    const timers: ReturnType<typeof setTimeout>[] = [];
    const step = playbackMs + 160;
    view.display.forEach((color, i) => {
      timers.push(
        setTimeout(() => {
          setFlash(color);
          beep(color, playbackMs);
        }, 450 + i * step),
      );
      timers.push(setTimeout(() => setFlash(null), 450 + i * step + playbackMs));
    });
    timers.push(setTimeout(() => setShowing(false), 450 + view.display.length * step));
    return () => timers.forEach(clearTimeout);
  }, [view, playbackMs, started, transitionMs]);

  const pump = useCallback(async () => {
    // Strictly sequential sender: at most one request in flight, so taps
    // can never arrive out of order and be wrongly rejected.
    if (pumpingRef.current) return;
    pumpingRef.current = true;
    try {
      while (queueRef.current.length > 0) {
        const current = viewRef.current;
        if (!current || current.finished) { queueRef.current = []; setPending(0); break; }
        if (current.session_id !== sessionId) break; // stale session (replay)
        if (!mountedRef.current) break;
        const head = queueRef.current[0];
        let next: ColorState;
        try {
          next = await api.move(ctx.initData, sessionId, head.color, head.id);
        } catch (e) {
          // Drop buffered taps (their fate is unknown) and resync from the
          // server, which remains the single source of truth for position.
          queueRef.current = [];
          setPending(0);
          setNotice(e instanceof Error ? e.message : 'Tap failed. Try again.');
          try {
            if (mountedRef.current) setView(await api.colorState(ctx.initData, sessionId));
          } catch {
            /* keep last known view */
          }
          break;
        }
        if (!mountedRef.current) break;
        queueRef.current.shift();
        setPending((p) => Math.max(0, p - 1));
        setView(next);
        if (next.finished) {
          queueRef.current = [];
          setPending(0);
          haptic(next.result?.outcome === 'win' ? 'success' : 'error');
        } else if (next.levels_completed > current.levels_completed) {
          // Round cleared: discard taps made before the player could see
          // the new level, then pause for the transition.
          queueRef.current = [];
          setPending(0);
          setTransitionMs(ROUND_TRANSITION_MS);
        }
      }
    } finally {
      pumpingRef.current = false;
    }
  }, [ctx.initData, sessionId]);

  const tap = useCallback(
    (color: number) => {
      const current = viewRef.current;
      if (!current || current.finished || showing || !started || transitionMs !== null) return;
      setNotice('');
      // Immediate acknowledgment so a tap never feels lost. The flash timer
      // is purely visual and never gates input.
      setFlash(color);
      if (tapFlashTimer.current) clearTimeout(tapFlashTimer.current);
      tapFlashTimer.current = setTimeout(() => setFlash(null), 180);
      queueRef.current.push({ color, id: newClientGuessId() });
      setPending((p) => p + 1);
      void pump();
    },
    [showing, started, transitionMs, pump],
  );

  useEffect(() => {
    const onKeyboard = (e: KeyboardEvent) => {
      if (e.key >= '1' && e.key <= '4') void tap(Number(e.key) - 1);
    };
    window.addEventListener('keydown', onKeyboard);
    return () => window.removeEventListener('keydown', onKeyboard);
  }, [tap]);

  const cancel = async () => {
    try {
      await api.cancel(ctx.initData, sessionId);
    } catch {
      /* already gone: still exit */
    }
    onExit();
  };

  const replay = async () => {
    if (!viewRef.current || replaying) return;
    setReplaying(true);
    try {
      const s = await api.start(ctx.initData, 'color_sequence', viewRef.current.difficulty);
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
    const won = view.result.outcome === 'win';
    const isBest = best !== null && view.result.score > best;
    return (
      <div className="rounded-3xl bg-panel p-6 text-center shadow-card animate-pop">
        <div className="text-5xl" aria-hidden>
          {won ? '🏆' : '💪'}
        </div>
        <h2 className="mt-2 text-2xl font-bold text-white">
          {won ? 'Sequence mastered!' : 'Run over!'}
        </h2>
        <p className="mt-1 text-sm text-slate-300">
          Reached level {view.result.score} · <b className="text-neon-cyan">+{view.result.xp_earned} XP</b>
        </p>
        {isBest && (
          <p className="mt-1 text-sm font-bold text-amber-300">🎉 New personal best!</p>
        )}
        {notice && (
          <p className="mt-2 text-sm text-amber-300" role="alert">
            {notice}
          </p>
        )}
        <div className="mt-4 flex gap-2">
          <button onClick={onExit} className="flex-1 rounded-xl bg-navy py-2.5 text-sm font-bold text-slate-200 active:scale-95">
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
        {matchId && onBackToMatch && (
          <MatchSubmitBanner ctx={ctx} matchId={matchId} sessionId={sessionId} onBackToMatch={onBackToMatch} />
        )}
      </div>
    );
  }

  if (!started) {
    return (
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <button onClick={onExit} className="rounded-xl bg-panel px-3 py-1.5 text-sm font-semibold text-slate-300 active:scale-95" aria-label="Back to lobby">
            ← Lobby
          </button>
          <span className="rounded-full bg-panel px-3 py-1 text-xs font-bold uppercase tracking-wider text-neon-cyan">
            {view.difficulty} · up to Lv {view.max_level}
          </span>
          <button onClick={cancel} className="rounded-xl bg-panel px-3 py-1.5 text-sm font-semibold text-rose-300 active:scale-95" aria-label="Cancel game">
            ✕ Give up
          </button>
        </div>
        <div className="rounded-3xl bg-panel p-6 text-center shadow-card animate-pop">
          <div className="text-5xl" aria-hidden>
            🎨
          </div>
          <h2 className="mt-3 text-xl font-bold text-white">
            Watch the colors carefully, then repeat them in the exact same order.
          </h2>
          <p className="mx-auto mt-2 max-w-xs text-sm text-slate-300">
            Memorize the flashing sequence. Tap the colors in order after the
            demonstration finishes. One wrong tap ends your run.
          </p>
          {best !== null && (
            <p className="mt-2 text-xs text-slate-400">🎨 Personal best: level {best}</p>
          )}
          <button
            onClick={() => setStarted(true)}
            className="mt-4 w-full rounded-xl bg-gradient-to-r from-neon-purple to-neon-cyan py-3 text-base font-bold text-white shadow-glow active:scale-[0.99]"
          >
            ▶ Start Game
          </button>
        </div>
        <div className="grid grid-cols-2 gap-3 opacity-60" aria-hidden="true">
          {COLORS.map((c) => (
            <div
              key={c.name}
              className={`flex h-20 items-center justify-center rounded-3xl text-base font-bold text-white/70 ${c.base}`}
            >
              {c.name}
            </div>
          ))}
        </div>
      </div>
    );
  }

  const inputLocked = showing || transitionMs !== null;
  const countdown = transitionMs === null ? 0 : Math.ceil(transitionMs / 1000);

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <button onClick={onExit} className="rounded-xl bg-panel px-3 py-1.5 text-sm font-semibold text-slate-300 active:scale-95" aria-label="Back to lobby">
          ← Lobby
        </button>
        <span className="rounded-full bg-panel px-3 py-1 text-xs font-bold uppercase tracking-wider text-neon-cyan">
          {view.difficulty} · Lv {view.level}/{view.max_level}
        </span>
        <button onClick={cancel} className="rounded-xl bg-panel px-3 py-1.5 text-sm font-semibold text-rose-300 active:scale-95" aria-label="Cancel game">
          ✕ Give up
        </button>
      </div>

      <div className="rounded-3xl bg-panel p-5 text-center shadow-card">
        {transitionMs !== null ? (
          <div aria-live="polite">
            <p className="text-base font-bold text-emerald-300">✅ Correct! Get ready… {countdown}</p>
            <div
              className="mx-auto mt-2 h-1.5 max-w-[220px] overflow-hidden rounded-full bg-navy"
              role="progressbar"
              aria-valuemin={0}
              aria-valuemax={ROUND_TRANSITION_MS}
              aria-valuenow={transitionMs}
              aria-label="Next sequence starting soon"
            >
              <div
                className="h-full rounded-full bg-gradient-to-r from-emerald-400 to-neon-cyan"
                style={{ width: `${(transitionMs / ROUND_TRANSITION_MS) * 100}%`, transition: 'width 100ms linear' }}
              />
            </div>
          </div>
        ) : (
          <p className="text-xs uppercase tracking-widest text-slate-400" aria-live="polite">
            {showing
              ? '👀 Watch carefully…'
              : `Your turn — tap ${Math.min(view.position + pending + 1, view.level)} of ${view.level}`}
          </p>
        )}
        <div className="mt-2 flex justify-center gap-1.5" aria-label={`Level progress ${view.levels_completed} completed`}>
          {Array.from({ length: view.max_level }).map((_, i) => (
            <span
              key={i}
              className={`h-2 w-2 rounded-full ${i < view.levels_completed ? 'bg-neon-cyan' : 'bg-navy'}`}
            />
          ))}
        </div>
        {best !== null && (
          <p className="mt-1 text-xs text-slate-400">🎨 Personal best: level {best}</p>
        )}
        {notice && (
          <p className="mt-2 text-sm text-amber-300" role="alert">
            {notice}
          </p>
        )}
      </div>

      <div className="grid grid-cols-2 gap-3" role="group" aria-label="Color buttons">
        {COLORS.map((c, i) => (
          <button
            key={c.name}
            onClick={() => void tap(i)}
            disabled={inputLocked}
            aria-label={`${c.name} button${flash === i ? ' (flashing)' : ''}`}
            className={`key-btn color-flash h-28 rounded-3xl text-lg font-bold text-white/90 shadow-card disabled:cursor-default ${
              flash === i ? c.lit : c.base
            } ${inputLocked ? 'opacity-90' : 'active:scale-95'}`}
          >
            {c.name}
          </button>
        ))}
      </div>
      <p className="text-center text-[11px] text-slate-500">Keys 1–4 work too · tap as fast as you like · input locks during playback and transitions</p>
    </div>
  );
}
