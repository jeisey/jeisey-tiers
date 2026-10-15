/**
 * Running simulations (ADR-110 §8): one lazy worker, cancellation that terminates it, no answer
 * for an older question, a sliced main-thread fallback when the worker cannot run, and cleanup.
 */

import { afterEach, describe, expect, it, vi } from "vitest";

import { MATCHUP_ENGINE_VERSION, MATCHUP_SEED, type SimInput } from "../src/data/matchup";
import { simulateMatchup } from "../src/data/matchupEngine";
import { CancelledError, FALLBACK_STEP, MatchupRunner } from "../src/data/matchupClient";
import type { MatchupRequest, MatchupResponse } from "../src/data/matchup.worker";

function input(draws = 2048, value = 10): SimInput {
  const constant = (key: string, points: number) => ({ key, taus: [0, 0.5, 1], values: [points - 5, points, points + 5], game: null, team: key, position: "RB" });
  return {
    version: MATCHUP_ENGINE_VERSION,
    seed: MATCHUP_SEED,
    draws,
    players: [constant("a", value), constant("b", 9)],
    correlation: {},
    opponent: [{ group: "RB", player: 1, fixed: 0 }],
    variants: [{ id: "base", slots: [{ group: "RB", player: 0, fixed: 0 }], detail: true }],
  };
}

/** A worker double the test drives by hand. */
class FakeWorker {
  static created: FakeWorker[] = [];
  onmessage: ((event: MessageEvent<MatchupResponse>) => void) | null = null;
  onerror: ((event: ErrorEvent) => void) | null = null;
  readonly posted: MatchupRequest[] = [];
  terminated = false;
  constructor() {
    FakeWorker.created.push(this);
  }
  postMessage(message: MatchupRequest): void {
    this.posted.push(message);
  }
  terminate(): void {
    this.terminated = true;
  }
  /** Answer a request as the real worker would. */
  answer(request: MatchupRequest): void {
    this.onmessage?.({ data: { id: request.id, ok: true, result: simulateMatchup(request.input), ms: 1 } } as MessageEvent<MatchupResponse>);
  }
  fail(): void {
    this.onerror?.({ preventDefault: () => undefined } as unknown as ErrorEvent);
  }
}

function runnerWithFake(): MatchupRunner {
  FakeWorker.created = [];
  return new MatchupRunner(() => new FakeWorker() as unknown as Worker);
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("the worker client", () => {
  it("creates the worker only on the first run, and resolves with the engine's answer", async () => {
    const runner = runnerWithFake();
    expect(FakeWorker.created).toHaveLength(0);
    const handle = runner.run(input());
    const worker = FakeWorker.created[0];
    expect(worker).toBeDefined();
    if (worker === undefined) return;
    const request = worker.posted[0];
    if (request === undefined) throw new Error("nothing posted");
    worker.answer(request);
    const outcome = await handle.promise;
    expect(outcome.where).toBe("worker");
    expect(outcome.result).toEqual(simulateMatchup(input()));
  });

  it("a newer run cancels the older one, terminates its worker, and ignores its late answer", async () => {
    const runner = runnerWithFake();
    const first = runner.run(input());
    const firstWorker = FakeWorker.created[0];
    const second = runner.run(input(2048, 12));
    await expect(first.promise).rejects.toBeInstanceOf(CancelledError);
    expect(firstWorker?.terminated).toBe(true);
    const secondWorker = FakeWorker.created[1];
    if (firstWorker === undefined || secondWorker === undefined) throw new Error("workers");
    // The old worker's answer (if it ever came) belongs to an old id and is dropped.
    const stale = firstWorker.posted[0];
    if (stale !== undefined) secondWorker.onmessage?.({ data: { id: stale.id, ok: true, result: simulateMatchup(input()), ms: 1 } } as MessageEvent<MatchupResponse>);
    const request = secondWorker.posted[0];
    if (request === undefined) throw new Error("nothing posted");
    secondWorker.answer(request);
    const outcome = await second.promise;
    expect(outcome.result).toEqual(simulateMatchup(input(2048, 12)));
  });

  it("cancel frees the controls at once", async () => {
    const runner = runnerWithFake();
    const handle = runner.run(input());
    handle.cancel();
    await expect(handle.promise).rejects.toBeInstanceOf(CancelledError);
    expect(FakeWorker.created[0]?.terminated).toBe(true);
    // A cancelled handle's cancel is harmless, and the next run starts a fresh worker.
    handle.cancel();
    runner.run(input());
    expect(FakeWorker.created).toHaveLength(2);
  });

  it("falls back to the sliced main-thread run when the worker fails", async () => {
    const runner = runnerWithFake();
    const handle = runner.run(input());
    FakeWorker.created[0]?.fail();
    const outcome = await handle.promise;
    expect(outcome.where).toBe("main");
    expect(outcome.result).toEqual(simulateMatchup(input()));
    expect(runner.usesWorker).toBe(false);
  });

  it("runs on the main thread, in slices, without a Worker at all, and stops when cancelled", async () => {
    const runner = new MatchupRunner(null);
    const done = await runner.run(input(4096)).promise;
    expect(done.where).toBe("main");
    expect(done.result).toEqual(simulateMatchup(input(4096)));
    const cancelled = runner.run(input(65536));
    cancelled.cancel();
    await expect(cancelled.promise).rejects.toBeInstanceOf(CancelledError);
  });

  it("yields to the browser whenever a slice's time is spent, through the draws and the summary", async () => {
    // A clock on which every check finds the slice's 8 ms spent: the run yields at every step.
    let clock = 0;
    vi.spyOn(performance, "now").mockImplementation(() => (clock += 9));
    const timeout = vi.spyOn(globalThis, "setTimeout");
    const runner = new MatchupRunner(null);
    const done = await runner.run(input(2048)).promise;
    expect(done.result).toEqual(simulateMatchup(input(2048)));
    // At least one yield per 64-draw step, and more for the summary's pieces.
    expect(timeout.mock.calls.length).toBeGreaterThan(2048 / FALLBACK_STEP);
  });

  it("reports an input the engine refuses as an error, not a result", async () => {
    const runner = new MatchupRunner(null);
    await expect(runner.run({ ...input(), draws: 70_000 }).promise).rejects.toThrow(/draws/);
  });

  it("dispose terminates the worker", () => {
    const runner = runnerWithFake();
    void runner.run(input()).promise.catch(() => undefined);
    runner.dispose();
    expect(FakeWorker.created[0]?.terminated).toBe(true);
  });
});
