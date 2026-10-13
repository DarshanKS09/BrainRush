export type Tab = 'home' | 'games' | 'leaderboard' | 'profile';

const TABS: { id: Tab; label: string; icon: string }[] = [
  { id: 'home', label: 'Home', icon: '🏠' },
  { id: 'games', label: 'Games', icon: '🎮' },
  { id: 'leaderboard', label: 'Ranks', icon: '🏆' },
  { id: 'profile', label: 'Profile', icon: '👤' },
];

export function BottomNav({ tab, onChange }: { tab: Tab; onChange: (t: Tab) => void }) {
  return (
    <nav
      aria-label="Primary"
      className="fixed inset-x-0 bottom-0 z-10 border-t border-white/10 bg-abyss/95 pb-[env(safe-area-inset-bottom)] backdrop-blur"
    >
      <div className="mx-auto grid max-w-md grid-cols-4">
        {TABS.map((t) => (
          <button
            key={t.id}
            onClick={() => onChange(t.id)}
            aria-current={tab === t.id ? 'page' : undefined}
            className={`flex flex-col items-center gap-0.5 py-2.5 text-[11px] font-semibold transition-colors ${
              tab === t.id ? 'text-neon-cyan' : 'text-slate-500 active:text-slate-300'
            }`}
          >
            <span className="text-lg" aria-hidden>
              {t.icon}
            </span>
            {t.label}
          </button>
        ))}
      </div>
    </nav>
  );
}
