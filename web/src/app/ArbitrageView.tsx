/**
 * The Arbitrage board: the market condition, the Draft Rail, the table, the export.
 *
 * The condition panel is the reason this view exists in this shape. A confidence label beside
 * a player's name reads as "the model is unsure about him" unless something says otherwise,
 * and that is the opposite of what the field means (ADR-041), so the meaning is stated once
 * here rather than on every row and every card.
 *
 * Everything in the panel is derived. At launch every published row read `low` for one
 * recorded reason and the panel said so; the same frozen rule later cleared its own bar and
 * the board became mostly `medium` with a handful of `low` rows, and the panel says that
 * instead — with no code change, because `marketHeadline` reports whatever the rows carry
 * (ADR-045, ADR-052). The full rubric, the cohort filters and the trend rule live once in
 * Data; what is here is the minimum needed to stop a number being misread.
 */

import { useMemo, useRef } from "react";

import { DraftRail } from "../charts/DraftRail";
import { Notice } from "../components/primitives";
import { arbitrageRowsToCsv } from "../data/csv";
import { formatEastern, formatInteger } from "../data/format";
import {
  explainClause,
  marketHeadline,
  marketSourceLabel,
  summarizeMarket,
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
  onOpenData,
}: {
  readonly index: ArtifactIndex;
  readonly state: AppState;
  readonly onChange: (next: Partial<AppState>) => void;
  readonly onSelect: (playerId: string) => void;
  readonly selectedPlayerId: string | null;
  readonly buildDate: string;
  readonly available: boolean;
  readonly onOpenData?: (() => void) | undefined;
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
      <MarketConditionNotice summary={summary} onOpenData={onOpenData} />

      <section className="section" aria-labelledby="draft-rail-heading">
        <div className="section-head">
          <h2 id="draft-rail-heading">Draft rail</h2>
          <p className="section-note">
            {`${METHOD_LABEL}: fair rank against ${marketSourceLabel(summary.sourceId)}. The bar is the signed difference in picks — not points, not dollars and not a probability.`}
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
          <span className="legend-item">
            <span className="legend-bar" data-kind="bargain" /> right of centre — the market
            drafts him <strong>later</strong> than his fair rank (a bargain)
          </span>
          <span className="legend-item">
            <span className="legend-bar" data-kind="premium" /> left of centre — the market
            drafts him <strong>earlier</strong> (a premium)
          </span>
          <span className="legend-item">▸ beyond the scale; the exact gap is on the row</span>
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
 * The market condition, in one line plus the evidence behind it.
 *
 * Every value printed here is read from the build: the label distribution over the rows in
 * scope, the cohort id, the clauses the cohort failed (when it failed any), the snapshot
 * time, the per-player median sample size. Nothing is a literal, and there is no branch that
 * assumes a particular condition — a `low` board, a `medium` board, a mixed board and a board
 * with no trend history all render from the same code.
 */
export function MarketConditionNotice({
  summary,
  onOpenData,
}: {
  readonly summary: ReturnType<typeof summarizeMarket>;
  readonly onOpenData?: (() => void) | undefined;
}): React.JSX.Element | null {
  const headline = marketHeadline(summary);
  if (headline === null) return null;
  const { assignment } = summary;
  const clauses = assignment?.failedClauses ?? [];

  return (
    <div className="notice market-condition" data-severity={headline.tone}>
      <div className="market-condition-head">
        <strong>{headline.sentence}</strong>{" "}
        <span>
          That is how much draft evidence stands behind these prices — not a probability that a
          player is a bargain, and nothing about the projection beside it.
        </span>
      </div>
      <ul className="market-facts">
        <li>
          <span className="market-fact-label">Price</span>
          <span className="market-fact-value">
            {marketSourceLabel(summary.sourceId)}
            {assignment !== null && !assignment.exact && (
              <span className="market-fact-qualifier"> · approximate cohort</span>
            )}
          </span>
        </li>
        {assignment !== null && (
          <li>
            <span className="market-fact-label">Cohort</span>
            <span className="market-fact-value">
              <code>{assignment.cohortId}</code>
              <span className="market-fact-qualifier">
                {assignment.sufficient ? " · clears the frozen rule" : " · below the frozen bar"}
              </span>
            </span>
          </li>
        )}
        {summary.medianSampleSize !== null && (
          <li>
            <span className="market-fact-label">Median sample</span>
            <span className="market-fact-value">
              {`${formatInteger(summary.medianSampleSize)} drafts per player`}
            </span>
          </li>
        )}
        <li>
          <span className="market-fact-label">Trend</span>
          <span className="market-fact-value">
            {summary.trendAvailable ? "measured" : "collecting"}
            {summary.trendSnapshots !== null && (
              <span className="market-fact-qualifier">
                {` · ${formatInteger(summary.trendSnapshots)} snapshot${summary.trendSnapshots === 1 ? "" : "s"} in the window`}
              </span>
            )}
          </span>
        </li>
        {summary.snapshotAtUtc !== null && (
          <li>
            <span className="market-fact-label">Snapshot</span>
            <span className="market-fact-value">{formatEastern(summary.snapshotAtUtc)}</span>
          </li>
        )}
      </ul>
      {clauses.length > 0 && (
        <p className="market-condition-clauses">
          {`Under the frozen sufficiency rule, ${clauses.map(explainClause).join("; ")}.`}
        </p>
      )}
      {onOpenData !== undefined && (
        <button
          type="button"
          className="button-link"
          onClick={onOpenData}
        >
          How these are measured
        </button>
      )}
    </div>
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
