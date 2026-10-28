/**
 * What the page has loaded, what it needs next, and the indexes built from it (ADR-098).
 *
 * The browser used to download every artifact before drawing anything. Now it reads the
 * manifest and fetches, in parallel, only the served files the open mode, view, block and card
 * need — `requiredKeys` is that rule, in one place, and the dependency map in
 * `docs/ARCHITECTURE.md` section 14 is its prose.
 *
 * The indexes the views have always read — `ArtifactIndex` and `InSeasonBundle` — are built
 * from whatever is loaded, so no view learned a new data API. The one new distinction they had
 * to learn is **published** versus **loaded**: every `has*` flag comes from the manifest (what
 * the build published), and a view is rendered only once every key it needs is loaded, so a
 * view never reads a block that is still on its way as if it were empty.
 *
 * A player card reads its records from its card shard rather than from the boards — see
 * `cardData` — so the card shows the same records whichever board it was opened from and
 * whichever blocks happen to be loaded.
 */

import { CriticalArtifactError, type Degradation } from "./errors";
import {
  ARTIFACT_SCHEMA_VERSION,
  type ArbitrageRecord,
  type ArtifactName,
  type BehaviorTrendSeriesRecord,
  type BuildMetadata,
  type EspnOwnershipRecord,
  type EspnOwnershipSeriesRecord,
  type MarketTrendSeriesRecord,
  type OpportunityCohortRecord,
  type OpportunityRecord,
  type UnprojectedRecord,
  type PlayerHeadshotRecord,
  type PlayerProjectionRecord,
  type PlayerStatusRecord,
  type PlayerUsageRecord,
  type RecentFormRow,
  type RosBuildMetadata,
  type RosTierRecord,
  type ScoringPreset,
  type SeasonActualsRow,
  type TeamMatchupRecord,
  type TierRecord,
  type UsageCohortRecord,
  type WeeklyGameContextRecord,
  type WeeklyProjectionRecord,
} from "./contracts";
import {
  ArtifactVersionError,
  majorVersion,
  parseBuildMetadata,
  parseRosBuildMetadata,
} from "./load";
import type { StatusEvidence } from "./availability";
import { ArtifactIndex } from "./model";
import { InSeasonBundle } from "./ros";
import {
  blockKey,
  bucketOf,
  cardKey,
  decodeTable,
  fetchServed,
  type EnvelopeHeader,
  type Manifest,
  type Table,
} from "./serving";
import { IN_SEASON_VIEWS, type ResolvedViewId } from "./state";

type Row = Record<string, unknown>;

/** What decides which served files a render needs. */
export interface NeedContext {
  readonly view: ResolvedViewId;
  readonly leaguePreset: string;
  readonly scoring: ScoringPreset;
  /** The open player card, or null. */
  readonly cardPlayerId: string | null;
  /**
   * My Leagues only (ADR-106): false until the workspace has named the active league's preset,
   * and when there is no league. The view then loads no block or scoring file at all.
   */
  readonly leagueFiles?: boolean;
  /**
   * ADR-115: the ROS board's bye filter is on, so it needs the next-game records — about 2 kB,
   * fetched only then. Start/Sit reads byes off its own weekly records.
   */
  readonly hideBye?: boolean;
}

/**
 * My Leagues' optional files (ADR-106): what Rising Stars reads, fetched only when a league has
 * it switched on, and never gating the lineup — the workspace renders while these load. The
 * same slices the Opportunity Board reads, so a reader who has opened that board pays nothing.
 */
export function risingKeys(manifest: Manifest, leaguePreset: string, scoring: ScoringPreset): readonly string[] {
  const block = blockKey(leaguePreset, scoring);
  return [`inseason_opportunity/${block}`, "player_usage/all", "behavior_trend_series/all"].filter(
    (key) => key in manifest.files,
  );
}

/**
 * Win My Matchup's YOLO files (ADR-110 §6): the block's Opportunity rows (net adds) and the role
 * series — Rising Stars' files minus the add-momentum series, which YOLO does not read. Fetched
 * only while YOLO is on for the open league, never gating the matchup.
 */
export function matchupYoloKeys(manifest: Manifest, leaguePreset: string, scoring: ScoringPreset): readonly string[] {
  const block = blockKey(leaguePreset, scoring);
  return [`inseason_opportunity/${block}`, "player_usage/all"].filter((key) => key in manifest.files);
}

/** The same rule, spelled for the manifest's keys. Pure: the budget test calls it too. */
export function requiredKeys(manifest: Manifest, context: NeedContext): readonly string[] {
  const block = blockKey(context.leaguePreset, context.scoring);
  const wanted: string[] = ["players"];
  const draft = ["tiers", "arbitrage", "data"].includes(context.view);
  // ADR-101: every in-season view applies the availability policy, which reads the compact
  // status slice (codes, designation, observation time, reviewed override) — ~3 kB, not the
  // whole status artifact. Joined in the browser by canonical id, never by build id.
  if (IN_SEASON_VIEWS.includes(context.view) && manifest.ros_build_metadata !== undefined) {
    wanted.push("player_availability/all");
  }
  // ADR-105: season actuals beside every in-season table and the RoS chart — one slice per
  // scoring preset, ranked at build time, so a direct link to any of these views (or to a card
  // opened from one) has the complete standings without visiting another view first.
  const actuals = `season_actuals/${context.scoring}`;
  switch (context.view) {
    case "tiers":
      wanted.push(`tiers/${block}`, "player_status/all");
      break;
    case "arbitrage":
    case "data":
      wanted.push(`arbitrage/${block}`, `tiers/${block}`, "player_status/all");
      break;
    case "ros":
      wanted.push(`ros_tiers/${block}`, actuals);
      if (context.hideBye === true) wanted.push("team_matchups/all");
      break;
    case "opportunity":
      wanted.push(
        `ros_tiers/${block}`,
        actuals,
        `inseason_opportunity/${block}`,
        "player_usage/all",
        "behavior_trend_series/all",
        "team_matchups/all",
        // ADR-112: ESPN's latest readings, one small slice for every block. Never the series.
        "espn_ownership/all",
        // ADR-113: recent windows and breakout evidence, one slice per scoring preset. Read
        // by this view only, so no other tab and no card pays for it.
        `recent_form/${context.scoring}`,
      );
      break;
    case "potw":
      wanted.push(
        `ros_tiers/${block}`,
        `inseason_opportunity/${block}`,
        "player_usage/all",
        "behavior_trend_series/all",
        "team_matchups/all",
        "player_headshots/all",
      );
      break;
    case "startsit":
      // The week board prints each player's RoS positional rank beside his season rank, so
      // it reads the league's rest-of-season block too (the default view's, already loaded).
      wanted.push(
        `weekly_projections/${context.scoring}`,
        "weekly_context/all",
        `ros_tiers/${block}`,
        actuals,
      );
      break;
    case "trade":
      // ADR-100 §9: one block of the rest-of-season board — the slice the default in-season
      // view has already loaded — and nothing else.
      wanted.push(`ros_tiers/${block}`);
      break;
    case "insights":
      // ADR-116: one scoring preset's stories — no story depends on league size — and the
      // status slice above, which every in-season view shares. Nothing else: a story carries
      // its own numbers, so the feed fetches no projection, card, usage or Skill Tree file.
      wanted.push(`insights/${context.scoring}`);
      break;
    case "myleagues":
      if (context.leagueFiles === false) break;
      // ADR-106: the active league's block and scoring only. The lineup and matchups read the
      // week's projections and game-day context (Start/Sit's two files); the player search,
      // ROS ranks and Improve read the block the default view already loaded; positions for
      // players with no weekly or ROS row come from the season actuals.
      wanted.push(
        `weekly_projections/${context.scoring}`,
        "weekly_context/all",
        `ros_tiers/${block}`,
        actuals,
      );
      break;
  }
  if (context.cardPlayerId !== null) {
    wanted.push(cardKey(context.leaguePreset, context.scoring, context.cardPlayerId, manifest.card_buckets));
    // The in-season cohort strips place a player among his published block; the draft card
    // shows the rest-of-season section beside the draft one once a board exists.
    if (manifest.ros_build_metadata !== undefined) {
      wanted.push(`ros_tiers/${block}`, `inseason_opportunity_cohort/${block}`, actuals);
      if (!draft) wanted.push("player_usage_cohort/all", "team_matchups/all", "weekly_context/all");
    }
  }
  // A key the build did not publish is simply not needed: the view reads it as absent, which
  // is what it has always done with a missing artifact.
  return [...new Set(wanted)].filter((key) => key in manifest.files);
}

/**
 * The Skill Tree's two served files for one player (ADR-107): his position's definitions and
 * the bucket shard holding his readings. Never part of `requiredKeys`: no view and no card open
 * fetches them; only an explicit Skill Tree activation does. A key the build did not publish is
 * left out — a player whose bucket holds no one has no readings.
 */
export function skillTreeKeys(manifest: Manifest, playerId: string, position: string): readonly string[] {
  const shard = `skill_tree/${String(bucketOf(playerId, manifest.card_buckets)).padStart(2, "0")}`;
  return [`skill_tree_definitions/${position}`, shard].filter((key) => key in manifest.files);
}

/**
 * One player's ESPN ownership history file (ADR-112): the bucket shard holding his series.
 * Never part of `requiredKeys` — no view and no card open fetches it; only activating a card's
 * In-season usage section does, and a second player in the same bucket costs nothing more.
 */
export function ownershipHistoryKeys(manifest: Manifest, playerId: string): readonly string[] {
  const shard = `espn_ownership_series/${String(bucketOf(playerId, manifest.card_buckets)).padStart(2, "0")}`;
  return [shard].filter((key) => key in manifest.files);
}

/**
 * The Insights feed's input (ADR-116), raw: the lazy view parses every row and the metadata
 * itself, so the parser and its rules ride the Insights chunk rather than the entry bundle.
 */
export interface InsightsSource {
  /** The build published `insights.json` at all (its envelope is in the manifest). */
  readonly published: boolean;
  /** Its envelope version is one this page reads. */
  readonly compatible: boolean;
  /** The preset's slice has loaded, or the build published none for it (zero stories). */
  readonly loaded: boolean;
  /** The preset's decoded rows; empty when it published no story for this preset. */
  readonly rows: readonly Record<string, unknown>[];
  /** `ros_build_metadata.insights`, verbatim (absent and null are the same unavailable state). */
  readonly meta: unknown;
  /**
   * The preset's evidence slice (`insight_evidence/<scoring>`): fetched the first time a reader
   * expands a story's Evidence, once per preset, never when the tab opens. Resolves with its
   * decoded rows, or none when the build published no slice for the preset.
   */
  readonly loadEvidence: () => Promise<readonly Record<string, unknown>[]>;
}

/** Families whose arrival changes nothing any subscriber renders (ADR-107, ADR-112). */
const QUIET_FAMILIES: ReadonlySet<string> = new Set([
  // ADR-116: a story's Evidence reads the rows from the promise it awaited.
  "insight_evidence",
  "skill_tree",
  "skill_tree_definitions",
  "espn_ownership_series",
]);

/** What the card needs to load one player's ESPN history on demand (ADR-112). */
export interface OwnershipHistorySource {
  /** `incompatible`: published under a record major version this page does not read. */
  readonly status: "published" | "incompatible";
  /** Start fetching (or reuse) a player's bucket; resolves with his series, or null. */
  readonly load: (playerId: string) => Promise<EspnOwnershipSeriesRecord | null>;
}

/** One player's Skill Tree rows as the store decoded them; parsed by the lazy chunk. */
export interface SkillTreeLoad {
  readonly rows: readonly Record<string, unknown>[];
  readonly definitions: readonly Record<string, unknown>[];
}

/** What the card needs to offer a Skill Tree and load one on demand (ADR-107). */
export interface SkillTreeSource {
  /** `incompatible`: published under a record major version this page does not read. */
  readonly status: "published" | "incompatible";
  /** `ros_build_metadata.skill_tree`, verbatim. */
  readonly meta: unknown;
  /** Start fetching (or reuse) a player's two files; resolves with his rows. */
  readonly load: (playerId: string, position: string) => Promise<SkillTreeLoad>;
}

function supported(header: EnvelopeHeader | undefined): boolean {
  return (
    header !== undefined &&
    majorVersion(header.schema_version) === majorVersion(ARTIFACT_SCHEMA_VERSION)
  );
}

export class DataStore {
  readonly manifest: Manifest;
  readonly base: string | undefined;
  readonly metadata: BuildMetadata;
  /** Null when the build published no usable in-season bundle — before kickoff, ordinarily. */
  readonly rosMetadata: RosBuildMetadata | null;
  readonly degradations: readonly Degradation[];
  private names: Readonly<Record<string, string>> | null = null;
  private readonly tables = new Map<string, readonly Row[]>();
  private readonly cards = new Map<string, Readonly<Record<string, readonly Row[]>>>();
  private readonly pending = new Map<string, Promise<void>>();
  private readonly listeners = new Set<() => void>();
  private versionValue = 0;
  private readonly boardCache = new Map<string, { stamp: string; index: ArtifactIndex }>();
  private readonly seasonCache = new Map<string, { stamp: string; bundle: InSeasonBundle | null }>();
  /** One evidence loader per preset, so a story's Evidence holds a stable function (ADR-116). */
  private readonly evidenceLoaders = new Map<string, () => Promise<readonly Row[]>>();

  constructor(manifest: Manifest, base?: string) {
    this.manifest = manifest;
    this.base = base;
    // The two refusals the page has always made, now made from the manifest: the build's own
    // metadata, and the tier board, must be versions this build understands.
    try {
      this.metadata = parseBuildMetadata(manifest.build_metadata);
    } catch (error) {
      throw new CriticalArtifactError("build_metadata.json", error);
    }
    const tiers = manifest.artifacts.tiers;
    if (tiers === undefined) {
      throw new CriticalArtifactError("tiers.json", new Error("the build published no tier board"));
    }
    if (!supported(tiers)) {
      throw new CriticalArtifactError(
        "tiers.json",
        new ArtifactVersionError("tiers", tiers.schema_version, ARTIFACT_SCHEMA_VERSION),
      );
    }
    let ros: RosBuildMetadata | null = null;
    if (manifest.ros_build_metadata !== undefined && supported(manifest.artifacts.ros_tiers)) {
      try {
        ros = parseRosBuildMetadata(manifest.ros_build_metadata);
      } catch {
        ros = null;
      }
    }
    this.rosMetadata = ros;
    // Reported in a fixed order, as the whole-artifact loader reported them.
    const degradations: Degradation[] = [];
    for (const artifact of ["arbitrage", "player_status", "projections"] as const) {
      const header = manifest.artifacts[artifact];
      if (header === undefined) {
        degradations.push({
          artifact,
          reason: "unavailable",
          message: `${artifact} was not published in this build`,
        });
      } else if (!supported(header)) {
        degradations.push({
          artifact,
          reason: "incompatible",
          message:
            `${artifact} declares schema version ${header.schema_version}, but this build ` +
            `supports ${ARTIFACT_SCHEMA_VERSION}.`,
        });
      }
    }
    this.degradations = degradations;
  }

  /**
   * The Skill Tree's loader, or null when this build published none (an older deploy, or a
   * failed enrichment). Its files go through the same hash-checked cache as every slice.
   */
  skillTreeSource(): SkillTreeSource | null {
    const header = this.manifest.artifacts.player_skill_tree;
    const definitions = this.manifest.artifacts.skill_tree_definitions;
    if (header === undefined || definitions === undefined) return null;
    const meta = (this.manifest.ros_build_metadata as { skill_tree?: unknown } | undefined)?.skill_tree ?? null;
    if (!supported(header) || !supported(definitions)) {
      return {
        status: "incompatible",
        meta,
        load: () => Promise.reject(new Error("the Skill Tree's artifact version is not supported")),
      };
    }
    return {
      status: "published",
      meta,
      load: async (playerId, position) => {
        const keys = skillTreeKeys(this.manifest, playerId, position);
        const definitionsKey = `skill_tree_definitions/${position}`;
        if (!keys.includes(definitionsKey)) throw new Error(`no Skill Tree definitions for ${position}`);
        await this.ensure(keys);
        const shard = keys.find((key) => key.startsWith("skill_tree/"));
        const rows = shard === undefined ? [] : (this.tables.get(shard) ?? []);
        return {
          rows: rows.filter((row) => row.player_id === playerId),
          definitions: this.tables.get(definitionsKey) ?? [],
        };
      },
    };
  }

  /**
   * The ESPN history loader, or null when this build published no series (an older deploy, a
   * build with no retained capture, or one where no board player had a point).
   */
  ownershipHistorySource(): OwnershipHistorySource | null {
    const header = this.manifest.artifacts.espn_ownership_series;
    if (header === undefined) return null;
    if (!supported(header)) {
      return {
        status: "incompatible",
        load: () => Promise.reject(new Error("the ESPN history's artifact version is not supported")),
      };
    }
    return {
      status: "published",
      load: async (playerId) => {
        const keys = ownershipHistoryKeys(this.manifest, playerId);
        await this.ensure(keys);
        const rows = keys.length === 0 ? [] : (this.tables.get(keys[0] ?? "") ?? []);
        const found = rows.find((row) => row.player_id === playerId);
        return (found as unknown as EspnOwnershipSeriesRecord | undefined) ?? null;
      },
    };
  }

  /** The Insights feed's rows and metadata for one scoring preset, as loaded (ADR-116). */
  insightsSource(scoring: ScoringPreset): InsightsSource {
    const key = `insights/${scoring}`;
    const listed = key in this.manifest.files;
    let loadEvidence = this.evidenceLoaders.get(scoring);
    if (loadEvidence === undefined) {
      const evidenceKey = `insight_evidence/${scoring}`;
      loadEvidence = async () => {
        if (!(evidenceKey in this.manifest.files)) return [];
        await this.ensure([evidenceKey]);
        return this.tables.get(evidenceKey) ?? [];
      };
      this.evidenceLoaders.set(scoring, loadEvidence);
    }
    return {
      published: this.manifest.artifacts.insights !== undefined,
      compatible: this.published("insights"),
      loaded: !listed || this.tables.has(key),
      rows: this.tables.get(key) ?? [],
      meta: (this.manifest.ros_build_metadata as { insights?: unknown } | undefined)?.insights ?? null,
      loadEvidence,
    };
  }

  /** A player's name from the dictionary every slice resolves through, or null (ADR-106). */
  nameFor(playerId: string): string | null {
    return this.names?.[playerId] ?? null;
  }

  /** Published and readable by this build. */
  published(artifact: ArtifactName): boolean {
    return supported(this.manifest.artifacts[artifact]);
  }

  get version(): number {
    return this.versionValue;
  }

  subscribe(listener: () => void): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  private notify(): void {
    this.versionValue += 1;
    for (const listener of this.listeners) listener();
  }

  isLoaded(keys: readonly string[]): boolean {
    return keys.every((key) =>
      key === "players" ? this.names !== null : this.tables.has(key) || this.cards.has(key),
    );
  }

  /** Fetch and decode every key not yet loaded, in parallel. Resolves when all are in. */
  ensure(keys: readonly string[]): Promise<void> {
    const work = keys.map((key) => this.load(key));
    return Promise.all(work).then(() => undefined);
  }

  private load(key: string): Promise<void> {
    if (this.isLoaded([key])) return Promise.resolve();
    const existing = this.pending.get(key);
    if (existing !== undefined) return existing;
    const digest = this.manifest.files[key];
    if (digest === undefined) return Promise.resolve();
    // A table that joins another decodes after it; the fetches still run side by side.
    const family = key.split("/", 1)[0] ?? "";
    const partition = key.slice(family.length + 1);
    const dependencies: Promise<void>[] = [key === "players" ? Promise.resolve() : this.load("players")];
    if (family === "inseason_opportunity" && `ros_tiers/${partition}` in this.manifest.files) {
      dependencies.push(this.load(`ros_tiers/${partition}`));
    }
    const task = Promise.all([fetchServed(key, digest, this.base), ...dependencies])
      .then(([payload]) => {
        this.decode(key, payload);
        // The Skill Tree reads its rows from the promise it awaited; no board or view
        // subscribes to them, so its files never re-render the page behind the card.
        if (!QUIET_FAMILIES.has(family)) this.notify();
      })
      .finally(() => {
        this.pending.delete(key);
      });
    this.pending.set(key, task);
    return task;
  }

  private decode(key: string, payload: unknown): void {
    const body = payload as Row;
    if (key === "players") {
      this.names = body.names as Record<string, string>;
      return;
    }
    const names = this.names ?? {};
    if (body.family === "card") {
      const sections: Record<string, readonly Row[]> = {};
      for (const [artifact, table] of Object.entries(body.sections as Record<string, Table>)) {
        const header = this.manifest.artifacts[artifact as ArtifactName];
        if (header === undefined) continue;
        sections[artifact] = decodeTable<Row>(table, header, names);
      }
      this.cards.set(key, sections);
      return;
    }
    const table = body as unknown as Table & { artifact: ArtifactName; partition: string };
    const header = this.manifest.artifacts[table.artifact];
    if (header === undefined) return;
    let joinSource: Map<string, Row> | undefined;
    if (table.join !== undefined) {
      const source = this.tables.get(`${table.join.family}/${table.partition}`) ?? [];
      joinSource = new Map(source.map((row) => [String(row.player_id), row]));
    }
    this.tables.set(key, decodeTable<Row>(table, header, names, joinSource));
  }

  private rows<T>(family: string, scope: ReadonlySet<string>): T[] {
    const out: T[] = [];
    for (const [key, rows] of this.tables) {
      if (key.startsWith(`${family}/`) && scope.has(key)) out.push(...(rows as unknown as T[]));
    }
    return out;
  }

  /** Which of `keys` are loaded: an index built from them changes only when this does. */
  private stamp(keys: readonly string[]): string {
    return keys.filter((key) => this.isLoaded([key])).join(",");
  }

  private blocksOf(family: string): { leaguePreset: string; scoring: ScoringPreset }[] {
    return Object.keys(this.manifest.files)
      .filter((key) => key.startsWith(`${family}/`))
      .map((key) => {
        const [leaguePreset = "", scoring = "PPR"] = key.slice(family.length + 1).split(".");
        return { leaguePreset, scoring: scoring as ScoringPreset };
      });
  }

  /**
   * The draft boards, built from exactly `keys` (the open view's needs).
   *
   * Scoped rather than "everything loaded", so a view's index is the same object until one of
   * its own files arrives: a card's shard landing must not hand the board a new index, or
   * every row under the reader's pointer would re-render and the card's trigger lose focus.
   */
  boardIndex(keys: readonly string[]): ArtifactIndex {
    const id = keys.join(",");
    const stamp = this.stamp(keys);
    const cached = this.boardCache.get(id);
    if (cached?.stamp === stamp) return cached.index;
    const scope = new Set(keys);
    const index = new ArtifactIndex({
      metadata: this.metadata,
      tiers: this.rows<TierRecord>("tiers", scope),
      arbitrage: this.published("arbitrage") ? this.rows<ArbitrageRecord>("arbitrage", scope) : null,
      arbitragePublished: this.published("arbitrage"),
      playerStatus: this.published("player_status")
        ? this.rows<PlayerStatusRecord>("player_status", scope)
        : null,
      headshots: this.published("player_headshots")
        ? this.rows<PlayerHeadshotRecord>("player_headshots", scope)
        : null,
      // Card-only artifacts: a card reads them from its shard (`cardData`).
      projections: this.published("projections") ? [] : null,
      trendSeries: this.published("market_trend_series") ? [] : null,
      blocks: this.blocksOf("tiers"),
    });
    this.boardCache.set(id, { stamp, index });
    return index;
  }

  /** The in-season bundle built from exactly `keys`; null when none was published. */
  inSeason(keys: readonly string[]): InSeasonBundle | null {
    const id = keys.join(",");
    const stamp = this.stamp(keys);
    const cached = this.seasonCache.get(id);
    if (cached?.stamp === stamp) return cached.bundle;
    const scope = new Set(keys);
    const metadata = this.rosMetadata;
    const bundle =
      metadata === null
        ? null
        : new InSeasonBundle({
            metadata,
            rosTiers: this.rows<RosTierRecord>("ros_tiers", scope),
            opportunity: this.published("inseason_opportunity")
              ? this.rows<OpportunityRecord | UnprojectedRecord>("inseason_opportunity", scope)
              : null,
            opportunityDegradation: this.opportunityDegradation(),
            behaviorSeries: this.published("behavior_trend_series")
              ? this.rows<BehaviorTrendSeriesRecord>("behavior_trend_series", scope)
              : null,
            usage:
              scope.has("player_usage/all") && this.tables.has("player_usage/all")
                ? this.rows<PlayerUsageRecord>("player_usage", scope)
                : null,
            usageCohort: this.rows<UsageCohortRecord>("player_usage_cohort", scope),
            opportunityCohort: this.rows<OpportunityCohortRecord>("inseason_opportunity_cohort", scope),
            matchups: this.published("team_matchups")
              ? this.rows<TeamMatchupRecord>("team_matchups", scope)
              : null,
            weekly: this.published("weekly_projections")
              ? this.rows<WeeklyProjectionRecord>("weekly_projections", scope)
              : null,
            weeklyContext: this.published("weekly_context")
              ? this.rows<WeeklyGameContextRecord>("weekly_context", scope)
              : null,
            status: this.published("player_status")
              ? this.rows<StatusEvidence>("player_availability", scope)
              : null,
            actuals: this.rows<SeasonActualsRow>("season_actuals", scope),
            actualsPublished: this.published("season_actuals"),
            espn:
              scope.has("espn_ownership/all") && this.tables.has("espn_ownership/all")
                ? this.rows<EspnOwnershipRecord>("espn_ownership", scope)
                : null,
            espnPublished: this.manifest.artifacts.espn_ownership !== undefined,
            espnCompatible: this.published("espn_ownership"),
            recent: [...scope].some((key) => key.startsWith("recent_form/") && this.tables.has(key))
              ? this.rows<RecentFormRow>("recent_form", scope)
              : null,
            recentPublished: this.manifest.artifacts.recent_form !== undefined,
            recentCompatible: this.published("recent_form"),
            published: {
              opportunity: this.published("inseason_opportunity"),
              behaviorSeries: this.published("behavior_trend_series"),
              usage: this.published("player_usage"),
              matchups: this.published("team_matchups"),
              weekly: this.published("weekly_projections"),
            },
            blocks: this.blocksOf("ros_tiers"),
          });
    this.seasonCache.set(id, { stamp, bundle });
    return bundle;
  }

  private opportunityDegradation(): Degradation | null {
    const header = this.manifest.artifacts.inseason_opportunity;
    if (header === undefined) {
      return {
        artifact: "inseason_opportunity",
        reason: "unavailable",
        message: "inseason_opportunity was not published in this build",
      };
    }
    if (!supported(header)) {
      return {
        artifact: "inseason_opportunity",
        reason: "incompatible",
        message: `inseason_opportunity declares schema version ${header.schema_version}`,
      };
    }
    return null;
  }

  /**
   * One player's records, from his card shard: a draft-board index and an in-season bundle
   * holding exactly the rows that shard carries. Null until the shard is loaded.
   */
  cardData(
    leaguePreset: string,
    scoring: ScoringPreset,
    playerId: string,
  ): { readonly index: ArtifactIndex; readonly inSeason: InSeasonBundle | null } | null {
    const key = cardKey(leaguePreset, scoring, playerId, this.manifest.card_buckets);
    const sections = this.cards.get(key);
    if (sections === undefined) return key in this.manifest.files ? null : this.emptyCard();
    const section = <T>(artifact: string): T[] => (sections[artifact] ?? []) as unknown as T[];
    const index = new ArtifactIndex({
      metadata: this.metadata,
      tiers: section<TierRecord>("tiers"),
      arbitrage: section<ArbitrageRecord>("arbitrage"),
      playerStatus: section<PlayerStatusRecord>("player_status"),
      headshots: section<PlayerHeadshotRecord>("player_headshots"),
      projections: section<PlayerProjectionRecord>("projections"),
      trendSeries: section<MarketTrendSeriesRecord>("market_trend_series"),
    });
    const metadata = this.rosMetadata;
    const inSeason =
      metadata === null
        ? null
        : new InSeasonBundle({
            metadata,
            rosTiers: section<RosTierRecord>("ros_tiers"),
            opportunity: section<OpportunityRecord | UnprojectedRecord>("inseason_opportunity"),
            opportunityDegradation: null,
            behaviorSeries: section<BehaviorTrendSeriesRecord>("behavior_trend_series"),
            usage: section<PlayerUsageRecord>("player_usage"),
            matchups: [],
            weekly: section<WeeklyProjectionRecord>("weekly_projections"),
            status: section<PlayerStatusRecord>("player_status"),
            espn: section<EspnOwnershipRecord>("espn_ownership"),
            espnPublished: this.manifest.artifacts.espn_ownership !== undefined,
            espnCompatible: this.published("espn_ownership"),
          });
    return { index, inSeason };
  }

  /** A player no shard holds — every lookup answers null, as a whole artifact would have. */
  private emptyCard(): { readonly index: ArtifactIndex; readonly inSeason: InSeasonBundle | null } {
    const index = new ArtifactIndex({
      metadata: this.metadata,
      tiers: [],
      arbitrage: [],
      playerStatus: [],
      headshots: [],
      projections: [],
      trendSeries: [],
    });
    const metadata = this.rosMetadata;
    return {
      index,
      inSeason:
        metadata === null
          ? null
          : new InSeasonBundle({ metadata, rosTiers: [], opportunity: [], opportunityDegradation: null }),
    };
  }

  /** Whether the card is part of the in-season product: the view it was opened from decides. */
  static cardIsInSeason(view: ResolvedViewId): boolean {
    return IN_SEASON_VIEWS.includes(view);
  }
}
