/**
 * Start/Sit: who to put in the slot, and how sure to be (ADR-096).
 *
 * Every fantasy site answers this with two projections and a winner. This tab answers it the
 * way a manager actually faces it — with a slot, two to four candidates, and a matchup:
 *
 * 1. **The duel deck** — the candidates side by side, each with his next-game median, his
 *    P10–P90 range, his game (opponent, kickoff, the sportsbook's implied team total), the
 *    official injury designation with how often it has meant a missed game, and his chance of
 *    a *startable* week in the reader's league.
 * 2. **The verdict** — who to start, with the head-to-head probability the sealed-season
 *    evaluation calibrated ("when this says 70%, it happened 73%"), and the reader's matchup
 *    posture: because a trailing manager needs a ceiling and a leading one a floor, the pick
 *    is the player most likely to *win the week* at the reader's margin, and the tab prints
 *    the margin at which that answer flips.
 * 3. **The picture** — each week as a distribution on one axis, against the startable line.
 * 4. **Why** — the median's additive driver account, differenced between the two leaders, so
 *    "why him" is a list of reasons in points rather than an assertion.
 * 5. **The week board** — every projection for the reader's filters, the place players are
 *    added from.
 *
 * Every per-player number is a published field; every probability is computed from published
 * quantiles by `data/startsit.ts`, the twin of the Python the evaluation scored.
 */

import { useMemo, useState } from "react";

import { OutcomeRidges, slotLetter } from "../charts/OutcomeRidges";
import { Notice, PositionTag, SectionHead, Segmented } from "../components/primitives";
import type { RosWeeklyMetadata, WeeklyProjectionRecord } from "../data/contracts";
import { WEEKLY_DRIVER_FAMILIES } from "../data/contracts";
import {
  flipSentence,
  injuryReading,
  readDuel,
  selectWeekBoard,
  toggleDuel,
  type Contender,
  type DuelReading,
  type WeekBoardOrder,
  type WeekBoardRow,
} from "../data/duel";
import { EM_DASH, formatEastern, formatSigned, formatValue } from "../data/format";
import type { InSeasonBundle } from "../data/ros";
import { MARGIN_BOUND, MAX_DUEL, SCORING_LABELS, type AppState } from "../data/state";

const POSTURES: readonly { readonly value: number; readonly label: string; readonly long: string }[] = [
  { value: -20, label: "Down 20", long: "Projected to lose by 20 without this slot" },
  { value: -10, label: "Down 10", long: "Projected to lose by 10 without this slot" },
  { value: 0, label: "Even", long: "An even matchup without this slot" },
  { value: 10, label: "Up 10", long: "Projected to win by 10 without this slot" },
  { value: 20, label: "Up 20", long: "Projected to win by 20 without this slot" },
];

const ORDERS: readonly { readonly value: WeekBoardOrder; readonly label: string; readonly description: string }[] = [
  { value: "startable", label: "Startable", description: "Chance of a startable week in your league" },
  { value: "median", label: "Median", description: "Median projected points" },
  { value: "ceiling", label: "Ceiling", description: "90th percentile projected points" },
  { value: "floor", label: "Floor", description: "10th percentile projected points" },
];

const BOARD_PAGE = 40;

function percent(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return EM_DASH;
  return `${(value * 100).toFixed(digits)}%`;
}

function marginLabel(margin: number): string {
  if (margin === 0) return "Even";
  return margin < 0 ? `Down ${String(-margin)}` : `Up ${String(margin)}`;
}

/** "54.1% vs 52.8% chance to win the week", one decimal because the gap is often small. */
function winPair(verdict: NonNullable<DuelReading["verdict"]>): string {
  return `${percent(verdict.pick.winProbability, 1)} vs ${percent(verdict.runnerUp.winProbability, 1)} chance to win the week`;
}

function gameLine(record: WeeklyProjectionRecord): string {
  const game = record.game;
  if (game === null) return `Bye in week ${String(record.target_week)}`;
  const venue = game.neutral_site ? "vs" : game.home_away === "home" ? "vs" : "@";
  return `${venue} ${game.opponent}`;
}

function lastName(name: string): string {
  const parts = name.split(" ");
  const tail = parts[parts.length - 1] ?? name;
  return /^(jr\.?|sr\.?|ii|iii|iv|v)$/i.test(tail) && parts.length > 2 ? (parts[parts.length - 2] ?? tail) : tail;
}

/** The Halo-style segmented meter: twenty cells, the value in words beside it. */
function ShieldMeter({
  value,
  label,
  tone,
}: {
  readonly value: number | null;
  readonly label: string;
  readonly tone?: "lead" | "trail" | undefined;
}): React.JSX.Element {
  const filled = value === null ? 0 : Math.round(Math.max(0, Math.min(1, value)) * 20);
  return (
    <div className="shield" data-tone={tone}>
      <span className="shield-label">{label}</span>
      <span className="shield-cells" aria-hidden="true">
        {Array.from({ length: 20 }, (_, index) => (
          <i key={index} data-on={index < filled ? "true" : undefined} />
        ))}
      </span>
      <span className="shield-value">{percent(value, 1)}</span>
    </div>
  );
}

export function StartSitView({
  bundle,
  state,
  onChange,
  onSelect,
  now,
}: {
  readonly bundle: InSeasonBundle;
  readonly state: AppState;
  readonly onChange: (patch: Partial<AppState>) => void;
  readonly onSelect: (playerId: string) => void;
  readonly now?: Date | undefined;
}): React.JSX.Element {
  const weekly = bundle.metadata.weekly ?? null;
  const [order, setOrder] = useState<WeekBoardOrder | null>(null);
  const [showAll, setShowAll] = useState(false);
  const effectiveOrder: WeekBoardOrder = order ?? (state.position === "all" ? "startable" : "median");

  const duel = useMemo(() => readDuel(bundle, state, now), [bundle, state, now]);
  const board = useMemo(
    () => selectWeekBoard(bundle, state, effectiveOrder, now),
    [bundle, state, effectiveOrder, now],
  );

  const toggle = (playerId: string): void => {
    onChange({ duel: toggleDuel(state.duel, playerId) });
  };

  if (!bundle.hasWeekly || weekly === null) {
    return (
      <section className="section startsit" aria-labelledby="startsit-heading">
        <SectionHead index="01" id="startsit-heading" title="Start/Sit" />
        <Notice title="No weekly projections were published with this build.">
          The rest-of-season board, the Opportunity Board and Pick of the Week are unaffected.
          Weekly projections need the promoted start/sit model and a scheduled game in the week
          after the cutoff; the Data view lists this build&rsquo;s warnings.
        </Notice>
      </section>
    );
  }

  const week = weekly.target_week;
  const scoringLabel = SCORING_LABELS[state.scoring];
  const kickedOff = weekly.kicked_off > 0 && weekly.upcoming === 0;

  return (
    <section className="section startsit" aria-labelledby="startsit-heading">
      <SectionHead
        index="01"
        id="startsit-heading"
        title={`Start/Sit — week ${String(week)}`}
        note={`Up to ${String(MAX_DUEL)} players for one slot. Each is a distribution of his week-${String(week)} ${scoringLabel} points given that he plays, from ${weekly.model_version}; the pick is whoever gives you the best chance to win the week at your margin.`}
      />
      {kickedOff && (
        <Notice severity="warning" title={`Every week-${String(week)} game had kicked off when this build ran.`}>
          The next week&rsquo;s projections publish once week {String(week)}&rsquo;s results are complete
          upstream.
        </Notice>
      )}

      <DuelDeck duel={duel} weekly={weekly} onRemove={toggle} onSelect={onSelect} />

      {duel.missing.length > 0 && (
        <p className="startsit-missing" role="note">
          {`${String(duel.missing.length)} player${duel.missing.length === 1 ? "" : "s"} in this link ${duel.missing.length === 1 ? "has" : "have"} no week-${String(week)} projection on this build and ${duel.missing.length === 1 ? "is" : "are"} left out.`}
        </p>
      )}

      <Verdict duel={duel} weekly={weekly} onMargin={(margin) => { onChange({ margin }); }} />

      {duel.eligible.length >= 1 && (
        <figure className="startsit-figure">
          <figcaption className="startsit-subhead">
            <span>The week, as a distribution</span>
            <span className="startsit-subhead-note">shape = where his points land; one scale for all</span>
          </figcaption>
          <OutcomeRidges contenders={duel.contenders} />
        </figure>
      )}

      {duel.matrix !== null && duel.eligible.length >= 3 && <HeadToHead duel={duel} />}

      {duel.verdict !== null && <WhyPanel duel={duel} weekly={weekly} />}

      <WeekBoard
        rows={board}
        order={effectiveOrder}
        onOrder={setOrder}
        duel={state.duel}
        onToggle={toggle}
        onSelect={onSelect}
        week={week}
        showAll={showAll}
        onShowAll={() => { setShowAll((value) => !value); }}
        weekly={weekly}
      />

      <details className="startsit-method">
        <summary>How these numbers are made, and how well they have done</summary>
        <MethodNotes weekly={weekly} />
      </details>
    </section>
  );
}

// --------------------------------------------------------------------------- the deck

function DuelDeck({
  duel,
  weekly,
  onRemove,
  onSelect,
}: {
  readonly duel: DuelReading;
  readonly weekly: RosWeeklyMetadata;
  readonly onRemove: (playerId: string) => void;
  readonly onSelect: (playerId: string) => void;
}): React.JSX.Element {
  const empty = MAX_DUEL - duel.contenders.length;
  const leader = duel.verdict?.pick.record.player_id ?? null;
  return (
    <div className="deck" data-count={duel.contenders.length}>
      {duel.contenders.map((contender, slot) => (
        <DeckCard
          key={contender.record.player_id}
          contender={contender}
          slot={slot}
          weekly={weekly}
          sigma={duel.sigma}
          lead={leader === contender.record.player_id}
          onRemove={onRemove}
          onSelect={onSelect}
        />
      ))}
      {Array.from({ length: empty }, (_, index) => (
        <div key={`empty-${String(index)}`} className="deck-card deck-empty chamfer">
          <span className="deck-slot" aria-hidden="true">
            {slotLetter(duel.contenders.length + index)}
          </span>
          <p>
            {duel.contenders.length + index === 0
              ? "Add a player from the week board below — the + beside any name."
              : duel.contenders.length + index === 1
                ? "Add a second player to compare."
                : "Optional: a third or fourth candidate for the slot."}
          </p>
        </div>
      ))}
    </div>
  );
}

function DeckCard({
  contender,
  slot,
  weekly,
  sigma,
  lead,
  onRemove,
  onSelect,
}: {
  readonly contender: Contender;
  readonly slot: number;
  readonly weekly: RosWeeklyMetadata;
  readonly sigma: number | null;
  readonly lead: boolean;
  readonly onRemove: (playerId: string) => void;
  readonly onSelect: (playerId: string) => void;
}): React.JSX.Element {
  const record = contender.record;
  const q = record.quantiles;
  const injury = injuryReading(record, weekly);
  const letter = slotLetter(slot);
  const state = contender.bye
    ? "bye"
    : contender.pending
      ? "pending"
      : contender.out
        ? "out"
        : contender.locked
          ? "locked"
          : "open";
  return (
    <article
      className="deck-card chamfer"
      data-slot={letter}
      data-lead={lead ? "true" : undefined}
      data-state={state}
      aria-label={`Slot ${letter}: ${record.display_name}`}
    >
      <header className="deck-head">
        <span className="deck-slot" aria-hidden="true">{letter}</span>
        <div className="deck-id">
          <button type="button" className="deck-name" onClick={() => { onSelect(record.player_id); }}>
            {record.display_name}
          </button>
          <span className="deck-meta">
            <PositionTag position={record.position} />
            <span>{`${record.team} ${gameLine(record)}`}</span>
          </span>
        </div>
        <button
          type="button"
          className="deck-remove"
          aria-label={`Remove ${record.display_name} from the comparison`}
          onClick={() => { onRemove(record.player_id); }}
        >
          ×
        </button>
      </header>

      {state !== "open" && (
        <p className="deck-flag" data-kind={state}>
          {state === "bye"
            ? `Bye in week ${String(record.target_week)} — he cannot fill the slot.`
            : state === "pending"
              ? "No sportsbook line is posted for his game yet. The model needs one, so he is projected once it is — left out of the verdict until then."
              : state === "out"
              ? "Ruled out on the official report — left out of the verdict."
              : "His game has kicked off; this projection is the record, not a choice."}
        </p>
      )}

      {q !== null && (
        <>
          <div className="deck-number">
            <span className="deck-median">{formatValue(q.q50)}</span>
            <span className="deck-unit">median pts</span>
          </div>
          <dl className="deck-range">
            <div>
              <dt>Floor</dt>
              <dd>{formatValue(q.q10)}</dd>
            </div>
            <div>
              <dt>P25–P75</dt>
              <dd>{`${formatValue(q.q25)}–${formatValue(q.q75)}`}</dd>
            </div>
            <div>
              <dt>Ceiling</dt>
              <dd>{formatValue(q.q90)}</dd>
            </div>
          </dl>
          {sigma !== null && contender.winProbability !== null && contender.eligible && (
            <ShieldMeter value={contender.winProbability} label="Win the week" tone={lead ? "lead" : "trail"} />
          )}
          {contender.topOfSet !== null && (
            <ShieldMeter value={contender.topOfSet} label="Top scorer of the set" />
          )}
          {contender.startable !== null && (
            <p className="deck-startable">
              <strong>{percent(contender.startable.probability)}</strong>
              {` chance of a startable week (≥ ${formatValue(contender.startable.threshold)} pts)`}
            </p>
          )}
        </>
      )}

      <footer className="deck-foot">
        {record.game !== null && (
          <span>
            {formatEastern(record.game.kickoff_utc)}
            {record.game.team_points !== null && ` · team total ${formatValue(record.game.team_points)}`}
          </span>
        )}
        {injury !== null && (
          <span className="deck-injury" data-designation={record.injury?.designation ?? undefined} title={injury.sentence}>
            <span aria-hidden="true">{injury.short}</span>
            <span className="visually-hidden">{injury.sentence}</span>
          </span>
        )}
      </footer>
    </article>
  );
}

// --------------------------------------------------------------------------- the verdict

function Verdict({
  duel,
  weekly,
  onMargin,
}: {
  readonly duel: DuelReading;
  readonly weekly: RosWeeklyMetadata;
  readonly onMargin: (margin: number) => void;
}): React.JSX.Element | null {
  if (duel.contenders.length === 0) return null;
  const verdict = duel.verdict;
  const calibration = weekly.evaluation.calibration ?? [];
  const bin =
    verdict === null
      ? undefined
      : calibration.find((row) => {
          const favourite = Math.max(verdict.edge, 1 - verdict.edge);
          return favourite >= row.low && (favourite < row.high || row.high >= 1);
        });
  return (
    <div className="verdict chamfer" aria-live="polite">
      {verdict === null ? (
        <p className="verdict-empty">
          {duel.eligible.length === 1 && duel.contenders.length > 1
            ? "Only one of these players can fill the slot this week."
            : "Add a second player to get a verdict."}
        </p>
      ) : (
        <>
          <p className="verdict-kicker">
            <span aria-hidden="true">▸</span> Verdict · {verdict.word}
          </p>
          <p className="verdict-head">
            Start <strong>{verdict.pick.record.display_name}</strong>
          </p>
          <p className="verdict-line">
            {verdict.edge >= 0.5
              ? `He outscores ${verdict.runnerUp.record.display_name} ${percent(verdict.edge)} of the time`
              : // The pick is the better chance to win the week, not the likelier to outscore:
                // say both halves, or the sentence reads as a contradiction.
                `${verdict.runnerUp.record.display_name} outscores him ${percent(1 - verdict.edge)} of the time, but his range wins more matchups: ${winPair(verdict)}`}
            {verdict.correlation.measured
              ? ` — same game, outcomes correlated (ρ ${formatSigned(verdict.correlation.rho, 2)}), accounted for.`
              : "."}
            {bin !== undefined &&
              ` On the sealed ${String(weekly.evaluation.holdout_season ?? "")} season, favourites given ${percent(bin.low)}–${percent(bin.high)} won ${percent(bin.observed)} of ${bin.pairs.toLocaleString("en-US")} such calls.`}
          </p>
          {verdict.postureChangedPick && (
            <p className="verdict-line verdict-posture-note">
              {`${verdict.medianLeader.record.display_name} has the higher median, but at ${marginLabel(duel.margin).toLowerCase()} ${verdict.pick.record.display_name}'s range gives you the better chance to win the week.`}
            </p>
          )}
          {verdict.flip !== null && Math.abs(verdict.flip.margin) <= MARGIN_BOUND ? (
            <p className="verdict-line verdict-flip">
              <span className="verdict-flip-label">Flip point</span>
              {` ${flipSentence(verdict.flip)}`}
            </p>
          ) : (
            duel.sigma !== null && (
              <p className="verdict-line verdict-flip">
                <span className="verdict-flip-label">No flip point</span>
                {` ${verdict.pick.record.display_name} is the better start at every margin from down ${String(MARGIN_BOUND)} to up ${String(MARGIN_BOUND)}.`}
              </p>
            )
          )}
        </>
      )}

      <div className="posture">
        <Segmented
          label="Your matchup without this slot"
          name="posture"
          value={POSTURES.some((posture) => posture.value === duel.margin) ? duel.margin : 999}
          options={[
            ...POSTURES.map((posture) => ({ value: posture.value, label: posture.label, description: posture.long })),
            ...(POSTURES.some((posture) => posture.value === duel.margin)
              ? []
              : [{ value: 999, label: marginLabel(duel.margin), description: `Custom margin ${String(duel.margin)} points` }]),
          ]}
          onChange={(value) => {
            if (value !== 999) onMargin(value);
          }}
        />
        <label className="posture-slider">
          <span className="visually-hidden">Matchup margin in points</span>
          <input
            type="range"
            min={-MARGIN_BOUND}
            max={MARGIN_BOUND}
            step={1}
            value={duel.margin}
            onChange={(event) => { onMargin(Number(event.target.value)); }}
          />
          <output>{`${duel.margin > 0 ? "+" : ""}${String(duel.margin)} pts`}</output>
        </label>
        <p className="posture-note">
          {duel.sigma === null
            ? "This build published no matchup uncertainty, so the pick is the higher median."
            : `Your margin from every other slot, yours minus theirs — read it off your platform's projected score. Its uncertainty, ±${formatValue(duel.sigma)} pts, is measured from the model's own misses over a full lineup on both sides; kickers and defences are not counted, so a real week is a little less certain.`}
        </p>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- head to head, and why

function HeadToHead({ duel }: { readonly duel: DuelReading }): React.JSX.Element {
  const players = duel.eligible;
  const slots = new Map(duel.contenders.map((contender, index) => [contender.record.player_id, slotLetter(index)]));
  return (
    <div className="h2h">
      <p className="startsit-subhead">
        <span>Head to head</span>
        <span className="startsit-subhead-note">row outscores column</span>
      </p>
      <table className="h2h-table">
        <thead>
          <tr>
            <th scope="col"><span className="visually-hidden">Player</span></th>
            {players.map((player) => (
              <th key={player.record.player_id} scope="col">
                {`${slots.get(player.record.player_id) ?? ""} ${lastName(player.record.display_name)}`}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {players.map((row, i) => (
            <tr key={row.record.player_id}>
              <th scope="row">{`${slots.get(row.record.player_id) ?? ""} ${lastName(row.record.display_name)}`}</th>
              {players.map((column, j) => {
                const value = duel.matrix?.[i]?.[j] ?? null;
                return (
                  <td
                    key={column.record.player_id}
                    data-edge={value === null ? undefined : value >= 0.55 ? "win" : value <= 0.45 ? "loss" : "even"}
                  >
                    {value === null ? EM_DASH : percent(value)}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function WhyPanel({
  duel,
  weekly,
}: {
  readonly duel: DuelReading;
  readonly weekly: RosWeeklyMetadata;
}): React.JSX.Element | null {
  const verdict = duel.verdict;
  if (verdict === null) return null;
  const a = verdict.pick.record;
  const b = verdict.runnerUp.record;
  if (a.drivers === null || b.drivers === null) return null;
  const drivers = { a: a.drivers, b: b.drivers };
  const rows = [
    ...(a.position === b.position ? [] : [{ key: "baseline", label: "Position baseline" }]),
    ...WEEKLY_DRIVER_FAMILIES.map((family) => ({ key: family, label: weekly.families[family] ?? family })),
  ]
    .map((row) => {
      const key = row.key as keyof typeof drivers.a;
      return { ...row, gap: (drivers.a[key] ?? 0) - (drivers.b[key] ?? 0) };
    })
    .filter((row) => Math.abs(row.gap) >= 0.05)
    .sort((left, right) => Math.abs(right.gap) - Math.abs(left.gap));
  const bound = Math.max(1, ...rows.map((row) => Math.abs(row.gap)));
  const medianGap = (a.quantiles?.q50 ?? 0) - (b.quantiles?.q50 ?? 0);
  return (
    <div className="why">
      <p className="startsit-subhead">
        <span>{`Why ${lastName(a.display_name)} over ${lastName(b.display_name)}`}</span>
        <span className="startsit-subhead-note">{`median gap ${formatSigned(medianGap)} pts, by reason`}</span>
      </p>
      {rows.length === 0 ? (
        <p className="why-empty">Their medians are built the same way; the difference is in their ranges.</p>
      ) : (
        <ul className="why-list">
          {rows.map((row) => (
            <li key={row.key} data-favours={row.gap > 0 ? "a" : "b"}>
              <span className="why-label">{row.label}</span>
              <span className="why-track" aria-hidden="true">
                <span
                  className="why-bar"
                  style={{
                    width: `${String((Math.abs(row.gap) / bound) * 50)}%`,
                    [row.gap > 0 ? "left" : "right"]: "50%",
                  }}
                />
              </span>
              <span className="why-value">
                {`${formatSigned(row.gap)} `}
                <span className="why-who">{row.gap > 0 ? lastName(a.display_name) : lastName(b.display_name)}</span>
              </span>
            </li>
          ))}
        </ul>
      )}
      <p className="why-note">
        Grouped contributions to each median from the model&rsquo;s own decomposition (TreeSHAP),
        differenced. They sum, with the calibration shift, to the median gap. Game environment is the
        sportsbook total and spread; opponent is what his defence allows the position.
      </p>
    </div>
  );
}

// --------------------------------------------------------------------------- the board

function WeekBoard({
  rows,
  order,
  onOrder,
  duel,
  onToggle,
  onSelect,
  week,
  showAll,
  onShowAll,
  weekly,
}: {
  readonly rows: readonly WeekBoardRow[];
  readonly order: WeekBoardOrder;
  readonly onOrder: (order: WeekBoardOrder) => void;
  readonly duel: readonly string[];
  readonly onToggle: (playerId: string) => void;
  readonly onSelect: (playerId: string) => void;
  readonly week: number;
  readonly showAll: boolean;
  readonly onShowAll: () => void;
  readonly weekly: RosWeeklyMetadata;
}): React.JSX.Element {
  const shown = showAll ? rows : rows.slice(0, BOARD_PAGE);
  const playing = rows.filter((row) => row.record.quantiles !== null);
  const high = Math.max(10, ...playing.map((row) => row.record.quantiles?.q90 ?? 0));
  const low = Math.min(0, ...playing.map((row) => row.record.quantiles?.q10 ?? 0));
  const at = (value: number): number => ((value - low) / (high - low)) * 100;
  const full = duel.length >= MAX_DUEL;
  return (
    <div className="weekboard">
      <div className="weekboard-head">
        <p className="startsit-subhead">
          <span>{`Week ${String(week)} board`}</span>
          <span className="startsit-subhead-note">{`${String(rows.length)} players · + adds to the comparison`}</span>
        </p>
        <Segmented
          label="Order by"
          name="weekboard-order"
          value={order}
          options={ORDERS.map((option) => ({ value: option.value, label: option.label, description: option.description }))}
          onChange={onOrder}
        />
      </div>
      <div className="weekboard-scroll">
        <table className="sheet weekboard-table">
          <thead>
            <tr>
              <th scope="col" className="wb-add"><span className="visually-hidden">Compare</span></th>
              <th scope="col" className="wb-rank">Pos rk</th>
              <th scope="col" className="wb-player">Player</th>
              <th scope="col" className="wb-game">Game</th>
              <th scope="col" className="wb-num wb-implied">Team total</th>
              <th scope="col" className="wb-num wb-opp">Opp. allows</th>
              <th scope="col" className="wb-num">Median</th>
              <th scope="col" className="wb-range">P10 – P90</th>
              <th scope="col" className="wb-num wb-start">Startable</th>
            </tr>
          </thead>
          <tbody>
            {shown.map((row) => {
              const record = row.record;
              const q = record.quantiles;
              const inDuel = duel.includes(record.player_id);
              const injury = injuryReading(record, weekly);
              return (
                <tr key={record.player_id} data-in-duel={inDuel ? "true" : undefined} data-locked={row.locked ? "true" : undefined}>
                  <td className="wb-add">
                    <button
                      type="button"
                      className="wb-toggle"
                      aria-pressed={inDuel}
                      disabled={!inDuel && (full || q === null)}
                      aria-label={inDuel ? `Remove ${record.display_name} from the comparison` : `Add ${record.display_name} to the comparison`}
                      onClick={() => { onToggle(record.player_id); }}
                    >
                      {inDuel ? "✓" : "+"}
                    </button>
                  </td>
                  <td className="wb-rank">{row.positionRank === null ? EM_DASH : `${record.position}${String(row.positionRank)}`}</td>
                  <td className="wb-player">
                    <span className="player-cell">
                      <button type="button" className="player-name" onClick={() => { onSelect(record.player_id); }}>
                        {record.display_name}
                      </button>
                      {injury !== null && (
                        <span className="deck-injury" data-designation={record.injury?.designation ?? undefined} title={injury.sentence}>
                          <span aria-hidden="true">{injury.short}</span>
                          <span className="visually-hidden">{injury.sentence}</span>
                        </span>
                      )}
                    </span>
                    <span className="wb-sub">{`${record.position} · ${record.team} ${gameLine(record)}`}</span>
                  </td>
                  <td className="wb-game">
                    {record.game === null ? "Bye" : gameLine(record)}
                    {row.locked && <span className="wb-locked"> · locked</span>}
                  </td>
                  <td className="wb-num wb-implied">{formatValue(record.game?.team_points ?? null)}</td>
                  <td className="wb-num wb-opp">
                    {record.opponent?.rank === null || record.opponent?.rank === undefined
                      ? EM_DASH
                      : `${ordinal(record.opponent.rank)} of ${String(record.opponent.defenses ?? 32)}`}
                  </td>
                  <td className="wb-num wb-median">{q === null ? EM_DASH : formatValue(q.q50)}</td>
                  <td className="wb-range">
                    {q === null ? (
                      <span className="wb-bye">{record.game_state === "lines_pending" ? "line pending" : "bye"}</span>
                    ) : (
                      <span className="wb-bar" aria-label={`P10 ${formatValue(q.q10)}, P25 ${formatValue(q.q25)}, median ${formatValue(q.q50)}, P75 ${formatValue(q.q75)}, P90 ${formatValue(q.q90)}`} role="img">
                        <span className="wb-bar-whisker" style={{ left: `${String(at(q.q10))}%`, width: `${String(at(q.q90) - at(q.q10))}%` }} />
                        <span className="wb-bar-box" style={{ left: `${String(at(q.q25))}%`, width: `${String(Math.max(0.8, at(q.q75) - at(q.q25)))}%` }} />
                        <span className="wb-bar-median" style={{ left: `${String(at(q.q50))}%` }} />
                        {row.threshold !== null && <span className="wb-bar-threshold" style={{ left: `${String(at(row.threshold))}%` }} />}
                      </span>
                    )}
                  </td>
                  <td className="wb-num wb-start">{percent(row.startable)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {rows.length > BOARD_PAGE && (
        <button type="button" className="button weekboard-more" onClick={onShowAll}>
          {showAll ? `Show the top ${String(BOARD_PAGE)}` : `Show all ${String(rows.length)}`}
        </button>
      )}
      <p className="weekboard-note">
        Range bar: whisker P10–P90, box P25–P75, tick the median, dashed line a startable week at his
        position in your league. &ldquo;Opp. allows&rdquo; ranks his opponent by fantasy points allowed to the
        position this season, shrunk toward the league rate; 1st is the most generous.
      </p>
    </div>
  );
}

function ordinal(value: number): string {
  const tens = value % 100;
  if (tens >= 11 && tens <= 13) return `${String(value)}th`;
  const suffix = { 1: "st", 2: "nd", 3: "rd" }[value % 10] ?? "th";
  return `${String(value)}${suffix}`;
}

// --------------------------------------------------------------------------- the method

function MethodNotes({ weekly }: { readonly weekly: RosWeeklyMetadata }): React.JSX.Element {
  const evaluation = weekly.evaluation;
  const seasons = weekly.training_seasons;
  const rates = Object.entries(weekly.injury_base_rates).filter(
    (entry): entry is [string, { reports: number; appeared: number; appearance_rate: number | null }] =>
      "appearance_rate" in entry[1],
  );
  return (
    <div className="startsit-method-body">
      <p>{weekly.statement}</p>
      <dl className="facts">
        <div>
          <dt>Model</dt>
          <dd>{`${weekly.model_version} · ${weekly.candidate_version}`}</dd>
        </div>
        <div>
          <dt>Trained on</dt>
          <dd>{seasons.length > 0 ? `${String(seasons[0])}–${String(seasons[seasons.length - 1])}` : EM_DASH}</dd>
        </div>
        <div>
          <dt>{`Sealed ${String(evaluation.holdout_season ?? "")} test`}</dt>
          <dd>
            {evaluation.holdout_pair_accuracy === undefined
              ? EM_DASH
              : `start/sit calls right ${percent(evaluation.holdout_pair_accuracy, 1)} of ${(evaluation.holdout_pairs ?? 0).toLocaleString("en-US")} same-position pairs (best simple rule ${percent(evaluation.best_baseline_pair_accuracy, 1)})`}
          </dd>
        </div>
        <div>
          <dt>Range honesty</dt>
          <dd>
            {evaluation.holdout_coverage_80 === undefined
              ? EM_DASH
              : `${percent(evaluation.holdout_coverage_80, 1)} of outcomes fell inside P10–P90 (target 80%)`}
          </dd>
        </div>
      </dl>
      {rates.length > 0 && (
        <p>
          {`Official designations, ${String((weekly.injury_base_rates._rule as { seasons?: number[] } | undefined)?.seasons?.[0] ?? "")}–${String((weekly.injury_base_rates._rule as { seasons?: number[] } | undefined)?.seasons?.slice(-1)[0] ?? "")}: `}
          {rates
            .map(([designation, entry]) => `${designation} players appeared ${percent(entry.appearance_rate)} of the time`)
            .join("; ")}
          . The projection assumes he plays; the report is printed beside it, never read by it.
        </p>
      )}
    </div>
  );
}
