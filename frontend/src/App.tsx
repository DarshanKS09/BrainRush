import { useEffect, useMemo, useState } from 'react';
import { initWebApp, type WebAppContext } from './telegram';
import { api, ApiError } from './api';
import { BottomNav, type Tab } from './components/BottomNav';
import { HomeScreen } from './screens/Home';
import { GamesScreen } from './screens/Games';
import { PlayScreen } from './screens/Play';
import { ColorPlayScreen } from './screens/ColorPlay';
import { ReflexPlayScreen } from './screens/ReflexPlay';
import { LeaderboardScreen } from './screens/Leaderboard';
import { ProfileScreen } from './screens/Profile';
import { HistoryScreen } from './screens/History';

type Route =
  | { name: Exclude<Tab, 'play'> }
  | { name: 'play'; sessionId: string; gameId: string }
  | { name: 'history' };

const PENDING_REFERRAL_KEY = 'brainrush:pendingReferral';

function readPendingReferral(): string | null {
  try {
    const v = window.localStorage?.getItem(PENDING_REFERRAL_KEY);
    return v && /^[A-Za-z0-9_-]{1,64}$/.test(v) ? v : null;
  } catch {
    return null;
  }
}

function writePendingReferral(code: string): void {
  try {
    window.localStorage?.setItem(PENDING_REFERRAL_KEY, code);
  } catch {
    /* private mode: launch param still attempted once */
  }
}

function clearPendingReferral(): void {
  try {
    window.localStorage?.removeItem(PENDING_REFERRAL_KEY);
  } catch {
    /* ignore */
  }
}

export default function App() {
  const ctx: WebAppContext = useMemo(() => initWebApp(), []);
  const [route, setRoute] = useState<Route>({ name: 'home' });
  const [referralNotice, setReferralNotice] = useState<{ kind: 'success' | 'ineligible'; text: string } | null>(null);
  // A referral code pending attribution. Screens that auto-register
  // (dashboard/history via get_verified_identity) must NOT run before the
  // claim settles: registration first would make a genuine newcomer look
  // like an existing user and forfeit both bonuses permanently.
  const [pendingCode] = useState<string | null>(() => ctx.startParam ?? readPendingReferral());
  const [claimDone, setClaimDone] = useState(pendingCode === null);
  const [claimFailed, setClaimFailed] = useState(false);
  const [claimAttempt, setClaimAttempt] = useState(0);

  useEffect(() => {
    if (!pendingCode || !ctx.initData || claimDone) return;
    if (ctx.startParam) writePendingReferral(ctx.startParam);
    let cancelled = false;
    api
      .referralClaim(ctx.initData, pendingCode)
      .then((r) => {
        if (cancelled) return;
        // Credited or already-credited: token served its purpose either way.
        clearPendingReferral();
        if (r.credited && !r.already) {
          setReferralNotice({
            kind: 'success',
            text: `🎁 Welcome bonus: +${r.referred_xp} XP! Your friend earned +${r.referrer_xp} XP.`,
          });
        }
        setClaimDone(true);
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        if (e instanceof ApiError && (e.status === 409 || e.status === 404)) {
          // Ineligible (existing user, self-referral, repeat) or unknown
          // code: nothing to retry, no private details exposed.
          clearPendingReferral();
          setReferralNotice({
            kind: 'ineligible',
            text:
              e.status === 404
                ? 'This invite link is invalid — no bonus awarded.'
                : 'This invite is not eligible for a bonus (already used or existing account).',
          });
          setClaimDone(true);
        } else {
          // Network/server error: keep the token and stay gated so a
          // retry can still attribute this genuinely new user.
          setClaimFailed(true);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [ctx, pendingCode, claimDone, claimAttempt]);

  if (!ctx.initData && !ctx.isDevMock) {
    return (
      <div className="app-bg min-h-screen text-white">
        <div className="mx-auto max-w-md px-4 pb-24 pt-10">
          <div className="rounded-3xl bg-panel p-6 text-center shadow-card">
            <div className="text-4xl" aria-hidden>
              🎮
            </div>
            <h1 className="mt-2 text-xl font-bold">BrainRush Arcade</h1>
            <p className="mt-2 text-sm text-slate-300">
              Open this app from Telegram using the <b>Open BrainRush</b> button to play with
              your account.
            </p>
          </div>
        </div>
      </div>
    );
  }

  const tab: Tab = route.name === 'play' ? 'games' : route.name === 'history' ? 'profile' : route.name;

  // While a referral claim is unsettled, show a splash instead of the app:
  // any screen would auto-register via /api/me and void a newcomer's bonus.
  if (pendingCode && !claimDone) {
    return (
      <div className="app-bg min-h-screen text-white">
        <div className="mx-auto max-w-md px-4 pb-24 pt-10">
          <div className="rounded-3xl bg-panel p-6 text-center shadow-card">
            <div className="text-4xl" aria-hidden>
              🎁
            </div>
            <h1 className="mt-2 text-xl font-bold">BrainRush Arcade</h1>
            {claimFailed ? (
              <>
                <p className="mt-2 text-sm text-slate-300" role="alert">
                  Couldn't verify your invite just now. Your bonus is safe — retry to apply it.
                </p>
                <div className="mt-4 flex gap-2">
                  <button
                    onClick={() => {
                      setClaimFailed(false);
                      setClaimAttempt((n) => n + 1);
                    }}
                    className="flex-1 rounded-xl bg-gradient-to-r from-neon-purple to-neon-cyan py-2.5 text-sm font-bold text-white shadow-glow active:scale-95"
                  >
                    Retry
                  </button>
                  <button
                    onClick={() => {
                      clearPendingReferral();
                      setClaimDone(true);
                    }}
                    className="flex-1 rounded-xl bg-navy py-2.5 text-sm font-bold text-slate-300 active:scale-95"
                  >
                    Continue without bonus
                  </button>
                </div>
              </>
            ) : (
              <p className="mt-2 text-sm text-slate-300">Applying your invite…</p>
            )}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="app-bg min-h-screen text-white">
      <div className="mx-auto max-w-md px-4 pb-28 pt-4">
        <div className="mb-3 flex items-center gap-2">
          <span className="text-xl" aria-hidden>
            🧠
          </span>
          <span className="bg-gradient-to-r from-neon-purple to-neon-cyan bg-clip-text text-lg font-bold text-transparent">
            BrainRush
          </span>
          {ctx.isDevMock && (
            <span className="rounded-full bg-amber-500/20 px-2 py-0.5 text-[10px] font-bold text-amber-300">
              DEV MOCK
            </span>
          )}
        </div>

        {referralNotice && (
          <div
            className={`mb-3 rounded-2xl border p-3 text-center ${
              referralNotice.kind === 'success'
                ? 'border-neon-cyan/30 bg-cyan-500/10'
                : 'border-amber-400/30 bg-amber-500/10'
            }`}
            role="status"
          >
            <p className="text-sm font-semibold text-white">{referralNotice.text}</p>
            <button
              onClick={() => setReferralNotice(null)}
              className="mt-1 text-xs font-bold text-slate-400 active:text-slate-200"
            >
              Dismiss
            </button>
          </div>
        )}

        {route.name === 'home' && (
          <HomeScreen
            ctx={ctx}
            onPlayNow={() => setRoute({ name: 'games' })}
            onResume={(gameId, sessionId) => setRoute({ name: 'play', gameId, sessionId })}
          />
        )}
        {route.name === 'games' && (
          <GamesScreen ctx={ctx} onStart={(gameId, sessionId) => setRoute({ name: 'play', gameId, sessionId })} />
        )}
        {route.name === 'play' && route.gameId === 'color_sequence' && (
          <ColorPlayScreen
            ctx={ctx}
            sessionId={route.sessionId}
            onExit={() => setRoute({ name: 'games' })}
            onReplay={(sessionId) => setRoute({ name: 'play', gameId: 'color_sequence', sessionId })}
          />
        )}
        {route.name === 'play' && route.gameId === 'reflex_rush' && (
          <ReflexPlayScreen
            key={route.sessionId}
            ctx={ctx}
            sessionId={route.sessionId}
            onExit={() => setRoute({ name: 'games' })}
            onReplay={(sessionId) => setRoute({ name: 'play', gameId: 'reflex_rush', sessionId })}
          />
        )}
        {route.name === 'play' && route.gameId !== 'color_sequence' && route.gameId !== 'reflex_rush' && (
          <PlayScreen
            ctx={ctx}
            sessionId={route.sessionId}
            onExit={() => setRoute({ name: 'games' })}
            onReplay={(sessionId) => setRoute({ name: 'play', gameId: 'number_guessing', sessionId })}
          />
        )}
        {route.name === 'leaderboard' && <LeaderboardScreen ctx={ctx} />}
        {route.name === 'profile' && (
          <ProfileScreen ctx={ctx} onViewHistory={() => setRoute({ name: 'history' })} />
        )}
        {route.name === 'history' && (
          <HistoryScreen ctx={ctx} onBack={() => setRoute({ name: 'profile' })} />
        )}
      </div>
      {route.name !== 'play' && (
        <BottomNav tab={tab} onChange={(t) => setRoute({ name: t })} />
      )}
    </div>
  );
}
