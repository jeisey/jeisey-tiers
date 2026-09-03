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
import { ConfidenceMeter, Notice, SectionHead } from "../components/primitives";
import { arbitrageRowsToCsv } from "../data/csv";
import { formatEastern, formatInteger } from "../data/format";
import {
  CONFIDENCE_SHORT,
  explainClause,
  marketHeadline,
  marketSourceLabel,
  summarizeMarket,
} from "../data/market";
import {
  CROSS_MARKET,
  comparisonFor,
  crossMarketAvailable,
  marketLabel,
  selectableMarkets,
  windowLabel,
  MARKET_SOURCES,
} from "../data/multimarket";
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

  // Which markets this build actually published, and which one is in force. A selection
  // naming a source the board does not carry falls back rather than rendering empty columns:
  // a shared link from a build with one more source must still open (roadmap 10.6).
  const records = useMemo(() => rows.map((row) => row.record), [rows]);
  const markets = useMemo(() => selectableMarkets(records), [records]);
  const showCross = useMemo(() => crossMarketAvailable(records), [records]);
  const options = useMemo(
    () => (showCross ? [...markets, CROSS_MARKET] : markets),
    [markets, showCross],
  );
  const market = options.includes(state.market)
    ? state.market
    : (options[0] ?? state.market);
  // The selected market's semantics, taken from the first row that carries them. Every row
  // in a block shares one cohort, so any row answers "what window is this, and does the
  // cohort actually observe a league size" - and the first one avoids a second pass.
  const marketMeta = useMemo(() => {
    const sample = records
      .map((record) => comparisonFor(record, market))
      .find((comparison) => comparison !== null);
    return sample == null
      ? null
      : {
          window: windowLabel(sample.aggregation_window_type, sample.aggregation_window_days),
          leagueSize: sample.league_size !== null,
        };
  }, [records, market]);

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

      {options.length > 1 && (
        <MarketSelector
          options={options}
          selected={market}
          onSelect={(next) => {
            onChange({ market: next });
          }}
          windowText={marketMeta?.window ?? ""}
          observed={marketMeta === null ? null : { leagueSize: marketMeta.leagueSize }}
        />
      )}

      <section className="section" aria-labelledby="draft-rail-heading">
        <SectionHead
          index="01"
          id="draft-rail-heading"
          title="Draft rail"
          note={`${METHOD_LABEL}: fair rank against ${options.length > 1 ? marketLabel(market) : marketSourceLabel(summary.sourceId)}. The bar is the signed difference in picks — not points, not dollars and not a probability.`}
        >
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
        </SectionHead>

        <DraftRail
          rows={railRows}
          onSelect={onSelect}
          selectedPlayerId={selectedPlayerId}
          market={market}
        />

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
        <SectionHead
          index="02"
          id="arbitrage-table-heading"
          title="Arbitrage table"
          note={
            "Every priced player, default order by arbitrage score. Sorting re-orders these " +
            "rows; every value is read from the arbitrage artifact."
          }
        >
          <ExportControls
            board="arbitrage"
            scoring={state.scoring}
            teams={state.teams}
            buildDate={buildDate}
            filteredCount={rows.length}
            buildFilteredCsv={() => arbitrageRowsToCsv(visibleRows.current)}
          />
        </SectionHead>

        {rows.length === 0 ? (
          <UnpricedEmptyState search={state.search} unpriced={unpriced} />
        ) : (
          <>
            <ArbitrageTable
              rows={rows}
              market={market}
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
 * The ADP market this board compares against.
 *
 * Deliberately a *choice* rather than a default blend. The sources measure different
 * populations over different windows — FFC's rolling week against MyFantasyLeague's whole
 * season — and silently averaging them would produce a number no capture contains
 * (Release 2 guardrail 2.3). The window and what the cohort actually observes are printed
 * beside the control, because "ADP" alone does not say which of these a reader is looking at.
 *
 * FantasyPros ECR is **not** here. It is a ranking, not a price, and it appears beside the
 * selected market on the row and the card instead of pretending to be another market.
 */
function MarketSelector({
  options,
  selected,
  onSelect,
  windowText,
  observed,
}: {
  readonly options: readonly string[];
  readonly selected: string;
  readonly onSelect: (next: string) => void;
  readonly windowText: string;
  readonly observed: { readonly leagueSize: boolean } | null;
}): React.JSX.Element {
  // The per-source description reaches the reader through the radio's accessible name rather
  // than through a paragraph. On a phone this control sits directly between the reader and
  // the board, and a sentence here costs more than it explains — `Data` carries the full
  // description of every source.
  const describe = (option: string): string =>
    option === CROSS_MARKET
      ? "Every published ADP source side by side, with the spread between them"
      : (MARKET_SOURCES[option]?.description ?? "");
  return (
    /*
     * A control, not a section. It was a numbered `SectionHead` with its own explanatory
     * paragraph, which on a phone pushed the board itself below the fold — a regression that
     * only appears once a build publishes more than one market, because the selector does not
     * render at all below two. No fixture had two until ADR-067, so nothing caught it.
     *
     * Now it reads like Scoring and Teams do: a label, the choices, and one line of context.
     */
    <section className="market-control" aria-labelledby="market-selector-heading">
      <div className="control">
        <span className="control-label" id="market-selector-heading">
          Market
        </span>
        <div className="segmented" role="radiogroup" aria-label="ADP market">
          {options.map((option) => (
            <button
              key={option}
              type="button"
              role="radio"
              aria-checked={selected === option}
              tabIndex={selected === option ? 0 : -1}
              onClick={() => {
                onSelect(option);
              }}
            >
              <span className="visually-hidden">{describe(option)}</span>
              <span aria-hidden="true">{marketLabel(option)}</span>
            </button>
          ))}
        </div>
      </div>
      {/*
        One line, because it sits between the reader and the board on a phone. What survives
        is the part that changes what the number *means*: the window a seven-day ADP and a
        season-cumulative one are not the same quantity, and whether league size was observed
        at all. The fuller methodology is in Data, which is where a reader goes for it.
      */}
      <p className="market-control-note">
        {windowText !== "" && <>{windowText}</>}
        {observed !== null && (
          <>
            {windowText !== "" && " · "}
            {observed.leagueSize ? "league size observed" : "league size not observed"}
          </>
        )}
      </p>
    </section>
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
  // The one label when the board is uniform, the most common one when it is mixed. Whatever
  // the rows carry — there is no branch here that assumes a condition (ADR-052).
  const level = summary.uniform ?? summary.dominant;

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
        {/* The design source's confidence meter, driven by whatever the rows carry: the one
            label when the board is uniform, the most common one when it is mixed. */}
        {level !== null && (
          <li>
            <span className="market-fact-label">
              {summary.uniform === null ? "Most common" : "Market data"}
            </span>
            <span className="market-fact-value">
              <ConfidenceMeter confidence={level} label={CONFIDENCE_SHORT[level]} />
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
