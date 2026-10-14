import { useEffect, useMemo, useRef, useState } from 'react';
import { initWebApp, type WebAppContext } from './telegram';
import { api } from './api';
import { BottomNav, type Tab } from './components/BottomNav';
import { HomeScreen } from './screens/Home';
import { GamesScreen } from './screens/Games';
import { PlayScreen } from './screens/Play';
import { ColorPlayScreen } from './screens/ColorPlay';
import { ReflexPlayScreen } from './screens/ReflexPlay';
import { LeaderboardScreen } from './screens/Leaderboard';
import { ProfileScreen } from './screens/Profile';

type Route =
  | { name: Exclude<Tab, 'play'> }
  | { name: 'play'; sessionId: string; gameId: string };

export default function App() {
  const ctx: WebAppContext = useMemo(() => initWebApp(), []);
  const [route, setRoute] = useState<Route>({ name: 'home' });
  const [referralNotice, setReferralNotice] = useState<string | null>(null);
  const claimTried = useRef(false);

  // First-launch referral attribution: runs once per app load when Telegram
  // provided a start_param. Safe to repeat across reloads — the backend
  // credits a newcomer at most once and replays are idempotent.
  useEffect(() => {
    if (!ctx.initData || !ctx.startParam || claimTried.current) return;
    claimTried.current = true;
    api
      .referralClaim(ctx.initData, ctx.startParam)
      .then((r) => {
        if (r.credited && !r.already) {
          setReferralNotice(
            `🎁 Welcome bonus: +${r.referred_xp} XP! Your friend earned +${r.referrer_xp} XP.`,
          );
        }
      })
      .catch(() => {
        /* ineligible/expired: stay silent, normal app flow continues */
      });
  }, [ctx]);

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

  const tab: Tab = route.name === 'play' ? 'games' : route.name;

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
          <div className="mb-3 rounded-2xl border border-neon-cyan/30 bg-cyan-500/10 p-3 text-center" role="status">
            <p className="text-sm font-semibold text-white">{referralNotice}</p>
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
        {route.name === 'profile' && <ProfileScreen ctx={ctx} />}
      </div>
      {route.name !== 'play' && (
        <BottomNav tab={tab} onChange={(t) => setRoute({ name: t })} />
      )}
    </div>
  );
}
