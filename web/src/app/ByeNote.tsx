/**
 * What the bye filter did to a board (ADR-115), in one line with the way back.
 *
 * The ROS and Start/Sit boards print this above their table when the filter hid anyone, when
 * it hid everyone a search matched, and when a link asked for it on a build that cannot apply
 * it. Ranks are never renumbered, so a hidden player leaves a gap this line explains.
 */

import type { ByeSchedule } from "../data/bye";

export function ByeNote({
  on,
  hidden,
  week,
  schedule,
  search,
  empty,
  onShow,
}: {
  readonly on: boolean;
  readonly hidden: number;
  readonly week: number | null;
  /** Null on a board whose rule needs no schedule (Start/Sit reads its own records). */
  readonly schedule: ByeSchedule | null;
  readonly search: string;
  /** The filter left nothing to show. */
  readonly empty: boolean;
  readonly onShow: () => void;
}): React.JSX.Element | null {
  if (!on) return null;
  if (schedule?.kind === "unavailable") {
    return (
      <p className="availability-note bye-note" role="note" data-bye="unavailable">
        {`Bye filter unavailable: ${schedule.reason}. Every player is shown.`}
      </p>
    );
  }
  if (hidden === 0) return null;
  const which = week === null ? "bye-week" : `week ${String(week)} bye`;
  const players = `${String(hidden)} ${which} player${hidden === 1 ? "" : "s"}`;
  return (
    <p className="availability-note bye-note" role="note" data-bye="hidden">
      {empty && search.trim() !== ""
        ? `“${search.trim()}” matches only ${players}, hidden by the bye filter.`
        : `${players} hidden.`}{" "}
      <button type="button" className="button" onClick={onShow}>
        Show bye-week players
      </button>
    </p>
  );
}
