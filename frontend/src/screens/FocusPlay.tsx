import { useCallback, useEffect, useRef, useState } from 'react';
import {
  api,
  newClientGuessId,
  type FocusColor,
  type FocusResult,
  type FocusShape,
  type FocusState,
} from '../api';
import type { WebAppContext } from '../telegram';
import { haptic } from '../telegram';
import { playSound, useAudioScope, useOutcomeSound } from '../audio';
import { ErrorNotice, Loading } from '../components/ui';
import { MatchSubmitBanner } from '../components/MatchSubmit';
import {
  FOCUS_POLL_MS,
  OBJECT_SIZE_PX,
  SHAPE_FILL,
  difficultySummary,
  clockOffsetFromSample,
  fallProgress,
  instructionFor,
  isTargetObject,
  mergeFallingObjects,
  objectTopPx,
  shapeLabel,
  type LocalFocusObject,
} from '../focusutil';

type FeedbackKind = 'hit' | 'wrong' | 'miss' | 'info';

interface Feedback {
  kind: FeedbackKind;
  text: string;
  id: number;
}

interface TargetChangePopup {
  id: number;
  color: FocusColor;
  shape: FocusShape;
  /** Server-measured time left in the hand-over window, used as the
   *  popup's animation duration so gameplay resumes exactly when it ends. */
  durationMs: number;
}

const FEEDBACK_CLASS: Record<FeedbackKind, string> = {
  hit: 'border-emerald-400/40 bg-emerald-500/15 text-emerald-200',
  wrong: 'border-rose-400/40 bg-rose-500/15 text-rose-200',
  miss: 'border-amber-400/40 bg-amber-500/15 text-amber-200',
  info: 'border-neon-cyan/40 bg-cyan-500/10 text-cyan-100',
};

/** One falling shape. Rendered once; the rAF loop owns its transform. */
function ShapeGlyph({
  shape,
  color,
  className = '',
}: {
  shape: FocusShape;
  color: FocusColor;
  className?: string;
}) {
  const fill = SHAPE_FILL[color] ?? '#94a3b8';
  const stroke = 'rgba(255,255,255,0.55)';
  return (
    <svg viewBox="0 0 24 24" className={className} aria-hidden="true" focusable="false">
      {shape === 'circle' && (
        <circle cx="12" cy="12" r="9.2" fill={fill} stroke={stroke} strokeWidth="1.1" />
      )}
      {shape === 'square' && (
        <rect x="3.4" y="3.4" width="17.2" height="17.2" rx="2.6" fill={fill} stroke={stroke} strokeWidth="1.1" />
      )}
      {shape === 'triangle' && (
        <polygon points="12,2.4 22,21.2 2,21.2" fill={fill} stroke={stroke} strokeWidth="1.1" />
      )}
      {shape === 'diamond' && (
        <polygon points="12,1.8 22.2,12 12,22.2 1.8,12" fill={fill} stroke={stroke} strokeWidth="1.1" />
      )}
      {shape === 'star' && (
        <polygon
          points="12,1.6 15.2,8.2 22.4,9.3 17.2,14.3 18.4,21.5 12,18.1 5.6,21.5 6.8,14.3 1.6,9.3 8.8,8.2"
          fill={fill}
          stroke={stroke}
          strokeWidth="1"
        />
      )}
    </svg>
  );
}

function fallbackResult(view: FocusState): FocusResult {
  return {
    outcome: 'loss',
    score: view.score,
    xp_earned: 0,
    accuracy_percent: view.accuracy_percent,
    hits: view.hits,
    missed_targets: view.missed,
    wrong_taps: view.wrong_taps,
    best_combo: view.best_combo,
    duration_ms: 0,
  };
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
  const [view, setView] = useState<FocusState | null>(null);
  const [objects, setObjects] = useState<LocalFocusObject[]>([]);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [feedback, setFeedback] = useState<Feedback | null>(null);
  const [targetChange, setTargetChange] = useState<TargetChangePopup | null>(null);
  const [started, setStarted] = useState(false);
  const [busy, setBusy] = useState<'pause' | 'resume' | 'exit' | null>(null);
  const [replaying, setReplaying] = useState(false);
  useAudioScope();
  const outcome = view?.finished ? (view.result?.outcome ?? null) : null;
  useOutcomeSound(sessionId, outcome, outcome === 'win' ? 'focusWin' : 'focusLoss');

  const areaRef = useRef<HTMLDivElement | null>(null);
  const nodeRefs = useRef(new Map<string, HTMLButtonElement>());
  const objectsRef = useRef<LocalFocusObject[]>([]);
  const viewRef = useRef<FocusState | null>(null);
  const tappedRef = useRef(new Set<string>());
  const offsetRef = useRef(0);
  // Tightest round trip seen: its midpoint gives the least-biased clock.
  const bestRttRef = useRef(Number.POSITIVE_INFINITY);
  const pausedRef = useRef(true);
  const mountedRef = useRef(true);
  const seqRef = useRef(0);
  const appliedRef = useRef(0);
  const feedbackTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const popupTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const shownChangeRef = useRef(0);
  const removalTimers = useRef(new Set<ReturnType<typeof setTimeout>>());
  const prevLivesRef = useRef<number | null>(null);

  // Mirrors so the animation/poll callbacks never need to re-subscribe.
  useEffect(() => {
    objectsRef.current = objects;
  }, [objects]);

  // Low-lives warning: fires once when a life is lost and only one remains.
  useEffect(() => {
    if (!view) return;
    const prev = prevLivesRef.current;
    prevLivesRef.current = view.lives;
    if (prev !== null && view.lives < prev && view.lives > 0 && view.lives === 1) {
      playSound('lowLives');
    }
  }, [view?.lives]);
  useEffect(() => {
    viewRef.current = view;
    pausedRef.current = !view || view.paused || view.finished;
  }, [view]);

  const showFeedback = useCallback((kind: FeedbackKind, text: string) => {
    setFeedback({ kind, text, id: Date.now() + Math.random() });
    if (feedbackTimer.current) clearTimeout(feedbackTimer.current);
    feedbackTimer.current = setTimeout(() => {
      if (mountedRef.current) setFeedback(null);
    }, 1000);
  }, []);

  const applyState = useCallback(
    (next: FocusState, sentAt = 0, receivedAt = 0) => {
    // Latency-compensated server clock. Adopting only the fastest sample
    // keeps the render within half of the best round trip of the server.
    if (next.now_ms > 0 && sentAt > 0 && receivedAt >= sentAt) {
      const rtt = receivedAt - sentAt;
      if (rtt <= bestRttRef.current) {
        bestRttRef.current = rtt;
        offsetRef.current = clockOffsetFromSample(next.now_ms, sentAt, receivedAt);
      }
    }
    setView(next);
    setObjects((prev) => mergeFallingObjects(prev, next.objects ?? [], tappedRef.current));
    if (next.finished) setStarted(true);

    // Target-change popup: one per server change id, timed by the server
    // window so it disappears exactly when gameplay resumes.
    const transition = next.transition;
    if (
      transition?.active &&
      !next.paused &&
      !next.finished &&
      transition.id !== shownChangeRef.current
    ) {
      shownChangeRef.current = transition.id;
      playSound('focusTargetChange');
      const durationMs = Math.max(500, transition.until_ms - next.now_ms);
      setTargetChange({
        id: transition.id,
        color: transition.target.color,
        shape: transition.target.shape,
        durationMs,
      });
      if (popupTimer.current) clearTimeout(popupTimer.current);
      popupTimer.current = setTimeout(() => {
        if (mountedRef.current) setTargetChange(null);
      }, durationMs);
    } else if (!transition?.active || next.paused || next.finished) {
      if (popupTimer.current) {
        clearTimeout(popupTimer.current);
        popupTimer.current = null;
      }
      setTargetChange(null);
    }
    },
    [],
  );

  /** Requests are sequenced so a slow poll can never overwrite a new tap. */
  const runRequest = useCallback(
    async (fn: () => Promise<FocusState>) => {
      const id = ++seqRef.current;
      const sentAt = Date.now();
      const state = await fn();
      if (id < appliedRef.current) return null;
      appliedRef.current = id;
      applyState(state, sentAt, Date.now());
      return state;
    },
    [applyState],
  );

  const load = useCallback(() => {
    setError('');
    const sentAt = Date.now();
    api
      .focusState(ctx.initData, sessionId)
      .then((state) => {
        applyState(state, sentAt, Date.now());
        if (!state.paused || state.finished) setStarted(true);
      })
      .catch((e: Error) => setError(e.message));
  }, [ctx.initData, sessionId, applyState]);

  useEffect(load, [load]);

  // Bottom-boundary handling: feedback + fade, then drop the node.
  const handleLanded = useCallback(
    (obj: LocalFocusObject) => {
      const current = viewRef.current;
      if (tappedRef.current.has(obj.id)) return;
      if (current && !current.finished && !current.paused && !current.transition.active) {
        if (isTargetObject(obj, current.target)) {
          showFeedback('miss', 'Missed target −1 life');
          haptic('error');
          playSound('missedTarget');
        }
      }
      const node = nodeRefs.current.get(obj.id);
      if (node) {
        node.style.transition = 'opacity 160ms linear';
        node.style.opacity = '0';
        nodeRefs.current.delete(obj.id);
      }
      const timer = setTimeout(() => {
        removalTimers.current.delete(timer);
        if (mountedRef.current) {
          setObjects((prev) => prev.filter((o) => o.id !== obj.id));
        }
      }, 180);
      removalTimers.current.add(timer);
    },
    [showFeedback],
  );
  const landedRef = useRef(handleLanded);
  useEffect(() => {
    landedRef.current = handleLanded;
  }, [handleLanded]);

  // One animation loop for the whole screen; React never re-renders per frame.
  useEffect(() => {
    mountedRef.current = true;
    let raf = 0;
    const frame = () => {
      raf = requestAnimationFrame(frame);
      const area = areaRef.current;
      if (!area || pausedRef.current) return;
      const height = area.clientHeight;
      if (height <= 0) return;
      const now = Date.now() + offsetRef.current;
      for (const obj of objectsRef.current) {
        if (obj.landed) continue;
        const progress = fallProgress(obj.spawned_at_ms, obj.fall_ms, now);
        const node = nodeRefs.current.get(obj.id);
        if (node) {
          node.style.transform = `translate3d(0, ${objectTopPx(progress, height)}px, 0)`;
        }
        if (progress >= 1) {
          obj.landed = true;
          landedRef.current(obj);
        }
      }
    };
    raf = requestAnimationFrame(frame);
    return () => {
      mountedRef.current = false;
      cancelAnimationFrame(raf);
      if (feedbackTimer.current) clearTimeout(feedbackTimer.current);
      if (popupTimer.current) clearTimeout(popupTimer.current);
      for (const timer of removalTimers.current) clearTimeout(timer);
      removalTimers.current.clear();
      nodeRefs.current.clear();
    };
  }, []);

  const playing = !!view && started && !view.paused && !view.finished;

  // Server poll: spawns new shapes and resolves misses authoritatively.
  useEffect(() => {
    if (!playing) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const tick = async () => {
      try {
        await runRequest(() => api.focusState(ctx.initData, sessionId));
      } catch {
        /* transient: the next tick retries */
      }
      if (!cancelled) timer = setTimeout(tick, FOCUS_POLL_MS);
    };
    timer = setTimeout(tick, FOCUS_POLL_MS);
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [playing, ctx.initData, sessionId, runRequest]);

  // Stop animating immediately when paused; resume re-syncs from the server.
  useEffect(() => {
    pausedRef.current = !view || view.paused || view.finished;
  }, [view]);

  const startGame = async () => {
    if (busy) return;
    setBusy('resume');
    setNotice('');
    try {
      const state = await runRequest(() => api.focusPause(ctx.initData, sessionId, false));
      if (state) {
        setStarted(true);
        playSound('start');
        showFeedback('info', 'Go! Tap the matching shapes.');
      }
    } catch (e) {
      setNotice(e instanceof Error ? e.message : 'Could not start the game.');
    } finally {
      setBusy(null);
    }
  };

  const togglePause = async () => {
    const current = viewRef.current;
    if (!current || current.finished || busy) return;
    const shouldPause = !current.paused;
    setBusy(shouldPause ? 'pause' : 'resume');
    setNotice('');
    if (shouldPause) {
      pausedRef.current = true;
      setView((prev) => (prev ? { ...prev, paused: true } : prev));
    }
    try {
      const state = await runRequest(() =>
        api.focusPause(ctx.initData, sessionId, shouldPause),
      );
      if (state) applyState(state);
    } catch (e) {
      setNotice(e instanceof Error ? e.message : 'Could not change pause state.');
      load();
    } finally {
      setBusy(null);
    }
  };

  const giveUp = async () => {
    if (busy) return;
    setBusy('exit');
    try {
      await api.cancel(ctx.initData, sessionId);
    } catch {
      /* already gone: still exit */
    }
    onExit();
  };

  const replay = async () => {
    if (replaying) return;
    setReplaying(true);
    setNotice('');
    try {
      const next = await api.start(ctx.initData, 'focus_rush', view?.difficulty ?? 'medium');
      onReplay(next.session_id);
    } catch (e) {
      setNotice(e instanceof Error ? e.message : 'Could not start a new run.');
    } finally {
      setReplaying(false);
    }
  };

  const tapObject = async (obj: LocalFocusObject) => {
    const current = viewRef.current;
    if (!current || current.finished || current.paused) return;
    // The server is mid target-change hand-over: nothing can score or punish.
    if (current.transition.active) return;
    if (obj.landed || tappedRef.current.has(obj.id)) return;
    // Scheduled shapes are delivered before they enter the play area.
    if (obj.spawned_at_ms > Date.now() + offsetRef.current) return;
    tappedRef.current.add(obj.id);
    const matching = isTargetObject(obj, current.target);
    playSound('metallicTap');
    showFeedback(matching ? 'hit' : 'wrong', matching ? 'CORRECT' : 'WRONG TARGET −1 life');
    haptic(matching ? 'light' : 'error');
    const node = nodeRefs.current.get(obj.id);
    if (node) {
      node.style.transition = 'transform 120ms ease, opacity 120ms ease';
      node.style.transform = `${node.style.transform} scale(0.4)`;
      node.style.opacity = '0';
      nodeRefs.current.delete(obj.id);
    }
    setObjects((prev) => prev.filter((o) => o.id !== obj.id));
    try {
      const state = await runRequest(() =>
        api.focusTap(ctx.initData, sessionId, obj.id, newClientGuessId()),
      );
      const tap = state?.last_tap;
      if (tap) {
        if (tap.outcome === 'hit') {
          showFeedback('hit', `CORRECT +${tap.points}`);
          playSound('focusCorrect');
        } else if (tap.outcome === 'wrong') {
          showFeedback('wrong', 'WRONG TARGET −1 life');
          haptic('error');
          playSound('focusWrong');
        } else if (tap.outcome === 'transition') {
          showFeedback('info', 'Get ready!');
        } else if (tap.outcome === 'expired') {
          setNotice('Too late — that shape already fell.');
        }
      }
    } catch (e) {
      tappedRef.current.delete(obj.id);
      setNotice(e instanceof Error ? e.message : 'Tap failed. Check your connection.');
    }
  };

  if (error && !view) return <ErrorNotice message={error} onRetry={load} />;
  if (!view) return <Loading label="Loading Focus Rush…" />;

  const target = view.target;
  const targetName = `${target.color.toUpperCase()} ${target.shape.toUpperCase()}`;

  if (view.finished) {
    const result = view.result ?? fallbackResult(view);
    const seconds = Math.round(result.duration_ms / 1000);
    return (
      <div className="space-y-3">
        <div className="rounded-3xl bg-panel p-6 text-center shadow-card animate-pop">
          <div className="text-5xl" aria-hidden>
            {result.outcome === 'win' ? '🏆' : '💪'}
          </div>
          <h2 className="mt-2 text-2xl font-bold text-white">
            {result.outcome === 'win' ? 'Sharp focus!' : 'Run over'}
          </h2>
          <p className="mt-1 text-sm text-slate-300">
            Score <b className="text-neon-cyan">{result.score}</b> · {seconds}s survived
          </p>
          <div className="mx-auto mt-4 grid max-w-xs grid-cols-2 gap-2 text-left">
            <div className="rounded-xl bg-navy px-3 py-2">
              <p className="text-[10px] uppercase tracking-widest text-slate-400">Accuracy</p>
              <p className="text-lg font-bold text-white">{Math.round(result.accuracy_percent)}%</p>
            </div>
            <div className="rounded-xl bg-navy px-3 py-2">
              <p className="text-[10px] uppercase tracking-widest text-slate-400">Missed targets</p>
              <p className="text-lg font-bold text-rose-300">{result.missed_targets}</p>
            </div>
            <div className="rounded-xl bg-navy px-3 py-2">
              <p className="text-[10px] uppercase tracking-widest text-slate-400">Targets hit</p>
              <p className="text-lg font-bold text-emerald-300">{result.hits}</p>
            </div>
            <div className="rounded-xl bg-navy px-3 py-2">
              <p className="text-[10px] uppercase tracking-widest text-slate-400">Best combo</p>
              <p className="text-lg font-bold text-white">{result.best_combo}</p>
            </div>
          </div>
          <p className="mt-3 text-sm font-bold text-neon-cyan">+{result.xp_earned} XP</p>
          {result.wrong_taps > 0 && (
            <p className="mt-1 text-xs text-slate-400">
              {result.wrong_taps} wrong tap{result.wrong_taps === 1 ? '' : 's'} · −1 life each
            </p>
          )}
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
        {matchId && onBackToMatch && (
          <MatchSubmitBanner
            ctx={ctx}
            matchId={matchId}
            sessionId={sessionId}
            onBackToMatch={onBackToMatch}
          />
        )}
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between gap-2">
        <button
          onClick={giveUp}
          disabled={busy === 'exit'}
          className="rounded-xl bg-panel px-3 py-1.5 text-xs font-semibold text-slate-300 active:scale-95 disabled:opacity-50"
          aria-label="Leave the game"
        >
          ← Lobby
        </button>
        <span className="truncate rounded-full bg-panel px-3 py-1 text-[10px] font-bold uppercase tracking-wider text-neon-cyan">
          {view.difficulty} · {difficultySummary(view.config)}
        </span>
        <button
          onClick={togglePause}
          disabled={busy !== null || !started}
          className="rounded-xl bg-panel px-3 py-1.5 text-xs font-semibold text-slate-200 active:scale-95 disabled:opacity-50"
          aria-label={view.paused ? 'Resume game' : 'Pause game'}
        >
          {view.paused ? '▶ Resume' : '⏸ Pause'}
        </button>
      </div>

      <div className="rounded-2xl border border-neon-cyan/25 bg-navy px-3 py-2">
        <div className="flex items-center justify-between gap-2">
          <div className="min-w-0">
            <p className="text-[10px] font-bold uppercase tracking-widest text-slate-400">
              Target
            </p>
            <p className="truncate text-lg font-black leading-tight text-white">
              <span style={{ color: SHAPE_FILL[target.color] }}>{target.color.toUpperCase()}</span>{' '}
              {target.shape.toUpperCase()}
            </p>
          </div>
          <ShapeGlyph shape={target.shape} color={target.color} className="h-9 w-9 shrink-0" />
        </div>
        <p className="mt-0.5 text-[11px] text-slate-400" aria-live="polite">
          {instructionFor(target)} · new target in{' '}
          {Math.max(0, Math.ceil(view.target_changes_in_ms / 1000))}s
        </p>
      </div>

      <div className="flex items-center justify-between rounded-2xl bg-panel px-3 py-1.5">
        <div>
          <p className="text-[10px] uppercase tracking-widest text-slate-400">Score</p>
          <p className="text-xl font-black leading-tight text-neon-cyan">{view.score}</p>
        </div>
        <div
          className="flex gap-1 text-lg"
          aria-label={`${view.lives} of ${view.max_lives} lives left`}
        >
          {Array.from({ length: view.max_lives }).map((_, i) => (
            <span key={i} className={i < view.lives ? '' : 'opacity-20 grayscale'} aria-hidden>
              ❤️
            </span>
          ))}
        </div>
        <div className="text-right">
          <p className="text-[10px] uppercase tracking-widest text-slate-400">Missed</p>
          <p
            className={`text-xl font-black leading-tight ${
              view.missed > 0 ? 'text-rose-300' : 'text-white'
            }`}
          >
            {view.missed}/{view.max_lives}
          </p>
        </div>
      </div>

      <div
        ref={areaRef}
        className="relative h-[56vh] max-h-[560px] min-h-[320px] select-none overflow-hidden rounded-3xl border border-white/5 bg-gradient-to-b from-[#111c3c] to-[#0a0e1a] shadow-card"
        aria-label="Falling shapes play area"
      >
        <div className="pointer-events-none absolute inset-0 flex justify-around opacity-[0.06]">
          {[0, 1, 2, 3, 4].map((i) => (
            <span key={i} className="h-full w-px bg-white" />
          ))}
        </div>
        <div className="pointer-events-none absolute inset-x-0 bottom-0 h-px bg-gradient-to-r from-transparent via-rose-400/50 to-transparent" />

        {objects.map((obj) => (
          <button
            key={obj.id}
            ref={(el) => {
              if (el) nodeRefs.current.set(obj.id, el);
              else nodeRefs.current.delete(obj.id);
            }}
            onPointerDown={(event) => {
              event.preventDefault();
              void tapObject(obj);
            }}
            type="button"
            aria-label={`${obj.color} ${obj.shape}${
              isTargetObject(obj, target) ? ', target' : ''
            }`}
            className="absolute top-0 rounded-full outline-none focus-visible:ring-2 focus-visible:ring-white/70"
            style={{
              left: `calc(${obj.x * 100}% - ${OBJECT_SIZE_PX / 2}px)`,
              width: OBJECT_SIZE_PX,
              height: OBJECT_SIZE_PX,
              transform: `translate3d(0, -${OBJECT_SIZE_PX}px, 0)`,
              touchAction: 'manipulation',
              willChange: 'transform',
            }}
          >
            <span className="block h-full w-full transition-transform duration-100 active:scale-90">
              <ShapeGlyph shape={obj.shape} color={obj.color} className="h-full w-full drop-shadow" />
            </span>
          </button>
        ))}

        {targetChange && started && !view.paused && (
          <div
            className="focus-target-popup pointer-events-none absolute inset-0 z-20 flex items-center justify-center bg-abyss/85 px-4 backdrop-blur-sm"
            style={{ animationDuration: `${targetChange.durationMs}ms` }}
            role="status"
            aria-live="assertive"
          >
            <div className="focus-target-card w-full max-w-[16rem] rounded-2xl border border-neon-cyan/40 bg-panel/95 px-4 py-5 text-center shadow-glow">
              <p className="text-[11px] font-black uppercase tracking-[0.2em] text-neon-cyan">
                Target changed!
              </p>
              <div className="mt-2 flex justify-center">
                <ShapeGlyph
                  shape={targetChange.shape}
                  color={targetChange.color}
                  className="h-16 w-16 drop-shadow"
                />
              </div>
              <p className="mt-2 text-xl font-black leading-tight text-white">
                <span style={{ color: SHAPE_FILL[targetChange.color] }}>
                  {targetChange.color.toUpperCase()}
                </span>{' '}
                {targetChange.shape.toUpperCase()}
              </p>
              <p className="mt-1 text-sm font-semibold text-slate-200">Tap only this shape!</p>
              <p className="mt-2 text-[10px] font-bold uppercase tracking-widest text-amber-300">
                Get ready!
              </p>
            </div>
          </div>
        )}

        {feedback && (
          <div className="pointer-events-none absolute inset-x-0 top-2 z-30 flex justify-center">
            <span
              key={feedback.id}
              role="status"
              aria-live="polite"
              className={`rounded-full border px-3 py-1 text-xs font-bold shadow-card ${FEEDBACK_CLASS[feedback.kind]}`}
            >
              {feedback.text}
            </span>
          </div>
        )}

        {!started && (
          <div className="absolute inset-0 z-10 flex flex-col items-center justify-center gap-3 bg-abyss/90 p-6 text-center backdrop-blur-sm">
            <div className="flex items-center gap-2">
              <ShapeGlyph shape={target.shape} color={target.color} className="h-10 w-10" />
              <span className="text-2xl font-black text-white">Ready?</span>
            </div>
            <p className="max-w-[17rem] text-sm text-slate-300">
              Tap every{' '}
              <b className="text-white">
                {shapeLabel(target.shape).toLowerCase()} shaped{' '}
                {target.color.toLowerCase()}
              </b>{' '}
              shape before it reaches the bottom. Ignore the rest — you have {view.max_lives}{' '}
              lives, and both a missed target and a wrong tap cost one.
            </p>
            <button
              onClick={startGame}
              disabled={busy !== null}
              className="w-full max-w-[16rem] rounded-xl bg-gradient-to-r from-neon-purple to-neon-cyan py-3 text-base font-bold text-white shadow-glow active:scale-[0.99] disabled:opacity-50"
            >
              {busy === 'resume' ? 'Starting…' : '▶ Start'}
            </button>
            <button onClick={giveUp} className="text-xs font-semibold text-slate-400">
              Give up (no XP)
            </button>
          </div>
        )}

        {started && view.paused && (
          <div className="absolute inset-0 z-10 flex flex-col items-center justify-center gap-3 bg-abyss/85 p-6 text-center backdrop-blur-sm">
            <p className="text-2xl font-black text-white">Paused</p>
            <p className="text-sm text-slate-300">
              Score <b className="text-neon-cyan">{view.score}</b> · target{' '}
              <b className="text-white">{targetName}</b>
            </p>
            <button
              onClick={togglePause}
              disabled={busy !== null}
              className="w-full max-w-[16rem] rounded-xl bg-gradient-to-r from-neon-purple to-neon-cyan py-3 text-base font-bold text-white shadow-glow active:scale-[0.99] disabled:opacity-50"
            >
              {busy === 'resume' ? 'Resuming…' : '▶ Resume'}
            </button>
            <button
              onClick={giveUp}
              className="rounded-xl bg-panel px-4 py-2 text-xs font-bold text-rose-300 active:scale-95"
            >
              ✕ Give up
            </button>
          </div>
        )}
      </div>

      <p className="text-center text-[11px] text-slate-500">
        Tap the target shapes · wrong shapes cost a life · {view.max_lives} lives ends the run
      </p>
      {notice && (
        <p className="text-center text-sm text-amber-300" role="alert">
          {notice}
        </p>
      )}
    </div>
  );
}
