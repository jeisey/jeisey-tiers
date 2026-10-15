/**
 * The player search box: an ARIA 1.2 combobox over a list the caller computes.
 *
 * Extracted from the Trade tab's outgoing-player search (ADR-100) so My Leagues' slot picker
 * (ADR-106) is the same control rather than a copy: type a few letters, arrow through at most a
 * handful of suggestions, Enter or click to pick, Escape to clear. The list is a listbox the
 * input owns through `aria-activedescendant`, so focus never leaves the input and a screen
 * reader hears each option as it is reached.
 *
 * ADR-111 makes it the site's one player search: the board search and Start/Sit's add-player
 * picker (`PlayerPickerDialog`) use it inside a dialog, where the results stay on screen under
 * the query (`persistent`), Enter with no option chosen applies the query as typed
 * (`onSubmit`), and an option can be shown but not chosen (`disabled`, with its reason in
 * `meta`).
 */

import { useId, useMemo, useRef, useState } from "react";

import type { Availability } from "../data/availability";
import type { PlayerStatusRecord, Position } from "../data/contracts";
import { AvailabilityBadge, PositionTag, StatusBadge } from "./primitives";

export interface ComboOption {
  readonly id: string;
  readonly name: string;
  readonly position: Position;
  /** One short trailing line: club and a published number. */
  readonly meta: string;
  readonly availability?: Availability | undefined;
  /** The draft board's status annotation, where there is no availability reading. */
  readonly status?: PlayerStatusRecord | null | undefined;
  /** Extra words for the option's accessible name (where he is now, why he fits). */
  readonly note?: string | undefined;
  /** Listed so the reader can see why, but not choosable (already chosen, no projection). */
  readonly disabled?: boolean | undefined;
}

export function PlayerCombobox({
  label,
  placeholder,
  disabled = false,
  search,
  onPick,
  className = "trade-picker",
  autoFocus = false,
  describedBy,
  persistent = false,
  autoActive = true,
  onSubmit,
  onQueryChange,
  initialQuery = "",
  listLabel = "Players",
}: {
  /** The accessible label (visually hidden: the placeholder and context carry it visibly). */
  readonly label: string;
  readonly placeholder: string;
  readonly disabled?: boolean;
  /** The suggestions for a query; called only for a non-empty query. */
  readonly search: (query: string) => readonly ComboOption[];
  readonly onPick: (id: string) => void;
  readonly className?: string;
  readonly autoFocus?: boolean;
  readonly describedBy?: string | undefined;
  /** Keep the results on screen whenever the query has any, focused or not (in a dialog). */
  readonly persistent?: boolean;
  /**
   * Start with the first option active, so Enter picks it. Off where Enter has a meaning of its
   * own (`onSubmit`): the reader arrows to an option to choose one.
   */
  readonly autoActive?: boolean;
  /** Enter with no option active: use the query as typed (the board search applies it). */
  readonly onSubmit?: ((query: string) => void) | undefined;
  readonly onQueryChange?: ((query: string) => void) | undefined;
  /** The query to start from (the board's current search), selected so typing replaces it. */
  readonly initialQuery?: string;
  readonly listLabel?: string;
}): React.JSX.Element {
  const id = useId();
  const start = autoActive ? 0 : -1;
  const [query, setQueryState] = useState(initialQuery);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(start);
  const input = useRef<HTMLInputElement>(null);
  const selected = useRef(initialQuery === "");
  const options = useMemo(() => (query.trim() === "" ? [] : search(query)), [search, query]);
  const setQuery = (next: string): void => {
    setQueryState(next);
    onQueryChange?.(next);
  };

  const pick = (option: ComboOption | undefined): void => {
    if (option === undefined || option.disabled === true) return;
    onPick(option.id);
    setQuery("");
    setOpen(false);
    input.current?.focus();
  };
  const expanded = (open || persistent) && options.length > 0;
  const current = expanded && active >= 0 && active < options.length ? active : -1;
  return (
    <div className={className}>
      <label className="visually-hidden" htmlFor={id}>
        {label}
      </label>
      <input
        ref={input}
        id={id}
        type="search"
        role="combobox"
        aria-expanded={expanded}
        aria-controls={`${id}-list`}
        aria-autocomplete="list"
        aria-activedescendant={current >= 0 ? `${id}-opt-${String(current)}` : undefined}
        aria-describedby={describedBy}
        autoComplete="off"
        spellCheck={false}
        // A dialog's picker is the one control the reader opened it for; the dialog focuses it.
        data-autofocus={autoFocus || undefined}
        disabled={disabled}
        placeholder={placeholder}
        value={query}
        onChange={(event) => {
          setQuery(event.target.value);
          setActive(start);
          setOpen(true);
        }}
        onBlur={() => {
          setOpen(false);
        }}
        onFocus={(event) => {
          setOpen(true);
          // A query carried in from the board is selected once, so typing replaces it.
          if (!selected.current) {
            selected.current = true;
            event.currentTarget.select();
          }
        }}
        onKeyDown={(event) => {
          if (event.key === "ArrowDown") {
            event.preventDefault();
            setOpen(true);
            setActive((value) => Math.min(value + 1, Math.max(0, options.length - 1)));
          } else if (event.key === "ArrowUp") {
            event.preventDefault();
            setActive((value) => Math.max(value - 1, start));
          } else if (event.key === "Enter") {
            if (current >= 0) {
              event.preventDefault();
              pick(options[current]);
            } else if (onSubmit !== undefined) {
              event.preventDefault();
              onSubmit(query);
            }
          } else if (event.key === "Escape") {
            // Only when there is something to clear: text, or a list on screen. Focus alone opens
            // nothing visible, so a bare Escape belongs to the dialog around the picker.
            if (query !== "" || expanded) {
              // Stop here: inside a dialog, the first Escape clears the search, not the dialog.
              event.preventDefault();
              event.stopPropagation();
              setQuery("");
              setActive(start);
              setOpen(false);
            }
          }
        }}
      />
      <ul id={`${id}-list`} role="listbox" className="trade-options" hidden={!expanded} aria-label={listLabel}>
        {options.map((option, index) => (
          <li
            key={option.id}
            id={`${id}-opt-${String(index)}`}
            role="option"
            aria-selected={index === current}
            aria-disabled={option.disabled === true || undefined}
            onMouseDown={(event) => {
              // Before the input's blur closes the list.
              event.preventDefault();
              pick(option);
            }}
          >
            <PositionTag position={option.position} />
            <span className="trade-option-name">{option.name}</span>
            <AvailabilityBadge availability={option.availability} />
            {option.availability === undefined && <StatusBadge status={option.status ?? null} />}
            <span className="trade-option-meta">{option.meta}</span>
            {option.note !== undefined && <span className="visually-hidden">{`, ${option.note}`}</span>}
          </li>
        ))}
      </ul>
    </div>
  );
}
