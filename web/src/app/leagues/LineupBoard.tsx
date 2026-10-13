/**
 * The saved roster, slot by slot, with this week's reading on each (ADR-106).
 *
 * Starters are grouped by position (QB, RB, WR, TE, FLEX), then the bench and IR. Each filled
 * slot prints one compact line — opponent, home or away, kickoff, floor / median / ceiling,
 * availability — and a disclosure with the rest: the game's lines, the position-specific
 * defense context, the startable chance against the published threshold, and "why this week"
 * (model attribution kept apart from the game-day context the model does not read). A bye is
 * said as a bye; the team's next game after it is not this week's matchup and is not shown.
 *
 * Rising Stars, when switched on, sit beside each starter group once — never repeated beside
 * every slot of it.
 */

import { useId, useState } from "react";

import { AvailabilityBadge, PositionTag } from "../../components/primitives";
import { WhyWeek } from "../../components/WhyWeek";
import type { RosWeeklyMetadata, WeeklyProjectionRecord } from "../../data/contracts";
import { EM_DASH, formatValue } from "../../data/format";
import {
  STARTER_GROUPS,
  SLOT_LABELS,
  type LineupMode,
  type SavedLeague,
  type SlotGroup,
} from "../../data/leagueContract";
import type { PlayerUniverse } from "../../data/leagueUniverse";
import type { PlayerWeek } from "../../data/lineup";
import type { RisingGroup, RisingSelection, RisingStar } from "../../data/rising";
import { slotLongName, slotName, type SlotRef } from "../../data/roster";
import { gridFromQuantiles, probAtLeast, quantileValues, type DistributionRule } from "../../data/startsit";
import { ordinal, type WhyThisWeek } from "../../data/whyweek";
import type { Availability } from "../../data/availability";
import { kickoffLabel, opponentLabel, percent, points } from "./shared";

const POSITION_PLURAL: Readonly<Record<string, string>> = { QB: "QBs", RB: "RBs", WR: "WRs", TE: "TEs" };

/** "3rd-most" or "5th-fewest": the side of the league it is on, as "why this week" says it. */
function defenseRank(rank: number, defenses: number): string {
  return rank <= defenses / 2 ? `${ordinal(rank)}-most` : `${ordinal(defenses + 1 - rank)}-fewest`;
}

export interface BoardReaders {
  readonly nameOf: (playerId: string) => string;
  readonly availabilityOf: (playerId: string) => Availability | null;
  readonly weekOf: (playerId: string) => PlayerWeek | null;
  readonly whyFor: (playerId: string) => WhyThisWeek | null;
  readonly threshold: (position: string) => number | null;
  readonly rule: DistributionRule;
  readonly teamOf: (playerId: string) => string | null;
  /** The slot's occupant and fitting bench players with a projection, for Start/Sit. */
  readonly compareFor: (slot: SlotRef) => readonly string[];
  readonly onCompare: (ids: readonly string[]) => void;
}

export function LineupBoard({
  league,
  universe,
  readers,
  mode,
  weekly,
  rising,
  onEditSlot,
  onSelect,
}: {
  readonly league: SavedLeague;
  readonly universe: PlayerUniverse;
  readonly readers: BoardReaders;
  readonly mode: LineupMode;
  readonly weekly: RosWeeklyMetadata | null;
  /** Rising Stars for this league, or null when it is switched off. */
  readonly rising: { readonly selection: RisingSelection | null; readonly status: string | null } | null;
  readonly onEditSlot: (slot: SlotRef) => void;
  readonly onSelect: (playerId: string) => void;
}): React.JSX.Element {
  const groups = STARTER_GROUPS.filter((group) => league.slots[group] > 0);
  return (
    <div className="lg-board" data-rising={rising !== null || undefined}>
      {groups.map((group) => (
        <GroupBlock
          key={group}
          group={group}
          league={league}
          universe={universe}
          readers={readers}
          mode={mode}
          weekly={weekly}
          rising={rising}
          onEditSlot={onEditSlot}
          onSelect={onSelect}
        />
      ))}
      <section className="lg-group lg-group-unsupported" aria-label="Team defense and kicker">
        <ul className="lg-slots">
          {(["DST", "K"] as const).map((label) => (
            <li key={label} className="lg-slot" data-state="unsupported">
              <span className="lg-slot-label">{label}</span>
              <span className="lg-slot-main lg-muted">Not supported — this site does not model team defense or kickers.</span>
            </li>
          ))}
        </ul>
      </section>
      {(["BN", "IR"] as const)
        .filter((group) => league.slots[group] > 0)
        .map((group) => (
          <GroupBlock
            key={group}
            group={group}
            league={league}
            universe={universe}
            readers={readers}
            mode={mode}
            weekly={weekly}
            rising={null}
            onEditSlot={onEditSlot}
            onSelect={onSelect}
          />
        ))}
    </div>
  );
}

function GroupBlock({
  group,
  league,
  universe,
  readers,
  mode,
  weekly,
  rising,
  onEditSlot,
  onSelect,
}: {
  readonly group: SlotGroup;
  readonly league: SavedLeague;
  readonly universe: PlayerUniverse;
  readonly readers: BoardReaders;
  readonly mode: LineupMode;
  readonly weekly: RosWeeklyMetadata | null;
  readonly rising: { readonly selection: RisingSelection | null; readonly status: string | null } | null;
  readonly onEditSlot: (slot: SlotRef) => void;
  readonly onSelect: (playerId: string) => void;
}): React.JSX.Element {
  const headingId = useId();
  const title =
    group === "BN" ? "Bench" : group === "IR" ? "Injured reserve (not started, not optimised)" : SLOT_LABELS[group];
  const risingGroup: RisingGroup | null = group === "BN" || group === "IR" ? null : group;
  return (
    <section className="lg-group" data-group={group} aria-labelledby={headingId}>
      <div className="lg-group-slots">
        <h3 id={headingId} className="lg-group-title">
          {title}
          {group === "FLEX" && <span className="lg-group-note"> · RB, WR or TE</span>}
        </h3>
        <ul className="lg-slots">
          {league.roster[group].map((id, index) => (
            <SlotRow
              key={`${group}:${String(index)}`}
              slot={{ group, index }}
              id={id}
              league={league}
              universe={universe}
              readers={readers}
              mode={mode}
              weekly={weekly}
              onEditSlot={onEditSlot}
              onSelect={onSelect}
            />
          ))}
        </ul>
      </div>
      {rising !== null && risingGroup !== null && (
        <RisingList group={risingGroup} rising={rising} onSelect={onSelect} />
      )}
    </section>
  );
}

function SlotRow({
  slot,
  id,
  league,
  universe,
  readers,
  mode,
  weekly,
  onEditSlot,
  onSelect,
}: {
  readonly slot: SlotRef;
  readonly id: string | null;
  readonly league: SavedLeague;
  readonly universe: PlayerUniverse;
  readonly readers: BoardReaders;
  readonly mode: LineupMode;
  readonly weekly: RosWeeklyMetadata | null;
  readonly onEditSlot: (slot: SlotRef) => void;
  readonly onSelect: (playerId: string) => void;
}): React.JSX.Element {
  const [open, setOpen] = useState(false);
  const detailId = useId();
  const short = slotName(slot, league.slots);
  const long = slotLongName(slot, league.slots);
  if (id === null) {
    return (
      <li className="lg-slot" data-state="empty">
        <span className="lg-slot-label" aria-hidden="true">{short}</span>
        <span className="lg-slot-main lg-muted">
          <span className="visually-hidden">{`${long}: `}</span>Empty
        </span>
        <span className="lg-slot-actions">
          <button
            type="button"
            className="button lg-edit"
            aria-label={`Add a player to ${long}`}
            onClick={() => {
              onEditSlot(slot);
            }}
          >
            Add
          </button>
        </span>
      </li>
    );
  }
  const player = universe.get(id);
  const name = readers.nameOf(id);
  const week = slot.group === "IR" ? null : readers.weekOf(id);
  const record = player?.weekly ?? null;
  const availability = readers.availabilityOf(id);
  const quantiles = record?.quantiles ?? null;
  const state = week?.kind ?? (player === null ? "unresolved" : slot.group === "IR" ? "ir" : "none");
  return (
    <li className="lg-slot" data-state={state} data-mode={mode}>
      <span className="lg-slot-label" aria-hidden="true">{short}</span>
      <span className="lg-slot-main">
        <span className="lg-slot-player">
          <span className="visually-hidden">{`${long}: `}</span>
          {player !== null && <PositionTag position={player.position} />}
          {player === null ? (
            <span className="lg-player-plain">{name}</span>
          ) : (
            <button
              type="button"
              className="player-name"
              onClick={() => {
                onSelect(id);
              }}
            >
              {name}
            </button>
          )}
          <span className="lg-team">{readers.teamOf(id) ?? EM_DASH}</span>
          <AvailabilityBadge availability={availability ?? undefined} />
          {player === null && <span className="lg-unresolved">Not in this build</span>}
        </span>
        <span className="lg-slot-week">
          {player === null ? (
            "No current data: kept as saved, matched by id on every visit."
          ) : record === null ? (
            "No weekly projection published."
          ) : (
            <>
              <span className="lg-game">
                {opponentLabel(record)}
                {record.game !== null && ` · ${kickoffLabel(record.game.kickoff_utc)}`}
              </span>
              {quantiles !== null ? (
                <span className="lg-quantiles" title="Floor (P10) · median (P50) · ceiling (P90), points given that he plays">
                  <span className="visually-hidden">Floor, median, ceiling: </span>
                  <span data-active={mode === "q10" || undefined}>{points(quantiles.q10)}</span>
                  <span aria-hidden="true"> · </span>
                  <strong data-active={mode === "q50" || undefined}>{points(quantiles.q50)}</strong>
                  <span aria-hidden="true"> · </span>
                  <span data-active={mode === "q90" || undefined}>{points(quantiles.q90)}</span>
                </span>
              ) : record.game_state === "lines_pending" ? (
                <span className="lg-muted">no line yet</span>
              ) : null}
            </>
          )}
        </span>
        {/* A bye is already the game line; every other reason is said once, here. */}
        {week?.reason != null && record?.game !== null && (
          <span className="lg-slot-status" data-kind={week.kind}>
            {week.reason}
          </span>
        )}
      </span>
      <span className="lg-slot-actions">
        <button
          type="button"
          className="button lg-edit"
          aria-label={`Edit ${long}: ${name}`}
          onClick={() => {
            onEditSlot(slot);
          }}
        >
          Edit
        </button>
        {player !== null && (
          <button
            type="button"
            className="button lg-more"
            aria-expanded={open}
            aria-controls={detailId}
            aria-label={`${open ? "Hide" : "Show"} ${name}'s week`}
            onClick={() => {
              setOpen((value) => !value);
            }}
          >
            {open ? "Hide" : "Week"}
          </button>
        )}
      </span>
      {player !== null && (
        <div id={detailId} className="lg-slot-detail" hidden={!open}>
          {open && (
            <SlotDetail
              id={id}
              slot={slot}
              group={slot.group}
              name={name}
              readers={readers}
              record={record}
              weekly={weekly}
              availability={availability}
              rosRank={player.ros?.ros_position_rank ?? null}
              position={player.position}
            />
          )}
        </div>
      )}
    </li>
  );
}

function SlotDetail({
  id,
  slot,
  group,
  name,
  readers,
  record,
  weekly,
  availability,
  rosRank,
  position,
}: {
  readonly id: string;
  readonly slot: SlotRef;
  readonly group: SlotGroup;
  readonly name: string;
  readonly readers: BoardReaders;
  readonly record: WeeklyProjectionRecord | null;
  readonly weekly: RosWeeklyMetadata | null;
  readonly availability: Availability | null;
  readonly rosRank: number | null;
  readonly position: string;
}): React.JSX.Element {
  if (record === null) {
    return (
      <p className="lg-help">
        {`No week-${String(weekly?.target_week ?? "")} projection is published for ${name}, so there is no matchup to read. His card has everything this build publishes.`}
      </p>
    );
  }
  const game = record.game;
  const quantiles = quantileValues(record);
  const threshold = readers.threshold(position);
  const chance =
    quantiles === null || threshold === null ? null : probAtLeast(gridFromQuantiles(quantiles, readers.rule), threshold);
  const opponent = record.opponent;
  const why = group === "IR" ? null : readers.whyFor(id);
  const compare = readers.compareFor(slot);
  return (
    <div className="lg-detail">
      <dl className="lg-facts">
        <div>
          <dt>Week {record.target_week}</dt>
          <dd>
            {game === null
              ? "Bye — he does not play this week."
              : `${opponentLabel(record)} · ${game.neutral_site ? "neutral site" : game.home_away === "home" ? "home" : "away"} · ${kickoffLabel(game.kickoff_utc)}`}
          </dd>
        </div>
        {game !== null && (
          <div>
            <dt>Lines</dt>
            <dd>
              {game.total_line === null
                ? "No line posted yet."
                : `Total ${formatValue(game.total_line)} · team implied ${formatValue(game.team_points)} pts`}
            </dd>
          </div>
        )}
        <div>
          <dt>Floor · median · ceiling</dt>
          <dd>
            {record.quantiles === null
              ? "No distribution published."
              : `${points(record.quantiles.q10)} · ${points(record.quantiles.q50)} · ${points(record.quantiles.q90)} pts, given that he plays`}
          </dd>
        </div>
        <div>
          <dt>Startable week</dt>
          <dd>
            {chance === null || threshold === null
              ? EM_DASH
              : `${percent(chance)} chance of ${points(threshold)}+ pts (the last starter at ${position} in a typical week, published preset)`}
          </dd>
        </div>
        {opponent?.rank != null && (
          <div>
            <dt>{`Defense vs ${POSITION_PLURAL[position] ?? position}`}</dt>
            <dd>
              {`${opponent.defense} allows ${formatValue(opponent.allowed_ppg)} pts a game to ${POSITION_PLURAL[position] ?? position} (league ${formatValue(opponent.league_ppg)}): the ${defenseRank(opponent.rank, opponent.defenses ?? 32)} of ${String(opponent.defenses ?? 32)}, over ${String(opponent.games ?? 0)} games.`}
            </dd>
          </div>
        )}
        <div>
          <dt>Availability</dt>
          <dd>{availability === null ? "No status record." : `${availability.headline}. ${availability.detail}`}</dd>
        </div>
        {rosRank !== null && (
          <div>
            <dt>Rest of season</dt>
            <dd>{`${position}${String(rosRank)} on the published board`}</dd>
          </div>
        )}
      </dl>
      {compare.length >= 2 && (
        <p>
          <button
            type="button"
            className="button-link"
            onClick={() => {
              readers.onCompare(compare);
            }}
          >
            {`Compare ${name} with ${String(compare.length - 1)} bench option${compare.length === 2 ? "" : "s"} in Start/Sit`}
          </button>
        </p>
      )}
      {why !== null && (
        <>
          <h4 className="lg-detail-title">Why this week</h4>
          <WhyWeek why={why} name={name} statement={weekly?.explanation?.statement} />
        </>
      )}
    </div>
  );
}

function RisingList({
  group,
  rising,
  onSelect,
}: {
  readonly group: RisingGroup;
  readonly rising: { readonly selection: RisingSelection | null; readonly status: string | null };
  readonly onSelect: (playerId: string) => void;
}): React.JSX.Element {
  const headingId = useId();
  const selection = rising.selection;
  const stars: readonly RisingStar[] = selection?.kind === "ready" ? selection.groups[group] : [];
  return (
    <aside className="lg-rising" aria-labelledby={headingId}>
      <h4 id={headingId} className="lg-rising-title">
        {`Rising ${group === "FLEX" ? "RB/WR/TE" : group}`}
      </h4>
      {selection === null ? (
        <p className="lg-help">{rising.status ?? "Loading…"}</p>
      ) : selection.kind === "unavailable" ? (
        <p className="lg-help">Not available on this build.</p>
      ) : stars.length === 0 ? (
        <p className="lg-help">
          None right now<span className="visually-hidden">: nobody off your roster has both a rising role and rising adds</span>.
        </p>
      ) : (
        <ol className="lg-rising-list">
          {stars.map((star) => (
            <li key={star.record.player_id}>
              <span className="lg-rising-name">
                <PositionTag position={star.record.position} />
                <button
                  type="button"
                  className="player-name"
                  onClick={() => {
                    onSelect(star.record.player_id);
                  }}
                >
                  {star.record.display_name}
                </button>
                <AvailabilityBadge availability={star.availability} />
              </span>
              <span className="lg-rising-role" title={star.role.sentence}>
                {`${star.role.metric} ${star.role.change ?? EM_DASH}`}
                <span className="lg-rising-window">{` ${star.role.detail}`}</span>
              </span>
              <span className="lg-rising-adds" title={star.momentum.sentence}>
                {`Adds ${star.momentum.value}`}
                <span className="lg-rising-window">{` ${star.momentum.span}`}</span>
              </span>
              {!star.projected && <span className="lg-rising-note">No model projection</span>}
              <span className="visually-hidden">{`${star.role.sentence} ${star.momentum.sentence}`}</span>
            </li>
          ))}
        </ol>
      )}
    </aside>
  );
}

