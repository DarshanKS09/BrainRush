import { describe, expect, it } from 'vitest';
import {
  difficultyBlurb,
  difficultyDisplayName,
  difficultyLabel,
  difficultySub,
  formatDate,
  formatSeconds,
  gameTitle,
  keypadReducer,
  outcomeLabel,
  perfectVerdict,
  reflexWaitText,
  resumeHint,
  sessionStatusLabel,
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

  it('labels color difficulties per game without touching backend ids', () => {
    expect(difficultyDisplayName('color_sequence', 'medium')).toBe('Normal');
    expect(difficultyDisplayName('color_sequence', 'easy')).toBe('Easy');
    expect(difficultyDisplayName('number_guessing', 'medium')).toBe('Medium');
    expect(difficultySub('color_sequence', { id: 'easy', max_attempts: 8, start_length: 3 }))
      .toBe('Up to 8 rounds · starts at 3');
    expect(difficultySub('number_guessing', { id: 'hard', max_attempts: 7 }))
      .toBe('7 attempts');
  });

  it('titles games and resume hints per type', () => {
    expect(gameTitle('color_sequence')).toBe('Color Sequence');
    expect(gameTitle('number_guessing')).toBe('Number Guessing');
    expect(resumeHint({ game_type: 'color_sequence', level: 4 })).toBe('Lv 4');
    expect(resumeHint({ game_type: 'number_guessing', attempts_left: 5 })).toBe('5 left');
  });

  it('labels session status before outcome', () => {
    expect(sessionStatusLabel('abandoned', null)).toBe('Abandoned');
    expect(sessionStatusLabel('expired', null)).toBe('Expired');
    expect(sessionStatusLabel('completed', 'win')).toBe('Won');
    expect(sessionStatusLabel('completed', 'loss')).toBe('Lost');
    expect(sessionStatusLabel('completed', null)).toBe('In progress');
    expect(sessionStatusLabel('started', null)).toBe('In progress');
  });

  it('describes reflex wait windows exactly', () => {
    expect(reflexWaitText({ id: 'easy', wait_min_ms: 2000, wait_max_ms: 2000 }))
      .toBe('Same wait every round: 2 s');
    expect(reflexWaitText({ id: 'medium', wait_min_ms: 1000, wait_max_ms: 3000 }))
      .toBe('Wait varies: 1–3 s');
    expect(reflexWaitText({ id: 'hard', wait_min_ms: 500, wait_max_ms: 3500 }))
      .toBe('Wait varies: 0.5–3.5 s');
    expect(reflexWaitText({ id: 'easy' })).toBe('Wait for green, then tap');
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

describe('perfectSecond', () => {
  it('titles the game and summarizes target ranges per difficulty', () => {
    expect(gameTitle('perfect_second')).toBe('Perfect Second');
    expect(difficultySub('perfect_second', { id: 'easy', max_attempts: 1, target_min_ms: 3000, target_max_ms: 15000, target_step_ms: 1000 }))
      .toBe('Targets 3–15 s · 1 s steps');
    expect(difficultySub('perfect_second', { id: 'medium', max_attempts: 1, target_min_ms: 3000, target_max_ms: 12000, target_step_ms: 500 }))
      .toBe('Targets 3–12 s · 500 ms steps');
    expect(difficultySub('perfect_second', { id: 'hard', max_attempts: 1, target_min_ms: 2000, target_max_ms: 10000, target_step_ms: 10 }))
      .toBe('Targets 2–10 s · 10 ms steps');
    expect(resumeHint({ game_type: 'perfect_second', target_ms: 5500, difficulty: 'medium' }))
      .toBe('🎯 5.5 s');
  });

  it('formats times per difficulty precision', () => {
    expect(formatSeconds(7000, 'easy')).toBe('7 s');
    expect(formatSeconds(5500, 'medium')).toBe('5.5 s');
    expect(formatSeconds(5000, 'medium')).toBe('5 s');
    expect(formatSeconds(5340, 'hard')).toBe('5.34 s');
    expect(formatSeconds(5500, 'hard')).toBe('5.50 s');
    expect(formatSeconds(5500, 'unknown')).toBe('5.50 s');
  });

  it('tiers verdicts by accuracy', () => {
    expect(perfectVerdict(100)).toBe('PERFECT! 🏆');
    expect(perfectVerdict(90)).toBe('Incredible! ⚡');
    expect(perfectVerdict(70)).toBe('Great timing! 🎯');
    expect(perfectVerdict(50)).toBe('Good effort! 👍');
    expect(perfectVerdict(25)).toBe('Close — keep practicing! 🙂');
    expect(perfectVerdict(1)).toBe('Way off! 😅');
    expect(perfectVerdict(0)).toBe('Missed it! 💪');
  });
});
