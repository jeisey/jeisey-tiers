/**
 * Improve's results (ADR-106): loaded with its engine only when the reader asks for upgrades.
 *
 * The run is synchronous and bounded (`improve_v1`), deferred one frame so "Searching…" paints
 * first, and memoised per league revision, block, build and clock minute — three entries at
 * most, one per saved league — so switching leagues and back re-runs nothing.
 */

import { useEffect, useState } from "react";

import { AvailabilityBadge, PositionTag } from "../../components/primitives";
import type { Availability } from "../../data/availability";
import type { Position, RosTierRecord } from "../../data/contracts";
import { formatSigned, formatValue } from "../../data/format";
import {
  IMPROVE_RULE_VERSION,
  WEEKLY_NEED_BELOW,
  improveRoster,
  type ImproveResult,
  type Need,
  type PackageIdea,
} from "../../data/improve";
import { PUBLISHED_STARTERS, type SavedLeague } from "../../data/leagueContract";
import type { WeekContext } from "../../data/lineup";
import { slotLongName } from "../../data/roster";
import type { DistributionRule } from "../../data/startsit";
import { percent, points } from "./shared";

const cache = new Map<string, ImproveResult>();
const CACHE_LIMIT = 3;

function remember(key: string, result: ImproveResult): void {
  cache.delete(key);
  cache.set(key, result);
  while (cache.size > CACHE_LIMIT) {
    const oldest = cache.keys().next().value;
    if (oldest === undefined) break;
    cache.delete(oldest);
  }
}

export function ImprovePanel({
  league,
  records,
  week,
  threshold,
  rule,
  availabilityOf,
  nameOf,
  onSelect,
  signature,
  presetLabel,
}: {
  readonly league: SavedLeague;
  readonly records: readonly RosTierRecord[];
  readonly week: WeekContext;
  readonly threshold: (position: Position) => number | null;
  readonly rule: DistributionRule;
  readonly availabilityOf: (playerId: string) => Availability;
  readonly nameOf: (playerId: string) => string;
  readonly onSelect: (playerId: string) => void;
  /** Everything the result depends on: league revision, block, build, clock minute. */
  readonly signature: string;
  /** "12-team Half PPR". */
  readonly presetLabel: string;
}): React.JSX.Element {
  const [result, setResult] = useState<{ key: string; value: ImproveResult } | null>(null);
  const [timing, setTiming] = useState<number | null>(null);
  // A league, block and minute already searched (this visit) is read back, not searched again.
  const known = result?.key === signature ? result.value : (cache.get(signature) ?? null);

  useEffect(() => {
    if (cache.has(signature)) return;
    const timer = setTimeout(() => {
      const started = performance.now();
      const value = improveRoster({ league, records, week, threshold, rule, availabilityFor: availabilityOf });
      const elapsed = performance.now() - started;
      if (typeof performance.measure === "function") {
        performance.measure("leagues-improve", { start: started, end: started + elapsed });
      }
      remember(signature, value);
      setTiming(elapsed);
      setResult({ key: signature, value });
    }, 0);
    return () => {
      clearTimeout(timer);
    };
  }, [signature, league, records, week, threshold, rule, availabilityOf]);

  if (known === null) {
    return (
      <p className="lg-help" role="status" aria-busy="true">
        Searching your roster, the published board and value-matched packages…
      </p>
    );
  }
  const value = known;
  return (
    <div className="lg-improve-result" role="region" aria-label="Upgrade ideas">
      <p className="lg-help">
        {`Weakness is slot-relative: a starter below a ${percent(WEEKLY_NEED_BELOW)} chance of a startable week at his position this week, or outside the rest-of-season starter line for a league your size (teams × your starters at that slot). Startable lines, rest-of-season ranks and values are from the published ${presetLabel} board.`}
        {value.customStarters &&
          ` That board assumes ${String(PUBLISHED_STARTERS.QB)} QB, ${String(PUBLISHED_STARTERS.RB)} RB, ${String(PUBLISHED_STARTERS.WR)} WR, ${String(PUBLISHED_STARTERS.TE)} TE and ${String(PUBLISHED_STARTERS.FLEX)} FLEX; your league's lineup differs, and nothing is recomputed for it.`}
      </p>
      {value.needs.length === 0 ? (
        <p className="lg-empty-need" role="status">
          No starting slot is below its line this week or for the rest of the season. Nothing to fix.
        </p>
      ) : (
        value.needs.map((need) => (
          <NeedBlock key={`${need.slot.group}:${String(need.slot.index)}`} need={need} league={league} nameOf={nameOf} availabilityOf={availabilityOf} onSelect={onSelect} />
        ))
      )}
      <p className="lg-help lg-improve-foot">
        {`Trade ideas are hypothetical and value-matched (expected rest-of-season value within ±${String(value.range)}%). Players off your roster may be owned by anyone in your league or by no one: ownership is unknown, and no idea is a claim that a manager will accept. ${String(value.evaluations)} package${value.evaluations === 1 ? "" : "s"} evaluated${value.truncated ? " — the search stopped at its limit" : ""}; rejected: ${String(value.rejected.capacity)} for roster room, ${String(value.rejected.hole)} for leaving a slot empty, ${String(value.rejected.new_need + value.rejected.no_gain)} for not fixing the need without another. ${IMPROVE_RULE_VERSION}`}
        {timing !== null && <span className="visually-hidden">{` Ran in ${String(Math.round(timing))} ms.`}</span>}
      </p>
    </div>
  );
}

function standingLine(need: Need["current"]): string {
  const week =
    need.chance === null
      ? "week unknown"
      : need.threshold === null
        ? `startable chance ${percent(need.chance)}`
        : `${percent(need.chance)} chance of ${points(need.threshold)}+ pts`;
  const position = need.ros?.position ?? "";
  const rank =
    need.id === null
      ? "empty"
      : need.rank === null
        ? "no published rest-of-season value"
        : need.slot.group === "FLEX"
          ? `#${String(need.rank)} among RB/WR/TE (line ${String(need.line)})`
          : `${position}${String(need.rank)} (line ${String(need.line)})`;
  return `This week: ${week} · rest of season: ${rank}`;
}

function NeedBlock({
  need,
  league,
  nameOf,
  availabilityOf,
  onSelect,
}: {
  readonly need: Need;
  readonly league: SavedLeague;
  readonly nameOf: (playerId: string) => string;
  readonly availabilityOf: (playerId: string) => Availability;
  readonly onSelect: (playerId: string) => void;
}): React.JSX.Element {
  const slot = slotLongName(need.slot, league.slots);
  const who = need.current.id === null ? "empty" : nameOf(need.current.id);
  return (
    <article className="lg-need" data-kind={need.kind}>
      <h4 className="lg-need-title">
        {`${slot}: ${who}`}
        <span className="lg-need-kind">{need.kind === "temporary" ? "This week" : "Roster need"}</span>
      </h4>
      <p className="lg-help">{standingLine(need.current)}</p>
      {need.benchUpgrade && need.best.id !== null && (
        <p className="lg-bench-upgrade">
          {`Bench first: start ${nameOf(need.best.id)} here (${percent(need.best.chance)} startable chance). Auto Start/Sit above makes this change.`}
        </p>
      )}
      {!need.remaining ? (
        <p className="lg-help">Your bench covers this slot; nothing external is needed.</p>
      ) : (
        <>
          {need.targets.length === 0 ? (
            <p className="lg-help">
              No player off your roster fits this slot and fixes it under the shared eligibility rules.
            </p>
          ) : (
            <div className="lg-targets">
              <h5 className="lg-subhead">Players who fit</h5>
              <ul className="lg-target-list">
                {need.targets.map((target) => (
                  <li key={target.record.player_id}>
                    <PositionTag position={target.record.position} />
                    <button type="button" className="player-name" onClick={() => { onSelect(target.record.player_id); }}>
                      {target.record.display_name}
                    </button>
                    <AvailabilityBadge availability={target.availability} />
                    <span className="lg-target-meta">
                      {`${target.record.team ?? "—"} · wk ${percent(target.chance)} · ROS ${target.record.position}${String(target.record.ros_position_rank)} · value ${formatValue(target.record.ros_expected_vorp)}`}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}
          {need.packages.length > 0 ? (
            <div className="lg-packages">
              <h5 className="lg-subhead">Trade ideas</h5>
              <ul className="lg-package-list">
                {need.packages.map((idea) => (
                  <PackageLine key={idea.key} idea={idea} league={league} nameOf={nameOf} availabilityOf={availabilityOf} />
                ))}
              </ul>
            </div>
          ) : (
            need.targets.length > 0 && (
              <p className="lg-help">
                No value-matched package from your roster fixes this slot without opening another hole or need.
              </p>
            )
          )}
        </>
      )}
    </article>
  );
}

function PackageLine({
  idea,
  league,
  nameOf,
  availabilityOf,
}: {
  readonly idea: PackageIdea;
  readonly league: SavedLeague;
  readonly nameOf: (playerId: string) => string;
  readonly availabilityOf: (playerId: string) => Availability;
}): React.JSX.Element {
  // Members by value, as the Trade tab lists them.
  const give = idea.outgoing.members.map((player) => player.record.display_name).join(" + ");
  const get = idea.incoming.members.map((player) => player.record.display_name).join(" + ");
  const gain = idea.after - idea.before;
  const approx = (approximate: boolean): string => (approximate ? "~" : "");
  return (
    <li className="lg-package">
      <p className="lg-package-head">
        <span>{`Give ${give}`}</span>
        <span aria-hidden="true"> → </span>
        <span className="visually-hidden">; </span>
        <span>{`receive ${get}`}</span>
      </p>
      <p className="lg-package-line">
        {`Median lineup ${points(idea.before)} → ${points(idea.after)} (${formatSigned(gain, 1)}; sum of individual medians, not a team median or win chance)`}
        {idea.affected.length > 0 &&
          ` · changes ${idea.affected
            .map((entry) => `${slotLongName(entry.slot, league.slots)} ${entry.from === null ? "—" : nameOf(entry.from)} → ${entry.to === null ? "—" : nameOf(entry.to)}`)
            .join("; ")}`}
      </p>
      <p className="lg-package-line">
        {`Rest-of-season value: give ${formatValue(idea.outgoing.value)} (${approx(idea.outgoing.approximate)}${formatValue(idea.outgoing.p10)}–${approx(idea.outgoing.approximate)}${formatValue(idea.outgoing.p90)}) · receive ${formatValue(idea.incoming.value)} (${approx(idea.incoming.approximate)}${formatValue(idea.incoming.p10)}–${approx(idea.incoming.approximate)}${formatValue(idea.incoming.p90)})`}
        {` · starters below the startable line this week ${String(idea.weeklyNeedsBefore)} → ${String(idea.weeklyNeedsAfter)}, outside their rest-of-season line ${String(idea.rosterNeedsBefore)} → ${String(idea.rosterNeedsAfter)}`}
      </p>
      {(idea.notes.length > 0 || idea.warnings.length > 0) && (
        <p className="lg-help">
          {[...idea.notes, ...idea.warnings.map((warning) => `Outgoing ${warning}.`)].join(" ")}
          {idea.get.map((player) => availabilityOf(player.id)).some((reading) => reading.short !== null) && " Check incoming availability badges on their cards."}
        </p>
      )}
      {(idea.outgoing.approximate || idea.incoming.approximate) && (
        <p className="lg-help">~ A two-player floor and ceiling is the Trade tab's approximation, not a published number.</p>
      )}
    </li>
  );
}
