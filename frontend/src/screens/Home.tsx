import { useEffect, useState } from 'react';
import { api, type DashboardData, type HistoryItem } from '../api';
import { formatDate, gameTitle, resumeHint, sessionStatusLabel } from '../gameutil';
import type { WebAppContext } from '../telegram';
import { ErrorNotice, Loading, SectionTitle, StatTile, XpBar } from '../components/ui';

export function HomeScreen({
  ctx,
  onPlayNow,
  onResume,
}: {
  ctx: WebAppContext;
  onPlayNow: () => void;
  onResume: (gameId: string, sessionId: string) => void;
}) {
  const [data, setData] = useState<DashboardData | null>(null);
  const [history, setHistory] = useState<HistoryItem[]>([]);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);

  const load = () => {
    setLoading(true);
    setError('');
    Promise.all([api.me(ctx.initData), api.history(ctx.initData, 5, 0)])
      .then(([me, hist]) => {
        setData(me);
        setHistory(hist.items);
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  };

  useEffect(load, [ctx.initData]);

  if (loading) return <Loading label="Loading your arcade…" />;
  if (error || !data) return <ErrorNotice message={error || 'Failed to load.'} onRetry={load} />;

  const initial = (data.user.display_name || data.user.username || 'P').charAt(0).toUpperCase();
  return (
    <div className="space-y-4 animate-rise">
      <header className="flex items-center gap-3 rounded-2xl bg-gradient-to-r from-violet-700/60 to-cyan-600/40 p-4 shadow-card">
        <div
          className="flex h-12 w-12 items-center justify-center rounded-full bg-gradient-to-br from-neon-purple to-neon-cyan text-xl font-bold text-white"
          aria-hidden
        >
          {initial}
        </div>
        <div className="min-w-0 flex-1">
          <h1 className="truncate text-lg font-bold text-white">
            {data.user.display_name || `@${data.user.username}` || 'Player'}
          </h1>
          <p className="text-xs text-slate-300">Welcome back to BrainRush</p>
        </div>
        <span className="rounded-full bg-black/40 px-3 py-1 text-sm font-bold text-neon-cyan">
          Lv {data.profile.level}
        </span>
      </header>

      <div className="rounded-2xl bg-panel p-4 shadow-card">
        <XpBar into={data.profile.xp_into_level} needed={data.profile.xp_for_next} level={data.profile.level} />
      </div>

      <div className="grid grid-cols-4 gap-2">
        <StatTile label="Streak" value={`🔥 ${data.profile.current_streak}`} />
        <StatTile label="Games" value={data.profile.games_played} />
        <StatTile label="Wins" value={data.profile.wins} />
        <StatTile label="Rank" value={`#${data.rank}`} accent="text-neon-cyan" />
      </div>

      <button
        onClick={onPlayNow}
        className="w-full rounded-2xl bg-gradient-to-r from-neon-purple to-neon-cyan py-3.5 text-lg font-bold text-white shadow-glow active:scale-[0.99]"
      >
        ▶ Play Now
      </button>

      {data.active_games.length > 0 && (
        <div className="rounded-2xl border border-neon-cyan/30 bg-cyan-500/10 p-4">
          <SectionTitle>Resume your game</SectionTitle>
          {data.active_games.map((g) => (
            <button
              key={g.session_id}
              onClick={() => onResume(g.game_type, g.session_id)}
              className="mt-1 flex w-full items-center justify-between rounded-xl bg-panel px-3 py-2.5 text-sm font-semibold text-white active:scale-[0.99]"
            >
              <span>{g.game_type === 'color_sequence' ? '🎨' : g.game_type === 'reflex_rush' ? '👆' : '🔢'} {gameTitle(g.game_type)} · {g.difficulty}</span>
              <span className="text-neon-cyan">{resumeHint(g)} →</span>
            </button>
          ))}
        </div>
      )}

      <div>
        <SectionTitle>Recent results</SectionTitle>
        {history.length === 0 ? (
          <p className="rounded-2xl bg-panel p-4 text-center text-sm text-slate-500">
            No games yet — your results will appear here.
          </p>
        ) : (
          <ul className="space-y-2">
            {history.map((h) => (
              <li key={h.session_id} className="flex items-center justify-between rounded-2xl bg-panel px-3 py-2.5 text-sm shadow-card">
                <span className="font-semibold text-white">
                  {h.status === 'completed'
                    ? (h.outcome === 'win' ? '🏆' : h.outcome === 'loss' ? '💪' : '🎮')
                    : h.status === 'abandoned'
                      ? '🚫'
                      : h.status === 'expired'
                        ? '⌛'
                        : '🎮'}{' '}
                  {sessionStatusLabel(h.status, h.outcome)}
                </span>
                <span className="text-slate-400">
                  {h.game_type === 'color_sequence' ? `Lv ${h.score}` : h.game_type === 'reflex_rush' ? `${h.score} pts` : `${h.score} tries`} · +{h.xp_earned} XP · {formatDate(h.started_at)}
                </span>
              </li>
            ))}
          </ul>
        )}
        {data.best_win_attempts !== null && (
          <p className="mt-2 text-center text-xs text-slate-400">
            ⭐ Personal best: won in {data.best_win_attempts} {data.best_win_attempts === 1 ? 'try' : 'tries'}
          </p>
        )}
        {data.best_color_level !== null && data.best_color_level !== undefined && (
          <p className="mt-1 text-center text-xs text-slate-400">
            🎨 Color best: reached level {data.best_color_level}
          </p>
        )}
        {data.best_reflex_score !== null && data.best_reflex_score !== undefined && (
          <p className="mt-1 text-center text-xs text-slate-400">
            👆 Reflex best: {data.best_reflex_score} pts
          </p>
        )}
      </div>

      <div className="rounded-2xl bg-panel p-4 text-center shadow-card">
        <p className="text-sm font-semibold text-slate-300">📅 Daily Challenge</p>
        <p className="mt-1 text-xs text-slate-500">Coming soon — check back after more games launch.</p>
      </div>
    </div>
  );
}
