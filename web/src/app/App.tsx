/**
 * The application shell.
 *
 * One page, three tabs, state in the URL. The load path splits critical from degradable: a
 * bad `build_metadata.json` or `tiers.json` produces a refusal, while a missing arbitrage,
 * status or projections artifact degrades a feature and leaves every intrinsic number exactly
 * as the build produced it (`docs/DATA_CONTRACTS.md` section 13, `docs/UX_SPEC.md` section 10).
 */

import { useCallback, useEffect, useMemo, useState } from "react";

import logoUrl from "../assets/jt_logo.png";

import { CriticalArtifactError, loadBundle, type Degradation } from "../data/bundle";
import { easternIsoDate } from "../data/format";
import { cohortAssignment } from "../data/market";
import { selectArbitrageRows, selectTierRows, type ArtifactIndex } from "../data/model";
import { selectOpportunityRows, selectRosRows, type InSeasonBundle } from "../data/ros";
import {
  SCORING_TO_PRESET,
  leaguePresetId,
  resolveMode,
  resolveView,
  type ScoringValue,
  type TeamCount,
} from "../data/state";
import { TEAM_COUNTS, SCORING_VALUES } from "../data/state";
import { ArbitrageView } from "./ArbitrageView";
import { Controls, SeasonMode, SeasonModeChip, ViewTabs } from "./Controls";
import { DataView } from "./DataView";
import { Masthead } from "./Masthead";
import { OpportunityView } from "./OpportunityView";
import { PlayerDetail, type PlayerDetailData } from "./PlayerDetail";
import { RosView } from "./RosView";
import { TiersView } from "./TiersView";
import { useAppState } from "./useAppState";

type LoadState =
  | { readonly status: "loading" }
  | {
      readonly status: "ready";
      readonly index: ArtifactIndex;
      readonly degradations: readonly Degradation[];
      readonly inSeason: InSeasonBundle | null;
    }
  | { readonly status: "error"; readonly error: CriticalArtifactError };

/**
 * `now` exists for the same reason `Masthead` already accepts one: freshness is measured
 * against the clock, and a test that renders a fixed fixture board must be able to say what
 * time it is. Production never passes it, so the default is the real clock.
 */
export function App({ now }: { readonly now?: Date } = {}): React.JSX.Element {
  const [load, setLoad] = useState<LoadState>({ status: "loading" });
  const { state, setState } = useAppState();
  const [selectedPlayerId, setSelectedPlayerId] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    loadBundle()
      .then((bundle) => {
        if (!cancelled) {
          setLoad({
            status: "ready",
            index: bundle.index,
            degradations: bundle.degradations,
            inSeason: bundle.inSeason,
          });
        }
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        setLoad({
          status: "error",
          error:
            error instanceof CriticalArtifactError
              ? error
              : new CriticalArtifactError("artifacts", error),
        });
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const onSelect = useCallback((playerId: string) => {
    setSelectedPlayerId(playerId);
  }, []);
  const onCloseDetail = useCallback(() => {
    setSelectedPlayerId(null);
  }, []);

  if (load.status === "loading") {
    return (
      <main className="app">
        <p role="status" className="muted" style={{ padding: "2rem 0" }}>
          Loading the board…
        </p>
      </main>
    );
  }

  if (load.status === "error") {
    return <CriticalError error={load.error} />;
  }

  return (
    <Board
      index={load.index}
      inSeason={load.inSeason}
      degradations={load.degradations}
      state={state}
      setState={setState}
      selectedPlayerId={selectedPlayerId}
      onSelect={onSelect}
      onCloseDetail={onCloseDetail}
      now={now}
    />
  );
}

function Board({
  index,
  inSeason,
  degradations,
  state,
  setState,
  selectedPlayerId,
  onSelect,
  onCloseDetail,
  now,
}: {
  readonly index: ArtifactIndex;
  /** The in-season bundle, or null before kickoff. See `LoadedBundle.inSeason`. */
  readonly inSeason: InSeasonBundle | null;
  readonly degradations: readonly Degradation[];
  readonly state: ReturnType<typeof useAppState>["state"];
  readonly setState: ReturnType<typeof useAppState>["setState"];
  readonly selectedPlayerId: string | null;
  readonly onSelect: (playerId: string) => void;
  readonly onCloseDetail: () => void;
  /**
   * Injected only by tests; the masthead's freshness clock (see `App`). Spelled
   * `| undefined` because `exactOptionalPropertyTypes` distinguishes an absent
   * property from a present one holding `undefined`, and `App` forwards the latter.
   */
  readonly now?: Date | undefined;
}): React.JSX.Element {
  const metadata = index.metadata;
  const buildDate = easternIsoDate(metadata.generated_at_utc);

  // The mode in force, and the panel it resolves to. Derived from the season state the build
  // recorded — which is derived from the NFL schedule, never from a date in this file —
  // unless the reader has overridden it, in which case the override wins and is in the URL.
  const mode = resolveMode(state.mode, inSeason?.derivedMode ?? null);
  const view = resolveView(state.view, mode);

  // Only offer a control value the build actually published; a preset with no rows would
  // otherwise present as an empty board rather than as an option that does not exist.
  const { availableScoring, availableTeams } = useMemo(() => {
    const scoring = new Set<ScoringValue>();
    const teams = new Set<TeamCount>();
    for (const block of index.availableBlocks()) {
      for (const value of SCORING_VALUES) {
        if (SCORING_TO_PRESET[value] === block.scoring) scoring.add(value);
      }
      for (const count of TEAM_COUNTS) {
        if (leaguePresetId(count) === block.leaguePreset) teams.add(count);
      }
    }
    return { availableScoring: scoring, availableTeams: teams };
  }, [index]);

  const openData = useCallback(() => {
    setState({ view: "data" });
  }, [setState]);

  /**
   * The row count beside the navigation, from the design source.
   *
   * `shown` is what the current filters select and `total` is what the build published for the
   * active preset. Both are counts of artifact rows; the Data view has no board and shows
   * none. This is a filter readout, not a derived quantity.
   */
  const rowCount = useMemo(() => {
    const leaguePreset = leaguePresetId(state.teams);
    const scoring = SCORING_TO_PRESET[state.scoring];
    if (view === "tiers") {
      return {
        shown: selectTierRows(index, state).length,
        total: index.tiersFor(leaguePreset, scoring).length,
      };
    }
    if (view === "arbitrage" && index.hasArbitrage) {
      return {
        shown: selectArbitrageRows(index, state).length,
        total: index.arbitrageFor(leaguePreset, scoring).length,
      };
    }
    if (view === "ros" && inSeason !== null) {
      return {
        shown: selectRosRows(inSeason, state).length,
        total: inSeason.rosFor(leaguePreset, scoring).length,
      };
    }
    if (view === "opportunity" && inSeason !== null) {
      return {
        shown: selectOpportunityRows(inSeason, state).length,
        total: inSeason.opportunityFor(leaguePreset, scoring).length,
      };
    }
    return undefined;
  }, [index, inSeason, state, view]);

  const detail: PlayerDetailData | null = useMemo(() => {
    if (selectedPlayerId === null) return null;
    const leaguePreset = leaguePresetId(state.teams);
    const scoring = SCORING_TO_PRESET[state.scoring];
    return {
      playerId: selectedPlayerId,
      tier: index.tierFor(leaguePreset, scoring, selectedPlayerId),
      arbitrage: index.arbitrageRecordFor(leaguePreset, scoring, selectedPlayerId),
      status: index.statusFor(selectedPlayerId),
      projection: index.projectionFor(scoring, selectedPlayerId),
      ros: inSeason?.rosRecordFor(leaguePreset, scoring, selectedPlayerId) ?? null,
      rosDisclosures: inSeason?.metadata.disclosures ?? null,
      marketAvailable: index.hasArbitrage,
      cohortExact: cohortAssignment(metadata, scoring, state.teams)?.exact ?? null,
      // The chart's own data, keyed by the market the reader has selected: switching the
      // selector must change the history, not relabel it (roadmap 10.7). Null until the
      // retained store holds enough of it, which the card renders as a truthful sentence.
      market: state.market,
      trendSeries: index.trendSeries(
        leaguePreset,
        scoring,
        state.market,
        selectedPlayerId,
      ),
    };
  }, [index, inSeason, metadata, selectedPlayerId, state.scoring, state.teams, state.market]);

  return (
    <>
      <a className="skip-link" href="#board">
        Skip to the board
      </a>
      <div className="app">
        <Masthead
          metadata={metadata}
          degradations={degradations}
          now={now}
          onOpenData={openData}
          seasonMode={
            <SeasonModeChip
              resolved={mode}
              seasonState={inSeason?.seasonState ?? "preseason_draft"}
              throughWeek={inSeason?.throughWeek ?? null}
            />
          }
        />

        <SeasonMode
          mode={state.mode}
          resolved={mode}
          throughWeek={inSeason?.throughWeek ?? null}
          available={inSeason !== null}
          onChange={(next) => {
            setState({ mode: next });
          }}
        />

        <div className="sticky-controls">
          <Controls
            state={state}
            onChange={setState}
            availableScoring={availableScoring}
            availableTeams={availableTeams}
          />
          <ViewTabs
            view={view}
            mode={mode}
            arbitrageAvailable={index.hasArbitrage}
            rowCount={rowCount}
            onChange={(next) => {
              setState({ view: next });
            }}
          />
        </div>

        <main id="board">
          <div
            role="tabpanel"
            id={`panel-${view}`}
            aria-labelledby={`tab-${view}`}
            tabIndex={-1}
          >
            {view === "tiers" && (
              <TiersView
                index={index}
                state={state}
                onChange={setState}
                onSelect={onSelect}
                selectedPlayerId={selectedPlayerId}
                buildDate={buildDate}
              />
            )}
            {view === "arbitrage" && (
              <ArbitrageView
                index={index}
                state={state}
                onChange={setState}
                onSelect={onSelect}
                selectedPlayerId={selectedPlayerId}
                buildDate={buildDate}
                available={index.hasArbitrage}
                onOpenData={openData}
              />
            )}
            {view === "ros" &&
              (inSeason === null ? (
                <NoInSeasonBundle />
              ) : (
                <RosView
                  bundle={inSeason}
                  state={state}
                  onSelect={onSelect}
                  selectedPlayerId={selectedPlayerId}
                />
              ))}
            {view === "opportunity" &&
              (inSeason === null ? (
                <NoInSeasonBundle />
              ) : (
                <OpportunityView
                  bundle={inSeason}
                  state={state}
                  onChange={setState}
                  onSelect={onSelect}
                  selectedPlayerId={selectedPlayerId}
                />
              ))}
            {view === "data" && (
              <DataView
                index={index}
                inSeason={inSeason}
                state={state}
                degradations={degradations}
              />
            )}
          </div>
        </main>

        <footer className="footer">
          <span>
            {/* The models actually behind what is on screen. In-season the board is served by
                a different model with a different horizon, and naming only the draft one here
                would attribute a rest-of-season number to a model that never produced it. */}
            {mode === "in_season" && inSeason !== null
              ? `${inSeason.metadata.ros_model_version} · ${inSeason.metadata.methodology_version}`
              : `${metadata.intrinsic_model_version} · ${metadata.arbitrage_method_version ?? "no arbitrage"}`}{" "}
            · build {metadata.build_id}
          </span>
          <span>
            Intrinsic tiers use no market or expert-rank input. Injury status is annotation only.
          </span>
          <span>
            Data: nflverse, ffopportunity, MyFantasyLeague, Sleeper (non-commercial). Free, no ads.
          </span>
        </footer>
      </div>

      <PlayerDetail data={detail} onClose={onCloseDetail} onOpenData={openData} />
    </>
  );
}

/**
 * What an in-season tab shows when there is no in-season bundle.
 *
 * Reachable two ways, and both are ordinary rather than broken: a link to `?view=ros` opened
 * before kickoff, and an in-season refresh that failed its gate so the previous deploy stayed.
 * Either way the draft board beside it is correct and current, which is what the message says.
 */
function NoInSeasonBundle(): React.JSX.Element {
  return (
    <section className="section">
      <div className="notice" data-severity="info" role="note">
        <strong>No rest-of-season board has been published yet.</strong>
        <p style={{ marginTop: "0.5rem" }}>
          The rest-of-season model needs at least one completed week of the current season, and
          the week&rsquo;s upstream data has to be complete before a board is built at that
          cutoff. Until then the draft board is the current product, and it is unaffected.
        </p>
      </div>
    </section>
  );
}

/**
 * The refusal.
 *
 * A schema the site does not understand is shown as expected-versus-received rather than as a
 * blank page, because the alternative — rendering a tier board from a contract we half
 * understand — is the one failure mode that looks fine and is wrong on draft day.
 */
function CriticalError({ error }: { readonly error: CriticalArtifactError }): React.JSX.Element {
  return (
    <main className="app">
      <header className="masthead">
        <h1 className="masthead-brand">
          <img className="masthead-logo" src={logoUrl} alt="Jeisey Tiers" width={434} height={145} />
        </h1>
      </header>
      <div className="notice" data-severity="error" role="alert" style={{ marginTop: "1.5rem" }}>
        <strong>
          {error.incompatible ? "Incompatible data contract" : "The board could not be loaded"}
        </strong>
        <p style={{ marginTop: "0.5rem" }}>{error.message}</p>
        {error.incompatible && (
          <dl className="facts" style={{ marginTop: "0.75rem" }}>
            <div>
              <dt>Artifact</dt>
              <dd>{error.artifact}</dd>
            </div>
            <div>
              <dt>Expected major version</dt>
              <dd>{error.expected ?? "—"}</dd>
            </div>
            <div>
              <dt>Received</dt>
              <dd>{error.found ?? "—"}</dd>
            </div>
          </dl>
        )}
        <p style={{ marginTop: "0.75rem" }}>
          Nothing is rendered from a contract this build does not understand. Regenerate the
          artifacts with <code>uv run ffdraft build-current</code> and{" "}
          <code>uv run ffdraft build-arbitrage</code>, then reload.
        </p>
      </div>
    </main>
  );
}
