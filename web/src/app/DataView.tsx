/**
 * Data and methodology: a compact reference surface, not a blog.
 *
 * Everything that can be read from `build_metadata.json` is read from it — the model version,
 * the methodology version, the arbitrage method, source retrieval times, warnings, the cohort
 * assignment and its failed clauses. No metric is hardcoded here; the detailed model
 * methodology links to the generated cards in the repository, which are produced by
 * `ffdraft model-card` and `ffdraft arbitrage-card` rather than written by hand.
 *
 * The limitations section is the point of the page. Every item in it is a measured, published
 * finding this product chose not to hide.
 */

import type { Degradation } from "../data/bundle";
import { formatEastern, formatInteger } from "../data/format";
import { CONFIDENCE_MEANING, cohortAssignment, explainClause, marketSourceLabel } from "../data/market";
import type { ArtifactIndex } from "../data/model";
import { SCORING_TO_PRESET, type AppState } from "../data/state";

const REPO = "https://github.com/jeisey/jeisey-tiers";

const SOURCE_LABELS: Readonly<Record<string, string>> = {
  nflreadpy: "nflverse (via nflreadpy)",
  ffopportunity: "ffopportunity expected points",
  myfantasyleague_adp: "MyFantasyLeague ADP export",
  sleeper: "Sleeper",
};

export function DataView({
  index,
  state,
  degradations,
}: {
  readonly index: ArtifactIndex;
  readonly state: AppState;
  readonly degradations: readonly Degradation[];
}): React.JSX.Element {
  const metadata = index.metadata;
  const assignment = cohortAssignment(metadata, SCORING_TO_PRESET[state.scoring], state.teams);
  const market = metadata.market;

  return (
    <div className="section">
      <section className="section" aria-labelledby="what-heading">
        <h2 id="what-heading">What this is</h2>
        <div className="prose">
          <p>
            <strong>Tier board</strong> — intrinsic, league-relative football value. The model
            behind it has never seen an average draft position, an expert consensus rank, or any
            other market signal. That firewall is enforced in code and checked by a test that
            walks the import graph, not by convention.
          </p>
          <p>
            <strong>Arbitrage</strong> — a deterministic comparison of that fair rank against{" "}
            {marketSourceLabel(market?.source_id ?? "myfantasyleague_adp")}. It is arithmetic,
            not a learned model: public historical ADP is a season-long aggregate recomputed at
            request time, so a "market cost" for a past season would include drafts held after
            the season was partly known. Nothing here is labelled ML, because nothing here is.
          </p>
        </div>
      </section>

      <section className="section" aria-labelledby="definitions-heading">
        <h2 id="definitions-heading">Definitions</h2>
        <dl className="definition-grid">
          <div>
            <dt>Fair rank</dt>
            <dd>
              The board order, 1-based and unique within a preset. It is the player&apos;s median
              simulated VORP, not his expected VORP.
            </dd>
          </div>
          <div>
            <dt>VORP</dt>
            <dd>
              Value over replacement. Every simulated season allocates starters and FLEX under
              your league&apos;s roster shape and derives that draw&apos;s own replacement level,
              so scarcity is simulated rather than subtracted.
            </dd>
          </div>
          <div>
            <dt>Expected vs median VORP</dt>
            <dd>
              Expected is the mean across draws and median is the middle draw. They differ most
              for players whose distribution is skewed by missed games.
            </dd>
          </div>
          <div>
            <dt>P25–P75, P10–P90</dt>
            <dd>
              Prediction intervals from the same simulation. The inner range is the whisker on
              the tier board; the outer is the lighter line behind it.
            </dd>
          </div>
          <div>
            <dt>Uncertainty</dt>
            <dd>The width of the player&apos;s simulated value distribution, in fantasy points.</dd>
          </div>
          <div>
            <dt>MFL ADP</dt>
            <dd>
              The average pick at which a player was drafted across the selected MyFantasyLeague
              cohort. Lower is earlier and more expensive.
            </dd>
          </div>
          <div>
            <dt>Value gap</dt>
            <dd>
              ADP minus fair rank. Positive means the market drafts him later than the model
              would, which is the bargain direction.
            </dd>
          </div>
          <div>
            <dt>Arbitrage score</dt>
            <dd>
              A 0–100 ordering within a preset, from the log ratio of ADP to fair rank. Eight
              picks between rank 3 and ADP 11 is a round of value; eight picks between 180 and
              188 is noise, and the log ratio is what tells them apart.
            </dd>
          </div>
          <div>
            <dt>Market-data confidence</dt>
            <dd>{CONFIDENCE_MEANING}</dd>
          </div>
        </dl>
      </section>

      <section className="section" aria-labelledby="model-heading">
        <h2 id="model-heading">Current build</h2>
        <div className="table-scroll">
          <table className="sheet">
            <caption>Read from the build metadata this page loaded.</caption>
            <tbody>
              <BuildRow label="Build id" value={metadata.build_id} />
              <BuildRow label="Generated" value={formatEastern(metadata.generated_at_utc)} />
              <BuildRow label="Season" value={String(metadata.season)} />
              <BuildRow label="Intrinsic model" value={metadata.intrinsic_model_version} />
              <BuildRow label="Methodology version" value={metadata.methodology_version} />
              <BuildRow
                label="Arbitrage"
                value={`${metadata.arbitrage_mode} · ${metadata.arbitrage_method_version ?? "—"}`}
              />
              <BuildRow label="Presets" value={metadata.supported_presets.join(", ")} />
              <BuildRow
                label="Quality gate"
                value={`${metadata.quality_gate.status} — ${String(metadata.quality_gate.critical_failures)} critical, ${String(metadata.quality_gate.warnings)} warning`}
              />
              {market !== null && market !== undefined && (
                <>
                  <BuildRow label="Market snapshot" value={formatEastern(market.snapshot_at_utc)} />
                  <BuildRow
                    label="Cohort rule"
                    value={`${market.cohort_rule_version ?? "—"} · confidence ${market.confidence_rubric_version ?? "—"} · trend ${market.trend_rule_version ?? "—"}`}
                  />
                </>
              )}
              {metadata.player_status !== null && metadata.player_status !== undefined && (
                <BuildRow
                  label="Status annotation"
                  value={`${formatInteger(metadata.player_status.players)} players, ${formatInteger(metadata.player_status.sleeper_matched)} matched to Sleeper, observed ${formatEastern(metadata.player_status.observed_at_utc)}`}
                />
              )}
            </tbody>
          </table>
        </div>
        <p className="section-note" style={{ marginTop: "0.5rem" }}>
          Full model methodology, including holdout metrics and the tier-stability measurement,
          lives in the generated model cards:{" "}
          <a href={`${REPO}/blob/main/models/cards/intrinsic-cb-hurdle-v1.md`}>intrinsic model</a>,{" "}
          <a href={`${REPO}/blob/main/models/cards/tier-method.md`}>tier method</a>,{" "}
          <a href={`${REPO}/blob/main/models/cards/arbitrage-method-a0.md`}>arbitrage method</a>.
        </p>
      </section>

      <section className="section" aria-labelledby="freshness-heading">
        <h2 id="freshness-heading">Freshness and source status</h2>
        <div className="table-scroll">
          <table className="sheet">
            <caption>Every row is reported by the build, not inferred by this page.</caption>
            <thead>
              <tr>
                <th scope="col" className="plain">
                  Source
                </th>
                <th scope="col" className="plain">
                  Retrieved
                </th>
                <th scope="col" className="plain">
                  Status
                </th>
                <th scope="col" className="plain">
                  Notes
                </th>
              </tr>
            </thead>
            <tbody>
              {metadata.sources.map((source) => (
                <tr key={source.source_id}>
                  <td>{SOURCE_LABELS[source.source_id] ?? source.source_id}</td>
                  <td className="muted">{formatEastern(source.retrieved_at_utc)}</td>
                  <td>{source.status}</td>
                  <td className="muted" style={{ whiteSpace: "normal" }}>
                    {(source.warnings ?? []).join(", ") || "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {degradations.length > 0 && (
          <div className="notice" data-severity="warning" style={{ marginTop: "0.75rem" }}>
            <strong>Degraded artifacts.</strong>
            <ul className="limitations" style={{ marginTop: "0.5rem" }}>
              {degradations.map((entry) => (
                <li key={entry.artifact}>
                  <strong>{entry.artifact}</strong>{" "}
                  {entry.reason === "incompatible"
                    ? "declares a schema version this site does not support and was refused."
                    : "could not be loaded for this build."}{" "}
                  {entry.artifact === "arbitrage" &&
                    "Tier values are unaffected; the arbitrage view is unavailable."}
                  {entry.artifact === "player_status" &&
                    "All model values are unchanged; injury and roster annotations are absent."}
                  {entry.artifact === "projections" &&
                    "Tier and arbitrage boards are unaffected; some player detail is thinner."}
                </li>
              ))}
            </ul>
          </div>
        )}

        {metadata.warnings.length > 0 && (
          <>
            <h3 style={{ marginTop: "1rem" }}>Build notes</h3>
            <ul className="limitations">
              {metadata.warnings.map((warning, position) => (
                <li key={`${String(position)}-${warning.slice(0, 24)}`}>{warning}</li>
              ))}
            </ul>
          </>
        )}
      </section>

      <div className="data-columns">
      <section className="section" aria-labelledby="market-heading">
        <h2 id="market-heading">Market provenance</h2>
        <div className="prose">
          <p>
            The market price is {marketSourceLabel(market?.source_id ?? "myfantasyleague_adp")} and
            only that. This product has not built a multi-source consensus and does not call it
            one.
          </p>
          {assignment !== null && (
            <p>
              For {state.scoring.toUpperCase()} at {state.teams} teams the board is priced by the{" "}
              <code>{assignment.cohortId}</code> cohort ({assignment.sourceFormatDetail}
              {assignment.exact ? ", exact for this preset" : ""}).{" "}
              {assignment.failedClauses.length > 0 && (
                <>
                  It did not clear the frozen sufficiency rule:{" "}
                  {assignment.failedClauses.map(explainClause).join("; ")}. Every row on that board
                  therefore carries low market-data confidence, which is a statement about the
                  evidence behind the price and not about the player.
                </>
              )}
            </p>
          )}
          <p>
            The retained snapshot behind these prices was taken{" "}
            {formatEastern(market?.snapshot_at_utc)}. MyFantasyLeague publishes no data-as-of time
            and no standard deviation, so dispersion is shown as the earliest and latest observed
            picks. Those are extreme single observations that widen with sample size, so they
            describe a range rather than a disagreement.
          </p>
        </div>
      </section>

      <section className="section" aria-labelledby="limitations-heading">
        <h2 id="limitations-heading">Current limitations</h2>
        <ul className="limitations">
          <li>
            <strong>Exact tier edges are soft.</strong> Tier membership reproduces across
            resamples; the precise cut positions do not. Read a tier as a group of comparable
            players, and treat two players either side of an edge as close rather than different
            in kind.
          </li>
          <li>
            <strong>The simulation has a measured convergence limitation.</strong> At the
            published draw count, two random seeds agree closely on ranking and less closely on
            value: a player&apos;s expected VORP moves by a fraction of a point and the tier cuts
            move more than that. A build is exactly reproducible for a fixed seed; it is not
            seed-invariant.
          </li>
          <li>
            <strong>MyFantasyLeague is the only market source in V1.</strong> There is no
            cross-platform consensus behind the ADP shown here.
          </li>
          <li>
            <strong>The redraft market population is early.</strong> Filtering to keeper-free
            drafts is required to price a redraft board correctly — in dynasty rookie drafts a
            rookie&apos;s average pick is a pick number in a rookie-only draft — and that filter
            shrinks the cohort. The population will fill out on its own as draft season matures.
          </li>
          <li>
            <strong>Standard and half-PPR are priced by an all-scoring cohort.</strong>{" "}
            MyFantasyLeague exposes a PPR flag and no half-PPR filter, so those two boards are
            priced largely by PPR drafters.
          </li>
          <li>
            <strong>Injury and roster status is annotation only.</strong> Nothing in it entered a
            projection, a fair rank, a tier or an arbitrage score. An absent injury designation is
            the absence of a report, not a clearance.
          </li>
          <li>
            <strong>Market trend needs history we are still collecting.</strong> A trend is
            measured over our own retained snapshots and needs at least three observation days
            spanning three days. Until then it is blank, which is not the same as flat.
          </li>
          <li>
            <strong>Rookie projections are lower-information.</strong> With no NFL production
            history, a rookie&apos;s projection rests on draft capital, biography and team
            context.
          </li>
          <li>
            <strong>Players are simulated independently.</strong> The simulation cannot express
            that a quarterback&apos;s collapse takes his receivers with him. That is the largest
            structural simplification in it.
          </li>
          <li>
            <strong>Some ranked players carry no market price.</strong> They stay fully ranked on
            the tier board and are absent from the arbitrage board, because there is nothing to
            compare them against.
            {market?.unpriced_top_players !== undefined &&
              ` In this build ${formatInteger(market.unpriced_top_players)} top-150 board rows are affected.`}
          </li>
        </ul>
      </section>

      <section className="section" aria-labelledby="sources-heading">
        <h2 id="sources-heading">Sources and attribution</h2>
        <ul className="source-list">
          <li>
            <strong>nflverse</strong> — play-by-play, rosters, depth charts, snap counts, draft and
            combine data, accessed through nflreadpy. Data is broadly CC-BY 4.0 and belongs to its
            respective owners.{" "}
            <a href="https://github.com/nflverse/nflverse-data">nflverse-data</a>
          </li>
          <li>
            <strong>ffopportunity</strong> — expected fantasy points, CC-BY-SA 4.0.{" "}
            <a href="https://ffopportunity.ffverse.com/">ffopportunity</a>
          </li>
          <li>
            <strong>MyFantasyLeague</strong> — the public ADP export, read with a registered
            developer client User-Agent under MyFantasyLeague&apos;s published developer rules.{" "}
            <a href="https://api.myfantasyleague.com/">MyFantasyLeague API</a>
          </li>
          <li>
            <strong>Sleeper</strong> — current player status and injury designations, used for
            annotation only. The Sleeper API is free for non-commercial use; this site is free and
            non-commercial and carries no advertising, affiliate links or paid tier.{" "}
            <a href="https://docs.sleeper.com/">Sleeper API docs</a>
          </li>
        </ul>
        <p className="section-note" style={{ marginTop: "0.75rem" }}>
          Source code, model cards and the full decision record are in the{" "}
          <a href={REPO}>project repository</a>.
        </p>
      </section>
      </div>
    </div>
  );
}

function BuildRow({
  label,
  value,
}: {
  readonly label: string;
  readonly value: string;
}): React.JSX.Element {
  return (
    <tr>
      <th scope="row" className="plain" style={{ width: "12rem", position: "static" }}>
        {label}
      </th>
      <td className="mono" style={{ whiteSpace: "normal" }}>
        {value}
      </td>
    </tr>
  );
}
