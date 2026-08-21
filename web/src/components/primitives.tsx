/**
 * Small shared pieces.
 *
 * Nothing here holds state or fetches anything; they exist so a position tag, a tier label
 * and an injury badge look and read the same in a table cell, a chart tooltip and a dialog.
 */

import type { Position } from "../data/contracts";
import type { PlayerStatusRecord } from "../data/contracts";
import { statusBadge } from "../data/model";

export function PositionTag({ position }: { readonly position: Position }): React.JSX.Element {
  return (
    <span className="pos-tag" data-pos={position}>
      {position}
    </span>
  );
}

export function TierTag({ label }: { readonly label: string }): React.JSX.Element {
  return <span className="tier-tag">{label}</span>;
}

/**
 * The compact injury/status mark.
 *
 * Renders **only** when the artifact carries something meaningful. A null `injury_status` is
 * the absence of a reported designation, not a report of health, so nothing here ever emits
 * the word "Healthy" (ADR-043).
 */
export function StatusBadge({
  status,
}: {
  readonly status: PlayerStatusRecord | null;
}): React.JSX.Element | null {
  const badge = statusBadge(status);
  if (badge === null) return null;
  return (
    <span
      className="status-badge"
      data-severity={badge.severity}
      title={`${badge.full} — current status annotation, not a model input`}
    >
      <span aria-hidden="true">{badge.short}</span>
      <span className="visually-hidden">
        {`Current status: ${badge.full}. Annotation only; the projection does not use it.`}
      </span>
    </span>
  );
}

export type NoticeSeverity = "info" | "warning" | "error";

export function Notice({
  severity = "info",
  title,
  children,
  role,
}: {
  readonly severity?: NoticeSeverity;
  readonly title?: string;
  readonly children: React.ReactNode;
  readonly role?: "alert" | "status";
}): React.JSX.Element {
  return (
    <div className="notice" data-severity={severity} role={role}>
      {title !== undefined && <strong>{title}</strong>}{" "}
      {children}
    </div>
  );
}

export interface SegmentedOption<T extends string | number> {
  readonly value: T;
  readonly label: string;
  /** Long form for assistive technology when the visible label is an abbreviation. */
  readonly description?: string;
  readonly disabled?: boolean;
}

/**
 * A radio group rendered as a segmented control.
 *
 * `role="radiogroup"` with `aria-checked` rather than a row of toggle buttons: a screen reader
 * should hear "1 of 3", not three independent pressed states (UX spec section 12).
 */
export function Segmented<T extends string | number>({
  label,
  value,
  options,
  onChange,
  name,
}: {
  readonly label: string;
  readonly value: T;
  readonly options: readonly SegmentedOption<T>[];
  readonly onChange: (value: T) => void;
  readonly name: string;
}): React.JSX.Element {
  const labelId = `${name}-label`;
  return (
    <div className="control">
      <span className="control-label" id={labelId}>
        {label}
      </span>
      <div className="segmented" role="radiogroup" aria-labelledby={labelId}>
        {options.map((option) => (
          <button
            key={option.value}
            type="button"
            role="radio"
            aria-checked={option.value === value}
            aria-label={option.description ?? option.label}
            disabled={option.disabled}
            // Roving tabindex: the group is one tab stop, arrows move within it.
            tabIndex={option.value === value ? 0 : -1}
            onKeyDown={(event) => {
              const index = options.findIndex((candidate) => candidate.value === value);
              const step =
                event.key === "ArrowRight" || event.key === "ArrowDown"
                  ? 1
                  : event.key === "ArrowLeft" || event.key === "ArrowUp"
                    ? -1
                    : 0;
              if (step === 0) return;
              event.preventDefault();
              const next = options[(index + step + options.length) % options.length];
              if (next !== undefined && !(next.disabled ?? false)) onChange(next.value);
            }}
            onClick={() => {
              onChange(option.value);
            }}
          >
            {option.label}
          </button>
        ))}
      </div>
    </div>
  );
}
