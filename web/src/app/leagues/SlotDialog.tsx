/**
 * One roster slot's actions (ADR-106): add or replace a player through the shared player
 * search, move or swap him with any legal slot, remove him, open his card, or compare the slot
 * in Start/Sit. Every action is a click or a key; nothing needs dragging.
 *
 * The search offers players who fit the slot. A player already on this roster is offered too,
 * marked with where he is, and choosing him moves him here (a swap when the slot is filled and
 * the swap is legal both ways) — one assignment per player, never a duplicate.
 */

import { useCallback, useState } from "react";

import { PlayerCombobox, type ComboOption } from "../../components/PlayerCombobox";
import { AvailabilityBadge, PositionTag } from "../../components/primitives";
import type { Availability } from "../../data/availability";
import { formatValue } from "../../data/format";
import { slotAccepts, type SavedLeague } from "../../data/leagueContract";
import type { PlayerUniverse } from "../../data/leagueUniverse";
import {
  EDIT_PROBLEM_TEXT,
  assignPlayer,
  destinations,
  findPlayer,
  movePlayer,
  occupant,
  removePlayer,
  slotLongName,
  type EditResult,
  type PositionOf,
  type SlotRef,
} from "../../data/roster";
import { Modal } from "../../components/Modal";
import { points } from "./shared";

export function SlotDialog({
  league,
  slot,
  universe,
  nameOf,
  positionOf,
  availabilityOf,
  onEdit,
  onClose,
  onSelect,
  onCompare,
  compareIds,
}: {
  readonly league: SavedLeague;
  readonly slot: SlotRef;
  readonly universe: PlayerUniverse;
  readonly nameOf: (playerId: string) => string;
  readonly positionOf: PositionOf;
  readonly availabilityOf: (playerId: string) => Availability | null;
  /** Commit a roster edit; resolves to an error message, or null when it was saved or kept. */
  readonly onEdit: (result: EditResult) => string | null;
  readonly onClose: () => void;
  readonly onSelect: (playerId: string) => void;
  readonly onCompare: (ids: readonly string[]) => void;
  readonly compareIds: readonly string[];
}): React.JSX.Element {
  const id = occupant(league.roster, slot);
  const [mode, setMode] = useState<"menu" | "pick" | "move">(id === null ? "pick" : "menu");
  const [error, setError] = useState<string | null>(null);
  const label = slotLongName(slot, league.slots);

  const act = (result: EditResult): void => {
    const message = onEdit(result);
    if (message === null) onClose();
    else setError(message);
  };

  const search = useCallback(
    (query: string): ComboOption[] =>
      universe
        .search(query, (player) => slotAccepts(slot.group, player.position) && player.id !== id, 8)
        .map((player) => {
          const where = findPlayer(league.roster, player.id);
          const median = player.weekly?.quantiles?.q50 ?? null;
          return {
            id: player.id,
            name: player.name,
            position: player.position,
            availability: availabilityOf(player.id) ?? undefined,
            meta:
              where !== null
                ? `On roster · ${slotLongName(where, league.slots)}`
                : `${player.team ?? "—"} · wk ${median === null ? "—" : points(median)}`,
            note:
              where !== null
                ? `already on your roster at ${slotLongName(where, league.slots)}; choosing him moves him here`
                : undefined,
          };
        }),
    [universe, slot.group, id, league.roster, league.slots, availabilityOf],
  );

  const pick = (playerId: string): void => {
    const where = findPlayer(league.roster, playerId);
    act(where === null ? assignPlayer(league.roster, slot, playerId, positionOf) : movePlayer(league.roster, where, slot, positionOf));
  };

  return (
    <Modal title={id === null ? `Add a player · ${label}` : `${label} · ${nameOf(id)}`} onClose={onClose}>
      {id !== null && (
        <div className="lg-slot-summary">
          {positionOf(id) !== null && <PositionTag position={positionOf(id) ?? "RB"} />}
          <span className="lg-slot-summary-name">{nameOf(id)}</span>
          <AvailabilityBadge availability={availabilityOf(id) ?? undefined} />
          {universe.get(id) === null && <span className="lg-unresolved">Not in this build</span>}
        </div>
      )}

      {mode === "menu" && id !== null && (
        <div className="lg-actions-grid">
          <button type="button" className="button" onClick={() => { setMode("pick"); }}>
            Replace
          </button>
          <button type="button" className="button" onClick={() => { setMode("move"); }}>
            Move or swap
          </button>
          <button type="button" className="button lg-danger" onClick={() => { act(removePlayer(league.roster, slot)); }}>
            Remove from roster
          </button>
          {universe.get(id) !== null && (
            <button
              type="button"
              className="button"
              onClick={() => {
                onClose();
                onSelect(id);
              }}
            >
              Open player card
            </button>
          )}
          {compareIds.length >= 2 && (
            <button
              type="button"
              className="button"
              onClick={() => {
                onClose();
                onCompare(compareIds);
              }}
            >
              {`Compare in Start/Sit (${String(compareIds.length)})`}
            </button>
          )}
        </div>
      )}

      {mode === "pick" && (
        <div className="lg-pick">
          <p className="lg-help" id={`slot-pick-help-${slot.group}-${String(slot.index)}`}>
            {id === null
              ? `Search for a player who can fill ${label}.`
              : `Search for a player to replace ${nameOf(id)} in ${label}. ${nameOf(id)} leaves your roster; to keep him, move him first.`}
          </p>
          <PlayerCombobox
            className="trade-picker lg-picker"
            label={`Find a player for ${label}`}
            placeholder="Name, team or position"
            search={search}
            onPick={pick}
            autoFocus
            describedBy={`slot-pick-help-${slot.group}-${String(slot.index)}`}
          />
          {id !== null && (
            <button type="button" className="button-link" onClick={() => { setMode("menu"); }}>
              Back
            </button>
          )}
        </div>
      )}

      {mode === "move" && id !== null && (
        <div className="lg-move">
          <p className="lg-help">{`Where should ${nameOf(id)} go? A filled slot is a swap.`}</p>
          <ul className="lg-destinations">
            {destinations(league.roster, league.slots, slot, positionOf).map((destination) => {
              const name = slotLongName(destination.slot, league.slots);
              const other = destination.other;
              const text =
                other === null ? `${name} — empty` : `${name} — swap with ${nameOf(other)}`;
              return (
                <li key={`${destination.slot.group}:${String(destination.slot.index)}`}>
                  <button
                    type="button"
                    className="button"
                    disabled={destination.problem !== null}
                    onClick={() => {
                      act(movePlayer(league.roster, slot, destination.slot, positionOf));
                    }}
                  >
                    {text}
                  </button>
                  {destination.problem !== null && (
                    <span className="lg-help">{EDIT_PROBLEM_TEXT[destination.problem]}</span>
                  )}
                </li>
              );
            })}
          </ul>
          <button type="button" className="button-link" onClick={() => { setMode("menu"); }}>
            Back
          </button>
        </div>
      )}

      {error !== null && (
        <p className="notice" data-severity="error" role="alert">
          {error}
        </p>
      )}
      {id !== null && universe.get(id)?.ros != null && (
        <p className="lg-help">
          {`Rest-of-season value ${formatValue(universe.get(id)?.ros?.ros_expected_vorp)} over replacement (published preset).`}
        </p>
      )}
    </Modal>
  );
}
