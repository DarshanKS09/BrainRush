import { SectionTitle } from '../components/ui';
import { useAudioSettings } from './useAudio';

/** Sound settings card. Lives in the existing Profile settings area. */
export function AudioSettingsCard() {
  const { muted, volume, setMuted, setVolume, preview } = useAudioSettings();

  return (
    <div className="rounded-2xl bg-panel p-4 shadow-card">
      <SectionTitle>Sound</SectionTitle>

      <div className="flex items-center justify-between gap-3">
        <div>
          <p className="text-sm font-semibold text-white">Sound effects</p>
          <p className="text-xs text-slate-400">Taps, correct/wrong answers, wins and losses</p>
        </div>
        <button
          type="button"
          role="switch"
          aria-checked={!muted}
          aria-label="Sound effects"
          onClick={() => {
            const next = !muted;
            setMuted(next);
            if (!next) preview();
          }}
          className={`relative h-7 w-12 shrink-0 rounded-full transition-colors active:scale-95 ${
            muted ? 'bg-navy' : 'bg-gradient-to-r from-neon-purple to-neon-cyan'
          }`}
        >
          <span
            className={`absolute top-1 h-5 w-5 rounded-full bg-white transition-all ${
              muted ? 'left-1' : 'left-6'
            }`}
          />
        </button>
      </div>

      <label className="mt-3 block">
        <span className="flex items-center justify-between text-xs font-semibold text-slate-300">
          <span>Volume</span>
          <span className="tabular-nums text-slate-400">{Math.round(volume * 100)}%</span>
        </span>
        <input
          type="range"
          min={0}
          max={100}
          step={5}
          value={Math.round(volume * 100)}
          disabled={muted}
          aria-label="Sound volume"
          onChange={(e) => setVolume(Number(e.target.value) / 100)}
          onPointerUp={() => {
            if (!muted && volume > 0) preview();
          }}
          onKeyUp={() => {
            if (!muted && volume > 0) preview();
          }}
          className="mt-1 w-full accent-neon-cyan disabled:opacity-40"
        />
      </label>

      {muted && <p className="mt-2 text-xs text-slate-500">Sound is off. Turn it back on to hear effects.</p>}
    </div>
  );
}
