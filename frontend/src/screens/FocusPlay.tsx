import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../api';
import { WebAppContext } from '../telegram';
import { ErrorNotice, Loading } from '../components/ui';

type Color = 'red' | 'blue' | 'green' | 'yellow';
type Shape = 'circle' | 'square' | 'triangle' | 'diamond';

interface RoundConfig {
  displayDuration: number; // ms
  gapDuration: number; // ms
  shapesPerRound: number;
}

// Shared configuration - used by both frontend and backend
const ROUND_CONFIGS: Record<string, RoundConfig> = {
  easy: { displayDuration: 1500, gapDuration: 1000, shapesPerRound: 5 },
  medium: { displayDuration: 1000, gapDuration: 600, shapesPerRound: 8 },
  hard: { displayDuration: 700, gapDuration: 300, shapesPerRound: 12 },
};

// Single shape display - only one shape visible at a time
function ShapeDisplay({ color, shape, isActive, onTap }: { color: Color; shape: Shape; isActive: boolean; onTap: () => void }) {
  const colorBg: Record<Color, string> = {
    red: 'bg-rose-600',
    blue: 'bg-sky-600',
    green: 'bg-emerald-500',
    yellow: 'bg-amber-500',
  };
  const shapeClass: Record<Shape, string> = {
    circle: 'rounded-full w-16 h-16 mx-auto',
    square: 'rounded-md w-16 h-16 mx-auto',
    triangle: 'rotate-6 w-16 h-16 mx-auto',
    diamond: 'rotate-45 w-16 h-16 mx-auto',
  };

  const base = 'transition-all duration-150 ease-in-out';

  return (
    <button
      onClick={isActive ? onTap : undefined}
      disabled={!isActive}
      className={`${base} ${colorBg[color]} ${shapeClass[shape]} text-white flex items-center justify-center rounded-2xl p-2 shadow-md`}
      aria-label={isActive ? 'Tap shape' : 'Shape inactive'}
    >
      <svg
        className="w-8 h-8"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="3"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        {shape === 'circle' && <circle cx="12" cy="12" r="8" />}
        {shape === 'square' && <rect x="4" y="4" width="16" height="16" rx="2" />}
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
    </button>
  );
}

export default function FocusPlayScreen({
  ctx,
  sessionId,
  onExit,
  _matchId,
  _onReplay,
  _onBackToMatch,
}: {
  ctx: WebAppContext;
  sessionId: string;
  onExit: () => void;
  _matchId?: string | null;
  _onReplay: (sessionId: string) => void;
  _onBackToMatch: () => void;
}) {
  const [state, setState] = useState<'ready' | 'countdown' | 'showing_shape' | 'gap' | 'round_result' | 'game_over'>('ready');
  const [difficulty, setDifficulty] = useState<'easy' | 'medium' | 'hard'>('medium');
  const [round, setRound] = useState(1);
  const [roundsCompleted, setRoundsCompleted] = useState(0);
  const [score, setScore] = useState(0);
  const [lives, setLives] = useState(3);
  const [currentTargetColor, setCurrentTargetColor] = useState<Color | null>(null);
  const [currentTargetShape, setCurrentTargetShape] = useState<Shape | null>(null);
  const [currentInstruction, setCurrentInstruction] = useState<string>('');
  const [activeShape, setActiveShape] = useState<{ color: Color; shape: Shape } | null>(null);  // Single active shape
  const [phase, setPhase] = useState<'showing' | 'gap'>('showing');  // 'showing' or 'gap'
  const [showResult, setShowResult] = useState<'win' | 'loss' | null>(null);
  const [roundResult, setRoundResult] = useState<{ roundNumber: number; correct: boolean; missed: boolean; scoreEarned: number } | null>(null);

  const sessionRef = useRef<string>(sessionId);
  sessionRef.current = sessionId;

  // Game config based on difficulty
  const config = ROUND_CONFIGS[difficulty];
  const { displayDuration, gapDuration, shapesPerRound } = config;

  // Load session state from API
  useEffect(() => {
    let mounted = true;

    api
      .state(ctx.initData, sessionId)
      .then((gs: any) => {
        if (!mounted) return;
        const s = gs as any;
        setState('ready');
        setDifficulty(s.difficulty || 'medium');
        setRound(s.round || 1);
        setRoundsCompleted(s.rounds_completed || 0);
        setScore(s.score || 0);
        setCurrentTargetColor(s.target_color || null);
        setCurrentTargetShape(s.target_shape || null);
        setCurrentInstruction(s.instruction || '');

        // Set initial active shape from saved state if in showing phase
        if (s.active_shape) {
          setActiveShape({
            color: s.active_shape[0] || 'blue',
            shape: s.active_shape[1] || 'circle',
          });
          setPhase('showing');
        } else if (s.phase === 'gap') {
          setPhase('gap');
        }

        if (s.finished) {
          setShowResult(s.result?.outcome === 'win' ? 'win' : 'loss');
        }
      })
      .catch((e) => {
        if (!mounted) return;
        console.error('Failed to load session state:', e);
      });

    return () => {
      mounted = false;
    };
  }, [ctx.initData, sessionId]);

  // Countdown timer
  const [count, setCount] = useState<number | null>(null);
  const countdownRef = useRef<number | null>(null);

  const startCountdown = useCallback(() => {
    let seconds = 3;
    if (countdownRef.current) clearInterval(countdownRef.current);
    setCount(seconds);
    countdownRef.current = window.setInterval(() => {
      seconds--;
      setCount(seconds);
      if (seconds <= 0) {
        clearInterval(countdownRef.current!);
        setCount(null);
        setState('showing_shape');
      }
    }, 1000);
  }, []);

  // Shape display scheduling - single shape at a time
  const shapeDisplayRef = useRef<number | null>(null);
  const gapRef = useRef<number | null>(null);

  const startShapeDisplay = useCallback(() => {
    if (shapeDisplayRef.current) clearTimeout(shapeDisplayRef.current);
    if (gapRef.current) clearTimeout(gapRef.current);

    // Reset: hide any active shape, set phase to showing
    setActiveShape(null);
    setPhase('showing');

    const shapes: Shape[] = ['circle', 'square', 'triangle', 'diamond'];
    const colors: Color[] = ['red', 'blue', 'green', 'yellow'];

    const displayNext = () => {
      // If game state changed or round complete, stop
      if (state !== 'showing_shape' && state !== 'gap') return;

      // If we've shown enough shapes for this round, move to round_result
      if (phase === 'showing' && /* shapesShown count tracked separately */ true) {
        // For now, we'll handle round completion via timer
      }

      // Pick a random shape and color for the next shape
      const color = colors[Math.floor(Math.random() * colors.length)];
      const shape = shapes[Math.floor(Math.random() * shapes.length)];

      // Set this shape as the active one
      setActiveShape({ color, shape });
      setPhase('showing');

      // Schedule disappearance after displayDuration
      shapeDisplayRef.current = window.setTimeout(() => {
        // Shape disappears - set to gap phase
        setActiveShape(null);
        setPhase('gap');

        // Schedule next shape after gapDuration
        gapRef.current = window.setTimeout(() => {
          if (state === 'showing_shape') {
            // Show next shape
            displayNext();
          } else if (state === 'gap') {
            // Gap phase ended, transition back to showing_shape or round_result
            if (phase === 'gap') {
              // Check if we've completed enough shapes for this round
              // In the new design, each round has shapesPerRound shapes to tap
              // After all shapes are shown and tapped, round completes
              setState('showing_shape');
              displayNext();
            }
          }
        }, gapDuration);
      }, displayDuration);
    };

    // Start the sequence
    displayNext();
  }, [displayDuration, gapDuration, state, shapesPerRound]);

  // Handle tap on active shape
  const handleShapeTap = useCallback(
    async (tapColor: Color, tapShape: Shape) => {
      if (state !== 'showing_shape' && state !== 'gap') return;
      if (!activeShape || activeShape.color !== tapColor || activeShape.shape !== tapShape) return;

      try {
        const next = await api.focus_tap(
          ctx.initData,
          sessionRef.current,
          tapColor,
          tapShape,
          `shape-${Date.now()}`
        );

        const ns = next as any;
        setState(prev => {
          const newState = { ...prev, ...ns };
          if (ns.round !== undefined) setRound(ns.round);
          if (ns.rounds_completed !== undefined) setRoundsCompleted(ns.rounds_completed);
          if (ns.score !== undefined) setScore(ns.score);
          if (ns.lives !== undefined) setLives(ns.lives);
          if (ns.target_color !== undefined) setCurrentTargetColor(ns.target_color);
          if (ns.target_shape !== undefined) setCurrentTargetShape(ns.target_shape);
          if (ns.instruction !== undefined) setCurrentInstruction(ns.instruction);
          if (ns.display_targets !== undefined) {
            // Convert display_targets to active_shape format
            const dt = ns.display_targets?.[0];
            if (dt) {
              setActiveShape({ color: dt.color || 'blue', shape: dt.shape || 'circle' });
              setPhase('showing');
            } else {
              setActiveShape(null);
              setPhase('gap');
            }
          }
          return newState;
        });

        // Check if round completed (3 rounds)
        if (ns.rounds_completed && ns.rounds_completed >= 3) {
          setRound(prev => prev + 1);
          setRoundsCompleted(3);
          setState('round_result');
          setRoundResult({
            roundNumber: round,
            correct: ns.correct || false,
            missed: false,
            scoreEarned: ns.points_earned || 0,
          });
        }
      } catch (e) {
        console.error('Tap failed:', e);
      }
    },
    [state, sessionRef.current, activeShape]
  );

  // Round result handling - auto-progress, no manual Next Round button
  const handleRoundComplete = useCallback(() => {
    if (round < 3) {
      // Auto-transition to next round after short delay
      setRound(round + 1);
      setRoundsCompleted(round);
      // Brief result display then auto-prepare next round
      const resultTimeout = setTimeout(() => {
        setState('ready');
        startCountdown();
      }, 1500);
      return () => clearTimeout(resultTimeout);
    } else {
      // Round 3 completed, show final results
      setState('game_over');
      // Backend already saved results
      api.focus_tap(ctx.initData, sessionRef.current, 'blue', 'circle', 'final').then(() => {}).catch(() => {});
    }
  }, [round, setRound, setRoundsCompleted]);

  // Cleanup timers on unmount
  useEffect(() => {
    return () => {
      if (countdownRef.current) clearInterval(countdownRef.current);
      if (shapeDisplayRef.current) clearTimeout(shapeDisplayRef.current);
      if (gapRef.current) clearTimeout(gapRef.current);
    };
  }, []);

  // Error state
  if (error && !state) return <ErrorNotice message={error} onRetry={() => window.location.reload()} />;
  if (!state) return <Loading label="Loading game…" />;

  // ---- State machine rendering ----

  if (state === 'ready') {
    return (
      <div className="min-h-screen flex items-center justify-center p-8">
        <div className="rounded-3xl bg-panel p-8 text-center shadow-card">
          <div className="text-6xl" aria-hidden>🎯</div>
          <h2 className="mt-4 text-2xl font-bold text-white">Focus Rush</h2>
          <p className="mt-2 text-sm text-slate-300">
            Select difficulty to start a 60-second attention challenge.
          </p>
          <div className="mt-6 grid grid-cols-3 gap-2">
            <button
              onClick={() => setDifficulty('easy')}
              className={`rounded-xl py-2 px-4 text-sm font-bold transition-all ${difficulty === 'easy' ? 'bg-gradient-to-br from-neon-purple to-neon-cyan text-white shadow-glow' : 'bg-navy text-slate-300 active:scale-95'}`}
            >
              Easy
            </button>
            <button
              onClick={() => setDifficulty('medium')}
              className={`rounded-xl py-2 px-4 text-sm font-bold transition-all ${difficulty === 'medium' ? 'bg-gradient-to-br from-neon-purple to-neon-cyan text-white shadow-glow' : 'bg-navy text-slate-300 active:scale-95'}`}
            >
              Medium
            </button>
            <button
              onClick={() => setDifficulty('hard')}
              className={`rounded-xl py-2 px-4 text-sm font-bold transition-all ${difficulty === 'hard' ? 'bg-gradient-to-br from-neon-purple to-neon-cyan text-white shadow-glow' : 'bg-navy text-slate-300 active:scale-95'}`}
            >
              Hard
            </button>
          </div>
        </div>
      </div>
    );
  }

  if (state === 'countdown') {
    return (
      <div className="min-h-screen flex items-center justify-center p-8">
        <div className="rounded-3xl bg-panel p-8 text-center shadow-card">
          <div className="text-8xl font-bold text-neon-cyan" aria-hidden>
            {count ?? 3}
          </div>
          <p className="mt-2 text-sm text-slate-300">Get ready!</p>
          <p className="mt-1 text-xs text-slate-400">Tap any time during the countdown to prepare</p>
        </div>
      </div>
    );
  }

  if (state === 'showing_shape') {
    return (
      <div className="min-h-screen flex flex-col items-center justify-center p-4">
        <div className="flex items-center justify-between w-full mb-6">
          <button
            onClick={onExit}
            className="rounded-xl bg-panel px-3 py-1.5 text-sm font-semibold text-slate-300 active:scale-95"
            aria-label="Back to lobby"
          >
            ← Lobby
          </button>
          <span className="rounded-full bg-panel px-3 py-1 text-xs font-bold uppercase tracking-wider text-neon-cyan">
            {difficulty}
          </span>
          <button
            onClick={onExit}
            className="rounded-xl bg-panel px-3 py-1.5 text-sm font-semibold text-rose-300 active:scale-95"
            aria-label="Cancel game"
          >
            ✕ Give up
          </button>
        </div>

        <div className="relative w-full max-w-md">
          <div className="mt-3 text-lg font-bold text-white text-center">
            {currentInstruction || 'Tap only ' + (currentTargetColor || 'blue') + ' ' + (currentTargetShape || 'circle')}
          </div>

          {activeShape && phase === 'showing' && (
            <div className="absolute center-top left-1/2 -translate-x-1/2 w-24 h-24 rounded-full flex items-center justify-center">
              <ShapeDisplay
                color={activeShape.color}
                shape={activeShape.shape}
                isActive={true}
                onTap={() => handleShapeTap(activeShape.color, activeShape.shape)}
              />
            </div>
          )}

          {!activeShape && phase === 'gap' && (
            <p className="mt-4 text-center text-slate-400">Shape disappeared - get ready for next</p>
          )}

          {!activeShape && phase === 'showing' && (
            <p className="mt-4 text-center text-slate-400">Tap the shape matching the instruction</p>
          )}
        </div>

        <div className="mt-4 flex justify-between text-sm text-slate-300 w-full">
          <span>Lives: {lives}</span>
          <span>Round: {round}/3</span>
          <span>Time: {Math.max(0, 60 - Math.floor(Date.now() / 1000 - (new Date().getTime() - 60000) / 1000))}s</span>
        </div>
      </div>
    );
  }

  if (state === 'gap') {
    // Gap phase - no shape visible, just text
    return (
      <div className="min-h-screen flex flex-col items-center justify-center p-4">
        <div className="flex items-center justify-between w-full mb-6">
          <button
            onClick={onExit}
            className="rounded-xl bg-panel px-3 py-1.5 text-sm font-semibold text-slate-300 active:scale-95"
            aria-label="Back to lobby"
          >
            ← Lobby
          </button>
          <span className="rounded-full bg-panel px-3 py-1 text-xs font-bold uppercase tracking-wider text-neon-cyan">
            {difficulty}
          </span>
          <button
            onClick={onExit}
            className="rounded-xl bg-panel px-3 py-1.5 text-sm font-semibold text-rose-300 active:scale-95"
            aria-label="Cancel game"
          >
            ✕ Give up
          </button>
        </div>

        <div className="relative w-full max-w-md">
          <div className="mt-3 text-lg font-bold text-white text-center">
            {currentInstruction || 'Tap only ' + (currentTargetColor || 'blue') + ' ' + (currentTargetShape || 'circle')}
          </div>

          <p className="mt-4 text-center text-slate-400">Get ready for the next shape...</p>

          <div className="mt-4 flex justify-between text-sm text-slate-300 w-full">
            <span>Lives: {lives}</span>
            <span>Round: {round}/3</span>
            <span>Time: {Math.max(0, 60 - Math.floor(Date.now() / 1000 - (new Date().getTime() - 60000) / 1000))}s</span>
          </div>
        </div>
      </div>
    );
  }

  if (state === 'round_result') {
    const result = roundResult!;
    const won = result.correct;
    return (
      <div className={`rounded-3xl p-6 text-center shadow-card animate-pop ${won ? 'bg-panel animate-pulseWin' : 'bg-panel'}`}>
        <div className="text-5xl" aria-hidden>{won ? '🏆' : '💪'}</div>
        <h2 className="mt-2 text-2xl font-bold text-white">{won ? 'Round Won!' : 'Missed Shape'}</h2>
        <p className="mt-1 text-sm text-slate-300">
          {won ? (
            <>
              Correct! +{result.scoreEarned} points
            </>
          ) : (
            <>
              Incorrect tap or missed shape
            </>
          )}
        </p>
        <div className="mt-4">
          <button
            onClick={() => setState('ready')}
            className="flex-1 rounded-xl bg-gradient-to-r from-neon-purple to-neon-cyan py-2.5 text-sm font-bold text-slate-200 active:scale-95"
          >
            Continue
          </button>
        </div>
      </div>
    );
  }

  if (state === 'game_over') {
    return (
      <div className="min-h-screen flex flex-col items-center justify-center p-8">
        <div className="rounded-3xl bg-panel p-8 text-center shadow-card animate-pop">
          <div className="text-6xl" aria-hidden>{score > 0 ? '🏆' : '💪'}</div>
          <h2 className="mt-2 text-2xl font-bold text-white">
            {score > 0 ? 'You Won!' : 'Out of Lives!'}
          </h2>
          <p className="mt-1 text-sm text-slate-300">
            Final Score: {score} · Rounds Completed: {roundsCompleted}/3
          </p>
          <div className="mt-6 grid grid-cols-2 gap-2">
            <button
              onClick={() => setState('ready')}
              className="rounded-xl bg-gradient-to-r from-neon-purple to-neon-cyan py-3 text-base font-bold text-white shadow-glow active:scale-[0.99]"
            >
              Play Again
            </button>
            <button
              onClick={() => onExit()}
              className="rounded-xl bg-navy py-3 text-base font-bold text-slate-200 active:scale-95"
            >
              Lobby
            </button>
          </div>
        </div>
      </div>
    );
  }

  return null;
}