import { useCallback, useEffect, useState } from 'react';
import { api, type MatchInviteItem, type MatchListItem } from '../api';
import { formatDate, gameTitle } from '../gameutil';
import type { WebAppContext } from '../telegram';
import { ErrorNotice, Loading, SectionTitle } from '../components/ui';

/** Invitations, active rooms, and history. Shared by the matches list and
 * the Play With Friends hub so both stay identical. */
export function MatchLists({
  ctx,
  onOpen,
}: {
  ctx: WebAppContext;
  onOpen: (matchId: string) => void;
}) {
  const [invites, setInvites] = useState<MatchInviteItem[]>([]);
  const [mine, setMine] = useState<MatchListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [joining, setJoining] = useState<string | null>(null);
  const [notice, setNotice] = useState('');

  const load = useCallback(() => {
    setError('');
    Promise.all([api.matchInvites(ctx.initData), api.matchMine(ctx.initData, 20, 0)])
      .then(([inv, my]) => {
        setInvites(inv.items);
        setMine(my.items);
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }, [ctx.initData]);

  useEffect(load, [load]);

  const join = async (matchId: string) => {
    setJoining(matchId);
    setNotice('');
    try {
      await api.matchJoin(ctx.initData, matchId);
      onOpen(matchId);
    } catch (e) {
      setNotice(e instanceof Error ? e.message : 'Could not join.');
    } finally {
      setJoining(null);
    }
  };

  if (loading) return <Loading label="Loading matches…" />;
  if (error) return <ErrorNotice message={error} onRetry={load} />;

  return (
    <div className="space-y-4">
      <div>
        <SectionTitle>Match invitations</SectionTitle>
        {invites.length === 0 ? (
          <p className="rounded-2xl bg-panel p-3 text-sm text-slate-400">No pending invitations.</p>
        ) : (
          <ul className="space-y-2">
            {invites.map((inv) => (
              <li key={inv.match_id} className="flex items-center gap-2 rounded-2xl bg-panel px-3 py-2.5 shadow-card">
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-bold text-white">
                    {gameTitle(inv.game_type)} · {inv.mode} · {inv.host_display_name}
                  </p>
                  <p className="text-xs text-slate-400">
                    {inv.participants}/{inv.max_players} players · {inv.difficulty}
                  </p>
                </div>
                <button
                  onClick={() => void join(inv.match_id)}
                  disabled={joining === inv.match_id}
                  className="rounded-xl bg-gradient-to-r from-neon-purple to-neon-cyan px-3 py-1.5 text-sm font-bold text-white disabled:opacity-50"
                >
                  {joining === inv.match_id ? 'Joining…' : 'Join'}
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div>
        <SectionTitle>My matches</SectionTitle>
        {notice && <p className="text-sm text-amber-300" role="alert">{notice}</p>}
        {mine.length === 0 ? (
          <p className="rounded-2xl bg-panel p-3 text-sm text-slate-400">
            No matches yet. Create one from any game, or open a share link from a friend.
          </p>
        ) : (
          <ul className="space-y-2">
            {mine.map((m) => (
              <li key={m.match_id}>
                <button
                  onClick={() => onOpen(m.match_id)}
                  className="flex w-full items-center justify-between gap-2 rounded-2xl bg-panel px-3 py-2.5 text-left shadow-card active:scale-[0.99]"
                >
                  <span className="min-w-0 flex-1 truncate text-sm font-semibold text-white">
                    {gameTitle(m.game_type)} · {m.mode} · {m.status}
                    {m.my_rank ? ` · #${m.my_rank}` : ''}
                  </span>
                  <span className="shrink-0 text-xs text-slate-400">
                    {m.participants}/{m.max_players} · {formatDate(m.finished_at ?? m.created_at)}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="rounded-2xl bg-panel p-3 text-xs text-slate-400">
        <p className="font-bold text-slate-200">How matches work</p>
        <p className="mt-1">
          Create a lobby from any game, invite friends or share the link, then start when enough
          players join. Everyone plays the same game on their own phone; results rank
          automatically. Match XP is +10 to finish, +10 to win (daily cap applies).
        </p>
      </div>
    </div>
  );
}
