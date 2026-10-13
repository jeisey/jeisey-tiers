/**
 * Editing a saved roster: add, replace, remove, move and swap, and resizing it when a league's
 * settings change (ADR-106).
 *
 * Every function is pure: a roster in, a new roster (or the reason the edit is refused) out.
 * Three invariants hold after every successful edit, and `checkRoster` restates them:
 *
 * 1. one assignment per player in a league (the same player may be in another league);
 * 2. every group holds exactly its configured number of slots;
 * 3. a starter slot holds only a position it accepts. A player whose position this build
 *    cannot read (an unresolved id) may sit on the bench or IR, and stays wherever an earlier
 *    build put him rather than being moved for us.
 */

import type { Position } from "./contracts";
import {
  SLOT_GROUPS,
  SLOT_LABELS,
  isStarterGroup,
  slotAccepts,
  type Roster,
  type SlotCounts,
  type SlotGroup,
} from "./leagueContract";

export interface SlotRef {
  readonly group: SlotGroup;
  readonly index: number;
}

export type PositionOf = (playerId: string) => Position | null;

export function slotKey(slot: SlotRef): string {
  return `${slot.group}:${String(slot.index)}`;
}

export function sameSlot(a: SlotRef, b: SlotRef): boolean {
  return a.group === b.group && a.index === b.index;
}

/** `QB`, `RB2`, `FLEX`, `BN3`, `IR1`: a number only where the group has more than one slot. */
export function slotName(slot: SlotRef, counts: SlotCounts): string {
  const short = slot.group === "BN" ? "BN" : slot.group;
  return counts[slot.group] > 1 || slot.group === "BN" || slot.group === "IR"
    ? `${short}${String(slot.index + 1)}`
    : short;
}

/** `Bench 3`, `RB 2`, `QB`: the long form for a sentence or an accessible name. */
export function slotLongName(slot: SlotRef, counts: SlotCounts): string {
  const label = SLOT_LABELS[slot.group];
  return counts[slot.group] > 1 || slot.group === "BN" || slot.group === "IR"
    ? `${label} ${String(slot.index + 1)}`
    : label;
}

export function occupant(roster: Roster, slot: SlotRef): string | null {
  return roster[slot.group][slot.index] ?? null;
}

export function findPlayer(roster: Roster, playerId: string): SlotRef | null {
  for (const group of SLOT_GROUPS) {
    const index = roster[group].indexOf(playerId);
    if (index >= 0) return { group, index };
  }
  return null;
}

/** Every slot in lineup order: starters, then bench, then IR. */
export function allSlots(counts: SlotCounts): SlotRef[] {
  const out: SlotRef[] = [];
  for (const group of SLOT_GROUPS) {
    for (let index = 0; index < counts[group]; index += 1) out.push({ group, index });
  }
  return out;
}

function withSlot(roster: Roster, slot: SlotRef, value: string | null): Roster {
  const next = [...roster[slot.group]];
  next[slot.index] = value;
  return { ...roster, [slot.group]: next };
}

function exists(roster: Roster, slot: SlotRef): boolean {
  return slot.index >= 0 && slot.index < roster[slot.group].length;
}

export type EditProblem =
  | "no_slot"
  | "duplicate"
  | "ineligible"
  | "unknown_position"
  | "same_slot"
  | "empty_slot"
  | "swap_ineligible";

export const EDIT_PROBLEM_TEXT: Readonly<Record<EditProblem, string>> = {
  no_slot: "That slot does not exist in this league.",
  duplicate: "He is already on this roster. Move him instead.",
  ineligible: "His position cannot fill that slot.",
  unknown_position: "This build cannot confirm his position, so he can only go to the bench or IR.",
  same_slot: "He is already in that slot.",
  empty_slot: "There is nobody in that slot.",
  swap_ineligible: "The player in that slot cannot take this one's place.",
};

export type EditResult = { readonly roster: Roster } | { readonly problem: EditProblem };

function fits(group: SlotGroup, playerId: string, positionOf: PositionOf): EditProblem | null {
  if (!isStarterGroup(group)) return null;
  const position = positionOf(playerId);
  if (position === null) return "unknown_position";
  return slotAccepts(group, position) ? null : "ineligible";
}

/** Put a player who is not on the roster into a slot, replacing whoever is there. */
export function assignPlayer(
  roster: Roster,
  slot: SlotRef,
  playerId: string,
  positionOf: PositionOf,
): EditResult {
  if (!exists(roster, slot)) return { problem: "no_slot" };
  if (findPlayer(roster, playerId) !== null) return { problem: "duplicate" };
  const problem = fits(slot.group, playerId, positionOf);
  if (problem !== null) return { problem };
  return { roster: withSlot(roster, slot, playerId) };
}

export function removePlayer(roster: Roster, slot: SlotRef): EditResult {
  if (!exists(roster, slot)) return { problem: "no_slot" };
  if (occupant(roster, slot) === null) return { problem: "empty_slot" };
  return { roster: withSlot(roster, slot, null) };
}

/** Move a player to another slot; an occupied destination is a swap, legal both ways or not at all. */
export function movePlayer(
  roster: Roster,
  from: SlotRef,
  to: SlotRef,
  positionOf: PositionOf,
): EditResult {
  if (!exists(roster, from) || !exists(roster, to)) return { problem: "no_slot" };
  if (sameSlot(from, to)) return { problem: "same_slot" };
  const mover = occupant(roster, from);
  if (mover === null) return { problem: "empty_slot" };
  const problem = fits(to.group, mover, positionOf);
  if (problem !== null) return { problem };
  const other = occupant(roster, to);
  if (other !== null && fits(from.group, other, positionOf) !== null) return { problem: "swap_ineligible" };
  return { roster: withSlot(withSlot(roster, to, mover), from, other) };
}

export interface Destination {
  readonly slot: SlotRef;
  /** Who is there now, if anyone: the move is then a swap. */
  readonly other: string | null;
  readonly problem: EditProblem | null;
}

/** Every other slot, with whether the player in `from` may go there. */
export function destinations(
  roster: Roster,
  counts: SlotCounts,
  from: SlotRef,
  positionOf: PositionOf,
): Destination[] {
  return allSlots(counts)
    .filter((slot) => !sameSlot(slot, from))
    .map((slot) => {
      const result = movePlayer(roster, from, slot, positionOf);
      return { slot, other: occupant(roster, slot), problem: "problem" in result ? result.problem : null };
    });
}

/** Empty slots that accept this player, starters first. */
export function openSlotsFor(
  roster: Roster,
  counts: SlotCounts,
  playerId: string,
  positionOf: PositionOf,
): SlotRef[] {
  return allSlots(counts).filter(
    (slot) => occupant(roster, slot) === null && fits(slot.group, playerId, positionOf) === null,
  );
}

/**
 * A roster laid out for new counts. Each group keeps its players in order with the gaps closed;
 * whoever no longer fits is returned as overflow, for the reader to place or remove before the
 * settings can be saved. Nobody is dropped here.
 */
export function resizeRoster(
  roster: Roster,
  counts: SlotCounts,
): { readonly roster: Roster; readonly overflow: readonly { readonly group: SlotGroup; readonly id: string }[] } {
  const overflow: { group: SlotGroup; id: string }[] = [];
  const next: Partial<Record<SlotGroup, (string | null)[]>> = {};
  for (const group of SLOT_GROUPS) {
    const current = roster[group];
    const size = counts[group];
    if (current.length <= size) {
      // Growing, or the same: every slot stays where it was.
      next[group] = [...current, ...Array.from({ length: size - current.length }, () => null)];
      continue;
    }
    const players = current.filter((id): id is string => id !== null);
    next[group] = Array.from({ length: size }, (_, index) => players[index] ?? null);
    for (const id of players.slice(size)) overflow.push({ group, id });
  }
  return { roster: next as Roster, overflow };
}

/** Restate the invariants. Empty when the roster is consistent. */
export function checkRoster(roster: Roster, counts: SlotCounts, positionOf: PositionOf): string[] {
  const problems: string[] = [];
  const seen = new Set<string>();
  for (const group of SLOT_GROUPS) {
    if (roster[group].length !== counts[group]) problems.push(`${group} has the wrong number of slots`);
    roster[group].forEach((id, index) => {
      if (id === null) return;
      if (seen.has(id)) problems.push(`${id} is assigned twice`);
      seen.add(id);
      const position = positionOf(id);
      if (isStarterGroup(group) && position !== null && !slotAccepts(group, position)) {
        problems.push(`${id} (${position}) cannot fill ${group}${String(index + 1)}`);
      }
    });
  }
  return problems;
}
