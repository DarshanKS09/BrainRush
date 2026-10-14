import { useEffect, useState } from 'react';
import { api, type GameInfo } from '../api';
import { difficultyDisplayName, difficultySub, reflexWaitText } from '../gameutil';
import type { WebAppContext } from '../telegram';
import { GameCard } from '../components/GameCard';
import { ErrorNotice, Loading, SectionTitle } from '../components/ui';
import { CreateMatchForm } from './Matches';
import { haptic } from '../telegram';

export function GamesScreen({
  ctx,
  onStart,
  onOpenMatch,
  onOpenMatches,
  onSetupMatch,
}: {
  ctx: WebAppContext;
  onStart: (gameId: string, sessionId: string) => void;
  onOpenMatch?: (matchId: string) => void;
  onOpenMatches?: () => void;
  onSetupMatch?: () => void;
}) {
  const [games, setGames] = useState<GameInfo[]>([]);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [picked, setPicked] = useState<GameInfo | null>(null);
  const [difficulty, setDifficulty] = useState('medium');
  const [starting, setStarting] = useState(false);
  const [startError, setStartError] = useState('');

  useEffect(() => {
    api
      .games(ctx.initData)
      .then((r) => setGames(r.games))
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }, [ctx.initData]);

  const begin = async () => {
    if (!picked) return;
    setStarting(true);
    setStartError('');
    try {
      const state = await api.start(ctx.initData, picked.id, difficulty);
      haptic('success');
      onStart(picked.id, state.session_id);
    } catch (e) {
      setStartError(e instanceof Error ? e.message : 'Could not start the game.');
    } finally {
      setStarting(false);
    }
  };

  if (loading) return <Loading label="Loading games…" />;
  if (error) return <ErrorNotice message={error} onRetry={() => window.location.reload()} />;
  return (
    <div className="space-y-3">
      <SectionTitle>Game lobby</SectionTitle>
      <button
        onClick={() => (onSetupMatch ?? onOpenMatches ?? (() => {}))()}
        className="w-full rounded-3xl bg-gradient-to-r from-amber-500 via-rose-500 to-neon-purple p-4 text-left shadow-glow active:scale-[0.99]"
      >
        <span className="flex items-center gap-2 text-lg font-black text-white">
          <span aria-hidden>👥</span> Play With Friends
        </span>
        <span className="mt-0.5 block text-xs font-medium text-white/85">
          Private room · pick a game &amp; mode · share a code or link
        </span>
      </button>
      <button
        onClick={onOpenMatches ?? (() => {})}
        className="w-full rounded-2xl bg-gradient-to-r from-neon-purple/20 to-neon-cyan/20 px-3 py-2.5 text-left ring-1 ring-neon-cyan/30 active:scale-[0.99]"
      >
        <span className="text-sm font-bold text-white">⚔️ Multiplayer matches</span>
        <span className="block text-xs text-slate-300">1v1 duels, free-for-all, tournaments — invite friends via link</span>
      </button>
      {games.map((g) => (
        <GameCard key={g.id} game={g} onPlay={(game) => { setPicked(game); setStartError(''); }} />
      ))}

      {picked?.playable && (
        <DifficultyModal
          picked={picked}
          difficulty={difficulty}
          setDifficulty={setDifficulty}
          starting={starting}
          startError={startError}
          onBack={() => setPicked(null)}
          onBegin={begin}
        />
      )}
      {picked?.playable && (
        <CreateMatchForm ctx={ctx} gameId={picked.id} onCreated={onOpenMatch ?? (() => {})} />
      )}
    </div>
  );
}

function XpRulesLine({ game, difficulty }: { game: GameInfo; difficulty: string }) {
  const rules = game.xp_rules?.[difficulty] as
    | { win_first_try?: number; win_last_try?: number; loss?: number; win?: number; loss_per_level?: number; win_bonus?: number; win_avg_ms?: number; perfect?: number; win_accuracy?: number }
    | undefined;
  if (!rules) return null;
  const text =
    game.id === 'color_sequence'
      ? `Win: +${rules.win} XP · Each level: +${rules.loss_per_level} XP`
      : game.id === 'reflex_rush'
        ? `Fast taps earn more · Win bonus: +${rules.win_bonus} XP`
        : game.id === 'perfect_second'
          ? `Perfect stop: +${rules.perfect} XP · ${rules.win_accuracy}%+ accuracy wins`
          : `Win XP: ${rules.win_first_try} first try → ${rules.win_last_try} last try · Loss: +${rules.loss} XP`;
  return <p className="mt-2 text-center text-xs text-slate-400">{text}</p>;
}

function ReflexRules({ game, difficulty }: { game: GameInfo; difficulty: string }) {
  if (game.id !== 'reflex_rush') return null;
  const d = game.difficulties.find((x) => x.id === difficulty);
  const winAvg = (game.xp_rules?.[difficulty] as { win_avg_ms?: number } | undefined)?.win_avg_ms;
  return (
    <div className="mt-2 rounded-xl bg-navy p-3 text-left text-xs text-slate-300">
      <p className="font-bold text-white">⏱️ {d ? reflexWaitText({ id: d.id, wait_min_ms: d.wait_min_ms, wait_max_ms: d.wait_max_ms }) : ''}</p>
      <p className="mt-1">5 rounds. Tapping before green is a false start: 0 points for that round, but it still counts.</p>
      <p className="mt-1">
        Faster valid taps earn more points and XP.
        {winAvg !== undefined && ` Win: average ≤ ${winAvg} ms with at most 1 false start.`}
      </p>
    </div>
  );
}

function DifficultyModal({
  picked,
  difficulty,
  setDifficulty,
  starting,
  startError,
  onBack,
  onBegin,
}: {
  picked: GameInfo;
  difficulty: string;
  setDifficulty: (d: string) => void;
  starting: boolean;
  startError: string;
  onBack: () => void;
  onBegin: () => void;
}) {
  return (
    <div className="fixed inset-0 z-20 flex items-end justify-center bg-black/70 p-4" role="dialog" aria-modal="true" aria-label="Choose difficulty">
      <div className="w-full max-w-md rounded-3xl bg-panel p-5 shadow-card animate-pop">
        <h3 className="text-lg font-bold text-white">{picked.title}</h3>
        <p className="mt-1 text-sm text-slate-400">
          {picked.id === 'color_sequence'
            ? 'Memorize the flashing colors, then repeat them. Longer runs earn more XP.'
            : picked.id === 'reflex_rush'
              ? 'Wait for green, then tap fast. False starts score 0 for that round.'
              : picked.id === 'perfect_second'
                ? 'Start the clock, then tap STOP exactly on the target. Closer stops earn up to 100 XP.'
                : 'Pick your difficulty. Fewer attempts, more XP per win.'}
        </p>
        <div className="mt-3 grid grid-cols-3 gap-2">
          {picked.difficulties.map((d) => (
            <button
              key={d.id}
              onClick={() => setDifficulty(d.id)}
              aria-pressed={difficulty === d.id}
              className={`rounded-xl px-2 py-2.5 text-sm font-bold transition-all ${
                difficulty === d.id
                  ? 'bg-gradient-to-br from-neon-purple to-neon-cyan text-white shadow-glow'
                  : 'bg-navy text-slate-300 active:scale-95'
              }`}
            >
              {difficultyDisplayName(picked.id, d.id)}
              <span className="block text-[11px] font-medium opacity-80">{difficultySub(picked.id, d)}</span>
            </button>
          ))}
        </div>
        <XpRulesLine game={picked} difficulty={difficulty} />
        <ReflexRules game={picked} difficulty={difficulty} />
        {startError && <p className="mt-2 text-center text-sm text-red-300" role="alert">{startError}</p>}
        <div className="mt-4 flex gap-2">
          <button
            onClick={onBack}
            className="flex-1 rounded-xl bg-navy py-2.5 text-sm font-bold text-slate-300 active:scale-95"
          >
            Back
          </button>
          <button
            onClick={onBegin}
            disabled={starting}
            className="flex-1 rounded-xl bg-gradient-to-r from-neon-purple to-neon-cyan py-2.5 text-sm font-bold text-white shadow-glow active:scale-95 disabled:opacity-50"
          >
            {starting ? 'Starting…' : 'Start game'}
          </button>
        </div>
      </div>
    </div>
  );
}
