/**
 * One Insights story (ADR-116): a self-contained unit a reader can screenshot as it stands —
 * what it is, who it is about, the reading labelled as a reading, the facts each with what kind
 * of number it is, the chart, what could undermine it, the caveat, where every number came from
 * and which edition said so. Nothing on it is hover-only.
 *
 * A `this_week` story that kickoff or the availability policy has overtaken is withdrawn in
 * place: the notice replaces the call to action, and the story as published stays one tap away.
 */

import { useEffect, useId, useRef, useState } from "react";

import { AvailabilityBadge, PositionTag } from "../../components/primitives";
import {
  BASIS_DESCRIPTIONS,
  BASIS_LABELS,
  FAMILY_LABELS,
  VARIANT_LABELS,
  evidenceByStory,
  evidenceRows,
  formatExact,
  kicker,
  playerContext,
  scoringLabel,
  sourceLabels,
  windowText,
  type InsightEvidence,
  type InsightStory,
  type StoryStanding,
} from "../../data/insights";
import type { InsightFamily } from "../../data/contracts";
import { ChartFigure } from "./ChartFigure";
import { chartTable } from "./chartText";
import { copyText } from "./copy";

/** Story-id prefixes, for naming the findings a player also qualified for. */
const SHORT_FAMILY: Readonly<Record<string, InsightFamily>> = {
  upside: "weekly_upside",
  opening: "opportunity_opening",
  volume: "volume_vs_results",
  streak: "streak_watch",
  role: "role_battle",
  pace: "pace_perspective",
};

export interface StoryCardProps {
  readonly story: InsightStory;
  readonly standing: StoryStanding;
  /** `Week 8 edition` — printed on the source line. */
  readonly edition: string;
  /** A label above the kicker for a linked story (`Linked story`, `Updated for Week 8`). */
  readonly flag?: string | null | undefined;
  /** Open the Evidence on first render (a deep link expands its story). */
  readonly expanded?: boolean | undefined;
  readonly link: string;
  readonly summary: string;
  readonly onSelect: (playerId: string) => void;
  readonly onShare: (story: InsightStory) => void;
  /** The preset's evidence slice, fetched (once) when a reader first opens a story's Evidence. */
  readonly loadEvidence: () => Promise<readonly Record<string, unknown>[]>;
  readonly headingRef?: React.Ref<HTMLHeadingElement> | undefined;
}

export function StoryCard({
  story,
  standing,
  edition,
  flag,
  expanded = false,
  link,
  summary,
  onSelect,
  onShare,
  loadEvidence,
  headingRef,
}: StoryCardProps): React.JSX.Element {
  const id = useId();
  const headingId = `${id}-headline`;
  const evidenceId = `${id}-evidence`;
  const [open, setOpen] = useState(expanded);
  const [copied, setCopied] = useState<{ readonly ok: boolean; readonly what: "link" | "summary" } | null>(null);
  const fallback = useRef<HTMLTextAreaElement>(null);
  const availability = standing.availability;
  const showAvailability =
    availability !== null && availability.short !== null && (story.horizon === "this_week" || availability.severity !== "none");

  const copy = (what: "link" | "summary"): void => {
    void copyText(what === "link" ? link : summary).then((ok) => {
      setCopied({ ok, what });
    });
  };

  const body = (
    <>
      <p className="ins-dek">
        <span className="ins-tag" data-kind="reading">
          Reading
        </span>{" "}
        {story.dek}
      </p>
      <dl className="ins-facts">
        {story.facts.map((fact) => (
          <div key={`${fact.label}:${fact.value}`} className="ins-fact">
            <dt>
              <span className="ins-fact-label">{fact.label}</span>{" "}
              <span className="ins-tag" data-basis={fact.basis} title={`Basis: ${BASIS_DESCRIPTIONS[fact.basis]}`}>
                {BASIS_LABELS[fact.basis]}
                <span className="visually-hidden">{` — ${BASIS_DESCRIPTIONS[fact.basis]}`}</span>
              </span>
            </dt>
            <dd>{fact.value}</dd>
          </div>
        ))}
      </dl>
      <ChartFigure story={story} />
      {story.counterpoint !== null && (
        <p className="ins-counter">
          <strong>What could undermine it</strong> {story.counterpoint}
        </p>
      )}
    </>
  );

  return (
    <article
      className="ins-story"
      id={`story-${story.story_id}`}
      data-story={story.story_id}
      data-family={story.family}
      data-withdrawn={standing.withdrawn || undefined}
      aria-labelledby={headingId}
    >
      {flag !== null && flag !== undefined && <p className="ins-flag">{flag}</p>}
      <p className="ins-kicker">
        <span>{kicker(story)}</span>
        <span className="ins-variant">{` · ${VARIANT_LABELS[story.variant]}`}</span>
        {story.nature === "thesis" && <span className="ins-nature"> · Thesis</span>}
      </p>
      <h4 className="ins-headline" id={headingId} ref={headingRef} tabIndex={-1}>
        {story.headline}
      </h4>
      <p className="ins-who">
        <button
          type="button"
          className="ins-player"
          aria-haspopup="dialog"
          onClick={() => {
            onSelect(story.player_id);
          }}
        >
          {story.display_name}
        </button>{" "}
        <PositionTag position={story.position} />{" "}
        <span className="ins-context">{playerContext(story).slice(1).join(" · ")}</span>
        {showAvailability && (
          <>
            {" "}
            <AvailabilityBadge availability={availability} />
          </>
        )}
      </p>
      {showAvailability && availability !== null && !standing.withdrawn && availability.severity !== "none" && (
        <p className="ins-availability" data-severity={availability.severity}>
          {availability.headline}
        </p>
      )}
      {standing.withdrawn ? (
        <>
          <p className="ins-withdrawn" role="note">
            <strong>Withdrawn.</strong> {standing.reason}
          </p>
          <details className="ins-withdrawn-body">
            <summary>The story as published</summary>
            {body}
          </details>
        </>
      ) : (
        body
      )}
      <p className="ins-caveat">
        <strong>Caveat</strong> {story.caveat}
      </p>
      <p className="ins-source">
        <span>{windowText(story)}</span>
        <span>{scoringLabel(story)}</span>
        <span>{`${edition} edition (${story.edition})`}</span>
        <span>{sourceLabels(story).join(" · ")}</span>
        <span className="ins-brand">Jeisey Tiers</span>
      </p>
      <div className="ins-actions">
        <button
          type="button"
          className="button"
          aria-expanded={open}
          aria-controls={evidenceId}
          onClick={() => {
            setOpen((value) => !value);
          }}
        >
          {open ? "Hide evidence" : "Evidence"}
        </button>
        <button
          type="button"
          className="button"
          aria-haspopup="dialog"
          onClick={() => {
            onShare(story);
          }}
        >
          Share
        </button>
        <button
          type="button"
          className="button"
          onClick={() => {
            copy("link");
          }}
        >
          Copy link
        </button>
        <button
          type="button"
          className="button"
          onClick={() => {
            copy("summary");
          }}
        >
          Copy summary
        </button>
      </div>
      <p className="ins-copy-status" role="status" aria-live="polite">
        {copied === null
          ? ""
          : copied.ok
            ? copied.what === "link"
              ? "Link copied."
              : "Summary copied."
            : `Could not copy the ${copied.what}. Select it below and copy it.`}
      </p>
      {copied !== null && !copied.ok && (
        <label className="ins-copy-fallback">
          <span className="visually-hidden">{copied.what === "link" ? "Story link" : "Story summary"}</span>
          <textarea
            ref={fallback}
            readOnly
            rows={copied.what === "link" ? 2 : 8}
            value={copied.what === "link" ? link : summary}
            onFocus={(event) => {
              event.currentTarget.select();
            }}
          />
        </label>
      )}
      <div className="ins-evidence" id={evidenceId} hidden={!open}>
        {open && <Evidence story={story} load={loadEvidence} />}
      </div>
    </article>
  );
}

/** Parsed evidence slices, by the decoded rows they came from: one parse per preset's slice. */
const parsedEvidence = new WeakMap<readonly Record<string, unknown>[], ReadonlyMap<string, InsightEvidence>>();

function evidenceFor(rows: readonly Record<string, unknown>[], storyId: string): InsightEvidence | null {
  let byStory = parsedEvidence.get(rows);
  if (byStory === undefined) {
    byStory = evidenceByStory(rows);
    parsedEvidence.set(rows, byStory);
  }
  return byStory.get(storyId) ?? null;
}

type EvidenceState =
  | { readonly status: "loading" }
  | { readonly status: "ready"; readonly evidence: InsightEvidence | null }
  | { readonly status: "failed"; readonly message: string };

/**
 * A story's Evidence: the chart's exact values at once (they are in the feed), then — from the
 * preset's evidence slice, fetched the first time any story is expanded — every predicate it
 * passed with its value and threshold, the named values behind it, and its sibling findings.
 */
function Evidence({
  story,
  load,
}: {
  readonly story: InsightStory;
  readonly load: () => Promise<readonly Record<string, unknown>[]>;
}): React.JSX.Element {
  const [attempt, setAttempt] = useState(0);
  const [state, setState] = useState<EvidenceState & { readonly attempt: number }>({ status: "loading", attempt: 0 });
  useEffect(() => {
    let live = true;
    load()
      .then((rows) => {
        if (live) setState({ status: "ready", evidence: evidenceFor(rows, story.story_id), attempt });
      })
      .catch((error: unknown) => {
        if (live) setState({ status: "failed", message: error instanceof Error ? error.message : String(error), attempt });
      });
    return () => {
      live = false;
    };
  }, [load, story.story_id, attempt]);
  const current: EvidenceState = state.attempt === attempt ? state : { status: "loading" };
  const table = chartTable(story);
  const times = story.source_times;
  const timeRows: (readonly [string, string])[] = [];
  if (times.espn_observed_at_utc !== undefined) timeRows.push(["ESPN roster share observed", formatExact(times.espn_observed_at_utc)]);
  if (times.lines_retrieved_at_utc !== undefined) timeRows.push(["Betting lines retrieved", formatExact(times.lines_retrieved_at_utc)]);
  if (times.injury_report_final !== undefined) timeRows.push(["Official injury report final", formatExact(times.injury_report_final)]);
  return (
    <>
      <ExactValues table={table} />
      {current.status === "loading" && (
        <p className="ins-evidence-wait" role="status">
          Loading the evidence…
        </p>
      )}
      {current.status === "failed" && (
        <p className="ins-evidence-wait" role="alert">
          {`The evidence could not be loaded (${current.message}). `}
          <button
            type="button"
            className="button-link"
            onClick={() => {
              setAttempt((value) => value + 1);
            }}
          >
            Try again
          </button>
        </p>
      )}
      {current.status === "ready" && current.evidence === null && (
        <p className="ins-evidence-wait" role="status">
          This build published no evidence row for this story.
        </p>
      )}
      {current.status === "ready" && current.evidence !== null && (
        <Qualification evidence={current.evidence} timeRows={timeRows} />
      )}
    </>
  );
}

function ExactValues({ table }: { readonly table: ReturnType<typeof chartTable> }): React.JSX.Element {
  return (
    <>
      <h5 className="ins-evidence-head">Exact values</h5>
      <div className="table-scroll" tabIndex={0} role="region" aria-label={`Exact values: ${table.caption}`}>
        <table className="ins-table">
          <caption>{table.caption}</caption>
          <thead>
            <tr>
              {table.columns.map((column, index) => (
                <th key={`${String(index)}:${column}`} scope="col">
                  {column}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {table.rows.map((row, index) => (
              <tr key={String(index)}>
                {row.map((cell, cellIndex) =>
                  cellIndex === 0 ? (
                    <th key={String(cellIndex)} scope="row">
                      {cell}
                    </th>
                  ) : (
                    <td key={String(cellIndex)}>{cell}</td>
                  ),
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

function Qualification({
  evidence,
  timeRows,
}: {
  readonly evidence: InsightEvidence;
  readonly timeRows: readonly (readonly [string, string])[];
}): React.JSX.Element {
  const rows = evidenceRows(evidence.evidence);
  return (
    <>
      <h5 className="ins-evidence-head">Why it qualified</h5>
      <div className="table-scroll" tabIndex={0} role="region" aria-label="Qualification">
        <table className="ins-table">
          <caption className="visually-hidden">Every rule the story passed, in the order it is checked</caption>
          <thead>
            <tr>
              <th scope="col">Rule</th>
              <th scope="col">Value</th>
              <th scope="col">Threshold</th>
            </tr>
          </thead>
          <tbody>
            {evidence.qualification.map((predicate) => (
              <tr key={predicate.rule}>
                <th scope="row">
                  {predicate.label}
                  <span className="ins-rule-id">{predicate.rule}</span>
                </th>
                <td>{formatExact(predicate.value)}</td>
                <td>{formatExact(predicate.threshold)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {rows.length + timeRows.length > 0 && (
        <dl className="ins-exact">
          {[...rows, ...timeRows].map(([label, value]) => (
            <div key={label}>
              <dt>{label}</dt>
              <dd>{value}</dd>
            </div>
          ))}
        </dl>
      )}
      {evidence.also_qualifies.length > 0 && (
        <p className="ins-also">
          <strong>Also qualified</strong>{" "}
          {evidence.also_qualifies
            .map((other) => {
              const family = SHORT_FAMILY[other.split("-", 1)[0] ?? ""];
              return family === undefined ? other : `${FAMILY_LABELS[family]} (${other})`;
            })
            .join(", ")}
          . One story per player: the first in the editorial order is the one published.
        </p>
      )}
    </>
  );
}
