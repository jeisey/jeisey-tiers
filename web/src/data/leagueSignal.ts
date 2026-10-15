/**
 * The one fact about My Leagues the page shell needs (ADR-106): which preset the active saved
 * league uses, so the shell loads that block and scoring — and nothing else — while the
 * workspace is open.
 *
 * Deliberately tiny and storage-free: the saved-leagues store, its validation and its
 * migrations load with the lazy workspace, which publishes here whenever its active league
 * changes. Until it has (`undefined`), the shell does not guess a preset, so a cold link to
 * My Leagues never downloads a block the reader's league does not use.
 */

import type { ScoringValue, TeamCount } from "./state";

export interface ActiveLeaguePreset {
  readonly name: string;
  readonly scoring: ScoringValue;
  readonly teams: TeamCount;
  /** Rising Stars is switched on: its optional files may load. */
  readonly rising: boolean;
}

/** `undefined`: the workspace has not loaded yet. `null`: it has, and there is no league. */
let current: ActiveLeaguePreset | null | undefined;
const listeners = new Set<() => void>();

export function publishActiveLeague(next: ActiveLeaguePreset | null): void {
  const same =
    current === next ||
    (current !== undefined &&
      current !== null &&
      next !== null &&
      current.name === next.name &&
      current.scoring === next.scoring &&
      current.teams === next.teams &&
      current.rising === next.rising);
  if (same) return;
  current = next;
  for (const listener of listeners) listener();
}

/** Back to "the workspace has not loaded": for tests that mount the page more than once. */
export function forgetActiveLeague(): void {
  current = undefined;
}

export function activeLeagueSnapshot(): ActiveLeaguePreset | null | undefined {
  return current;
}

export function subscribeActiveLeague(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/**
 * Win My Matchup's YOLO mode (ADR-110 §6) is on for the open league: the shell may load the two
 * files it reads (the block's Opportunity rows and the role series). Published by the lazy
 * Win My Matchup panel while it is mounted with YOLO on, and cleared when it unmounts, so no
 * other view or league ever loads them on its behalf.
 */
let yoloFiles = false;
const yoloListeners = new Set<() => void>();

export function publishYoloFiles(on: boolean): void {
  if (yoloFiles === on) return;
  yoloFiles = on;
  for (const listener of yoloListeners) listener();
}

export function yoloFilesSnapshot(): boolean {
  return yoloFiles;
}

export function subscribeYoloFiles(listener: () => void): () => void {
  yoloListeners.add(listener);
  return () => {
    yoloListeners.delete(listener);
  };
}
