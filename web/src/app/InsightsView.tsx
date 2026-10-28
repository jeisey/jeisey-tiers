/**
 * The Insights tab (ADR-116): a compact editorial feed of the build's findings, in season only.
 *
 * Every story is the artifact's — written at build time from fixed rules over the build's
 * published evidence. The page decides only what a filter shows and in what order, and one
 * thing at the reader's clock: a `this_week` story stops being a start idea at kickoff, or when
 * the availability policy (ADR-101) would refuse him, and says so in place.
 *
 * The URL is the state: the family filter (`ins`), the ESPN ceiling the upside family is read
 * under (`ceil`), a linked story and the edition it was shared from (`story`, `ed`) and the
 * share view (`share`). A link from an older edition never silently shows a newer finding:
 * the page names both editions and either shows the same story's current version, labelled as
 * updated, or says it is no longer in the edition. Old editions are not kept.
 *
 * Loaded with its stylesheet only when the tab is opened; the share view is a further chunk.
 */

import "../styles/insights.css";

import { Suspense, lazy, useCallback, useEffect, useMemo, useRef, useState } from "react";

import { PlayerPickerDialog } from "../components/PlayerPickerDialog";
import { useClock } from "./insights/useClock";
import { usePrefersReducedMotion } from "../components/useElementWidth";
import type { InsightsSource } from "../data/store";
import {
  FILTER_LABELS,
  editionAge,
  editionLabel,
  editionLine,
  familyStates,
  insightsState,
  parseInsightStories,
  playerContext,
  scoringLabel,
  selectFeed,
  sourceLabels,
  storyLink,
  storyReport,
  storyStanding,
  storySummary,
  unavailableFamilies,
  windowText,
  type InsightStory,
  type StoryStanding,
} from "../data/insights";
import type { InsightsMetadata } from "../data/contracts";
import { searchTermFor, type SearchEntry } from "../data/playerSearch";
import type { InSeasonBundle } from "../data/ros";
import {
  INSIGHT_CEILINGS,
  INSIGHT_FILTERS,
  POSITION_LABELS,
  SCORING_LABELS,
  type AppState,
  type InsightCeiling,
  type InsightFilter,
} from "../data/state";
import { StoryCard } from "./insights/StoryCard";

const ShareView = lazy(() => import("./insights/ShareView").then((module) => ({ default: module.ShareView })));

export interface InsightsViewProps {
  readonly bundle: InSeasonBundle;
  readonly source: InsightsSource;
  readonly state: AppState;
  readonly onChange: (next: Partial<AppState>) => void;
  readonly onSelect: (playerId: string) => void;
  /** Tests only: a fixed clock. Production ticks every 30 seconds (`useClock`). */
  readonly now?: Date | undefined;
}

export function InsightsView({ bundle, source, state, onChange, onSelect, now }: InsightsViewProps): React.JSX.Element {
  const clock = useClock(now);
  const status = useMemo(
    () =>
      insightsState({
        published: source.published,
        compatible: source.compatible,
        meta: source.meta,
        fullMeta: source.fullMeta,
      }),
    [source.published, source.compatible, source.meta, source.fullMeta],
  );
  const head = (action: React.ReactNode): React.JSX.Element => (
    <div className="ins-head">
      <div className="ins-title">
        <h2 id="insights-heading">Insights</h2>
        {action}
      </div>
      {status.kind === "published" || status.kind === "withheld" ? (
        <EditionMeta meta={status.meta} clock={clock} bundle={bundle} scoring={SCORING_LABELS[state.scoring]} />
      ) : (
        <p className="ins-note">{LEAGUE_SIZE_NOTE}</p>
      )}
    </div>
  );
  return (
    <section className="section insights" aria-labelledby="insights-heading">
      {status.kind === "published" ? (
        <Feed
          meta={status.meta}
          rows={source.rows}
          loadEvidence={source.loadEvidence}
          bundle={bundle}
          state={state}
          clock={clock}
          onChange={onChange}
          onSelect={onSelect}
          head={head}
        />
      ) : (
        <>
          {head(null)}
          <div className="notice ins-state" data-severity={status.kind === "incompatible" ? "warning" : "info"} data-state={status.kind} role="note">
            <strong>{status.kind === "withheld" ? "No Insights this week." : "Insights are not available."}</strong>{" "}
            {status.reason}
          </div>
        </>
      )}
    </section>
  );
}

/** Stories read no replacement level or league depth, so the Teams setting has no effect. */
const LEAGUE_SIZE_NOTE = "Same in every league size: the Teams setting changes nothing here.";

function EditionMeta({
  meta,
  clock,
  bundle,
  scoring,
}: {
  readonly meta: InsightsMetadata;
  readonly clock: number;
  readonly bundle: InSeasonBundle;
  readonly scoring: string;
}): React.JSX.Element {
  const age = editionAge(meta.generated_at_utc, clock);
  const behind = meta.through_week < bundle.throughWeek;
  return (
    <>
      <p className="ins-meta">
        <span>{editionLine(meta)}</span>
        {age !== null && (
          <span data-stale={age.stale || undefined}>{age.stale ? `${age.text} — stale` : age.text}</span>
        )}
        <span>{`${scoring} scoring`}</span>
        {/* Folded into the edition line so the first story sits higher on a phone. */}
        <span className="ins-league-note">{LEAGUE_SIZE_NOTE}</span>
      </p>
      {behind && (
        <p className="ins-meta-warn">
          {`This edition runs through week ${String(meta.through_week)}; the rest of the site is through week ${String(bundle.throughWeek)}.`}
        </p>
      )}
    </>
  );
}

interface ChipOption<T extends string | number> {
  readonly value: T;
  readonly label: string;
  readonly count?: number;
  readonly description?: string;
}

/** A radio group as a row of chips: one tab stop, arrows move, 44px targets on touch. */
function ChipGroup<T extends string | number>({
  label,
  name,
  value,
  options,
  onChange,
  className,
}: {
  readonly label: string;
  readonly name: string;
  readonly value: T;
  readonly options: readonly ChipOption<T>[];
  readonly onChange: (value: T) => void;
  readonly className?: string;
}): React.JSX.Element {
  const labelId = `${name}-label`;
  const group = useRef<HTMLDivElement>(null);
  return (
    <div className={className === undefined ? "ins-chips" : `ins-chips ${className}`}>
      <span className="control-label" id={labelId}>
        {label}
      </span>
      <div className="ins-chip-row" role="radiogroup" aria-labelledby={labelId} ref={group}>
        {options.map((option) => (
          <button
            key={String(option.value)}
            type="button"
            role="radio"
            className="ins-chip"
            aria-checked={option.value === value}
            aria-label={option.description}
            tabIndex={option.value === value ? 0 : -1}
            onKeyDown={(event) => {
              const step =
                event.key === "ArrowRight" || event.key === "ArrowDown" ? 1 : event.key === "ArrowLeft" || event.key === "ArrowUp" ? -1 : 0;
              if (step === 0) return;
              event.preventDefault();
              const index = options.findIndex((candidate) => candidate.value === value);
              const next = options[(index + step + options.length) % options.length];
              if (next === undefined) return;
              onChange(next.value);
              requestAnimationFrame(() => {
                group.current?.querySelector<HTMLButtonElement>('[aria-checked="true"]')?.focus();
              });
            }}
            onClick={() => {
              onChange(option.value);
            }}
          >
            {option.label}
            {option.count !== undefined && <span className="ins-chip-count">{option.count}</span>}
          </button>
        ))}
      </div>
    </div>
  );
}

const PRESET_VALUE = { STD: "std", HALF: "half", PPR: "ppr" } as const;

function Feed({
  meta,
  rows,
  loadEvidence,
  bundle,
  state,
  clock,
  onChange,
  onSelect,
  head,
}: {
  /** The tab's heading block, with an action beside the title. */
  readonly head: (action: React.ReactNode) => React.JSX.Element;
  readonly meta: InsightsMetadata;
  readonly rows: readonly Record<string, unknown>[];
  readonly loadEvidence: InsightsSource["loadEvidence"];
  readonly bundle: InSeasonBundle;
  readonly state: AppState;
  readonly clock: number;
  readonly onChange: (next: Partial<AppState>) => void;
  readonly onSelect: (playerId: string) => void;
}): React.JSX.Element {
  const parsed = useMemo(() => parseInsightStories(rows), [rows]);
  // Only the reader's own preset: a slice for another preset never reaches this page.
  const stories = parsed.stories;
  const standings = useMemo(() => {
    const out = new Map<string, StoryStanding>();
    for (const story of stories) {
      const availability = bundle.availabilityWithReport(story.player_id, storyReport(story));
      out.set(story.story_id, storyStanding(story, clock, availability));
    }
    return out;
  }, [stories, bundle, clock]);

  const editionName = editionLabel(meta.edition);
  const linkedId = state.story;
  const linked = linkedId === "" ? null : (stories.find((story) => story.story_id === linkedId) ?? null);
  const mismatch = linkedId !== "" && state.ed !== "" && state.ed !== meta.edition;
  const feed = useMemo(
    () =>
      selectFeed(stories, {
        ins: state.ins,
        ceil: state.ceil,
        search: state.search,
        position: state.position,
        familyOrder: meta.selection.family_order,
      }),
    [stories, state.ins, state.ceil, state.search, state.position, meta.selection.family_order],
  );
  const inFeed = linked !== null && [...feed.lead, ...feed.more].some((story) => story.story_id === linked.story_id);
  const upsidePresent = stories.some((story) => story.family === "weekly_upside");
  const showCeiling = upsidePresent && (state.ins === "all" || state.ins === "week");
  const unavailable = unavailableFamilies(meta);

  const origin = typeof window === "undefined" ? "" : window.location.origin;
  const base = import.meta.env.BASE_URL;
  const linkFor = useCallback((story: InsightStory) => storyLink(origin, base, story), [origin, base]);

  // A deep link scrolls to its story and focuses its headline — once per link, and never while
  // the share view (which has focus) is open.
  const reduced = usePrefersReducedMotion();
  const focused = useRef<string | null>(null);
  useEffect(() => {
    if (linkedId === "" || state.share !== "") return;
    const key = `${linkedId}|${state.ed}`;
    if (focused.current === key) return;
    focused.current = key;
    // The edition notice, when there is one, is what a reader must see first; then the story.
    const notice = document.querySelector<HTMLElement>(".ins-link-notice");
    const card = document.getElementById(`story-${linkedId}`);
    const target = notice ?? card;
    if (target !== null && typeof target.scrollIntoView === "function") {
      target.scrollIntoView({ block: "start", behavior: reduced ? "auto" : "smooth" });
    }
    const heading = card?.querySelector<HTMLElement>(".ins-headline") ?? notice;
    heading?.focus({ preventScroll: true });
  }, [linkedId, state.ed, state.share, reduced]);

  const share = useCallback(
    (story: InsightStory) => {
      // Opening the share view from a card is not a deep link: focus stays with the dialog,
      // and goes back to this card's Share button when it closes.
      focused.current = `${story.story_id}|${story.edition}`;
      onChange({ story: story.story_id, ed: story.edition, share: "land" });
    },
    [onChange],
  );

  const [picking, setPicking] = useState(false);
  const pool = useMemo<readonly SearchEntry[]>(() => {
    const byPlayer = new Map<string, { story: InsightStory; count: number }>();
    for (const story of stories) {
      const entry = byPlayer.get(story.player_id);
      if (entry === undefined) byPlayer.set(story.player_id, { story, count: 1 });
      else entry.count += 1;
    }
    return [...byPlayer.values()].map(({ story, count }) => ({
      id: story.player_id,
      name: story.display_name,
      position: story.position,
      team: story.team,
      availability: bundle.availabilityFor(story.player_id),
      meta: `${story.team ?? "FA"} · ${String(count)} ${count === 1 ? "story" : "stories"}`,
    }));
  }, [stories, bundle]);

  const card = (story: InsightStory, flag: string | null): React.JSX.Element => {
    const standing = standings.get(story.story_id) ?? { withdrawn: false, reason: null, availability: null };
    const link = linkFor(story);
    return (
      <StoryCard
        key={story.story_id}
        story={story}
        standing={standing}
        edition={editionName}
        flag={flag}
        link={link}
        summary={storySummary(story, link, standing)}
        onSelect={onSelect}
        onShare={share}
        loadEvidence={loadEvidence}
      />
    );
  };

  const linkedFlag = linked === null ? null : mismatch ? `Updated for ${editionName}` : "Linked story";
  const flagFor = (story: InsightStory): string | null => (story.story_id === linkedId ? linkedFlag : null);
  const shown = feed.lead.length + feed.more.length;
  const filtersActive = state.ins !== "all" || state.ceil !== 50 || state.search !== "" || state.position !== "all";
  const clearLink = (): void => {
    onChange({ story: "", ed: "", share: "" });
  };

  const shareStory = state.share === "" ? null : linked;
  const shareStanding = shareStory === null ? null : (standings.get(shareStory.story_id) ?? null);

  return (
    <>
      {head(
        stories.length === 0 ? null : (
          <button
            type="button"
            className="button ins-find"
            aria-haspopup="dialog"
            aria-label="Find a player's stories"
            onClick={() => {
              setPicking(true);
            }}
          >
            Find a player
          </button>
        ),
      )}
      {parsed.rejected > 0 && (
        <p className="ins-meta-warn" role="note">
          {`${String(parsed.rejected)} ${parsed.rejected === 1 ? "story" : "stories"} in this build could not be read by this page and ${parsed.rejected === 1 ? "is" : "are"} not shown.`}
        </p>
      )}

      {linkedId !== "" && (mismatch || linked === null) && (
        <div className="notice ins-link-notice" data-severity="info" role="note" tabIndex={-1}>
          {mismatch ? (
            <p>
              <strong>{`This link is from the ${editionLabel(state.ed)} edition; the current edition is ${editionName}.`}</strong>{" "}
              {linked === null
                ? "This story is no longer in the current edition."
                : `The same story as it stands in the ${editionName} edition is shown, marked “Updated for ${editionName}”.`}{" "}
              Older editions are not kept, so a link cannot show a story as it was.
            </p>
          ) : (
            <p>
              <strong>This story is not available.</strong>{" "}
              {`No story “${linkedId}” is in the ${editionName} edition’s ${SCORING_LABELS[state.scoring]} stories.`}
            </p>
          )}
          <p>
            <button type="button" className="button-link" onClick={clearLink}>
              {linked === null ? "Dismiss" : "Show the feed without the link"}
            </button>
          </p>
        </div>
      )}

      {stories.length === 0 ? (
        <EmptyEdition meta={meta} editionName={editionName} />
      ) : (
        <>
          <div className="ins-controls">
            <ChipGroup<InsightFilter>
              name="insights-filter"
              label="Show"
              value={state.ins}
              className="ins-filter"
              options={INSIGHT_FILTERS.map((filter) => ({
                value: filter,
                label: FILTER_LABELS[filter],
                count: feed.counts[filter],
                description: `${FILTER_LABELS[filter]}, ${String(feed.counts[filter])} ${feed.counts[filter] === 1 ? "story" : "stories"}`,
              }))}
              onChange={(ins) => {
                onChange({ ins });
              }}
            />
            {showCeiling && (
              <>
                <ChipGroup<InsightCeiling>
                  name="insights-ceiling"
                  label="Upside · ESPN rostered below"
                  value={state.ceil}
                  className="ins-ceiling"
                  options={INSIGHT_CEILINGS.map((ceiling) => ({
                    value: ceiling,
                    label: `${String(ceiling)}%`,
                    description: `Rostered in fewer than ${String(ceiling)}% of ESPN leagues`,
                  }))}
                  onChange={(ceil) => {
                    onChange({ ceil });
                  }}
                />
                <p className="ins-ceiling-note">
                  ESPN leagues, not yours; an unknown share is not 0%.
                </p>
              </>
            )}
          </div>

          {(state.search !== "" || state.position !== "all") && (
            <div className="active-search ins-active">
              <p className="active-search-text">
                <span className="active-search-label">Showing</span>{" "}
                {state.search !== "" && <strong>{`stories matching “${state.search}”`}</strong>}
                {state.search !== "" && state.position !== "all" && " · "}
                {state.position !== "all" && <strong>{`${POSITION_LABELS[state.position]} only (Position setting)`}</strong>}
              </p>
              <span className="active-search-actions">
                {state.search !== "" && (
                  <button
                    type="button"
                    className="button-link"
                    onClick={() => {
                      onChange({ search: "" });
                    }}
                  >
                    Clear search
                  </button>
                )}
                {state.position !== "all" && (
                  <button
                    type="button"
                    className="button-link"
                    onClick={() => {
                      onChange({ position: "all" });
                    }}
                  >
                    All positions
                  </button>
                )}
              </span>
            </div>
          )}

          {unavailable.length > 0 && (
            <div className="notice ins-degraded" data-severity="warning" role="note">
              <strong>Not built this week:</strong>{" "}
              {unavailable.map((entry, index) => (
                <span key={entry.family}>
                  {index > 0 && "; "}
                  {`${entry.label} — ${entry.reason.replace(/\.$/, "")}`}
                </span>
              ))}
              .
            </div>
          )}

          {linked !== null && !inFeed && (
            <section className="ins-group" aria-labelledby="ins-linked-heading">
              <h3 id="ins-linked-heading">Linked story</h3>
              {filtersActive && <p className="ins-group-note">Shown although the current settings would hide it.</p>}
              {card(linked, linkedFlag)}
            </section>
          )}

          {shown === 0 ? (
            <div className="notice ins-empty" data-severity="info" role="note">
              <strong>No story matches these settings.</strong>{" "}
              {feed.hiddenByCeiling > 0
                ? `${String(feed.hiddenByCeiling)} upside ${feed.hiddenByCeiling === 1 ? "story is" : "stories are"} above the ESPN ${String(state.ceil)}% ceiling. `
                : ""}
              {state.ins !== "all" && unavailable.some((entry) => familyForFilter(state.ins) === entry.family)
                ? "That family was not built this week (above). "
                : ""}
              <button
                type="button"
                className="button-link"
                onClick={() => {
                  onChange({ ins: "all", ceil: 50, search: "", position: "all" });
                }}
              >
                Show every story
              </button>
            </div>
          ) : (
            <>
              {feed.lead.length > 0 && (
                <section className="ins-group" aria-labelledby="ins-lead-heading">
                  <h3 id="ins-lead-heading">{state.ins === "all" ? "Lead stories" : `Lead stories · ${FILTER_LABELS[state.ins]}`}</h3>
                  <div className="ins-list">{feed.lead.map((story) => card(story, flagFor(story)))}</div>
                </section>
              )}
              {feed.more.length > 0 && (
                <section className="ins-group" aria-labelledby="ins-more-heading">
                  <h3 id="ins-more-heading">More findings</h3>
                  <p className="ins-group-note">Every other story that met its rule, by family.</p>
                  <div className="ins-list">{feed.more.map((story) => card(story, flagFor(story)))}</div>
                </section>
              )}
            </>
          )}
        </>
      )}

      <About meta={meta} />

      {picking && (
        <PlayerPickerDialog
          title="Find a player's stories"
          label="Search the players these stories are about"
          help="Choose a player to show only the stories about him, or press Enter to show every match."
          pool={pool}
          poolName="this edition's stories"
          initialQuery={state.search}
          onPick={(entry) => {
            onChange({ search: searchTermFor(entry) });
            setPicking(false);
          }}
          onApply={(query) => {
            onChange({ search: query.slice(0, 64) });
            setPicking(false);
          }}
          onClose={() => {
            setPicking(false);
          }}
        />
      )}

      {shareStory !== null && state.share !== "" && (
        <Suspense fallback={null}>
          <ShareView
            story={shareStory}
            layout={state.share}
            input={{
              // A start idea that stands with a designation carries it on the card too.
              context:
                shareStory.horizon === "this_week" &&
                shareStanding?.withdrawn !== true &&
                shareStanding?.availability != null &&
                shareStanding.availability.severity !== "none"
                  ? [...playerContext(shareStory), shareStanding.availability.headline]
                  : playerContext(shareStory),
              withdrawn: shareStanding?.withdrawn === true ? shareStanding.reason : null,
              edition: editionLine(meta),
              window: windowText(shareStory),
              scoring: scoringLabel(shareStory),
              sources: sourceLabels(shareStory),
            }}
            link={linkFor(shareStory)}
            summary={storySummary(shareStory, linkFor(shareStory), shareStanding ?? undefined)}
            onLayout={(layout) => {
              onChange({ share: layout });
            }}
            onClose={() => {
              onChange({ share: "" });
            }}
          />
        </Suspense>
      )}
    </>
  );
}

function familyForFilter(filter: InsightFilter): string | null {
  switch (filter) {
    case "week":
      return "weekly_upside";
    case "disappoint":
      return "volume_vs_results";
    case "opening":
      return "opportunity_opening";
    case "roles":
      return "role_battle";
    case "streaks":
      return "streak_watch";
    case "pace":
      return "pace_perspective";
    default:
      return null;
  }
}

/** A published edition in which no story met its rule: each family, and why. */
function EmptyEdition({ meta, editionName }: { readonly meta: InsightsMetadata; readonly editionName: string }): React.JSX.Element {
  const states = familyStates(meta);
  return (
    <div className="notice ins-state" data-severity="info" data-state="empty" role="note">
      <strong>{`No story qualified in the ${editionName} edition.`}</strong>{" "}
      Every story is a fixed rule over the week&rsquo;s evidence, and this week none was met.
      {states.length > 0 && (
        <ul className="ins-family-states">
          {states.map((entry) => (
            <li key={entry.family}>
              <strong>{entry.label}</strong>{" "}
              {entry.status.status === "unavailable"
                ? `— not built: ${entry.status.reason ?? "its evidence was unavailable"}`
                : entry.status.status === "empty"
                  ? `— ${entry.status.reason ?? "no player met its rule"}`
                  : "— published"}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** How the stories are chosen and what they never claim, from the build's own account. */
function About({ meta }: { readonly meta: InsightsMetadata }): React.JSX.Element {
  const definitions = Object.entries(meta.definitions);
  return (
    <details className="notice disclosure ins-about">
      <summary>How these stories are chosen</summary>
      <p>
        {`Each story is a fixed rule (${meta.rule_version}) over the build's published evidence — observed nflverse statistics, the weekly start/sit model's published distribution and ESPN's public roster share. The lead is chosen by editorial priority and variety (${meta.selection_rule_version}), never by a score: at most ${String(meta.selection.team_cap)} lead stories per team, and one story per player.`}
      </p>
      <p>
        Stories describe completed weeks and this week&rsquo;s published model distribution; none is a forecast of a
        result. Tags on every fact say what kind of number it is: <strong>Observed</strong> (an nflverse statistic),{" "}
        <strong>Model</strong> (a published model output) or <strong>ESPN</strong> (ESPN&rsquo;s public roster share). The
        &ldquo;Reading&rdquo; is the story&rsquo;s editorial interpretation of those numbers.
      </p>
      {definitions.length > 0 && (
        <dl className="ins-definitions">
          {definitions.map(([key, text]) => (
            <div key={key}>
              <dt>{key.replace(/_/g, " ")}</dt>
              <dd>{text}</dd>
            </div>
          ))}
        </dl>
      )}
      {meta.limitations.length > 0 && (
        <>
          <h3 className="ins-about-head">Limitations</h3>
          <ul>
            {meta.limitations.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        </>
      )}
      {meta.unsupported.length > 0 && (
        <>
          <h3 className="ins-about-head">Claims these stories never make</h3>
          <ul>
            {meta.unsupported.map((entry) => (
              <li key={entry.claim}>
                <strong>{entry.claim}</strong> — {entry.reason}
              </li>
            ))}
          </ul>
        </>
      )}
      <p className="muted">{`Editions are rebuilt with each completed week; older editions are not kept. ${PRESET_NOTE}`}</p>
    </details>
  );
}

const PRESET_NOTE = `Scoring changes which stories qualify and their numbers; a story marked “Same in every scoring” is identical in all three (${Object.keys(PRESET_VALUE).join(", ")}).`;
