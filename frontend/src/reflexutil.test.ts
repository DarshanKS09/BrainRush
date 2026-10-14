import { describe, expect, it } from 'vitest';
import {
  REFLEX_ROUNDS,
  countFalseStarts,
  randomWaitMs,
  reflexAverage,
  reflexBest,
  waitWindow,
} from './reflexutil';

describe('reflexutil', () => {
  it('plays exactly five rounds', () => {
    expect(REFLEX_ROUNDS).toBe(5);
  });

  it('draws waits inside the difficulty window', () => {
    expect(randomWaitMs(800, 2500, () => 0)).toBe(800);
    expect(randomWaitMs(800, 2500, () => 0.99999)).toBe(2500);
    const mid = randomWaitMs(1000, 3000, () => 0.5);
    expect(mid).toBeGreaterThanOrEqual(1000);
    expect(mid).toBeLessThanOrEqual(3000);
  });

  it('averages and bests only valid taps', () => {
    const rounds = [
      { reaction_ms: 200, false_start: false },
      { reaction_ms: null, false_start: true },
      { reaction_ms: 400, false_start: false },
    ];
    expect(reflexAverage(rounds)).toBe(300);
    expect(reflexBest(rounds)).toBe(200);
    expect(countFalseStarts(rounds)).toBe(1);
    expect(reflexAverage([{ reaction_ms: null, false_start: true }])).toBeNull();
    expect(reflexBest([{ reaction_ms: null, false_start: true }])).toBeNull();
  });

  it('resolves wait windows from the catalog with safe defaults', () => {
    expect(waitWindow([{ id: 'medium', wait_min_ms: 1000, wait_max_ms: 3000 }], 'medium')).toEqual({
      min: 1000,
      max: 3000,
    });
    expect(waitWindow([], 'hard')).toEqual({ min: 1000, max: 3000 });
  });
});
