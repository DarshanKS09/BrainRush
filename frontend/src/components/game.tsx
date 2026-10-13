const KEYS = ['1', '2', '3', '4', '5', '6', '7', '8', '9', 'clear', '0', 'back'];

export function Keypad({
  onKey,
  disabled,
}: {
  onKey: (key: string) => void;
  disabled?: boolean;
}) {
  return (
    <div className="grid grid-cols-3 gap-2" role="group" aria-label="Number keypad">
      {KEYS.map((key) => (
        <button
          key={key}
          onClick={() => onKey(key)}
          disabled={disabled}
          aria-label={key === 'back' ? 'Backspace' : key === 'clear' ? 'Clear' : `Digit ${key}`}
          className="key-btn rounded-2xl bg-panel py-3.5 text-xl font-bold text-white shadow-card disabled:opacity-40"
        >
          {key === 'back' ? '⌫' : key === 'clear' ? 'C' : key}
        </button>
      ))}
    </div>
  );
}

export function AttemptPips({ used, max }: { used: number; max: number }) {
  return (
    <div className="flex justify-center gap-1.5" aria-label={`${max - used} attempts left`}>
      {Array.from({ length: max }).map((_, i) => (
        <span
          key={i}
          className={`pip h-2.5 w-2.5 rounded-full ${
            i < max - used ? 'bg-neon-cyan shadow-[0_0_8px_rgba(34,211,238,0.8)]' : 'bg-navy'
          }`}
        />
      ))}
    </div>
  );
}

export function GuessHistory({ guesses }: { guesses: { value: number; hint: string }[] }) {
  if (guesses.length === 0) {
    return <p className="py-3 text-center text-sm text-slate-500">No guesses yet — make your move!</p>;
  }
  return (
    <ul className="nice-scroll max-h-36 space-y-1.5 overflow-y-auto pr-1">
      {[...guesses].reverse().map((g, i) => (
        <li
          key={`${g.value}-${i}`}
          className={`history-row flex items-center justify-between rounded-xl px-3 py-1.5 text-sm font-semibold ${
            g.hint === 'high' ? 'bg-rose-500/15 text-rose-200' : 'bg-cyan-500/15 text-cyan-200'
          }`}
        >
          <span>#{guesses.length - i}</span>
          <span className="text-base">{g.value}</span>
          <span>{g.hint === 'high' ? '▼ Too high' : '▲ Too low'}</span>
        </li>
      ))}
    </ul>
  );
}
