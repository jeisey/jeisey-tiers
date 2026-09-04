/**
 * The global control strip and the view tabs.
 *
 * One compact row on desktop, wrapping to two on tablet, sticky on mobile. Every control
 * writes to the URL, so the state a user is looking at is the state they can send someone
 * (`docs/UX_SPEC.md` section 3).
 */

import { useEffect, useId, useRef, useState } from "react";

import { Segmented } from "../components/primitives";
import type {
  AppState,
  ModeId,
  PositionFilter,
  ResolvedViewId,
  ScoringValue,
  TeamCount,
} from "../data/state";
import {
  POSITION_FILTERS,
  POSITION_LABELS,
  SCORING_LABELS,
  SCORING_VALUES,
  TEAM_COUNTS,
} from "../data/state";

/**
 * The tab set each mode owns.
 *
 * Roadmap 12.4: Draft mode is Tier Board plus Arbitrage Board; In-Season mode is ROS Tier
 * Board plus Opportunity Board. `Data` is shared, because the methodology and provenance a
 * reader needs do not change with the season.
 *
 * The other mode's boards are still *reachable* — a URL naming them opens them, and the
 * mode switch is one click — they are simply not what this mode leads with.
 */
const DRAFT_TABS: readonly { id: ResolvedViewId; label: string }[] = [
  { id: "tiers", label: "Tiers" },
  { id: "arbitrage", label: "Arbitrage" },
  { id: "data", label: "Data" },
];

const IN_SEASON_TABS: readonly { id: ResolvedViewId; label: string }[] = [
  { id: "ros", label: "ROS tiers" },
  { id: "opportunity", label: "Opportunity" },
  { id: "data", label: "Data" },
];

export function tabsForMode(mode: "draft" | "in_season"): readonly {
  id: ResolvedViewId;
  label: string;
}[] {
  return mode === "in_season" ? IN_SEASON_TABS : DRAFT_TABS;
}

export function ViewTabs({
  view,
  onChange,
  arbitrageAvailable,
  rowCount,
  mode,
}: {
  readonly view: ResolvedViewId;
  readonly onChange: (view: ResolvedViewId) => void;
  readonly arbitrageAvailable: boolean;
  /** Which tab set to show. The reader's resolved mode, never the raw URL value. */
  readonly mode: "draft" | "in_season";
  /**
   * The design source prints `{{ shownCount }} OF 300 ROWS` beside its navigation. Both
   * numbers are counts of rows the current filters select against the rows the build
   * published; nothing here is a literal and nothing is computed from a value.
   */
  readonly rowCount?: { readonly shown: number; readonly total: number } | undefined;
}): React.JSX.Element {
  const tabs = tabsForMode(mode);
  return (
    <div className="tabs-row">
      <div className="tabs" role="tablist" aria-label="Board">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            type="button"
            role="tab"
            id={`tab-${tab.id}`}
            aria-selected={view === tab.id}
            aria-controls={`panel-${tab.id}`}
            tabIndex={view === tab.id ? 0 : -1}
            onKeyDown={(event) => {
              const step = event.key === "ArrowRight" ? 1 : event.key === "ArrowLeft" ? -1 : 0;
              if (step === 0) return;
              event.preventDefault();
              const index = tabs.findIndex((candidate) => candidate.id === view);
              const next = tabs[(index + step + tabs.length) % tabs.length];
              if (next !== undefined) onChange(next.id);
            }}
            onClick={() => {
              onChange(tab.id);
            }}
          >
            {tab.label}
            {tab.id === "arbitrage" && !arbitrageAvailable && (
              <span className="visually-hidden"> (market comparison unavailable)</span>
            )}
          </button>
        ))}
      </div>
      {rowCount !== undefined && (
        <span className="tabs-count" role="status">
          {`${String(rowCount.shown)} of ${String(rowCount.total)} rows`}
        </span>
      )}
    </div>
  );
}

/**
 * The season-mode indicator and switch.
 *
 * One obvious indicator (roadmap 12.4), and it says *why* it is what it is: the mode is
 * derived from the NFL schedule, so a reader who wonders why the site changed in September
 * gets the answer in the same sentence as the control that overrides it.
 *
 * The switch appears only when there is something to switch to. Before kickoff there is no
 * in-season bundle, so a two-state control would offer an empty board.
 */
export function SeasonMode({
  mode,
  resolved,
  onChange,
  seasonState,
  throughWeek,
  available,
}: {
  readonly mode: ModeId;
  readonly resolved: "draft" | "in_season";
  readonly onChange: (mode: ModeId) => void;
  readonly seasonState: string;
  readonly throughWeek: number | null;
  /** False before kickoff: no in-season bundle exists, so there is nothing to switch to. */
  readonly available: boolean;
}): React.JSX.Element {
  const label = resolved === "in_season" ? "In-Season" : "Draft";
  const detail =
    resolved === "in_season" && throughWeek !== null
      ? `through week ${String(throughWeek)}`
      : seasonState.replace(/_/g, " ");
  return (
    <div className="season-mode" data-mode={resolved}>
      <span className="season-mode-label">
        <span className="season-mode-dot" aria-hidden="true" />
        {label} mode
      </span>
      <span className="season-mode-detail muted">{detail}</span>
      {available && (
        <Segmented<ModeId>
          name="mode"
          label="Season mode"
          value={mode}
          options={[
            { value: "auto", label: "Auto", description: "Follow the NFL schedule" },
            { value: "draft", label: "Draft", description: "Preseason board" },
            { value: "in_season", label: "In-season", description: "Rest-of-season board" },
          ]}
          onChange={onChange}
        />
      )}
    </div>
  );
}

export function Controls({
  state,
  onChange,
  availableScoring,
  availableTeams,
}: {
  readonly state: AppState;
  readonly onChange: (next: Partial<AppState>) => void;
  readonly availableScoring: ReadonlySet<ScoringValue>;
  readonly availableTeams: ReadonlySet<TeamCount>;
}): React.JSX.Element {
  return (
    <div className="controls">
      <Segmented<ScoringValue>
        name="scoring"
        label="Scoring"
        value={state.scoring}
        options={SCORING_VALUES.map((value) => ({
          value,
          label: value === "half" ? "Half" : value.toUpperCase(),
          description: SCORING_LABELS[value],
          disabled: !availableScoring.has(value),
        }))}
        onChange={(scoring) => {
          onChange({ scoring });
        }}
      />
      <Segmented<TeamCount>
        name="teams"
        label="Teams"
        value={state.teams}
        options={TEAM_COUNTS.map((value) => ({
          value,
          label: String(value),
          description: `${String(value)}-team league`,
          disabled: !availableTeams.has(value),
        }))}
        onChange={(teams) => {
          onChange({ teams });
        }}
      />
      <Segmented<PositionFilter>
        name="position"
        label="Position"
        value={state.position}
        options={POSITION_FILTERS.map((value) => ({
          value,
          label: POSITION_LABELS[value],
          description: value === "all" ? "All positions" : POSITION_LABELS[value],
        }))}
        onChange={(position) => {
          onChange({ position });
        }}
      />
      <div className="control control-spacer">
        <PlayerSearch
          value={state.search}
          onChange={(search) => {
            onChange({ search });
          }}
        />
      </div>
    </div>
  );
}

/**
 * The search box.
 *
 * Locally controlled and pushed to the URL on a short debounce: typing eight characters should
 * not leave eight entries in the browser's history, and the address bar should not flicker on
 * every keystroke. The value is still fully shareable — it is in the URL as soon as typing
 * pauses, and immediately on blur or Enter.
 */
export function PlayerSearch({
  value,
  onChange,
}: {
  readonly value: string;
  readonly onChange: (value: string) => void;
}): React.JSX.Element {
  const id = useId();
  const input = useRef<HTMLInputElement>(null);
  const [draft, setDraft] = useState(value);
  const [lastPropValue, setLastPropValue] = useState(value);

  // Adopt an externally-driven change (back/forward, or a cleared filter) by adjusting state
  // during render rather than in an effect: React re-renders immediately with the new value
  // instead of painting the stale one first.
  if (lastPropValue !== value) {
    setLastPropValue(value);
    setDraft(value);
  }

  useEffect(() => {
    if (draft === value) return;
    const timer = setTimeout(() => {
      onChange(draft);
    }, 220);
    return () => {
      clearTimeout(timer);
    };
  }, [draft, onChange, value]);

  /**
   * `/` focuses the search box — the shortcut the design source advertises with a key hint
   * inside the field. It is ignored whenever the keystroke could be text: any modifier, any
   * form control, any editable element, or an open dialog, which is where a drafter typing a
   * name into the card's own controls would otherwise lose the character.
   */
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent): void => {
      if (event.key !== "/" || event.metaKey || event.ctrlKey || event.altKey) return;
      const active = document.activeElement;
      if (
        active instanceof HTMLInputElement ||
        active instanceof HTMLTextAreaElement ||
        active instanceof HTMLSelectElement ||
        (active instanceof HTMLElement && active.isContentEditable) ||
        active?.closest("dialog[open]") != null
      ) {
        return;
      }
      event.preventDefault();
      input.current?.focus();
      input.current?.select();
    };
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
    };
  }, []);

  return (
    <>
      <label className="control-label" htmlFor={id}>
        Player search
      </label>
      <div className="search-field">
        <input
          ref={input}
          id={id}
          type="search"
          value={draft}
          placeholder="Name, team or position"
          autoComplete="off"
          spellCheck={false}
          onChange={(event) => {
            setDraft(event.target.value);
          }}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.preventDefault();
              onChange(draft);
            }
            if (event.key === "Escape" && draft !== "") {
              event.preventDefault();
              setDraft("");
              onChange("");
            }
          }}
        />
        {draft === "" ? (
          <span className="search-key" aria-hidden="true">
            /
          </span>
        ) : (
          <button
            type="button"
            aria-label="Clear player search"
            onClick={() => {
              setDraft("");
              onChange("");
            }}
          >
            ×
          </button>
        )}
      </div>
    </>
  );
}
