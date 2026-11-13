import { describe, expect, it } from 'vitest';
import {
  OBJECT_SIZE_PX,
  accuracyText,
  difficultySummary,
  fallProgress,
  instructionFor,
  isTargetObject,
  mergeFallingObjects,
  objectTopPx,
} from './focusutil';
import type { FocusObject } from './api';

const target = { color: 'blue', shape: 'circle' } as const;

function obj(overrides: Partial<FocusObject> = {}): FocusObject {
  return {
    id: 'o1',
    color: 'blue',
    shape: 'circle',
    x: 0.27,
    spawned_at_ms: 1000,
    fall_ms: 4000,
    stale: false,
    ...overrides,
  };
}

describe('fallProgress', () => {
  it('is linear between spawn and landing and clamps at both ends', () => {
    expect(fallProgress(1000, 4000, 500)).toBe(0);
    expect(fallProgress(1000, 4000, 1000)).toBe(0);
    expect(fallProgress(1000, 4000, 3000)).toBe(0.5);
    expect(fallProgress(1000, 4000, 9000)).toBe(1);
  });

  it('treats a non-positive fall duration as already landed', () => {
    expect(fallProgress(0, 0, 10)).toBe(1);
  });
});

describe('objectTopPx', () => {
  it('starts fully above the area and ends at the bottom edge', () => {
    expect(objectTopPx(0, 400)).toBe(-OBJECT_SIZE_PX);
    expect(objectTopPx(1, 400)).toBe(400);
    // Halfway through its own travel: -48 + 0.5 * (400 + 48).
    expect(objectTopPx(0.5, 400)).toBe(176);
  });

  it('clamps out-of-range progress', () => {
    expect(objectTopPx(-2, 400)).toBe(-OBJECT_SIZE_PX);
    expect(objectTopPx(4, 400)).toBe(400);
  });
});

describe('isTargetObject', () => {
  it('matches only the current target and ignores stale shapes', () => {
    expect(isTargetObject(obj(), target)).toBe(true);
    expect(isTargetObject(obj({ color: 'red' }), target)).toBe(false);
    expect(isTargetObject(obj({ shape: 'square' }), target)).toBe(false);
    expect(isTargetObject(obj({ stale: true }), target)).toBe(false);
    expect(isTargetObject(obj(), null)).toBe(false);
  });
});

describe('mergeFallingObjects', () => {
  it('adds server objects, keeps landing state, drops resolved ones', () => {
    const previous = [
      { ...obj({ id: 'o1' }), landed: true },
      { ...obj({ id: 'o2' }) },
    ];
    const incoming = [obj({ id: 'o1' }), obj({ id: 'o3', color: 'red' })];
    const merged = mergeFallingObjects(previous, incoming, new Set());
    expect(merged.map((o) => o.id)).toEqual(['o1', 'o3']);
    expect(merged[0].landed).toBe(true);
    expect(merged[1].landed).toBeUndefined();
  });

  it('never resurrects an object that was just tapped', () => {
    const merged = mergeFallingObjects([], [obj({ id: 'o9' })], new Set(['o9']));
    expect(merged).toEqual([]);
  });
});

describe('labels', () => {
  it('formats accuracy and the target instruction', () => {
    expect(accuracyText(66.6)).toBe('67%');
    expect(accuracyText(Number.NaN)).toBe('0%');
    expect(instructionFor(target)).toBe('TAP BLUE CIRCLES');
  });

  it('summarises difficulty from the server config', () => {
    const text = difficultySummary({
      fall_ms: 2400,
      spawn_interval_ms: 460,
      max_objects: 10,
      target_change_ms: 11000,
      max_lives: 3,
      colors: ['red', 'blue', 'green', 'yellow', 'purple'],
    });
    expect(text).toBe('2.4s fall · 460ms spawn · 5 colours');
    expect(difficultySummary(null)).toBe('');
  });
});
