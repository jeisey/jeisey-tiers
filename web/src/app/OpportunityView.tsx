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
 * *There is no combined score.* The board offers three orderings — by rest-of-season value,
 * by adds, by net adds — and they are different sorts of the same rows. A single blended
 * number would imply a common unit between a fair rank and a transaction count, and there
 * isn't one. The chart added in ADR-085 holds to that literally: two tracks with their own
 * zeros, their own scales and a rule between them, and nothing that spans both.
 *
 * *Behaviour decides visibility, never value.* A player surfaced from beyond the published
 * tier depth carries the fair rank the model gave him and no tier at all, labelled as an
 * exception rather than quietly slotted in.
 */

import { useCallback, useEffect, useMemo, useRef } from "react";

import { OpportunityBoard, type OpportunityMark } from "../charts/OpportunityBoard";
import { Notice, RosStatusBadge, SectionHead, Segmented } from "../components/primitives";
import { opportunityRowsToCsv } from "../data/csv";
import { formatRank, formatValue } from "../data/format";
import {
  longAbsenceLabel,
  selectOpportunityRows,
  type InSeasonBundle,
  type OpportunityRow,
} from "../data/ros";
import {
  OPPORTUNITY_SORTS,
  SCORING_LABELS,
  type AppState,
  type OpportunitySort,
} from "../data/state";
import { ExportControls } from "./ExportControls";
import { OpportunityTable } from "./OpportunityTable";

const SORT_LABELS: Readonly<Record<OpportunitySort, string>> = {
  value: "ROS value",
  adds: "Adds",
  net: "Net adds",
};

/** How deep the chart goes by default. The table below still holds every published row. */
export const OPPORTUNITY_BOARD_PREVIEW_DEPTH = 40;

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
function markLabel(row: OpportunityRow, windowText: string): string {
  const record = row.record;
  const moves =
    record.add_count === null || record.add_count === undefined
      ? "no add or drop counts published"
      : `${String(record.add_count)} add${record.add_count === 1 ? "" : "s"} and ` +
        `${String(record.drop_count ?? 0)} drop${record.drop_count === 1 ? "" : "s"} ` +
        `over the ${windowText} window`;
  const snap =
    record.snap_share_last3 === null || record.snap_share_last3 === undefined
      ? ""
      : `, snap share ${String(Math.round(record.snap_share_last3 * 100))} percent`;
  return (
    `${record.display_name}, ${record.position}${String(record.ros_position_rank)}` +
    `${record.team === null ? "" : `, ${record.team}`}, rest-of-season rank ` +
    `${formatRank(record.ros_fair_rank)}, rest-of-season expected VORP ` +
    `${formatValue(record.ros_expected_vorp)} points. Separately: ${moves}${snap}` +
    (record.outside_tier_board ? ". Surfaced from beyond the tier depth; no tier" : "") +
    (record.long_absence ? `. ${longAbsenceLabel(record)}` : "")
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
  const rows = useMemo(() => selectOpportunityRows(bundle, state), [bundle, state]);
  const visibleRows = useRef<readonly OpportunityRow[]>(rows);
  useEffect(() => {
    visibleRows.current = rows;
  }, [rows]);

  const metadata = bundle.metadata;
  const behavior = metadata.behavior ?? null;
  const available = behavior?.available === true;
  const buildDate = metadata.generated_at_utc.slice(0, 10);
  const surfaced = useMemo(
    () => rows.filter((row) => row.record.outside_tier_board).length,
    [rows],
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
      charted.map((row) => ({
        playerId: row.record.player_id,
        rosRank: row.record.ros_fair_rank,
        position: row.record.position,
        positionRank: row.record.ros_position_rank,
        displayName: row.record.display_name,
        rosExpectedVorp: row.record.ros_expected_vorp,
        addCount: row.record.add_count ?? null,
        dropCount: row.record.drop_count ?? null,
        netAddCount: row.record.net_add_count ?? null,
        snapShare: row.record.snap_share_last3 ?? null,
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
        label: markLabel(row, windowText),
      })),
    [charted, windowText],
  );
  const truncated = charted.length < rows.length;

  const onToggleDepth = useCallback(() => {
    onChange({ board: state.board === "full" ? "top" : "full" });
  }, [onChange, state.board]);

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
          <Segmented<OpportunitySort>
            name="opportunity"
            label="Order by"
            value={state.opportunity}
            options={OPPORTUNITY_SORTS.map((sort) => ({ value: sort, label: SORT_LABELS[sort] }))}
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

        {rows.length === 0 ? (
          <Notice title="No players match.">
            {state.search === ""
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
            {state.search === ""
              ? "This position filter returns nothing for the selected preset."
              : `No player on the ${SCORING_LABELS[state.scoring]} opportunity board matches “${state.search}”.`}
          </Notice>
        ) : (
          <OpportunityTable
            rows={rows}
            windowSuffix={windowSuffix}
            onSelect={onSelect}
            selectedPlayerId={selectedPlayerId}
            visibleRowsRef={visibleRows}
          />
        )}
      </section>
    </>
  );
}
