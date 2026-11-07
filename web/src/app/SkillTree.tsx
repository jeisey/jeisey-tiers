/**
 * The Skill Tree (ADR-107): a player's positional statistical profile as connected branches of
 * illustrated stat nodes. A lazy chunk — its code, styles and data load only when a reader
 * opens the section (desktop) or chooses its tab (phone).
 *
 * **The metaphor describes observations.** A node is one published statistic: its value, its
 * sample and, when the sample and the cohort allow, its percentile among qualified players at
 * his position. Nothing is spent, unlocked or earned; the connectors show category and reading
 * order, and the lit path to a selected node is a reading path, not progression. There is no
 * overall rating and no branch score.
 *
 * **Shape follows the pane, never shrinks.** Four branch columns where the pane is wide enough
 * (desktop and tablet card), two in between, one on a phone — the branches reflow vertically
 * rather than scaling the desktop tree down. Every node is a button: tap, click, Enter or Space
 * opens its detail inline; the arrow keys move between nodes; hover is never required.
 *
 * **The meter is a coarse aid.** Ten ticks, one per ten percentile points, rounded up
 * (`meterTicks`), tinted by one of five percentile bands (`percentileBand`) — only for a ranked
 * higher/lower reading of this season. The exact percentile and place are always in words.
 *
 * **Comparison (ADR-117)** is a lazy chunk of its own, loaded from inside this one: a ranked
 * node's detail offers it, and only pressing that button loads its code and the one cohort
 * slice it draws.
 */

import {
  Suspense,
  lazy,
  memo,
  startTransition,
  useCallback,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
} from "react";

import "../styles/skilltree.css";

import { useElementWidth } from "../components/useElementWidth";
import type { Position } from "../data/contracts";
import {
  BAND_KEY,
  METER_TICKS,
  buildSkillTreeView,
  nodeName,
  nodeOrder,
  type PercentileBand,
  type SkillReading,
  type SkillTreeView,
} from "../data/skilltree";
import type { SkillTreeSource } from "../data/store";
import { BranchGlyph, CoreEmblem, MetricGlyph } from "./skillTreeGlyphs";

const SkillCompare = lazy(() => import("./SkillCompare"));

const TICKS: readonly number[] = Array.from({ length: METER_TICKS }, (_, index) => index + 1);
const BANDS: readonly PercentileBand[] = [1, 2, 3, 4, 5];

type Load =
  | { readonly status: "loading"; readonly key: string }
  | { readonly status: "ready"; readonly key: string; readonly view: SkillTreeView }
  | { readonly status: "error"; readonly key: string; readonly message: string };

const KIND_TAG: Readonly<Record<string, string>> = {
  volume: "VOL",
  share: "SHARE",
  rate: "RATE",
  context: "CTX",
};

const KIND_WORD: Readonly<Record<string, string>> = {
  volume: "Volume",
  share: "Opportunity share",
  rate: "Efficiency rate",
  context: "Context — no better direction",
};

const NOUNS: Readonly<Partial<Record<Position, string>>> = { QB: "QBs", RB: "RBs", WR: "WRs", TE: "TEs" };

/**
 * Views already built, per source and player: a second look at a player (another tab and back,
 * or the card closed and reopened) draws his tree in its first frame, with no loading state and
 * no second render. Weakly keyed by the source, so a new deploy's store starts empty.
 */
const VIEWS = new WeakMap<SkillTreeSource, Map<string, SkillTreeView>>();

function cachedView(source: SkillTreeSource, key: string): SkillTreeView | undefined {
  return VIEWS.get(source)?.get(key);
}

function rememberView(source: SkillTreeSource, key: string, view: SkillTreeView): void {
  const views = VIEWS.get(source) ?? new Map<string, SkillTreeView>();
  views.set(key, view);
  VIEWS.set(source, views);
}

/**
 * The pane's likely width before it is measured: the window less the sheet's gutters. A phone
 * then lays out one column in its first frame instead of four and then one.
 */
function initialWidth(): number {
  return typeof window === "undefined" ? 720 : Math.max(280, Math.min(720, window.innerWidth - 48));
}

/** Branch columns for a pane this wide. */
export function columnsFor(width: number): 1 | 2 | 4 {
  if (width >= 620) return 4;
  if (width >= 400) return 2;
  return 1;
}

/**
 * The meter, drawn from the reading's one meter field. `fill`: ten ticks, the first `ticks` lit
 * in the band's tint — zero lit is a solid, empty track (a ranked reading at the very bottom),
 * never the dashed track of a reading with no rank. `context`: a marker on a neutral track.
 * `empty`: a dashed track, nothing lit; the state is in words beside it.
 */
function Meter({ node }: { readonly node: SkillReading }): React.JSX.Element {
  if (node.meter === "marker" && node.marker !== null) {
    return (
      <span className="st-meter" data-variant="context" aria-hidden="true">
        {TICKS.map((index) => (
          <span key={index} className="st-seg" />
        ))}
        <span className="st-mark" style={{ left: `${String(Math.min(100, Math.max(0, node.marker)))}%` }} />
      </span>
    );
  }
  return (
    <span
      className="st-meter"
      data-variant={node.meter === "ticks" ? "fill" : "empty"}
      data-ticks={node.meter === "ticks" ? node.ticks : undefined}
      aria-hidden="true"
    >
      {TICKS.map((index) => (
        <span key={index} className="st-seg" data-on={index <= node.ticks ? "true" : undefined} />
      ))}
    </span>
  );
}

/**
 * One node. Memoised with stable callbacks: selecting a node re-renders only the nodes whose
 * selection or tab stop changed, not the whole tree (measured on a throttled phone, ADR-107).
 */
const NodeButton = memo(function NodeButton({
  node,
  selected,
  focusable,
  detailId,
  onSelect,
  register,
}: {
  readonly node: SkillReading;
  readonly selected: boolean;
  readonly focusable: boolean;
  readonly detailId: string;
  readonly onSelect: (id: string) => void;
  readonly register: (id: string, element: HTMLButtonElement | null) => void;
}): React.JSX.Element {
  const { definition } = node;
  return (
    <button
      type="button"
      ref={(element) => {
        register(node.id, element);
      }}
      className="st-node"
      data-state={node.state}
      data-kind={definition.kind}
      data-direction={definition.direction}
      data-empty={node.empty ? "true" : undefined}
      data-band={node.band ?? undefined}
      data-meter={node.meter}
      data-metric={node.id}
      aria-expanded={selected}
      aria-controls={selected ? detailId : undefined}
      aria-label={nodeName(node)}
      tabIndex={focusable ? 0 : -1}
      onClick={() => {
        onSelect(node.id);
      }}
    >
      <span className="st-frame" aria-hidden="true">
        <MetricGlyph metric={node.id} />
      </span>
      <span className="st-node-text" aria-hidden="true">
        <span className="st-node-label">{definition.short_label}</span>
        <span className="st-node-value">
          {node.valueText}
          {node.unitText !== "" && !node.empty && <small>{node.unitText}</small>}
        </span>
        <span className="st-node-standing">{node.standingText}</span>
      </span>
      <span className="st-kind" aria-hidden="true">
        {KIND_TAG[definition.kind] ?? ""}
      </span>
      <Meter node={node} />
    </button>
  );
});

function DetailLine({ node }: { readonly node: SkillReading }): React.JSX.Element {
  return (
    <li
      className="st-detail-more-item"
      data-state={node.state}
      data-band={node.band ?? undefined}
      data-meter={node.meter}
    >
      <span className="st-detail-more-label">{node.definition.label}</span>
      <span className="st-detail-more-value">
        {node.valueText}
        {node.unitText !== "" && !node.empty && <small>{node.unitText}</small>}
      </span>
      <span className="st-detail-more-sample">
        {[node.sampleText, node.standingText].filter((text) => text !== "").join(" · ")}
        {node.meterText !== "" && <span className="visually-hidden"> Meter: {node.meterText}.</span>}
      </span>
      {node.meter !== "none" && <Meter node={node} />}
      <span className="st-detail-more-definition">{node.definition.definition}</span>
    </li>
  );
}

/** What the detail needs to offer a comparison (ADR-117). */
interface CompareSlot {
  readonly source: SkillTreeSource;
  readonly position: Position;
  /** The tree's player key: a comparison's state never outlives it. */
  readonly playerKey: string;
  readonly name: string;
  readonly open: boolean;
  readonly onToggle: () => void;
}

/**
 * The detail's comparison offer. A ranked reading of this season: a button that loads the
 * comparison's code and its one cohort slice. The archive: why there is none. An older build
 * that serves no cohorts: that it is not available. Anything unranked: nothing.
 */
function CompareOffer({ node, slot }: { readonly node: SkillReading; readonly slot: CompareSlot }): React.JSX.Element | null {
  const panelId = useId();
  const noun = NOUNS[slot.position] ?? "players";
  if (node.definition.role === "archive") {
    const testers = node.state === "ranked" && node.cohortSize !== null ? `${String(node.cohortSize)} ` : "";
    return (
      <p className="st-compare-note" data-kind="archive">
        <strong>No comparison is drawn for the archive.</strong> Its rank is among the {testers}historical
        combine testers at his combine position, whose rows this build does not publish; today&rsquo;s{" "}
        {noun} are not that cohort and are never put in its place.
      </p>
    );
  }
  if (node.state !== "ranked" || node.definition.role === "presence") return null;
  if (!slot.source.hasCohorts(slot.position)) {
    return (
      <p className="st-compare-note" data-kind="unavailable">
        Comparison with the whole cohort is not available for this build: it publishes no cohort files.
      </p>
    );
  }
  const count = node.cohortSize === null ? "" : ` ${String(node.cohortSize)}`;
  return (
    <div className="st-compare-offer">
      <button
        type="button"
        className="st-compare-toggle"
        aria-expanded={slot.open}
        aria-controls={slot.open ? panelId : undefined}
        onClick={slot.onToggle}
      >
        {slot.open ? "Hide comparison" : `Compare with all${count} ranked ${noun}`}
      </button>
      {slot.open && (
        <div id={panelId}>
          <Suspense fallback={<p className="st-compare-status">Loading the comparison…</p>}>
            <SkillCompare
              key={`${slot.playerKey}|${node.id}`}
              source={slot.source}
              focal={node}
              position={slot.position}
              name={slot.name}
            />
          </Suspense>
        </div>
      )}
    </div>
  );
}

function Detail({
  node,
  id,
  reasons,
  onClose,
  compare,
}: {
  readonly node: SkillReading;
  readonly id: string;
  readonly reasons: Readonly<Record<string, string>>;
  readonly onClose: () => void;
  readonly compare: CompareSlot;
}): React.JSX.Element {
  const { definition } = node;
  const reasonSentence =
    node.reason !== null && !node.reason.startsWith("tested_as:") ? reasons[node.reason] : undefined;
  return (
    <div
      className="st-detail"
      id={id}
      role="region"
      aria-label={`${definition.label}: details`}
      data-band={node.band ?? undefined}
      data-meter={node.meter}
      data-empty={node.empty ? "true" : undefined}
    >
      <div className="st-detail-head">
        <span className="st-frame" aria-hidden="true">
          <MetricGlyph metric={node.id} />
        </span>
        <div className="st-detail-title">
          <h5>{definition.label}</h5>
          <span className="st-detail-kind">
            {KIND_WORD[definition.kind]}
            {definition.direction === "lower" ? " · lower is better" : ""}
          </span>
        </div>
        <button type="button" className="st-detail-close" onClick={onClose}>
          Close<span className="visually-hidden"> {definition.label} details</span>
        </button>
      </div>
      <p className="st-detail-value">
        <strong>{node.valueText}</strong>
        {node.unitText !== "" && !node.empty && <small>{node.unitText}</small>}
        {node.sampleText !== "" && <span className="st-detail-sample">{node.sampleText}</span>}
      </p>
      <p className="st-detail-standing" data-state={node.state}>
        {node.standingText}
        {reasonSentence !== undefined && <span className="st-detail-reason"> — {reasonSentence}</span>}
        {node.meterText !== "" && <span className="visually-hidden"> Meter: {node.meterText}.</span>}
      </p>
      {node.meter !== "none" && (
        <div className="st-detail-meter">
          <Meter node={node} />
        </div>
      )}
      <CompareOffer node={node} slot={compare} />
      <dl className="st-detail-facts">
        <div>
          <dt>What it is</dt>
          <dd>{definition.definition}</dd>
        </div>
        <div>
          <dt>How to read it</dt>
          <dd>{definition.interpretation}</dd>
        </div>
        <div>
          <dt>Ranked against</dt>
          <dd>{definition.cohort_rule}</dd>
        </div>
        <div>
          <dt>Window</dt>
          <dd>{definition.window}</dd>
        </div>
        <div>
          <dt>Formula</dt>
          <dd>{definition.formula}</dd>
        </div>
        <div>
          <dt>Source</dt>
          <dd>
            {definition.source_label}
            <span className="st-detail-fields"> · {definition.source_fields.join(", ")}</span>
          </dd>
        </div>
        <div>
          <dt>Limitations</dt>
          <dd>{definition.limitations}</dd>
        </div>
      </dl>
      {node.details.length > 0 && (
        <ul className="st-detail-more" aria-label={`More on ${definition.label}`}>
          {node.details.map((detail) => (
            <DetailLine key={detail.id} node={detail} />
          ))}
        </ul>
      )}
    </div>
  );
}

export default function SkillTree({
  source,
  playerId,
  position,
  name,
}: {
  readonly source: SkillTreeSource;
  readonly playerId: string;
  readonly position: Position;
  readonly name: string;
}): React.JSX.Element {
  const rootRef = useRef<HTMLDivElement>(null);
  const width = useElementWidth(rootRef, initialWidth());
  const columns = columnsFor(width);
  const baseId = useId();
  const detailId = `${baseId}-detail`;
  const key = `${playerId}|${position}`;
  const initial = (): Load => {
    const view = cachedView(source, key);
    return view === undefined ? { status: "loading", key } : { status: "ready", key, view };
  };
  const [load, setLoad] = useState<Load>(initial);
  const [selected, setSelected] = useState<string | null>(null);
  const [focusId, setFocusId] = useState<string | null>(null);
  /**
   * The comparison that is open, as `player|metric` (ADR-117), or null. Keyed so that it can
   * never survive a change of player or metric: another node, the same node closed, or another
   * player each leave it closed, and its pins and search start empty when it opens again.
   */
  const [compareKey, setCompareKey] = useState<string | null>(null);
  const buttons = useRef(new Map<string, HTMLButtonElement>());
  const orderRef = useRef<readonly string[]>([]);
  // Stable for the memoised nodes: a tap re-renders only the nodes it changes.
  const select = useCallback((id: string): void => {
    setSelected((current) => (current === id ? null : id));
    setCompareKey(null);
    // The archive plaque is its own tab stop, never the tree's roving one.
    if (orderRef.current.includes(id)) setFocusId(id);
  }, []);
  const register = useCallback((id: string, element: HTMLButtonElement | null): void => {
    if (element === null) buttons.current.delete(id);
    else buttons.current.set(id, element);
  }, []);

  // A new player starts with nothing selected — adjusted during render, as the card's tabs are.
  const [lastKey, setLastKey] = useState(key);
  if (lastKey !== key) {
    setLastKey(key);
    setSelected(null);
    setFocusId(null);
    setCompareKey(null);
    setLoad(initial());
  }

  useEffect(() => {
    if (cachedView(source, key) !== undefined) return;
    let cancelled = false;
    source
      .load(playerId, position)
      .then((loaded) => {
        const view = buildSkillTreeView(loaded, source.meta, position);
        rememberView(source, key, view);
        // A transition: the tap that asked for the tree paints its loading note first, and the
        // tree's own render yields to the browser rather than holding that frame (ADR-107).
        if (!cancelled) {
          startTransition(() => {
            setLoad({ status: "ready", key, view });
          });
        }
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setLoad({ status: "error", key, message: error instanceof Error ? error.message : String(error) });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [source, playerId, position, key]);

  const view = load.status === "ready" && load.key === key ? load.view : null;
  const order = useMemo(() => (view === null ? [] : nodeOrder(view)), [view]);
  useEffect(() => {
    orderRef.current = order;
  }, [order]);
  const nodes = useMemo(() => {
    const map = new Map<string, SkillReading>();
    for (const branch of view?.branches ?? []) for (const node of branch.nodes) map.set(node.id, node);
    if (view?.archive != null) map.set(view.archive.id, view.archive);
    return map;
  }, [view]);
  const reasons = useMemo(() => {
    const meta = source.meta as { reasons?: Record<string, string> } | null;
    return meta?.reasons ?? {};
  }, [source]);

  if (load.status === "error" && load.key === key) {
    return (
      <p className="section-note st-note" data-kind="error">
        The skill tree could not be loaded ({load.message}). Every other part of the card is unaffected.
      </p>
    );
  }
  if (view === null) {
    return (
      <div className="st" ref={rootRef} aria-busy="true">
        <p className="section-note st-note">Loading the skill tree…</p>
      </div>
    );
  }
  if (view.noRecord) {
    return (
      <div className="st" ref={rootRef}>
        <p className="section-note st-note">
          No skill tree is published for {name} in this build: he has no regular-season game through
          the cutoff and no board publishes him.
        </p>
      </div>
    );
  }
  if (view.noAppearances) {
    return (
      <div className="st" ref={rootRef}>
        <p className="section-note st-note" data-kind="empty">
          {name} has not played a regular-season game through the cutoff, so there are no statistics to
          describe yet. Nothing here is zero; it is unwritten.
        </p>
      </div>
    );
  }

  const roving = focusId !== null && order.includes(focusId) ? focusId : (order[0] ?? null);
  const selectedNode = selected === null ? null : (nodes.get(selected) ?? null);
  const selectedBranch =
    selected === null ? null : (view.branches.find((branch) => branch.nodes.some((node) => node.id === selected))?.id ?? null);

  const move = (event: React.KeyboardEvent<HTMLDivElement>): void => {
    const current = roving;
    if (current === null) return;
    const branchIndex = view.branches.findIndex((branch) => branch.nodes.some((node) => node.id === current));
    const branch = view.branches[branchIndex];
    if (branch === undefined) return;
    const nodeIndex = branch.nodes.findIndex((node) => node.id === current);
    let next: string | undefined;
    switch (event.key) {
      case "ArrowDown":
        next = branch.nodes[nodeIndex + 1]?.id ?? view.branches[branchIndex + 1]?.nodes[0]?.id;
        break;
      case "ArrowUp":
        next = branch.nodes[nodeIndex - 1]?.id ?? view.branches[branchIndex - 1]?.nodes.at(-1)?.id;
        break;
      case "ArrowRight": {
        const target = view.branches[branchIndex + 1];
        next = target?.nodes[Math.min(nodeIndex, target.nodes.length - 1)]?.id;
        break;
      }
      case "ArrowLeft": {
        const target = view.branches[branchIndex - 1];
        next = target?.nodes[Math.min(nodeIndex, target.nodes.length - 1)]?.id;
        break;
      }
      case "Home":
        next = order[0];
        break;
      case "End":
        next = order.at(-1);
        break;
      default:
        return;
    }
    event.preventDefault();
    if (next === undefined) return;
    setFocusId(next);
    buttons.current.get(next)?.focus();
  };

  const close = (): void => {
    const id = selected;
    setSelected(null);
    setCompareKey(null);
    if (id !== null) buttons.current.get(id)?.focus();
  };

  const openKey = selected === null ? null : `${key}|${selected}`;
  const detail =
    selectedNode === null ? null : (
      <Detail
        node={selectedNode}
        id={detailId}
        reasons={reasons}
        onClose={close}
        compare={{
          source,
          position,
          playerKey: key,
          name,
          open: openKey !== null && compareKey === openKey,
          onToggle: () => {
            setCompareKey((current) => (current === openKey ? null : openKey));
          },
        }}
      />
    );
  const noun = NOUNS[position] ?? "players";

  return (
    <div className="st" ref={rootRef} data-columns={columns}>
      <div className="st-head">
        <CoreEmblem position={position} />
        <div className="st-head-text">
          <p className="st-window">
            {view.window} · <strong>{view.games}</strong> game{view.games === 1 ? "" : "s"} played
          </p>
          <p className="st-legend">
            {/* A sample: 6 of 10 lit is a percentile from 50.1 to 60, band 40 to under 60. */}
            <span className="st-legend-meter" data-band="3" aria-hidden="true">
              {TICKS.map((index) => (
                <span key={index} data-on={index <= 6 ? "true" : undefined} />
              ))}
            </span>
            Meter = percentile among qualified {noun}: ten ticks, one per 10 points, rounded up (0 lights
            none, 0.1–10 lights one, 90.1–100 all ten); the exact percentile and place are in words. Tint =
            percentile band:{" "}
            <span className="st-band-key">
              {BANDS.map((band) => (
                <span key={band} className="st-band-key-item" data-band={band}>
                  <span className="st-band-swatch" aria-hidden="true" />
                  {BAND_KEY[band]}
                </span>
              ))}
            </span>
            . Context metrics mark a position on a neutral track, not a grade; the archive is untinted. Tags:
            VOL volume · SHARE opportunity · RATE efficiency · CTX context. No overall rating: each node is one
            statistic.
          </p>
        </div>
      </div>
      {view.withheld.length > 0 && (
        <ul className="st-withheld">
          {view.withheld.map((entry) => (
            <li key={entry.source}>
              <strong>{entry.source}:</strong> {entry.sentence}
            </li>
          ))}
        </ul>
      )}
      <div
        className="st-grid"
        role="group"
        aria-label={`${name}'s skill tree: ${String(view.branches.length)} branches. Arrow keys move between statistics.`}
        onKeyDown={move}
      >
        {view.branches.map((branch) => {
          const litTo =
            selectedBranch === branch.id ? branch.nodes.findIndex((node) => node.id === selected) : -1;
          return (
            <section
              key={branch.id}
              className="st-branch"
              data-lit={litTo >= 0 ? "true" : undefined}
              aria-labelledby={`${baseId}-${branch.id}`}
            >
              <h4 className="st-branch-head" id={`${baseId}-${branch.id}`}>
                <span className="st-branch-emblem" aria-hidden="true">
                  <BranchGlyph branch={branch.id} />
                </span>
                {branch.label}
              </h4>
              <ol className="st-nodes">
                {branch.nodes.map((node, index) => (
                  <li key={node.id} className="st-link" data-lit={index <= litTo ? "true" : undefined}>
                    <NodeButton
                      node={node}
                      selected={selected === node.id}
                      focusable={roving === node.id}
                      detailId={detailId}
                      onSelect={select}
                      register={register}
                    />
                    {/* One column: the detail opens under the node that was tapped. */}
                    {columns === 1 && selected === node.id && detail}
                  </li>
                ))}
              </ol>
            </section>
          );
        })}
      </div>
      {columns > 1 && selectedBranch !== null && detail}
      {view.archive !== null && (
        <div className="st-archive">
          <span className="st-archive-label">Archive · historical context, not current speed</span>
          <NodeButton
            node={view.archive}
            selected={selected === view.archive.id}
            focusable
            detailId={detailId}
            onSelect={select}
            register={register}
          />
        </div>
      )}
      {selectedNode !== null && selectedBranch === null && detail}
    </div>
  );
}
