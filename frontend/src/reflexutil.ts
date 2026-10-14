/** Pure Reflex Rush helpers (unit-tested). Timing itself uses performance.now in the screen. */

export const REFLEX_ROUNDS = 5;

export interface LocalRound {
  reaction_ms: number | null;
  false_start: boolean;
}

/** Random pre-signal wait in ms, injectable RNG for tests. */
export function randomWaitMs(minMs: number, maxMs: number, rng: () => number = Math.random): number {
  const lo = Math.min(minMs, maxMs);
  const hi = Math.max(minMs, maxMs);
  return Math.floor(lo + rng() * (hi - lo + 1));
}

export function reflexAverage(rounds: LocalRound[]): number | null {
  const valid = rounds.filter((r) => !r.false_start && r.reaction_ms !== null) as {
    reaction_ms: number;
  }[];
  if (valid.length === 0) return null;
  return Math.round(valid.reduce((s, r) => s + r.reaction_ms, 0) / valid.length);
}

export function reflexBest(rounds: LocalRound[]): number | null {
  const valid = rounds
    .filter((r) => !r.false_start && r.reaction_ms !== null)
    .map((r) => r.reaction_ms as number);
  return valid.length ? Math.min(...valid) : null;
}

export function countFalseStarts(rounds: LocalRound[]): number {
  return rounds.filter((r) => r.false_start).length;
}

/** Resolve the wait window for a difficulty from the catalog entry. */
export function waitWindow(
  difficulties: { id: string; wait_min_ms?: number; wait_max_ms?: number }[],
  difficulty: string,
): { min: number; max: number } {
  const d = difficulties.find((x) => x.id === difficulty);
  return { min: d?.wait_min_ms ?? 1000, max: d?.wait_max_ms ?? 3000 };
}
