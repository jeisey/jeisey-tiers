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
 * isn't one.
 *
 * *Behaviour decides visibility, never value.* A player surfaced from beyond the published
 * tier depth carries the fair rank the model gave him and no tier at all, labelled as an
 * exception rather than quietly slotted in.
 */

import { useEffect, useMemo, useRef } from "react";

import { Notice, SectionHead, Segmented } from "../components/primitives";
import { opportunityRowsToCsv } from "../data/csv";
import { formatValue } from "../data/format";
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

const SORT_LABELS: Readonly<Record<OpportunitySort, string>> = {
  value: "ROS value",
  adds: "Adds",
  net: "Net adds",
};

function windowLabel(hours: number | null | undefined): string {
  if (hours === null || hours === undefined) return "window unknown";
  return `${String(hours)}h`;
}

function countCell(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : String(value);
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

  const window = behavior?.lookback_hours;
  const windowSuffix = window === null || window === undefined ? "" : ` (${String(window)}h)`;

  return (
    <>
      <section className="section" aria-labelledby="opportunity-heading">
        <SectionHead
          index="01"
          id="opportunity-heading"
          title={`Opportunity — through week ${String(metadata.through_week)}`}
          note={
            "Rest-of-season value beside fantasy-market behaviour. Add and drop counts are " +
            "transactions over the window shown — not a draft price, not a rank, and never " +
            "subtracted from one."
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
        </SectionHead>

        {available ? (
          <dl className="facts">
            <div>
              <dt>Behaviour source</dt>
              <dd>{behavior?.source_id ?? "—"}</dd>
            </div>
            <div>
              <dt>Window requested</dt>
              <dd>{windowLabel(behavior?.lookback_hours)}</dd>
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
        ) : (
          <Notice title="No current add/drop behaviour.">
            {behavior?.degraded_reason ??
              "No retained behaviour snapshot was available for this build."}{" "}
            Every rest-of-season value on this board is unchanged: the behaviour feed decides
            which players are visible and never what they are worth.
          </Notice>
        )}

        <p className="muted" style={{ marginTop: "0.75rem" }}>
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
            "Current status is annotation and reached no model input."
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
          <div className="table-scroll">
            <table className="sheet">
              <caption>
                In-season opportunity board. Add and drop counts are transactions over the
                requested window; they are never converted into a draft position and never
                differenced against the rest-of-season rank. A row marked
                &ldquo;surfaced&rdquo; is published because current evidence made him
                relevant, and carries no tier.
              </caption>
              <thead>
                <tr>
                  <th scope="col" style={{ width: "4.5rem", textAlign: "right" }}>
                    ROS Rank
                  </th>
                  <th scope="col" className="col-player">
                    Player
                  </th>
                  <th scope="col" style={{ width: "3rem" }}>
                    Pos
                  </th>
                  <th scope="col" style={{ width: "3.5rem" }}>
                    Team
                  </th>
                  <th scope="col" style={{ width: "7rem", textAlign: "right" }}>
                    ROS Exp VORP
                  </th>
                  <th scope="col" style={{ width: "6rem", textAlign: "right" }}>
                    {`Adds${windowSuffix}`}
                  </th>
                  <th scope="col" style={{ width: "6rem", textAlign: "right" }}>
                    {`Drops${windowSuffix}`}
                  </th>
                  <th scope="col" style={{ width: "6rem", textAlign: "right" }}>
                    Net adds
                  </th>
                  <th scope="col" style={{ width: "6rem", textAlign: "right" }}>
                    Snap share
                  </th>
                  <th scope="col" style={{ width: "9rem", textAlign: "right" }}>
                    Weeks since last game
                  </th>
                  <th scope="col" className="col-annotation" style={{ width: "7rem" }}>
                    Current status
                  </th>
                </tr>
              </thead>
              <tbody>
                {rows.map(({ record }) => (
                  <tr
                    key={record.player_id}
                    data-selected={record.player_id === selectedPlayerId}
                    data-player={record.player_id}
                    data-surfaced={record.outside_tier_board ? "true" : undefined}
                    data-long-absence={record.long_absence ? "true" : undefined}
                  >
                    <td className="num">{String(record.ros_fair_rank)}</td>
                    <td className="col-player">
                      <span className="player-cell">
                        <button
                          type="button"
                          className="player-name"
                          onClick={() => {
                            onSelect(record.player_id);
                          }}
                        >
                          {record.display_name}
                        </button>
                        {record.outside_tier_board && (
                          <span
                            className="surface-badge"
                            title="Surfaced by current evidence; published without a tier"
                          >
                            surfaced
                          </span>
                        )}
                        {record.long_absence && (
                          <span
                            className="absence-badge"
                            data-flag="long-absence"
                            title={longAbsenceLabel(record)}
                          >
                            <span aria-hidden="true">◷</span>
                            <span className="absence-weeks">
                              {`${String(Math.round(record.weeks_since_last_game))}w`}
                            </span>
                            <span className="visually-hidden">
                              {`${longAbsenceLabel(record)}. No injury or practice-report information is used.`}
                            </span>
                          </span>
                        )}
                      </span>
                    </td>
                    <td>{record.position}</td>
                    <td className="muted">{record.team ?? "—"}</td>
                    <td className="num">{formatValue(record.ros_expected_vorp)}</td>
                    <td className="num">{countCell(record.add_count)}</td>
                    <td className="num">{countCell(record.drop_count)}</td>
                    <td className="num">{countCell(record.net_add_count)}</td>
                    <td className="num muted">
                      {record.snap_share_last3 === null || record.snap_share_last3 === undefined
                        ? "—"
                        : `${String(Math.round(record.snap_share_last3 * 100))}%`}
                    </td>
                    <td className="num muted">
                      {Math.round(record.weeks_since_last_game) === 0
                        ? "Played latest week"
                        : String(Math.round(record.weeks_since_last_game))}
                    </td>
                    <td className="muted col-annotation">{record.current_status ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </>
  );
}
