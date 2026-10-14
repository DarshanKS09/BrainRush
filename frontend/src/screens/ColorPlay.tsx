import { useCallback, useEffect, useRef, useState } from 'react';
import { api, newClientGuessId, type ColorState } from '../api';
import type { WebAppContext } from '../telegram';
import { ErrorNotice, Loading } from '../components/ui';
import { haptic } from '../telegram';

const COLORS = [
  { name: 'Red', base: 'bg-rose-600', lit: 'bg-rose-400 shadow-[0_0_36px_rgba(251,113,133,0.9)]' },
  { name: 'Green', base: 'bg-emerald-600', lit: 'bg-emerald-300 shadow-[0_0_36px_rgba(110,231,183,0.9)]' },
  { name: 'Blue', base: 'bg-sky-600', lit: 'bg-sky-300 shadow-[0_0_36px_rgba(125,211,252,0.9)]' },
  { name: 'Yellow', base: 'bg-amber-500', lit: 'bg-amber-200 shadow-[0_0_36px_rgba(252,211,77,0.9)]' },
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
}: {
  ctx: WebAppContext;
  sessionId: string;
  onExit: () => void;
  onReplay: (sessionId: string) => void;
}) {
  const [view, setView] = useState<ColorState | null>(null);
  const [playbackMs, setPlaybackMs] = useState(500);
  const [best, setBest] = useState<number | null>(null);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [showing, setShowing] = useState(false);
  const [flash, setFlash] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [replaying, setReplaying] = useState(false);
  const viewRef = useRef<ColorState | null>(null);
  viewRef.current = view;
  const playedLevel = useRef<string>('');

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
      })
      .catch((e: Error) => setError(e.message));
  }, [ctx.initData, sessionId]);

  useEffect(load, [load]);

  // Play back the current level's prefix whenever a new level arrives.
  useEffect(() => {
    if (!view || view.finished) return;
    const key = `${view.session_id}:${view.level}:${view.moves.length}`;
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
  }, [view, playbackMs]);

  const tap = useCallback(
    async (color: number) => {
      const current = viewRef.current;
      if (!current || current.finished || showing || busy) return;
      setBusy(true);
      setNotice('');
      try {
        const next = await api.move(ctx.initData, sessionId, color, newClientGuessId());
        setView(next);
        if (next.finished) haptic(next.result?.outcome === 'win' ? 'success' : 'error');
      } catch (e) {
        setNotice(e instanceof Error ? e.message : 'Tap failed. Try again.');
      } finally {
        setBusy(false);
      }
    },
    [busy, ctx.initData, sessionId, showing],
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
      </div>
    );
  }

  const inputLocked = showing || busy;

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
        <p className="text-xs uppercase tracking-widest text-slate-400" aria-live="polite">
          {showing ? '👀 Watch carefully…' : `Your turn — repeat ${view.level} colors`}
        </p>
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
            className={`key-btn h-28 rounded-3xl text-lg font-bold text-white/90 shadow-card disabled:cursor-default ${
              flash === i ? c.lit : c.base
            } ${inputLocked ? 'opacity-90' : 'active:scale-95'}`}
          >
            {c.name}
          </button>
        ))}
      </div>
      <p className="text-center text-[11px] text-slate-500">Keys 1–4 work too · input locks during playback</p>
    </div>
  );
}
