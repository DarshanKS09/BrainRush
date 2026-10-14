import { useState } from 'react';
import { api } from '../api';
import { gameTitle } from '../gameutil';
import type { WebAppContext } from '../telegram';
import { MatchLists } from './MatchLists';

const MODES = [
  { id: 'duel', label: '1v1 Duel', hint: 'Exactly 2 players' },
  { id: 'ffa', label: 'Free-for-All', hint: '3–8 players' },
  { id: 'tournament', label: 'Tournament', hint: '5+ players' },
];

export function MatchesScreen({
  ctx,
  onOpen,
}: {
  ctx: WebAppContext;
  onOpen: (matchId: string) => void;
}) {
  return <MatchLists ctx={ctx} onOpen={onOpen} />;
}

export function CreateMatchForm({
  ctx,
  gameId,
  onCreated,
}: {
  ctx: WebAppContext;
  gameId: string;
  onCreated: (matchId: string) => void;
}) {
  const [mode, setMode] = useState('duel');
  const [difficulty, setDifficulty] = useState('hard');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const create = async () => {
    setBusy(true);
    setError('');
    try {
      const view = await api.matchCreate(ctx.initData, gameId, mode, difficulty);
      onCreated(view.match_id);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not create the match.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="rounded-3xl bg-panel p-4 shadow-card">
      <h3 className="font-bold text-white">⚔️ Play {gameTitle(gameId)} with friends</h3>
      <div className="mt-2 grid grid-cols-3 gap-2">
        {MODES.map((m) => (
          <button
            key={m.id}
            onClick={() => setMode(m.id)}
            aria-pressed={mode === m.id}
            className={`rounded-xl px-2 py-2 text-xs font-bold ${mode === m.id ? 'bg-gradient-to-br from-neon-purple to-neon-cyan text-white' : 'bg-navy text-slate-300'}`}
          >
            {m.label}
            <span className="block text-[10px] font-medium opacity-80">{m.hint}</span>
          </button>
        ))}
      </div>
      <div className="mt-2 grid grid-cols-3 gap-2">
        {['easy', 'medium', 'hard'].map((d) => (
          <button
            key={d}
            onClick={() => setDifficulty(d)}
            aria-pressed={difficulty === d}
            className={`rounded-xl py-1.5 text-xs font-bold capitalize ${difficulty === d ? 'bg-navy text-neon-cyan ring-1 ring-neon-cyan/50' : 'bg-navy/50 text-slate-400'}`}
          >
            {d}
          </button>
        ))}
      </div>
      {error && <p className="mt-2 text-sm text-red-300" role="alert">{error}</p>}
      <button
        onClick={() => void create()}
        disabled={busy}
        className="mt-3 w-full rounded-xl bg-gradient-to-r from-neon-purple to-neon-cyan py-2.5 text-sm font-bold text-white disabled:opacity-50"
      >
        {busy ? 'Creating…' : 'Create match lobby'}
      </button>
    </div>
  );
}
