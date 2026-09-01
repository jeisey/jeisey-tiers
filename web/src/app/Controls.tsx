/**
 * The global control strip and the view tabs.
 *
 * One compact row on desktop, wrapping to two on tablet, sticky on mobile. Every control
 * writes to the URL, so the state a user is looking at is the state they can send someone
 * (`docs/UX_SPEC.md` section 3).
 */

import { useEffect, useId, useRef, useState } from "react";

import { Segmented } from "../components/primitives";
import type { AppState, PositionFilter, ScoringValue, TeamCount, ViewId } from "../data/state";
import { POSITION_FILTERS, POSITION_LABELS, SCORING_LABELS, SCORING_VALUES, TEAM_COUNTS } from "../data/state";

const VIEW_TABS: readonly { id: ViewId; label: string }[] = [
  { id: "tiers", label: "Tiers" },
  { id: "arbitrage", label: "Arbitrage" },
  { id: "data", label: "Data" },
];

export function ViewTabs({
  view,
  onChange,
  arbitrageAvailable,
  rowCount,
}: {
  readonly view: ViewId;
  readonly onChange: (view: ViewId) => void;
  readonly arbitrageAvailable: boolean;
  /**
   * The design source prints `{{ shownCount }} OF 300 ROWS` beside its navigation. Both
   * numbers are counts of rows the current filters select against the rows the build
   * published; nothing here is a literal and nothing is computed from a value.
   */
  readonly rowCount?: { readonly shown: number; readonly total: number } | undefined;
}): React.JSX.Element {
  return (
    <div className="tabs-row">
      <div className="tabs" role="tablist" aria-label="Board">
        {VIEW_TABS.map((tab) => (
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
              const index = VIEW_TABS.findIndex((candidate) => candidate.id === view);
              const next = VIEW_TABS[(index + step + VIEW_TABS.length) % VIEW_TABS.length];
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
