import { useCallback, useEffect, useState } from 'react';
import { api, ApiError, type FriendEntry } from '../api';
import type { WebAppContext } from '../telegram';
import { ErrorNotice, Loading, SectionTitle } from './ui';

async function copyText(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    /* fall through to legacy path */
  }
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

function shareCode(code: string): boolean {
  const text = `Add me on BrainRush Arcade! My friend code is ${code}`;
  const shareUrl = `https://t.me/share/url?url=${encodeURIComponent(text)}&text=${encodeURIComponent(text)}`;
  try {
    const openTelegramLink = window.Telegram?.WebApp?.openTelegramLink;
    if (typeof openTelegramLink === 'function') {
      openTelegramLink(shareUrl);
      return true;
    }
  } catch {
    /* fall through */
  }
  try {
    const nav = navigator as Navigator & {
      share?: (data: { title?: string; text?: string }) => Promise<void>;
    };
    if (typeof nav.share === 'function') {
      void nav.share({ title: 'BrainRush', text }).catch(() => {});
      return true;
    }
  } catch {
    /* fall through */
  }
  return false;
}

function friendName(f: FriendEntry): string {
  return f.display_name || (f.username ? `@${f.username}` : 'Player');
}

export function FriendPanel({ ctx }: { ctx: WebAppContext }) {
  const [open, setOpen] = useState(false);
  const [code, setCode] = useState<string | null>(null);
  const [friends, setFriends] = useState<FriendEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [copied, setCopied] = useState(false);
  const [input, setInput] = useState('');
  const [formError, setFormError] = useState('');
  const [formOk, setFormOk] = useState('');
  const [adding, setAdding] = useState(false);

  const load = useCallback(() => {
    setLoading(true);
    setError('');
    Promise.all([api.friendMine(ctx.initData), api.friendsList(ctx.initData)])
      .then(([mine, list]) => {
        setCode(mine.code);
        setFriends(list.friends);
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }, [ctx.initData]);

  useEffect(() => {
    if (open && code === null && !loading) load();
  }, [open, code, loading, load]);

  const onCopy = async () => {
    if (!code) return;
    setCopied(await copyText(code));
    window.setTimeout(() => setCopied(false), 2000);
  };

  const onAdd = async () => {
    const value = input.trim();
    if (!value) {
      setFormError('Please enter a friend code.');
      setFormOk('');
      return;
    }
    setAdding(true);
    setFormError('');
    setFormOk('');
    try {
      const r = await api.friendAdd(ctx.initData, value);
      // Refresh the list in place: no reload needed.
      const list = await api.friendsList(ctx.initData);
      setFriends(list.friends);
      setInput('');
      setFormOk(r.added ? 'Friend added successfully!' : 'You are already friends.');
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) {
        setFormError('Friend code not found. Please check the code.');
      } else if (e instanceof ApiError && e.status === 409) {
        setFormError(e.message || 'You cannot add yourself as a friend.');
      } else {
        setFormError(e instanceof Error ? e.message : 'Could not add friend. Try again.');
      }
    } finally {
      setAdding(false);
    }
  };

  return (
    <div className="rounded-2xl bg-panel p-4 shadow-card">
      <button
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="w-full rounded-xl bg-gradient-to-r from-neon-purple to-neon-cyan py-3 text-base font-bold text-white shadow-glow active:scale-[0.99]"
      >
        👥 Add Friend
      </button>

      {open && (
        <div className="mt-3 space-y-4 animate-rise">
          {loading && <Loading label="Loading friends…" />}
          {error && <ErrorNotice message={error} onRetry={load} />}

          {code !== null && (
            <div>
              <SectionTitle>My Friend Code</SectionTitle>
              <p className="mt-1 text-xs text-slate-400">
                Share this code with a friend so they can add you on BrainRush.
              </p>
              <div className="mt-2 rounded-xl bg-abyss p-3 text-center">
                <p className="text-lg font-mono font-bold tracking-widest text-neon-cyan">{code}</p>
              </div>
              <div className="mt-2 flex gap-2">
                <button
                  onClick={onCopy}
                  className="flex-1 rounded-xl bg-navy py-2.5 text-sm font-bold text-slate-200 active:scale-95"
                >
                  {copied ? '✓ Copied!' : 'Copy'}
                </button>
                <button
                  onClick={() => {
                    if (!shareCode(code)) void onCopy();
                  }}
                  className="flex-1 rounded-xl bg-navy py-2.5 text-sm font-bold text-slate-200 active:scale-95"
                >
                  Share
                </button>
              </div>
            </div>
          )}

          {code !== null && !error && (
            <div>
              <SectionTitle>Add a Friend</SectionTitle>
              <div className="mt-2 flex gap-2">
                <input
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  placeholder="Enter friend code"
                  aria-label="Friend code"
                  maxLength={32}
                  className="min-w-0 flex-1 rounded-xl bg-abyss px-3 py-2.5 font-mono text-sm text-white placeholder:text-slate-500"
                />
                <button
                  onClick={onAdd}
                  disabled={adding}
                  className="shrink-0 rounded-xl bg-gradient-to-r from-neon-purple to-neon-cyan px-4 py-2.5 text-sm font-bold text-white shadow-glow active:scale-95 disabled:opacity-50"
                >
                  {adding ? 'Adding…' : 'Add Friend'}
                </button>
              </div>
              {formError && (
                <p className="mt-2 text-center text-sm text-red-300" role="alert">
                  {formError}
                </p>
              )}
              {formOk && (
                <p className="mt-2 text-center text-sm font-bold text-emerald-300" role="status">
                  {formOk}
                </p>
              )}
            </div>
          )}

          {code !== null && !error && (
            <div>
              <SectionTitle>My Friends ({friends.length})</SectionTitle>
              {friends.length === 0 ? (
                <p className="mt-1 rounded-xl bg-abyss p-3 text-center text-sm text-slate-500">
                  No friends yet — share your code above to get started.
                </p>
              ) : (
                <ul className="mt-2 space-y-2">
                  {friends.map((f, i) => (
                    <li
                      key={`${f.display_name}-${f.username}-${i}`}
                      className="flex items-center gap-3 rounded-xl bg-abyss px-3 py-2"
                    >
                      <span
                        className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-neon-purple to-neon-cyan text-base font-bold text-white"
                        aria-hidden
                      >
                        {friendName(f).charAt(0).toUpperCase()}
                      </span>
                      <span className="min-w-0 flex-1 truncate text-sm font-semibold text-white">
                        {friendName(f)}
                      </span>
                      <span className="shrink-0 text-xs text-slate-400">Lv {f.level}</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
