/**
 * Running Win My Matchup's simulations (ADR-110 §8): one lazy worker, one run at a time, and no
 * answer that belongs to an older question.
 *
 * * **One worker, created on first use.** It is a separate chunk: opening the panel does not
 *   fetch it, and the first *Simulate* does.
 * * **One run at a time.** A new run supersedes the pending one, which is cancelled. Cancelling
 *   terminates the worker — a simulation is synchronous inside it, so a message could not stop
 *   it — and the next run starts a fresh one.
 * * **Stale answers are dropped.** Every request carries an id; a response for any other id is
 *   ignored, and the caller also checks the run's fingerprint against its current inputs.
 * * **Without a worker** (no `Worker`, or one that fails to start), the same engine — loaded on
 *   demand, so the view's chunk carries no copy of it — runs on the main thread in slices of
 *   about 8 ms of work: draws in steps of 64, then the summary piece by piece, yielding to the
 *   browser whenever a slice's time is spent, so no slice is a long task even while the engine's
 *   code is still cold. Cancellation stops it at the next slice.
 */

import type { SimInput, SimResult } from "./matchup";
import type { MatchupRequest, MatchupResponse } from "./matchup.worker";

/** Main-thread work per slice in the fallback, in ms, and the draws between clock checks. */
export const FALLBACK_SLICE_MS = 8;
export const FALLBACK_STEP = 64;

export class CancelledError extends Error {
  constructor() {
    super("cancelled");
    this.name = "CancelledError";
  }
}

export interface RunOutcome {
  readonly result: SimResult;
  readonly ms: number;
  /** Where it ran: the worker, or the sliced main-thread fallback. */
  readonly where: "worker" | "main";
}

export interface RunHandle {
  readonly promise: Promise<RunOutcome>;
  readonly cancel: () => void;
}

interface Pending {
  readonly id: number;
  readonly input: SimInput;
  readonly resolve: (outcome: RunOutcome) => void;
  readonly reject: (error: Error) => void;
  cancelled: boolean;
}

type WorkerFactory = () => Worker;

function defaultFactory(): Worker {
  return new Worker(new URL("./matchup.worker.ts", import.meta.url), { type: "module", name: "win-my-matchup" });
}

function nextTick(): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, 0));
}

export class MatchupRunner {
  private worker: Worker | null = null;
  private pending: Pending | null = null;
  private nextId = 1;
  private broken = false;
  private readonly factory: WorkerFactory | null;

  constructor(factory: WorkerFactory | null = typeof Worker === "undefined" ? null : defaultFactory) {
    this.factory = factory;
  }

  /** Whether runs go to a worker (until one fails to start). */
  get usesWorker(): boolean {
    return this.factory !== null && !this.broken;
  }

  run(input: SimInput): RunHandle {
    this.cancel();
    const id = this.nextId;
    this.nextId += 1;
    let pending: Pending | null = null;
    const promise = new Promise<RunOutcome>((resolve, reject) => {
      pending = { id, input, resolve, reject, cancelled: false };
    });
    const entry = pending as unknown as Pending;
    this.pending = entry;
    if (this.usesWorker) this.post(entry);
    else void this.runOnMain(entry);
    return {
      promise,
      cancel: () => {
        if (this.pending === entry) this.cancel();
      },
    };
  }

  /** Stop the pending run, if any. The controls are free at once. */
  cancel(): void {
    const pending = this.pending;
    if (pending === null) return;
    pending.cancelled = true;
    this.pending = null;
    if (this.worker !== null) {
      this.worker.terminate();
      this.worker = null;
    }
    pending.reject(new CancelledError());
  }

  /** Release everything: on unmount and league switches. */
  dispose(): void {
    this.cancel();
    if (this.worker !== null) {
      this.worker.terminate();
      this.worker = null;
    }
  }

  private ensureWorker(): Worker | null {
    if (this.worker !== null) return this.worker;
    if (this.factory === null) return null;
    try {
      const worker = this.factory();
      worker.onmessage = (event: MessageEvent<MatchupResponse>) => {
        const pending = this.pending;
        const message = event.data;
        if (pending?.id !== message.id) return;
        this.pending = null;
        if (message.ok) pending.resolve({ result: message.result, ms: message.ms, where: "worker" });
        else pending.reject(new Error(message.error));
      };
      worker.onerror = (event) => {
        event.preventDefault();
        // A worker that cannot start or crashes: run the pending input on the main thread.
        this.broken = true;
        if (this.worker !== null) this.worker.terminate();
        this.worker = null;
        const pending = this.pending;
        if (pending !== null) void this.runOnMain(pending);
      };
      this.worker = worker;
      return worker;
    } catch {
      this.broken = true;
      return null;
    }
  }

  private post(pending: Pending): void {
    const worker = this.ensureWorker();
    if (worker === null) {
      void this.runOnMain(pending);
      return;
    }
    const request: MatchupRequest = { id: pending.id, input: pending.input };
    worker.postMessage(request);
  }

  private async runOnMain(pending: Pending): Promise<void> {
    const started = performance.now();
    try {
      // The engine loads on the main thread only when no worker can run it.
      const { createRun } = await import("./matchupEngine");
      if (pending.cancelled) return;
      const run = createRun(pending.input);
      let sliceStart = performance.now();
      // True when the slice's time is spent and, after yielding, the run was cancelled.
      const pause = async (): Promise<boolean> => {
        if (performance.now() - sliceStart < FALLBACK_SLICE_MS) return false;
        await nextTick();
        sliceStart = performance.now();
        return pending.cancelled;
      };
      while (!run.step(FALLBACK_STEP)) {
        if (await pause()) return;
      }
      const pieces = run.summarize();
      let piece = pieces.next();
      while (piece.done !== true) {
        if (await pause()) return;
        piece = pieces.next();
      }
      if (pending.cancelled || this.pending !== pending) return;
      this.pending = null;
      pending.resolve({ result: piece.value, ms: performance.now() - started, where: "main" });
    } catch (error) {
      if (this.pending === pending) this.pending = null;
      pending.reject(error instanceof Error ? error : new Error(String(error)));
    }
  }
}
