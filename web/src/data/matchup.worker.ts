/**
 * Win My Matchup's dedicated worker (ADR-110 §8): runs one `matchup_sim_v1` simulation per
 * request off the main thread and posts back its summary. It holds nothing between requests;
 * the page terminates it to cancel a run, and creates it only when a reader first simulates.
 */

import { createRun, type SimInput, type SimResult } from "./matchup";

export interface MatchupRequest {
  readonly id: number;
  readonly input: SimInput;
}

export type MatchupResponse =
  | { readonly id: number; readonly ok: true; readonly result: SimResult; readonly ms: number }
  | { readonly id: number; readonly ok: false; readonly error: string };

interface WorkerScope {
  onmessage: ((event: MessageEvent<MatchupRequest>) => void) | null;
  postMessage(message: MatchupResponse): void;
}

const scope = globalThis as unknown as WorkerScope;

scope.onmessage = (event) => {
  const { id, input } = event.data;
  const started = performance.now();
  try {
    const run = createRun(input);
    run.step(run.draws);
    scope.postMessage({ id, ok: true, result: run.result(), ms: performance.now() - started });
  } catch (error) {
    scope.postMessage({ id, ok: false, error: error instanceof Error ? error.message : String(error) });
  }
};
