import { describe, expect, it } from 'vitest';
import {
  difficultyBlurb,
  difficultyLabel,
  formatDate,
  keypadReducer,
  outcomeLabel,
  xpPercent,
} from './gameutil';

describe('xpPercent', () => {
  it('computes progress and clamps', () => {
    expect(xpPercent(50, 200)).toBe(25);
    expect(xpPercent(0, 100)).toBe(0);
    expect(xpPercent(999, 100)).toBe(100);
    expect(xpPercent(10, 0)).toBe(100);
  });
});

describe('labels', () => {
  it('formats difficulties, dates, outcomes', () => {
    expect(difficultyLabel('easy')).toBe('Easy');
    expect(difficultyBlurb(15)).toBe('15 attempts');
    expect(outcomeLabel('win')).toBe('Won');
    expect(outcomeLabel(null)).toBe('In progress');
    expect(formatDate(null)).toBe('—');
    expect(formatDate('not-a-date')).toBe('—');
    expect(formatDate('2026-10-12T10:00:00+00:00')).not.toBe('—');
  });
});

describe('keypadReducer', () => {
  it('appends digits, caps at 100, supports back/clear', () => {
    expect(keypadReducer('', '4')).toBe('4');
    expect(keypadReducer('4', '2')).toBe('42');
    expect(keypadReducer('10', '1')).toBe('10'); // would exceed 100
    expect(keypadReducer('100', '5')).toBe('100');
    expect(keypadReducer('42', 'back')).toBe('4');
    expect(keypadReducer('42', 'clear')).toBe('');
    expect(keypadReducer('4', 'x')).toBe('4');
  });
});
