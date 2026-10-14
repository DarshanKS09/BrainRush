import { useEffect, useState } from 'react';
import { api, type DashboardData, type HistoryItem } from '../api';
import type { WebAppContext } from '../telegram';
import { ErrorNotice, Loading, SectionTitle, StatTile, XpBar } from '../components/ui';
import { FriendPanel } from '../components/FriendPanel';
import { ReferralPanel } from '../components/ReferralPanel';
import { HistoryRow } from './History';

const PROFILE_PREVIEW_COUNT = 5;

export function ProfileScreen({ ctx, onViewHistory }: { ctx: WebAppContext; onViewHistory: () => void }) {
  const [data, setData] = useState<DashboardData | null>(null);
  const [history, setHistory] = useState<HistoryItem[]>([]);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);

  const load = () => {
    setLoading(true);
    setError('');
    Promise.all([api.me(ctx.initData), api.history(ctx.initData, PROFILE_PREVIEW_COUNT, 0)])
      .then(([me, hist]) => {
        setData(me);
        setHistory(hist.items.slice(0, PROFILE_PREVIEW_COUNT));
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  };

  useEffect(load, [ctx.initData]);

  if (loading) return <Loading label="Loading profile…" />;
  if (error || !data) return <ErrorNotice message={error || 'Failed to load.'} onRetry={load} />;

  const p = data.profile;
  return (
    <div className="space-y-4 animate-rise">
      <div className="rounded-2xl bg-panel p-4 shadow-card">
        <h1 className="text-lg font-bold text-white">
          {data.user.display_name || `@${data.user.username}` || 'Player'}
        </h1>
        <div className="mt-3">
          <XpBar into={p.xp_into_level} needed={p.xp_for_next} level={p.level} />
        </div>
      </div>

      <div className="grid grid-cols-3 gap-2">
        <StatTile label="Games" value={p.games_played} />
        <StatTile label="Wins" value={p.wins} accent="text-emerald-300" />
        <StatTile label="Losses" value={p.losses} accent="text-rose-300" />
        <StatTile label="Streak" value={`🔥 ${p.current_streak}`} />
        <StatTile label="Best run" value={p.longest_streak} />
        <StatTile label="Total XP" value={p.total_xp} accent="text-neon-cyan" />
      </div>

      <div className="rounded-2xl bg-panel p-4 shadow-card">
        <SectionTitle>Today (UTC)</SectionTitle>
        <p className="text-sm text-slate-300">
          {data.today.games_played} games · +{data.today.xp_earned} XP
        </p>
        {data.best_win_attempts !== null && (
          <p className="mt-1 text-sm text-slate-300">
            ⭐ Personal best: won in {data.best_win_attempts} {data.best_win_attempts === 1 ? 'try' : 'tries'}
          </p>
        )}
      </div>

      <div>
        <SectionTitle>Game history</SectionTitle>
        {history.length === 0 ? (
          <p className="rounded-2xl bg-panel p-4 text-center text-sm text-slate-500">No games played yet.</p>
        ) : (
          <>
            <ul className="space-y-2">
              {history.map((h) => (
                <HistoryRow key={h.session_id} h={h} />
              ))}
            </ul>
            <button
              onClick={onViewHistory}
              className="mt-2 w-full rounded-xl bg-panel py-2.5 text-sm font-bold text-neon-cyan active:scale-[0.99]"
            >
              View Full History →
            </button>
          </>
        )}
      </div>

      <FriendPanel ctx={ctx} />

      <ReferralPanel ctx={ctx} />
    </div>
  );
}
