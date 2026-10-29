import { useCallback, useEffect, useRef, useState } from 'react';
import {
  api,
  ApiError,
  type FriendEntry,
  type MatchResultView,
  type MatchView,
} from '../api';
import { formatDate, formatSeconds, gameTitle } from '../gameutil';
import type { WebAppContext } from '../telegram';
import { ErrorNotice, Loading, SectionTitle } from '../components/ui';
import { haptic } from '../telegram';

type View = MatchView | MatchResultView;

function scoreText(gameType: string, score: number | null): string {
  if (score === null || score === undefined) return '—';
  if (gameType === 'color_sequence') return `Lv ${score}`;
  if (gameType === 'reflex_rush') return `${score} pts`;
  if (gameType === 'perfect_second') return `${(score / 1000).toFixed(2)}s err`;
  return `${score} tries`;
}

async function copyText(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch { /* fallback */ }
  try {
    const area = document.createElement('textarea');
    area.value = text;
    area.style.position = 'fixed';
    area.style.opacity = '0';
    document.body.appendChild(area);
    area.select();
    const ok = document.execCommand('copy');
    document.body.removeChild(area);
    return ok;
  } catch {
    return false;
  }
}

function openShare(link: string, text: string): void {
  const url = `https://t.me/share/url?url=${encodeURIComponent(link)}&text=${encodeURIComponent(text)}`;
  try {
    const fn = window.Telegram?.WebApp?.openTelegramLink;
    if (typeof fn === 'function') {
      fn(url);
      return;
    }
  } catch { /* fallback */ }
  try {
    window.open(url, '_blank', 'noopener');
  } catch { /* clipboard remains */ }
}

export function MatchDetailScreen({
  ctx,
  matchId,
  onExit,
  onPlay,
}: {
  ctx: WebAppContext;
  matchId: string;
  onExit: () => void;
  onPlay: (gameId: string, difficulty: string, matchId: string) => void;
}) {
  const [view, setView] = useState<View | null>(null);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState<string | null>(null);
  const [link, setLink] = useState<string | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [friends, setFriends] = useState<FriendEntry[] | null>(null);
  const [showInvite, setShowInvite] = useState(false);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  const load = useCallback(async () => {
    try {
      const v = await api.matchGet(ctx.initData, matchId);
      setView(v);
      setError('');
    } catch (e) {
      if (e instanceof ApiError && (e.status === 404 || e.status === 403)) {
        setError('Match not found. It may have expired or you are not a participant.');
      } else {
        setError(e instanceof Error ? e.message : 'Could not load the match.');
      }
    }
  }, [ctx.initData, matchId]);

  useEffect(() => {
    void load();
    // Poll only while the match is live; completed matches are stable and
    // only change on explicit user actions (rematch, etc.).
    if (timer.current) clearInterval(timer.current);
    timer.current = setInterval(() => {
      if (view?.status === 'completed') return;
      void load();
    }, 3000);
    return () => {
      if (timer.current) clearInterval(timer.current);
    };
  }, [load, view]);

  // Reconnect affordance: refresh on tab visibility regain (backgrounding).
  useEffect(() => {
    const onVis = () => {
      if (document.visibilityState === 'visible') void load();
    };
    document.addEventListener('visibilitychange', onVis);
    window.addEventListener('focus', onVis);
    return () => {
      document.removeEventListener('visibilitychange', onVis);
      window.removeEventListener('focus', onVis);
    };
  }, [load]);

  const act = async (name: string, fn: () => Promise<unknown>) => {
    setBusy(name);
    setNotice('');
    try {
      await fn();
      haptic('success');
      await load();
    } catch (e) {
      setNotice(e instanceof Error ? e.message : 'Action failed.');
    } finally {
      setBusy(null);
    }
  };

  const loadLink = async () => {
    setBusy('link');
    try {
      const r = await api.matchLink(ctx.initData, matchId);
      setToken(r.token);
      setLink(r.link);
      if (!r.link) setNotice('Bot username is not configured yet — share the token code instead: ' + r.token);
    } catch (e) {
      setNotice(e instanceof Error ? e.message : 'Could not load the link.');
    } finally {
      setBusy(null);
    }
  };

  const loadFriends = async () => {
    try {
      const r = await api.friendsList(ctx.initData);
      // FriendEntry has no user_id; invite needs ids. Fetch is best-effort:
      // entries without ids cannot be invited from here (use share link).
      setFriends(r.friends);
    } catch {
      setFriends([]);
    }
  };

  if (error && !view) return <ErrorNotice message={error} onRetry={() => void load()} />;
  if (!view) return <Loading label="Loading match…" />;

  const me = view.participants.find((p) => p.is_me);
  const amHost = !!me?.is_host;
  const finished = view.status === 'completed';
  const live: MatchView | null = finished ? null : (view as MatchView);
  const result: MatchResultView | null = finished ? (view as MatchResultView) : null;
  const deadline = live?.deadline ?? null;
  const secsLeft = deadline ? Math.max(0, Math.floor((new Date(deadline).getTime() - Date.now()) / 1000)) : null;

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <button onClick={onExit} className="rounded-xl bg-panel px-3 py-1.5 text-sm font-semibold text-slate-300" aria-label="Back to matches">
          ← Matches
        </button>
        <span className="rounded-full bg-panel px-3 py-1 text-xs font-bold uppercase tracking-wider text-neon-cyan">
          {view.status}
        </span>
      </div>

      <div className="rounded-3xl bg-panel p-4 shadow-card">
        <h2 className="text-lg font-bold text-white">
          {gameTitle(view.game_type)} · {view.mode}
        </h2>
        <p className="text-xs text-slate-400">
          {view.difficulty} · {view.count} player{view.count === 1 ? '' : 's'}
          {'target_ms' in view && view.target_ms != null ? ` · 🎯 ${formatSeconds(view.target_ms, view.difficulty)}` : ''}
          {finished ? ` · finished ${formatDate(view.finished_at)}` : secsLeft !== null ? ` · ends in ${Math.floor(secsLeft / 60)}m ${secsLeft % 60}s` : ''}
        </p>
        {notice && <p className="mt-2 text-sm text-amber-300" role="alert">{notice}</p>}

        <ul className="mt-3 space-y-1.5">
          {view.participants.map((p) => (
            <li key={p.user_id} className={`flex items-center justify-between gap-2 rounded-xl px-3 py-2 text-sm ${p.rank === 1 && finished ? 'bg-gradient-to-r from-amber-500/25 to-yellow-400/10 ring-1 ring-amber-400/40' : 'bg-navy/60'}`}>
              <span className="min-w-0 flex-1 truncate font-semibold text-white">
                {finished && p.rank ? `#${p.rank} ` : ''}{p.display_name}
                {p.is_me ? ' (you)' : ''}{p.is_host ? ' 👑' : ''}
                {!p.online && !finished ? ' · offline' : ''}
              </span>
              <span className="shrink-0 text-xs text-slate-300">
                {p.finished ? `${scoreText(view.game_type, p.score)} · +${p.xp_earned} XP` : p.is_me ? 'you: not submitted' : 'playing…'}
              </span>
            </li>
          ))}
        </ul>
      </div>

      {live && live.status === 'lobby' && (
        <div className="rounded-3xl bg-panel p-4 shadow-card">
          <SectionTitle>Lobby {`(${live.count}/${live.max_players})`}</SectionTitle>
          <p className="text-xs text-slate-400">
            Waiting for players… need at least {live.min_players} to start.
          </p>
          {live.room_code && (
            <div className="mt-2 flex items-center justify-between gap-2 rounded-xl bg-navy px-3 py-2">
              <span className="text-xs text-slate-400">
                Room code{' '}
                <b className="font-mono text-base font-bold tracking-[0.25em] text-white">
                  {live.room_code}
                </b>
              </span>
              <button
                onClick={() => void (async () => { setCopied(await copyText(live.room_code)); setTimeout(() => setCopied(false), 2000); })()}
                className="rounded-lg bg-panel px-3 py-1.5 text-xs font-bold text-white active:scale-95"
              >
                {copied ? 'Copied ✓' : 'Copy Code'}
              </button>
            </div>
          )}
          <div className="mt-2 flex flex-wrap gap-2">
            {amHost && (
              <button
                onClick={() => void act('start', () => api.matchStart(ctx.initData, matchId))}
                disabled={busy !== null}
                className="flex-1 rounded-xl bg-gradient-to-r from-neon-purple to-neon-cyan py-2 text-sm font-bold text-white disabled:opacity-50"
              >
                {busy === 'start' ? 'Starting…' : '▶ Start match'}
              </button>
            )}
            <button onClick={() => void loadLink()} disabled={busy === 'link'} className="flex-1 rounded-xl bg-navy py-2 text-sm font-bold text-slate-200 disabled:opacity-50">
              {busy === 'link' ? 'Loading…' : '🔗 Invite link'}
            </button>
            <button
              onClick={() => { setShowInvite((s) => !s); if (!friends) void loadFriends(); }}
              className="flex-1 rounded-xl bg-navy py-2 text-sm font-bold text-slate-200"
            >
              👥 Invite friends
            </button>
          </div>
          {(link || token) && (
            <div className="mt-2 rounded-xl bg-navy p-2 text-xs">
              {link ? <p className="break-all text-neon-cyan">{link}</p> : <p className="break-all text-slate-200">Token: {token}</p>}
              <div className="mt-1 flex gap-2">
                <button
                  onClick={() => void (async () => { setCopied(await copyText(link ?? token ?? '')); setTimeout(() => setCopied(false), 2000); })()}
                  className="flex-1 rounded-lg bg-panel py-1.5 font-bold text-white"
                >
                  {copied ? 'Copied ✓' : 'Copy'}
                </button>
                {link && (
                  <button
                    onClick={() => openShare(link, `Join my BrainRush ${gameTitle(live.game_type)} match!`)}
                    className="flex-1 rounded-lg bg-panel py-1.5 font-bold text-white"
                  >
                    Share via Telegram
                  </button>
                )}
              </div>
            </div>
          )}
          {showInvite && (
            <div className="mt-2 rounded-xl bg-navy p-2 text-xs text-slate-300">
              <p className="mb-1 font-bold text-white">Friends (tap to invite — friends only)</p>
              {friends === null ? (
                <p>Loading…</p>
              ) : friends.length === 0 ? (
                <p>Add friends first (Profile → Friends), or use the share link above.</p>
              ) : (
                <FriendInviteList friends={friends} />
              )}
            </div>
          )}
          <div className="mt-2 flex gap-2">
            {amHost ? (
              <button onClick={() => void act('cancel', () => api.matchCancel(ctx.initData, matchId).then(() => onExit()))} disabled={busy !== null} className="flex-1 rounded-xl bg-navy py-2 text-sm font-bold text-rose-300 disabled:opacity-50">
                Cancel lobby
              </button>
            ) : (
              <button onClick={() => void act('leave', () => api.matchLeave(ctx.initData, matchId).then(() => onExit()))} disabled={busy !== null} className="flex-1 rounded-xl bg-navy py-2 text-sm font-bold text-rose-300 disabled:opacity-50">
                Leave lobby
              </button>
            )}
          </div>
        </div>
      )}

      {live && live.status === 'active' && (
        <div className="rounded-3xl bg-panel p-4 shadow-card">
          <SectionTitle>Your turn</SectionTitle>
          {me?.finished ? (
            <p className="text-sm text-slate-300">✅ Result submitted. Waiting for opponents…</p>
          ) : (
            <button
              onClick={() => onPlay(live.game_type, live.difficulty, matchId)}
              className="w-full rounded-xl bg-gradient-to-r from-neon-purple to-neon-cyan py-2.5 text-sm font-bold text-white"
            >
              🎮 Play my round ({live.difficulty})
            </button>
          )}
          <div className="mt-2 flex gap-2">
            <button onClick={() => void load()} className="flex-1 rounded-xl bg-navy py-2 text-sm font-bold text-slate-200">
              ↻ Refresh
            </button>
            <button onClick={() => void act('finalize', () => api.matchFinalize(ctx.initData, matchId))} disabled={busy !== null} className="flex-1 rounded-xl bg-navy py-2 text-sm font-bold text-slate-200 disabled:opacity-50">
              {busy === 'finalize' ? 'Settling…' : 'Settle results'}
            </button>
          </div>
          <p className="mt-1 text-[11px] text-slate-500">
            Settle applies once everyone finishes or the deadline passes. Unfinished players rank last with 0 XP.
          </p>
        </div>
      )}

      {result && (
        <div className="rounded-3xl bg-panel p-4 shadow-card">
          <SectionTitle>Final results</SectionTitle>
          <div className="flex gap-2">
            <button
              onClick={() => void act('rematch', () => api.matchRematch(ctx.initData, matchId).then(() => onExit()))}
              disabled={busy !== null}
              className="flex-1 rounded-xl bg-gradient-to-r from-neon-purple to-neon-cyan py-2 text-sm font-bold text-white disabled:opacity-50"
            >
              {busy === 'rematch' ? 'Creating…' : '↻ Rematch'}
            </button>
            <button
              onClick={() => void (async () => {
                const text = `🏆 BrainRush ${gameTitle(result.game_type)} (${result.mode}): ` +
                  result.participants.map((p) => `${p.rank ? `#${p.rank} ` : ''}${p.display_name} ${scoreText(result.game_type, p.score)}`).join(' · ');
                setCopied(await copyText(text));
                setTimeout(() => setCopied(false), 2000);
              })()}
              className="flex-1 rounded-xl bg-navy py-2 text-sm font-bold text-slate-200"
            >
              {copied ? 'Copied ✓' : 'Share results'}
            </button>
            <button onClick={onExit} className="flex-1 rounded-xl bg-navy py-2 text-sm font-bold text-slate-200">
              Games
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function FriendInviteList({ friends }: {
  friends: FriendEntry[];
}) {
  // NOTE: FriendEntry currently carries no user_id, so per-friend invite
  // buttons cannot be addressed. Keep the list informational and direct
  // hosts to the share link. This avoids inventing an id mapping.
  return (
    <ul className="space-y-1">
      {friends.map((f, i) => (
        <li key={i} className="rounded-lg bg-panel px-2 py-1.5">
          {(f.display_name || (f.username ? `@${f.username}` : 'Player'))} · Lv {f.level}
        </li>
      ))}
      <li className="px-1 pt-1 text-[11px] text-slate-500">
        Per-friend in-app invites need friend user IDs from the API; use the share link above for now.
      </li>
    </ul>
  );
}
