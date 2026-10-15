/**
 * The player search, in a dialog (ADR-111): the query and its results on screen together.
 *
 * One component for every "find a player" on the boards. The board search (Controls) applies
 * what is chosen to the open board; Start/Sit's empty cards add the chosen player to the
 * comparison. Both are the shared `Modal` around the shared `PlayerCombobox`, over a pool the
 * caller already has in memory — the open board's own rows — so typing re-renders this dialog
 * and nothing behind it, and no file is fetched for a search.
 *
 * Nothing is committed until a choice is made: Cancel, the close button, the backdrop and
 * Escape (after it has cleared any text) all leave the page as it was.
 */

import { useCallback, useId, useMemo, useState } from "react";

import { searchPlayers, type SearchEntry } from "../data/playerSearch";
import { Modal } from "./Modal";
import { PlayerCombobox, type ComboOption } from "./PlayerCombobox";

/** How many results the list shows at once: a screenful above a phone keyboard. */
const SHOWN = 8;

function toOption(entry: SearchEntry): ComboOption {
  const reason = entry.unavailableReason;
  return {
    id: entry.id,
    name: entry.name,
    position: entry.position,
    availability: entry.availability,
    status: entry.status,
    meta: reason ?? entry.meta ?? entry.team ?? "—",
    note: reason,
    disabled: reason !== undefined,
  };
}

export function PlayerPickerDialog({
  title,
  label,
  help,
  pool,
  poolName,
  onPick,
  onClose,
  onApply,
  initialQuery = "",
}: {
  readonly title: string;
  /** The input's accessible name. */
  readonly label: string;
  /** One line saying what choosing a player does here. */
  readonly help: string;
  /** The players to search; null while the board's rows are still loading. */
  readonly pool: readonly SearchEntry[] | null;
  /** What the pool is, for "No player on … matches". */
  readonly poolName: string;
  readonly onPick: (entry: SearchEntry) => void;
  readonly onClose: () => void;
  /** Apply the query as typed (every match). Only where a partial query means something. */
  readonly onApply?: ((query: string) => void) | undefined;
  readonly initialQuery?: string;
}): React.JSX.Element {
  const id = useId();
  const [query, setQuery] = useState(initialQuery);
  const byId = useMemo(() => new Map((pool ?? []).map((entry) => [entry.id, entry])), [pool]);
  const search = useCallback(
    (text: string) => (pool === null ? [] : searchPlayers(pool, text, SHOWN).entries.map(toOption)),
    [pool],
  );
  const total = useMemo(() => (pool === null ? 0 : searchPlayers(pool, query, 0).total), [pool, query]);
  const typed = query.trim() !== "";

  const apply =
    onApply === undefined
      ? undefined
      : (text: string): void => {
          // A query with no match would only empty the board; the status line already says so.
          if (text.trim() !== "" && pool !== null && searchPlayers(pool, text, 0).total > 0) onApply(text.trim());
        };

  let status = "";
  if (pool === null) status = "Loading players…";
  else if (!typed) status = "";
  else if (total === 0) status = `No player on ${poolName} matches “${query.trim()}”.`;
  else if (total > SHOWN) status = `${String(SHOWN)} of ${String(total)} matches shown. Keep typing to narrow them.`;
  else status = `${String(total)} ${total === 1 ? "match" : "matches"}.`;

  return (
    <Modal title={title} onClose={onClose} picker>
      <div className="picker">
        <p className="lg-help" id={`${id}-help`}>
          {help}
        </p>
        <PlayerCombobox
          className="trade-picker lg-picker"
          label={label}
          placeholder="Name, team or position"
          search={search}
          onPick={(playerId) => {
            const entry = byId.get(playerId);
            if (entry !== undefined && entry.unavailableReason === undefined) onPick(entry);
          }}
          autoFocus
          persistent
          autoActive={onApply === undefined}
          onSubmit={apply}
          onQueryChange={setQuery}
          initialQuery={initialQuery}
          describedBy={`${id}-help ${id}-status`}
        />
        <p className="picker-status" id={`${id}-status`} role="status" aria-live="polite">
          {status}
        </p>
        <div className="picker-actions">
          {apply !== undefined && typed && total > 0 && (
            <button
              type="button"
              className="button"
              onClick={() => {
                apply(query);
              }}
            >
              {total === 1 ? "Show the match" : `Show all ${String(total)} matches`}
            </button>
          )}
          <button type="button" className="button-link" onClick={onClose}>
            Cancel
          </button>
        </div>
      </div>
    </Modal>
  );
}
