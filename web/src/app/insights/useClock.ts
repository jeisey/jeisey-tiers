/**
 * The reader's clock, to the minute, for withdrawing a start idea at kickoff (ADR-116).
 *
 * A test passes a fixed time; otherwise it ticks every 30 seconds so a story whose game starts
 * while the page is open is withdrawn without a reload, and memoised readings change at most once
 * a minute. The same hook as My Leagues' (`app/leagues/shared.ts`), deliberately copied: sharing
 * it would split it into a third chunk that My Leagues and Win My Matchup fetch too, and their
 * cold paths are the tightest budgets on the site.
 */

import { useEffect, useState } from "react";

export function useClock(fixed: Date | undefined): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (fixed !== undefined) return;
    const timer = setInterval(() => {
      setNow(Date.now());
    }, 30_000);
    return () => {
      clearInterval(timer);
    };
  }, [fixed]);
  const value = fixed?.getTime() ?? now;
  return Math.floor(value / 60_000) * 60_000;
}
