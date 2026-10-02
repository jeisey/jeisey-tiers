/**
 * The application shell.
 *
 * One page, three tabs, state in the URL. The load path splits critical from degradable: a
 * bad `build_metadata.json` or `tiers.json` produces a refusal, while a missing arbitrage,
 * status or projections artifact degrades a feature and leaves every intrinsic number exactly
 * as the build produced it (`docs/DATA_CONTRACTS.md` section 13, `docs/UX_SPEC.md` section 10).
 */

import {
  Suspense,
  lazy,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
} from "react";
import { flushSync } from "react-dom";


import { AvailabilityContext, PanelToggle } from "../components/primitives";
import { CriticalArtifactError, openSite, type Degradation } from "../data/bundle";
import { selectOpportunityCandidates, signalTeam } from "../data/candidates";
import { easternIsoDate } from "../data/format";
import { cohortAssignment } from "../data/market";
import { selectArbitrageRows, selectTierRows, type ArtifactIndex } from "../data/model";
import { selectPotwBoard, visiblePicks, clampSet } from "../data/potw";
import {
  behaviorMomentum,
  buildRosCohortContext,
  selectRosRows,
  splitActionable,
  type InSeasonBundle,
} from "../data/ros";
import { buildUsageCohort } from "../data/signals";
import { requiredKeys, type DataStore } from "../data/store";
import { selectWeekBoard, startableFor, toggleDuel } from "../data/duel";
import {
  IN_SEASON_VIEWS,
  SCORING_TO_PRESET,
  leaguePresetId,
  resolveMode,
  resolveView,
  type ScoringValue,
  type TeamCount,
} from "../data/state";
import { TEAM_COUNTS, SCORING_VALUES } from "../data/state";
import { ArbitrageView } from "./ArbitrageView";
import { Controls, SeasonMode, SeasonModeChip, ViewTabs, settingsSummary } from "./Controls";
import { DataView } from "./DataView";
import { BrandLogo, Masthead } from "./Masthead";
import { OpportunityView } from "./OpportunityView";
import { whyThisWeek } from "../data/whyweek";
import { PlayerDetail, type PlayerDetailData } from "./PlayerDetail";
import { PotwView } from "./PotwView";
import { RosView } from "./RosView";
import { TiersView } from "./TiersView";
import { useAppState } from "./useAppState";

/**
 * The Start/Sit tab and its chart, loaded when the tab is first opened (ADR-096). It is the one
 * view a draft-season reader never opens, and splitting it keeps the entry bundle under the
 * size it was before the tab existed. The arithmetic it shares with the player card
 * (`data/startsit.ts`, `data/duel.ts`) stays in the entry bundle, so the split is a view only.
 */
const StartSitView = lazy(() =>
  import("./StartSitView").then((module) => ({ default: module.StartSitView })),
);

/**
 * The Trade tab and its engine (ADR-100), loaded the same way: only a reader who opens the tab
 * downloads the search. It reads the rest-of-season block the default view already loaded.
 */
const TradeView = lazy(() => import("./TradeView").then((module) => ({ default: module.TradeView })));

type LoadState =
  | { readonly status: "loading" }
  | { readonly status: "ready"; readonly store: DataStore }
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
    openSite()
      .then((store) => {
        if (!cancelled) setLoad({ status: "ready", store });
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
    return <LoadingBoard />;
  }

  if (load.status === "error") {
    return <CriticalError error={load.error} />;
  }

  return (
    <SiteBoard
      store={load.store}
      state={state}
      setState={setState}
      selectedPlayerId={selectedPlayerId}
      onSelect={onSelect}
      onCloseDetail={onCloseDetail}
      now={now}
    />
  );
}

function LoadingBoard(): React.JSX.Element {
  return (
    <main className="app">
      <p role="status" className="muted" style={{ padding: "2rem 0" }}>
        Loading the board…
      </p>
    </main>
  );
}

/**
 * The served files the open view and card need, fetched as they are needed (ADR-098).
 *
 * The view's own files gate the first paint, exactly as the whole-artifact loader's single
 * promise did; after that a switch of tab, block or card fetches only what that switch adds,
 * and the chrome stays on screen while it does.
 */
function SiteBoard({
  store,
  state,
  setState,
  selectedPlayerId,
  onSelect,
  onCloseDetail,
  now,
}: {
  readonly store: DataStore;
  readonly state: ReturnType<typeof useAppState>["state"];
  readonly setState: ReturnType<typeof useAppState>["setState"];
  readonly selectedPlayerId: string | null;
  readonly onSelect: (playerId: string) => void;
  readonly onCloseDetail: () => void;
  readonly now?: Date | undefined;
}): React.JSX.Element {
  // Re-render when anything arrives; what to build from it is decided below.
  useSyncExternalStore(
    useCallback((listener: () => void) => store.subscribe(listener), [store]),
    () => store.version,
  );
  const mode = resolveMode(state.mode, store.rosMetadata?.season_state.product_mode ?? null);
  const view = resolveView(state.view, mode);
  const leaguePreset = leaguePresetId(state.teams);
  const scoring = SCORING_TO_PRESET[state.scoring];
  const viewKeys = useMemo(
    () => requiredKeys(store.manifest, { view, leaguePreset, scoring, cardPlayerId: null }),
    [store, view, leaguePreset, scoring],
  );
  const cardKeys = useMemo(
    () =>
      selectedPlayerId === null
        ? []
        : requiredKeys(store.manifest, { view, leaguePreset, scoring, cardPlayerId: selectedPlayerId }),
    [store, view, leaguePreset, scoring, selectedPlayerId],
  );
  const [failure, setFailure] = useState<Error | null>(null);
  const [firstPaint, setFirstPaint] = useState(false);
  const viewReady = store.isLoaded(viewKeys);
  const cardReady = store.isLoaded(cardKeys);
  if (viewReady && !firstPaint) setFirstPaint(true);

  useEffect(() => {
    let cancelled = false;
    store.ensure([...viewKeys, ...cardKeys]).catch((error: unknown) => {
      if (!cancelled) setFailure(error instanceof Error ? error : new Error(String(error)));
    });
    return () => {
      cancelled = true;
    };
  }, [store, viewKeys, cardKeys]);

  // Each built from exactly the keys it reads; the store hands back the same object until one
  // of those keys loads, so a card's shard arriving never gives the board a new index.
  const index = store.boardIndex(viewKeys);
  const inSeason = store.inSeason(viewKeys);
  const cohorts = store.inSeason(cardKeys);
  // A shard is immutable once loaded, so the card's records are fixed by these inputs.
  const card = useMemo(
    () =>
      selectedPlayerId === null || !cardReady
        ? null
        : store.cardData(leaguePreset, scoring, selectedPlayerId),
    [store, selectedPlayerId, cardReady, leaguePreset, scoring],
  );

  if (!firstPaint && failure === null) return <LoadingBoard />;

  return (
    <Board
      index={index}
      inSeason={inSeason}
      degradations={store.degradations}
      state={state}
      setState={setState}
      selectedPlayerId={selectedPlayerId}
      onSelect={onSelect}
      onCloseDetail={onCloseDetail}
      now={now}
      panelReady={viewReady}
      failure={failure}
      card={card}
      cohorts={cohorts}
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
  panelReady,
  failure,
  card,
  cohorts,
}: {
  /**
   * The in-season bundle built from the card's own keys: the blocks and populations a card's
   * cohort strips place one player among (ADR-098). Null before kickoff.
   */
  readonly cohorts: InSeasonBundle | null;
  /** Every served file the open view reads is loaded (ADR-098). */
  readonly panelReady: boolean;
  /** A served file failed to load; the panel says so rather than drawing a partial board. */
  readonly failure: Error | null;
  /** The open card's records, from its shard; null until it has loaded. */
  readonly card: ReturnType<DataStore["cardData"]>;
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
  // ADR-101: the availability policy's reader for every in-season panel's rows.
  const availabilityReader = useMemo(
    () => (inSeason === null ? null : (playerId: string) => inSeason.availabilityFor(playerId)),
    [inSeason],
  );

  // The season, as distinct from the boards this build holds. The draft build records it
  // because the draft build always runs, which is the only way the page can know the season
  // has started while no rest-of-season bundle exists (ADR-079).
  const buildSeason = metadata.season_state ?? null;
  const awaitingFirstRos =
    inSeason === null &&
    buildSeason !== null &&
    buildSeason.state !== null &&
    buildSeason.state !== "preseason_draft" &&
    !buildSeason.ros_board_expected;

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

  /*
    The phone's settings panel (ADR-093). Closed by default: the sticky bar a phone carries
    while the board scrolls is one summary row and the tabs, and the controls are one tap
    away. Local state rather than URL state, because it is chrome and not board — a shared
    link names a board, and should not open someone else's panel. Above the sheet breakpoint
    the stylesheet ignores it and every control is on screen, exactly as before.
  */
  const [settingsOpen, setSettingsOpen] = useState(false);
  const settingsToggle = useRef<HTMLButtonElement>(null);
  const toggleSettings = useCallback(() => {
    setSettingsOpen((open) => !open);
  }, []);
  // Synchronous, so the `/` shortcut can focus the search box in the same keystroke.
  const revealSearch = useCallback(() => {
    flushSync(() => {
      setSettingsOpen(true);
    });
  }, []);
  // Escape closes the panel and returns focus to the row that opened it — but only where
  // there is a panel to close. A search box with text uses its own Escape to clear first.
  const onSettingsKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLDivElement>) => {
      if (event.key !== "Escape" || event.isDefaultPrevented() || !settingsOpen) return;
      const toggle = settingsToggle.current;
      if (toggle === null || toggle.getClientRects().length === 0) return;
      event.preventDefault();
      setSettingsOpen(false);
      toggle.focus();
    },
    [settingsOpen],
  );

  /**
   * The row count beside the navigation, from the design source.
   *
   * `shown` is what the current filters select and `total` is what the build published for the
   * active preset. Both are counts of artifact rows; the Data view has no board and shows
   * none. This is a filter readout, not a derived quantity.
   */
  const rowCount = useMemo(() => {
    if (!panelReady) return undefined;
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
        // The actionable board's rows (ADR-101): a held-back player is not "shown".
        shown: splitActionable(selectRosRows(inSeason, state), state.unavailable, state.search).shown.length,
        total: inSeason.rosFor(leaguePreset, scoring).length,
      };
    }
    if (view === "opportunity" && inSeason !== null) {
      return {
        shown: selectOpportunityCandidates(inSeason, state).candidates.length,
        total: inSeason.opportunityFor(leaguePreset, scoring).length,
      };
    }
    if (view === "startsit" && inSeason !== null) {
      // Board rows the filters select against the week's published projections for this
      // scoring preset: the same "shown of published" readout every other board prints.
      return {
        shown: selectWeekBoard(inSeason, state, "median").length,
        total: inSeason.weeklyFor(scoring).length,
      };
    }
    if (view === "potw" && inSeason !== null) {
      // Picks on screen against picks in the whole set. The readout is the same "what the
      // filters select of what the build produced" it is on every other board; here the
      // denominator is a set rather than a board, because a set is what the view publishes.
      const board = selectPotwBoard(inSeason, state);
      const set = board.sets[clampSet(state.set, board) - 1];
      return set === undefined
        ? { shown: 0, total: 0 }
        : { shown: visiblePicks(set, state.position).length, total: set.picks.length };
    }
    return undefined;
  }, [index, inSeason, state, view, panelReady]);

  const detail: PlayerDetailData | null = useMemo(() => {
    // The card opens once its shard is in (ADR-098): every per-player record below is read
    // from it, so the card is the same whichever board it was opened from. Flags that say what
    // the build *published*, and the cohorts a value is placed among, come from the boards.
    if (selectedPlayerId === null || card === null) return null;
    const leaguePreset = leaguePresetId(state.teams);
    const scoring = SCORING_TO_PRESET[state.scoring];
    const own = card.inSeason;
    const ros = own?.rosRecordFor(leaguePreset, scoring, selectedPlayerId) ?? null;
    const opportunity = own?.opportunityRecordFor(leaguePreset, scoring, selectedPlayerId) ?? null;
    const usage = own?.usageFor(selectedPlayerId) ?? null;
    const weekly = own?.weeklyRecordFor(scoring, selectedPlayerId) ?? null;
    return {
      playerId: selectedPlayerId,
      tier: card.index.tierFor(leaguePreset, scoring, selectedPlayerId),
      arbitrage: card.index.arbitrageRecordFor(leaguePreset, scoring, selectedPlayerId),
      status: card.index.statusFor(selectedPlayerId),
      // Null whenever the build published no portrait for him, which is ordinary. The card
      // draws a monogram and nothing else about it changes (ADR-087).
      headshotUrl: card.index.headshotFor(selectedPlayerId)?.image_url ?? null,
      projection: card.index.projectionFor(scoring, selectedPlayerId),
      ros,
      rosDisclosures: inSeason?.metadata.disclosures ?? null,
      /*
        What a published number means, against the rows it was published beside.

        Computed from the block rather than from `selectRosRows`, deliberately: the reader's
        position filter is a question about what to show, not about what a player's interval
        width compares with, and a cohort that moved when the filter did would be a reading
        about the control. Assembled in `data/ros` rather than in the card, so the card stays a
        renderer and the rule has one home and one test.
      */
      rosCohort:
        cohorts === null || ros === null
          ? null
          : buildRosCohortContext(cohorts, leaguePreset, scoring, ros, opportunity),
      // The in-season panel's own inputs.
      //
      // `inSeason` is keyed off the *view*, not the mode. The card belongs to the board the
      // row was clicked on: a row on the Tier Board is a draft-model row and its market
      // comparison is the draft market, whatever month it is. Keying it off the mode instead
      // gave the draft board an in-season card in November — which is also how ADR-079's two
      // lifecycle windows, in-season with no board at all, end up correct here for free.
      opportunity,
      behavior: inSeason?.metadata.behavior ?? null,
      // The signal layer (ADR-091). The usage record names the team whose next game is read;
      // the rest-of-season row's team is the fallback for a player with no usage record.
      usage,
      usageCohort:
        cohorts === null || usage === null
          ? null
          : buildUsageCohort(cohorts.usageCohortRecords, usage, scoring),
      usagePublished: inSeason?.hasUsage ?? false,
      matchup: cohorts?.matchupFor(signalTeam(usage, ros?.team, opportunity?.team)) ?? null,
      matchupsPublished: inSeason?.hasMatchups ?? false,
      signals: inSeason?.metadata.signals ?? null,
      momentum: own === null ? null : behaviorMomentum(own, selectedPlayerId),
      seriesPublished: inSeason?.hasBehaviorSeries ?? false,
      inSeason: IN_SEASON_VIEWS.includes(view) && inSeason !== null,
      // ADR-101: the policy's reading from the card's own shard (status, ROS row, report).
      availability: own?.availabilityFor(selectedPlayerId) ?? null,
      // The weekly start/sit layer (ADR-096): shown on an in-season card only.
      weekly,
      weeklyWhy:
        weekly === null
          ? null
          : whyThisWeek(
              weekly,
              cohorts?.weeklyContextFor(weekly.team) ?? null,
              cohorts?.weeklyContextFor(weekly.game?.opponent ?? null) ?? null,
            ),
      weeklyMeta: inSeason?.metadata.weekly ?? null,
      weeklyStartable: startableFor(weekly, inSeason?.metadata.weekly, leaguePreset, scoring),
      inDuel: state.duel.includes(selectedPlayerId),
      marketAvailable: index.hasArbitrage,
      cohortExact: cohortAssignment(metadata, scoring, state.teams)?.exact ?? null,
      // Every market's retained history for this player. The card picks which of them to
      // draw from the selection; passing the *selection* into the index is what made the
      // cross view look up a `cross` source that no capture ever produced (ADR-081).
      market: state.market,
      trendSeries: card.index.trendSeriesFor(leaguePreset, scoring, selectedPlayerId),
    };
  }, [
    index,
    inSeason,
    card,
    cohorts,
    metadata,
    view,
    selectedPlayerId,
    state.scoring,
    state.teams,
    state.market,
    state.duel,
  ]);

  // From a card to the comparison: add him (a full comparison is left as it is) and go.
  const onCompare = useCallback(
    (playerId: string) => {
      setState({
        view: "startsit",
        duel: state.duel.includes(playerId) ? state.duel : toggleDuel(state.duel, playerId),
      });
      onCloseDetail();
    },
    [setState, state.duel, onCloseDetail],
  );

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
              seasonState={inSeason?.seasonState ?? buildSeason?.state ?? null}
              throughWeek={inSeason?.throughWeek ?? null}
              note={buildSeason?.note}
              awaiting={awaitingFirstRos}
            />
          }
        />

        {/*
          One sticky block. On a phone it is the summary row and the tabs, with every control
          folded between them until the row is tapped; above the sheet breakpoint the row is
          not rendered, nothing is sticky, and the season-mode band, the controls and the tabs
          stack exactly as they always have (ADR-093).
        */}
        <div className="sticky-controls">
          <PanelToggle
            className="settings-toggle"
            label="Settings"
            items={settingsSummary(state, inSeason !== null)}
            open={settingsOpen}
            controls="board-settings"
            onToggle={toggleSettings}
            toggleRef={settingsToggle}
          />
          <div
            id="board-settings"
            className="board-settings phone-panel"
            data-open={settingsOpen}
            onKeyDown={onSettingsKeyDown}
          >
            <SeasonMode
              mode={state.mode}
              resolved={mode}
              throughWeek={inSeason?.throughWeek ?? null}
              available={inSeason !== null}
              onChange={(next) => {
                setState({ mode: next });
              }}
            />
            <Controls
              state={state}
              onChange={setState}
              availableScoring={availableScoring}
              availableTeams={availableTeams}
              onRevealSearch={revealSearch}
            />
          </div>
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
          {awaitingFirstRos && (
            <AwaitingFirstRosBoard
              note={buildSeason?.note ?? ""}
              complete={buildSeason?.state === "season_complete"}
            />
          )}
          <div
            role="tabpanel"
            id={`panel-${view}`}
            aria-labelledby={`tab-${view}`}
            tabIndex={-1}
          >
            <AvailabilityContext.Provider
              value={inSeason !== null && IN_SEASON_VIEWS.includes(view) ? availabilityReader : null}
            >
            {!panelReady && <PanelLoading failure={failure} />}
            {panelReady && view === "tiers" && (
              <TiersView
                index={index}
                state={state}
                onChange={setState}
                onSelect={onSelect}
                selectedPlayerId={selectedPlayerId}
                buildDate={buildDate}
              />
            )}
            {panelReady && view === "arbitrage" && (
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
            {panelReady && view === "ros" &&
              (inSeason === null ? (
                <NoInSeasonBundle />
              ) : (
                <RosView
                  bundle={inSeason}
                  state={state}
                  onChange={setState}
                  onSelect={onSelect}
                  selectedPlayerId={selectedPlayerId}
                />
              ))}
            {panelReady && view === "opportunity" &&
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
            {panelReady && view === "startsit" &&
              (inSeason === null ? (
                <NoInSeasonBundle />
              ) : (
                <Suspense
                  fallback={
                    <section className="section startsit" aria-busy="true">
                      <p className="startsit-loading">Loading Start/Sit…</p>
                    </section>
                  }
                >
                  <StartSitView
                    bundle={inSeason}
                    state={state}
                    onChange={setState}
                    onSelect={onSelect}
                    now={now}
                  />
                </Suspense>
              ))}
            {panelReady && view === "trade" &&
              (inSeason === null ? (
                <NoInSeasonBundle />
              ) : (
                <Suspense
                  fallback={
                    <section className="section trade" aria-busy="true">
                      <p className="startsit-loading">Loading Trade…</p>
                    </section>
                  }
                >
                  <TradeView bundle={inSeason} state={state} onChange={setState} onSelect={onSelect} />
                </Suspense>
              ))}
            {panelReady && view === "potw" &&
              (inSeason === null ? (
                <NoInSeasonBundle />
              ) : (
                <PotwView
                  bundle={inSeason}
                  state={state}
                  onChange={setState}
                  onSelect={onSelect}
                  selectedPlayerId={selectedPlayerId}
                  headshotFor={(playerId) => index.headshotFor(playerId)?.image_url ?? null}
                />
              ))}
            {panelReady && view === "data" && (
              <DataView
                index={index}
                inSeason={inSeason}
                state={state}
                degradations={degradations}
              />
            )}
            </AvailabilityContext.Provider>
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
            Intrinsic tiers use no market or expert-rank input. Injury status decides what is
            recommended, never a model number.
          </span>
          <span>
            Data: nflverse, ffopportunity, MyFantasyLeague, Fantasy Football Calculator, Sleeper
            (non-commercial), NWS, Open-Meteo (CC BY 4.0). Free, no ads.
          </span>
        </footer>
      </div>

      <PlayerDetail
        data={detail}
        onClose={onCloseDetail}
        onOpenData={openData}
        onCompare={inSeason?.hasWeekly === true ? onCompare : undefined}
      />
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
/**
 * The season has started and there is no rest-of-season board yet.
 *
 * Two ordinary windows produce it: the days between the first kickoff and the first published
 * week, and the weeks after the last scored one. In both the draft board on screen is the
 * only board that exists, and it is correct — what would not be correct is letting the page
 * imply the season has not begun. The build's own sentence is rendered rather than a sentence
 * written here, so the page cannot describe a state the build did not report (ADR-079).
 */
function AwaitingFirstRosBoard({
  note,
  complete,
}: {
  readonly note: string;
  readonly complete: boolean;
}): React.JSX.Element {
  return (
    <div className="notice season-notice" data-severity="info" role="note">
      <strong>
        {complete ? "The fantasy season is over." : "The regular season has started."}
      </strong>{" "}
      {note === ""
        ? "The first rest-of-season board is published once a completed week's upstream data is available."
        : `${note.charAt(0).toUpperCase()}${note.slice(1)}.`}{" "}
      The draft board below is unaffected and current.
    </div>
  );
}

/**
 * The open view's files are on their way, or one of them could not be read.
 *
 * A failure here is almost always a deploy that landed while the page was open: the manifest
 * this page read names files the new deploy replaced. Reloading reads the new manifest, and
 * nothing from either deploy is ever mixed into one board.
 */
function PanelLoading({ failure }: { readonly failure: Error | null }): React.JSX.Element {
  if (failure === null) {
    return (
      <section className="section" aria-busy="true">
        <p role="status" className="muted">
          Loading…
        </p>
      </section>
    );
  }
  return (
    <section className="section">
      <div className="notice" data-severity="error" role="alert">
        <strong>This part of the board could not be loaded.</strong>
        <p style={{ marginTop: "0.5rem" }}>
          The site may have been updated since this page was opened. Reload to read the current
          build.
        </p>
        <p className="muted" style={{ marginTop: "0.5rem" }}>
          {failure.message}
        </p>
        <p style={{ marginTop: "0.75rem" }}>
          <button
            type="button"
            onClick={() => {
              window.location.reload();
            }}
          >
            Reload
          </button>
        </p>
      </div>
    </section>
  );
}

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
        <BrandLogo />
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
