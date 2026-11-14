/** One shared Web Audio manager for the whole app.
 *
 *  Design notes:
 *  - Exactly one AudioContext is created, lazily, and only resumed from a
 *    real user gesture (Telegram Mini App + mobile browsers block autoplay).
 *  - Each sound recipe is rendered once with OfflineAudioContext into an
 *    AudioBuffer ("preload"), so repeated plays are cheap and never build a
 *    graph per interaction.
 *  - If rendering has not finished yet (very first tap), the same recipe is
 *    synthesized live so the effect is never silently missing.
 *  - Every call is wrapped so blocked/suspended audio can never throw into a
 *    game handler.
 *  - Nothing here reads game state: callers decide when an event happened.
 */
import {
  AUDIO_STORAGE_KEYS,
  COLOR_TONES,
  DEFAULT_VOLUME,
  SOUNDS,
  type SoundName,
  type SoundSpec,
} from './audioConfig';

export interface AudioSettingsView {
  muted: boolean;
  volume: number;
}

type AudioContextCtor = typeof AudioContext;
type OfflineCtor = typeof OfflineAudioContext;

let ctx: AudioContext | null = null;
let master: GainNode | null = null;
let muted = readStoredMuted();
let volume = readStoredVolume();
let preloadPromise: Promise<void> | null = null;
let unlockInstalled = false;
let visibilityHooked = false;
let terminalGuard = { at: 0 };

const buffers = new Map<SoundName, AudioBuffer>();
const lastPlayedAt = new Map<SoundName, number>();
const activeSources = new Set<AudioScheduledSourceNode>();
const listeners = new Set<(settings: AudioSettingsView) => void>();

function readStoredMuted(): boolean {
  try {
    return window.localStorage?.getItem(AUDIO_STORAGE_KEYS.muted) === '1';
  } catch {
    return false;
  }
}

function readStoredVolume(): number {
  try {
    const raw = Number(window.localStorage?.getItem(AUDIO_STORAGE_KEYS.volume));
    if (Number.isFinite(raw) && raw >= 0 && raw <= 1) return raw;
  } catch {
    /* private mode */
  }
  return DEFAULT_VOLUME;
}

function persistSettings(): void {
  try {
    window.localStorage?.setItem(AUDIO_STORAGE_KEYS.muted, muted ? '1' : '0');
    window.localStorage?.setItem(AUDIO_STORAGE_KEYS.volume, String(volume));
  } catch {
    /* storage unavailable: settings last for this session only */
  }
}

function notify(): void {
  const snapshot = getAudioSettings();
  for (const listener of listeners) {
    try {
      listener(snapshot);
    } catch {
      /* a bad subscriber must not break audio */
    }
  }
}

export function getAudioSettings(): AudioSettingsView {
  return { muted, volume };
}

export function subscribeAudioSettings(fn: (settings: AudioSettingsView) => void): () => void {
  listeners.add(fn);
  return () => {
    listeners.delete(fn);
  };
}

function audioContextCtor(): AudioContextCtor | null {
  if (typeof window === 'undefined') return null;
  return (
    window.AudioContext ??
    (window as unknown as { webkitAudioContext?: AudioContextCtor }).webkitAudioContext ??
    null
  );
}

function offlineCtor(): OfflineCtor | null {
  if (typeof window === 'undefined') return null;
  return (
    window.OfflineAudioContext ??
    (window as unknown as { webkitOfflineAudioContext?: OfflineCtor }).webkitOfflineAudioContext ??
    null
  );
}

/** Lazily create the single shared context plus its master gain. */
function ensureContext(): AudioContext | null {
  if (ctx) return ctx;
  const Ctor = audioContextCtor();
  if (!Ctor) return null;
  try {
    const created = new Ctor();
    const gain = created.createGain();
    gain.gain.value = muted ? 0 : volume;
    gain.connect(created.destination);
    ctx = created;
    master = gain;
  } catch {
    ctx = null;
    master = null;
  }
  return ctx;
}

function applyMasterGain(): void {
  if (!master) return;
  try {
    const target = muted ? 0 : volume;
    // A short ramp avoids a click when the slider or toggle changes.
    master.gain.setTargetAtTime(target, master.context.currentTime, 0.01);
  } catch {
    /* ignore */
  }
}

function resumeContext(): void {
  const c = ctx;
  if (!c) return;
  if (c.state === 'suspended') {
    c.resume().catch(() => {
      /* gesture still pending: game continues silently */
    });
  }
}

function totalDuration(spec: SoundSpec): number {
  let end = 0;
  for (const tone of spec.tones ?? []) end = Math.max(end, (tone.delay ?? 0) + tone.dur);
  for (const noise of spec.noises ?? []) end = Math.max(end, (noise.delay ?? 0) + noise.dur);
  return Math.max(0.05, end + 0.03);
}

function schedule(
  target: BaseAudioContext,
  spec: SoundSpec,
  destination: AudioNode,
  startAt: number,
  sources: AudioScheduledSourceNode[],
): void {
  const level = spec.level ?? 0.4;

  for (const tone of spec.tones ?? []) {
    const t0 = startAt + (tone.delay ?? 0);
    const dur = Math.max(0.02, tone.dur);
    const osc = target.createOscillator();
    const gain = target.createGain();
    osc.type = tone.type ?? 'sine';
    osc.frequency.setValueAtTime(Math.max(20, tone.freq), t0);
    if (tone.to) {
      osc.frequency.exponentialRampToValueAtTime(Math.max(20, tone.to), t0 + dur);
    }
    const peak = Math.max(0.0001, (tone.gain ?? 0.4) * level);
    gain.gain.setValueAtTime(0.0001, t0);
    gain.gain.exponentialRampToValueAtTime(peak, t0 + Math.min(0.012, dur * 0.25));
    gain.gain.exponentialRampToValueAtTime(0.0001, t0 + dur);
    osc.connect(gain).connect(destination);
    osc.start(t0);
    osc.stop(t0 + dur + 0.02);
    sources.push(osc);
  }

  for (const noise of spec.noises ?? []) {
    const t0 = startAt + (noise.delay ?? 0);
    const dur = Math.max(0.02, noise.dur);
    const frames = Math.max(1, Math.floor(target.sampleRate * dur));
    const buffer = target.createBuffer(1, frames, target.sampleRate);
    const data = buffer.getChannelData(0);
    for (let i = 0; i < frames; i += 1) data[i] = Math.random() * 2 - 1;
    const src = target.createBufferSource();
    src.buffer = buffer;
    const filter = target.createBiquadFilter();
    filter.type = 'bandpass';
    filter.frequency.setValueAtTime(noise.filter ?? 2400, t0);
    filter.Q.value = noise.q ?? 1;
    const gain = target.createGain();
    const peak = Math.max(0.0001, (noise.gain ?? 0.2) * level);
    gain.gain.setValueAtTime(peak, t0);
    gain.gain.exponentialRampToValueAtTime(0.0001, t0 + dur);
    src.connect(filter).connect(gain).connect(destination);
    src.start(t0);
    src.stop(t0 + dur + 0.02);
    sources.push(src);
  }
}

function track(source: AudioScheduledSourceNode): void {
  activeSources.add(source);
  source.addEventListener('ended', () => {
    activeSources.delete(source);
  });
}

/** Render one recipe into a buffer. Never throws. */
async function renderSound(spec: SoundSpec): Promise<AudioBuffer | null> {
  const OAC = offlineCtor();
  const live = ensureContext();
  if (!OAC || !live) return null;
  try {
    const rate = live.sampleRate || 44_100;
    const frames = Math.max(1, Math.ceil(totalDuration(spec) * rate));
    const offline = new OAC(1, frames, rate);
    const sources: AudioScheduledSourceNode[] = [];
    schedule(offline, spec, offline.destination, 0, sources);
    return await offline.startRendering();
  } catch {
    return null;
  }
}

/** Render every sound once. Safe to call repeatedly; resolves when done. */
export function preloadAudio(): Promise<void> {
  if (preloadPromise) return preloadPromise;
  preloadPromise = (async () => {
    const names = Object.keys(SOUNDS) as SoundName[];
    // Small batches keep the main thread responsive during the first gesture.
    for (let i = 0; i < names.length; i += 4) {
      await Promise.all(
        names.slice(i, i + 4).map(async (name) => {
          if (buffers.has(name)) return;
          const buffer = await renderSound(SOUNDS[name]);
          if (buffer) buffers.set(name, buffer);
        }),
      );
    }
  })()
    .catch(() => {
      /* assets are optional */
    })
    .finally(() => {
      // Allow a later retry if the context did not exist yet.
      if (buffers.size === 0) preloadPromise = null;
    });
  return preloadPromise;
}

/** Call from a genuine user gesture (tap / key press). Idempotent. */
export function unlockAudio(): void {
  const c = ensureContext();
  if (!c) return;
  resumeContext();
  void preloadAudio();
}

/** Install the one-time global gesture unlock + visibility handling. */
export function installAudioUnlock(): void {
  if (typeof window === 'undefined' || unlockInstalled) return;
  unlockInstalled = true;
  const onGesture = () => {
    try {
      unlockAudio();
    } catch {
      /* ignore */
    }
  };
  try {
    window.addEventListener('pointerdown', onGesture, { passive: true });
    window.addEventListener('keydown', onGesture);
    window.addEventListener('touchstart', onGesture, { passive: true });
  } catch {
    /* old clients */
  }
  if (!visibilityHooked && typeof document !== 'undefined') {
    visibilityHooked = true;
    document.addEventListener('visibilitychange', () => {
      try {
        if (document.visibilityState === 'hidden') stopAllSounds();
        else if (!muted) resumeContext();
      } catch {
        /* ignore */
      }
    });
  }
}

/** Stop every sound that is currently sounding. */
export function stopAllSounds(): void {
  for (const source of activeSources) {
    try {
      source.stop();
    } catch {
      /* already stopped */
    }
  }
  activeSources.clear();
}

/** Play one effect. No-op when muted, unsupported, or blocked. */
export function playSound(name: SoundName): void {
  try {
    if (muted) return;
    const spec = SOUNDS[name];
    if (!spec) return;

    const now = Date.now();
    const gap = spec.minGapMs ?? 40;
    if (now - (lastPlayedAt.get(name) ?? 0) < gap) return;

    // Never let a victory and a defeat sound overlap (or repeat back-to-back).
    if (spec.terminal) {
      if (now - terminalGuard.at < 1000) return;
      terminalGuard = { at: now };
      stopAllSounds();
    }

    const c = ensureContext();
    if (!c) return;

    lastPlayedAt.set(name, now);
    resumeContext();

    const destination = master ?? c.destination;
    const buffer = buffers.get(name);
    if (buffer) {
      const src = c.createBufferSource();
      src.buffer = buffer;
      src.connect(destination);
      track(src);
      src.start();
      return;
    }

    // Preload has not finished yet: synthesize this one live, once.
    const sources: AudioScheduledSourceNode[] = [];
    schedule(c, spec, destination, c.currentTime + 0.001, sources);
    for (const source of sources) track(source);
    void preloadAudio();
  } catch {
    /* audio must never break gameplay */
  }
}

/** Color Sequence playback tone for pad index 0..3. */
export function playColorTone(index: number): void {
  playSound(COLOR_TONES[index] ?? 'uiTap');
}

export function isMuted(): boolean {
  return muted;
}

export function getVolume(): number {
  return volume;
}

/** Muting takes effect immediately: anything sounding is cut. */
export function setMuted(next: boolean): void {
  if (muted === next) return;
  muted = next;
  persistSettings();
  if (muted) stopAllSounds();
  applyMasterGain();
  notify();
}

export function setVolume(next: number): void {
  if (!Number.isFinite(next)) return;
  const clamped = Math.min(1, Math.max(0, next));
  if (clamped === volume) return;
  volume = clamped;
  persistSettings();
  applyMasterGain();
  notify();
}
