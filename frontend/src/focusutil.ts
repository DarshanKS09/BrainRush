/** Pure helpers for the Focus Rush falling-shapes arcade (unit-tested). */
import type { FocusColor, FocusObject, FocusShape } from './api';

export interface LocalFocusObject extends FocusObject {
  /** True once this object reached the bottom locally; stops scoring it. */
  landed?: boolean;
}

export interface FocusConfigView {
  fall_ms: number;
  spawn_interval_ms: number;
  max_objects: number;
  target_change_ms: number;
  max_lives: number;
  colors?: string[];
  shapes?: string[];
}

/** Diameter of a falling shape in px (also used for the landing test). */
export const OBJECT_SIZE_PX = 48;

// The server sends ~2.5 s of scheduled spawns ahead, so one poll per second
// is enough to keep the play area fed without hammering the API.
export const FOCUS_POLL_MS = 900;

/** Server-clock offset from one response, using the midpoint of the request
 *  window. Using the receipt instant instead makes the client's clock lag the
 *  server by the response time, so shapes are drawn lower than the server
 *  thinks and vanish before the player sees them reach the bottom. */
export function clockOffsetFromSample(
  serverNowMs: number,
  sentAtMs: number,
  receivedAtMs: number,
): number {
  if (!Number.isFinite(serverNowMs) || serverNowMs <= 0) return 0;
  if (!Number.isFinite(sentAtMs) || sentAtMs <= 0) return 0;
  if (!Number.isFinite(receivedAtMs) || receivedAtMs < sentAtMs) return 0;
  return serverNowMs - Math.round((sentAtMs + receivedAtMs) / 2);
}

/** Fall progress 0..1 for one object at a server-clock instant. */
export function fallProgress(
  spawnedAtMs: number,
  fallMs: number,
  nowMs: number,
): number {
  if (!Number.isFinite(fallMs) || fallMs <= 0) return 1;
  const elapsed = nowMs - spawnedAtMs;
  if (!Number.isFinite(elapsed) || elapsed <= 0) return 0;
  return Math.min(1, elapsed / fallMs);
}

/** Vertical offset (px) inside the play area for a fall progress 0..1. */
export function objectTopPx(
  progress: number,
  areaHeightPx: number,
  sizePx: number = OBJECT_SIZE_PX,
): number {
  const p = Math.min(1, Math.max(0, progress));
  return -sizePx + p * (areaHeightPx + sizePx);
}

/** A shape is scoreable only while it is not stale and matches the target. */
export function isTargetObject(
  obj: Pick<FocusObject, 'color' | 'shape' | 'stale'>,
  target: { color: FocusColor; shape: FocusShape } | null | undefined,
): boolean {
  if (!target || obj.stale) return false;
  return obj.color === target.color && obj.shape === target.shape;
}

/** Replace the rendered set with the server's, keeping local landing state. */
export function mergeFallingObjects(
  previous: readonly LocalFocusObject[],
  incoming: readonly FocusObject[],
  tapped: ReadonlySet<string>,
): LocalFocusObject[] {
  const previousById = new Map(previous.map((o) => [o.id, o]));
  const merged: LocalFocusObject[] = [];
  for (const next of incoming) {
    if (tapped.has(next.id)) continue;
    const old = previousById.get(next.id);
    merged.push(old ? { ...next, landed: old.landed } : { ...next });
  }
  return merged;
}

export function accuracyText(percent: number): string {
  if (!Number.isFinite(percent)) return '0%';
  return `${Math.round(percent)}%`;
}

/** "2.4s fall · 460ms spawn · 5 colours" for the difficulty pill. */
export function difficultySummary(config: FocusConfigView | undefined | null): string {
  if (!config) return '';
  const fall = `${(config.fall_ms / 1000).toFixed(1)}s fall`;
  const spawn = `${config.spawn_interval_ms}ms spawn`;
  const colors = config.colors?.length;
  const palette = colors ? ` · ${colors} colours` : '';
  return `${fall} · ${spawn}${palette}`;
}

export function instructionFor(target: { color: string; shape: string }): string {
  return `TAP ${target.color.toUpperCase()} ${target.shape.toUpperCase()}S`;
}

export function shapeLabel(shape: string): string {
  return shape.charAt(0).toUpperCase() + shape.slice(1);
}

export const SHAPE_FILL: Record<FocusColor, string> = {
  red: '#f43f5e',
  blue: '#38bdf8',
  green: '#34d399',
  yellow: '#fbbf24',
  purple: '#a78bfa',
};
