import { useEffect, useState } from 'react';
import { api, ApiError, type GameInfo } from '../api';
import { difficultyDisplayName, gameTitle } from '../gameutil';
import type { WebAppContext } from '../telegram';
import { ErrorNotice, Loading, SectionTitle } from '../components/ui';
import { haptic } from '../telegram';

const MODES = [
  {
    id: 'duel',
    title: '1v1 Duel',
    desc: 'You plus one friend. Exactly 2 players, winner takes the round.',
    min: 2,
    cap: 2,
  },
  {
    id: 'ffa',
    title: 'Free-for-All',
    desc: 'You plus 2–7 friends. Everyone plays on their own phone; all scores rank.',
    min: 3,
    cap: 8,
  },
  {
    id: 'tournament',
    title: 'Tournament',
    desc: 'A bigger group battle. Ranked 1st…last when everyone finishes or time runs out.',
    min: 5,
    cap: 16,
  },
];

export function JoinByCode({ ctx, onJoined }: { ctx: WebAppContext; onJoined: (matchId: string) => void }) {
  const [code, setCode] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const join = async () => {
    const value = code.trim();
    if (!value) {
      setError('Enter the room code from your friend.');
      return;
    }
    setBusy(true);
    setError('');
    try {
      const view = await api.matchJoinByCode(ctx.initData, value);
      haptic('success');
      onJoined(view.match_id);
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) {
        setError('Room not found. Please check the code.');
      } else {
        setError(e instanceof Error ? e.message : 'Could not join the room.');
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="rounded-3xl bg-panel p-4 shadow-card">
      <SectionTitle>Join Room</SectionTitle>
      <p className="mt-1 text-xs text-slate-400">
        Enter the 6-letter room code — no invitation needed.
      </p>
      <div className="mt-2 flex gap-2">
        <input
          value={code}
          onChange={(e) => setCode(e.target.value.toUpperCase())}
          placeholder="e.g. KQ7X2P"
          aria-label="Room code"
          maxLength={12}
          autoCapitalize="characters"
          autoCorrect="off"
          className="min-w-0 flex-1 rounded-xl bg-abyss px-3 py-2.5 text-center font-mono text-lg font-bold tracking-[0.3em] text-white placeholder:text-slate-600"
        />
        <button
          onClick={() => void join()}
          disabled={busy}
          aria-label="Join room by code"
          className="shrink-0 rounded-xl bg-gradient-to-r from-neon-purple to-neon-cyan px-4 py-2.5 text-sm font-bold text-white shadow-glow active:scale-95 disabled:opacity-50"
        >
          {busy ? 'Joining…' : 'Join Room'}
        </button>
      </div>
      {error && (
        <p className="mt-2 text-center text-sm text-red-300" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}

export function MatchSetupScreen({
  ctx,
  onOpenMatch,
  onBack,
}: {
  ctx: WebAppContext;
  onOpenMatch: (matchId: string) => void;
  onBack: () => void;
}) {
  const [games, setGames] = useState<GameInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [gameId, setGameId] = useState<string | null>(null);
  const [mode, setMode] = useState('duel');
  const [maxPlayers, setMaxPlayers] = useState(4);
  const [difficulty, setDifficulty] = useState('medium');
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState('');

  useEffect(() => {
    api
      .games(ctx.initData)
      .then((r) => {
        setGames(r.games);
        const firstMp = r.games.find((g) => g.playable && g.multiplayer);
        if (firstMp) setGameId(firstMp.id);
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }, [ctx.initData]);

  const game = games.find((g) => g.id === gameId) ?? null;
  const modeInfo = MODES.find((m) => m.id === mode) ?? MODES[0];
  const cappedMax = Math.min(Math.max(maxPlayers, modeInfo.min), modeInfo.cap);

  const create = async () => {
    if (!game) return;
    setCreating(true);
    setCreateError('');
    try {
      const view = await api.matchCreate(
        ctx.initData,
        game.id,
        mode,
        difficulty,
        mode === 'duel' ? undefined : cappedMax,
      );
      haptic('success');
      onOpenMatch(view.match_id);
    } catch (e) {
      setCreateError(e instanceof Error ? e.message : 'Could not create the room.');
    } finally {
      setCreating(false);
    }
  };

  if (loading) return <Loading label="Loading games…" />;
  if (error) return <ErrorNotice message={error} onRetry={() => window.location.reload()} />;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <button
          onClick={onBack}
          className="rounded-xl bg-panel px-3 py-1.5 text-sm font-semibold text-slate-300 active:scale-95"
          aria-label="Back to games"
        >
          ← Games
        </button>
        <span className="rounded-full bg-panel px-3 py-1 text-xs font-bold uppercase tracking-wider text-neon-cyan">
          Private room
        </span>
      </div>

      <JoinByCode ctx={ctx} onJoined={onOpenMatch} />

      <div>
        <SectionTitle>Step 1 — Pick a game</SectionTitle>
        <ul className="mt-2 space-y-2">
          {games.map((g) => {
            const mp = g.playable && g.multiplayer;
            const selected = gameId === g.id;
            return (
              <li key={g.id}>
                <button
                  onClick={() => mp && setGameId(g.id)}
                  disabled={!mp}
                  aria-pressed={selected}
                  className={`flex w-full items-center justify-between gap-2 rounded-2xl px-3 py-2.5 text-left shadow-card active:scale-[0.99] disabled:cursor-default ${
                    selected
                      ? 'bg-gradient-to-r from-neon-purple/40 to-neon-cyan/40 ring-1 ring-neon-cyan/60'
                      : 'bg-panel'
                  } ${!mp ? 'opacity-60' : ''}`}
                >
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-bold text-white">{gameTitle(g.id)}</span>
                    <span className="block text-[11px] text-slate-400">
                      {mp
                        ? `Multiplayer: ${(g.multiplayer?.modes ?? []).join(', ')}`
                        : g.playable
                          ? 'Solo only for now'
                          : 'Coming soon'}
                    </span>
                  </span>
                  {selected && <span className="text-neon-cyan" aria-hidden>✓</span>}
                </button>
              </li>
            );
          })}
        </ul>
      </div>

      <div>
        <SectionTitle>Step 2 — Pick a mode</SectionTitle>
        <div className="mt-2 grid grid-cols-3 gap-2">
          {MODES.map((m) => (
            <button
              key={m.id}
              onClick={() => {
                setMode(m.id);
                setMaxPlayers(Math.min(Math.max(m.min + 1, m.min), m.cap));
              }}
              aria-pressed={mode === m.id}
              className={`rounded-xl px-2 py-2.5 text-xs font-bold ${
                mode === m.id
                  ? 'bg-gradient-to-br from-neon-purple to-neon-cyan text-white shadow-glow'
                  : 'bg-panel text-slate-300 active:scale-95'
              }`}
            >
              {m.title}
              <span className="block text-[10px] font-medium opacity-80">
                {m.id === 'duel' ? '2 players' : `${m.min}–${m.cap} players`}
              </span>
            </button>
          ))}
        </div>
        <p className="mt-1 text-xs text-slate-400">{modeInfo.desc}</p>
        {mode !== 'duel' && (
          <div className="mt-2 flex items-center justify-between rounded-xl bg-panel px-3 py-2">
            <span className="text-xs font-bold text-slate-300">Max players</span>
            <span className="flex items-center gap-3">
              <button
                onClick={() => setMaxPlayers((n) => Math.max(modeInfo.min, n - 1))}
                className="rounded-lg bg-navy px-3 py-1 text-base font-bold text-white active:scale-95"
                aria-label="Fewer max players"
              >
                −
              </button>
              <span className="w-6 text-center text-sm font-bold text-neon-cyan" aria-live="polite">
                {cappedMax}
              </span>
              <button
                onClick={() => setMaxPlayers((n) => Math.min(modeInfo.cap, n + 1))}
                className="rounded-lg bg-navy px-3 py-1 text-base font-bold text-white active:scale-95"
                aria-label="More max players"
              >
                +
              </button>
            </span>
          </div>
        )}
      </div>

      <div>
        <SectionTitle>Step 3 — Difficulty &amp; create</SectionTitle>
        <div className="mt-2 grid grid-cols-3 gap-2">
          {['easy', 'medium', 'hard'].map((d) => (
            <button
              key={d}
              onClick={() => setDifficulty(d)}
              aria-pressed={difficulty === d}
              className={`rounded-xl py-2 text-xs font-bold capitalize ${
                difficulty === d ? 'bg-panel text-neon-cyan ring-1 ring-neon-cyan/50' : 'bg-panel/60 text-slate-400 active:scale-95'
              }`}
            >
              {difficultyDisplayName(game?.id ?? '', d)}
            </button>
          ))}
        </div>
        {createError && (
          <p className="mt-2 text-center text-sm text-red-300" role="alert">
            {createError}
          </p>
        )}
        <button
          onClick={() => void create()}
          disabled={!game || creating}
          className="mt-3 w-full rounded-xl bg-gradient-to-r from-neon-purple to-neon-cyan py-3 text-base font-bold text-white shadow-glow active:scale-[0.99] disabled:opacity-50"
        >
          {creating ? 'Creating…' : `Create private room${game ? ` · ${gameTitle(game.id)} ${modeInfo.title}` : ''}`}
        </button>
        <p className="mt-1 text-center text-[11px] text-slate-500">
          You&apos;ll get a room code + invite link to share. Minimum to start:{' '}
          {mode === 'duel' ? '2 players' : `${modeInfo.min} players`}.
        </p>
      </div>
    </div>
  );
}
