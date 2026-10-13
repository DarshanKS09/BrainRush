import { useEffect, useState } from 'react';
import { api, type LeaderboardEntry } from '../api';
import type { WebAppContext } from '../telegram';
import { ErrorNotice, Loading, SectionTitle } from '../components/ui';

const PAGE = 20;

function medal(rank: number): string {
  if (rank === 1) return '🥇';
  if (rank === 2) return '🥈';
  if (rank === 3) return '🥉';
  return `#${rank}`;
}

export function LeaderboardScreen({ ctx }: { ctx: WebAppContext }) {
  const [entries, setEntries] = useState<LeaderboardEntry[]>([]);
  const [myRank, setMyRank] = useState<number | null>(null);
  const [offset, setOffset] = useState(0);
  const [hasMore, setHasMore] = useState(true);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);

  const load = (from: number) => {
    setError('');
    api
      .leaderboard(ctx.initData, PAGE, from)
      .then((r) => {
        setEntries((prev) => (from === 0 ? r.entries : [...prev, ...r.entries]));
        setMyRank(r.my_rank);
        setHasMore(r.entries.length === PAGE);
        setOffset(from + r.entries.length);
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  };

  useEffect(() => load(0), [ctx.initData]);

  if (loading && entries.length === 0) return <Loading label="Loading rankings…" />;
  if (error && entries.length === 0)
    return <ErrorNotice message={error} onRetry={() => { setLoading(true); load(0); }} />;

  return (
    <div className="space-y-3">
      <SectionTitle>Leaderboard · Top by XP</SectionTitle>
      {myRank !== null && (
        <p className="rounded-2xl bg-gradient-to-r from-violet-700/50 to-cyan-600/30 p-3 text-center text-sm font-bold text-white">
          Your rank: #{myRank}
        </p>
      )}
      {entries.length === 0 ? (
        <p className="rounded-2xl bg-panel p-4 text-center text-sm text-slate-500">
          No ranked players yet — finish a game to claim the top spot.
        </p>
      ) : (
        <ul className="space-y-2">
          {entries.map((e) => (
            <li key={`${e.rank}-${e.display_name}`} className="flex items-center gap-3 rounded-2xl bg-panel px-3 py-2.5 shadow-card animate-rise">
              <span className="w-10 text-center font-bold text-white">{medal(e.rank)}</span>
              <span className="min-w-0 flex-1 truncate text-sm font-semibold text-white">{e.display_name}</span>
              <span className="text-xs text-slate-400">Lv {e.level}</span>
              <span className="text-sm font-bold text-neon-cyan">{e.total_xp} XP</span>
            </li>
          ))}
        </ul>
      )}
      {hasMore && entries.length > 0 && (
        <button
          onClick={() => load(offset)}
          className="w-full rounded-xl bg-panel py-2.5 text-sm font-bold text-slate-200 active:scale-[0.99]"
        >
          Load more
        </button>
      )}
    </div>
  );
}
