/** Pure UI helpers (unit-tested). */

export function xpPercent(xpIntoLevel: number, xpForNext: number): number {
  if (xpForNext <= 0) return 100;
  return Math.min(100, Math.max(0, (xpIntoLevel / xpForNext) * 100));
}

export function difficultyLabel(id: string): string {
  return id.charAt(0).toUpperCase() + id.slice(1);
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
