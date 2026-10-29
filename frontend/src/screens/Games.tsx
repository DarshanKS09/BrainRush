/** Games library: a polished 3-column game grid.
 *
 * Replaces the old vertically stacked full-width cards. Every registered
 * game appears exactly once as a compact tile (icon + name). Tapping a
 * playable tile opens an in-place details panel (no navigation away) that
 * shows the description, difficulties, and modes, with a prominent Play Now
 * button. Exactly one colorful "Play With Friends" button sits at the top,
 * separate from the grid, and opens the existing multiplayer hub.
 */
import { useEffect, useMemo, useState } from 'react';
import { api, type GameInfo } from '../api';
import { difficultyDisplayName, difficultySub } from '../gameutil';
import type { WebAppContext } from '../telegram';
import { GameTile } from '../components/GameTile';
import { ErrorNotice, Loading, SectionTitle } from '../components/ui';
import { haptic } from '../telegram';

const MODE_LABELS: Record<string, string> = {
  duel: '1v1 Duel',
  ffa: 'Free-for-All',
  tournament: 'Tournament',
};

export function GamesScreen({
  ctx,
  onStart,
  onSetupMatch,
}: {
  ctx: WebAppContext;
  onStart: (gameId: string, sessionId: string) => void;
  onSetupMatch?: () => void;
}) {
  const [games, setGames] = useState<GameInfo[]>([]);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [selected, setSelected] = useState<GameInfo | null>(null);
  const [difficulty, setDifficulty] = useState('medium');
  const [starting, setStarting] = useState(false);
  const [startError, setStartError] = useState('');

  useEffect(() => {
    setLoading(true);
    setError('');
    api
      .games(ctx.initData)
      .then((r) => setGames(r.games))
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }, [ctx.initData]);

  const filtered = useMemo(
    () => games.filter((g) => g.title.toLowerCase().includes(search.toLowerCase())),
    [games, search],
  );

  const begin = async () => {
    if (!selected) return;
    setStarting(true);
    setStartError('');
    try {
      const state = await api.start(ctx.initData, selected.id, difficulty);
      haptic('success');
      onStart(selected.id, state.session_id);
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
      {/* Exactly one prominent Play With Friends button, separate from the grid. */}
      <button
        onClick={() => (onSetupMatch ?? (() => {}))()}
        className="w-full rounded-3xl bg-gradient-to-r from-amber-500 via-rose-500 to-neon-purple p-4 text-left shadow-glow active:scale-[0.99]"
      >
        <span className="flex items-center gap-2 text-lg font-black text-white">
          <span aria-hidden>👥</span> Play With Friends
        </span>
        <span className="mt-0.5 block text-xs font-medium text-white/85">
          Private room · pick a game & mode · share a code or link
        </span>
      </button>

      {/* Compact client-side search (no backend requests). */}
      <div className="relative">
        <input
          type="search"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search games…"
          aria-label="Search games"
          className="w-full rounded-xl bg-abyss px-3 py-2.5 pl-9 pr-3 text-sm text-white placeholder:text-slate-500 focus:outline-none focus:ring-2 focus:ring-neon-cyan"
        />
        <span className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500 text-xs" aria-hidden>
          🔍
        </span>
      </div>

      <SectionTitle>Games</SectionTitle>
      {filtered.length === 0 ? (
        <p className="rounded-2xl bg-panel p-4 text-center text-sm text-slate-400">
          No games match your search.
        </p>
      ) : (
        <div className="grid grid-cols-3 gap-2">
          {filtered.map((g) => (
            <GameTile key={g.id} game={g} onSelect={setSelected} />
          ))}
        </div>
      )}

      {/* In-place details panel (overlay): keeps routing intact, no navigation away. */}
      {selected && (
        <GameDetailsPanel
          game={selected}
          difficulty={difficulty}
          setDifficulty={setDifficulty}
          starting={starting}
          startError={startError}
          onClose={() => setSelected(null)}
          onPlay={begin}
          onPlayWithFriends={onSetupMatch}
        />
      )}
    </div>
  );
}

/** Difficulty chips reused by the details panel. */
function DifficultyChips({
  game,
  difficulty,
  setDifficulty,
}: {
  game: GameInfo;
  difficulty: string;
  setDifficulty: (d: string) => void;
}) {
  return (
    <div className="mt-2 grid grid-cols-3 gap-1.5">
      {game.difficulties.map((d) => {
        const active = difficulty === d.id;
        return (
          <button
            key={d.id}
            onClick={() => setDifficulty(d.id)}
            aria-pressed={active}
            className={`rounded-xl px-2 py-1.5 text-xs font-bold transition-all ${
              active
                ? 'bg-gradient-to-br from-neon-purple to-neon-cyan text-white shadow-glow'
                : 'bg-navy text-slate-300 active:scale-95'
            }`}
          >
            {difficultyDisplayName(game.id, d.id)}
            <span className="block text-[10px] font-medium opacity-70">
              {difficultySub(game.id, d)}
            </span>
          </button>
        );
      })}
    </div>
  );
}

/** Game details panel: opens when a grid tile is tapped. */
function GameDetailsPanel({
  game,
  difficulty,
  setDifficulty,
  starting,
  startError,
  onClose,
  onPlay,
  onPlayWithFriends,
}: {
  game: GameInfo;
  difficulty: string;
  setDifficulty: (d: string) => void;
  starting: boolean;
  startError: string;
  onClose: () => void;
  onPlay: () => void;
  onPlayWithFriends?: () => void;
}) {
  const multiplayerModes = (game.multiplayer?.modes ?? []).filter(Boolean);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4"
      role="dialog"
      aria-modal="true"
      aria-label={game.title}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="w-full max-w-md rounded-3xl bg-panel p-6 shadow-card animate-pop">
        <div className="flex items-center justify-between mb-1">
          <div className="flex h-[64px] w-[64px] items-center justify-center rounded-2xl bg-gradient-to-r from-neon-purple to-neon-cyan text-white shadow-glow">
            <span className="text-3xl" aria-hidden>
              {({
                number_guessing: '🔢',
                color_sequence: '🎨',
                reflex_rush: '⚡',
                perfect_second: '⏱️',
                maze_race: '🌀',
                memory_match: '🃏',
                reaction_test: '🎯',
                math_challenge: '➗',
                word_puzzle: '🔤',
              } as Record<string, string>)[game.id] ?? '🎲'}
            </span>
          </div>
          <button
            onClick={onClose}
            className="rounded-xl bg-navy p-1.5 text-slate-400 active:bg-white/10 active:scale-95"
            aria-label="Close"
          >
            ✕
          </button>
        </div>
        <h2 className="mt-1 text-lg font-bold text-white">{game.title}</h2>
        <p className="mt-1 text-sm text-slate-300">{game.description}</p>

        {game.playable && game.difficulties.length > 0 && (
          <>
            <SectionTitle>Difficulty</SectionTitle>
            <DifficultyChips game={game} difficulty={difficulty} setDifficulty={setDifficulty} />
          </>
        )}

        {multiplayerModes.length > 0 && (
          <>
            <SectionTitle>Play with friends</SectionTitle>
            <p className="mt-1 text-xs text-slate-400">
              Modes: {multiplayerModes.map((m) => MODE_LABELS[m] ?? m).join(' · ')}
            </p>
            <button
              onClick={() => {
                onClose();
                (onPlayWithFriends ?? (() => {}))();
              }}
              className="mt-2 w-full rounded-xl bg-navy border border-white/20 px-3 py-2 text-sm font-bold text-slate-200 active:bg-white/10 disabled:opacity-50"
              disabled={!game.playable}
            >
              Open Play With Friends
            </button>
          </>
        )}

        {!game.playable && (
          <p className="mt-2 text-xs text-slate-500 text-center">
            Coming soon — no gameplay yet.
          </p>
        )}

        {startError && (
          <p className="mt-2 text-center text-sm text-red-300" role="alert">
            {startError}
          </p>
        )}

        <div className="mt-5 flex gap-2">
          {game.playable ? (
            <button
              onClick={onPlay}
              disabled={starting}
              className="flex-1 rounded-xl bg-gradient-to-r from-neon-purple to-neon-cyan py-3 text-sm font-bold text-white shadow-glow active:scale-[0.98] disabled:opacity-50"
            >
              {starting ? 'Starting…' : 'Play Now'}
            </button>
          ) : (
            <button
              disabled
              className="flex-1 rounded-xl bg-navy py-3 text-sm font-bold text-slate-500 cursor-not-allowed"
            >
              Coming soon
            </button>
          )}
          <button
            onClick={onClose}
            className="flex-1 rounded-xl bg-navy py-3 text-sm font-bold text-slate-300 active:scale-95"
          >
            Back
          </button>
        </div>
      </div>
    </div>
  );
}
