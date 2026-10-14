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
  if ((gameId === 'color_sequence' || gameId === 'reflex_rush') && id === 'medium') return 'Normal';
  return difficultyLabel(id);
}

/** One-line difficulty summary, per game (attempts vs rounds). */
export function difficultySub(
  gameId: string,
  d: { id: string; max_attempts: number; start_length?: number; wait_min_ms?: number; wait_max_ms?: number },
): string {
  if (gameId === 'color_sequence') {
    return `Up to ${d.max_attempts} rounds · starts at ${d.start_length ?? '?'}`;
  }
  if (gameId === 'reflex_rush') {
    if (d.wait_min_ms !== undefined && d.wait_max_ms !== undefined) {
      if (d.wait_min_ms === d.wait_max_ms) return `Fixed ${d.wait_min_ms / 1000} s wait`;
      return `Waits ${d.wait_min_ms / 1000}–${d.wait_max_ms / 1000} s`;
    }
    return `5 rounds · tap fast`;
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

/** History label driven by session status first: abandoned/expired rows
 * have no result, so outcome-only labels would wrongly read "In progress". */
export function sessionStatusLabel(status: string, outcome: string | null): string {
  if (status === 'abandoned') return 'Abandoned';
  if (status === 'expired') return 'Expired';
  if (status === 'completed') return outcomeLabel(outcome);
  return 'In progress';
}

/** Exact pre-signal wait description for Reflex Rush difficulties, from the
 * catalog's published wait window (backend-enforced ranges). */
export function reflexWaitText(d: { id: string; wait_min_ms?: number; wait_max_ms?: number }): string {
  const min = d.wait_min_ms;
  const max = d.wait_max_ms;
  if (min === undefined || max === undefined) return 'Wait for green, then tap';
  const secs = (ms: number): string => `${ms / 1000}`;
  if (min === max) return `Same wait every round: ${secs(min)} s`;
  if (Number.isInteger(min / 1000) && Number.isInteger(max / 1000)) {
    return `Wait varies: ${min / 1000}–${max / 1000} s`;
  }
  return `Wait varies: ${secs(min)}–${secs(max)} s`;
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
  if (gameType === 'reflex_rush') return 'Reflex Rush';
  return gameType;
}

/** Right-hand resume hint; shape differs per game type. */
export function resumeHint(game: {
  game_type: string;
  attempts_left?: number;
  level?: number;
  rounds_played?: number;
  rounds_total?: number;
}): string {
  if (game.game_type === 'color_sequence') return `Lv ${game.level ?? '?'}`;
  if (game.game_type === 'reflex_rush')
    return `${game.rounds_played ?? 0}/${game.rounds_total ?? 5}`;
  return `${game.attempts_left ?? '?'} left`;
}

/** Format a reaction time for display. Null = false start. */
export function formatMs(ms: number | null): string {
  if (ms === null || ms === undefined) return 'False start';
  return `${ms} ms`;
}
