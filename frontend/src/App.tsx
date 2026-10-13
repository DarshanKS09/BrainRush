import { useMemo, useState } from 'react';
import { initWebApp, type WebAppContext } from './telegram';
import { BottomNav, type Tab } from './components/BottomNav';
import { HomeScreen } from './screens/Home';
import { GamesScreen } from './screens/Games';
import { PlayScreen } from './screens/Play';
import { LeaderboardScreen } from './screens/Leaderboard';
import { ProfileScreen } from './screens/Profile';

type Route =
  | { name: Exclude<Tab, 'play'> }
  | { name: 'play'; sessionId: string };

export default function App() {
  const ctx: WebAppContext = useMemo(() => initWebApp(), []);
  const [route, setRoute] = useState<Route>({ name: 'home' });

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

        {route.name === 'home' && (
          <HomeScreen
            ctx={ctx}
            onPlayNow={() => setRoute({ name: 'games' })}
            onResume={(sessionId) => setRoute({ name: 'play', sessionId })}
          />
        )}
        {route.name === 'games' && (
          <GamesScreen ctx={ctx} onStart={(sessionId) => setRoute({ name: 'play', sessionId })} />
        )}
        {route.name === 'play' && (
          <PlayScreen
            ctx={ctx}
            sessionId={route.sessionId}
            onExit={() => setRoute({ name: 'games' })}
            onReplay={(sessionId) => setRoute({ name: 'play', sessionId })}
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
