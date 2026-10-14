import type { GameInfo } from '../api';
import { difficultyDisplayName, difficultySub } from '../gameutil';

const ART: Record<string, { icon: string; gradient: string }> = {
  number_guessing: { icon: '🔢', gradient: 'from-violet-600 to-cyan-500' },
  color_sequence: { icon: '🎨', gradient: 'from-pink-500 to-amber-400' },
  reflex_rush: { icon: '👆', gradient: 'from-amber-500 to-rose-500' },
  memory_match: { icon: '🃏', gradient: 'from-fuchsia-600 to-purple-500' },
  reaction_test: { icon: '⚡', gradient: 'from-amber-500 to-rose-500' },
  math_challenge: { icon: '➗', gradient: 'from-emerald-500 to-cyan-500' },
  word_puzzle: { icon: '🔤', gradient: 'from-sky-500 to-indigo-500' },
};

export function GameCard({
  game,
  onPlay,
}: {
  game: GameInfo;
  onPlay: (game: GameInfo) => void;
}) {
  const art = ART[game.id] ?? { icon: '🎲', gradient: 'from-slate-600 to-slate-500' };
  return (
    <div className="overflow-hidden rounded-2xl bg-panel shadow-card animate-rise">
      <div className={`flex items-center gap-3 bg-gradient-to-r ${art.gradient} p-4`}>
        <span className="text-3xl" aria-hidden>
          {art.icon}
        </span>
        <div>
          <h3 className="font-bold text-white">{game.title}</h3>
          {game.playable ? (
            <span className="rounded-full bg-black/30 px-2 py-0.5 text-[11px] font-semibold text-white">
              Playable now
            </span>
          ) : (
            <span className="rounded-full bg-black/30 px-2 py-0.5 text-[11px] font-semibold text-white/80">
              Coming soon
            </span>
          )}
        </div>
      </div>
      <div className="p-4">
        <p className="text-sm text-slate-300">{game.description}</p>
        {game.playable && game.difficulties.length > 0 && (
          <div className="mt-2 flex flex-wrap gap-1.5">
            {game.difficulties.map((d) => (
              <span key={d.id} className="rounded-lg bg-navy px-2 py-1 text-[11px] text-slate-300">
                {difficultyDisplayName(game.id, d.id)} · {difficultySub(game.id, d)}
              </span>
            ))}
          </div>
        )}
        <button
          onClick={() => onPlay(game)}
          disabled={!game.playable}
          aria-disabled={!game.playable}
          className={`mt-3 w-full rounded-xl py-2.5 text-sm font-bold transition-transform ${
            game.playable
              ? 'bg-gradient-to-r from-neon-purple to-neon-cyan text-white shadow-glow active:scale-[0.98]'
              : 'cursor-not-allowed bg-navy text-slate-500'
          }`}
        >
          {game.playable ? 'Play' : 'Coming soon'}
        </button>
      </div>
    </div>
  );
}
