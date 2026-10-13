/**
 * My Leagues (ADR-106): up to three of the reader's own leagues, saved in this browser, and
 * what the published boards say about each one this week.
 *
 * A league is a scoring preset, a league size, the reader's own roster (canonical ids per
 * slot) and two preferences. Selecting one makes its preset the one in force — the shell loads
 * its block and scoring, and the URL, the controls and the links to every other tool follow.
 * Its roster is resolved by id against the current build on every visit.
 *
 * What it shows, top to bottom: the league switcher and its storage state; the active preset
 * and links to the other tools on it; Auto Start/Sit (a proposal, applied only on request, with
 * undo); the roster slot by slot with this week's reading on each and Rising Stars beside the
 * groups; and Improve, whose search loads only when it is run.
 *
 * Loaded lazily, with its own stylesheet: a reader who never opens the tab downloads none of it.
 */

import "../styles/leagues.css";

import { Suspense, lazy, useCallback, useEffect, useMemo, useState } from "react";

import { Notice, SectionHead, Segmented } from "../components/primitives";
import type { Availability } from "../data/availability";
import type { InSeasonBundle } from "../data/ros";
import type { ScoringPreset } from "../data/contracts";
import { formatEastern } from "../data/format";
import {
  LINEUP_MODES,
  MAX_LEAGUES,
  PUBLISHED_STARTERS,
  STARTER_GROUPS,
  SLOT_LABELS,
  rosterIds,
  startersDiffer,
  type LineupMode,
  type SavedLeague,
} from "../data/leagueContract";
import type { LeagueSnapshot, LeagueStore } from "../data/leagueStore";
import { canAddLeague, setPrefs, updateLeague } from "../data/leagueOps";
import { publishActiveLeague } from "../data/leagueSignal";
import { universeFor } from "../data/leagueUniverse";
import {
  LINEUP_RULE_VERSION,
  MODE_LABELS,
  comparablesFor,
  optimizeLineup,
  readWeeks,
  type LineupProposal,
  type WeekContext,
} from "../data/lineup";
import { RISING_RULE_VERSION, RISING_SIGNAL_TEXT, selectRisingStars } from "../data/rising";
import { EDIT_PROBLEM_TEXT, slotLongName, type EditResult, type SlotRef } from "../data/roster";
import { distributionRule, startableThreshold } from "../data/startsit";
import {
  SCORING_LABELS,
  SCORING_TO_PRESET,
  leaguePresetId,
  type AppState,
  type ResolvedViewId,
  type ScoringValue,
  type TeamCount,
} from "../data/state";
import { whyThisWeek } from "../data/whyweek";
import { LineupBoard, type BoardReaders } from "./leagues/LineupBoard";
import { SettingsDialog } from "./leagues/SettingsDialog";
import { SlotDialog } from "./leagues/SlotDialog";
import { points, sumLabel, useClock } from "./leagues/shared";
import { useLeagueSnapshot, useLeagueStore } from "./useLeagues";

/** Improve's view and engine (with the trade engine it reuses), loaded when first run. */
const ImprovePanel = lazy(() =>
  import("./leagues/ImprovePanel").then((module) => ({ default: module.ImprovePanel })),
);

type DialogState =
  | { readonly kind: "create" }
  | { readonly kind: "edit"; readonly leagueId: string }
  | { readonly kind: "slot"; readonly leagueId: string; readonly slot: SlotRef }
  | null;

export function MyLeaguesView({
  bundle,
  ready,
  loadedFor,
  failure,
  risingBundle,
  risingRequested,
  risingFailure,
  state,
  onChange,
  onSelect,
  nameOf,
  availableScoring,
  availableTeams,
  now,
}: {
  readonly bundle: InSeasonBundle;
  /** Every file the shell's current preset needs is loaded. */
  readonly ready: boolean;
  /**
   * The preset those files are for. Just after a switch the shell still holds the previous
   * league's until this view publishes the new one, and a league is never drawn on another's.
   */
  readonly loadedFor: { readonly scoring: ScoringValue; readonly teams: TeamCount };
  readonly failure: Error | null;
  readonly risingBundle: InSeasonBundle | null;
  readonly risingRequested: boolean;
  readonly risingFailure: Error | null;
  readonly state: AppState;
  readonly onChange: (patch: Partial<AppState>) => void;
  readonly onSelect: (playerId: string) => void;
  readonly nameOf: (playerId: string) => string | null;
  readonly availableScoring: ReadonlySet<ScoringValue>;
  readonly availableTeams: ReadonlySet<TeamCount>;
  readonly now?: Date | undefined;
}): React.JSX.Element {
  const store = useLeagueStore();
  const snapshot = useLeagueSnapshot();
  const [dialog, setDialog] = useState<DialogState>(null);
  const leagues = snapshot.doc.leagues;
  const active = leagues.find((league) => league.id === snapshot.activeId) ?? null;
  const writable = snapshot.save.kind !== "readonly" && snapshot.save.kind !== "protected";
  const closeDialog = useCallback(() => {
    setDialog(null);
  }, []);
  // Tell the shell which preset is in force, so it loads that block and scoring (ADR-106).
  useEffect(() => {
    publishActiveLeague(
      active === null
        ? null
        : { name: active.name, scoring: active.scoring, teams: active.teams, rising: active.prefs.risingStars },
    );
  }, [active]);

  return (
    <section className="section leagues" aria-labelledby="leagues-heading">
      <SectionHead
        index="01"
        id="leagues-heading"
        title="My Leagues"
        note={`Up to ${String(MAX_LEAGUES)} of your own leagues, saved in this browser only: nothing is uploaded or put in a link, and clearing this site's data removes them. Each league holds your team's roster; every number is read from the current build by player id.`}
      />
      <StorageStatus snapshot={snapshot} store={store} />
      <LeagueSwitcher
        leagues={leagues}
        activeId={active?.id ?? null}
        canCreate={writable && canAddLeague(snapshot.doc)}
        writable={writable}
        onSwitch={(id) => {
          store.activate(id);
        }}
        onCreate={() => {
          setDialog({ kind: "create" });
        }}
        onEdit={() => {
          if (active !== null) setDialog({ kind: "edit", leagueId: active.id });
        }}
        hasActive={active !== null}
      />
      {active === null ? (
        <EmptyLeagues
          writable={writable}
          onCreate={() => {
            setDialog({ kind: "create" });
          }}
        />
      ) : (
        <LeagueWorkspace
          key={active.id}
          league={active}
          store={store}
          writable={writable}
          bundle={bundle}
          ready={ready && loadedFor.scoring === active.scoring && loadedFor.teams === active.teams}
          failure={failure}
          risingBundle={risingBundle}
          risingRequested={risingRequested}
          risingFailure={risingFailure}
          onChange={onChange}
          onSelect={onSelect}
          nameOf={nameOf}
          presetPublished={availableScoring.has(active.scoring) && availableTeams.has(active.teams)}
          now={now}
          onEditSlot={(slot) => {
            setDialog({ kind: "slot", leagueId: active.id, slot });
          }}
          onEditLeague={() => {
            setDialog({ kind: "edit", leagueId: active.id });
          }}
          slotDialog={
            dialog?.kind === "slot" && dialog.leagueId === active.id ? dialog.slot : null
          }
          onCloseSlot={closeDialog}
        />
      )}
      {(dialog?.kind === "create" || dialog?.kind === "edit") && (
        <SettingsDialog
          store={store}
          league={dialog.kind === "edit" ? (leagues.find((league) => league.id === dialog.leagueId) ?? null) : null}
          defaults={{ scoring: state.scoring, teams: state.teams, season: bundle.season }}
          availableScoring={availableScoring}
          availableTeams={availableTeams}
          nameOf={(id) => nameOf(id) ?? id}
          positionOf={(id) =>
            universeFor(bundle, SCORING_TO_PRESET[active?.scoring ?? state.scoring], leaguePresetId(active?.teams ?? state.teams), nameOf).get(id)?.position ?? null
          }
          onClose={closeDialog}
          leagueCount={leagues.length}
        />
      )}
    </section>
  );
}

// ----------------------------------------------------------------------------- storage

function StorageStatus({ snapshot, store }: { readonly snapshot: LeagueSnapshot; readonly store: LeagueStore }): React.JSX.Element | null {
  const save = snapshot.save;
  const notices = snapshot.notices;
  return (
    <div className="lg-storage">
      {save.kind === "unsaved" && (
        <Notice severity="warning" title="Not saved." role="status">
          {save.reason === "quota"
            ? "This browser's storage for the site is full, so your changes live only in this tab until it accepts them."
            : save.reason === "unavailable"
              ? "This browser is not letting the site store data (a private window or blocked site data). Your changes work until you close this tab."
              : "The browser refused to save the last change. It is kept in this tab; the next change tries again."}
        </Notice>
      )}
      {save.kind === "readonly" && (
        <Notice severity="warning" title="Saved by a newer version of this site." role="status">
          {`Your leagues were saved in a format (version ${String(save.version)}) this page does not read. Reload to get the latest site; nothing has been changed.`}
        </Notice>
      )}
      {save.kind === "protected" && (
        <Notice severity="error" title="Saved leagues could not be read, and no backup could be kept." role="alert">
          Nothing is written over them until you choose.{" "}
          <button type="button" className="button-link" onClick={() => { store.discardUnreadable(); }}>
            Replace the unreadable data
          </button>
        </Notice>
      )}
      {notices.map((notice) => {
        switch (notice.kind) {
          case "malformed":
            return (
              <Notice key="malformed" severity="warning" title="Saved leagues could not be read." role="status">
                {`${notice.reason.charAt(0).toUpperCase()}${notice.reason.slice(1)}.${notice.backedUp ? " A copy was kept in this browser as a backup." : ""} `}
                <button type="button" className="button-link" onClick={() => { store.dismiss("malformed"); }}>Dismiss</button>
              </Notice>
            );
          case "set_aside":
            return (
              <Notice key="set_aside" severity="warning" title="A saved league could not be read and was set aside." role="status">
                {`${notice.problems.join("; ")}.${notice.backedUp ? " The original was kept in this browser as a backup." : ""} `}
                <button type="button" className="button-link" onClick={() => { store.dismiss("set_aside"); }}>Dismiss</button>
              </Notice>
            );
          case "migrated":
            return (
              <Notice key="migrated" title="Saved leagues were upgraded." role="status">
                {`They were saved by an older version (${String(notice.from)}) and read into the current format; the original was kept as a backup. `}
                <button type="button" className="button-link" onClick={() => { store.dismiss("migrated"); }}>Dismiss</button>
              </Notice>
            );
          case "conflict":
            return (
              <Notice key="conflict" severity="warning" title="Changed in another tab." role="alert">
                {`${notice.message} `}
                <button type="button" className="button-link" onClick={() => { store.dismiss("conflict"); }}>Dismiss</button>
              </Notice>
            );
          case "diverged":
            return (
              <Notice key="diverged" severity="warning" title="Another tab saved changes." role="alert">
                This tab has changes that were never saved, so they were not replaced.{" "}
                <button type="button" className="button-link" onClick={() => { store.reloadFromStorage(); }}>
                  Load the saved version
                </button>
              </Notice>
            );
        }
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------- switcher

function LeagueSwitcher({
  leagues,
  activeId,
  canCreate,
  writable,
  onSwitch,
  onCreate,
  onEdit,
  hasActive,
}: {
  readonly leagues: readonly SavedLeague[];
  readonly activeId: string | null;
  readonly canCreate: boolean;
  readonly writable: boolean;
  readonly onSwitch: (id: string) => void;
  readonly onCreate: () => void;
  readonly onEdit: () => void;
  readonly hasActive: boolean;
}): React.JSX.Element {
  return (
    <div className="lg-bar">
      {leagues.length > 0 && (
        <div className="lg-switch" role="radiogroup" aria-label="Saved leagues">
          {leagues.map((league, index) => (
            <button
              key={league.id}
              type="button"
              role="radio"
              aria-checked={league.id === activeId}
              tabIndex={league.id === activeId ? 0 : -1}
              className="lg-switch-option"
              onClick={() => {
                onSwitch(league.id);
              }}
              onKeyDown={(event) => {
                const step = event.key === "ArrowRight" || event.key === "ArrowDown" ? 1 : event.key === "ArrowLeft" || event.key === "ArrowUp" ? -1 : 0;
                if (step === 0) return;
                event.preventDefault();
                const next = leagues[(index + step + leagues.length) % leagues.length];
                if (next !== undefined) {
                  onSwitch(next.id);
                  const target = event.currentTarget.parentElement?.querySelectorAll<HTMLButtonElement>("button")[
                    (index + step + leagues.length) % leagues.length
                  ];
                  target?.focus();
                }
              }}
            >
              <span className="lg-switch-name">{league.name}</span>
              <span className="lg-switch-meta">{`${SCORING_LABELS[league.scoring]} · ${String(league.teams)}`}</span>
            </button>
          ))}
        </div>
      )}
      <div className="lg-bar-actions">
        {hasActive && (
          <button type="button" className="button" onClick={onEdit} disabled={!writable}>
            League settings
          </button>
        )}
        <button
          type="button"
          className="button"
          onClick={onCreate}
          disabled={!canCreate}
          aria-describedby={canCreate || !writable ? undefined : "lg-cap-note"}
        >
          New league
        </button>
        {!canCreate && writable && (
          <span id="lg-cap-note" className="lg-help">{`Up to ${String(MAX_LEAGUES)} leagues. Delete one to add another.`}</span>
        )}
      </div>
    </div>
  );
}

function EmptyLeagues({ writable, onCreate }: { readonly writable: boolean; readonly onCreate: () => void }): React.JSX.Element {
  return (
    <div className="lg-empty">
      <p>
        Save a league to get its best legal lineup for this week, each starter&rsquo;s matchup,
        upgrade ideas for its weakest slots, and players whose role and adds are rising. You
        enter only your own team.
      </p>
      <button type="button" className="button chamfer" data-variant="primary" onClick={onCreate} disabled={!writable}>
        Create a league
      </button>
    </div>
  );
}

// --------------------------------------------------------------------------- workspace

function LeagueWorkspace({
  league,
  store,
  writable,
  bundle,
  ready,
  failure,
  risingBundle,
  risingRequested,
  risingFailure,
  onChange,
  onSelect,
  nameOf,
  presetPublished,
  now,
  onEditSlot,
  onEditLeague,
  slotDialog,
  onCloseSlot,
}: {
  readonly league: SavedLeague;
  readonly store: LeagueStore;
  readonly writable: boolean;
  readonly bundle: InSeasonBundle;
  readonly ready: boolean;
  readonly failure: Error | null;
  readonly risingBundle: InSeasonBundle | null;
  readonly risingRequested: boolean;
  readonly risingFailure: Error | null;
  readonly onChange: (patch: Partial<AppState>) => void;
  readonly onSelect: (playerId: string) => void;
  readonly nameOf: (playerId: string) => string | null;
  readonly presetPublished: boolean;
  readonly now?: Date | undefined;
  readonly onEditSlot: (slot: SlotRef) => void;
  readonly onEditLeague: () => void;
  readonly slotDialog: SlotRef | null;
  readonly onCloseSlot: () => void;
}): React.JSX.Element {
  const scoring = SCORING_TO_PRESET[league.scoring];
  const leaguePreset = leaguePresetId(league.teams);
  const presetLabel = `${String(league.teams)}-team ${SCORING_LABELS[league.scoring]}`;
  const tools = (view: ResolvedViewId, patch: Partial<AppState> = {}): void => {
    onChange({ view, scoring: league.scoring, teams: league.teams, ...patch });
  };

  const header = (
    <div className="lg-preset">
      <p className="lg-preset-line">
        <strong>{presetLabel}</strong>
        <span>{` · ${STARTER_GROUPS.filter((group) => league.slots[group] > 0).map((group) => `${String(league.slots[group])} ${SLOT_LABELS[group]}`).join(", ")} · ${String(league.slots.BN)} bench · ${String(league.slots.IR)} IR · ${String(league.season)} season`}</span>
      </p>
      <p className="lg-preset-links">
        <span className="lg-help">{`Open on ${presetLabel}:`}</span>
        <button type="button" className="button-link" onClick={() => { tools("ros"); }}>ROS tiers</button>
        <button type="button" className="button-link" onClick={() => { tools("startsit"); }}>Start/Sit</button>
        <button type="button" className="button-link" onClick={() => { tools("trade"); }}>Trade</button>
        <button type="button" className="button-link" onClick={() => { tools("opportunity"); }}>Opportunity</button>
      </p>
      {startersDiffer(league.slots) && (
        <p className="lg-help">
          {`Your slots govern this workspace. Published ROS values, ranks, tiers and startable lines assume ${String(PUBLISHED_STARTERS.QB)} QB, ${String(PUBLISHED_STARTERS.RB)} RB, ${String(PUBLISHED_STARTERS.WR)} WR, ${String(PUBLISHED_STARTERS.TE)} TE, ${String(PUBLISHED_STARTERS.FLEX)} FLEX and are not recomputed for yours.`}
        </p>
      )}
    </div>
  );

  if (!presetPublished) {
    return (
      <div className="lg-workspace">
        {header}
        <Notice severity="warning" title="This league's preset is not published by this build.">
          {`No ${presetLabel} board exists in this build, so nothing can be read for it. The league and its roster are kept as saved. `}
          <button type="button" className="button-link" onClick={onEditLeague} disabled={!writable}>League settings</button>
        </Notice>
      </div>
    );
  }
  if (!ready) {
    return (
      <div className="lg-workspace">
        {header}
        {failure === null ? (
          <p className="lg-help" role="status" aria-busy="true">{`Loading the ${presetLabel} board…`}</p>
        ) : (
          <Notice severity="error" title="This league's board could not be loaded." role="alert">
            {`The site may have been updated since this page was opened. Reload to read the current build. (${failure.message})`}
          </Notice>
        )}
      </div>
    );
  }
  return (
    <ReadyWorkspace
      league={league}
      store={store}
      writable={writable}
      bundle={bundle}
      risingBundle={risingBundle}
      risingRequested={risingRequested}
      risingFailure={risingFailure}
      onChange={onChange}
      onSelect={onSelect}
      nameOf={nameOf}
      now={now}
      onEditSlot={onEditSlot}
      slotDialog={slotDialog}
      onCloseSlot={onCloseSlot}
      header={header}
      scoring={scoring}
      leaguePreset={leaguePreset}
      presetLabel={presetLabel}
    />
  );
}

function ReadyWorkspace({
  league,
  store,
  writable,
  bundle,
  risingBundle,
  risingRequested,
  risingFailure,
  onChange,
  onSelect,
  nameOf,
  now,
  onEditSlot,
  slotDialog,
  onCloseSlot,
  header,
  scoring,
  leaguePreset,
  presetLabel,
}: {
  readonly league: SavedLeague;
  readonly store: LeagueStore;
  readonly writable: boolean;
  readonly bundle: InSeasonBundle;
  readonly risingBundle: InSeasonBundle | null;
  readonly risingRequested: boolean;
  readonly risingFailure: Error | null;
  readonly onChange: (patch: Partial<AppState>) => void;
  readonly onSelect: (playerId: string) => void;
  readonly nameOf: (playerId: string) => string | null;
  readonly now?: Date | undefined;
  readonly onEditSlot: (slot: SlotRef) => void;
  readonly slotDialog: SlotRef | null;
  readonly onCloseSlot: () => void;
  readonly header: React.ReactNode;
  readonly scoring: ScoringPreset;
  readonly leaguePreset: string;
  readonly presetLabel: string;
}): React.JSX.Element {
  const clock = useClock(now);
  const universe = useMemo(() => universeFor(bundle, scoring, leaguePreset, nameOf), [bundle, scoring, leaguePreset, nameOf]);
  const weekly = bundle.hasWeekly ? (bundle.metadata.weekly ?? null) : null;
  const rule = useMemo(() => distributionRule(weekly), [weekly]);
  const availabilityOf = useCallback(
    (id: string): Availability | null => (universe.get(id) === null ? null : bundle.availabilityFor(id)),
    [bundle, universe],
  );
  const context: WeekContext = useMemo(
    () => ({
      weeklyFor: (id: string) => bundle.weeklyRecordFor(scoring, id),
      availabilityFor: availabilityOf,
      positionOf: (id: string) => universe.get(id)?.position ?? null,
      targetWeek: weekly?.target_week ?? null,
      now: clock,
    }),
    [bundle, scoring, availabilityOf, universe, weekly, clock],
  );
  const mode = league.prefs.mode;
  const weeks = useMemo(() => readWeeks(league.roster, context), [league.roster, context]);
  const proposal = useMemo(
    () => (weekly === null ? null : measured(() => optimizeLineup(league.roster, league.slots, context, mode, weeks))),
    [league.roster, league.slots, context, mode, weeks, weekly],
  );
  const name = useCallback((id: string) => universe.get(id)?.name ?? nameOf(id) ?? id, [universe, nameOf]);
  const threshold = useCallback(
    (position: string) => startableThreshold(weekly, leaguePreset, scoring, position),
    [weekly, leaguePreset, scoring],
  );
  const readers: BoardReaders = useMemo(
    () => ({
      nameOf: name,
      availabilityOf,
      weekOf: (id: string) => weeks.get(id) ?? null,
      whyFor: (id: string) => {
        const record = bundle.weeklyRecordFor(scoring, id);
        return record === null
          ? null
          : whyThisWeek(record, bundle.weeklyContextFor(record.team), bundle.weeklyContextFor(record.game?.opponent ?? null));
      },
      threshold,
      rule,
      teamOf: (id: string) => bundle.teamLabel(id, universe.get(id)?.team ?? null),
      compareFor: (slot: SlotRef) => comparablesFor(slot, league.roster, weeks),
      onCompare: (ids: readonly string[]) => {
        onChange({ view: "startsit", scoring: league.scoring, teams: league.teams, duel: ids });
      },
    }),
    [name, availabilityOf, weeks, bundle, scoring, threshold, rule, universe, league.roster, league.scoring, league.teams, onChange],
  );

  // Rising Stars: computed once per league roster and loaded bundle, never per render.
  const rosterSet = useMemo(() => new Set(rosterIds(league.roster)), [league.roster]);
  const rising = useMemo(() => {
    if (!league.prefs.risingStars) return null;
    if (risingBundle === null) {
      return {
        selection: null,
        status: risingFailure !== null ? "Rising Stars could not be loaded. Reload to try again." : risingRequested ? "Loading role and add evidence…" : null,
      };
    }
    return { selection: selectRisingStars(risingBundle, leaguePreset, scoring, rosterSet), status: null };
  }, [league.prefs.risingStars, risingBundle, risingFailure, risingRequested, leaguePreset, scoring, rosterSet]);

  const [message, setMessage] = useState<string | null>(null);
  const [undo, setUndo] = useState<{ readonly before: SavedLeague["roster"]; readonly rev: number } | null>(null);

  const commitRoster = (result: EditResult): string | null => {
    if ("problem" in result) return EDIT_PROBLEM_TEXT[result.problem];
    const outcome = updateLeague(store, league, (current) => ({ ...current, roster: result.roster }));
    if (!outcome.ok) return outcome.message;
    setUndo(null);
    return null;
  };

  const apply = (current: LineupProposal): void => {
    const outcome = updateLeague(store, league, (stored) => ({ ...stored, roster: current.roster }));
    if (outcome.ok) {
      setUndo({ before: league.roster, rev: league.rev + 1 });
      setMessage(`Applied ${String(current.moves.length)} change${current.moves.length === 1 ? "" : "s"}.`);
    } else {
      setMessage(outcome.message);
    }
  };
  const revert = (): void => {
    if (undo === null) return;
    if (league.rev !== undo.rev) {
      setUndo(null);
      setMessage("The lineup changed since, so that change can no longer be undone.");
      return;
    }
    const outcome = updateLeague(store, league, (stored) => ({ ...stored, roster: undo.before }));
    setUndo(null);
    setMessage(outcome.ok ? "Undone: your previous lineup is back." : outcome.message);
  };

  const [improveOpen, setImproveOpen] = useState(false);
  const records = bundle.rosFor(leaguePreset, scoring);
  // What Improve's answer depends on: the roster and its shape, the block, the build and the
  // minute (kickoff locks). Not the league's revision: a preference toggle re-runs nothing.
  const improveSignature = useMemo(
    () =>
      [
        league.id,
        JSON.stringify(league.roster),
        JSON.stringify(league.slots),
        String(league.teams),
        bundle.metadata.build_id,
        leaguePreset,
        scoring,
        String(clock),
      ].join("|"),
    [league.id, league.roster, league.slots, league.teams, bundle, leaguePreset, scoring, clock],
  );

  const seasonOld = league.season !== bundle.season;
  const unresolved = rosterIds(league.roster).filter((id) => universe.get(id) === null);
  const empty = rosterIds(league.roster).length === 0;
  const slotOpen = slotDialog;

  return (
    <div className="lg-workspace">
      {header}
      {seasonOld && (
        <Notice severity="warning" title={`Saved for the ${String(league.season)} season.`}>
          {`Players are matched by id against the ${String(bundle.season)} boards; anyone with no ${String(bundle.season)} data stays listed as not in this build. `}
          {writable && (
            <button
              type="button"
              className="button-link"
              onClick={() => {
                updateLeague(store, league, (current) => ({ ...current, season: bundle.season }));
              }}
            >
              {`Mark as ${String(bundle.season)}`}
            </button>
          )}
        </Notice>
      )}
      {unresolved.length > 0 && (
        <p className="lg-help" role="note">
          {`${String(unresolved.length)} saved player${unresolved.length === 1 ? " is" : "s are"} not in this build's boards (${unresolved.map(name).join(", ")}): kept as saved, left where you put them, and given no numbers.`}
        </p>
      )}

      <div className="lg-toolbar">
        <label className="lg-toggle">
          <input
            type="checkbox"
            checked={league.prefs.risingStars}
            disabled={!writable}
            onChange={(event) => {
              setPrefs(store, league, { risingStars: event.target.checked });
            }}
          />
          <span>Rising Stars</span>
        </label>
        {league.prefs.risingStars && (
          <p className="lg-help lg-rising-rule">
            {`Off-roster players whose role (snap share; QB pass attempts) AND adds are both rising now — never either alone, no blended score. Ownership in your league is unknown. `}
            <button
              type="button"
              className="button-link"
              onClick={() => {
                onChange({ view: "opportunity", scoring: league.scoring, teams: league.teams, only: ["role", "momentum"] });
              }}
            >
              Evidence on the Opportunity Board
            </button>
            {rising?.selection?.kind === "unavailable" &&
              ` This build did not publish ${rising.selection.missing.map((signal) => RISING_SIGNAL_TEXT[signal]).join(" or ")}, so rising players cannot be read — not "nobody is rising".`}
            <span className="visually-hidden">{` ${RISING_RULE_VERSION}`}</span>
          </p>
        )}
      </div>

      {weekly === null ? (
        <Notice title="No weekly projections were published with this build.">
          Auto Start/Sit and matchups need the week&rsquo;s projections. Your roster can still be
          edited, and Rising Stars still works.
        </Notice>
      ) : (
        proposal !== null &&
        !empty && (
          <AutoLineup
            proposal={proposal}
            league={league}
            weekly={{ target: weekly.target_week, generated: bundle.metadata.generated_at_utc, kickedOff: weekly.kicked_off > 0 && weekly.upcoming === 0 }}
            name={name}
            writable={writable}
            onMode={(next) => {
              setPrefs(store, league, { mode: next });
            }}
            onApply={apply}
            onUndo={undo === null ? null : revert}
            message={message}
          />
        )
      )}

      <LineupBoard
        league={league}
        universe={universe}
        readers={readers}
        mode={mode}
        weekly={weekly}
        rising={rising}
        onEditSlot={(slot) => {
          if (writable) onEditSlot(slot);
        }}
        onSelect={onSelect}
      />

      <section className="lg-improve" aria-labelledby="lg-improve-heading">
        <h3 id="lg-improve-heading" className="lg-section-title">Improve</h3>
        {weekly === null || empty ? (
          <p className="lg-help">{empty ? "Add players to your roster to find upgrades." : "Improve needs this week's projections."}</p>
        ) : !improveOpen ? (
          <p>
            <button type="button" className="button" onClick={() => { setImproveOpen(true); }}>
              Find upgrades
            </button>{" "}
            <span className="lg-help">Your weakest starting slots, players who would fix them, and value-matched trade ideas from your roster.</span>
          </p>
        ) : (
          <Suspense fallback={<p className="lg-help" role="status">Loading Improve…</p>}>
            <ImprovePanel
              league={league}
              records={records}
              week={context}
              threshold={threshold}
              rule={rule}
              availabilityOf={(id) => bundle.availabilityFor(id)}
              nameOf={name}
              onSelect={onSelect}
              signature={improveSignature}
              presetLabel={presetLabel}
            />
          </Suspense>
        )}
      </section>

      <p className="lg-help lg-foot">
        {`Projections: ${weekly?.model_version ?? "none"} (production; weekly v2 stays in shadow) · build ${formatEastern(bundle.metadata.generated_at_utc)} · ROS through week ${String(bundle.throughWeek)} · ${LINEUP_RULE_VERSION}`}
      </p>

      {slotOpen !== null && (
        <SlotDialog
          league={league}
          slot={slotOpen}
          universe={universe}
          nameOf={name}
          positionOf={(id) => universe.get(id)?.position ?? null}
          availabilityOf={availabilityOf}
          onEdit={commitRoster}
          onClose={onCloseSlot}
          onSelect={onSelect}
          onCompare={(ids) => {
            onChange({ view: "startsit", scoring: league.scoring, teams: league.teams, duel: ids });
          }}
          compareIds={comparablesFor(slotOpen, league.roster, weeks)}
        />
      )}
    </div>
  );
}

/** Time one optimiser run; `measure-leagues.mjs` reads the `leagues-optimize` entries. */
function measured(run: () => LineupProposal): LineupProposal {
  const timed = typeof performance !== "undefined" && typeof performance.measure === "function";
  const started = timed ? performance.now() : 0;
  const result = run();
  if (timed) performance.measure("leagues-optimize", { start: started, end: performance.now() });
  return result;
}

// -------------------------------------------------------------------------- auto lineup

function AutoLineup({
  proposal,
  league,
  weekly,
  name,
  writable,
  onMode,
  onApply,
  onUndo,
  message,
}: {
  readonly proposal: LineupProposal;
  readonly league: SavedLeague;
  readonly weekly: { readonly target: number; readonly generated: string; readonly kickedOff: boolean };
  readonly name: (id: string) => string;
  readonly writable: boolean;
  readonly onMode: (mode: LineupMode) => void;
  readonly onApply: (proposal: LineupProposal) => void;
  readonly onUndo: (() => void) | null;
  readonly message: string | null;
}): React.JSX.Element {
  const counted = proposal.starters.filter((line) => line.score !== null).length;
  const gaps = proposal.gaps.filter((gap) => gap.kind === "gap");
  const unscored = proposal.gaps.filter((gap) => gap.kind === "unscored");
  const label = MODE_LABELS[proposal.mode].toLowerCase();
  return (
    <section className="lg-auto" aria-labelledby="lg-auto-heading">
      <div className="lg-auto-head">
        <h3 id="lg-auto-heading" className="lg-section-title">{`Auto Start/Sit — week ${String(weekly.target)}`}</h3>
        <Segmented<LineupMode>
          name={`lg-mode-${league.id}`}
          label="Maximise"
          value={proposal.mode}
          options={LINEUP_MODES.map((value) => ({
            value,
            label: MODE_LABELS[value],
            description: `${MODE_LABELS[value]} (${value === "q50" ? "P50" : value === "q10" ? "P10" : "P90"}) of each starter`,
            disabled: !writable && value !== proposal.mode,
          }))}
          onChange={onMode}
        />
      </div>
      <p className="lg-help">
        {`Build ${formatEastern(weekly.generated)}. Maximises the ${sumLabel(proposal.mode, counted)} — not the team's joint ${label}, and not a chance to win your matchup. Bye, out and doubtful players sit; questionable or unknown status starts "if active"; started games are locked; IR is untouched.`}
      </p>
      {weekly.kickedOff && (
        <Notice severity="warning" title={`Every week-${String(weekly.target)} game had kicked off when this build ran.`}>
          Nothing can be moved until the next week&rsquo;s projections publish.
        </Notice>
      )}
      <p className="lg-auto-totals" role="status">
        <span>{`Your lineup: ${points(proposal.currentTotal)}`}</span>
        <span>{`Best legal lineup: ${points(proposal.total)}`}</span>
        <span className="lg-muted">{`(${sumLabel(proposal.mode, counted)}; ${String(proposal.filled)} of ${String(proposal.starterSlots)} slots filled with a player who can play)`}</span>
      </p>
      {proposal.moves.length === 0 ? (
        <p className="lg-auto-none">{`Your lineup is already the best legal lineup for the ${label}.`}</p>
      ) : (
        <ol className="lg-moves" aria-label="Proposed changes">
          {proposal.moves.map((move) => {
            const week = proposal.weeks.get(move.id);
            const score = week?.record?.quantiles?.[proposal.mode] ?? null;
            const to = slotLongName(move.to, league.slots);
            const from = slotLongName(move.from, league.slots);
            const starting = move.to.group !== "BN";
            return (
              <li key={move.id} data-direction={starting ? "in" : "out"}>
                {starting
                  ? `Start ${name(move.id)} at ${to}${score === null ? "" : ` (${points(score)})`} — from ${from}`
                  : `Bench ${name(move.id)} — from ${from}${week?.reason != null ? `: ${week.reason}` : score === null ? "" : ` (${points(score)})`}`}
                {week?.conditional === true && starting && <span className="lg-if-active"> · if active</span>}
              </li>
            );
          })}
        </ol>
      )}
      {gaps.length > 0 && (
        <ul className="lg-gaps" aria-label="Slots that cannot be filled">
          {gaps.map((gap) => (
            <li key={`${gap.slot.group}:${String(gap.slot.index)}`}>
              <strong>{slotLongName(gap.slot, league.slots)}:</strong> {gap.reason}
            </li>
          ))}
        </ul>
      )}
      {unscored.length > 0 && (
        <ul className="lg-gaps" data-kind="unscored" aria-label="Players left in place">
          {unscored.map((gap) => (
            <li key={`${gap.slot.group}:${String(gap.slot.index)}`}>
              <strong>{slotLongName(gap.slot, league.slots)}:</strong> {gap.reason}
            </li>
          ))}
        </ul>
      )}
      <div className="lg-auto-actions">
        <button
          type="button"
          className="button chamfer"
          data-variant="primary"
          disabled={proposal.moves.length === 0 || !writable}
          onClick={() => {
            onApply(proposal);
          }}
        >
          {proposal.moves.length === 0 ? "Nothing to apply" : `Apply ${String(proposal.moves.length)} change${proposal.moves.length === 1 ? "" : "s"}`}
        </button>
        {onUndo !== null && (
          <button type="button" className="button" onClick={onUndo}>
            Undo
          </button>
        )}
        {message !== null && (
          <span className="lg-help" role="status">
            {message}
          </span>
        )}
      </div>
    </section>
  );
}
