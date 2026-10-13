import { xpPercent } from '../gameutil';

export function XpBar({ into, needed, level }: { into: number; needed: number; level: number }) {
  const pct = xpPercent(into, needed);
  return (
    <div>
      <div className="flex items-baseline justify-between">
        <span className="text-xs font-semibold uppercase tracking-widest text-neon-cyan">Level {level}</span>
        <span className="text-xs text-slate-400">
          {into} / {needed} XP
        </span>
      </div>
      <div
        className="mt-1.5 h-2.5 overflow-hidden rounded-full bg-navy"
        role="progressbar"
        aria-valuenow={Math.round(pct)}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={`Level ${level} progress`}
      >
        <div
          className="h-full rounded-full bg-gradient-to-r from-neon-purple to-neon-cyan transition-all duration-500"
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

export function StatTile({ label, value, accent }: { label: string; value: string | number; accent?: string }) {
  return (
    <div className="rounded-2xl bg-panel p-3 text-center shadow-card">
      <div className={`text-xl font-bold ${accent ?? 'text-white'}`}>{value}</div>
      <div className="mt-0.5 text-[11px] uppercase tracking-wider text-slate-400">{label}</div>
    </div>
  );
}

export function Loading({ label }: { label?: string }) {
  return (
    <div className="flex flex-col items-center gap-3 py-10" role="status" aria-live="polite">
      <div className="h-10 w-10 animate-spin rounded-full border-2 border-navy border-t-neon-cyan" />
      <p className="text-sm text-slate-400">{label ?? 'Loading…'}</p>
    </div>
  );
}

export function ErrorNotice({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="rounded-2xl border border-red-500/30 bg-red-500/10 p-4 text-center" role="alert">
      <p className="text-sm text-red-200">{message}</p>
      {onRetry && (
        <button
          onClick={onRetry}
          className="mt-3 rounded-xl bg-panel px-4 py-2 text-sm font-semibold text-white active:scale-95"
        >
          Try again
        </button>
      )}
    </div>
  );
}

export function SectionTitle({ children }: { children: React.ReactNode }) {
  return <h2 className="mb-2 text-sm font-bold uppercase tracking-widest text-slate-400">{children}</h2>;
}
