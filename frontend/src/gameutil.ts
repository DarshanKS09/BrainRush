/** Pure UI helpers (unit-tested). */

export function xpPercent(xpIntoLevel: number, xpForNext: number): number {
  if (xpForNext <= 0) return 100;
  return Math.min(100, Math.max(0, (xpIntoLevel / xpForNext) * 100));
}

export function difficultyLabel(id: string): string {
  return id.charAt(0).toUpperCase() + id.slice(1);
}

/** Frontend display name per game (backend ids stay easy/medium/hard). */
export function difficultyDisplayName(gameId: string, id: string): string {
  if (gameId === 'color_sequence' && id === 'medium') return 'Normal';
  return difficultyLabel(id);
}

/** One-line difficulty summary, per game (attempts vs rounds). */
export function difficultySub(
  gameId: string,
  d: { id: string; max_attempts: number; start_length?: number },
): string {
  if (gameId === 'color_sequence') {
    return `Up to ${d.max_attempts} rounds · starts at ${d.start_length ?? '?'}`;
  }
  return difficultyBlurb(d.max_attempts);
}

export function difficultyBlurb(maxAttempts: number): string {
  return `${maxAttempts} attempts`;
}

export function formatDate(iso: string | null): string {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '—';
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

export function outcomeLabel(outcome: string | null): string {
  if (outcome === 'win') return 'Won';
  if (outcome === 'loss') return 'Lost';
  if (outcome === 'draw') return 'Draw';
  return 'In progress';
}

/** Keypad buffer reducer: digits append (max 3 chars), back clears. */
export function keypadReducer(buffer: string, key: string): string {
  if (key === 'back') return buffer.slice(0, -1);
  if (key === 'clear') return '';
  if (!/^[0-9]$/.test(key)) return buffer;
  if (buffer.length >= 3) return buffer;
  const next = buffer === '0' ? key : buffer + key;
  const n = Number(next);
  if (n > 100) return buffer;
  return String(n);
}

/** Short per-game title for resume rows and history. */
export function gameTitle(gameType: string): string {
  if (gameType === 'color_sequence') return 'Color Sequence';
  if (gameType === 'number_guessing') return 'Number Guessing';
  return gameType;
}

/** Right-hand resume hint; shape differs per game type. */
export function resumeHint(game: {
  game_type: string;
  attempts_left?: number;
  level?: number;
}): string {
  if (game.game_type === 'color_sequence') return `Lv ${game.level ?? '?'}`;
  return `${game.attempts_left ?? '?'} left`;
}
