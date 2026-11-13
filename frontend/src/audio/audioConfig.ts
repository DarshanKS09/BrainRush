/** Sound catalogue for BrainRush.
 *
 *  Every effect is synthesized from a tiny declarative recipe (one oscillator
 *  plus optional filtered noise). No audio files, no external URLs, nothing to
 *  license or download — the recipes are original. The manager renders each
 *  recipe once into an AudioBuffer (see audioManager.ts).
 */

export type SoundName =
  | 'uiTap'
  | 'correct'
  | 'wrong'
  | 'win'
  | 'loss'
  | 'levelComplete'
  | 'targetChange'
  | 'lifeLost'
  | 'lowLives'
  | 'missedTarget'
  | 'countdown'
  | 'start'
  | 'metallicTap'
  | 'focusCorrect'
  | 'focusWrong'
  | 'focusTargetChange'
  | 'focusWin'
  | 'focusLoss'
  | 'move'
  | 'blocked'
  | 'stop'
  | 'falseStart'
  | 'perfectWin'
  | 'colorRed'
  | 'colorGreen'
  | 'colorBlue'
  | 'colorYellow';

export interface ToneSpec {
  /** Starting frequency in Hz. */
  freq: number;
  /** Optional exponential glide target in Hz. */
  to?: number;
  /** Duration in seconds. */
  dur: number;
  /** Start offset in seconds (for arpeggios). */
  delay?: number;
  type?: OscillatorType;
  /** Peak gain 0..1 before the per-sound level is applied. */
  gain?: number;
}

export interface NoiseSpec {
  dur: number;
  delay?: number;
  gain?: number;
  /** Band-pass centre frequency in Hz. */
  filter?: number;
  q?: number;
}

export interface SoundSpec {
  tones?: ToneSpec[];
  noises?: NoiseSpec[];
  /** Peak level 0..1 applied on top of the master volume. */
  level?: number;
  /** Two plays closer together than this are treated as one event. */
  minGapMs?: number;
  /** Terminal sounds (win/loss) cut whatever is still playing. */
  terminal?: boolean;
}

/** Interaction tap: short, quiet, and safe to repeat rapidly. */
const TAP: SoundSpec = {
  tones: [{ freq: 760, dur: 0.035, type: 'triangle', gain: 0.35 }],
  level: 0.32,
  minGapMs: 45,
};

export const SOUNDS: Record<SoundName, SoundSpec> = {
  // --- ordinary interaction -------------------------------------------------
  uiTap: TAP,
  move: {
    tones: [{ freq: 440, dur: 0.035, type: 'triangle', gain: 0.32 }],
    level: 0.3,
    minGapMs: 60,
  },
  blocked: {
    tones: [{ freq: 110, to: 82, dur: 0.09, type: 'sine', gain: 0.4 }],
    noises: [{ dur: 0.05, gain: 0.16, filter: 500, q: 0.9 }],
    level: 0.34,
    minGapMs: 120,
  },
  metallicTap: {
    tones: [{ freq: 1480, dur: 0.03, type: 'square', gain: 0.3 }],
    noises: [{ dur: 0.035, gain: 0.34, filter: 3400, q: 1.6 }],
    level: 0.38,
    minGapMs: 35,
  },
  stop: {
    tones: [
      { freq: 660, dur: 0.06, type: 'sine', gain: 0.42 },
      { freq: 990, dur: 0.05, type: 'sine', gain: 0.18, delay: 0.04 },
    ],
    level: 0.34,
    minGapMs: 80,
  },
  countdown: {
    tones: [{ freq: 880, dur: 0.05, type: 'sine', gain: 0.35 }],
    level: 0.3,
    minGapMs: 80,
  },
  start: {
    tones: [
      { freq: 523.25, dur: 0.09, type: 'sine', gain: 0.4 },
      { freq: 783.99, dur: 0.11, type: 'sine', gain: 0.42, delay: 0.07 },
    ],
    level: 0.34,
    minGapMs: 150,
  },

  // --- correct / incorrect --------------------------------------------------
  correct: {
    tones: [
      { freq: 659.25, dur: 0.07, type: 'sine', gain: 0.44 },
      { freq: 987.77, dur: 0.09, type: 'sine', gain: 0.42, delay: 0.055 },
    ],
    level: 0.4,
    minGapMs: 90,
  },
  wrong: {
    tones: [
      { freq: 196, to: 165, dur: 0.16, type: 'sawtooth', gain: 0.4 },
      { freq: 147, dur: 0.1, type: 'square', gain: 0.2, delay: 0.06 },
    ],
    level: 0.36,
    minGapMs: 140,
  },
  falseStart: {
    tones: [{ freq: 233, to: 185, dur: 0.14, type: 'square', gain: 0.38 }],
    level: 0.34,
    minGapMs: 140,
  },

  // --- game won / lost ------------------------------------------------------
  win: {
    tones: [
      { freq: 523.25, dur: 0.1, type: 'sine', gain: 0.46 },
      { freq: 659.25, dur: 0.1, type: 'sine', gain: 0.46, delay: 0.09 },
      { freq: 783.99, dur: 0.1, type: 'sine', gain: 0.46, delay: 0.18 },
      { freq: 1046.5, dur: 0.24, type: 'sine', gain: 0.5, delay: 0.27 },
    ],
    level: 0.45,
    minGapMs: 1200,
    terminal: true,
  },
  loss: {
    tones: [
      { freq: 392, dur: 0.13, type: 'sine', gain: 0.44 },
      { freq: 329.63, dur: 0.13, type: 'sine', gain: 0.42, delay: 0.12 },
      { freq: 261.63, to: 220, dur: 0.24, type: 'sine', gain: 0.42, delay: 0.24 },
    ],
    level: 0.42,
    minGapMs: 1200,
    terminal: true,
  },

  // --- contextual -----------------------------------------------------------
  levelComplete: {
    tones: [
      { freq: 783.99, dur: 0.08, type: 'sine', gain: 0.44 },
      { freq: 1046.5, dur: 0.12, type: 'sine', gain: 0.46, delay: 0.07 },
    ],
    level: 0.38,
    minGapMs: 200,
  },
  targetChange: {
    tones: [
      { freq: 880, dur: 0.055, type: 'sine', gain: 0.32 },
      { freq: 1174.66, dur: 0.08, type: 'sine', gain: 0.3, delay: 0.045 },
    ],
    level: 0.3,
    minGapMs: 300,
  },
  lifeLost: {
    tones: [
      { freq: 330, to: 262, dur: 0.1, type: 'square', gain: 0.36 },
      { freq: 220, dur: 0.13, type: 'square', gain: 0.26, delay: 0.08 },
    ],
    level: 0.34,
    minGapMs: 200,
  },
  lowLives: {
    tones: [
      { freq: 466.16, dur: 0.06, type: 'triangle', gain: 0.34 },
      { freq: 349.23, dur: 0.09, type: 'triangle', gain: 0.32, delay: 0.07 },
    ],
    level: 0.3,
    minGapMs: 400,
  },
  missedTarget: {
    tones: [{ freq: 262, to: 196, dur: 0.18, type: 'square', gain: 0.36 }],
    noises: [{ dur: 0.06, gain: 0.12, filter: 700, q: 0.8 }],
    level: 0.34,
    minGapMs: 200,
  },

  // --- Focus Rush -----------------------------------------------------------
  focusCorrect: {
    tones: [
      { freq: 1046.5, dur: 0.06, type: 'sine', gain: 0.42 },
      { freq: 1318.5, dur: 0.1, type: 'sine', gain: 0.44, delay: 0.05 },
    ],
    noises: [{ dur: 0.04, gain: 0.1, filter: 4200, q: 1.4, delay: 0.005 }],
    level: 0.38,
    minGapMs: 70,
  },
  focusWrong: {
    tones: [
      { freq: 165, to: 124, dur: 0.18, type: 'sawtooth', gain: 0.42 },
      { freq: 110, dur: 0.12, type: 'square', gain: 0.2, delay: 0.05 },
    ],
    level: 0.36,
    minGapMs: 220,
  },
  focusTargetChange: {
    tones: [
      { freq: 587.33, dur: 0.07, type: 'sine', gain: 0.32 },
      { freq: 880, dur: 0.09, type: 'sine', gain: 0.32, delay: 0.06 },
      { freq: 1174.66, dur: 0.12, type: 'sine', gain: 0.28, delay: 0.13 },
    ],
    level: 0.3,
    minGapMs: 400,
  },
  focusWin: {
    tones: [
      { freq: 523.25, dur: 0.1, type: 'sine', gain: 0.46 },
      { freq: 659.25, dur: 0.1, type: 'sine', gain: 0.46, delay: 0.09 },
      { freq: 783.99, dur: 0.1, type: 'sine', gain: 0.46, delay: 0.18 },
      { freq: 1046.5, dur: 0.16, type: 'sine', gain: 0.5, delay: 0.27 },
      { freq: 1567.98, dur: 0.2, type: 'sine', gain: 0.24, delay: 0.34 },
    ],
    level: 0.45,
    minGapMs: 1200,
    terminal: true,
  },
  focusLoss: {
    tones: [
      { freq: 392, to: 349.23, dur: 0.14, type: 'sine', gain: 0.44 },
      { freq: 277.18, dur: 0.14, type: 'sine', gain: 0.4, delay: 0.12 },
      { freq: 196, to: 155, dur: 0.26, type: 'sine', gain: 0.4, delay: 0.24 },
    ],
    level: 0.42,
    minGapMs: 1200,
    terminal: true,
  },
  perfectWin: {
    tones: [
      { freq: 659.25, dur: 0.08, type: 'sine', gain: 0.44 },
      { freq: 880, dur: 0.08, type: 'sine', gain: 0.46, delay: 0.075 },
      { freq: 1174.66, dur: 0.18, type: 'sine', gain: 0.48, delay: 0.15 },
      { freq: 1567.98, dur: 0.2, type: 'sine', gain: 0.24, delay: 0.24 },
    ],
    level: 0.44,
    minGapMs: 1200,
    terminal: true,
  },

  // --- Color Sequence playback tones (one per pad) --------------------------
  colorRed: {
    tones: [{ freq: 261.63, dur: 0.28, type: 'sine', gain: 0.42 }],
    level: 0.4,
    minGapMs: 60,
  },
  colorGreen: {
    tones: [{ freq: 329.63, dur: 0.28, type: 'sine', gain: 0.42 }],
    level: 0.4,
    minGapMs: 60,
  },
  colorBlue: {
    tones: [{ freq: 392.0, dur: 0.28, type: 'sine', gain: 0.42 }],
    level: 0.4,
    minGapMs: 60,
  },
  colorYellow: {
    tones: [{ freq: 523.25, dur: 0.28, type: 'sine', gain: 0.42 }],
    level: 0.4,
    minGapMs: 60,
  },
};

/** Playback tone for a Color Sequence pad index. */
export const COLOR_TONES: SoundName[] = ['colorRed', 'colorGreen', 'colorBlue', 'colorYellow'];

/** Win/loss sound for a game id. Gameplay never reads this — only the sound
 *  that accompanies an authoritative final result. */
export function outcomeSound(gameId: string, outcome: 'win' | 'loss'): SoundName {
  if (gameId === 'focus_rush') return outcome === 'win' ? 'focusWin' : 'focusLoss';
  return outcome === 'win' ? 'win' : 'loss';
}

export const AUDIO_STORAGE_KEYS = {
  muted: 'brainrush:audio:muted',
  volume: 'brainrush:audio:volume',
} as const;

export const DEFAULT_VOLUME = 0.7;
