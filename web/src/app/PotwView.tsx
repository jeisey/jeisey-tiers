/**
 * Pick of the Week: four player highlights, one per position.
 *
 * The two in-season boards beside this one publish every row and let the reader do the
 * ordering. This view does the opposite — it makes a claim about four players — so almost
 * everything here is about making that claim checkable:
 *
 * - **the bar is printed, not implied.** Every card states the add count that qualified the
 *   player, the median it had to clear, and how many players at his position set that median.
 *   A reader who thinks the pick is wrong can see exactly which threshold produced it.
 * - **the reasons are published fields read back in words.** `reasonsFor` in `data/potw.ts`
 *   builds them; nothing in this file writes a sentence about a player.
 * - **no percentage of leagues and no matchup rating.** Two of the three things a waiver card
 *   conventionally shows that this product cannot source. ADR-088 records the four routes that
 *   were checked for a rostered share and why all four are closed; the honest substitute is
 *   the add volume itself, and it is labelled as a count of transactions every time it appears.
 * - **the third one is now sourced.** The mockup's `ADD MOMENTUM` sparkline was a *data* gap
 *   rather than a rights gap: the retained store had held a daily add/drop snapshot since the
 *   season opened and nothing published a series over them. `behavior_trend_series.json` does,
 *   and `BehaviorSparkline` draws it (ADR-089). It is still not a rostered share and still
 *   cannot become one — a count of transactions has no denominator in leagues.
 *
 * **The portrait is here on purpose and is bounded** (ADR-087 as extended by ADR-088). The
 * rule that a portrait never goes on a board row stands — three hundred rows would be three
 * hundred third-party requests for decoration. This is not a board: it is at most four cards
 * on a tab a reader chose to open, the picture is the format the owner asked for, and only the
 * visible set's portraits are ever in the DOM, so cycling sets replaces four requests rather
 * than accumulating twenty.
 */

import { useCallback, useMemo } from "react";

import { BehaviorSparkline } from "../charts/BehaviorSparkline";
import { MatchupPanel } from "../charts/MatchupPanel";
import { Bars } from "../charts/UsageRails";
import { PlayerPortrait } from "../components/PlayerPortrait";
import { Notice, PositionTag, RosStatusBadge, SectionHead } from "../components/primitives";
import { cohortStat, finiteValues } from "../data/cohort";
import type { Position, ScoringPreset, TeamMatchupRecord } from "../data/contracts";
import { EM_DASH, formatInteger, formatValue } from "../data/format";
import {
  POTW_POSITIONS,
  POTW_RULE_VERSION,
  absenceSentence,
  clampSet,
  selectPotwBoard,
  visiblePicks,
  type PotwAbsence,
  type PotwBoard,
  type PotwPick,
  type PotwSet,
} from "../data/potw";
import {
  behaviorMomentum,
  longAbsenceLabel,
  movesBound,
  type BehaviorMomentum,
  type InSeasonBundle,
} from "../data/ros";
import {
  DIRECTION_GLYPH,
  ROLE_METRICS_BY_POSITION,
  changeWindow,
  formatChange,
  formatMetric,
  formatShare,
  productionBars,
  roleReading,
  roleSentence,
} from "../data/signals";
import {
  POSITION_FILTERS,
  POSITION_LABELS,
  SCORING_TO_PRESET,
  leaguePresetId,
  type AppState,
} from "../data/state";

/** The mockup's four-tile readout row, in the order it lays them out. */
function Tile({
  label,
  value,
  hint,
  kind,
}: {
  readonly label: string;
  readonly value: string;
  readonly hint?: string | undefined;
  readonly kind?: "bargain" | "premium" | "even" | undefined;
}): React.JSX.Element {
  return (
    <div className="readout potw-tile" data-kind={kind} data-size="sm">
      <span className="readout-label">{label}</span>
      <span className="readout-value">{value}</span>
      {hint !== undefined && <span className="readout-hint">{hint}</span>}
    </div>
  );
}

/**
 * The adds-and-drops strip, on the board's own symmetric axis.
 *
 * The same geometry the Opportunity Board and the player card already draw, for the same
 * reason they draw it: drops left of centre, adds right, a bound taken from the population
 * rather than from the worst outlier, and a chevron where a count runs past it.
 *
 * It is **today's counts**, and it sits beside the momentum strip rather than being replaced
 * by it: one says how many rosters moved on him in the last window, the other says which way
 * that has been going. Two readings, side by side, no blended score — the rule the whole
 * feature is built on (ADR-088, ADR-089).
 */
function MovesStrip({
  adds,
  drops,
  bound,
}: {
  readonly adds: number | null;
  readonly drops: number | null;
  readonly bound: number;
}): React.JSX.Element {
  const addsWidth = Math.min(50, ((adds ?? 0) / bound) * 50);
  const dropsWidth = Math.min(50, ((drops ?? 0) / bound) * 50);
  return (
    <div className="opp-track" data-track="moves" data-card="true" aria-hidden="true">
      <span className="opp-zero" style={{ left: "50%" }} />
      <span
        className="opp-move-bar"
        data-kind="drop"
        style={{ left: `${String(50 - dropsWidth)}%`, width: `${String(dropsWidth)}%` }}
      />
      <span
        className="opp-move-bar"
        data-kind="add"
        style={{ left: "50%", width: `${String(addsWidth)}%` }}
      />
      {(adds ?? 0) > bound && (
        <span className="opp-overflow" data-kind="add">
          ›
        </span>
      )}
      {(drops ?? 0) > bound && (
        <span className="opp-overflow" data-kind="drop">
          ‹
        </span>
      )}
    </div>
  );
}

/**
 * The three kinds of evidence behind a pick, side by side and never combined (ADR-091).
 *
 * **Role** is what he is doing on the field, **production** is what it has scored and what
 * the model projects, **matchup** is the next game as context. Each has its own heading and
 * its own unit, for the reason the moves pair beneath it is two panels rather than one: they
 * share no scale, and a single "why" number made of them would be manufactured. Every figure
 * is a published field — the role change is the artifact's own difference and the implied
 * points the artifact's own arithmetic — and none of it chose this player: the pick is the
 * six gates and the rest-of-season ordering, exactly as before.
 */
function PickEvidence({
  pick,
  scoring,
  matchup,
  usagePublished,
  matchupsPublished,
}: {
  readonly pick: PotwPick;
  readonly scoring: ScoringPreset;
  readonly matchup: TeamMatchupRecord | null;
  readonly usagePublished: boolean;
  /** Whether this build published `team_matchups.json` at all. A different fact from the above. */
  readonly matchupsPublished: boolean;
}): React.JSX.Element {
  const { usage } = pick;
  const metrics = ROLE_METRICS_BY_POSITION[pick.position].slice(0, 2);
  const readings = usage === null ? [] : metrics.map((metric) => roleReading(usage, metric));
  const production = usage === null ? null : productionBars(usage, scoring);
  const latestGame = production?.bars.find((bar) => bar.latest) ?? null;
  const touchdowns = usage?.touchdown_points_share[scoring] ?? null;
  const record = pick.opportunity;
  const perGame =
    pick.ros === null
      ? null
      : typeof pick.ros.points_per_game_to_date === "number"
        ? pick.ros.points_per_game_to_date
        : null;

  return (
    <div className="potw-evidence">
      <section className="potw-evidence-block" data-evidence="role" aria-label="Role, observed">
        <span className="potw-evidence-kind">Role · observed</span>
        {usage === null ? (
          <p className="potw-evidence-row">
            {usagePublished
              ? "No week-by-week role is published for him."
              : "This build published no role series."}
          </p>
        ) : (
          readings.map((reading) => {
            const { spec, change, direction } = reading;
            return (
              <div key={spec.metric} className="potw-role" data-metric={spec.metric}>
                <p className="potw-evidence-row" title={roleSentence(reading)}>
                  <strong>{spec.label}</strong>
                  <span>
                    {change === null
                      ? "—"
                      : change.earlier === null
                        ? formatMetric(spec, change.latest)
                        : `${formatMetric(spec, change.earlier)} → ${formatMetric(spec, change.latest)}`}
                  </span>
                  {change?.change !== null && change?.change !== undefined && direction !== null && (
                    <span className="usage-rail-change" data-direction={direction}>
                      <span aria-hidden="true">{DIRECTION_GLYPH[direction]}</span>{" "}
                      {formatChange(spec, change.change)}
                    </span>
                  )}
                </p>
                <div className="usage-rail" data-direction={direction ?? "none"}>
                  <Bars bars={reading.bars} axisMax={reading.axisMax} />
                </div>
                <span className="visually-hidden">{roleSentence(reading)}</span>
              </div>
            );
          })
        )}
        {readings[0]?.change != null && (
          <p className="cohort-note">{changeWindow(readings[0].change)}</p>
        )}
      </section>

      <section
        className="potw-evidence-block"
        data-evidence="production"
        aria-label="Production"
      >
        <span className="potw-evidence-kind">Production</span>
        <p className="potw-evidence-row">
          <strong>Latest game</strong>
          <span>
            {latestGame?.value == null
              ? EM_DASH
              : `${formatValue(latestGame.value)} pts · week ${String(latestGame.week)}`}
          </span>
        </p>
        <p className="potw-evidence-row">
          <strong>Per game so far</strong>
          <span>{formatValue(perGame)}</span>
        </p>
        <p className="potw-evidence-row">
          <strong>Projected rate</strong>
          <span>{pick.projectedRate === null ? EM_DASH : formatValue(pick.projectedRate)}</span>
          {/* The division it is, word for word (ADR-086): never "expected points per game". */}
          <span className="usage-rail-window">remaining points ÷ remaining games</span>
        </p>
        <p className="potw-evidence-row">
          <strong>Points from TDs</strong>
          <span>
            {usage === null
              ? EM_DASH
              : touchdowns === null
                ? "under 10 points so far"
                : formatShare(touchdowns)}
          </span>
        </p>
      </section>

      <section className="potw-evidence-block" data-evidence="matchup" aria-label="Next game">
        <span className="potw-evidence-kind">Next game · context</span>
        {matchup === null ? (
          <p className="potw-evidence-row">
            {matchupsPublished
              ? `No next game is published for ${record.team ?? "his team"}.`
              : "This build published no schedule context."}
          </p>
        ) : (
          <MatchupPanel record={matchup} team={matchup.team} statement={null} compact />
        )}
      </section>
    </div>
  );
}

/**
 * One pick.
 *
 * The whole card is a rendering of two artifact records. The only arithmetic is the cohort
 * reading beside the rest-of-season value, which is `cohort.ts`'s rank-among-published-rows
 * and carries its own denominator, exactly as every other cohort reading in this product does.
 */
function PickCard({
  pick,
  movesAxis,
  valueStat,
  onSelect,
  selectedPlayerId,
  portraitUrl,
  momentum,
  seriesPublished,
  scoring,
  matchup,
  usagePublished,
  matchupsPublished,
}: {
  readonly pick: PotwPick;
  readonly movesAxis: number;
  readonly valueStat: ReturnType<typeof cohortStat>;
  readonly onSelect: (playerId: string) => void;
  readonly selectedPlayerId: string | null;
  readonly portraitUrl: string | null;
  /** The retained add window, or null when the feed has never carried this player. */
  readonly momentum: BehaviorMomentum | null;
  /** Whether this build published a series artifact at all. A different fact from the above. */
  readonly seriesPublished: boolean;
  readonly scoring: ScoringPreset;
  /** His team's next game, or null. Context only (ADR-091). */
  readonly matchup: TeamMatchupRecord | null;
  readonly usagePublished: boolean;
  readonly matchupsPublished: boolean;
}): React.JSX.Element {
  const record = pick.opportunity;
  const window =
    record.behavior_lookback_hours === null || record.behavior_lookback_hours === undefined
      ? "window unknown"
      : `${String(record.behavior_lookback_hours)}h`;
  const net = record.net_add_count ?? 0;

  return (
    <article
      className="potw-card chamfer"
      data-pos={record.position}
      data-selected={record.player_id === selectedPlayerId}
      aria-labelledby={`potw-name-${record.player_id}`}
    >
      <header className="potw-card-head">
        <span className="potw-card-pos" data-pos={record.position} aria-hidden="true">
          {record.position}
        </span>
        <div className="potw-card-identity">
          <h3 className="potw-card-name" id={`potw-name-${record.player_id}`}>
            <button
              type="button"
              className="player-name"
              onClick={() => {
                onSelect(record.player_id);
              }}
            >
              {record.display_name}
            </button>
          </h3>
          <p className="potw-card-sub">
            <PositionTag position={record.position} />
            <span className="dot-sep">
              {record.team ?? EM_DASH} · {record.position}
              {String(record.ros_position_rank)} rest-of-season
            </span>
            <RosStatusBadge status={record.current_status} />
            {record.long_absence && (
              <span className="absence-badge" data-flag="long-absence">
                <span aria-hidden="true">◷</span>
                <span className="absence-weeks">{longAbsenceLabel(record)}</span>
              </span>
            )}
          </p>
        </div>
        <span className="potw-card-seal chamfer">
          <span className="potw-seal-rank">{`#${String(pick.depth)}`}</span>
          <span className="potw-seal-label">
            {`${record.position} waiver pick`}
            <span className="potw-seal-of">
              {`of ${String(pick.poolSize)} eligible`}
              <span className="visually-hidden">
                {` — candidates at this position that cleared this week's add bar`}
              </span>
            </span>
          </span>
        </span>
      </header>

      <div className="potw-card-body">
        <div className="potw-card-portrait">
          <PlayerPortrait
            name={record.display_name}
            position={record.position}
            imageUrl={portraitUrl}
          />
          <span className="potw-portrait-team">{record.team ?? EM_DASH}</span>
        </div>

        <div className="readout-grid potw-tiles" data-row="primary">
          <Tile
            label={`Adds (${window})`}
            value={formatInteger(record.add_count)}
            hint={
              pick.floor.fromPopulation
                ? `bar ${formatInteger(pick.floor.value)} · median of ${String(pick.floor.count)}`
                : "too few counts to set a bar"
            }
          />
          <Tile
            label="Net roster moves"
            value={`${net > 0 ? "▲ +" : net < 0 ? "▼ " : ""}${formatInteger(net)}`}
            hint={`adds minus drops, ${window}`}
            kind={net > 0 ? "bargain" : net < 0 ? "premium" : "even"}
          />
          <Tile
            label="ROS expected VORP"
            value={formatValue(record.ros_expected_vorp)}
            hint={
              valueStat === null
                ? "points over replacement"
                : `${String(valueStat.rank)} of ${String(valueStat.count)} ${record.position}s`
            }
          />
        </div>

        <div className="potw-why">
          <span className="readout-label">Why he is the pick</span>
          <ul className="potw-why-list">
            {pick.reasons.map((reason) => (
              <li key={reason}>{reason}</li>
            ))}
          </ul>
        </div>

        {/*
          The evidence row (ADR-091) replaces the four-tile row that printed two three-week
          shares for every position — a quarterback's two constants included. Role is now his
          position's own readings week by week, production says what it scored, and the next
          game is context. The rest-of-season rank the old row carried is in the header's
          position rank and the seal beside it.
        */}
        <PickEvidence
          pick={pick}
          scoring={scoring}
          matchup={matchup}
          usagePublished={usagePublished}
          matchupsPublished={matchupsPublished}
        />

        <div className="potw-moves">
          {/*
            Two readings side by side, and the split is the product rule rather than a layout
            choice. The left strip is *this window*: how many rosters moved on him in the last
            24 hours, on the board's own symmetric axis. The right strip is *the window behind
            it*: which way that count has been going, over the days the store actually holds.
            They are never combined into one score — an instantaneous count and a rate have no
            shared unit, and a blend of them would be the most confident-looking number on the
            card (AGENTS.md section 10, ADR-088).
          */}
          <div className="potw-moves-pair">
            <div className="potw-moves-today">
              <span className="readout-label">
                {`Roster moves — drops left, adds right, axis ±${formatInteger(movesAxis)}`}
              </span>
              <MovesStrip
                adds={record.add_count ?? null}
                drops={record.drop_count ?? null}
                bound={movesAxis}
              />
            </div>
            {momentum === null ? (
              /*
                Three absences and a reader can act on the difference, so they are three
                sentences and never a blank panel — the same construction 6A.8.2 uses for a
                position with no pick.
              */
              <div className="momentum" data-direction="absent">
                <span className="readout-label">Add momentum</span>
                <p className="momentum-reading momentum-absent">
                  {seriesPublished
                    ? "No retained history: the feed has not carried him inside the window."
                    : "This build published no add/drop history."}
                </p>
              </div>
            ) : (
              <BehaviorSparkline momentum={momentum} />
            )}
          </div>
          <p className="cohort-note">
            {`${formatInteger(record.drop_count)} drops and ${formatInteger(record.add_count)} adds over the ${window} window. ` +
              "A count is a count of transactions, not a share of leagues." +
              (momentum === null
                ? ""
                : ` The strip beside it draws the ${String(momentum.record.observations)} retained snapshot${momentum.record.observations === 1 ? "" : "s"} behind that count.`)}
          </p>
        </div>
      </div>
    </article>
  );
}

export function PotwView({
  bundle,
  state,
  onChange,
  onSelect,
  selectedPlayerId,
  headshotFor,
}: {
  readonly bundle: InSeasonBundle;
  readonly state: AppState;
  readonly onChange: (next: Partial<AppState>) => void;
  readonly onSelect: (playerId: string) => void;
  readonly selectedPlayerId: string | null;
  /** The published portrait address for a player, or null. Injected so this stays a renderer. */
  readonly headshotFor: (playerId: string) => string | null;
}): React.JSX.Element {
  const board = useMemo(() => selectPotwBoard(bundle, state), [bundle, state]);
  const activeIndex = clampSet(state.set, board);
  const activeSet = board.sets[activeIndex - 1] ?? null;
  const picks = activeSet === null ? [] : visiblePicks(activeSet, state.position);

  const rows = useMemo(
    () => bundle.opportunityFor(leaguePresetId(state.teams), SCORING_TO_PRESET[state.scoring]),
    [bundle, state.teams, state.scoring],
  );

  /** The whole block's counts, bounded exactly as the Opportunity Board bounds them. */
  const movesAxis = useMemo(() => {
    const counts = finiteValues([
      ...rows.map((row) => row.add_count),
      ...rows.map((row) => row.drop_count),
    ]);
    return counts.length === 0 ? 1 : movesBound(counts);
  }, [rows]);

  const onSetChange = useCallback(
    (next: number) => {
      onChange({ set: next });
    },
    [onChange],
  );

  if (!bundle.hasOpportunity) {
    return (
      <section className="section" aria-labelledby="potw-missing-heading">
        <SectionHead
          index="01"
          id="potw-missing-heading"
          title="Pick of the Week"
          note="This build published no opportunity artifact, which is where the add and drop counts live."
        />
        <Notice title="No waiver picks in this build.">
          A pick is chosen from published add and drop counts, and this build has none. The
          rest-of-season board is unaffected: every intrinsic value is exactly what the build
          produced. {bundle.opportunityDegradation?.message ?? ""}
        </Notice>
      </section>
    );
  }

  return (
    <section className="section" aria-labelledby="potw-heading">
      <SectionHead
        index="01"
        id="potw-heading"
        title={`Pick of the Week — through week ${String(bundle.throughWeek)}`}
        note={
          "The most valuable player at each position that the wire is still moving on. " +
          "Roster moves decide who is eligible; the rest-of-season model decides who wins. " +
          "Nothing here is a share of leagues — this product cannot publish one."
        }
      >
        {board.sets.length > 1 && (
          <div className="segmented potw-sets" role="group" aria-label="Pick set">
            {board.sets.map((set) => (
              <button
                key={set.index}
                type="button"
                aria-pressed={set.index === activeIndex}
                onClick={() => {
                  onSetChange(set.index);
                }}
              >
                {`Set ${String(set.index)}`}
              </button>
            ))}
          </div>
        )}
      </SectionHead>

      {/* The mockup's position chip row. It writes the *global* position filter rather than a
          second one of its own, so a reader who narrows here sees the same narrowing on the
          boards beside it and the URL says so once. */}
      <div className="potw-chiprow">
        <span className="potw-chiprow-label">
          {state.position === "all" ? "All positions featured" : POSITION_LABELS[state.position]}
        </span>
        <div className="segmented" role="group" aria-label="Position">
          {POSITION_FILTERS.map((filter) => (
            <button
              key={filter}
              type="button"
              aria-pressed={state.position === filter}
              onClick={() => {
                onChange({ position: filter });
              }}
            >
              {filter === "all" ? "All" : POSITION_LABELS[filter]}
            </button>
          ))}
        </div>
        <span className="potw-chiprow-meta muted">
          {`${String(board.sets.length)} set${board.sets.length === 1 ? "" : "s"} · ` +
            `${String(board.consideredRows)} rows considered · ${POTW_RULE_VERSION}`}
        </span>
      </div>

      {!board.behaviorAvailable && (
        <Notice title="No current add/drop behaviour.">
          A waiver pick needs evidence that rosters can still acquire the player, and the only
          such evidence this product publishes is the add and drop counts. The build recorded
          {` “${bundle.metadata.behavior?.degraded_reason ?? "no retained behaviour snapshot"}”.`}{" "}
          Every rest-of-season value on the boards beside this one is unchanged.
        </Notice>
      )}

      {board.behaviorAvailable && board.sets.length === 0 && (
        <Notice title="Nobody cleared the bar this week.">
          No player at any position was added more than the median of his position&rsquo;s own
          add counts with roster moves running positive. That is a quiet wire, not a failure —
          the Opportunity Board has every published row and every count behind this decision.
        </Notice>
      )}

      {picks.length > 0 && (
        <div className="potw-grid">
          {picks.map((pick) => (
            <PickCard
              key={pick.opportunity.player_id}
              pick={pick}
              movesAxis={movesAxis}
              valueStat={cohortStat(
                rows
                  .filter((row) => row.position === pick.position)
                  .map((row) => row.ros_expected_vorp),
                pick.opportunity.ros_expected_vorp,
                "desc",
              )}
              onSelect={onSelect}
              selectedPlayerId={selectedPlayerId}
              portraitUrl={headshotFor(pick.opportunity.player_id)}
              momentum={behaviorMomentum(bundle, pick.opportunity.player_id)}
              seriesPublished={bundle.hasBehaviorSeries}
              scoring={SCORING_TO_PRESET[state.scoring]}
              matchup={bundle.matchupFor(pick.usage?.team ?? pick.opportunity.team)}
              usagePublished={bundle.hasUsage}
              matchupsPublished={bundle.hasMatchups}
            />
          ))}
        </div>
      )}

      {/* A position with no pick says which case it is in, rather than rendering an empty
          frame. The three cases are genuinely different and a reader can act on the
          difference: the feed is down, nobody qualified, or this set is deeper than the pool. */}
      {activeSet !== null && (
        <PositionAbsences set={activeSet} board={board} filter={state.position} />
      )}

      <p className="muted board-note">
        <strong>How a pick is chosen.</strong> A player is eligible when the feed reports him
        added at least as often as the median of his own position&rsquo;s non-zero add counts on
        this board, with adds exceeding drops over the same window, no long absence, and no
        roster code that says he cannot play. Among the eligible, the pick is the one the
        rest-of-season model values highest — the add count decides membership and never the
        ordering, because a count of transactions and a number of points share no unit and may
        not be combined into a score.
      </p>
      <p className="muted board-note">
        <strong>There is no rostered percentage here, and it is not an omission.</strong> No
        source this project may publish from reports one: Sleeper documents no ownership field,
        FantasyPros&rsquo; ownership columns are benchmark-only and may not be redistributed,
        and ESPN is disabled in the source registry. An add count is availability evidence in
        the direction that matters — a roster that added a player did not have him, so a player
        rostered nearly everywhere cannot post a large one — but it recovers no percentage, and
        nothing on this page claims it does.
      </p>
    </section>
  );
}

/**
 * The positions this set has no pick for, each saying which of three things happened.
 *
 * Never a blank card, and never one sentence for three different situations: a reader can act
 * on the difference between "the feed published nothing", "nobody cleared the bar" and "this
 * set is deeper than the pool", and only the last of those means looking at an earlier set.
 */
function PositionAbsences({
  set,
  board,
  filter,
}: {
  readonly set: PotwSet;
  readonly board: PotwBoard;
  readonly filter: AppState["position"];
}): React.JSX.Element | null {
  const shown: { position: Position; absence: PotwAbsence }[] = [];
  for (const position of POTW_POSITIONS) {
    const absence = set.absent.get(position);
    if (absence === undefined) continue;
    if (filter !== "all" && filter.toUpperCase() !== position) continue;
    shown.push({ position, absence });
  }
  if (shown.length === 0) return null;
  return (
    <ul className="potw-absences">
      {shown.map(({ position, absence }) => (
        <li key={position} className="potw-absence chamfer">
          <span className="potw-absence-pos" data-pos={position}>
            {position}
          </span>
          <span>{absenceSentence(position, absence, board)}</span>
        </li>
      ))}
    </ul>
  );
}
