/**
 * Win My Matchup's two lineups (ADR-110 §2): mine as saved, and the opponent's as the reader
 * enters it, each starter slot with its stated condition and, when it blocks, what fixes it.
 *
 * The opponent is entered through the shared player picker: a slot offers only players its
 * position accepts and never one on my roster; a player already in the opponent's lineup moves
 * (a swap when legal). Their bench and IR are optional and only keep known-owned players out of
 * YOLO. Nothing here optimises the opponent: the starters entered are the starters simulated.
 */

import { memo, useId, useState } from "react";

import { PlayerCombobox, type ComboOption } from "../../components/PlayerCombobox";
import { AvailabilityBadge, PositionTag } from "../../components/primitives";
import type { Availability } from "../../data/availability";
import { STARTER_GROUPS, rosterIds, slotAccepts, type SavedLeague, type StarterGroup } from "../../data/leagueContract";
import type { PlayerUniverse } from "../../data/leagueUniverse";
import type { MatchupSetup, Scenario, SlotReading } from "../../data/matchupSetup";
import { slotLongName, slotName, type SlotRef } from "../../data/roster";
import {
  OPPONENT_NAME_MAX,
  WMM_MAX_OTHERS,
  addOpponentOther,
  assignOpponent,
  clearOpponentSlot,
  confirmEmpty,
  countAsZero,
  opponentIds,
  removeOpponentPlayer,
  renameOpponent,
  setFinal,
  slotKeyOf,
  trimOpponent,
  type MatchupEntry,
} from "../../data/wmmContract";
import { Modal } from "./Modal";
import { kickoffLabel, opponentLabel, points } from "./shared";

export type EntryEdit = (change: (entry: MatchupEntry) => MatchupEntry) => void;

export interface LineupReaders {
  readonly universe: PlayerUniverse;
  readonly name: (id: string) => string;
  readonly teamOf: (id: string) => string | null;
  readonly availabilityOf: (id: string) => Availability | null;
  readonly onSelect: (id: string) => void;
}

const KIND_TEXT: Readonly<Record<SlotReading["kind"], string>> = {
  modelled: "",
  final: "Final",
  bye: "Bye · 0",
  zero: "Counted as 0",
  empty: "Left empty · 0",
  blocking: "Needs a decision",
};

/** Memoized, like `FinalsEditor`: a result arriving re-renders the view, not these unchanged rows. */
export const MatchupLineups = memo(function MatchupLineups({
  league,
  setup,
  entry,
  readers,
  writable,
  scenario,
  onEdit,
  onEditLineup,
}: {
  readonly league: SavedLeague;
  readonly setup: MatchupSetup;
  readonly entry: MatchupEntry | null;
  readonly readers: LineupReaders;
  readonly writable: boolean;
  readonly scenario: Scenario;
  readonly onEdit: EntryEdit;
  readonly onEditLineup: () => void;
}): React.JSX.Element {
  const [dialog, setDialog] = useState<SlotRef | "others" | null>(null);
  const counts = league.slots;
  const opponentName = entry?.opponent.name ?? "";
  const nameId = useId();
  return (
    <div className="wmm-lineups">
      <section className="wmm-side" aria-labelledby={`${nameId}-mine`}>
        <div className="wmm-side-head">
          <h4 id={`${nameId}-mine`} className="wmm-side-title">
            Your starters
          </h4>
          <button type="button" className="button-link" onClick={onEditLineup}>
            Edit your lineup
          </button>
        </div>
        <ul className="lg-slots">
          {setup.mine.map((line) => (
            <MatchupSlot
              key={`${line.slot.group}:${String(line.slot.index)}`}
              line={line}
              counts={counts}
              readers={readers}
              writable={writable}
              scenario={scenario}
              onEdit={onEdit}
              onOpen={null}
              onEditLineup={onEditLineup}
            />
          ))}
        </ul>
      </section>

      <section className="wmm-side" aria-labelledby={`${nameId}-theirs`}>
        <div className="wmm-side-head">
          <h4 id={`${nameId}-theirs`} className="wmm-side-title">
            Opponent&rsquo;s starters
          </h4>
          <label className="wmm-name">
            <span className="visually-hidden">Opponent&rsquo;s team name</span>
            <input
              key={opponentName}
              type="text"
              className="wmm-name-input"
              maxLength={OPPONENT_NAME_MAX}
              placeholder="Their name (optional)"
              defaultValue={opponentName}
              disabled={!writable}
              onBlur={(event) => {
                const value = event.currentTarget.value;
                onEdit((current) => renameOpponent(current, value));
              }}
              onKeyDown={(event) => {
                if (event.key === "Enter") event.currentTarget.blur();
              }}
            />
          </label>
        </div>
        {setup.overflow.length > 0 && (
          <p className="notice" data-severity="warning" role="status">
            {`${setup.overflow.map((item) => `${readers.name(item.id)} (${item.group})`).join(", ")} no longer fit${setup.overflow.length === 1 ? "s" : ""} this league's starting slots. `}
            <button type="button" className="button-link" disabled={!writable} onClick={() => { onEdit((current) => trimOpponent(current, counts)); }}>
              Remove {setup.overflow.length === 1 ? "him" : "them"}
            </button>
          </p>
        )}
        <ul className="lg-slots">
          {setup.theirs.map((line) => (
            <MatchupSlot
              key={`${line.slot.group}:${String(line.slot.index)}`}
              line={line}
              counts={counts}
              readers={readers}
              writable={writable}
              scenario={scenario}
              onEdit={onEdit}
              onOpen={(slot) => {
                setDialog(slot);
              }}
              onEditLineup={onEditLineup}
            />
          ))}
        </ul>
        <OpponentOthers entry={entry} readers={readers} writable={writable} onEdit={onEdit} onAdd={() => { setDialog("others"); }} />
      </section>

      {dialog !== null && (
        <OpponentDialog
          league={league}
          entry={entry}
          target={dialog}
          readers={readers}
          onEdit={onEdit}
          onClose={() => {
            setDialog(null);
          }}
        />
      )}
    </div>
  );
});

function MatchupSlot({
  line,
  counts,
  readers,
  writable,
  scenario,
  onEdit,
  onOpen,
  onEditLineup,
}: {
  readonly line: SlotReading;
  readonly counts: SavedLeague["slots"];
  readonly readers: LineupReaders;
  readonly writable: boolean;
  readonly scenario: Scenario;
  readonly onEdit: EntryEdit;
  /** Opens the opponent's slot editor; null on my side, which is edited in the lineup view. */
  readonly onOpen: ((slot: SlotRef) => void) | null;
  readonly onEditLineup: () => void;
}): React.JSX.Element {
  const { slot, id } = line;
  const short = slotName(slot, counts);
  const long = slotLongName(slot, counts);
  const key = slotKeyOf(slot.group as StarterGroup, slot.index);
  const side = line.side;
  const record = line.week?.record ?? null;
  const quantiles = line.kind === "modelled" ? (record?.quantiles ?? null) : null;
  const player = id === null ? null : readers.universe.get(id);
  const sideWord = side === "mine" ? "your" : "the opponent's";
  return (
    <li className="lg-slot wmm-slot" data-kind={line.kind} data-side={side}>
      <span className="lg-slot-label" aria-hidden="true">{short}</span>
      <span className="lg-slot-main">
        <span className="lg-slot-player">
          <span className="visually-hidden">{`${side === "mine" ? "Your" : "Opponent's"} ${long}: `}</span>
          {id === null ? (
            <span className="lg-muted">Empty</span>
          ) : (
            <>
              {player !== null && <PositionTag position={player.position} />}
              {player === null ? (
                <span className="lg-player-plain">{readers.name(id)}</span>
              ) : (
                <button type="button" className="player-name" onClick={() => { readers.onSelect(id); }}>
                  {readers.name(id)}
                </button>
              )}
              <span className="lg-team">{readers.teamOf(id) ?? ""}</span>
              <AvailabilityBadge availability={readers.availabilityOf(id) ?? undefined} />
            </>
          )}
        </span>
        <span className="lg-slot-week">
          {record !== null && (
            <span className="lg-game">
              {opponentLabel(record)}
              {record.game !== null && ` · ${kickoffLabel(record.game.kickoff_utc)}`}
            </span>
          )}
          {quantiles !== null && (
            <span className="lg-quantiles" title="Floor (P10) · median (P50) · ceiling (P90), points given that he plays">
              <span className="visually-hidden">Floor, median, ceiling: </span>
              {points(quantiles.q10)}
              <span aria-hidden="true"> · </span>
              <strong>{points(quantiles.q50)}</strong>
              <span aria-hidden="true"> · </span>
              {points(quantiles.q90)}
            </span>
          )}
          {line.kind !== "modelled" && <span className="wmm-kind" data-kind={line.kind}>{line.kind === "final" ? `Final ${points(line.fixed, 2)}` : KIND_TEXT[line.kind]}</span>}
        </span>
        {line.note !== null && (
          <span className="lg-slot-status" data-kind={line.kind === "blocking" ? "sidelined" : line.locked ? "locked" : "note"}>
            {line.note}
          </span>
        )}
      </span>
      <span className="lg-slot-actions">
        {onOpen !== null && (
          <button
            type="button"
            className="button lg-edit"
            disabled={!writable}
            aria-label={id === null ? `Set the opponent's ${long}` : `Change the opponent's ${long}: ${readers.name(id)}`}
            onClick={() => {
              onOpen(slot);
            }}
          >
            {id === null ? "Set" : "Change"}
          </button>
        )}
        {line.kind === "blocking" && line.fix === "fill" && (
          <button type="button" className="button" disabled={!writable} aria-label={`Leave ${sideWord} ${long} empty: it counts 0`} onClick={() => { onEdit((current) => confirmEmpty(current, side, key, true)); }}>
            Leave empty (0)
          </button>
        )}
        {line.kind === "empty" && (
          <button type="button" className="button" disabled={!writable} aria-label={`Stop leaving ${sideWord} ${long} empty`} onClick={() => { onEdit((current) => confirmEmpty(current, side, key, false)); }}>
            Undo
          </button>
        )}
        {line.kind === "blocking" && line.fix === "count_zero" && id !== null && (
          <button type="button" className="button" disabled={!writable} aria-label={`Count ${readers.name(id)} as 0`} onClick={() => { onEdit((current) => countAsZero(current, id, true)); }}>
            Count as 0
          </button>
        )}
        {line.kind === "zero" && id !== null && (
          <button type="button" className="button" disabled={!writable} aria-label={`Stop counting ${readers.name(id)} as 0`} onClick={() => { onEdit((current) => countAsZero(current, id, false)); }}>
            Undo
          </button>
        )}
        {line.kind === "blocking" && line.fix === "resolve_overlap" && id !== null && (
          <button type="button" className="button" disabled={!writable} onClick={() => { onEdit((current) => removeOpponentPlayer(current, id)); }}>
            Remove from opponent
          </button>
        )}
        {side === "mine" && line.kind === "blocking" && (line.fix === "replace" || line.fix === "fill") && (
          <button type="button" className="button" onClick={onEditLineup}>
            Edit lineup
          </button>
        )}
        {line.kind === "blocking" && line.fix === "final" && scenario === "pregame" && (
          <span className="lg-help">Switch to “With final scores”.</span>
        )}
      </span>
    </li>
  );
}

function OpponentOthers({
  entry,
  readers,
  writable,
  onEdit,
  onAdd,
}: {
  readonly entry: MatchupEntry | null;
  readonly readers: LineupReaders;
  readonly writable: boolean;
  readonly onEdit: EntryEdit;
  readonly onAdd: () => void;
}): React.JSX.Element {
  const others = entry?.opponent.others ?? [];
  return (
    <details className="wmm-others">
      <summary>{`Their bench and IR (optional) · ${String(others.length)}`}</summary>
      <p className="lg-help">Only used to keep players you know they own out of YOLO pickups. Not simulated.</p>
      {others.length > 0 && (
        <ul className="wmm-other-list">
          {others.map((id) => (
            <li key={id}>
              <span>{readers.name(id)}</span>
              <button type="button" className="button-link" disabled={!writable} aria-label={`Remove ${readers.name(id)} from the opponent's bench and IR`} onClick={() => { onEdit((current) => removeOpponentPlayer(current, id)); }}>
                Remove
              </button>
            </li>
          ))}
        </ul>
      )}
      <button type="button" className="button" disabled={!writable || others.length >= WMM_MAX_OTHERS} onClick={onAdd}>
        Add a bench or IR player
      </button>
    </details>
  );
}

function OpponentDialog({
  league,
  entry,
  target,
  readers,
  onEdit,
  onClose,
}: {
  readonly league: SavedLeague;
  readonly entry: MatchupEntry | null;
  readonly target: SlotRef | "others";
  readonly readers: LineupReaders;
  readonly onEdit: EntryEdit;
  readonly onClose: () => void;
}): React.JSX.Element {
  const mine = new Set(rosterIds(league.roster));
  const theirs = new Set(entry === null ? [] : opponentIds(entry));
  const slot = target === "others" ? null : target;
  const group = slot === null ? null : (slot.group as StarterGroup);
  const occupant = slot === null || group === null || entry === null ? null : (entry.opponent.starters[group][slot.index] ?? null);
  const label = slot === null ? "their bench and IR" : `the opponent's ${slotLongName(slot, league.slots)}`;
  const fits = (into: StarterGroup, id: string): boolean => slotAccepts(into, readers.universe.get(id)?.position ?? null);
  const where = (id: string): string | null => {
    if (entry === null) return null;
    for (const candidate of STARTER_GROUPS) {
      const index = entry.opponent.starters[candidate].indexOf(id);
      if (index >= 0) return slotLongName({ group: candidate, index }, league.slots);
    }
    return entry.opponent.others.includes(id) ? "their bench" : null;
  };
  const search = (query: string): ComboOption[] =>
      readers.universe
        .search(
          query,
          (player) =>
            !mine.has(player.id) &&
            player.id !== occupant &&
            (group === null ? !theirs.has(player.id) : slotAccepts(group, player.position)),
          8,
        )
        .map((player) => {
          const at = where(player.id);
          const median = player.weekly?.quantiles?.q50 ?? null;
          return {
            id: player.id,
            name: player.name,
            position: player.position,
            availability: readers.availabilityOf(player.id) ?? undefined,
            meta: at !== null ? `Theirs · ${at}` : `${player.team ?? "—"} · wk ${median === null ? "—" : points(median)}`,
            note: at !== null ? `already entered for the opponent at ${at}; choosing him moves him here` : undefined,
          };
        });
  const pick = (id: string): void => {
    if (slot === null || group === null) onEdit((current) => addOpponentOther(current, id));
    else onEdit((current) => assignOpponent(current, league.slots, { group, index: slot.index }, id, fits));
    onClose();
  };
  return (
    <Modal title={slot === null ? "Add to their bench or IR" : `Opponent · ${slotLongName(slot, league.slots)}`} onClose={onClose}>
      <p className="lg-help" id="wmm-pick-help">
        {slot === null
          ? "Search for a player they roster but are not starting. Players on your roster are not offered: a player can be on only one team."
          : `Search for the player they start at ${slotLongName(slot, league.slots)}. Only positions this slot accepts are offered, and never a player on your roster.`}
      </p>
      <PlayerCombobox
        className="trade-picker lg-picker"
        label={`Find a player for ${label}`}
        placeholder="Name, team or position"
        search={search}
        onPick={pick}
        autoFocus
        describedBy="wmm-pick-help"
      />
      {slot !== null && occupant !== null && (
        <div className="lg-actions-grid">
          <button
            type="button"
            className="button lg-danger"
            onClick={() => {
              onEdit((current) => clearOpponentSlot(current, league.slots, { group: slot.group as StarterGroup, index: slot.index }));
              onClose();
            }}
          >
            {`Remove ${readers.name(occupant)}`}
          </button>
        </div>
      )}
    </Modal>
  );
}

/** The kicked-off starters on both sides, with a final score each when the reader has one. */
export const FinalsEditor = memo(function FinalsEditor({
  setup,
  entry,
  readers,
  writable,
  onEdit,
}: {
  readonly setup: MatchupSetup;
  readonly entry: MatchupEntry | null;
  readonly readers: LineupReaders;
  readonly writable: boolean;
  readonly onEdit: EntryEdit;
}): React.JSX.Element | null {
  if (setup.lockedStarters.length === 0) return null;
  return (
    <div className="wmm-finals">
      <p className="lg-help">
        These starters&rsquo; games have kicked off. This is not live scoring: an in-progress game is never updated
        from its current score. Once a game is over you may enter the final fantasy points; the{" "}
        <em>With final scores</em> scenario then counts that score instead of his projection, exactly once.
      </p>
      <ul className="wmm-final-list">
        {setup.lockedStarters.map((line) => {
          const id = line.id;
          if (id === null) return null;
          const saved = entry?.finals[id];
          return (
            <li key={`${line.side}:${id}`}>
              <span className="wmm-final-name">{`${readers.name(id)} (${line.side === "mine" ? "yours" : "theirs"})`}</span>
              <form
                className="wmm-final-form"
                onSubmit={(event) => {
                  event.preventDefault();
                  const input = event.currentTarget.elements.namedItem("points");
                  if (!(input instanceof HTMLInputElement)) return;
                  const value = Number.parseFloat(input.value);
                  if (Number.isFinite(value)) onEdit((current) => setFinal(current, id, value));
                }}
              >
                <label>
                  <span className="visually-hidden">{`Final fantasy points for ${readers.name(id)}`}</span>
                  <input
                    key={String(saved ?? "")}
                    name="points"
                    type="number"
                    inputMode="decimal"
                    step="0.01"
                    min={-100}
                    max={100}
                    defaultValue={saved ?? ""}
                    disabled={!writable}
                    className="wmm-final-input"
                  />
                </label>
                <button type="submit" className="button" disabled={!writable} aria-label={`${saved === undefined ? "Save final" : "Update final"} for ${readers.name(id)}`}>
                  {saved === undefined ? "Save final" : "Update"}
                </button>
                {saved !== undefined && (
                  <button type="button" className="button-link" disabled={!writable} aria-label={`Clear the final for ${readers.name(id)}`} onClick={() => { onEdit((current) => setFinal(current, id, null)); }}>
                    Clear
                  </button>
                )}
              </form>
            </li>
          );
        })}
      </ul>
    </div>
  );
});
