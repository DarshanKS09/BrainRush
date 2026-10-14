import { useEffect, useState } from 'react';
import { api, type HistoryItem } from '../api';
import { formatDate, gameTitle, sessionStatusLabel } from '../gameutil';
import type { WebAppContext } from '../telegram';
import { ErrorNotice, Loading, SectionTitle } from '../components/ui';

const PAGE = 20;

function scoreText(h: HistoryItem): string {
  if (h.game_type === 'color_sequence') return `Lv ${h.score}`;
  if (h.game_type === 'reflex_rush') return `${h.score} pts`;
  if (h.game_type === 'perfect_second') return `${(h.score / 1000).toFixed(2)}s err`;
  return `${h.score} tries`;
}

export function HistoryRow({ h }: { h: HistoryItem }) {
  const icon =
    h.status === 'completed'
      ? (h.outcome === 'win' ? '🏆' : h.outcome === 'loss' ? '💪' : '🎮')
      : h.status === 'abandoned'
        ? '🚫'
        : h.status === 'expired'
          ? '⌛'
          : '🎮';
  return (
    <li className="flex items-center justify-between gap-2 rounded-2xl bg-panel px-3 py-2.5 text-sm shadow-card">
      <span className="min-w-0 flex-1 truncate font-semibold text-white">
        {icon} {gameTitle(h.game_type)} · {sessionStatusLabel(h.status, h.outcome)}
      </span>
      <span className="shrink-0 text-slate-400">
        {scoreText(h)} · +{h.xp_earned} XP · {formatDate(h.started_at)}
      </span>
    </li>
  );
}

export function HistoryScreen({ ctx, onBack }: { ctx: WebAppContext; onBack: () => void }) {
  const [items, setItems] = useState<HistoryItem[]>([]);
  const [offset, setOffset] = useState(0);
  const [hasMore, setHasMore] = useState(true);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);

  const load = (from: number) => {
    setError('');
    api
      .history(ctx.initData, PAGE, from)
      .then((r) => {
        setItems((prev) => (from === 0 ? r.items : [...prev, ...r.items]));
        setHasMore(r.items.length === PAGE);
        setOffset(from + r.items.length);
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  };

  useEffect(() => load(0), [ctx.initData]);

  if (loading && items.length === 0) return <Loading label="Loading history…" />;
  if (error && items.length === 0)
    return (
      <div className="space-y-3">
        <button
          onClick={onBack}
          className="rounded-xl bg-panel px-3 py-1.5 text-sm font-semibold text-slate-300 active:scale-95"
          aria-label="Back to profile"
        >
          ← Profile
        </button>
        <ErrorNotice message={error} onRetry={() => { setLoading(true); load(0); }} />
      </div>
    );

  return (
    <div className="space-y-3 animate-rise">
      <div className="flex items-center justify-between">
        <button
          onClick={onBack}
          className="rounded-xl bg-panel px-3 py-1.5 text-sm font-semibold text-slate-300 active:scale-95"
          aria-label="Back to profile"
        >
          ← Profile
        </button>
        <SectionTitle>Full history</SectionTitle>
        <span className="w-16" aria-hidden />
      </div>
      {items.length === 0 ? (
        <p className="rounded-2xl bg-panel p-4 text-center text-sm text-slate-500">
          No games played yet.
        </p>
      ) : (
        <ul className="space-y-2">
          {items.map((h) => (
            <HistoryRow key={h.session_id} h={h} />
          ))}
        </ul>
      )}
      {error && items.length > 0 && (
        <p className="text-center text-sm text-amber-300" role="alert">
          {error}{' '}
          <button onClick={() => load(offset)} className="font-bold underline">
            Retry
          </button>
        </p>
      )}
      {hasMore && items.length > 0 && (
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
