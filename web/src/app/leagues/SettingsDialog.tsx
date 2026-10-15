/**
 * Create, edit or delete a saved league (ADR-106).
 *
 * The scoring and size choices are the presets this build publishes — Standard, Half PPR and
 * PPR at 10, 12 and 14 teams — and nothing is mapped onto another: an unpublished choice is
 * disabled, not substituted. Starter, bench and IR counts move within `SLOT_BOUNDS`. Reducing a
 * count never drops a player: whoever no longer fits is listed, and the league cannot be saved
 * until each of them is placed elsewhere or removed by the reader.
 */

import { useId, useState } from "react";

import { PositionTag } from "../../components/primitives";
import type { Position } from "../../data/contracts";
import {
  LEAGUE_NAME_MAX,
  PUBLISHED_STARTERS,
  SLOT_BOUNDS,
  SLOT_GROUPS,
  SLOT_LABELS,
  cleanLeagueName,
  emptyRoster,
  slotAccepts,
  startersDiffer,
  DEFAULT_SLOTS,
  type Roster,
  type SavedLeague,
  type SlotCounts,
  type SlotGroup,
} from "../../data/leagueContract";
import type { LeagueStore } from "../../data/leagueStore";
import { addLeague, deleteLeague, updateLeague } from "../../data/leagueOps";
import { resizeRoster } from "../../data/roster";
import {
  SCORING_LABELS,
  SCORING_VALUES,
  TEAM_COUNTS,
  type ScoringValue,
  type TeamCount,
} from "../../data/state";
import { Modal } from "../../components/Modal";

interface Draft {
  readonly name: string;
  readonly scoring: ScoringValue;
  readonly teams: TeamCount;
  readonly season: number;
  readonly slots: SlotCounts;
  readonly roster: Roster;
  /** Players a reduced count displaced, waiting for the reader to place or remove them. */
  readonly overflow: readonly string[];
}

const COUNT_HELP: Readonly<Record<SlotGroup, string>> = {
  QB: "Quarterbacks",
  RB: "Running backs",
  WR: "Wide receivers",
  TE: "Tight ends",
  FLEX: "FLEX: a running back, receiver or tight end",
  BN: "Bench",
  IR: "Injured reserve",
};

export function SettingsDialog({
  store,
  league,
  defaults,
  availableScoring,
  availableTeams,
  nameOf,
  positionOf,
  onClose,
  leagueCount,
}: {
  readonly store: LeagueStore;
  /** The league being edited, or null to create one. */
  readonly league: SavedLeague | null;
  readonly defaults: { readonly scoring: ScoringValue; readonly teams: TeamCount; readonly season: number };
  readonly availableScoring: ReadonlySet<ScoringValue>;
  readonly availableTeams: ReadonlySet<TeamCount>;
  readonly nameOf: (playerId: string) => string;
  readonly positionOf: (playerId: string) => Position | null;
  readonly onClose: () => void;
  readonly leagueCount: number;
}): React.JSX.Element {
  const baseId = useId();
  const [draft, setDraft] = useState<Draft>(() =>
    league === null
      ? {
          name: "",
          scoring: availableScoring.has(defaults.scoring) ? defaults.scoring : (SCORING_VALUES.find((value) => availableScoring.has(value)) ?? defaults.scoring),
          teams: availableTeams.has(defaults.teams) ? defaults.teams : (TEAM_COUNTS.find((value) => availableTeams.has(value)) ?? defaults.teams),
          season: defaults.season,
          slots: DEFAULT_SLOTS,
          roster: emptyRoster(DEFAULT_SLOTS),
          overflow: [],
        }
      : {
          name: league.name,
          scoring: league.scoring,
          teams: league.teams,
          season: league.season,
          slots: league.slots,
          roster: league.roster,
          overflow: [],
        },
  );
  const [error, setError] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);

  const setCount = (group: SlotGroup, value: number): void => {
    const bounded = Math.max(SLOT_BOUNDS[group].min, Math.min(SLOT_BOUNDS[group].max, value));
    setDraft((current) => {
      const slots = { ...current.slots, [group]: bounded };
      const resized = resizeRoster(current.roster, slots);
      return {
        ...current,
        slots,
        roster: resized.roster,
        overflow: [...current.overflow, ...resized.overflow.map((entry) => entry.id)],
      };
    });
  };

  const place = (playerId: string, group: SlotGroup): void => {
    setDraft((current) => {
      const index = current.roster[group].indexOf(null);
      if (index < 0) return current;
      const slots = [...current.roster[group]];
      slots[index] = playerId;
      return {
        ...current,
        roster: { ...current.roster, [group]: slots },
        overflow: current.overflow.filter((id) => id !== playerId),
      };
    });
  };
  const drop = (playerId: string): void => {
    setDraft((current) => ({ ...current, overflow: current.overflow.filter((id) => id !== playerId) }));
  };

  const scoringOk = availableScoring.has(draft.scoring);
  const teamsOk = availableTeams.has(draft.teams);
  const seasonOk = Number.isInteger(draft.season) && draft.season >= 2000 && draft.season <= 2100;
  const canSave = draft.overflow.length === 0 && scoringOk && teamsOk && seasonOk;

  const save = (): void => {
    if (!canSave) return;
    const name = cleanLeagueName(draft.name, league?.name ?? `League ${String(leagueCount + 1)}`);
    const result =
      league === null
        ? addLeague(store, {
            name,
            scoring: draft.scoring,
            teams: draft.teams,
            season: draft.season,
            slots: draft.slots,
          })
        : updateLeague(store, league, (current) => ({
            ...current,
            name,
            scoring: draft.scoring,
            teams: draft.teams,
            season: draft.season,
            slots: draft.slots,
            roster: draft.roster,
          }));
    if (result.ok) onClose();
    else setError(result.message);
  };

  const remove = (): void => {
    if (league === null) return;
    const result = deleteLeague(store, league);
    if (result.ok) onClose();
    else setError(result.message);
  };

  const differs = startersDiffer(draft.slots);
  return (
    <Modal title={league === null ? "New league" : `Edit ${league.name}`} onClose={onClose} wide>
      <form
        className="lg-settings"
        onSubmit={(event) => {
          event.preventDefault();
          save();
        }}
      >
        <div className="lg-field">
          <label className="control-label" htmlFor={`${baseId}-name`}>
            League name
          </label>
          <input
            id={`${baseId}-name`}
            type="text"
            className="lg-input"
            maxLength={LEAGUE_NAME_MAX}
            data-autofocus
            value={draft.name}
            placeholder={league?.name ?? `League ${String(leagueCount + 1)}`}
            autoComplete="off"
            onChange={(event) => {
              const name = event.target.value;
              setDraft((current) => ({ ...current, name }));
            }}
          />
        </div>

        <fieldset className="lg-field lg-choice">
          <legend className="control-label">Scoring</legend>
          {SCORING_VALUES.map((value) => (
            <label key={value} className="lg-radio" data-disabled={!availableScoring.has(value) || undefined}>
              <input
                type="radio"
                name={`${baseId}-scoring`}
                value={value}
                checked={draft.scoring === value}
                disabled={!availableScoring.has(value)}
                onChange={() => {
                  setDraft((current) => ({ ...current, scoring: value }));
                }}
              />
              {SCORING_LABELS[value]}
            </label>
          ))}
        </fieldset>

        <fieldset className="lg-field lg-choice">
          <legend className="control-label">Teams in the league</legend>
          {TEAM_COUNTS.map((value) => (
            <label key={value} className="lg-radio" data-disabled={!availableTeams.has(value) || undefined}>
              <input
                type="radio"
                name={`${baseId}-teams`}
                value={value}
                checked={draft.teams === value}
                disabled={!availableTeams.has(value)}
                onChange={() => {
                  setDraft((current) => ({ ...current, teams: value }));
                }}
              />
              {`${String(value)} teams`}
            </label>
          ))}
          <p className="lg-help">
            League size, not rosters to enter: you enter only your own team. Other scoring rules,
            sizes and superflex are not published, so they are not offered.
          </p>
        </fieldset>

        <div className="lg-field">
          <label className="control-label" htmlFor={`${baseId}-season`}>
            Season
          </label>
          <input
            id={`${baseId}-season`}
            type="number"
            className="lg-input lg-input-short"
            min={2000}
            max={2100}
            value={draft.season}
            onChange={(event) => {
              const season = Number.parseInt(event.target.value, 10);
              setDraft((current) => ({ ...current, season: Number.isNaN(season) ? current.season : season }));
            }}
          />
        </div>

        <fieldset className="lg-field">
          <legend className="control-label">Roster slots</legend>
          <ul className="lg-counts">
            {SLOT_GROUPS.map((group) => (
              <li key={group} className="lg-count">
                <span className="lg-count-name" id={`${baseId}-${group}`}>
                  {SLOT_LABELS[group]}
                  <span className="visually-hidden">{`: ${COUNT_HELP[group]}`}</span>
                </span>
                <span className="lg-stepper" role="group" aria-labelledby={`${baseId}-${group}`}>
                  <button
                    type="button"
                    aria-label={`Fewer ${SLOT_LABELS[group]} slots`}
                    disabled={draft.slots[group] <= SLOT_BOUNDS[group].min}
                    onClick={() => {
                      setCount(group, draft.slots[group] - 1);
                    }}
                  >
                    −
                  </button>
                  <output aria-live="polite" aria-label={`${SLOT_LABELS[group]} slots`}>
                    {draft.slots[group]}
                  </output>
                  <button
                    type="button"
                    aria-label={`More ${SLOT_LABELS[group]} slots`}
                    disabled={draft.slots[group] >= SLOT_BOUNDS[group].max}
                    onClick={() => {
                      setCount(group, draft.slots[group] + 1);
                    }}
                  >
                    +
                  </button>
                </span>
                <span className="lg-count-bounds">{`${String(SLOT_BOUNDS[group].min)}–${String(SLOT_BOUNDS[group].max)}`}</span>
              </li>
            ))}
            {(["DST", "K"] as const).map((group) => (
              <li key={group} className="lg-count" data-unsupported="true">
                <span className="lg-count-name">{group}</span>
                <span className="lg-unsupported">Not supported</span>
              </li>
            ))}
          </ul>
          <p className="lg-help">
            FLEX takes a running back, receiver or tight end. Team defense and kickers are not
            modelled by this site.
            {differs &&
              ` The published boards assume ${String(PUBLISHED_STARTERS.QB)} QB, ${String(PUBLISHED_STARTERS.RB)} RB, ${String(PUBLISHED_STARTERS.WR)} WR, ${String(PUBLISHED_STARTERS.TE)} TE and ${String(PUBLISHED_STARTERS.FLEX)} FLEX; your counts govern your lineup and these tools, and benchmarks built for the published lineup are labelled as such.`}
          </p>
        </fieldset>

        {draft.overflow.length > 0 && (
          <div className="notice lg-overflow" data-severity="warning" role="alert">
            <strong>{`${String(draft.overflow.length)} player${draft.overflow.length === 1 ? " no longer fits" : "s no longer fit"}.`}</strong>{" "}
            Place or remove each before saving.
            <ul className="lg-overflow-list">
              {draft.overflow.map((id) => {
                const position = positionOf(id);
                const targets = SLOT_GROUPS.filter(
                  (group) =>
                    draft.roster[group].includes(null) &&
                    (group === "BN" || group === "IR" || (position !== null && slotAccepts(group, position))),
                );
                return (
                  <li key={id}>
                    {position !== null && <PositionTag position={position} />}
                    <span className="lg-overflow-name">{nameOf(id)}</span>
                    {targets.map((group) => (
                      <button
                        key={group}
                        type="button"
                        className="button"
                        onClick={() => {
                          place(id, group);
                        }}
                      >
                        {`To ${SLOT_LABELS[group]}`}
                      </button>
                    ))}
                    <button
                      type="button"
                      className="button"
                      onClick={() => {
                        drop(id);
                      }}
                    >
                      Remove from roster
                    </button>
                  </li>
                );
              })}
            </ul>
          </div>
        )}

        {error !== null && (
          <p className="notice" data-severity="error" role="alert">
            {error}
          </p>
        )}

        <div className="lg-dialog-actions">
          <button type="submit" className="button chamfer" data-variant="primary" disabled={!canSave}>
            {league === null ? "Create league" : "Save changes"}
          </button>
          <button type="button" className="button" onClick={onClose}>
            Cancel
          </button>
          {league !== null &&
            (confirmDelete ? (
              <span className="lg-confirm" role="group" aria-label="Confirm delete">
                <span>{`Delete “${league.name}” and its roster from this browser?`}</span>
                <button type="button" className="button lg-danger" onClick={remove}>
                  Delete league
                </button>
                <button
                  type="button"
                  className="button"
                  onClick={() => {
                    setConfirmDelete(false);
                  }}
                >
                  Keep it
                </button>
              </span>
            ) : (
              <button
                type="button"
                className="button lg-danger"
                onClick={() => {
                  setConfirmDelete(true);
                }}
              >
                Delete…
              </button>
            ))}
        </div>
      </form>
    </Modal>
  );
}
