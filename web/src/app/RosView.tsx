/**
 * The ROS Tier Board: the in-season answer, in the draft board's own visual language.
 *
 * Reused deliberately rather than redesigned. Roadmap 12.4 asks for one product with two
 * modes, not two products, so the section rhythm, the numbered heads, the board, the legend
 * strip and the table are the ones the Tier Board established; what changes is the quantity
 * and the disclosures around it. The board itself is `charts/TierBoard`, handed marks built
 * from `ros_vorp_*` and an axis that says so in every string — the component never learns
 * which of the two boards it is drawing, which is what stops the two quantities meeting
 * (ADR-071).
 *
 * Four things this view is obliged to say, and says in text rather than by implication:
 *
 * 1. **This is rest-of-season value**, from an explicit cutoff week, and it is not the
 *    preseason fair rank. The heading, the caption and every column name carry it.
 * 2. **A tier is a band.** The boundary failed the frozen stability gate (ADR-074), so the
 *    board never draws an edge as a fact — the same treatment Release 1 gave preseason tiers.
 * 3. **No injury or practice-report information is used** (ADR-070, ADR-076). The sentence
 *    comes from the artifact, so the interface cannot drift from what the model actually did.
 * 4. **Ordering inside the long-absence cohort is weak**, measured and published, shown where
 *    those rows are rather than filed away in a methodology page.
 *
 * **How much of that is on screen before a click changed in ADR-085.** Phase 12 printed all
 * four as full paragraphs above the board, which on a laptop was most of the first screen
 * spent on caveats before a single number. The obligation is to *state* them, not to spend
 * the fold on them: the contractual sentence — the one about injury information — is the
 * always-visible summary, and the rest sits one disclosure open beneath it, in the DOM and in
 * the accessibility tree either way. Data carries the same statements in full (ADR-058).
 */

import { useCallback, useMemo, useRef } from "react";

import { TierBoard, defaultOpenTiers } from "../charts/TierBoard";
import type { BoardAxis, BoardGroup, BoardRankLane } from "../charts/boardModel";
import { formatSeasonRank, seasonAbsence } from "../data/actuals";
import { AvailabilityBadge, Notice, SectionHead } from "../components/primitives";
import { rosRowsToCsv } from "../data/csv";
import { formatRank, formatValue } from "../data/format";
import {
  groupRosByTier,
  longAbsenceLabel,
  rosRankDomain,
  selectRosRows,
  splitActionable,
  type InSeasonBundle,
  type RosRow,
  type RosTierGroup,
} from "../data/ros";
import { SCORING_LABELS, type AppState } from "../data/state";
import { ExportControls } from "./ExportControls";
import { LongAbsenceBadge } from "./RosTable";
import { RosTable } from "./RosTable";
import { seasonCaption } from "./SeasonColumns";

export const ROS_BAND_NOTE =
  "Rest-of-season tiers are bands, not lines. Membership reproduces across resamples; the " +
  "exact cut positions do not, so read a player near an edge as belonging to both.";

/** How deep the default board goes. The table below still holds every published row. */
export const ROS_BOARD_PREVIEW_DEPTH = 100;

/**
 * The rest-of-season board's own mark label.
 *
 * Every quantity in it is named `remaining`, because that is what it is. The preseason board
 * builds its own (`TiersView`): one shared sentence across the two would be the first place a
 * season total and what is left of one got read as the same number.
 */
function markLabel(row: RosRow, tierLabel: string): string {
  const record = row.record;
  return (
    `${record.display_name}, ${record.position}${String(record.ros_position_rank)}` +
    `${record.team === null ? "" : `, ${record.team}`}, rest-of-season tier ${tierLabel}, ` +
    `rest-of-season rank ${formatRank(record.ros_fair_rank)}, median simulated remaining ` +
    `VORP ${formatValue(record.ros_vorp_p50)}, P25 to P75 ${formatValue(record.ros_vorp_p25)} ` +
    `to ${formatValue(record.ros_vorp_p75)}, P10 to P90 ${formatValue(record.ros_vorp_p10)} ` +
    `to ${formatValue(record.ros_vorp_p90)}` +
    seasonLabel(row) +
    (record.long_absence ? `. ${longAbsenceLabel(record)}` : "") +
    (row.availability?.short != null ? `. ${row.availability.headline}` : "")
  );
}

/** The rank comparison in words, for the mark's accessible label (ADR-105). */
function seasonLabel(row: RosRow): string {
  const record = row.record;
  const season = row.season;
  const ros = `. Rest-of-season ${record.position}${String(record.ros_position_rank)}`;
  if (season === undefined) return ros;
  if (season.kind === "ranked") {
    return `${ros}, season to date ${formatSeasonRank(season)} by points scored`;
  }
  return `${ros}, no season rank: ${(seasonAbsence(season) ?? "").toLowerCase()}`;
}

/** The rest-of-season tier groups, as marks the board can draw. Nothing is recomputed. */
function toBoardGroups(groups: readonly RosTierGroup[]): readonly BoardGroup[] {
  return groups.map((group) => ({
    ordinal: group.ordinal,
    label: group.label,
    marks: group.rows.map((row) => ({
      playerId: row.record.player_id,
      rank: row.record.ros_fair_rank,
      position: row.record.position,
      positionRank: row.record.ros_position_rank,
      displayName: row.record.display_name,
      p10: row.record.ros_vorp_p10,
      p25: row.record.ros_vorp_p25,
      p50: row.record.ros_vorp_p50,
      p75: row.record.ros_vorp_p75,
      p90: row.record.ros_vorp_p90,
      badges: (
        <>
          <AvailabilityBadge availability={row.availability} />
          <LongAbsenceBadge row={row} />
        </>
      ),
      label: markLabel(row, group.label),
      ranks: {
        ros: row.record.ros_position_rank,
        season: row.season?.kind === "ranked" ? row.season.rank : null,
        seasonAbsence: row.season === undefined ? null : seasonAbsence(row.season),
      },
    })),
  }));
}

export function RosView({
  bundle,
  state,
  onChange,
  onSelect,
  selectedPlayerId,
}: {
  readonly bundle: InSeasonBundle;
  readonly state: AppState;
  readonly onChange: (next: Partial<AppState>) => void;
  readonly onSelect: (playerId: string) => void;
  readonly selectedPlayerId: string | null;
}): React.JSX.Element {
  const all = useMemo(() => selectRosRows(bundle, state), [bundle, state]);
  // ADR-101: the default ranking is actionable — a player whose season is over is held back
  // (and searchable, and one click away). Nothing is renumbered: ranks are the model's.
  const { shown: rows, held } = useMemo(
    () => splitActionable(all, state.unavailable, state.search),
    [all, state.unavailable, state.search],
  );
  const unavailableNow = useMemo(
    () => rows.filter((row) => row.availability?.horizon === "unavailable_now").length,
    [rows],
  );
  const seasonOverShown = useMemo(
    () => rows.filter((row) => row.availability?.horizon === "season_over").length,
    [rows],
  );
  const visibleRows = useRef<readonly RosRow[]>(rows);
  const metadata = bundle.metadata;
  const disclosures = metadata.disclosures;
  const flagged = useMemo(() => rows.filter((row) => row.record.long_absence).length, [rows]);
  const buildDate = metadata.generated_at_utc.slice(0, 10);

  const charted = useMemo(
    () => (state.board === "full" ? rows : rows.slice(0, ROS_BOARD_PREVIEW_DEPTH)),
    [rows, state.board],
  );
  const groups = useMemo(() => groupRosByTier(charted), [charted]);
  const boardGroups = useMemo(() => toBoardGroups(groups), [groups]);
  const truncated = charted.length < rows.length;

  const openTiers = useMemo(
    () => new Set(state.tiers ?? defaultOpenTiers(boardGroups)),
    [boardGroups, state.tiers],
  );
  const allOpen = groups.length > 0 && groups.every((group) => openTiers.has(group.ordinal));

  const onToggleTier = useCallback(
    (ordinal: number) => {
      const next = new Set(openTiers);
      if (next.has(ordinal)) next.delete(ordinal);
      else next.add(ordinal);
      onChange({ tiers: [...next].sort((a, b) => a - b) });
    },
    [onChange, openTiers],
  );

  const onToggleAll = useCallback(() => {
    onChange({ tiers: allOpen ? [] : groups.map((group) => group.ordinal) });
  }, [allOpen, groups, onChange]);

  const openCount = groups
    .filter((group) => openTiers.has(group.ordinal))
    .reduce((total, group) => total + group.rows.length, 0);
  /*
   * How many of the charted rows a band actually holds.
   *
   * Not `charted.length`: a surfaced row is published with a rest-of-season value and no tier
   * at all (`ros_tier` null), so `groupRosByTier` forms no band for it and the board draws it
   * nowhere. Counting the slice instead of the bands would print a denominator that includes
   * players who are not on the picture — the table below has them, and says so.
   */
  const banded = groups.reduce((total, group) => total + group.rows.length, 0);

  // ADR-105: the comparison lane's scale comes from the whole published block, so filtering,
  // searching or collapsing never moves a mark.
  const rankDomain = useMemo(() => rosRankDomain(bundle, state), [bundle, state]);
  const actualsUp = bundle.actualsAvailability.published;
  const rankLane: BoardRankLane = {
    domain: rankDomain,
    unit: "Pos rank",
    note:
      "Positional rank, log scale, 1 at the left: ■ rest of season, ▲ season to date by " +
      "points. Each player is ranked within his own position" +
      (state.position === "all" ? " — QB4 and RB4 are separate standings." : "."),
  };

  const axis: BoardAxis = {
    title: "Median simulated remaining VORP",
    unit: "Median",
    quantityShort: "remaining VORP",
    note: `Rows in rest-of-season rank order · through week ${String(metadata.through_week)}`,
    summary:
      `${String(groups.length)} rest-of-season tier bands of ${SCORING_LABELS[state.scoring]} ` +
      "players. Each row shows the player's median simulated remaining VORP and the P25 to " +
      "P75 interval around it on a shared scale. Tier bands overlap because exact tier edges " +
      "are not statistically stable. This is what is left of the season from a different " +
      "model with a different replacement baseline, never the preseason value of the same " +
      "shape. A second lane compares two positional ranks on their own scale: the square is " +
      "the rest-of-season rank and the triangle the season-to-date rank by points scored. " +
      "The table below carries the same values.",
  };

  return (
    <>
      <section className="section" aria-labelledby="ros-board-heading">
        <SectionHead
          index="01"
          id="ros-board-heading"
          title={`Rest of season — through week ${String(metadata.through_week)}`}
          note={
            `What is left of ${String(metadata.season)}, from weeks 1–` +
            `${String(metadata.through_week)}. Not the preseason board: another model, another ` +
            "horizon, another replacement baseline."
          }
        >
          <button type="button" className="button" onClick={onToggleAll}>
            {allOpen ? "Collapse all tiers" : "Expand all tiers"}
          </button>
          <button
            type="button"
            className="button chamfer"
            data-variant="primary"
            aria-pressed={state.board === "full"}
            onClick={() => {
              onChange({ board: state.board === "full" ? "top" : "full" });
            }}
          >
            {state.board === "full"
              ? `Show top ${String(ROS_BOARD_PREVIEW_DEPTH)}`
              : `Show full board (${String(rows.length)})`}
          </button>
        </SectionHead>

        {/*
          The disclosure block. Every sentence is rendered from the artifact rather than from
          constants in this file, so a build that changed what the model reads would change
          these sentences too — the interface cannot claim a property the model no longer has.

          The summary is the one ADR-076 requires to be stated: no injury or practice-report
          information. The rest opens beneath it rather than occupying the fold, and Data
          carries all of it again in full.
        */}
        <details className="notice disclosure" data-severity="info">
          <summary>
            <span className="disclosure-lede">
              <strong>What this estimate does and does not know.</strong>{" "}
              {disclosures.long_absence_statement}
            </span>
          </summary>
          <p>{disclosures.long_absence_ordering_weakness}</p>
          {disclosures.tier_boundary_statement !== undefined && (
            <p>{disclosures.tier_boundary_statement}</p>
          )}
          <p className="muted">
            {`${String(disclosures.long_absence_players)} player${
              disclosures.long_absence_players === 1 ? "" : "s"
            } on the published board carr${
              disclosures.long_absence_players === 1 ? "ies" : "y"
            } this flag; ${String(flagged)} ${flagged === 1 ? "is" : "are"} in the current view. `}
            A long absence here means: {disclosures.long_absence_definition}.
          </p>
        </details>

        {groups.length === 0 ? (
          <Notice title="No players match.">
            {state.search === ""
              ? "This position filter returns nothing for the selected preset."
              : `No player on the ${SCORING_LABELS[state.scoring]} rest-of-season board matches “${state.search}”.`}
          </Notice>
        ) : (
          <TierBoard
            groups={boardGroups}
            axis={axis}
            onSelect={onSelect}
            selectedPlayerId={selectedPlayerId}
            openTiers={openTiers}
            onToggleTier={onToggleTier}
            rankLane={rankLane}
          />
        )}

        <div className="legend">
          {(["QB", "RB", "WR", "TE"] as const).map((position) => (
            <span className="legend-item" key={position}>
              <span className="legend-swatch" data-pos={position} />
              {position}
            </span>
          ))}
          <span className="legend-sep" aria-hidden="true" />
          <span className="legend-item">
            <span className="legend-rule" />
            <span className="legend-tick" aria-hidden="true" />
            P25–P75 simulated remaining VORP; the tick is the median
          </span>
          <span className="legend-item" data-legend="rank-ros">
            <span className="rank-glyph" data-kind="ros" aria-hidden="true" />
            RoS positional rank
          </span>
          <span className="legend-item" data-legend="rank-season">
            <span className="rank-glyph" data-kind="season" aria-hidden="true" />
            {`Season positional rank by points, weeks 1–${String(metadata.through_week)}`}
            {!actualsUp && " (unavailable for this build)"}
          </span>
          <span className="legend-item">{ROS_BAND_NOTE}</span>
          <span className="legend-item muted">
            {`${String(openCount)} of ${String(banded)} charted players are in open bands`}
            {banded < charted.length &&
              `; ${String(charted.length - banded)} shown row${charted.length - banded === 1 ? " carries" : "s carry"} no tier and so no band`}
            {truncated &&
              `; charting the top ${String(charted.length)} of ${String(rows.length)}, and the table below has every row.`}
          </span>
        </div>

        {/* The build's own account of itself, below the picture it made — the UX spec's
            "compact context" row rather than a preamble to the board. */}
        <dl className="facts" style={{ marginTop: "0.75rem" }}>
          <div>
            <dt>Cutoff</dt>
            <dd>{`Through week ${String(metadata.through_week)} (${metadata.cutoff_rule_version})`}</dd>
          </div>
          <div>
            <dt>Season state</dt>
            <dd>{metadata.season_state.season_state.replace(/_/g, " ")}</dd>
          </div>
          <div>
            <dt>Model</dt>
            <dd>{metadata.ros_model_version}</dd>
          </div>
          <div>
            <dt>Replacement</dt>
            <dd>{metadata.simulation.replacement_rule.replace(/_/g, " ")}</dd>
          </div>
          <div>
            <dt>Draws</dt>
            <dd>
              {String(metadata.simulation.draws)}
              {metadata.simulation.convergence_gate === "fail" && " (declared fallback)"}
            </dd>
          </div>
          <div>
            <dt>Data complete through</dt>
            <dd>{`week ${String(metadata.source_freshness.available_through_week)}`}</dd>
          </div>
        </dl>
      </section>

      <section className="section" aria-labelledby="ros-table-heading">
        <SectionHead
          index="02"
          id="ros-table-heading"
          title="Rest-of-season table"
          note={
            "ROS rank is the model's published order — sorting re-orders these rows without " +
            "changing it, and it is not adjusted for injuries. Szn rank, Total pts and Avg " +
            "pts/g are what each player has actually scored so far. The mark beside a name is " +
            "the availability reading (ADR-101), which reached no model input."
          }
        >
          <ExportControls
            board="ros_tiers"
            scoring={state.scoring}
            teams={state.teams}
            buildDate={buildDate}
            throughWeek={metadata.through_week}
            filteredCount={rows.length}
            buildFilteredCsv={() => rosRowsToCsv(visibleRows.current)}
          />
        </SectionHead>

        <AvailabilityNote
          held={held.length}
          seasonOverShown={seasonOverShown}
          unavailableNow={unavailableNow}
          showing={state.unavailable}
          onToggle={() => {
            onChange({ unavailable: !state.unavailable });
          }}
        />

        {rows.length === 0 ? (
          <Notice title="No players match.">
            {state.search === ""
              ? "This position filter returns nothing for the selected preset."
              : `No player on the ${SCORING_LABELS[state.scoring]} rest-of-season board matches “${state.search}”.`}
          </Notice>
        ) : (
          <RosTable
            rows={rows}
            onSelect={onSelect}
            selectedPlayerId={selectedPlayerId}
            visibleRowsRef={visibleRows}
            seasonNote={seasonCaption(
              metadata.through_week,
              SCORING_LABELS[state.scoring],
              actualsUp ? null : bundle.actualsAvailability.reason,
            )}
          />
        )}
      </section>
    </>
  );
}

/**
 * What the availability policy did to this board (ADR-101), in one line with its switch.
 *
 * Ranks are the model's and are never renumbered, so a held-back player leaves a gap in the
 * ROS rank column; this line is where that gap is explained.
 */
function AvailabilityNote({
  held,
  seasonOverShown,
  unavailableNow,
  showing,
  onToggle,
}: {
  readonly held: number;
  readonly seasonOverShown: number;
  readonly unavailableNow: number;
  readonly showing: boolean;
  readonly onToggle: () => void;
}): React.JSX.Element | null {
  const hidden = held;
  const over = showing ? seasonOverShown : 0;
  if (hidden === 0 && over === 0 && unavailableNow === 0) return null;
  const parts: string[] = [];
  if (hidden > 0) {
    parts.push(
      `${String(hidden)} player${hidden === 1 ? " is" : "s are"} out for the season and held back from this ranking; ranks are the model's and are not renumbered, so ${hidden === 1 ? "his" : "their"} rank${hidden === 1 ? " is" : "s are"} skipped.`,
    );
  }
  if (over > 0) {
    parts.push(
      `${String(over)} player${over === 1 ? " is" : "s are"} out for the season and listed for inspection only — ${over === 1 ? "his value is" : "their values are"} the model's, which predates the news.`,
    );
  }
  if (unavailableNow > 0) {
    parts.push(
      `${String(unavailableNow)} on a reserve list or released stay listed and marked: unavailable now, return uncertain, value unchanged.`,
    );
  }
  return (
    <p className="availability-note" role="note">
      {parts.join(" ")}{" "}
      {(hidden > 0 || showing) && (
        <button type="button" className="button" aria-pressed={showing} onClick={onToggle}>
          {showing ? "Hide players out for the season" : "Show players out for the season"}
        </button>
      )}
    </p>
  );
}
