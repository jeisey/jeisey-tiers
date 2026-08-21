/**
 * The Arbitrage board: the shared market condition, the Draft Rail, the table, the export.
 *
 * The condition notice is the reason this view exists in this shape. At launch every one of
 * the 2,122 published rows reads `low` confidence for a single recorded reason, so rendering
 * 2,122 identical unexplained pills would be worse than useless — the label would read as
 * "the model is unsure about these players", which is the opposite of what it means. The
 * shared cause is explained once, here, in numbers pulled out of build metadata (ADR-041,
 * ADR-045).
 */

import { useMemo, useRef } from "react";

import { DraftRail } from "../charts/DraftRail";
import { Notice } from "../components/primitives";
import { arbitrageRowsToCsv } from "../data/csv";
import { formatEastern, formatInteger } from "../data/format";
import {
  CONFIDENCE_MEANING,
  CONFIDENCE_SHORT,
  explainClause,
  marketSourceLabel,
  summarizeMarket,
  TREND_UNAVAILABLE_EXPLANATION,
} from "../data/market";
import { selectArbitrageRows, unpricedMatches, type ArbitrageRow, type ArtifactIndex } from "../data/model";
import { RAIL_MODES, SCORING_TO_PRESET, type AppState, type RailMode } from "../data/state";
import { ExportControls } from "./ExportControls";
import { ArbitrageTable } from "./ArbitrageTable";

/** How many rails the chart draws. The table below still holds every priced row. */
export const RAIL_DEPTH = 30;

const RAIL_LABELS: Readonly<Record<RailMode, string>> = {
  bargains: "Bargains",
  premiums: "Premiums",
  all: "All",
};

export const METHOD_LABEL = "Deterministic market-gap baseline";

export function ArbitrageView({
  index,
  state,
  onChange,
  onSelect,
  selectedPlayerId,
  buildDate,
  available,
}: {
  readonly index: ArtifactIndex;
  readonly state: AppState;
  readonly onChange: (next: Partial<AppState>) => void;
  readonly onSelect: (playerId: string) => void;
  readonly selectedPlayerId: string | null;
  readonly buildDate: string;
  readonly available: boolean;
}): React.JSX.Element {
  const rows = useMemo(() => selectArbitrageRows(index, state), [index, state]);
  const visibleRows = useRef<readonly ArbitrageRow[]>(rows);
  const unpriced = useMemo(() => unpricedMatches(index, state), [index, state]);

  const summary = useMemo(
    () =>
      summarizeMarket(
        index.metadata,
        rows.map((row) => row.record),
        SCORING_TO_PRESET[state.scoring],
        state.teams,
      ),
    [index.metadata, rows, state.scoring, state.teams],
  );

  const railRows = useMemo(() => {
    const filtered =
      state.rail === "bargains"
        ? rows.filter((row) => row.record.rank_gap > 0)
        : state.rail === "premiums"
          ? rows.filter((row) => row.record.rank_gap < 0)
          : rows;
    // Bargains are already in descending arbitrage-score order; premiums read best worst-first,
    // which is ascending score.
    const ordered =
      state.rail === "premiums"
        ? [...filtered].sort((a, b) => a.record.arbitrage_score - b.record.arbitrage_score)
        : filtered;
    return ordered.slice(0, RAIL_DEPTH);
  }, [rows, state.rail]);

  if (!available) {
    return (
      <Notice severity="warning" title="Market comparison unavailable." role="status">
        The arbitrage artifact could not be loaded for this build, so there is nothing to compare
        fair rank against. The tier board is unaffected — its values never depend on market data.
      </Notice>
    );
  }

  return (
    <>
      <MarketConditionNotice summary={summary} />

      <section className="section" aria-labelledby="draft-rail-heading">
        <div className="section-head">
          <h2 id="draft-rail-heading">Draft rail</h2>
          <p className="section-note">
            {`${METHOD_LABEL}: fair rank against ${marketSourceLabel(summary.sourceId)}. No learned surplus model exists in V1, so a rail's length is picks — not points and not dollars.`}
          </p>
          <div className="section-actions">
            <div className="segmented" role="radiogroup" aria-label="Draft rail population">
              {RAIL_MODES.map((mode) => (
                <button
                  key={mode}
                  type="button"
                  role="radio"
                  aria-checked={state.rail === mode}
                  tabIndex={state.rail === mode ? 0 : -1}
                  onClick={() => {
                    onChange({ rail: mode });
                  }}
                >
                  {RAIL_LABELS[mode]}
                </button>
              ))}
            </div>
          </div>
        </div>

        <DraftRail rows={railRows} onSelect={onSelect} selectedPlayerId={selectedPlayerId} />

        <div className="legend">
          <span className="legend-item">◆ Fair rank (model)</span>
          <span className="legend-item">○ MyFantasyLeague ADP (market)</span>
          <span className="legend-item">
            → market drafts him later than fair rank (bargain); ← market drafts him earlier
            (premium)
          </span>
          {railRows.length < rows.length && (
            <span className="legend-item muted">
              {`Showing ${String(railRows.length)} of ${String(rows.length)} priced players; the table below has every row.`}
            </span>
          )}
        </div>
      </section>

      <section className="section" aria-labelledby="arbitrage-table-heading">
        <div className="section-head">
          <h2 id="arbitrage-table-heading">Arbitrage table</h2>
          <div className="section-actions">
            <ExportControls
              board="arbitrage"
              scoring={state.scoring}
              teams={state.teams}
              buildDate={buildDate}
              filteredCount={rows.length}
              buildFilteredCsv={() => arbitrageRowsToCsv(visibleRows.current)}
            />
          </div>
        </div>

        {rows.length === 0 ? (
          <UnpricedEmptyState search={state.search} unpriced={unpriced} />
        ) : (
          <>
            <ArbitrageTable
              rows={rows}
              onSelect={onSelect}
              selectedPlayerId={selectedPlayerId}
              visibleRowsRef={visibleRows}
            />
            {unpriced.length > 0 && (
              <p className="section-note" style={{ marginTop: "0.5rem" }}>
                {`${String(unpriced.length)} matching tier ${unpriced.length === 1 ? "player carries" : "players carry"} no current MyFantasyLeague ADP, so ${unpriced.length === 1 ? "he is" : "they are"} not on this board: ${unpriced.map((record) => record.display_name).join(", ")}.`}
              </p>
            )}
          </>
        )}
      </section>
    </>
  );
}

/**
 * The shared market condition.
 *
 * Everything printed here is read from the build: the cohort id, the clauses the cohort
 * failed, the snapshot time, the per-player median sample size computed over the rows in
 * scope. Nothing is a literal.
 */
export function MarketConditionNotice({
  summary,
}: {
  readonly summary: ReturnType<typeof summarizeMarket>;
}): React.JSX.Element | null {
  const { assignment, uniform } = summary;
  if (summary.rows === 0) return null;

  const clauses = assignment?.failedClauses ?? [];
  const uniformLow = uniform !== null && uniform !== "high";

  return (
    <>
      {uniformLow && (
        <Notice severity="warning" title={`Every row on this board reads ${CONFIDENCE_SHORT[uniform].toLowerCase()} market-data confidence.`}>
          {clauses.length > 0 ? (
            <>
              {`Under the frozen cohort rule, ${clauses.map(explainClause).join("; ")}. `}
            </>
          ) : (
            "The market cohort serving this preset did not clear the frozen sufficiency rule. "
          )}
          {summary.medianSampleSize !== null && (
            <>
              {`The direct per-player evidence is better than that label suggests: the median priced player here was selected in ${formatInteger(summary.medianSampleSize)} drafts. `}
            </>
          )}
          {CONFIDENCE_MEANING}
        </Notice>
      )}
      {/* Two further facts about the market, kept as one dense line rather than two more
          boxes: neither is an alarm, and stacking three panels above the chart would bury it. */}
      <p className="view-notes">
        {!summary.trendAvailable && (
          <>
            <strong>Trend collecting.</strong> {TREND_UNAVAILABLE_EXPLANATION}
            {summary.trendSnapshots !== null &&
              ` The store holds ${formatInteger(summary.trendSnapshots)} snapshot${summary.trendSnapshots === 1 ? "" : "s"} in the window.`}{" "}
          </>
        )}
        {assignment !== null && !assignment.exact && (
          <>
            <strong>Approximate cohort.</strong>{" "}
            {`${marketSourceLabel(summary.sourceId)} cannot filter drafts to this exact scoring and league size, so prices come from the ${assignment.cohortId} population (${assignment.sourceFormatDetail}).`}
            {assignment.scoringPreset !== "PPR" &&
              " That population is not scoring-specific, so this board is priced largely by PPR drafters."}
          </>
        )}
        {summary.snapshotAtUtc !== null && ` Snapshot taken ${formatEastern(summary.snapshotAtUtc)}.`}
      </p>
    </>
  );
}

function UnpricedEmptyState({
  search,
  unpriced,
}: {
  readonly search: string;
  readonly unpriced: readonly { display_name: string; fair_rank: number }[];
}): React.JSX.Element {
  if (unpriced.length > 0) {
    return (
      <div className="empty-state">
        <h3>On the tier board, but not priced</h3>
        <p>
          {unpriced.length === 1
            ? "This player has no current MyFantasyLeague ADP, so there is nothing to compare his fair rank against."
            : "These players have no current MyFantasyLeague ADP, so there is nothing to compare their fair ranks against."}{" "}
          They are fully ranked on the Tiers board.
        </p>
        <ul>
          {unpriced.map((record) => (
            <li key={record.display_name}>
              {record.display_name} — fair rank {record.fair_rank}
            </li>
          ))}
        </ul>
      </div>
    );
  }
  return (
    <div className="empty-state">
      <h3>No priced players match</h3>
      <p>
        {search === ""
          ? "No arbitrage rows exist for the current filters."
          : `Nothing on the arbitrage board matches “${search}”.`}
      </p>
    </div>
  );
}
