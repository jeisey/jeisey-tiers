/**
 * The application shell.
 *
 * One page, three tabs, state in the URL. The load path splits critical from degradable: a
 * bad `build_metadata.json` or `tiers.json` produces a refusal, while a missing arbitrage,
 * status or projections artifact degrades a feature and leaves every intrinsic number exactly
 * as the build produced it (`docs/DATA_CONTRACTS.md` section 13, `docs/UX_SPEC.md` section 10).
 */

import { useCallback, useEffect, useMemo, useState } from "react";

import { CriticalArtifactError, loadBundle, type Degradation } from "../data/bundle";
import { easternIsoDate } from "../data/format";
import { type ArtifactIndex } from "../data/model";
import { SCORING_TO_PRESET, leaguePresetId, type ScoringValue, type TeamCount } from "../data/state";
import { TEAM_COUNTS, SCORING_VALUES } from "../data/state";
import { ArbitrageView } from "./ArbitrageView";
import { Controls, ViewTabs } from "./Controls";
import { DataView } from "./DataView";
import { Masthead } from "./Masthead";
import { PlayerDetail, type PlayerDetailData } from "./PlayerDetail";
import { TiersView } from "./TiersView";
import { useAppState } from "./useAppState";

type LoadState =
  | { readonly status: "loading" }
  | { readonly status: "ready"; readonly index: ArtifactIndex; readonly degradations: readonly Degradation[] }
  | { readonly status: "error"; readonly error: CriticalArtifactError };

export function App(): React.JSX.Element {
  const [load, setLoad] = useState<LoadState>({ status: "loading" });
  const { state, setState } = useAppState();
  const [selectedPlayerId, setSelectedPlayerId] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    loadBundle()
      .then((bundle) => {
        if (!cancelled) {
          setLoad({ status: "ready", index: bundle.index, degradations: bundle.degradations });
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
      degradations={load.degradations}
      state={state}
      setState={setState}
      selectedPlayerId={selectedPlayerId}
      onSelect={onSelect}
      onCloseDetail={onCloseDetail}
    />
  );
}

function Board({
  index,
  degradations,
  state,
  setState,
  selectedPlayerId,
  onSelect,
  onCloseDetail,
}: {
  readonly index: ArtifactIndex;
  readonly degradations: readonly Degradation[];
  readonly state: ReturnType<typeof useAppState>["state"];
  readonly setState: ReturnType<typeof useAppState>["setState"];
  readonly selectedPlayerId: string | null;
  readonly onSelect: (playerId: string) => void;
  readonly onCloseDetail: () => void;
}): React.JSX.Element {
  const metadata = index.metadata;
  const buildDate = easternIsoDate(metadata.generated_at_utc);

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
      marketAvailable: index.hasArbitrage,
    };
  }, [index, selectedPlayerId, state.scoring, state.teams]);

  return (
    <>
      <a className="skip-link" href="#board">
        Skip to the board
      </a>
      <div className="app">
        <Masthead
          metadata={metadata}
          degradations={degradations}
          onOpenData={() => {
            setState({ view: "data" });
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
            view={state.view}
            arbitrageAvailable={index.hasArbitrage}
            onChange={(view) => {
              setState({ view });
            }}
          />
        </div>

        <main id="board">
          <div
            role="tabpanel"
            id={`panel-${state.view}`}
            aria-labelledby={`tab-${state.view}`}
            tabIndex={-1}
          >
            {state.view === "tiers" && (
              <TiersView
                index={index}
                state={state}
                onChange={setState}
                onSelect={onSelect}
                selectedPlayerId={selectedPlayerId}
                buildDate={buildDate}
              />
            )}
            {state.view === "arbitrage" && (
              <ArbitrageView
                index={index}
                state={state}
                onChange={setState}
                onSelect={onSelect}
                selectedPlayerId={selectedPlayerId}
                buildDate={buildDate}
                available={index.hasArbitrage}
              />
            )}
            {state.view === "data" && (
              <DataView index={index} state={state} degradations={degradations} />
            )}
          </div>
        </main>

        <footer className="footer">
          <span>
            {metadata.intrinsic_model_version} · {metadata.arbitrage_method_version ?? "no arbitrage"}{" "}
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

      <PlayerDetail data={detail} onClose={onCloseDetail} />
    </>
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
        <div className="wordmark">
          ffdraft <span>· tiers &amp; arbitrage</span>
        </div>
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
