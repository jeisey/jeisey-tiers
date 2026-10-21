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

import { describeNet, describeSide, netAdds, sideOf } from "../data/behavior";
import { Suspense, lazy, useCallback, useEffect, useMemo, useRef, useState } from "react";

import { OpportunityBoard, type OpportunityMark } from "../charts/OpportunityBoard";
import {
  Notice,
  PanelToggle,
  RosStatusBadge,
  SectionHead,
  Segmented,
  TeamCell,
} from "../components/primitives";
import {
  breakoutUnavailableReason,
  filterAvailable,
  roleCell,
  selectOpportunityCandidates,
  type CeilingReport,
  type FilterReport,
  type OpportunityCandidate,
  type OpportunitySelection,
} from "../data/candidates";
import { opportunityRowsToCsv } from "../data/csv";
import {
  ESPN_CEILINGS,
  ESPN_CEILING_LABELS,
  ceilingPhrase,
  espnCell,
  espnFilterUnavailableReason,
  espnFilterUsable,
  type EspnCeiling,
} from "../data/espn";
import { formatEastern, formatRank, formatValue } from "../data/format";
import type { EspnOwnershipMetadata, ScoringPreset, UnprojectedRecord } from "../data/contracts";
import { matchesPosition, matchesSearch } from "../data/model";
import { longAbsenceLabel, rosValue, type InSeasonBundle } from "../data/ros";
import {
  OPPORTUNITY_FILTERS,
  OPPORTUNITY_SORTS,
  SCORING_LABELS,
  SCORING_TO_PRESET,
  leaguePresetId,
  type AppState,
  type OpportunityFilter,
  type OpportunitySort,
} from "../data/state";
import { ExportControls } from "./ExportControls";
import { OpportunityTable } from "./OpportunityTable";
import {
  SeasonPerGameCell,
  SeasonPointsCell,
  SeasonRankCell,
  seasonCaption,
} from "./SeasonColumns";
import { SEASON_COLUMN_LABELS } from "../data/actuals";
import type { RecentFormMetadata, RecentWindowKey } from "../data/contracts";
import {
  BREAKOUT_FILTERS,
  BREAKOUT_FILTER_LABELS,
  LENS_LABELS,
  RECENT_LENSES,
  formatRecentRank,
  formatSpan,
  recentDetail,
  recentSentence,
  windowSpan,
  type BreakoutCensus,
  type BreakoutFilter,
  type RecentLens,
} from "../data/recent";
import type { RecentColumnsSpec } from "./OpportunityTable";

/** ADR-113: the evidence dialog and its sentences load on first use, never with the board. */
const BreakoutDialog = lazy(() => import("./BreakoutDialog"));

const SORT_LABELS: Readonly<Record<OpportunitySort, string>> = {
  value: "ROS value",
  adds: "Adds",
  net: "Net adds",
  momentum: "Momentum",
  role: "Role",
  espn: "ESPN rost%",
  espn7: "ESPN 7d",
};

/** The long form a screen reader hears for each ordering. */
const SORT_DESCRIPTIONS: Readonly<Record<OpportunitySort, string>> = {
  value: "ROS value",
  adds: "Adds",
  net: "Net adds",
  momentum: "Add momentum, steepest published rise first",
  role: "Role direction: rising, flat, falling, then no reading",
  espn: "ESPN rostered percentage, highest first; no current reading last",
  espn7: "ESPN 7-day roster change in percentage points, largest gain first; no change last",
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

/** `Rostered below 50% on ESPN: 30 · 12 with no current ESPN reading, not counted either way`. */
function ceilingReportText(report: CeilingReport): string {
  const missing =
    report.withoutReading > 0
      ? ` · ${String(report.withoutReading)} with no current ESPN reading, not counted either way`
      : "";
  const phrase = ceilingPhrase(report.ceiling);
  return `${phrase.charAt(0).toUpperCase()}${phrase.slice(1)}: ${String(report.passing)}${missing}`;
}

/** How the role ordering compared rows, which depends on how many positions are on screen. */
function roleOrderNote(selection: OpportunitySelection): string {
  return selection.roleOrdering.magnitudes
    ? "Role order: rising, flat, falling, then no reading; within each, the larger published change first."
    : "Role order: rising, flat, falling, then no reading; within each, by ROS rank — a QB's change is in attempts and everyone else's in share points, so sizes are compared only within one position.";
}

/** The ceiling's values as the radio group carries them. */
type EspnCeilingOption = "all" | "10" | "25" | "50" | "75";

/** What the ESPN ceiling tests, in one sentence. */
const ESPN_CEILING_RULE =
  "Keep players whose current ESPN rostered percentage is strictly below the ceiling. A player " +
  "with no current ESPN reading (not listed by ESPN, no verified ESPN id, or a stale reading) " +
  "does not pass, and is counted apart rather than as 0%.";

/** What the recent-weeks lens does, in one sentence. */
const RECENT_LENS_RULE =
  "Observed production in the last N completed regular-season weeks ending at the cutoff — the " +
  "same calendar weeks for every player. A bye or missed game is fewer games, never an older " +
  "week. Changes no value, rank, tier or role reading.";

/** What the breakout filter tests, in one sentence. */
const BREAKOUT_RULE_TEXT =
  "Keeps players whose published breakout category in the selected window is the one chosen " +
  "(Any: Takeover, Sneaking or Eyebrow). Descriptive heuristic thresholds over weekly ranks and " +
  "role shares; not a prediction. A player with too little data does not pass and is counted apart.";

/** `W3–5: 1 Takeover · 2 Sneaking · 3 Eyebrow · 5 too little data · 2 no record`. */
function censusText(span: string, census: BreakoutCensus): string {
  const parts = [
    `${String(census.takeover)} Takeover`,
    `${String(census.sneaking)} Sneaking`,
    `${String(census.eyebrow)} Eyebrow`,
  ];
  if (census.insufficient > 0) parts.push(`${String(census.insufficient)} too little data`);
  if (census.unavailable > 0) parts.push(`${String(census.unavailable)} no recent record`);
  return `Breakouts in ${span}: ${parts.join(" · ")}`;
}

/** The caption sentence for the recent columns, or for their absence. */
function recentCaption(windowKey: RecentWindowKey | null, span: string, unavailable: string | null): string {
  if (unavailable !== null) return `Recent columns: ${unavailable}`;
  if (windowKey === null) return "Season lens: no recent-window columns.";
  // The window stays with the table; how the rank and the badge are formed is on the Data tab.
  return `Recent: positional rank by total points in ${span}.`;
}

function hasActiveFilter(selection: OpportunitySelection): boolean {
  return (
    selection.filters.some((report) => report.available) ||
    selection.ceiling?.usable === true ||
    selection.breakout?.usable === true
  );
}

/** The ESPN readings' source, freshness and coverage, beside the board's own facts. */
function EspnFacts({
  bundle,
  meta,
}: {
  readonly bundle: InSeasonBundle;
  readonly meta: EspnOwnershipMetadata | null;
}): React.JSX.Element {
  const availability = bundle.espnAvailability;
  if (meta === null) {
    return (
      <p className="muted board-note" data-espn="unavailable">
        {availability.kind === "unpublished"
          ? "ESPN roster percentages: not in this build."
          : `ESPN roster percentages: unavailable for this build${
              availability.kind === "unavailable" ? ` (${availability.reason})` : ""
            }. Every other column is unaffected.`}
      </p>
    );
  }
  const states = meta.reading_states ?? {};
  const absent =
    (states.not_published ?? 0) +
    (states.invalid ?? 0) +
    (states.no_espn_id ?? 0) +
    (states.ambiguous_espn_id ?? 0);
  return (
    <>
      <dl className="facts" data-espn={availability.kind} style={{ marginTop: "0.75rem" }}>
        <div>
          <dt>ESPN read</dt>
          <dd>
            {formatEastern(meta.latest_observed_at_utc ?? null)}
            {availability.kind === "stale" ? " · stale" : ""}
          </dd>
        </div>
        <div>
          <dt>ESPN period at read</dt>
          <dd>{meta.espn_current_period === null || meta.espn_current_period === undefined ? "—" : String(meta.espn_current_period)}</dd>
        </div>
        <div>
          <dt>ESPN readings</dt>
          <dd>{`${String((states.observed ?? 0) + (states.stale ?? 0))} of ${String(meta.players ?? 0)}`}</dd>
        </div>
        <div>
          <dt>No ESPN reading</dt>
          <dd>{String(absent)}</dd>
        </div>
        <div>
          <dt>Daily ESPN reads (28d)</dt>
          <dd>{String(meta.captures_in_window ?? 0)}</dd>
        </div>
      </dl>
      {/* Whose leagues these are, and the attribution, stay beside the numbers (ADR-112); how
          the changes are measured is on the Data tab (ADR-115). */}
      <p className="muted board-note" data-espn-note="population">
        {meta.population_statement ?? ""} {meta.attribution ?? ""}
      </p>
    </>
  );
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
  state: Pick<AppState, "opportunity" | "board"> & { readonly last?: RecentLens },
  selection: Pick<OpportunitySelection, "filters"> & {
    readonly ceiling?: CeilingReport | null;
    readonly breakout?: OpportunitySelection["breakout"];
    readonly census?: BreakoutCensus | null;
  },
  rowCount: number,
  recentMeta: RecentFormMetadata | null = null,
): readonly string[] {
  const applied = selection.filters
    .filter((report) => report.available)
    .map((report) => FILTER_LABELS[report.filter]);
  if (selection.ceiling?.usable === true) applied.push(`ESPN ${ESPN_CEILING_LABELS[selection.ceiling.ceiling] ?? ""}`);
  if (selection.breakout?.usable === true) applied.push(BREAKOUT_FILTER_LABELS[selection.breakout.filter]);
  // ADR-113: the lens is folded too, so its real weeks and missing evidence are in the row.
  const lens = state.last;
  const lensText =
    lens === undefined || recentMeta === null
      ? []
      : [
          lens === "season"
            ? "Season"
            : `${LENS_LABELS[lens]} ${formatSpan(windowSpan(recentMeta, lens), true)}` +
              (selection.census === null || selection.census === undefined
                ? ""
                : ` · ${String(selection.census.insufficient + selection.census.unavailable)} without evidence`),
        ];
  return [
    `By ${SORT_LABELS[state.opportunity]}`,
    applied.length === 0 ? "No filters" : applied.join(" + "),
    state.board === "full" || rowCount <= OPPORTUNITY_BOARD_PREVIEW_DEPTH
      ? `All ${String(rowCount)}`
      : `Top ${String(OPPORTUNITY_BOARD_PREVIEW_DEPTH)} of ${String(rowCount)}`,
    ...lensText,
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
  const moves = !record.behavior_available
    ? "no add or drop counts published"
    : `${describeSide(sideOf(record, "add"), "add")} and ` +
      `${describeSide(sideOf(record, "drop"), "drop")}, ${describeNet(record)}, ` +
      `over the ${windowText} window`;
  const role = ` Role: ${roleCell(candidate.role, record.position).sentence}`;
  const espn = candidate.espn.kind === "unavailable" ? "" : ` ESPN: ${espnCell(candidate.espn).sentence}`;
  return (
    `${record.display_name}, ${record.position}${String(record.ros_position_rank)}` +
    `${record.team === null ? "" : `, ${record.team}`}, rest-of-season rank ` +
    `${formatRank(record.ros_fair_rank)}, rest-of-season median VORP ` +
    `${formatValue(rosValue(record))} points. Separately: ${moves}.${role}${espn}` +
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
  // ADR-102: off-roster players with no model output. Position and search apply; the value,
  // role and momentum controls cannot, because there is nothing of his for them to read.
  const unprojected = useMemo(
    () =>
      bundle
        .unprojectedFor(leaguePresetId(state.teams), SCORING_TO_PRESET[state.scoring])
        .filter(
          (record) =>
            matchesPosition(record.position, state.position) &&
            matchesSearch(
              { ...record, team: bundle.teamLabel(record.player_id, record.team) },
              state.search,
            ),
        ),
    [bundle, state.teams, state.scoring, state.position, state.search],
  );
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

  const espnUnavailable = espnFilterUsable(bundle.espnAvailability)
    ? null
    : espnFilterUnavailableReason(bundle.espnAvailability);
  const espnMeta =
    bundle.espnAvailability.kind === "published" || bundle.espnAvailability.kind === "stale"
      ? bundle.espnAvailability.meta
      : null;
  const discovery = useMemo(() => {
    const role = selection.filters.find((report) => report.filter === "role" && report.available);
    const ceiling = selection.ceiling;
    if (role === undefined || !ceiling?.usable) return null;
    return {
      label: `Role rising + ${ceilingPhrase(ceiling.ceiling)}`,
      ceilingText: `${ceilingPhrase(ceiling.ceiling).charAt(0).toUpperCase()}${ceilingPhrase(ceiling.ceiling).slice(1)}`,
      role,
      ceiling,
    };
  }, [selection]);

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
          rosValue: rosValue(row.record),
          addCount: sideOf(row.record, "add").count,
          dropCount: sideOf(row.record, "drop").count,
          net: netAdds(row.record),
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
              <RosStatusBadge status={row.record.current_status} playerId={row.record.player_id} />
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

  // ADR-113: the recent-weeks lens. Observed production only: it changes no value, rank, tier,
  // role reading or count, and the Season lens shows the season columns alone.
  const recentMeta =
    bundle.recentAvailability.kind === "published" ? bundle.recentAvailability.meta : null;
  const recentReason =
    bundle.recentAvailability.kind === "unavailable" ? bundle.recentAvailability.reason : null;
  const windowKey: RecentWindowKey | null =
    state.last === "season" || recentMeta === null ? null : state.last;
  const span = windowKey === null || recentMeta === null ? null : windowSpan(recentMeta, windowKey);
  // The headings carry the bare range (`W6–8`); the census, the caption and the control say
  // when the season is younger than the window asked for.
  const spanLabel = span === null ? "" : formatSpan({ ...span, requested: span.weeks }, true);
  const spanFull = span === null ? "" : formatSpan(span, true);
  const [explaining, setExplaining] = useState<string | null>(null);
  const onExplain = useCallback((playerId: string) => {
    setExplaining(playerId);
  }, []);
  const closeExplain = useCallback(() => {
    setExplaining(null);
  }, []);
  const recentSpec: RecentColumnsSpec | null = useMemo(
    () => (windowKey === null ? null : { spanLabel, onExplain }),
    [windowKey, spanLabel, onExplain],
  );
  const explained =
    explaining === null ? null : (rows.find((row) => row.row.record.player_id === explaining) ?? null);
  const breakoutReason = breakoutUnavailableReason(bundle, state.last);

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
        >
          <PanelToggle
            className="opp-options-toggle"
            label="Options"
            items={opportunityOptionsSummary(state, selection, rows.length, recentMeta)}
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
          <div
            className="phone-panel phone-panel-contents opp-espn-control"
            data-open={optionsOpen}
            title={espnUnavailable ?? ESPN_CEILING_RULE}
          >
            <Segmented<EspnCeilingOption>
              name="espn-ceiling"
              label="ESPN rostered"
              value={String(state.espn) as EspnCeilingOption}
              options={ESPN_CEILINGS.map((ceiling) => ({
                value: String(ceiling) as EspnCeilingOption,
                label: ESPN_CEILING_LABELS[String(ceiling)] ?? String(ceiling),
                description:
                  ceiling === "all"
                    ? "All players, whatever their ESPN roster percentage"
                    : `Only players rostered in strictly fewer than ${String(ceiling)}% of ESPN leagues`,
                disabled: ceiling !== "all" && espnUnavailable !== null,
              }))}
              onChange={(value) => {
                onChange({ espn: (value === "all" ? "all" : Number(value)) as EspnCeiling });
              }}
            />
          </div>
          {/* ADR-113: the recent-weeks lens and the breakout filter fold with the others. */}
          <div
            className="phone-panel phone-panel-contents opp-recent-control"
            data-open={optionsOpen}
            title={recentReason ?? RECENT_LENS_RULE}
          >
            <Segmented<RecentLens>
              name="recent-lens"
              label="Recent weeks"
              value={recentMeta === null ? "season" : state.last}
              options={RECENT_LENSES.map((lens) => ({
                value: lens,
                label: lens === "season" ? "Season" : lens,
                description:
                  lens === "season"
                    ? "Season to date only: no recent window and no breakout category"
                    : recentMeta === null
                      ? `${LENS_LABELS[lens]} weeks: unavailable for this build`
                      : `${LENS_LABELS[lens]} completed weeks, ${formatSpan(windowSpan(recentMeta, lens))}`,
                disabled: lens !== "season" && recentMeta === null,
              }))}
              onChange={(last) => {
                onChange({ last });
              }}
            />
          </div>
          <div
            className="phone-panel phone-panel-contents opp-breakout-control"
            data-open={optionsOpen}
            title={breakoutReason ?? BREAKOUT_RULE_TEXT}
          >
            <Segmented<BreakoutFilter>
              name="breakout"
              label="Breakout"
              // What the board applies: All when the lens or the build cannot apply the link's
              // choice (the notice below names it).
              value={breakoutReason === null ? state.form : "all"}
              options={BREAKOUT_FILTERS.map((filter) => ({
                value: filter,
                label: BREAKOUT_FILTER_LABELS[filter],
                description:
                  filter === "all"
                    ? "All players, whatever their breakout category"
                    : filter === "any"
                      ? "Only players with a Takeover, Sneaking or Eyebrow badge in the selected window"
                      : `Only players with a ${BREAKOUT_FILTER_LABELS[filter]} badge in the selected window`,
                disabled: filter !== "all" && breakoutReason !== null,
              }))}
              onChange={(form) => {
                onChange({ form });
              }}
            />
          </div>
          <span className="opp-filter-status muted">
            {[
              selection.filters.length === 0 && selection.ceiling === null && selection.breakout === null
                ? `${String(rows.length)} shown`
                : `${String(rows.length)} of ${String(selection.matched)} shown`,
              ...selection.filters.filter((report) => report.available).map(reportText),
              ...(selection.ceiling?.usable === true ? [ceilingReportText(selection.ceiling)] : []),
              ...(selection.breakout?.usable === true
                ? [`${BREAKOUT_FILTER_LABELS[selection.breakout.filter]}: ${String(selection.breakout.passing)}`]
                : []),
            ].join(" · ")}
          </span>
          {selection.census !== null && (
            <span className="opp-recent-status opp-breakout-census muted" data-census="breakout">
              {censusText(spanFull, selection.census)}
            </span>
          )}
          {recentReason !== null && (
            <span className="opp-recent-status muted" data-recent="unavailable">
              {`Recent weeks: ${recentReason}`}
            </span>
          )}
        </div>
        {discovery !== null && (
          <div className="opp-discovery" data-rule="role-espn">
            <p className="opp-discovery-rule">
              <strong>{discovery.label}</strong>
              {` — ${String(rows.length)} player${rows.length === 1 ? "" : "s"} pass both conditions.`}
            </p>
            <ul className="opp-discovery-conditions">
              <li>
                {`Role rising: ${String(discovery.role.passing)} of ${String(selection.matched)}`}
                {discovery.role.withoutReading > 0
                  ? ` (${String(discovery.role.withoutReading)} with no published change).`
                  : "."}{" "}
                {FILTER_RULES.role}
              </li>
              <li>
                {`${discovery.ceilingText}: ${String(discovery.ceiling.passing)} of ${String(selection.matched)}`}
                {discovery.ceiling.withoutReading > 0
                  ? ` (${String(discovery.ceiling.withoutReading)} with no current ESPN reading).`
                  : "."}{" "}
                {`Strictly below ${String(discovery.ceiling.ceiling)}%; the reading is ESPN's, not your league's.`}
              </li>
            </ul>
            <p className="muted opp-discovery-evidence">
              {`Supporting evidence, not part of the rule: ${String(selection.evidence.espnRising)} of ` +
                `${String(selection.evidence.espnMeasured)} with a measured ESPN 7-day change are rising on ESPN; ` +
                `${String(selection.evidence.sleeperPositive)} of ${String(selection.evidence.sleeperMeasured)} ` +
                "with Sleeper counts have positive net adds. Two populations in two units, shown apart; " +
                "neither changes who passes, and no score combines them."}
            </p>
          </div>
        )}
        {state.opportunity === "role" && (
          <p className="muted opp-order-note">{roleOrderNote(selection)}</p>
        )}

        {state.espn !== "all" && espnUnavailable !== null && (
          <Notice title="The ESPN filter in this link cannot be applied to this build.">
            {espnUnavailable} The board below is shown without it rather than as though no
            player passed it, and no player is treated as 0% rostered.
          </Notice>
        )}

        {state.form !== "all" && breakoutReason !== null && (
          <Notice title="The breakout filter in this link cannot be applied here.">
            {breakoutReason} The board below is shown without it rather than as though no
            player passed it.
          </Notice>
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
            {selection.matched > 0 && hasActiveFilter(selection)
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

        <EspnFacts bundle={bundle} meta={espnMeta} />

        {/* ADR-114: the one state a reader needs to read a dash or a "≥" in the count columns. */}
        {available && (
          <p className="muted board-note" data-behavior-note="coverage">
            {`Sleeper lists its top 100 adds and top 100 drops (${windowText}). A dash is outside that list, not zero; a net marked ≥ is a bound.`}
          </p>
        )}
      </section>

      <section className="section" aria-labelledby="opportunity-table-heading">
        <SectionHead
          index="02"
          id="opportunity-table-heading"
          title="Opportunity table"
        >
          <ExportControls
            board="inseason_opportunity"
            scoring={state.scoring}
            teams={state.teams}
            buildDate={buildDate}
            throughWeek={metadata.through_week}
            filteredCount={rows.length}
            buildFilteredCsv={() =>
              opportunityRowsToCsv(visibleRows.current, windowKey ?? "season", recentMeta)
            }
            fullLabel="Download full CSV · season only"
            fullTitle={
              "The build's file: every published row of every league and scoring block, with " +
              "season-to-date columns. It carries no recent window; the filtered export writes " +
              "the window selected here for the rows on screen."
            }
            filteredLabel={windowKey === null ? "Export filtered CSV" : `Export filtered CSV · ${spanLabel}`}
          />
        </SectionHead>

        {rows.length === 0 ? (
          <Notice title="No players match.">
            {selection.matched > 0 && hasActiveFilter(selection)
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
            seasonNote={seasonCaption(
              metadata.through_week,
              SCORING_LABELS[state.scoring],
              bundle.actualsAvailability.published ? null : bundle.actualsAvailability.reason,
            )}
            recent={recentSpec}
            recentNote={recentCaption(windowKey, spanFull, recentReason)}
          />
        )}
      </section>

      {explained?.recent !== undefined && recentMeta !== null && (
        <Suspense fallback={null}>
        <BreakoutDialog
          name={explained.row.record.display_name}
          standing={explained.recent}
          season={explained.season}
          meta={recentMeta}
          onClose={closeExplain}
        />
        </Suspense>
      )}

      {unprojected.length > 0 && (
        <UnprojectedSection
          bundle={bundle}
          records={unprojected}
          windowKey={windowKey}
          spanLabel={spanLabel}
          scoring={SCORING_TO_PRESET[state.scoring]}
          onSelect={onSelect}
          selectedPlayerId={selectedPlayerId}
        />
      )}
    </>
  );
}

/**
 * Off-roster players the model has no output for, whom managers are adding (ADR-102).
 *
 * A separate, plain table because nothing on the board above can order them: they have no
 * rank, tier or value, and a blank in a sorted value column would read as a zero or as last.
 * Each row says why he is here and what he is not — playable this week — and opens his card.
 */
function UnprojectedSection({
  bundle,
  records,
  windowKey,
  spanLabel,
  scoring,
  onSelect,
  selectedPlayerId,
}: {
  readonly bundle: InSeasonBundle;
  readonly records: readonly UnprojectedRecord[];
  readonly windowKey: RecentWindowKey | null;
  readonly spanLabel: string;
  readonly scoring: ScoringPreset;
  readonly onSelect: (playerId: string) => void;
  readonly selectedPlayerId: string | null;
}): React.JSX.Element {
  return (
    <section className="section" aria-labelledby="opportunity-unprojected-heading">
      <SectionHead
        index="03"
        id="opportunity-unprojected-heading"
        title="Not projected"
        note={
          "Verified off-roster players with heavy add volume and no validated rest-of-season " +
          "output. Speculative stashes: none can play until he signs or appears on a roster."
        }
      />
      <div
        className="table-scroll"
        role="region"
        aria-labelledby="opportunity-unprojected-heading"
        tabIndex={0}
      >
        <table className="sheet unprojected-sheet">
          <caption className="visually-hidden">
            Off-roster players without a projection, most added first
          </caption>
          <thead>
            <tr>
              <th scope="col" className="plain">
                Player
              </th>
              <th scope="col" className="plain">
                Pos
              </th>
              <th scope="col" className="plain">
                Team
              </th>
              {/* ADR-105: genuine actuals, with no RoS projection manufactured beside them. */}
              <th scope="col" className="plain">
                ROS PosRk
              </th>
              <th scope="col" className="plain">
                {SEASON_COLUMN_LABELS.rank}
              </th>
              <th scope="col" className="plain">
                {SEASON_COLUMN_LABELS.points}
              </th>
              <th scope="col" className="plain">
                {SEASON_COLUMN_LABELS.perGame}
              </th>
              {/* ADR-113: genuine recent actuals too, and still no projection beside them. */}
              {windowKey !== null && (
                <th scope="col" className="plain">
                  Recent <span className="th-sub">{spanLabel}</span>
                </th>
              )}
              <th scope="col">Adds</th>
              <th scope="col">Drops</th>
              <th scope="col" className="plain">
                Why listed
              </th>
            </tr>
          </thead>
          <tbody>
            {records.map((record) => {
              const reading = bundle.availabilityFor(record.player_id);
              const season = bundle.seasonStandingFor(scoring, record.player_id);
              const recent =
                windowKey === null ? undefined : bundle.recentStandingFor(scoring, record.player_id, windowKey);
              return (
                <tr
                  key={record.player_id}
                  data-selected={record.player_id === selectedPlayerId}
                  data-player-id={record.player_id}
                >
                  <th scope="row">
                    <button
                      type="button"
                      className="player-name"
                      onClick={() => {
                        onSelect(record.player_id);
                      }}
                    >
                      {record.display_name}
                    </button>{" "}
                    <RosStatusBadge status={record.current_status} playerId={record.player_id} />
                  </th>
                  <td>{record.position}</td>
                  <td>
                    <TeamCell team={record.team} playerId={record.player_id} />
                  </td>
                  <td className="muted">No RoS projection</td>
                  <td className="num">
                    <SeasonRankCell standing={season} />
                  </td>
                  <td className="num">
                    <SeasonPointsCell standing={season} />
                  </td>
                  <td className="num">
                    <SeasonPerGameCell standing={season} />
                  </td>
                  {windowKey !== null && (
                    <td className="num" title={recentSentence(recent)}>
                      {formatRecentRank(recent)}{" "}
                      <span className="muted">{recentDetail(recent)}</span>
                    </td>
                  )}
                  <td className="num" title={describeSide(sideOf(record, "add"), "add")}>
                    {formatCount(sideOf(record, "add").count)}
                  </td>
                  <td className="num" title={describeSide(sideOf(record, "drop"), "drop")}>
                    {formatCount(sideOf(record, "drop").count)}
                  </td>
                  <td className="muted">
                    {reading.kind === "unsigned"
                      ? "Unsigned free agent · no projection"
                      : `${reading.headline} · no projection`}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function formatCount(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : value.toLocaleString("en-US");
}
