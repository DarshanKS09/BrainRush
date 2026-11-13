import { useEffect, useRef, useState } from 'react';
import { outcomeSound } from './audioConfig';
import {
  getAudioSettings,
  playSound,
  setMuted as storeMuted,
  setVolume as storeVolume,
  stopAllSounds,
  subscribeAudioSettings,
  unlockAudio,
} from './audioManager';
import type { SoundName } from './audioConfig';

/** Cancel anything still sounding when a game screen goes away. */
export function useAudioScope(): void {
  useEffect(() => () => stopAllSounds(), []);
}

/** Play the win/loss effect once per session, from authoritative state.
 *
 *  `sound` is resolved by the caller from the final result, so a component
 *  that briefly renders an empty result cannot fire the wrong effect twice.
 */
export function useOutcomeSound(
  sessionId: string,
  outcome: 'win' | 'loss' | null | undefined,
  sound: SoundName,
): void {
  const played = useRef('');
  const session = useRef(sessionId);
  if (session.current !== sessionId) {
    session.current = sessionId;
    played.current = '';
  }
  useEffect(() => {
    if (!outcome) return;
    const key = `${sessionId}:${outcome}`;
    if (played.current === key) return;
    played.current = key;
    playSound(sound);
  }, [outcome, sessionId, sound]);
}

/** Convenience for games whose win/loss effects come from the catalogue map. */
export function useGameOutcomeSound(
  gameId: string,
  sessionId: string,
  outcome: 'win' | 'loss' | null | undefined,
): void {
  useOutcomeSound(sessionId, outcome, outcomeSound(gameId, outcome ?? 'loss'));
}

/** Reactive audio settings for the settings UI. */
export function useAudioSettings() {
  const [settings, setSettings] = useState(getAudioSettings);

  useEffect(() => subscribeAudioSettings(setSettings), []);

  return {
    muted: settings.muted,
    volume: settings.volume,
    setMuted: (next: boolean) => {
      storeMuted(next);
    },
    setVolume: (next: number) => {
      storeVolume(next);
    },
    /** Short confirmation so the user hears the new level immediately. */
    preview: () => {
      unlockAudio();
      playSound('uiTap');
    },
  };
}
