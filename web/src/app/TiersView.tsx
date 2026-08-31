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
import { Notice, SectionHead } from "../components/primitives";
import { tierRowsToCsv } from "../data/csv";
import { groupByTier, type ArtifactIndex, type TierRow } from "../data/model";
import { selectTierRows } from "../data/model";
import { SCORING_LABELS, type AppState } from "../data/state";
import { ExportControls } from "./ExportControls";
import { TierTable } from "./TierTable";

/** How deep the default board goes. The table below still holds the whole board. */
export const BOARD_PREVIEW_DEPTH = 100;

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
  const truncated = charted.length < rows.length;

  const openTiers = useMemo(
    () => new Set(state.tiers ?? defaultOpenTiers(groups)),
    [groups, state.tiers],
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
            groups={groups}
            onSelect={onSelect}
            selectedPlayerId={selectedPlayerId}
            scoringLabel={SCORING_LABELS[state.scoring]}
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
