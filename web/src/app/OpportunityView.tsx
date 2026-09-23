/**
 * The Opportunity Board: rest-of-season value beside what managers are actually doing.
 *
 * The draft-season question was "where does the market disagree with the model?", answered
 * against a price. In November there is no price, so the question changes rather than the
 * answer being faked: **who is worth holding, and who is the wire moving on?**
 *
 * Three rules govern every line here, and they are all about not inventing a quantity:
 *
 * *An add count is not an ADP.* It is a number of transactions inside a declared window. The
 * column says "Adds (24h)" with the window from the artifact, never "ADP" and never "rank".
 *
 * *There is no combined score.* The board offers five orderings — rest-of-season value,
 * adds, net adds, add momentum and role direction — and they are different sorts of the same
 * rows. A single blended number would imply a common unit between a fair rank and a
 * transaction count, and there isn't one. The chart added in ADR-085 holds to that literally:
 * two tracks with their own zeros, their own scales and a rule between them, and nothing that
 * spans both.
 *
 * *A filter is one question about one reading* (ADR-092). "Role rising", "Momentum rising" and
 * "Surfaced" each test one published signal and compose by AND. There is no chip that counts
 * how many signals agree, because that count is a score with its arithmetic hidden. A row with
 * no reading does not pass a filter and is not counted as failing it either: the status line
 * prints both numbers, and a filter whose artifact the build did not publish is named and
 * left off rather than emptying the board.
 *
 * *Behaviour decides visibility, never value.* A player surfaced from beyond the published
 * tier depth carries the fair rank the model gave him and no tier at all, labelled as an
 * exception rather than quietly slotted in.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { OpportunityBoard, type OpportunityMark } from "../charts/OpportunityBoard";
import {
  Notice,
  PanelToggle,
  RosStatusBadge,
  SectionHead,
  Segmented,
} from "../components/primitives";
import {
  filterAvailable,
  roleCell,
  selectOpportunityCandidates,
  type FilterReport,
  type OpportunityCandidate,
  type OpportunitySelection,
} from "../data/candidates";
import { opportunityRowsToCsv } from "../data/csv";
import { formatRank, formatValue } from "../data/format";
import { longAbsenceLabel, type InSeasonBundle } from "../data/ros";
import {
  OPPORTUNITY_FILTERS,
  OPPORTUNITY_SORTS,
  SCORING_LABELS,
  type AppState,
  type OpportunityFilter,
  type OpportunitySort,
} from "../data/state";
import { ExportControls } from "./ExportControls";
import { OpportunityTable } from "./OpportunityTable";

const SORT_LABELS: Readonly<Record<OpportunitySort, string>> = {
  value: "ROS value",
  adds: "Adds",
  net: "Net adds",
  momentum: "Momentum",
  role: "Role",
};

/** The long form a screen reader hears for each ordering. */
const SORT_DESCRIPTIONS: Readonly<Record<OpportunitySort, string>> = {
  value: "ROS value",
  adds: "Adds",
  net: "Net adds",
  momentum: "Add momentum, steepest published rise first",
  role: "Role direction: rising, flat, falling, then no reading",
};

const FILTER_LABELS: Readonly<Record<OpportunityFilter, string>> = {
  role: "Role rising",
  momentum: "Momentum rising",
  surfaced: "Surfaced",
};

/** What each chip tests, in one sentence — the chip's tooltip and its accessible description. */
const FILTER_RULES: Readonly<Record<OpportunityFilter, string>> = {
  role:
    "His position's leading role measure (pass attempts for a QB, snap share otherwise) has a " +
    "published rise in his latest game against his earlier games.",
  momentum:
    "His published add-count slope over the retained window is positive, and the window " +
    "reaches the latest snapshot — a slope that ended earlier in the week is not current.",
  surfaced: "Published from beyond the rest-of-season tier depth by current evidence.",
};

/** Why a chip cannot be applied, in the words of the artifact that is missing. */
const FILTER_UNAVAILABLE: Readonly<Record<OpportunityFilter, string>> = {
  role: "This build published no week-by-week role series, so no role direction can be read.",
  momentum:
    "This build published no add-momentum series, so no add trend can be read. Adds and drops " +
    "for the latest window are unaffected.",
  surfaced: "",
};

/** `Role rising: 12 · 40 with no published change`. Two numbers, never folded into one. */
function reportText(report: FilterReport): string {
  const noun: Readonly<Record<OpportunityFilter, string>> = {
    role: "with no published change",
    momentum: "with no current published slope",
    surfaced: "",
  };
  const missing =
    report.withoutReading > 0 && report.filter !== "surfaced"
      ? ` · ${String(report.withoutReading)} ${noun[report.filter]}, not counted either way`
      : "";
  return `${FILTER_LABELS[report.filter]}: ${String(report.passing)}${missing}`;
}

/** How the role ordering compared rows, which depends on how many positions are on screen. */
function roleOrderNote(selection: OpportunitySelection): string {
  return selection.roleOrdering.magnitudes
    ? "Role order: rising, flat, falling, then no reading; within each, the larger published change first."
    : "Role order: rising, flat, falling, then no reading; within each, by ROS rank — a QB's change is in attempts and everyone else's in share points, so sizes are compared only within one position.";
}

/** How deep the chart goes by default. The table below still holds every published row. */
export const OPPORTUNITY_BOARD_PREVIEW_DEPTH = 40;

/**
 * What the folded board options print on a phone (ADR-093): the ordering, the filters that
 * are actually applied, and how many rows the chart draws — the three things the folded
 * controls decide, so none of them can be on without the row saying so. A filter named by a
 * link that this build cannot apply is not listed; the notice below the options names it.
 */
export function opportunityOptionsSummary(
  state: Pick<AppState, "opportunity" | "board">,
  selection: Pick<OpportunitySelection, "filters">,
  rowCount: number,
): readonly string[] {
  const applied = selection.filters
    .filter((report) => report.available)
    .map((report) => FILTER_LABELS[report.filter]);
  return [
    `By ${SORT_LABELS[state.opportunity]}`,
    applied.length === 0 ? "No filters" : applied.join(" + "),
    state.board === "full" || rowCount <= OPPORTUNITY_BOARD_PREVIEW_DEPTH
      ? `All ${String(rowCount)}`
      : `Top ${String(OPPORTUNITY_BOARD_PREVIEW_DEPTH)} of ${String(rowCount)}`,
  ];
}

function windowLabel(hours: number | null | undefined): string {
  if (hours === null || hours === undefined) return "window unknown";
  return `${String(hours)}h`;
}

/**
 * A mark's accessible label.
 *
 * Both readings, named as what they are and kept apart in the sentence exactly as they are
 * kept apart in the picture: a value in points, then a count of transactions over a window.
 * Nothing here joins them with a word like "versus" that would imply an exchange rate.
 */
function markLabel(candidate: OpportunityCandidate, windowText: string): string {
  const record = candidate.row.record;
  const moves =
    record.add_count === null || record.add_count === undefined
      ? "no add or drop counts published"
      : `${String(record.add_count)} add${record.add_count === 1 ? "" : "s"} and ` +
        `${String(record.drop_count ?? 0)} drop${record.drop_count === 1 ? "" : "s"} ` +
        `over the ${windowText} window`;
  const role = ` Role: ${roleCell(candidate.role, record.position).sentence}`;
  return (
    `${record.display_name}, ${record.position}${String(record.ros_position_rank)}` +
    `${record.team === null ? "" : `, ${record.team}`}, rest-of-season rank ` +
    `${formatRank(record.ros_fair_rank)}, rest-of-season expected VORP ` +
    `${formatValue(record.ros_expected_vorp)} points. Separately: ${moves}.${role}` +
    (record.outside_tier_board ? " Surfaced from beyond the tier depth; no tier." : "") +
    (record.long_absence ? ` ${longAbsenceLabel(record)}.` : "")
  );
}

export function OpportunityView({
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
  const selection = useMemo(() => selectOpportunityCandidates(bundle, state), [bundle, state]);
  const rows = selection.candidates;
  const visibleRows = useRef<readonly OpportunityCandidate[]>(rows);
  useEffect(() => {
    visibleRows.current = rows;
  }, [rows]);

  const metadata = bundle.metadata;
  const behavior = metadata.behavior ?? null;
  const available = behavior?.available === true;
  const buildDate = metadata.generated_at_utc.slice(0, 10);
  const surfaced = useMemo(
    () => rows.filter((row) => row.row.record.outside_tier_board).length,
    [rows],
  );
  const toggleFilter = useCallback(
    (filter: OpportunityFilter) => {
      const next = state.only.includes(filter)
        ? state.only.filter((active) => active !== filter)
        : [...state.only, filter];
      onChange({ only: OPPORTUNITY_FILTERS.filter((candidate) => next.includes(candidate)) });
    },
    [onChange, state.only],
  );

  const window = behavior?.lookback_hours;
  const windowText = windowLabel(window);
  const windowSuffix = window === null || window === undefined ? "" : ` (${String(window)}h)`;

  const charted = useMemo(
    () => (state.board === "full" ? rows : rows.slice(0, OPPORTUNITY_BOARD_PREVIEW_DEPTH)),
    [rows, state.board],
  );
  const marks: readonly OpportunityMark[] = useMemo(
    () =>
      charted.map((candidate) => {
        const row = candidate.row;
        return {
          playerId: row.record.player_id,
          rosRank: row.record.ros_fair_rank,
          position: row.record.position,
          positionRank: row.record.ros_position_rank,
          displayName: row.record.display_name,
          rosExpectedVorp: row.record.ros_expected_vorp,
          addCount: row.record.add_count ?? null,
          dropCount: row.record.drop_count ?? null,
          netAddCount: row.record.net_add_count ?? null,
          role: roleCell(candidate.role, row.record.position),
          surfaced: row.record.outside_tier_board,
          badges: (
            <>
              {row.record.outside_tier_board && (
                <span
                  className="surface-badge"
                  title="Surfaced by current evidence; published without a tier"
                >
                  surfaced
                </span>
              )}
              <RosStatusBadge status={row.record.current_status} />
              {row.record.long_absence && (
                <span
                  className="absence-badge"
                  data-flag="long-absence"
                  title={longAbsenceLabel(row.record)}
                >
                  <span aria-hidden="true">◷</span>
                  <span className="absence-weeks">
                    {`${String(Math.round(row.record.weeks_since_last_game))}w`}
                  </span>
                </span>
              )}
            </>
          ),
          label: markLabel(candidate, windowText),
        };
      }),
    [charted, windowText],
  );
  const truncated = charted.length < rows.length;

  const onToggleDepth = useCallback(() => {
    onChange({ board: state.board === "full" ? "top" : "full" });
  }, [onChange, state.board]);

  /*
    The phone's board options (ADR-093): the orderings, the depth switch and the filter chips
    fold behind one row. The status line beneath them never folds — it is the filters' census,
    and ADR-092 prints it so that a filter is never read as a count of the whole board.
  */
  const [optionsOpen, setOptionsOpen] = useState(false);
  const toggleOptions = useCallback(() => {
    setOptionsOpen((open) => !open);
  }, []);

  if (!bundle.hasOpportunity) {
    return (
      <section className="section" aria-labelledby="opportunity-missing-heading">
        <SectionHead
          index="01"
          id="opportunity-missing-heading"
          title="Opportunity board"
          note="This build published no opportunity artifact."
        />
        <Notice title="The Opportunity Board is not in this build.">
          The rest-of-season board beside it is unaffected: every intrinsic value is exactly
          what the build produced. {bundle.opportunityDegradation?.message ?? ""}
        </Notice>
      </section>
    );
  }

  return (
    <>
      <section className="section" aria-labelledby="opportunity-heading">
        <SectionHead
          index="01"
          id="opportunity-heading"
          title={`Opportunity — through week ${String(metadata.through_week)}`}
          note={
            "Rest-of-season value beside fantasy-market behaviour. Adds and drops are " +
            "transactions over the window shown — not a price, not a rank, and never " +
            "combined with a value."
          }
        >
          <PanelToggle
            className="opp-options-toggle"
            label="Options"
            items={opportunityOptionsSummary(state, selection, rows.length)}
            open={optionsOpen}
            controls="opp-order-options opp-filter-options"
            onToggle={toggleOptions}
          />
          <div
            id="opp-order-options"
            className="phone-panel phone-panel-contents"
            data-open={optionsOpen}
          >
            <Segmented<OpportunitySort>
              name="opportunity"
              label="Order by"
              value={state.opportunity}
              options={OPPORTUNITY_SORTS.map((sort) => ({
                value: sort,
                label: SORT_LABELS[sort],
                description: SORT_DESCRIPTIONS[sort],
              }))}
              onChange={(opportunity) => {
                onChange({ opportunity });
              }}
            />
            <button
              type="button"
              className="button chamfer"
              data-variant="primary"
              aria-pressed={state.board === "full"}
              onClick={onToggleDepth}
            >
              {state.board === "full"
                ? `Show top ${String(OPPORTUNITY_BOARD_PREVIEW_DEPTH)}`
                : `Show full board (${String(rows.length)})`}
            </button>
          </div>
        </SectionHead>

        {!available && (
          <Notice title="No current add/drop behaviour.">
            {/* The reason is the build's own machine phrase, so it is quoted rather than
                spliced into the sentence, where it would read as a fragment. */}
            {`The build recorded “${behavior?.degraded_reason ?? "no retained behaviour snapshot"}”.`}{" "}
            Every rest-of-season value on this board is unchanged: the behaviour feed decides
            which players are visible and never what they are worth.
          </Notice>
        )}

        {/*
          The filters. Toggle buttons rather than a radio group, because they compose: each is
          one question about one published reading, and switching on two asks both. A chip
          whose artifact is missing is disabled and says so, and if a shared link names it the
          notice below names it again rather than letting it empty the board.
        */}
        <div className="opp-filters" role="group" aria-labelledby="opp-filters-label">
          <div
            id="opp-filter-options"
            className="phone-panel phone-panel-contents"
            data-open={optionsOpen}
          >
            <span className="control-label" id="opp-filters-label">
              Show only
            </span>
            <div className="segmented opp-filter-set">
              {OPPORTUNITY_FILTERS.map((filter) => {
                const available = filterAvailable(bundle, filter);
                const pressed = state.only.includes(filter);
                return (
                  <button
                    key={filter}
                    type="button"
                    className="opp-filter"
                    data-filter={filter}
                    aria-pressed={pressed && available}
                    disabled={!available}
                    title={available ? FILTER_RULES[filter] : FILTER_UNAVAILABLE[filter]}
                    onClick={() => {
                      toggleFilter(filter);
                    }}
                  >
                    {FILTER_LABELS[filter]}
                  </button>
                );
              })}
            </div>
          </div>
          <span className="opp-filter-status muted">
            {[
              selection.filters.length === 0
                ? `${String(rows.length)} shown`
                : `${String(rows.length)} of ${String(selection.matched)} shown`,
              ...selection.filters.filter((report) => report.available).map(reportText),
            ].join(" · ")}
          </span>
        </div>
        {state.opportunity === "role" && (
          <p className="muted opp-order-note">{roleOrderNote(selection)}</p>
        )}

        {selection.unavailable.length > 0 && (
          <Notice title="A filter in this link cannot be applied to this build.">
            {selection.unavailable.map((filter) => FILTER_UNAVAILABLE[filter]).join(" ")} The
            board below is shown without {selection.unavailable.length === 1 ? "that filter" : "those filters"}{" "}
            rather than as though no player passed it.
          </Notice>
        )}

        {rows.length === 0 ? (
          <Notice title="No players match.">
            {selection.matched > 0 && selection.filters.length > 0
              ? `None of the ${String(selection.matched)} players the position and search controls leave passes every filter switched on.`
              : state.search === ""
                ? "This position filter returns nothing for the selected preset."
                : `No player on the ${SCORING_LABELS[state.scoring]} opportunity board matches “${state.search}”.`}
          </Notice>
        ) : (
          <OpportunityBoard
            marks={marks}
            windowLabel={windowText}
            behaviorAvailable={available}
            orderLabel={SORT_LABELS[state.opportunity]}
            onSelect={onSelect}
            selectedPlayerId={selectedPlayerId}
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
            Rest-of-season expected VORP, from zero
          </span>
          <span className="legend-item">
            <span className="legend-bar" data-kind="bargain" />
            Adds right of centre
            <span className="legend-bar" data-kind="drop" />
            drops left, on their own count scale
          </span>
          <span className="legend-item">
            Role: ▲ ▬ ▼ latest game against earlier games, in the position&rsquo;s own measure
          </span>
          <span className="legend-item muted">
            {truncated
              ? `Charting the top ${String(charted.length)} of ${String(rows.length)} by ${SORT_LABELS[state.opportunity].toLowerCase()}; the table below has every row.`
              : `Charting all ${String(charted.length)} shown player${charted.length === 1 ? "" : "s"}.`}
          </span>
        </div>

        {available ? (
          <dl className="facts" style={{ marginTop: "0.75rem" }}>
            <div>
              <dt>Behaviour source</dt>
              <dd>{behavior?.source_id ?? "—"}</dd>
            </div>
            <div>
              <dt>Window requested</dt>
              <dd>{windowText}</dd>
            </div>
            <div>
              <dt>Snapshot retrieved</dt>
              <dd>{behavior?.snapshot_at_utc ?? "—"}</dd>
            </div>
            <div>
              <dt>Players matched</dt>
              <dd>{String(behavior?.matched_players ?? 0)}</dd>
            </div>
            <div>
              <dt>Surfaced beyond tier depth</dt>
              <dd>{String(surfaced)}</dd>
            </div>
          </dl>
        ) : null}

        <p className="muted board-note">
          A count is a count. &ldquo;Adds&rdquo; is the number of rosters that added the player
          inside the requested window, as the source reported it. The source publishes no
          observation time of its own, so the time above is when the snapshot was retrieved,
          not a claim about when the transactions happened.
        </p>
        <p className="muted board-note">
          Four readings sit side by side and are never combined: rest-of-season value (the
          model), role (observed: the position&rsquo;s leading measure, latest game against the
          average of earlier games), add momentum (the published slope of the add count over
          the retained window, with its span) and the next game (sportsbook context read by no
          model; nothing here rates an opponent). A filter tests one of them at a time.
        </p>
      </section>

      <section className="section" aria-labelledby="opportunity-table-heading">
        <SectionHead
          index="02"
          id="opportunity-table-heading"
          title="Opportunity table"
          note={
            "Every rest-of-season column is copied from the rest-of-season board unchanged. " +
            "The mark beside a name is annotation and reached no model input."
          }
        >
          <ExportControls
            board="inseason_opportunity"
            scoring={state.scoring}
            teams={state.teams}
            buildDate={buildDate}
            throughWeek={metadata.through_week}
            filteredCount={rows.length}
            buildFilteredCsv={() => opportunityRowsToCsv(visibleRows.current)}
          />
        </SectionHead>

        {rows.length === 0 ? (
          <Notice title="No players match.">
            {selection.matched > 0 && selection.filters.length > 0
              ? "No player passes every filter switched on above."
              : state.search === ""
                ? "This position filter returns nothing for the selected preset."
                : `No player on the ${SCORING_LABELS[state.scoring]} opportunity board matches “${state.search}”.`}
          </Notice>
        ) : (
          <OpportunityTable
            rows={rows}
            windowSuffix={windowSuffix}
            roleOrdering={selection.roleOrdering}
            onSelect={onSelect}
            selectedPlayerId={selectedPlayerId}
            visibleRowsRef={visibleRows}
          />
        )}
      </section>
    </>
  );
}
