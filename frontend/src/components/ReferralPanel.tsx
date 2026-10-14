import { useCallback, useEffect, useState } from 'react';
import { api, type ReferralLink, type ReferralStats } from '../api';
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

function shareReferral(link: string): boolean {
  const text = 'Join me on BrainRush Arcade — we both earn bonus XP!';
  const shareUrl = `https://t.me/share/url?url=${encodeURIComponent(link)}&text=${encodeURIComponent(text)}`;
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
      share?: (data: { title?: string; text?: string; url?: string }) => Promise<void>;
    };
    if (typeof nav.share === 'function') {
      void nav.share({ title: 'BrainRush', text, url: link }).catch(() => {});
      return true;
    }
  } catch {
    /* fall through */
  }
  return false;
}

export function ReferralPanel({ ctx }: { ctx: WebAppContext }) {
  const [open, setOpen] = useState(false);
  const [link, setLink] = useState<ReferralLink | null>(null);
  const [stats, setStats] = useState<ReferralStats | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [copied, setCopied] = useState(false);

  const load = useCallback(() => {
    setLoading(true);
    setError('');
    Promise.all([api.referralMine(ctx.initData), api.referralStats(ctx.initData)])
      .then(([mine, st]) => {
        setLink(mine);
        setStats(st);
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }, [ctx.initData]);

  useEffect(() => {
    if (open && !link && !loading) load();
  }, [open, link, loading, load]);

  const onCopy = async () => {
    const target = link?.link ?? link?.code ?? '';
    if (!target) return;
    setCopied(await copyText(target));
    window.setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="rounded-2xl bg-panel p-4 shadow-card">
      <button
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="w-full rounded-xl bg-gradient-to-r from-neon-purple to-neon-cyan py-3 text-base font-bold text-white shadow-glow active:scale-[0.99]"
      >
        🎁 Refer a Friend &amp; Earn XP
      </button>

      {open && (
        <div className="mt-3 space-y-3 animate-rise">
          {loading && <Loading label="Loading your referral link…" />}
          {error && <ErrorNotice message={error} onRetry={load} />}
          {link && (
            <>
              <p className="text-center text-sm text-slate-300">
                You get <b className="text-neon-cyan">+{link.referrer_xp} XP</b> per friend ·{' '}
                they get <b className="text-neon-cyan">+{link.referred_xp} XP</b>
              </p>
              <div className="rounded-xl bg-abyss p-3 text-center">
                {link.link ? (
                  <p className="break-all text-sm font-mono text-neon-cyan">{link.link}</p>
                ) : (
                  <>
                    <p className="text-sm font-mono text-neon-cyan">Code: {link.code}</p>
                    <p className="mt-1 text-xs text-slate-500">
                      Shareable link unavailable until the bot is configured.
                    </p>
                  </>
                )}
              </div>
              <div className="flex gap-2">
                <button
                  onClick={onCopy}
                  className="flex-1 rounded-xl bg-navy py-2.5 text-sm font-bold text-slate-200 active:scale-95"
                >
                  {copied ? '✓ Copied!' : 'Copy Link'}
                </button>
                <button
                  onClick={() => {
                    if (link.link && !shareReferral(link.link)) void onCopy();
                  }}
                  disabled={!link.link}
                  className="flex-1 rounded-xl bg-navy py-2.5 text-sm font-bold text-slate-200 active:scale-95 disabled:opacity-40"
                >
                  Share
                </button>
              </div>
              {stats && (
                <>
                  <SectionTitle>Your referrals</SectionTitle>
                  <p className="text-center text-sm text-slate-300">
                    {stats.referrals} friend{stats.referrals === 1 ? '' : 's'} joined ·{' '}
                    <b className="text-neon-cyan">+{stats.referral_xp} XP</b> earned
                  </p>
                </>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}
