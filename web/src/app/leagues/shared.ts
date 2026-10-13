/**
 * Small helpers the My Leagues components share (ADR-106).
 */

import { useEffect, useState } from "react";

import type { WeeklyProjectionRecord } from "../../data/contracts";
import { EM_DASH } from "../../data/format";
import { MODE_LABELS } from "../../data/lineup";
import type { LineupMode } from "../../data/leagueContract";

/**
 * The reader's clock, to the minute, for kickoff locks. A test passes a fixed time; otherwise
 * it ticks every 30 seconds so a game that starts while the page is open locks without a
 * reload, and memoised readings change at most once a minute.
 */
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

const KICKOFF = new Intl.DateTimeFormat("en-US", {
  timeZone: "America/New_York",
  weekday: "short",
  hour: "numeric",
  minute: "2-digit",
});

/** `Sun 1:00 PM ET`: when in the week, in Eastern, as a schedule prints it. */
export function kickoffLabel(iso: string | null | undefined): string {
  if (iso === null || iso === undefined) return "kickoff not published";
  const parsed = Date.parse(iso);
  if (Number.isNaN(parsed)) return "kickoff not published";
  return `${KICKOFF.format(new Date(parsed))} ET`;
}

/** `@ MIA`, `vs MIA`, `vs MIA (neutral)`, or the bye. */
export function opponentLabel(record: WeeklyProjectionRecord): string {
  const game = record.game;
  if (game === null) return `Bye in week ${String(record.target_week)}`;
  if (game.neutral_site) return `vs ${game.opponent} (neutral)`;
  return `${game.home_away === "home" ? "vs" : "@"} ${game.opponent}`;
}

export function points(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return EM_DASH;
  return value.toFixed(digits);
}

export function percent(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return EM_DASH;
  return `${String(Math.round(value * 100))}%`;
}

/** "sum of 9 individual medians" — what a lineup total is, every time it is printed. */
export function sumLabel(mode: LineupMode, count: number): string {
  const noun = MODE_LABELS[mode].toLowerCase();
  const plural = noun === "median" ? "medians" : `${noun}s`;
  return `sum of ${String(count)} individual ${count === 1 ? noun : plural}`;
}
