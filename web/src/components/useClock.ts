/**
 * The reader's clock, to the minute, for kickoff locks (ADR-106) and withdrawals (ADR-116).
 *
 * A test passes a fixed time; otherwise it ticks every 30 seconds so a game that starts while the
 * page is open locks — or a start idea is withdrawn — without a reload, and memoised readings
 * change at most once a minute.
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
