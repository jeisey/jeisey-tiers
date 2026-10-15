/**
 * Win My Matchup (ADR-110): this week's matchup for the open league — the reader's starters
 * against the opponent's as entered — simulated on request, with lineup changes ranked by the
 * chance to win and an opt-in, ceiling-first YOLO waiver mode.
 *
 * **Lazy.** This file, its stylesheet and the simulation worker are their own chunks: My Leagues
 * downloads none of them until the reader opens this view, and the worker loads on the first
 * *Simulate*. YOLO's two data files load only while YOLO is on.
 *
 * **Nothing runs on its own.** A simulation starts from *Simulate*, *Evaluate changes* or
 * *Preview* — never from a render, a keystroke, a data load or a timer. Each run is identified by
 * a fingerprint of everything it read; a result is shown only while the inputs still produce that
 * fingerprint, so an edit, a new week or a league switch can never show an older answer. Results
 * live in this component's memory only (at most six), and are never saved.
 *
 * **Nothing changes a roster on its own.** Only *Apply* and a confirmed *Add to my roster* write
 * to the league, as one edit each, with *Undo*.
 */

import "../../styles/wmm.css";

import { useCallback, useContext, useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";

import { Notice, Segmented } from "../../components/primitives";
import type { Availability } from "../../data/availability";
import type { RosWeeklyMetadata, ScoringPreset } from "../../data/contracts";
import { formatAge, formatEastern } from "../../data/format";
import { STALE_WARNING_HOURS } from "../../data/freshness";
import { rosterIds, type Roster, type SavedLeague } from "../../data/leagueContract";
import { updateLeague } from "../../data/leagueOps";
import { publishYoloFiles } from "../../data/leagueSignal";
import type { LeagueStore } from "../../data/leagueStore";
import type { PlayerUniverse } from "../../data/leagueUniverse";
import type { WeekContext } from "../../data/lineup";
import { MATCHUP_DRAWS, MATCHUP_ENGINE_VERSION, type SimResult, type VariantResult } from "../../data/matchup";
import { CancelledError, MatchupRunner } from "../../data/matchupClient";
import {
  buildSimInput,
  latentCorrelations,
  normalProposals,
  readSetup,
  type BuiltInput,
  type Identity,
  type Proposal,
  type Scenario,
  type SetupInput,
} from "../../data/matchupSetup";
import type { InSeasonBundle } from "../../data/ros";
import { checkRoster, slotLongName } from "../../data/roster";
import type { DistributionRule } from "../../data/startsit";
import { findEntry, opponentIds, prefsFor, previousEntry, setMark, type Mark, type MatchupEntry } from "../../data/wmmContract";
import { editEntry, reuseEntry, setWmmPrefs, sharedWmmStore, type WmmSnapshot, type WmmStore } from "../../data/wmmStore";
import { selectYolo, yoloProposal, type YoloCandidate } from "../../data/yolo";
import { MatchupLineups, FinalsEditor, type LineupReaders } from "./MatchupLineups";
import { GroupTable, Headline, MarginChart, Totals } from "./MatchupResults";
import { NormalChanges, YoloPanel, movesText, variantFor, type EvaluatedChange } from "./MatchupChanges";
import { Modal } from "./Modal";
import { WmmStoreContext } from "./wmmContext";
import { points } from "./shared";

/** Results kept in memory for this league's view: enough to switch back and forth. */
const RESULT_LIMIT = 6;

type RunKind = "simulate" | "changes" | "preview";

interface Running {
  readonly kind: RunKind;
  readonly fingerprint: string;
  readonly cancel: () => void;
}

interface ChangesRun {
  /** The baseline the changes were evaluated against: stale once that changes. */
  readonly baseFingerprint: string;
  readonly built: BuiltInput;
  readonly proposals: readonly Proposal[];
  readonly yolo: readonly (Proposal & { readonly candidateId: string })[];
}

interface PreviewRun {
  readonly baseFingerprint: string;
  readonly proposal: Proposal;
  readonly label: string;
  readonly built: BuiltInput;
}

export interface WinMyMatchupProps {
  readonly league: SavedLeague;
  readonly leagueStore: LeagueStore;
  readonly leagueWritable: boolean;
  readonly bundle: InSeasonBundle;
  readonly yoloBundle: InSeasonBundle | null;
  readonly yoloFailure: Error | null;
  readonly context: WeekContext;
  readonly universe: PlayerUniverse;
  readonly name: (id: string) => string;
  readonly teamOf: (id: string) => string | null;
  readonly availabilityOf: (id: string) => Availability | null;
  readonly rule: DistributionRule;
  readonly weekly: RosWeeklyMetadata;
  readonly scoring: ScoringPreset;
  readonly leaguePreset: string;
  readonly presetLabel: string;
  readonly onSelect: (id: string) => void;
  readonly onEditLineup: () => void;
  /** Tests hand in their own store; the page uses the shared one. */
  readonly store?: WmmStore;
}

function useWmmSnapshot(store: WmmStore): WmmSnapshot {
  return useSyncExternalStore(store.subscribe, store.snapshot, store.snapshot);
}

function hoursSince(iso: string, now: number): number {
  const parsed = Date.parse(iso);
  return Number.isNaN(parsed) ? Number.POSITIVE_INFINITY : (now - parsed) / 3_600_000;
}

function measure(name: string, start: number): void {
  if (typeof performance !== "undefined" && typeof performance.measure === "function") {
    performance.measure(name, { start, end: performance.now() });
  }
}

/** Let the browser paint and handle input between two pieces of main-thread work. */
function yieldToBrowser(): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, 0));
}

export function WinMyMatchup(props: WinMyMatchupProps): React.JSX.Element {
  const { league, leagueStore, leagueWritable, bundle, yoloBundle, yoloFailure, context, universe, name, rule, weekly, scoring, leaguePreset } = props;
  const injected = useContext(WmmStoreContext);
  const store = useMemo(() => props.store ?? injected ?? sharedWmmStore(), [props.store, injected]);
  const snapshot = useWmmSnapshot(store);
  const week = weekly.target_week;
  const season = bundle.season;
  const at = useMemo(() => ({ leagueId: league.id, season, week }), [league.id, season, week]);
  const entry = findEntry(snapshot.doc, league.id, season, week);
  const previous = entry === null ? previousEntry(snapshot.doc, league.id, season, week) : null;
  const prefs = prefsFor(snapshot.doc, league.id);
  const wmmWritable = snapshot.save.kind !== "readonly" && snapshot.save.kind !== "protected";
  const [notice, setNotice] = useState<string | null>(null);

  // YOLO's files load only while this view is open with YOLO on.
  useEffect(() => {
    publishYoloFiles(prefs.yolo);
    return () => {
      publishYoloFiles(false);
    };
  }, [prefs.yolo]);

  const edit = useCallback(
    (change: (current: MatchupEntry) => MatchupEntry): void => {
      const outcome = editEntry(store, at, entry, change);
      setNotice(outcome.ok ? null : outcome.message);
    },
    [store, at, entry],
  );

  const [scenario, setScenario] = useState<Scenario>("pregame");
  const setupInput: SetupInput = useMemo(() => ({ league, entry, context, scenario }), [league, entry, context, scenario]);
  const setup = useMemo(() => readSetup(setupInput), [setupInput]);
  const correlation = useMemo(() => latentCorrelations(weekly), [weekly]);
  const identity: Identity = useMemo(
    () => ({ buildId: bundle.metadata.build_id, modelVersion: weekly.model_version, scoring, week, leagueId: league.id }),
    [bundle, weekly, scoring, week, league.id],
  );
  const baseline = useMemo(
    () => (setup.complete ? buildSimInput(setup, [], rule, correlation, identity) : null),
    [setup, rule, correlation, identity],
  );

  // ------------------------------------------------------------------------- running
  const runner = useRef<MatchupRunner | null>(null);
  useEffect(
    () => () => {
      runner.current?.dispose();
      runner.current = null;
    },
    [],
  );
  const [results, setResults] = useState<ReadonlyMap<string, SimResult>>(() => new Map());
  const [running, setRunning] = useState<Running | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const [changes, setChanges] = useState<ChangesRun | null>(null);
  const [preview, setPreview] = useState<PreviewRun | null>(null);
  const [preparing, setPreparing] = useState(false);

  const remember = useCallback((fingerprint: string, result: SimResult) => {
    setResults((current) => {
      const next = new Map(current);
      next.delete(fingerprint);
      next.set(fingerprint, result);
      while (next.size > RESULT_LIMIT) {
        const oldest = next.keys().next().value;
        if (oldest === undefined) break;
        next.delete(oldest);
      }
      return next;
    });
  }, []);

  const start = useCallback(
    (kind: RunKind, built: BuiltInput) => {
      setFailure(null);
      if (results.has(built.fingerprint)) return;
      const active = runner.current ?? new MatchupRunner();
      runner.current = active;
      const begun = performance.now();
      const handle = active.run(built.input);
      setRunning({ kind, fingerprint: built.fingerprint, cancel: handle.cancel });
      handle.promise.then(
        (outcome) => {
          measure(`wmm-${kind}`, begun);
          remember(built.fingerprint, outcome.result);
          setRunning((current) => (current?.fingerprint === built.fingerprint ? null : current));
        },
        (error: unknown) => {
          setRunning((current) => (current?.fingerprint === built.fingerprint ? null : current));
          if (!(error instanceof CancelledError)) setFailure(error instanceof Error ? error.message : String(error));
        },
      );
    },
    [results, remember],
  );

  // A run for inputs that have since changed is cancelled rather than left to finish.
  const baseFingerprint = baseline?.fingerprint ?? null;
  useEffect(() => {
    if (running === null) return;
    const stillCurrent =
      (running.kind === "simulate" && running.fingerprint === baseFingerprint) ||
      (running.kind === "changes" && changes?.baseFingerprint === baseFingerprint && changes.built.fingerprint === running.fingerprint) ||
      (running.kind === "preview" && preview?.baseFingerprint === baseFingerprint && preview.built.fingerprint === running.fingerprint);
    if (!stillCurrent) running.cancel();
  }, [running, baseFingerprint, changes, preview]);

  const baseResult = baseline === null ? undefined : results.get(baseline.fingerprint);
  const changesCurrent = changes !== null && changes.baseFingerprint === baseFingerprint ? changes : null;
  const changesResult = changesCurrent === null ? undefined : results.get(changesCurrent.built.fingerprint);
  const previewCurrent = preview !== null && preview.baseFingerprint === baseFingerprint ? preview : null;
  const previewResult = previewCurrent === null ? undefined : results.get(previewCurrent.built.fingerprint);

  const simulate = (): void => {
    if (baseline !== null) start("simulate", baseline);
  };

  // --------------------------------------------------------------------------- YOLO
  const owned = useMemo(() => new Set([...rosterIds(league.roster), ...(entry === null ? [] : opponentIds(entry))]), [league.roster, entry]);
  const marks = entry?.marks;
  const yoloSelection = useMemo(() => {
    if (!prefs.yolo || yoloBundle === null) return null;
    return selectYolo({ bundle: yoloBundle, leaguePreset, scoring, context, baseline: setup.mine, owned, marks: marks ?? {} });
  }, [prefs.yolo, yoloBundle, leaguePreset, scoring, context, setup.mine, owned, marks]);

  const findChanges = async (): Promise<void> => {
    if (baseline === null || preparing) return;
    setPreparing(true);
    const begun = performance.now();
    await yieldToBrowser();
    const proposals = normalProposals(setupInput, setup.mine);
    await yieldToBrowser();
    const yolo =
      yoloSelection?.kind === "ready"
        ? yoloSelection.candidates.map((candidate) => ({ ...yoloProposal(candidate, setupInput), candidateId: candidate.id }))
        : [];
    const built = buildSimInput(setup, [...proposals, ...yolo], rule, correlation, identity);
    measure("wmm-prepare", begun);
    setPreparing(false);
    setChanges({ baseFingerprint: baseline.fingerprint, built, proposals, yolo });
    start("changes", built);
  };

  const showPreview = (proposal: Proposal | null, label: string): void => {
    if (proposal === null || baseline === null) {
      setPreview(null);
      return;
    }
    const built = buildSimInput(setup, [proposal], rule, correlation, identity, { detailFor: [proposal.id] });
    setPreview({ baseFingerprint: baseline.fingerprint, proposal, label, built });
    start("preview", built);
  };

  // ---------------------------------------------------------------------- applying
  const [message, setMessage] = useState<string | null>(null);
  const [undo, setUndo] = useState<{ readonly before: Roster; readonly rev: number } | null>(null);
  const applyRoster = (roster: Roster, text: string): boolean => {
    const problems = checkRoster(roster, league.slots, (id) => universe.get(id)?.position ?? null);
    if (problems.length > 0) {
      setMessage(`That change would leave an illegal roster (${problems.join("; ")}), so it was not applied.`);
      return false;
    }
    const outcome = updateLeague(leagueStore, league, (stored) => ({ ...stored, roster }));
    if (!outcome.ok) {
      setMessage(outcome.message);
      return false;
    }
    setUndo({ before: league.roster, rev: league.rev + 1 });
    setPreview(null);
    setMessage(`${text} Simulate again to see the new picture.`);
    return true;
  };
  const revert = (): void => {
    if (undo === null) return;
    if (league.rev !== undo.rev) {
      setUndo(null);
      setMessage("The lineup changed since, so that change can no longer be undone.");
      return;
    }
    const outcome = updateLeague(leagueStore, league, (stored) => ({ ...stored, roster: undo.before }));
    setUndo(null);
    setMessage(outcome.ok ? "Undone: your previous roster is back." : outcome.message);
  };
  const [pickup, setPickup] = useState<YoloCandidate | null>(null);

  // ----------------------------------------------------------------------- readings
  const readers: LineupReaders = useMemo(
    () => ({ universe, name, teamOf: props.teamOf, availabilityOf: props.availabilityOf, onSelect: props.onSelect }),
    [universe, name, props.teamOf, props.availabilityOf, props.onSelect],
  );
  const age = hoursSince(bundle.metadata.generated_at_utc, context.now);
  const conditional = setup.mine.concat(setup.theirs).filter((line) => line.kind === "modelled" && line.conditional).length;
  const lockedPregame = setup.mine.concat(setup.theirs).filter((line) => line.kind === "modelled" && line.locked).length;
  const finalsUsed = setup.mine.concat(setup.theirs).filter((line) => line.kind === "final").length;
  const scenarioLabel = scenario === "finals" ? `With ${String(finalsUsed)} final score${finalsUsed === 1 ? "" : "s"}` : "Pregame projection";

  const evaluated: EvaluatedChange[] = [];
  const yoloEvaluated = new Map<string, VariantResult>();
  const benchCeiling: EvaluatedChange[] = [];
  if (changesCurrent !== null && changesResult !== undefined) {
    for (const proposal of changesCurrent.proposals) {
      const result = variantFor(changesResult, proposal.id);
      if (result === null) continue;
      evaluated.push({ proposal, result });
    }
    // Bench options that raise the 90th percentile of my simulated total, best first: the
    // ceiling-minded reading of the same evaluated changes.
    benchCeiling.push(
      ...evaluated
        .filter((item) => (item.result.paired?.p90 ?? 0) >= 0.05)
        .sort((a, b) => (b.result.paired?.p90 ?? 0) - (a.result.paired?.p90 ?? 0) || (a.proposal.id < b.proposal.id ? -1 : 1))
        .slice(0, 3),
    );
    for (const proposal of changesCurrent.yolo) {
      const result = variantFor(changesResult, proposal.id);
      if (result !== null) yoloEvaluated.set(proposal.candidateId, result);
    }
  }
  const compare = previewResult?.variants[1] ?? null;

  return (
    <section className="wmm" aria-labelledby="wmm-heading">
      <div className="wmm-head">
        <h3 id="wmm-heading" className="lg-section-title">{`Win My Matchup — week ${String(week)}`}</h3>
        <p className="lg-help">
          {`${props.presetLabel} · projections ${weekly.model_version} · build ${formatEastern(bundle.metadata.generated_at_utc)}${Number.isFinite(age) ? ` (${formatAge(Math.max(0, age))})` : ""}. Covers your QB, RB, WR, TE and FLEX starters only: kickers and team defenses are not modelled, so this is not a full fantasy-team win probability.`}
        </p>
        {age > STALE_WARNING_HOURS && (
          <Notice severity="warning" title="This build is not fresh.">
            {`It is ${String(Math.round(age))} hours old, so injuries, lines and adds may have moved since.`}
          </Notice>
        )}
      </div>

      <WmmStorage snapshot={snapshot} store={store} />
      {notice !== null && (
        <p className="notice" data-severity="warning" role="alert">
          {notice}
        </p>
      )}

      {previous !== null && (
        <Notice title={`Week ${String(week)} has no opponent yet.`} role="status">
          {`Your last saved matchup was week ${String(previous.week)}${previous.opponent.name === "" ? "" : ` against ${previous.opponent.name}`}. Its results are not shown: every week is simulated fresh. `}
          <button
            type="button"
            className="button-link"
            disabled={!wmmWritable}
            onClick={() => {
              const outcome = reuseEntry(store, at, previous);
              setNotice(outcome.ok ? null : outcome.message);
            }}
          >
            {`Reuse that opponent's lineup for week ${String(week)}`}
          </button>
        </Notice>
      )}

      <MatchupLineups
        league={league}
        setup={setup}
        entry={entry}
        readers={readers}
        writable={wmmWritable}
        scenario={scenario}
        onEdit={edit}
        onEditLineup={props.onEditLineup}
      />

      <FinalsEditor setup={setup} entry={entry} readers={readers} writable={wmmWritable} onEdit={edit} />

      <div className="wmm-run">
        {setup.lockedStarters.length > 0 && (
          <Segmented<Scenario>
            name={`wmm-scenario-${league.id}`}
            label="Scenario"
            value={scenario}
            options={[
              { value: "pregame", label: "Pregame projection", description: "Pregame projection: every starter from his published pregame distribution" },
              { value: "finals", label: "With final scores", description: "With final scores: confirmed finals replace those players' projections" },
            ]}
            onChange={setScenario}
          />
        )}
        <Readiness setup={setup} name={name} league={league} conditional={conditional} lockedPregame={lockedPregame} />
        <div className="wmm-run-actions">
          {running !== null && running.kind === "simulate" ? (
            <>
              <span className="lg-help" role="status" aria-live="polite">{`Simulating ${MATCHUP_DRAWS.toLocaleString("en-US")} games…`}</span>
              <button type="button" className="button" onClick={running.cancel}>
                Cancel
              </button>
            </>
          ) : (
            <button type="button" className="button chamfer" data-variant="primary" disabled={baseline === null} onClick={simulate}>
              Simulate
            </button>
          )}
          <span className="lg-help">Runs only when you press it. The same inputs give the same answer.</span>
        </div>
        {failure !== null && (
          <p className="notice" data-severity="error" role="alert">
            {`The simulation could not run: ${failure}`}
          </p>
        )}
      </div>

      {/* Outside the result: applying a change invalidates the result, never its Undo. */}
      {(message !== null || undo !== null) && (
        <p className="wmm-run-actions wmm-applied">
          {message !== null && (
            <span className="lg-help" role="status">
              {message}
            </span>
          )}
          {undo !== null && (
            <button type="button" className="button" onClick={revert}>
              Undo
            </button>
          )}
        </p>
      )}

      {baseline !== null && baseResult === undefined && results.size > 0 && running === null && (
        <p className="lg-help" role="status">Your lineups changed since the last simulation. Simulate again to see the picture for these lineups.</p>
      )}

      {baseResult !== undefined && (
        <section className="wmm-result" aria-labelledby="wmm-result-heading">
          <h4 id="wmm-result-heading" className="visually-hidden">Simulation result</h4>
          <Headline base={baseResult.variants[0] ?? required(baseResult)} draws={baseResult.draws} scenario={scenarioLabel} />
          <p className="lg-help wmm-caveat">
            Estimated scenario probabilities under the published projections and same-game correlations (ADR-110). They
            are not calibrated as team probabilities, the noise above is the simulation&rsquo;s alone, and a stable
            number is not proof of an accurate forecast.{conditional > 0 && ` ${String(conditional)} starter${conditional === 1 ? " is" : "s are"} simulated "if active".`}
            {lockedPregame > 0 && ` ${String(lockedPregame)} kicked-off starter${lockedPregame === 1 ? " is" : "s are"} simulated from the pregame projection.`}
          </p>
          <MarginChart result={previewResult ?? baseResult} compare={compare} compareLabel={previewCurrent?.label ?? null} />
          <Totals result={previewResult ?? baseResult} compare={compare} compareLabel={previewCurrent?.label ?? null} />
          {previewCurrent !== null && previewResult === undefined && running?.kind === "preview" && (
            <p className="lg-help" role="status">Simulating the preview…</p>
          )}
          <GroupTable
            groups={(compare ?? baseResult.variants[0])?.groups ?? []}
            baseline={compare === null ? null : (baseResult.variants[0]?.groups ?? null)}
            label={compare === null ? "Slot groups: your lineup against theirs" : `Slot groups with ${previewCurrent?.label ?? "the proposal"}`}
          />
          <SimNotes result={baseResult} />

          <section className="wmm-section" aria-labelledby="wmm-changes-heading">
            <h4 id="wmm-changes-heading" className="wmm-side-title">Lineup changes</h4>
            {changesResult === undefined ? (
              <p className="wmm-run-actions">
                {running?.kind === "changes" || preparing ? (
                  <>
                    <span className="lg-help" role="status">Evaluating lineup changes…</span>
                    {running !== null && (
                      <button type="button" className="button" onClick={running.cancel}>
                        Cancel
                      </button>
                    )}
                  </>
                ) : (
                  <>
                    <button type="button" className="button" onClick={() => { void findChanges(); }}>
                      {prefs.yolo ? "Evaluate changes and pickups" : "Evaluate lineup changes"}
                    </button>
                    <span className="lg-help">Compares your bench options{prefs.yolo ? " and YOLO's potential pickups" : ""} against this opponent on the same simulated games.</span>
                  </>
                )}
              </p>
            ) : (
              <NormalChanges
                league={league}
                evaluated={evaluated.filter((item) => item.proposal.kind !== "yolo")}
                base={changesResult.variants[0] ?? required(changesResult)}
                name={name}
                previewId={previewCurrent?.proposal.id ?? null}
                writable={leagueWritable}
                onPreview={(proposal) => {
                  showPreview(proposal, proposal === null ? "" : proposal.label);
                }}
                onApply={(proposal) => {
                  applyRoster(proposal.roster, `Applied: ${movesText(proposal, league, name)}.`);
                }}
              />
            )}
          </section>
        </section>
      )}

      <YoloPanel
        league={league}
        on={prefs.yolo}
        writable={wmmWritable}
        selection={yoloSelection}
        loading={prefs.yolo && yoloBundle === null && yoloFailure === null}
        failure={prefs.yolo ? yoloFailure : null}
        evaluated={yoloEvaluated}
        benchCeiling={benchCeiling}
        name={name}
        previewId={previewCurrent?.proposal.id ?? null}
        onToggle={(on) => {
          const outcome = setWmmPrefs(store, league.id, { yolo: on });
          setNotice(outcome.ok ? null : outcome.message);
        }}
        onMark={(id, mark: Mark | null) => {
          edit((current) => setMark(current, id, mark));
        }}
        onPreview={(candidate) => {
          if (candidate === null) {
            setPreview(null);
            return;
          }
          showPreview(yoloProposal(candidate, setupInput), `${candidate.name} (YOLO)`);
        }}
        onAdd={setPickup}
        onApplyBench={(proposal) => {
          applyRoster(proposal.roster, `Applied: ${movesText(proposal, league, name)}.`);
        }}
      />

      <p className="lg-help lg-foot">
        {`${MATCHUP_ENGINE_VERSION} · ${MATCHUP_DRAWS.toLocaleString("en-US")} simulated games, fixed seed · Gaussian copula within each NFL game on the build's latent same-game correlations (${weekly.correlation.method ?? "measured"}); different games independent · ties at 0.01 points`}
      </p>

      {pickup !== null && (
        <PickupDialog
          candidate={pickup}
          setupInput={setupInput}
          league={league}
          name={name}
          writable={leagueWritable && wmmWritable}
          onClose={() => {
            setPickup(null);
          }}
          onConfirm={(roster) => {
            edit((current) => setMark(current, pickup.id, "available"));
            if (applyRoster(roster, `Added ${pickup.name} at ${slotLongName(pickup.slot.slot, league.slots)}.`)) setPickup(null);
          }}
        />
      )}
    </section>
  );
}

function required(result: SimResult): VariantResult {
  const first = result.variants[0];
  if (first === undefined) throw new Error("a simulation result with no lineup");
  return first;
}

function Readiness({
  setup,
  name,
  league,
  conditional,
  lockedPregame,
}: {
  readonly setup: ReturnType<typeof readSetup>;
  readonly name: (id: string) => string;
  readonly league: SavedLeague;
  readonly conditional: number;
  readonly lockedPregame: number;
}): React.JSX.Element {
  if (setup.complete) {
    const zeros = setup.mine.concat(setup.theirs).filter((line) => line.kind === "bye" || line.kind === "zero" || line.kind === "empty").length;
    return (
      <p className="wmm-ready" data-ready="true">
        {`Ready: ${String(setup.mine.length)} starters a side.`}
        {zeros > 0 && ` ${String(zeros)} count${zeros === 1 ? "s" : ""} as a known 0.`}
        {conditional > 0 && ` ${String(conditional)} "if active".`}
        {lockedPregame > 0 && ` ${String(lockedPregame)} kicked off (pregame projection).`}
      </p>
    );
  }
  const issues = setup.blocking.map((line) => `${line.side === "mine" ? "Your" : "Their"} ${slotLongName(line.slot, league.slots)}${line.id === null ? "" : ` (${name(line.id)})`}: ${line.note ?? "needs a decision"}`);
  if (setup.overflow.length > 0) issues.push("Some of their starters no longer fit this league's slots.");
  return (
    <div className="wmm-ready" data-ready="false">
      <p className="wmm-ready-title">{`Simulate needs ${String(issues.length)} decision${issues.length === 1 ? "" : "s"}:`}</p>
      <ul className="lg-gaps">
        {issues.map((issue) => (
          <li key={issue}>{issue}</li>
        ))}
      </ul>
    </div>
  );
}

function SimNotes({ result }: { readonly result: SimResult }): React.JSX.Element | null {
  const unmeasured = result.notes.filter((note) => note.kind === "unmeasured_pair").map((note) => note.subject);
  const fallback = result.notes.filter((note) => note.kind === "block_fallback" && note.variants.length === 0).map((note) => note.subject);
  if (unmeasured.length === 0 && fallback.length === 0) return null;
  return (
    <ul className="lg-gaps" data-kind="unscored" aria-label="Assumptions in this simulation">
      {unmeasured.length > 0 && (
        <li>
          <strong>Unmeasured pairs:</strong>
          {` ${unmeasured.join(", ")} — the build has no measured correlation for these same-game pairs, so they are simulated as independent.`}
        </li>
      )}
      {fallback.length > 0 && (
        <li>
          <strong>Independent games:</strong>
          {` ${fallback.join(", ")} — the measured pairwise correlations for these games do not form a valid joint correlation, so their players are simulated independently. Nothing was adjusted to force a fit.`}
        </li>
      )}
    </ul>
  );
}

function WmmStorage({ snapshot, store }: { readonly snapshot: WmmSnapshot; readonly store: WmmStore }): React.JSX.Element | null {
  const save = snapshot.save;
  const items: React.ReactNode[] = [];
  if (save.kind === "unsaved") {
    items.push(
      <Notice key="unsaved" severity="warning" title="Matchup not saved." role="status">
        {save.reason === "quota" ? "This browser's storage for the site is full; your opponent entries live only in this tab." : "This browser is not letting the site store data; your opponent entries work until you close this tab."}
      </Notice>,
    );
  }
  if (save.kind === "readonly") {
    items.push(
      <Notice key="readonly" severity="warning" title="Saved by a newer version of this site." role="status">
        {`Your matchups were saved in a format (version ${String(save.version)}) this page does not read. Reload to get the latest site; nothing has been changed.`}
      </Notice>,
    );
  }
  if (save.kind === "protected") {
    items.push(
      <Notice key="protected" severity="error" title="Saved matchups could not be read, and no backup could be kept." role="alert">
        Nothing is written over them until you choose.{" "}
        <button type="button" className="button-link" onClick={() => { store.discardUnreadable(); }}>
          Replace the unreadable data
        </button>
      </Notice>,
    );
  }
  for (const notice of snapshot.notices) {
    const text =
      notice.kind === "malformed"
        ? `Saved matchups could not be read: ${notice.reason}.${notice.backedUp ? " A copy was kept as a backup." : ""}`
        : notice.kind === "set_aside"
          ? `${notice.problems.join("; ")}.${notice.backedUp ? " The original was kept as a backup." : ""}`
          : notice.kind === "migrated"
            ? `Saved matchups were upgraded from version ${String(notice.from)}; the original was kept as a backup.`
            : notice.kind === "conflict"
              ? notice.message
              : "Another tab saved matchup changes while this one holds changes that were never saved.";
    items.push(
      <Notice key={notice.kind} severity="warning" role={notice.kind === "conflict" || notice.kind === "diverged" ? "alert" : "status"}>
        {`${text} `}
        {notice.kind === "diverged" ? (
          <button type="button" className="button-link" onClick={() => { store.reloadFromStorage(); }}>
            Load the saved version
          </button>
        ) : (
          <button type="button" className="button-link" onClick={() => { store.dismiss(notice.kind); }}>
            Dismiss
          </button>
        )}
      </Notice>,
    );
  }
  return items.length === 0 ? null : <div className="lg-storage">{items}</div>;
}

function PickupDialog({
  candidate,
  setupInput,
  league,
  name,
  writable,
  onClose,
  onConfirm,
}: {
  readonly candidate: YoloCandidate;
  readonly setupInput: SetupInput;
  readonly league: SavedLeague;
  readonly name: (id: string) => string;
  readonly writable: boolean;
  readonly onClose: () => void;
  readonly onConfirm: (roster: Roster) => void;
}): React.JSX.Element {
  const proposal = yoloProposal(candidate, setupInput);
  const [available, setAvailable] = useState(candidate.mark === "available");
  const [drop, setDrop] = useState<string | null>(null);
  const incumbent = candidate.slot.id;
  const slot = slotLongName(candidate.slot.slot, league.slots);
  const droppable = [...(incumbent === null ? [] : [incumbent]), ...league.roster.BN.filter((id): id is string => id !== null)];
  const roster = ((): Roster | null => {
    if (!proposal.needsDrop) return proposal.roster;
    if (drop === null) return null;
    if (drop === incumbent) return proposal.roster;
    const bench = [...proposal.roster.BN];
    const index = bench.indexOf(drop);
    if (index < 0 || incumbent === null) return null;
    bench[index] = incumbent;
    return { ...proposal.roster, BN: bench };
  })();
  const ready = writable && available && roster !== null;
  return (
    <Modal title={`Add ${candidate.name}`} onClose={onClose}>
      <p>
        {`Start ${candidate.name} at ${slot}`}
        {incumbent === null ? "." : proposal.benchTo !== null ? `; ${name(incumbent)} moves to ${slotLongName(proposal.benchTo, league.slots)}.` : `, replacing ${name(incumbent)}.`}
      </p>
      <p className="lg-help">{`Ceiling ${points(candidate.incumbentQ90)} → ${points(candidate.q90)}; median ${points(candidate.incumbentQ50)} → ${points(candidate.q50)}. This updates only the roster saved in this browser: no transaction is made on your fantasy platform.`}</p>
      <label className="wmm-confirm">
        <input type="checkbox" checked={available} data-autofocus onChange={(event) => { setAvailable(event.target.checked); }} />
        <span>{`I checked: ${candidate.name} is available in my league.`}</span>
      </label>
      {proposal.needsDrop && (
        <fieldset className="wmm-drop">
          <legend>Your bench is full. Who do you drop?</legend>
          {droppable.map((id) => (
            <label key={id} className="wmm-drop-option">
              <input type="radio" name="wmm-drop" value={id} checked={drop === id} onChange={() => { setDrop(id); }} />
              <span>{id === incumbent ? `${name(id)} (the starter he replaces)` : name(id)}</span>
            </label>
          ))}
        </fieldset>
      )}
      <div className="lg-actions-grid">
        <button type="button" className="button chamfer" data-variant="primary" disabled={!ready} onClick={() => { if (roster !== null) onConfirm(roster); }}>
          Add to my roster
        </button>
        <button type="button" className="button" onClick={onClose}>
          Cancel
        </button>
      </div>
      {!available && <p className="lg-help">Confirm his availability first.</p>}
      {available && proposal.needsDrop && drop === null && <p className="lg-help">Choose who to drop.</p>}
    </Modal>
  );
}
