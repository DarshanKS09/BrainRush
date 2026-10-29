/** Compact game tile for the 3-column game library grid.
 *
 * Each tile shows only a distinctive SVG icon and the game name. Tapping a
 * playable tile opens the game details panel (handled by the parent). Icons
 * are lightweight inline SVGs with a consistent 24x24 viewBox, 2.5px strokes,
 * and round caps/joins so they look like a deliberate set.
 */
import type { GameInfo } from '../api';

type IconProps = { className?: string };

function NumberGuessingIcon({ className }: IconProps) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="3" width="18" height="18" rx="2"/>
      <path d="M8 8h2v2M8 10l2 2M14 12l-2 2M11 16l3-3"/>
    </svg>
  );
}

function ColorSequenceIcon({ className }: IconProps) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="3" width="18" height="18" rx="2"/>
      <circle cx="7" cy="12" r="1.5" fill="currentColor"/>
      <circle cx="12" cy="12" r="1.5" fill="currentColor"/>
      <circle cx="17" cy="12" r="1.5" fill="currentColor"/>
      <path d="M5 12h19"/>
    </svg>
  );
}

function ReflexRushIcon({ className }: IconProps) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="3" width="18" height="18" rx="2"/>
      <path d="M7 8l4 8-4 4M17 8l-4 8 4 4"/>
      <circle cx="12" cy="12" r="1.5" fill="currentColor"/>
    </svg>
  );
}

function PerfectSecondIcon({ className }: IconProps) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="9"/>
      <path d="M12 12v-7M12 12l3 3"/>
    </svg>
  );
}

function MazeRaceIcon({ className }: IconProps) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="3" width="18" height="18" rx="2"/>
      <path d="M7 7h5v5H7zM15 15h-5v-5h5zM7 15h5M15 7v5"/>
    </svg>
  );
}

function MemoryMatchIcon({ className }: IconProps) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
      <rect x="5" y="6" width="7" height="10" rx="1"/>
      <rect x="12" y="8" width="7" height="10" rx="1"/>
      <path d="M10 10h2M17 12h2"/>
    </svg>
  );
}

function ReactionTestIcon({ className }: IconProps) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="9"/>
      <circle cx="12" cy="12" r="5"/>
      <circle cx="12" cy="12" r="1.5" fill="currentColor"/>
    </svg>
  );
}

function MathChallengeIcon({ className }: IconProps) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="3" width="18" height="18" rx="2"/>
      <path d="M8 12h8M12 8v8"/>
    </svg>
  );
}

function WordPuzzleIcon({ className }: IconProps) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="3" width="18" height="18" rx="2"/>
      <path d="M7 8h2v2H7zM11 8h2v2h-2zM15 8h2v2h-2zM9 12h2v2H9zM13 12h2v2h-2zM17 12h2v2h-2z"/>
    </svg>
  );
}

const GAME_ICONS: Record<string, React.ComponentType<IconProps>> = {
  number_guessing: NumberGuessingIcon,
  color_sequence: ColorSequenceIcon,
  reflex_rush: ReflexRushIcon,
  perfect_second: PerfectSecondIcon,
  maze_race: MazeRaceIcon,
  memory_match: MemoryMatchIcon,
  reaction_test: ReactionTestIcon,
  math_challenge: MathChallengeIcon,
  word_puzzle: WordPuzzleIcon,
};

function DefaultIcon({ className }: IconProps) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="3" width="18" height="18" rx="2"/>
      <circle cx="12" cy="12" r="4"/>
    </svg>
  );
}

export function GameTile({
  game,
  onSelect,
}: {
  game: GameInfo;
  onSelect: (game: GameInfo) => void;
}) {
  const Icon = GAME_ICONS[game.id] ?? DefaultIcon;
  const playable = game.playable;

  return (
    <button
      onClick={() => (playable ? onSelect(game) : undefined)}
      disabled={!playable}
      aria-label={game.title}
      aria-disabled={!playable}
      className={`flex flex-col items-center justify-center gap-1.5 rounded-2xl bg-panel border border-white/10 shadow-card p-2 active:scale-95 transition-transform duration-150 ${
        playable
          ? 'hover:bg-white/5 cursor-pointer'
          : 'opacity-55 pointer-events-none'
      }`}
    >
      <div className="flex h-[44px] w-[44px] items-center justify-center rounded-xl bg-white/5">
        <Icon className="h-8 w-8" />
      </div>
      <span className="text-xs font-semibold text-white truncate text-center leading-snug line-clamp-2 px-0.5">
        {game.title}
      </span>
    </button>
  );
}
