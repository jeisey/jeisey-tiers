/**
 * The Tiers board: chart, legend, table, export.
 *
 * The chart is drawn from the same rows the table renders, filtered identically. The only
 * difference between them is population: the table owns every published row, while the chart
 * defaults to the draft-relevant top of the board because 300 overlapping labels in one
 * viewport is not a legible chart. The switch is explicit, shareable and never changes a
 * value — a player shown in either place carries the artifact's own numbers.
 */

import { useMemo, useRef } from "react";

import { TierBoard, TIER_SOFT_EDGE_NOTE } from "../charts/TierBoard";
import { Notice } from "../components/primitives";
import { tierRowsToCsv } from "../data/csv";
import { groupByTier, type ArtifactIndex, type TierRow } from "../data/model";
import { selectTierRows } from "../data/model";
import { SCORING_LABELS, type AppState } from "../data/state";
import { ExportControls } from "./ExportControls";
import { TierTable } from "./TierTable";

/** How deep the default chart goes. The table below still holds the whole board. */
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

  return (
    <>
      <section className="section" aria-labelledby="tier-board-heading">
        <div className="section-head">
          <h2 id="tier-board-heading">Tier board</h2>
          <p className="section-note">{TIER_SOFT_EDGE_NOTE}</p>
          <div className="section-actions">
            <button
              type="button"
              className="button"
              aria-pressed={state.board === "full"}
              onClick={() => {
                onChange({ board: state.board === "full" ? "top" : "full" });
              }}
            >
              {state.board === "full"
                ? `Show top ${String(BOARD_PREVIEW_DEPTH)}`
                : `Show full board (${String(rows.length)})`}
            </button>
          </div>
        </div>

        <TierBoard
          groups={groups}
          onSelect={onSelect}
          selectedPlayerId={selectedPlayerId}
          scoringLabel={SCORING_LABELS[state.scoring]}
        />

        <div className="legend">
          {(["QB", "RB", "WR", "TE"] as const).map((position) => (
            <span className="legend-item" key={position}>
              <span className="legend-swatch" data-pos={position} />
              {position}
            </span>
          ))}
          <span className="legend-item">
            <span className="legend-rule" />
            P25–P75 simulated VORP; P10–P90 is in player detail
          </span>
          <span className="legend-item">
            Bands are tier groups; vertical position within one carries no meaning
          </span>
          {truncated && (
            <span className="legend-item muted">
              {`Charting the top ${String(charted.length)} of ${String(rows.length)}; the table below has every row.`}
            </span>
          )}
        </div>
      </section>

      <section className="section" aria-labelledby="tier-table-heading">
        <div className="section-head">
          <h2 id="tier-table-heading">Tier table</h2>
          <div className="section-actions">
            <ExportControls
              board="tiers"
              scoring={state.scoring}
              teams={state.teams}
              buildDate={buildDate}
              filteredCount={rows.length}
              buildFilteredCsv={() => tierRowsToCsv(visibleRows.current)}
            />
          </div>
        </div>

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
