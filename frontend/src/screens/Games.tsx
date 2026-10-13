import { useEffect, useState } from 'react';
import { api, type GameInfo } from '../api';
import { difficultyBlurb, difficultyLabel } from '../gameutil';
import type { WebAppContext } from '../telegram';
import { GameCard } from '../components/GameCard';
import { ErrorNotice, Loading, SectionTitle } from '../components/ui';
import { haptic } from '../telegram';

export function GamesScreen({
  ctx,
  onStart,
}: {
  ctx: WebAppContext;
  onStart: (sessionId: string) => void;
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
      const state = await api.start(ctx.initData, difficulty);
      haptic('success');
      onStart(state.session_id);
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
      {games.map((g) => (
        <GameCard key={g.id} game={g} onPlay={(game) => { setPicked(game); setStartError(''); }} />
      ))}

      {picked?.playable && (
        <div className="fixed inset-0 z-20 flex items-end justify-center bg-black/70 p-4" role="dialog" aria-modal="true" aria-label="Choose difficulty">
          <div className="w-full max-w-md rounded-3xl bg-panel p-5 shadow-card animate-pop">
            <h3 className="text-lg font-bold text-white">{picked.title}</h3>
            <p className="mt-1 text-sm text-slate-400">Pick your difficulty. Fewer attempts, more XP per win.</p>
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
                  {difficultyLabel(d.id)}
                  <span className="block text-[11px] font-medium opacity-80">{difficultyBlurb(d.max_attempts)}</span>
                </button>
              ))}
            </div>
            {picked.xp_rules && (
              <p className="mt-2 text-center text-xs text-slate-400">
                Win XP: {picked.xp_rules[difficulty]?.win_first_try} first try →{' '}
                {picked.xp_rules[difficulty]?.win_last_try} last try · Loss: +{picked.xp_rules[difficulty]?.loss} XP
              </p>
            )}
            {startError && <p className="mt-2 text-center text-sm text-red-300" role="alert">{startError}</p>}
            <div className="mt-4 flex gap-2">
              <button
                onClick={() => setPicked(null)}
                className="flex-1 rounded-xl bg-navy py-2.5 text-sm font-bold text-slate-300 active:scale-95"
              >
                Back
              </button>
              <button
                onClick={begin}
                disabled={starting}
                className="flex-1 rounded-xl bg-gradient-to-r from-neon-purple to-neon-cyan py-2.5 text-sm font-bold text-white shadow-glow active:scale-95 disabled:opacity-50"
              >
                {starting ? 'Starting…' : 'Start game'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
