/**
 * The ROS Tier Board: the in-season answer, in the draft board's own visual language.
 *
 * Reused deliberately rather than redesigned. Roadmap 12.4 asks for one product with two
 * modes, not two products, so the section rhythm, the numbered heads, the legend strip and
 * the table are the ones the Tier Board established; what changes is the quantity and the
 * disclosures around it.
 *
 * Four things this view is obliged to say, and says in text rather than by implication:
 *
 * 1. **This is rest-of-season value**, from an explicit cutoff week, and it is not the
 *    preseason fair rank. The heading, the caption and every column name carry it.
 * 2. **A tier is a band.** The boundary failed the frozen stability gate (ADR-074), so the
 *    board never draws an edge as a fact — the same treatment Release 1 gave preseason tiers.
 * 3. **No injury or practice-report information is used** (ADR-070, ADR-076). The sentence
 *    comes from the artifact, so the interface cannot drift from what the model actually did.
 * 4. **Ordering inside the long-absence cohort is weak**, measured and published, shown where
 *    those rows are rather than filed away in a methodology page.
 */

import { useMemo, useRef } from "react";

import { Notice, SectionHead } from "../components/primitives";
import { rosRowsToCsv } from "../data/csv";
import { groupRosByTier, selectRosRows, type InSeasonBundle, type RosRow } from "../data/ros";
import { SCORING_LABELS, type AppState } from "../data/state";
import { ExportControls } from "./ExportControls";
import { RosTable } from "./RosTable";

export const ROS_BAND_NOTE =
  "Rest-of-season tiers are bands, not lines. Membership reproduces across resamples; the " +
  "exact cut positions do not, so read a player near an edge as belonging to both.";

export function RosView({
  bundle,
  state,
  onSelect,
  selectedPlayerId,
}: {
  readonly bundle: InSeasonBundle;
  readonly state: AppState;
  readonly onSelect: (playerId: string) => void;
  readonly selectedPlayerId: string | null;
}): React.JSX.Element {
  const rows = useMemo(() => selectRosRows(bundle, state), [bundle, state]);
  const visibleRows = useRef<readonly RosRow[]>(rows);
  const groups = useMemo(() => groupRosByTier(rows), [rows]);
  const metadata = bundle.metadata;
  const disclosures = metadata.disclosures;
  const flagged = useMemo(() => rows.filter((row) => row.record.long_absence).length, [rows]);
  const buildDate = metadata.generated_at_utc.slice(0, 10);

  return (
    <>
      <section className="section" aria-labelledby="ros-summary-heading">
        <SectionHead
          index="01"
          id="ros-summary-heading"
          title={`Rest of season — through week ${String(metadata.through_week)}`}
          note={
            `Every value below is what is left of ${String(metadata.season)}, estimated from ` +
            `weeks 1–${String(metadata.through_week)} only. These are not the preseason ` +
            "numbers: a different model, a different horizon, and a different replacement " +
            "baseline (the best player nobody rosters, not the best nobody starts)."
          }
        />

        {/*
          The disclosure block. It is rendered from the artifact rather than from constants in
          this file, so a build that changed what the model reads would change these sentences
          too — the interface cannot claim a property the model no longer has.
        */}
        <div className="notice" data-severity="info" role="note">
          <strong>What this estimate does and does not know</strong>
          <p style={{ marginTop: "0.5rem" }}>{disclosures.long_absence_statement}</p>
          <p style={{ marginTop: "0.5rem" }}>{disclosures.long_absence_ordering_weakness}</p>
          {disclosures.tier_boundary_statement !== undefined && (
            <p style={{ marginTop: "0.5rem" }}>{disclosures.tier_boundary_statement}</p>
          )}
          <p className="muted" style={{ marginTop: "0.5rem" }}>
            {`${String(disclosures.long_absence_players)} player${
              disclosures.long_absence_players === 1 ? "" : "s"
            } on the published board carr${
              disclosures.long_absence_players === 1 ? "ies" : "y"
            } this flag; ${String(flagged)} ${flagged === 1 ? "is" : "are"} in the current view. `}
            A long absence here means: {disclosures.long_absence_definition}.
          </p>
        </div>

        <dl className="facts" style={{ marginTop: "0.75rem" }}>
          <div>
            <dt>Cutoff</dt>
            <dd>{`Through week ${String(metadata.through_week)} (${metadata.cutoff_rule_version})`}</dd>
          </div>
          <div>
            <dt>Season state</dt>
            <dd>{metadata.season_state.season_state.replace(/_/g, " ")}</dd>
          </div>
          <div>
            <dt>Model</dt>
            <dd>{metadata.ros_model_version}</dd>
          </div>
          <div>
            <dt>Replacement</dt>
            <dd>{metadata.simulation.replacement_rule.replace(/_/g, " ")}</dd>
          </div>
          <div>
            <dt>Draws</dt>
            <dd>
              {String(metadata.simulation.draws)}
              {metadata.simulation.convergence_gate === "fail" && " (declared fallback)"}
            </dd>
          </div>
          <div>
            <dt>Data complete through</dt>
            <dd>{`week ${String(metadata.source_freshness.available_through_week)}`}</dd>
          </div>
        </dl>

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
            P25–P75 simulated remaining VORP; the mark is the median
          </span>
          <span className="legend-item">{ROS_BAND_NOTE}</span>
          <span className="legend-item muted">
            {`${String(groups.length)} tier band${groups.length === 1 ? "" : "s"} across ${String(rows.length)} shown player${rows.length === 1 ? "" : "s"}`}
          </span>
        </div>
      </section>

      <section className="section" aria-labelledby="ros-table-heading">
        <SectionHead
          index="02"
          id="ros-table-heading"
          title="Rest-of-season table"
          note={
            "ROS rank is the published order — sorting re-orders these rows without changing " +
            "it. Current status is annotation and reached no model input."
          }
        >
          <ExportControls
            board="ros_tiers"
            scoring={state.scoring}
            teams={state.teams}
            buildDate={buildDate}
            throughWeek={metadata.through_week}
            filteredCount={rows.length}
            buildFilteredCsv={() => rosRowsToCsv(visibleRows.current)}
          />
        </SectionHead>

        {rows.length === 0 ? (
          <Notice title="No players match.">
            {state.search === ""
              ? "This position filter returns nothing for the selected preset."
              : `No player on the ${SCORING_LABELS[state.scoring]} rest-of-season board matches “${state.search}”.`}
          </Notice>
        ) : (
          <RosTable
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
