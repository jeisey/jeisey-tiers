/**
 * The player search box: an ARIA 1.2 combobox over a list the caller computes.
 *
 * Extracted from the Trade tab's outgoing-player search (ADR-100) so My Leagues' slot picker
 * (ADR-106) is the same control rather than a copy: type a few letters, arrow through at most a
 * handful of suggestions, Enter or click to pick, Escape to clear. The list is a listbox the
 * input owns through `aria-activedescendant`, so focus never leaves the input and a screen
 * reader hears each option as it is reached.
 */

import { useId, useMemo, useRef, useState } from "react";

import type { Availability } from "../data/availability";
import type { Position } from "../data/contracts";
import { AvailabilityBadge, PositionTag } from "./primitives";

export interface ComboOption {
  readonly id: string;
  readonly name: string;
  readonly position: Position;
  /** One short trailing line: club and a published number. */
  readonly meta: string;
  readonly availability?: Availability | undefined;
  /** Extra words for the option's accessible name (where he is now, why he fits). */
  readonly note?: string | undefined;
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
}): React.JSX.Element {
  const id = useId();
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  const options = useMemo(() => (query.trim() === "" ? [] : search(query)), [search, query]);

  const pick = (option: ComboOption | undefined): void => {
    if (option === undefined) return;
    onPick(option.id);
    setQuery("");
    setOpen(false);
    input.current?.focus();
  };
  const expanded = open && options.length > 0;
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
        aria-activedescendant={expanded ? `${id}-opt-${String(active)}` : undefined}
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
          setActive(0);
          setOpen(true);
        }}
        onBlur={() => {
          setOpen(false);
        }}
        onFocus={() => {
          setOpen(true);
        }}
        onKeyDown={(event) => {
          if (event.key === "ArrowDown") {
            event.preventDefault();
            setOpen(true);
            setActive((value) => Math.min(value + 1, Math.max(0, options.length - 1)));
          } else if (event.key === "ArrowUp") {
            event.preventDefault();
            setActive((value) => Math.max(value - 1, 0));
          } else if (event.key === "Enter") {
            if (expanded) {
              event.preventDefault();
              pick(options[active]);
            }
          } else if (event.key === "Escape") {
            // Only when there is something to clear: text, or a list on screen. Focus alone opens
            // nothing visible, so a bare Escape belongs to the dialog around the picker.
            if (query !== "" || expanded) {
              // Stop here: inside a dialog, the first Escape clears the search, not the dialog.
              event.preventDefault();
              event.stopPropagation();
              setQuery("");
              setOpen(false);
            }
          }
        }}
      />
      <ul id={`${id}-list`} role="listbox" className="trade-options" hidden={!expanded} aria-label="Players">
        {options.map((option, index) => (
          <li
            key={option.id}
            id={`${id}-opt-${String(index)}`}
            role="option"
            aria-selected={index === active}
            onMouseDown={(event) => {
              // Before the input's blur closes the list.
              event.preventDefault();
              pick(option);
            }}
          >
            <PositionTag position={option.position} />
            <span className="trade-option-name">{option.name}</span>
            <AvailabilityBadge availability={option.availability} />
            <span className="trade-option-meta">{option.meta}</span>
            {option.note !== undefined && <span className="visually-hidden">{`, ${option.note}`}</span>}
          </li>
        ))}
      </ul>
    </div>
  );
}
