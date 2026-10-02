/**
 * Trade: model-based targets for what a manager offers (ADR-100).
 *
 * Offer one to three players, choose what you want back — ROS value, the highest ceiling or the
 * highest floor — and how many players, and the tab deals ranked incoming packages whose
 * expected rest-of-season value falls in a band around what you offer. Every number is a
 * published `ros_tiers` field or `trade_targets_v1` arithmetic over them (`data/trade.ts`);
 * nothing here ranks, prices or filters on its own.
 *
 * Loaded lazily with its engine: a reader who never opens the tab never downloads either.
 */

import { useId, useMemo, useRef, useState } from "react";

import { Notice, PositionTag, RosStatusBadge, SectionHead, Segmented } from "../components/primitives";
import type { RosTierRecord } from "../data/contracts";
import { EM_DASH, formatSigned, formatValue } from "../data/format";
import { longAbsenceLabel, type InSeasonBundle } from "../data/ros";
import {
  COMP_SLOTS,
  MAX_GIVE,
  MAX_KEEP,
  SCORING_LABELS,
  SCORING_TO_PRESET,
  TRADE_COUNTS,
  TRADE_RANGES,
  canonicalComp,
  leaguePresetId,
  type AppState,
  type CompSlot,
  type TradeCount,
  type TradeGoal,
  type TradeRange,
} from "../data/state";
import {
  EXCLUSION_TEXT,
  KEPT_PROBLEM_TEXT,
  MEMBER_SHARE_MIN,
  POOL_CAP,
  afterKeep,
  checkKept,
  compositionLabel,
  dealingOrder,
  exhausted,
  explorationStamp,
  moreTargets,
  objectiveOf,
  resolveExploration,
  searchTrade,
  severeStatus,
  swapSlot,
  tradeHorizon,
  type Exclusion,
  type KeptPackage,
  type RankedPackage,
  type TradeHorizon,
  type TradePackage,
  type TradeSearch,
} from "../data/trade";

export const GOAL_LABELS: Readonly<Record<TradeGoal, string>> = {
  value: "ROS value",
  ceiling: "Highest ceiling",
  floor: "Highest floor",
};

const GOAL_STAT: Readonly<Record<TradeGoal, string>> = {
  value: "Value",
  ceiling: "Ceiling",
  floor: "Floor",
};

const SLOT_LABELS: Readonly<Record<CompSlot, string>> = {
  qb: "QB",
  rb: "RB",
  wr: "WR",
  te: "TE",
  any: "Any",
};

type Patch = Partial<AppState>;

/** Every control change starts a new search: the exploration is cleared, the shelf kept. */
const FRESH: Patch = { shown: [], dealt: 0, stamp: "" };

function plural(count: number, one: string, many = `${one}s`): string {
  return `${String(count)} ${count === 1 ? one : many}`;
}

function shapeLabel(give: number, get: number): string {
  return `Give ${String(give)} · Receive ${String(get)}`;
}

function rosterLabel(give: number, get: number): string {
  const change = get - give;
  if (change === 0) return "Same roster spots";
  return change > 0 ? `Needs ${plural(change, "open roster spot")}` : `Frees ${plural(-change, "roster spot")}`;
}

/** The same fact for a readout cell: `+1 spot`, `−1 spot`, `even`. */
function rosterShort(give: number, get: number): string {
  const change = get - give;
  if (change === 0) return "Even";
  return `${formatSigned(change, 0)} ${Math.abs(change) === 1 ? "spot" : "spots"}`;
}

/** A floor or ceiling, marked `~` when it is the two- or three-player approximation. */
function quantileText(pkg: TradePackage, value: number): string {
  return `${pkg.approximate ? "~" : ""}${formatValue(value)}`;
}

function percentOf(delta: number, base: number): string {
  return `${formatSigned((delta / base) * 100, 1)}%`;
}

function horizonSentence(horizon: TradeHorizon | null): string {
  if (horizon === null) return "Remaining weeks were not published with this build.";
  const span = `Weeks ${String(horizon.firstWeek)}–${String(horizon.lastWeek)} (${plural(horizon.weeks, "week")})`;
  if (!horizon.agreesWithContract) return `${span}.`;
  const playoffs =
    horizon.playoffFirstWeek === null
      ? ""
      : `, including weeks ${String(horizon.playoffFirstWeek)}–${String(horizon.lastWeek)}, where most fantasy playoffs fall`;
  return `${span}${playoffs}; NFL week ${String(horizon.excludedWeek)} is not counted. There is no playoff-only projection.`;
}

export function TradeView({
  bundle,
  state,
  onChange,
  onSelect,
}: {
  readonly bundle: InSeasonBundle;
  readonly state: AppState;
  readonly onChange: (patch: Patch) => void;
  readonly onSelect: (playerId: string) => void;
}): React.JSX.Element {
  const leaguePreset = leaguePresetId(state.teams);
  const scoring = SCORING_TO_PRESET[state.scoring];
  const records = useMemo(() => bundle.rosFor(leaguePreset, scoring), [bundle, leaguePreset, scoring]);
  const horizon = useMemo(
    () => tradeHorizon(bundle.season, bundle.throughWeek, bundle.rosFor(leaguePreset, scoring)),
    [bundle, leaguePreset, scoring],
  );

  // Keyed by value, not identity: every URL change parses fresh arrays, and a swap must not
  // re-run the search (ADR-100's 200 ms target is for the search; a swap is a re-deal).
  const giveKey = state.give.join(".");
  const compKey = state.comp.join(".");
  const search = useMemo(
    () =>
      measuredSearch({
        records,
        give: giveKey === "" ? [] : giveKey.split("."),
        goal: state.goal,
        get: state.get,
        range: state.range,
        comp: compKey === "" ? [] : (compKey.split(".") as CompSlot[]),
      }),
    [records, giveKey, state.goal, state.get, state.range, compKey],
  );

  const order = useMemo(
    () => (search.status === "ok" ? dealingOrder(search.pool) : []),
    [search],
  );
  const keepKey = state.keep.map((members) => [...members].sort().join(".")).join("_");
  const keptKeys = useMemo(() => new Set(keepKey === "" ? [] : keepKey.split("_")), [keepKey]);
  const stamp = explorationStamp({
    buildId: bundle.metadata.build_id,
    leaguePreset,
    scoring,
    give: state.give,
    goal: state.goal,
    get: state.get,
    range: state.range,
    comp: state.comp,
  });
  const { exploration, redealt } = useMemo(
    () => resolveExploration(order, { shown: state.shown, dealt: state.dealt }, state.stamp === stamp, keptKeys),
    [order, state.shown, state.dealt, state.stamp, stamp, keptKeys],
  );
  const visible = exploration.shown
    .map((index) => order[index])
    .filter((entry): entry is RankedPackage => entry !== undefined);
  const kept = useMemo(
    () => state.keep.map((ids) => checkKept(ids, records, { get: state.get, comp: state.comp }, search)),
    [state.keep, records, state.get, state.comp, search],
  );
  const noneLeft = search.status === "ok" && exhausted(order, exploration, keptKeys);
  // Players on this board, not ids in the link: a stale id gives nothing and takes no spot.
  const giveCount = search.outgoing.players.length + search.outgoing.unpriced.length;

  const control = (patch: Patch): void => {
    onChange({ ...patch, ...FRESH });
  };
  const explore = (next: { shown: readonly number[]; dealt: number } | null): void => {
    if (next !== null) onChange({ shown: next.shown, dealt: next.dealt, stamp });
  };
  const keep = (slot: number, entry: RankedPackage): void => {
    if (state.keep.length >= MAX_KEEP) return;
    const ids = entry.pkg.members.map((member) => member.id).sort();
    const nextKept = new Set([...keptKeys, entry.pkg.key]);
    const next = afterKeep(order, exploration, slot, nextKept);
    onChange({ keep: [...state.keep, ids], shown: next.shown, dealt: next.dealt, stamp });
  };
  const unkeep = (key: string): void => {
    onChange({ keep: state.keep.filter((ids) => [...ids].sort().join(".") !== key) });
  };

  // One sentence for assistive technology whenever the result set changes.
  const announcement =
    search.status !== "ok"
      ? ""
      : visible.length === 0
        ? "No packages qualify for these settings."
        : `${plural(visible.length, "package")} shown of ${String(search.qualifying)} that qualify, ranked by ${GOAL_LABELS[state.goal]}.`;

  const scoringLabel = SCORING_LABELS[state.scoring];

  if (records.length === 0) {
    return (
      <section className="section trade" aria-labelledby="trade-heading">
        <SectionHead index="01" id="trade-heading" title="Trade targets" />
        <Notice title="No rest-of-season values for this scoring and league size.">
          The Trade tab prices players from the rest-of-season board, and this build published
          none for {scoringLabel} at {String(state.teams)} teams. Every other board is unaffected.
        </Notice>
      </section>
    );
  }

  return (
    <section className="section trade" aria-labelledby="trade-heading">
      <SectionHead
        index="01"
        id="trade-heading"
        title="Trade targets"
        note={`Rest of season from ${bundle.metadata.ros_model_version}, through week ${String(bundle.throughWeek)} · ${scoringLabel} · ${String(state.teams)} teams. Value is expected points above the best player nobody rosters.`}
      />

      <GiveBox
        records={records}
        search={search}
        give={state.give}
        onAdd={(id) => {
          control({ give: [...state.give, id] });
        }}
        onRemove={(id) => {
          control({ give: state.give.filter((other) => other !== id) });
        }}
        onSelect={onSelect}
        disclosure={bundle.metadata.disclosures.long_absence_statement}
      />

      <div className="trade-controls">
        <Segmented<TradeGoal>
          name="trade-goal"
          label="Prefer"
          value={state.goal}
          options={(["value", "ceiling", "floor"] as const).map((goal) => ({
            value: goal,
            label: GOAL_LABELS[goal],
          }))}
          onChange={(goal) => {
            control({ goal });
          }}
        />
        <Segmented<TradeCount>
          name="trade-get"
          label="Players to receive"
          value={state.get}
          options={TRADE_COUNTS.map((count) => ({
            value: count,
            label: String(count),
            description: `Receive ${plural(count, "player")}`,
          }))}
          onChange={(get) => {
            control({ get, comp: resizeComp(state.comp, get) });
          }}
        />
        <Segmented<TradeRange>
          name="trade-range"
          label="Value range"
          value={state.range}
          options={TRADE_RANGES.map((range) => ({
            value: range,
            label: `±${String(range)}%`,
            description: `Within ${String(range)} percent of your value, either way`,
          }))}
          onChange={(range) => {
            control({ range });
          }}
        />
        <CompositionControl
          comp={state.comp}
          get={state.get}
          onChange={(comp) => {
            control({ comp });
          }}
        />
      </div>

      <p className="trade-shape">
        <strong>{shapeLabel(Math.max(giveCount, 1), state.get)}</strong>
        <span>{rosterLabel(Math.max(giveCount, 1), state.get)}</span>
        <span>{compositionLabel(state.comp, state.get)}</span>
      </p>
      <p className="trade-help">
        {horizonSentence(horizon)} Floor and ceiling are the 10th and 90th percentiles of a
        player&rsquo;s <em>total</em> value over those weeks — not weekly consistency, not one
        game&rsquo;s upside.
      </p>

      <SearchStatus search={search} state={state} onChange={control} />

      {search.status === "ok" && (
        <>
          <OutgoingLine search={search} goal={state.goal} />
          <p className="trade-disclaimer" role="note">
            <strong>Model-based targets.</strong> Each is a combination of players whose
            rest-of-season value is close to yours. They may be on different teams in your league,
            and this tool cannot know your league&rsquo;s rosters or whether anyone would accept.
          </p>
          {redealt && (
            <Notice severity="info" title="Re-dealt from the start.">
              This link&rsquo;s suggestions were made on a different board or different settings, so
              the current board&rsquo;s first packages are shown.
            </Notice>
          )}
        </>
      )}

      <p className="visually-hidden" aria-live="polite" role="status">
        {announcement}
      </p>

      {search.status === "ok" && visible.length > 0 && (
        <>
          <ol className="trade-results" aria-label={`Suggested packages, ranked by ${GOAL_LABELS[state.goal]}`}>
            {exploration.shown.map((index, slot) => {
              const entry = order[index];
              if (entry === undefined) return null;
              return (
                <PackageCard
                  key={entry.pkg.key}
                  entry={entry}
                  search={search}
                  goal={state.goal}
                  give={giveCount}
                  onSelect={onSelect}
                  actions={
                    <>
                      <button
                        type="button"
                        className="button trade-keep"
                        disabled={state.keep.length >= MAX_KEEP}
                        title={state.keep.length >= MAX_KEEP ? `Up to ${String(MAX_KEEP)} kept packages` : undefined}
                        onClick={() => {
                          keep(slot, entry);
                        }}
                      >
                        Keep
                      </button>
                      <button
                        type="button"
                        className="button trade-swap"
                        disabled={noneLeft}
                        aria-label={`Swap package ${String(slot + 1)} for another`}
                        onClick={() => {
                          explore(swapSlot(order, exploration, slot, keptKeys));
                        }}
                      >
                        Swap
                      </button>
                    </>
                  }
                />
              );
            })}
          </ol>
          <div className="trade-actions">
            <button
              type="button"
              className="button"
              disabled={noneLeft}
              onClick={() => {
                explore(moreTargets(order, exploration, keptKeys));
              }}
            >
              More targets
            </button>
            <button
              type="button"
              className="button"
              onClick={() => {
                onChange({ keep: [], ...FRESH });
              }}
            >
              Reset
            </button>
            <span className="trade-count">
              {`${plural(search.qualifying, "package")} qualify · best ${String(Math.min(search.qualifying, POOL_CAP))} explored · ${String(exploration.dealt)} dealt`}
            </span>
          </div>
          {noneLeft && (
            <p className="trade-exhausted" role="note">
              {`Every one of the best ${String(order.length)} packages has been dealt. Widen the value range, change the positions, or Reset to start over.`}
            </p>
          )}
        </>
      )}

      {kept.length > 0 && (
        <KeptShelf
          kept={kept}
          search={search}
          goal={state.goal}
          give={giveCount}
          onSelect={onSelect}
          onRemove={unkeep}
        />
      )}

      {search.status === "ok" && (search.excluded.length > 0 || search.belowReplacement > 0) && (
        <ExcludedList excluded={search.excluded} belowReplacement={search.belowReplacement} onSelect={onSelect} />
      )}

      <details className="trade-method">
        <summary>How targets are found</summary>
        <MethodNotes />
      </details>
    </section>
  );
}

/**
 * The search, timed. The benchmark (`measure-trade.mjs`) reads the `trade-search` entries;
 * one performance entry per search is the whole cost.
 */
function measuredSearch(query: Parameters<typeof searchTrade>[0]): TradeSearch {
  const timed = typeof performance !== "undefined" && typeof performance.measure === "function";
  const started = timed ? performance.now() : 0;
  const result = searchTrade(query);
  if (timed) performance.measure("trade-search", { start: started, end: performance.now() });
  return result;
}

/** Grow or shrink the composition with the receive count; extra slots are `any`. */
function resizeComp(comp: readonly CompSlot[], get: number): CompSlot[] {
  if (comp.length === 0) return [];
  const next = comp.slice(0, get);
  while (next.length < get) next.push("any");
  return next.every((slot) => slot === "any") ? [] : canonicalComp(next);
}

// ----------------------------------------------------------------------------- give box

function GiveBox({
  records,
  search,
  give,
  onAdd,
  onRemove,
  onSelect,
  disclosure,
}: {
  readonly records: readonly RosTierRecord[];
  readonly search: TradeSearch;
  readonly give: readonly string[];
  readonly onAdd: (id: string) => void;
  readonly onRemove: (id: string) => void;
  readonly onSelect: (id: string) => void;
  readonly disclosure: string;
}): React.JSX.Element {
  const byId = useMemo(() => new Map(records.map((record) => [record.player_id, record])), [records]);
  const flagged = give
    .map((id) => byId.get(id))
    .filter((record): record is RosTierRecord => record !== undefined && (record.long_absence || severeStatus(record.current_status) !== null));
  return (
    <div className="trade-give">
      <div className="trade-give-row">
        <span className="control-label" id="trade-give-label">
          You give
        </span>
        <ul className="trade-chips" aria-labelledby="trade-give-label">
          {give.map((id) => {
            const record = byId.get(id);
            return (
              <li key={id} className="trade-chip" data-missing={record === undefined || undefined}>
                {record === undefined ? (
                  <span className="trade-chip-name">Not on this board</span>
                ) : (
                  <>
                    <PositionTag position={record.position} />
                    <button type="button" className="player-name trade-chip-name" onClick={() => { onSelect(id); }}>
                      {record.display_name}
                    </button>
                    <RosStatusBadge status={record.current_status} />
                    <span className="trade-chip-value" title="Expected rest-of-season value over replacement">
                      {formatValue(record.ros_expected_vorp)}
                    </span>
                  </>
                )}
                <button
                  type="button"
                  className="trade-chip-remove"
                  aria-label={`Remove ${record?.display_name ?? "the missing player"} from what you give`}
                  onClick={() => { onRemove(id); }}
                >
                  ×
                </button>
              </li>
            );
          })}
        </ul>
        <PlayerPicker records={records} exclude={give} full={give.length >= MAX_GIVE} onPick={onAdd} />
      </div>
      {search.outgoing.missing.length > 0 && (
        <p className="trade-note" role="note">
          {`${plural(search.outgoing.missing.length, "player")} in this link ${search.outgoing.missing.length === 1 ? "is" : "are"} not on this board (build, scoring or league size) and ${search.outgoing.missing.length === 1 ? "counts" : "count"} for nothing.`}
        </p>
      )}
      {flagged.length > 0 && (
        <p className="trade-note" role="note">
          {flagged
            .map((record) =>
              record.long_absence
                ? `${record.display_name}: ${longAbsenceLabel(record).toLowerCase()}.`
                : `${record.display_name}: roster status ${record.current_status ?? ""}.`,
            )
            .join(" ")}{" "}
          {disclosure} His value is offered as published.
        </p>
      )}
    </div>
  );
}

/**
 * The outgoing-player search: a combobox over the block's published rows, best fair rank
 * first, at most eight suggestions. The full list is the ROS board, one tab away.
 */
function PlayerPicker({
  records,
  exclude,
  full,
  onPick,
}: {
  readonly records: readonly RosTierRecord[];
  readonly exclude: readonly string[];
  readonly full: boolean;
  readonly onPick: (id: string) => void;
}): React.JSX.Element {
  const id = useId();
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  const options = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (needle === "") return [];
    const out: RosTierRecord[] = [];
    for (const record of records) {
      if (exclude.includes(record.player_id)) continue;
      const hay = `${record.display_name} ${record.team ?? ""} ${record.position}`.toLowerCase();
      if (!hay.includes(needle)) continue;
      out.push(record);
      if (out.length >= 8) break;
    }
    return out;
  }, [records, exclude, query]);

  const pick = (record: RosTierRecord | undefined): void => {
    if (record === undefined) return;
    onPick(record.player_id);
    setQuery("");
    setOpen(false);
    input.current?.focus();
  };
  const expanded = open && options.length > 0;
  return (
    <div className="trade-picker">
      <label className="visually-hidden" htmlFor={id}>
        Add a player you would give
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
        autoComplete="off"
        spellCheck={false}
        disabled={full}
        placeholder={full ? `Up to ${String(MAX_GIVE)} players` : "Add a player you'd give"}
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
            if (query !== "" || open) {
              event.preventDefault();
              setQuery("");
              setOpen(false);
            }
          }
        }}
      />
      <ul id={`${id}-list`} role="listbox" className="trade-options" hidden={!expanded} aria-label="Players">
        {options.map((record, index) => (
          <li
            key={record.player_id}
            id={`${id}-opt-${String(index)}`}
            role="option"
            aria-selected={index === active}
            onMouseDown={(event) => {
              // Before the input's blur closes the list.
              event.preventDefault();
              pick(record);
            }}
          >
            <PositionTag position={record.position} />
            <span className="trade-option-name">{record.display_name}</span>
            <span className="trade-option-meta">{`${record.team ?? "FA"} · ${formatValue(record.ros_expected_vorp)}`}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

// -------------------------------------------------------------------------- composition

function CompositionControl({
  comp,
  get,
  onChange,
}: {
  readonly comp: readonly CompSlot[];
  readonly get: number;
  readonly onChange: (comp: CompSlot[]) => void;
}): React.JSX.Element {
  const slots: CompSlot[] = comp.length === get ? [...comp] : Array.from({ length: get }, () => "any" as const);
  return (
    <fieldset className="control trade-comp">
      <legend className="control-label">Positions</legend>
      <div className="trade-comp-slots">
        {slots.map((slot, index) => (
          <select
            key={`${String(index)}-${String(get)}`}
            aria-label={`Player ${String(index + 1)} position`}
            value={slot}
            onChange={(event) => {
              const next = [...slots];
              next[index] = event.target.value as CompSlot;
              onChange(next.every((value) => value === "any") ? [] : canonicalComp(next));
            }}
          >
            {COMP_SLOTS.map((option) => (
              <option key={option} value={option}>
                {SLOT_LABELS[option]}
              </option>
            ))}
          </select>
        ))}
      </div>
    </fieldset>
  );
}

// ------------------------------------------------------------------------- status lines

function SearchStatus({
  search,
  state,
  onChange,
}: {
  readonly search: TradeSearch;
  readonly state: AppState;
  readonly onChange: (patch: Patch) => void;
}): React.JSX.Element | null {
  if (search.status === "no_outgoing") {
    return (
      <p className="trade-empty">
        Add one to three players you would trade away. The tab then deals packages of the
        size you choose whose expected rest-of-season value is within your value range of
        theirs.
      </p>
    );
  }
  if (search.status === "unpriced_outgoing") {
    return (
      <Notice severity="warning" title="No published value.">
        {`${search.outgoing.unpriced.map((record) => record.display_name).join(", ")} has no complete rest-of-season value on this board, so nothing can be compared with it. Remove him to search.`}
      </Notice>
    );
  }
  if (search.status === "nonpositive") {
    const value = search.outgoing.pkg?.value ?? 0;
    return (
      <Notice severity="info" title="Nothing to trade for.">
        {`What you give is worth ${formatSigned(value)} over the rest of the season — at or below replacement, the best player nobody rosters. The model sees no asset value to match, so no packages are generated. Add a player with positive value.`}
      </Notice>
    );
  }
  if (search.pool.length > 0) {
    return search.truncated ? (
      <Notice severity="warning" title="Search stopped early.">
        This search reached its safety limit; the packages shown are the best of those examined.
        Narrow the value range or name positions to search everything.
      </Notice>
    ) : null;
  }
  // A comparable pool does not exist: say so and offer the explicit ways to broaden.
  const wider = TRADE_RANGES.find((range) => range > state.range);
  const otherCounts = TRADE_COUNTS.filter((count) => count !== state.get);
  return (
    <div className="notice trade-none" data-severity="info" role="note">
      <strong>No package qualifies.</strong>{" "}
      {`No ${plural(state.get, "player")} ${state.get === 1 ? "is" : "are"} worth between ${formatValue(search.band.low)} and ${formatValue(search.band.high)} together${state.comp.length > 0 ? ` as ${compositionLabel(state.comp, state.get)}` : ""}, with each carrying at least ${String(MEMBER_SHARE_MIN * 100)}% of the value. Nothing is widened for you:`}
      <span className="trade-broaden">
        {wider !== undefined && (
          <button type="button" className="button" onClick={() => { onChange({ range: wider }); }}>
            {`Widen to ±${String(wider)}%`}
          </button>
        )}
        {state.comp.length > 0 && (
          <button type="button" className="button" onClick={() => { onChange({ comp: [] }); }}>
            Any positions
          </button>
        )}
        {otherCounts.map((count) => (
          <button
            key={count}
            type="button"
            className="button"
            onClick={() => {
              onChange({ get: count, comp: resizeComp(state.comp, count) });
            }}
          >
            {`Receive ${String(count)}`}
          </button>
        ))}
      </span>
    </div>
  );
}

function OutgoingLine({
  search,
  goal,
}: {
  readonly search: Extract<TradeSearch, { status: "ok" }>;
  readonly goal: TradeGoal;
}): React.JSX.Element {
  const pkg = search.outgoingPkg;
  return (
    <dl className="trade-outgoing">
      <div>
        <dt>Your value</dt>
        <dd>{formatValue(pkg.value)}</dd>
      </div>
      <div data-active={goal === "floor" || undefined}>
        <dt>Floor</dt>
        <dd>{quantileText(pkg, pkg.p10)}</dd>
      </div>
      <div data-active={goal === "ceiling" || undefined}>
        <dt>Ceiling</dt>
        <dd>{quantileText(pkg, pkg.p90)}</dd>
      </div>
      <div>
        <dt>Proj. pts</dt>
        <dd>{formatValue(pkg.points)}</dd>
      </div>
      <div>
        <dt>Range</dt>
        <dd>{`${formatValue(search.band.low)} – ${formatValue(search.band.high)}`}</dd>
      </div>
    </dl>
  );
}

// ---------------------------------------------------------------------------- packages

function PackageMembers({
  pkg,
  onSelect,
}: {
  readonly pkg: TradePackage;
  readonly onSelect: (id: string) => void;
}): React.JSX.Element {
  return (
    <ul className="trade-members">
      {pkg.members.map((member) => (
        <li key={member.id}>
          <PositionTag position={member.record.position} />
          <span className="trade-member-id">
            <button type="button" className="player-name" onClick={() => { onSelect(member.id); }}>
              {member.record.display_name}
            </button>
            <span className="trade-member-team">{member.record.team ?? "FA"}</span>
          </span>
          <RosStatusBadge status={member.record.current_status} />
          <span className="trade-member-value" title="Expected rest-of-season value over replacement">
            {formatValue(member.value)}
          </span>
        </li>
      ))}
    </ul>
  );
}

/** "Why it qualifies", in numbers: the band, the share floor, and the rank under the preset. */
function qualifiesSentence(entry: RankedPackage, search: Extract<TradeSearch, { status: "ok" }>, goal: TradeGoal): string {
  const pkg = entry.pkg;
  const out = search.outgoingPkg;
  const parts = [
    `Value ${formatValue(pkg.value)} is ${formatSigned(entry.valueDelta)} (${percentOf(entry.valueDelta, out.value)}) against your ${formatValue(out.value)}, inside ±${String(search.band.range)}%.`,
  ];
  if (pkg.members.length > 1) {
    const smallest = Math.min(...pkg.members.map((member) => member.value));
    parts.push(`Smallest piece carries ${String(Math.round((smallest / pkg.value) * 100))}% (at least ${String(MEMBER_SHARE_MIN * 100)}% required).`);
  }
  if (goal !== "value") {
    parts.push(
      `${GOAL_STAT[goal]} ${quantileText(pkg, objectiveOf(pkg, goal))} vs your ${quantileText(out, objectiveOf(out, goal))} (${formatSigned(entry.objectiveDelta)}).`,
    );
  }
  parts.push(`#${String(entry.rank)} of ${String(search.qualifying)} by ${GOAL_LABELS[goal]}.`);
  return parts.join(" ");
}

function PackageMetrics({
  pkg,
  out,
  goal,
  give,
}: {
  readonly pkg: TradePackage;
  readonly out: TradePackage | null;
  readonly goal: TradeGoal;
  readonly give: number;
}): React.JSX.Element {
  const delta = (a: number, b: number | undefined): string => (b === undefined ? "" : ` (${formatSigned(a - b)})`);
  return (
    <dl className="trade-metrics">
      <div data-active={goal === "value" || undefined}>
        <dt>Value</dt>
        <dd>
          {formatValue(pkg.value)}
          <span className="trade-delta">{delta(pkg.value, out?.value)}</span>
        </dd>
      </div>
      <div data-active={goal === "floor" || undefined}>
        <dt>Floor</dt>
        <dd>
          {quantileText(pkg, pkg.p10)}
          <span className="trade-delta">{delta(pkg.p10, out?.p10)}</span>
        </dd>
      </div>
      <div data-active={goal === "ceiling" || undefined}>
        <dt>Ceiling</dt>
        <dd>
          {quantileText(pkg, pkg.p90)}
          <span className="trade-delta">{delta(pkg.p90, out?.p90)}</span>
        </dd>
      </div>
      <div>
        <dt>Proj. pts</dt>
        <dd>
          {formatValue(pkg.points)}
          <span className="trade-delta">{delta(pkg.points, out?.points)}</span>
        </dd>
      </div>
      <div>
        <dt>Top asset</dt>
        <dd>
          {formatValue(pkg.top)}
          <span className="trade-delta">{out === null ? "" : ` vs ${formatValue(out.top)}`}</span>
        </dd>
      </div>
      <div>
        <dt>Roster</dt>
        <dd>{rosterShort(Math.max(give, 1), pkg.members.length)}</dd>
      </div>
    </dl>
  );
}

function PackageCard({
  entry,
  search,
  goal,
  give,
  onSelect,
  actions,
}: {
  readonly entry: RankedPackage;
  readonly search: Extract<TradeSearch, { status: "ok" }>;
  readonly goal: TradeGoal;
  readonly give: number;
  readonly onSelect: (id: string) => void;
  readonly actions: React.ReactNode;
}): React.JSX.Element {
  const names = entry.pkg.members.map((member) => member.record.display_name).join(" + ");
  return (
    <li className="trade-package chamfer" aria-label={`${names}, rank ${String(entry.rank)}`}>
      <div className="trade-package-head">
        <span className="trade-rank" aria-hidden="true">{`#${String(entry.rank)}`}</span>
        <PackageMembers pkg={entry.pkg} onSelect={onSelect} />
        <div className="trade-package-actions">{actions}</div>
      </div>
      <PackageMetrics pkg={entry.pkg} out={search.outgoingPkg} goal={goal} give={give} />
      <p className="trade-why">{qualifiesSentence(entry, search, goal)}</p>
    </li>
  );
}

function KeptShelf({
  kept,
  search,
  goal,
  give,
  onSelect,
  onRemove,
}: {
  readonly kept: readonly KeptPackage[];
  readonly search: TradeSearch;
  readonly goal: TradeGoal;
  readonly give: number;
  readonly onSelect: (id: string) => void;
  readonly onRemove: (key: string) => void;
}): React.JSX.Element {
  return (
    <div className="trade-kept">
      <h3 className="trade-subhead">{`Kept (${String(kept.length)} of ${String(MAX_KEEP)})`}</h3>
      <ul>
        {kept.map((item) => (
          <li key={item.key} className="trade-package chamfer" data-invalid={item.problems.length > 0 || undefined}>
            <div className="trade-package-head">
              {item.pkg === null ? (
                <p className="trade-members-missing">{`${plural(item.ids.length, "player")} — not all on this board`}</p>
              ) : (
                <PackageMembers pkg={item.pkg} onSelect={onSelect} />
              )}
              <div className="trade-package-actions">
                <button type="button" className="button" onClick={() => { onRemove(item.key); }}>
                  Remove
                </button>
              </div>
            </div>
            {item.pkg !== null && (
              <PackageMetrics pkg={item.pkg} out={search.status === "ok" ? search.outgoingPkg : null} goal={goal} give={give} />
            )}
            {item.problems.length > 0 && (
              <p className="trade-invalid" role="note">
                {`No longer qualifies: ${item.problems.map((problem) => KEPT_PROBLEM_TEXT[problem]).join("; ")}.`}
              </p>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

function ExcludedList({
  excluded,
  belowReplacement,
  onSelect,
}: {
  readonly excluded: readonly Exclusion[];
  readonly belowReplacement: number;
  readonly onSelect: (id: string) => void;
}): React.JSX.Element {
  return (
    <details className="trade-excluded">
      <summary>{`Not targets: ${plural(excluded.length, "player")} with value, plus ${String(belowReplacement)} at or below replacement`}</summary>
      <p className="trade-help">
        Players with positive value who are left out, and why. Status and absence never change a
        value; they only keep a player from leading suggestions on an estimate that does not read
        injury news. A player listed Out for this week only is still a target.
      </p>
      {excluded.length > 0 && (
        <ul className="trade-excluded-list">
          {excluded.map((row) => (
            <li key={row.record.player_id}>
              <PositionTag position={row.record.position} />
              <button type="button" className="player-name" onClick={() => { onSelect(row.record.player_id); }}>
                {row.record.display_name}
              </button>
              <span className="trade-member-value">{formatValue(row.record.ros_expected_vorp)}</span>
              <span className="trade-excluded-reason">{exclusionDetail(row)}</span>
            </li>
          ))}
        </ul>
      )}
    </details>
  );
}

function exclusionDetail(row: Exclusion): string {
  if (row.reason === "long_absence") return `${EXCLUSION_TEXT.long_absence}: ${longAbsenceLabel(row.record).toLowerCase()}`;
  if (row.reason === "roster_status") return `${EXCLUSION_TEXT.roster_status}: ${row.record.current_status ?? EM_DASH}`;
  return EXCLUSION_TEXT[row.reason];
}

function MethodNotes(): React.JSX.Element {
  return (
    <div className="trade-method-body">
      <p>
        <strong>Comparable value first.</strong> Every package&rsquo;s expected value — points
        above the best player nobody rosters, summed over the remaining weeks — must fall within
        your value range of what you give. Expected values add exactly. Raw points are shown for
        context only: they would always favour quarterbacks.
      </p>
      <p>
        <strong>Your preference second.</strong> Within that pool, ROS value ranks by expected
        value, Highest ceiling by the 90th percentile and Highest floor by the 10th. The range is
        always measured in expected value, so switching to ceiling never changes what your
        players are worth.
      </p>
      <p>
        <strong>No filler.</strong> In a 2- or 3-player package each player must carry at least{" "}
        {String(MEMBER_SHARE_MIN * 100)}% of its value, and every target is above replacement. Values
        are assets, not lineup points: two players in two roster spots are not one starter, so
        each package shows its best single asset and the roster spots it needs.
      </p>
      <p>
        <strong>Floors and ceilings of packages are approximate (~).</strong> Percentiles do not
        add. For 2–3 players the tab rebuilds each player&rsquo;s distribution from his five
        published percentiles and expectation, treats players as independent, and combines them
        (ADR-100). Checked against the simulation&rsquo;s own draws it is within about a point on a
        100-point range; its calibration is not claimed.
      </p>
      <p>
        <strong>Not targets:</strong> players at or below replacement, players with a long
        absence, and players with a reserve, inactive, suspended, released or retired roster code.
        Full methodology is in Data.
      </p>
    </div>
  );
}
