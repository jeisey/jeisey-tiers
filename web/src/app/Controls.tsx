/**
 * The global control strip and the view tabs.
 *
 * One compact row on desktop, wrapping to two on tablet. On a phone the strip folds behind one
 * sticky summary row above the tabs, and opens from it (ADR-093). Every control writes to the
 * URL, so the state a user is looking at is the state they can send someone
 * (`docs/UX_SPEC.md` section 3); whether the phone panel is open is not board state and is
 * not in the URL.
 */

import { useCallback, useEffect, useId, useRef, useState } from "react";

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
 * Board, Start/Sit (ADR-096), Opportunity Board and Pick of the Week. `Data` is shared, because the methodology
 * and provenance a reader needs do not change with the season.
 *
 * `POTW` sits last of the three in-season boards because it is the narrowest: the two boards
 * before it publish every row, and it publishes four of them. A reader who disagrees with a
 * pick needs the board it was selected from to be one click away, and reading order is the
 * cheapest way to say which is which (ADR-088).
 *
 * The other mode's boards are still *reachable* — a URL naming them opens them, and the
 * mode switch is one click — they are simply not what this mode leads with.
 */
interface TabSpec {
  readonly id: ResolvedViewId;
  readonly label: string;
  /**
   * A narrow-screen label. The full label stays in the accessible name (visually hidden at
   * that width), so a screen reader still hears "Opportunity" where a phone shows "Opp".
   */
  readonly short?: string;
}

const DRAFT_TABS: readonly TabSpec[] = [
  { id: "tiers", label: "Tiers" },
  { id: "arbitrage", label: "Arbitrage" },
  { id: "data", label: "Data" },
];

const IN_SEASON_TABS: readonly TabSpec[] = [
  { id: "ros", label: "ROS tiers" },
  // Second, beside the board it is read against: this week's decision is the one a manager
  // makes most often, and the rest-of-season board is its context (ADR-096).
  { id: "startsit", label: "Start/Sit" },
  // Third: the other decision read off the rest-of-season board, priced in its units (ADR-100).
  { id: "trade", label: "Trade" },
  { id: "opportunity", label: "Opportunity", short: "Opp" },
  { id: "potw", label: "POTW" },
  { id: "data", label: "Data" },
];

export function tabsForMode(mode: "draft" | "in_season"): readonly TabSpec[] {
  return mode === "in_season" ? IN_SEASON_TABS : DRAFT_TABS;
}

/**
 * Bring a tab fully into the horizontally scrolled row, without animating when the reader asked
 * for reduced motion. The row is scrolled by hand rather than with `scrollIntoView`: that call
 * would also move Chrome's sequential-focus starting point to the tab, so the first Tab key on
 * a fresh page would skip the skip link and every control above the board. Nothing happens when
 * the tab is already in view, which is the ordinary desktop case.
 */
function reveal(row: HTMLElement | null, tab: HTMLElement | null): void {
  if (row === null || tab === null || typeof row.scrollBy !== "function") return;
  const bounds = row.getBoundingClientRect();
  const box = tab.getBoundingClientRect();
  const margin = 20;
  let delta = 0;
  if (box.left < bounds.left) delta = box.left - bounds.left - margin;
  else if (box.right > bounds.right) delta = box.right - bounds.right + margin;
  if (delta === 0) return;
  const reduced =
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  row.scrollBy({ left: delta, behavior: reduced ? "auto" : "smooth" });
}

/**
 * The view tabs.
 *
 * Six in-season tabs do not fit a 320px row at a legible size, so the row scrolls sideways
 * rather than shrinking text or tap targets (ADR-100). Three things keep that usable: the
 * active tab is scrolled into view whenever it changes, a focused tab is scrolled into view so
 * a keyboard reader never tabs onto something off screen, and an edge marker says when there
 * is more row in either direction. Below 560px "Opportunity" prints as "Opp",
 * with the full word kept in the accessible name.
 */
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
  const list = useRef<HTMLDivElement>(null);
  const keyboard = useRef(false);
  const [overflow, setOverflow] = useState<{ start: boolean; end: boolean }>({ start: false, end: false });

  const measure = useCallback(() => {
    const element = list.current;
    if (element === null) return;
    const start = element.scrollLeft > 1;
    const end = element.scrollLeft + element.clientWidth < element.scrollWidth - 1;
    setOverflow((current) => (current.start === start && current.end === end ? current : { start, end }));
  }, []);

  useEffect(() => {
    const element = list.current;
    if (element === null) return;
    measure();
    element.addEventListener("scroll", measure, { passive: true });
    const observer = typeof ResizeObserver === "function" ? new ResizeObserver(measure) : null;
    observer?.observe(element);
    return () => {
      element.removeEventListener("scroll", measure);
      observer?.disconnect();
    };
  }, [measure, mode]);

  // The active tab is always on screen; after an arrow key, focus follows it (WAI-ARIA tabs).
  useEffect(() => {
    const active = list.current?.querySelector<HTMLButtonElement>(`#tab-${view}`) ?? null;
    reveal(list.current, active);
    if (keyboard.current) {
      keyboard.current = false;
      active?.focus();
    }
    measure();
  }, [view, measure]);

  return (
    <div className="tabs-row" data-overflow-start={overflow.start || undefined} data-overflow-end={overflow.end || undefined}>
      <span className="tabs-more tabs-more-start" aria-hidden="true">‹</span>
      <div className="tabs" role="tablist" aria-label="Board" ref={list}>
        {tabs.map((tab) => (
          <button
            key={tab.id}
            type="button"
            role="tab"
            id={`tab-${tab.id}`}
            aria-selected={view === tab.id}
            aria-controls={`panel-${tab.id}`}
            tabIndex={view === tab.id ? 0 : -1}
            onFocus={(event) => {
              reveal(list.current, event.currentTarget);
            }}
            onKeyDown={(event) => {
              const step = event.key === "ArrowRight" ? 1 : event.key === "ArrowLeft" ? -1 : 0;
              if (step === 0) return;
              event.preventDefault();
              const index = tabs.findIndex((candidate) => candidate.id === view);
              const next = tabs[(index + step + tabs.length) % tabs.length];
              if (next !== undefined) {
                keyboard.current = true;
                onChange(next.id);
              }
            }}
            onClick={() => {
              onChange(tab.id);
            }}
          >
            {tab.short === undefined ? (
              tab.label
            ) : (
              <>
                <span className="tab-label-long">{tab.label}</span>
                <span className="tab-label-short" aria-hidden="true">
                  {tab.short}
                </span>
              </>
            )}
            {tab.id === "arbitrage" && !arbitrageAvailable && (
              <span className="visually-hidden"> (market comparison unavailable)</span>
            )}
          </button>
        ))}
      </div>
      <span className="tabs-more tabs-more-end" aria-hidden="true">›</span>
      {rowCount !== undefined && (
        <span className="tabs-count" role="status">
          {`${String(rowCount.shown)} of ${String(rowCount.total)} rows`}
        </span>
      )}
    </div>
  );
}

/**
 * The season-mode switch, and the cutoff it is switching between.
 *
 * Rendered only when there is something to switch to. Before kickoff there is no in-season
 * bundle, so a two-state control would offer an empty board — and a band whose only content
 * is a mode the tabs beneath it already show is worse than no band, because it costs the top
 * of every phone screen for a repetition.
 */
export function SeasonMode({
  mode,
  resolved,
  onChange,
  throughWeek,
  available,
}: {
  readonly mode: ModeId;
  readonly resolved: "draft" | "in_season";
  readonly onChange: (mode: ModeId) => void;
  readonly throughWeek: number | null;
  /** False before kickoff: no in-season bundle exists, so there is nothing to switch to. */
  readonly available: boolean;
}): React.JSX.Element | null {
  if (!available) return null;
  const detail =
    throughWeek === null ? "no rest-of-season cutoff" : `through week ${String(throughWeek)}`;
  return (
    <div className="season-mode" data-mode={resolved}>
      <span className="season-mode-detail muted">{detail}</span>
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
    </div>
  );
}

/**
 * What the folded settings bar prints on a phone (ADR-093).
 *
 * Every folded control's value, so a reader can tell which board is on screen without opening
 * the panel — a folded control whose value you cannot see is a filter you can forget is on.
 * Two items appear only when they say something: the search term, when there is one, and the
 * season mode, when a reader has overridden `auto` — the tabs already show which board the
 * schedule chose. The mode goes last although its switch is first in the panel: at 320px
 * the row ellipsises, and a rare override should be what is cut, not the scoring.
 *
 * Every value is the URL's, so the summary is the applied state: a search still inside its
 * debounce is not on the board yet and is not printed here yet either.
 */
export function settingsSummary(state: AppState, modeSwitch: boolean): readonly string[] {
  const items: string[] = [
    state.scoring === "half" ? "Half" : state.scoring.toUpperCase(),
    `${String(state.teams)} teams`,
    state.position === "all" ? "All positions" : POSITION_LABELS[state.position],
  ];
  if (state.search !== "") items.push(`“${state.search}”`);
  if (modeSwitch && state.mode !== "auto") {
    items.push(state.mode === "draft" ? "Draft mode" : "In-season mode");
  }
  return items;
}

export function Controls({
  state,
  onChange,
  availableScoring,
  availableTeams,
  onRevealSearch,
}: {
  readonly state: AppState;
  readonly onChange: (next: Partial<AppState>) => void;
  readonly availableScoring: ReadonlySet<ScoringValue>;
  readonly availableTeams: ReadonlySet<TeamCount>;
  /**
   * Make the search box visible, synchronously, before the `/` shortcut focuses it. On a phone
   * the box can be inside a folded panel, and focusing an element that is not rendered does
   * nothing at all (ADR-093).
   */
  readonly onRevealSearch?: (() => void) | undefined;
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
          onReveal={onRevealSearch}
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
  onReveal,
}: {
  readonly value: string;
  readonly onChange: (value: string) => void;
  /** Called before the shortcut focuses the box, when the box is not rendered. */
  readonly onReveal?: (() => void) | undefined;
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
      // A box inside a folded phone panel has no layout box, and `focus()` on it would be a
      // silent no-op. Ask for it to be shown first; the caller shows it synchronously.
      if (input.current !== null && input.current.getClientRects().length === 0) onReveal?.();
      input.current?.focus();
      input.current?.select();
    };
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [onReveal]);

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
