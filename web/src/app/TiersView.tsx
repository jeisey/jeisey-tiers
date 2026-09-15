/**
 * The Tiers board: board, legend, table, export.
 *
 * The board is drawn from the same rows the table renders, filtered identically. The only
 * difference between them is population: the table owns every published row, while the board
 * shows the draft-relevant top and lets the reader open the rest. The switch is explicit,
 * shareable and never changes a value — a player shown in either place carries the artifact's
 * own numbers.
 *
 * **Which tiers are open is state, not a preference.** It lives in the URL like every other
 * control, and it is resolved from the build rather than stored as a default: tier sizes come
 * out of the segmentation and change with every rebuild, so writing a fixed list into
 * `DEFAULT_STATE` would freeze one build's structure. `state.tiers === null` means "the board
 * chooses", and the first interaction writes an explicit set.
 */

import { useCallback, useMemo, useRef } from "react";

import { TierBoard, TIER_SOFT_EDGE_NOTE, defaultOpenTiers } from "../charts/TierBoard";
import type { BoardAxis, BoardGroup } from "../charts/boardModel";
import { Notice, SectionHead, StatusBadge } from "../components/primitives";
import { tierRowsToCsv } from "../data/csv";
import { formatRank, formatValue } from "../data/format";
import { groupByTier, type ArtifactIndex, type TierGroup, type TierRow } from "../data/model";
import { selectTierRows } from "../data/model";
import { SCORING_LABELS, type AppState } from "../data/state";
import { ExportControls } from "./ExportControls";
import { TierTable } from "./TierTable";

/** How deep the default board goes. The table below still holds the whole board. */
export const BOARD_PREVIEW_DEPTH = 100;

/**
 * The preseason board's own mark label.
 *
 * Every quantity in it is named `…VORP` with no qualifier, which on this board means a whole
 * season's simulated value. The rest-of-season board builds its own label with its own words
 * (`RosView`), because the two are different quantities and a shared sentence would be the
 * first place they got confused.
 */
function markLabel(row: TierRow, tierLabel: string): string {
  const record = row.record;
  return (
    `${record.display_name}, ${record.position}${String(record.position_rank)}` +
    `${record.team === null ? "" : `, ${record.team}`}, tier ${tierLabel}, ` +
    `fair rank ${formatRank(record.fair_rank)}, median simulated VORP ` +
    `${formatValue(record.p50_vorp)}, P25 to P75 ${formatValue(record.p25_vorp)} ` +
    `to ${formatValue(record.p75_vorp)}, P10 to P90 ${formatValue(record.p10_vorp)} ` +
    `to ${formatValue(record.p90_vorp)}`
  );
}

/** The preseason tier groups, as marks the board can draw. Nothing is recomputed. */
function toBoardGroups(groups: readonly TierGroup[]): readonly BoardGroup[] {
  return groups.map((group) => ({
    ordinal: group.ordinal,
    label: group.label,
    marks: group.rows.map((row) => ({
      playerId: row.record.player_id,
      rank: row.record.fair_rank,
      position: row.record.position,
      positionRank: row.record.position_rank,
      displayName: row.record.display_name,
      p10: row.record.p10_vorp,
      p25: row.record.p25_vorp,
      p50: row.record.p50_vorp,
      p75: row.record.p75_vorp,
      p90: row.record.p90_vorp,
      badges: <StatusBadge status={row.status} />,
      label: markLabel(row, group.label),
    })),
  }));
}

export function TiersView({
  index,
  state,
  onChange,
  onSelect,
  selectedPlayerId,
  buildDate,
}: {
  readonly index: ArtifactIndex;
  readonly state: AppState;
  readonly onChange: (next: Partial<AppState>) => void;
  readonly onSelect: (playerId: string) => void;
  readonly selectedPlayerId: string | null;
  readonly buildDate: string;
}): React.JSX.Element {
  const rows = useMemo(() => selectTierRows(index, state), [index, state]);
  const visibleRows = useRef<readonly TierRow[]>(rows);

  const charted = useMemo(
    () => (state.board === "full" ? rows : rows.slice(0, BOARD_PREVIEW_DEPTH)),
    [rows, state.board],
  );
  const groups = useMemo(() => groupByTier(charted), [charted]);
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
      if (next.has(ordinal)) {
        next.delete(ordinal);
      } else {
        next.add(ordinal);
      }
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

  const axis: BoardAxis = {
    title: "Median simulated VORP",
    unit: "Median",
    quantityShort: "VORP",
    note: "Rows in fair-rank order · P10–P90 is in player detail",
    summary:
      `${String(groups.length)} tier groups of ${SCORING_LABELS[state.scoring]} players. Each ` +
      "row shows the player's median simulated VORP and the P25 to P75 interval around it on " +
      "a shared scale. Tier bands overlap because exact tier edges are not statistically " +
      "stable. The table below carries the same values.",
  };

  return (
    <>
      <section className="section" aria-labelledby="tier-board-heading">
        <SectionHead index="01" id="tier-board-heading" title="Tier board" note={TIER_SOFT_EDGE_NOTE}>
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
              ? `Show top ${String(BOARD_PREVIEW_DEPTH)}`
              : `Show full board (${String(rows.length)})`}
          </button>
        </SectionHead>

        {groups.length === 0 ? (
          <Notice title="No players match.">
            {state.search === ""
              ? "This position filter returns nothing for the selected preset."
              : `No player on the ${SCORING_LABELS[state.scoring]} board matches “${state.search}”.`}
          </Notice>
        ) : (
          <TierBoard
            groups={boardGroups}
            axis={axis}
            onSelect={onSelect}
            selectedPlayerId={selectedPlayerId}
            openTiers={openTiers}
            onToggleTier={onToggleTier}
          />
        )}

        {/* The design source's legend strip: the four position marks, a vertical rule, then
            what the geometry means. */}
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
            P25–P75 simulated VORP; the mark is the median. P10–P90 is in player detail
          </span>
          <span className="legend-item">
            A tier&apos;s band is that tier&apos;s own P25–P75 span. Neighbouring bands overlap,
            because exact tier edges are soft
          </span>
          <span className="legend-item muted">
            {`${String(openCount)} of ${String(charted.length)} charted players are in open tiers`}
            {truncated &&
              `; charting the top ${String(charted.length)} of ${String(rows.length)}, and the table below has every row.`}
          </span>
        </div>
      </section>

      <section className="section" aria-labelledby="tier-table-heading">
        <SectionHead
          index="02"
          id="tier-table-heading"
          title="Tier table"
          note={
            "Fair rank is the published order — sorting re-orders these rows without changing " +
            "it. Every value is read from the tier artifact."
          }
        >
          <ExportControls
            board="tiers"
            scoring={state.scoring}
            teams={state.teams}
            buildDate={buildDate}
            filteredCount={rows.length}
            buildFilteredCsv={() => tierRowsToCsv(visibleRows.current)}
          />
        </SectionHead>

        {rows.length === 0 ? (
          <Notice title="No players match.">
            {state.search === ""
              ? "This position filter returns nothing for the selected preset."
              : `No player on the ${SCORING_LABELS[state.scoring]} board matches “${state.search}”.`}
          </Notice>
        ) : (
          <TierTable
            rows={rows}
            onSelect={onSelect}
            selectedPlayerId={selectedPlayerId}
            visibleRowsRef={visibleRows}
          />
        )}
      </section>
    </>
  );
}
