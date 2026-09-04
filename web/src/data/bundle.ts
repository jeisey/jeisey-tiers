/**
 * Loading the whole board, with the critical and the degradable told apart.
 *
 * Not every artifact is equally load-bearing. `build_metadata.json` and `tiers.json` *are*
 * the product: if either is unreadable or declares a version this build does not understand,
 * the honest outcome is a refusal, because a half-understood tier board looks fine and is
 * wrong (`docs/DATA_CONTRACTS.md` section 13). Arbitrage, player status and projections are
 * additive: without them the intrinsic board is still exactly correct, so their absence
 * degrades a feature rather than the page.
 *
 * The browser fetches generated static files and nothing else — no MyFantasyLeague, no
 * Sleeper, no nflverse, no FantasyPros (`docs/ARCHITECTURE.md` section 3.2).
 */

import type {
  ArbitrageRecord,
  ArtifactName,
  BuildMetadata,
  MarketTrendSeriesRecord,
  OpportunityRecord,
  PlayerProjectionRecord,
  PlayerStatusRecord,
  RosBuildMetadata,
  RosTierRecord,
  TierRecord,
} from "./contracts";
import {
  ArtifactVersionError,
  loadArtifact,
  loadBuildMetadata,
  loadRosBuildMetadata,
} from "./load";
import { ArtifactIndex } from "./model";
import { InSeasonBundle } from "./ros";

/** Why an optional artifact is missing, in the words the Data panel will use. */
export interface Degradation {
  readonly artifact: ArtifactName;
  readonly reason: "incompatible" | "unavailable";
  readonly message: string;
}

export interface LoadedBundle {
  readonly index: ArtifactIndex;
  readonly degradations: readonly Degradation[];
  /**
   * The in-season bundle, or null when this build published none.
   *
   * Null is the normal state before kickoff and is not a failure: the draft product is the
   * whole product until the season starts. It is also what a site shows when an in-season
   * refresh failed its gate — the last good draft board stays, and the in-season tabs say
   * why they are absent rather than rendering an empty table.
   */
  readonly inSeason: InSeasonBundle | null;
}

export class CriticalArtifactError extends Error {
  readonly artifact: string;
  readonly incompatible: boolean;
  readonly expected: string | null;
  readonly found: string | null;

  constructor(artifact: string, cause: unknown) {
    const versionError = cause instanceof ArtifactVersionError ? cause : null;
    super(cause instanceof Error ? cause.message : String(cause));
    this.name = "CriticalArtifactError";
    this.artifact = artifact;
    this.incompatible = versionError !== null;
    this.expected = versionError?.supported ?? null;
    this.found = versionError?.found ?? null;
  }
}

interface OptionalResult<TRecord> {
  readonly records: readonly TRecord[] | null;
  readonly degradation: Degradation | null;
}

async function optional<TRecord>(
  artifact: ArtifactName,
  base: string | undefined,
): Promise<OptionalResult<TRecord>> {
  const where: { base?: string } = base === undefined ? {} : { base };
  try {
    const envelope = await loadArtifact<TRecord>(artifact, where);
    return { records: envelope.records, degradation: null };
  } catch (error) {
    // An unsupported version is reported differently from a missing file: one means the build
    // and the site disagree about a contract, the other means the build did not produce it.
    // Both leave the intrinsic board untouched, which is the point of the split.
    return {
      records: null,
      degradation: {
        artifact,
        reason: error instanceof ArtifactVersionError ? "incompatible" : "unavailable",
        message: error instanceof Error ? error.message : String(error),
      },
    };
  }
}

export async function loadBundle(options: { readonly base?: string } = {}): Promise<LoadedBundle> {
  // `exactOptionalPropertyTypes` is on, so an absent base is an absent key rather than an
  // explicit `undefined`; the loader then falls back to Vite's `BASE_URL`.
  const where: { base?: string } = options.base === undefined ? {} : { base: options.base };
  const base = options.base;

  let metadata: BuildMetadata;
  try {
    metadata = await loadBuildMetadata(where);
  } catch (error) {
    throw new CriticalArtifactError("build_metadata.json", error);
  }

  let tiers: readonly TierRecord[];
  try {
    tiers = (await loadArtifact<TierRecord>("tiers", where)).records;
  } catch (error) {
    throw new CriticalArtifactError("tiers.json", error);
  }

  // Fetched together, but reported in a fixed order: a Data panel that listed degraded
  // sources in whatever order the network happened to settle would read differently on
  // every reload.
  const [arbitrage, playerStatus, projections, trendSeries] = await Promise.all([
    optional<ArbitrageRecord>("arbitrage", base),
    optional<PlayerStatusRecord>("player_status", base),
    optional<PlayerProjectionRecord>("projections", base),
    // Absent until the retained store holds enough history to draw one, and absent on any
    // Release 1 bundle. The card degrades to the scalar trend it has always shown.
    optional<MarketTrendSeriesRecord>("market_trend_series", base),
  ]);
  const degradations = [arbitrage, playerStatus, projections]
    .map((result) => result.degradation)
    .filter((entry): entry is Degradation => entry !== null);

  return {
    index: new ArtifactIndex({
      metadata,
      tiers,
      arbitrage: arbitrage.records,
      playerStatus: playerStatus.records,
      projections: projections.records,
      trendSeries: trendSeries.records,
    }),
    degradations,
    inSeason: await loadInSeason(base),
  };
}

/**
 * Load the in-season bundle, or explain its absence.
 *
 * Deliberately all-or-nothing about its *metadata*: the rest-of-season board may not be
 * rendered without `ros_build_metadata.json`, because that file carries the cutoff week and
 * ADR-076's disclosure sentences, and a board showing a long-absence flag without them is
 * exactly the misleading product the ADR exists to prevent. The Opportunity Board is one
 * level softer — it is additive on top of a valid ROS board, so its absence removes a tab
 * rather than the mode.
 */
async function loadInSeason(base: string | undefined): Promise<InSeasonBundle | null> {
  const where: { base?: string } = base === undefined ? {} : { base };
  let metadata: RosBuildMetadata;
  try {
    metadata = await loadRosBuildMetadata(where);
  } catch {
    return null;
  }
  let rosTiers: readonly RosTierRecord[];
  try {
    rosTiers = (await loadArtifact<RosTierRecord>("ros_tiers", where)).records;
  } catch {
    return null;
  }
  const opportunity = await optional<OpportunityRecord>("inseason_opportunity", base);
  return new InSeasonBundle({
    metadata,
    rosTiers,
    opportunity: opportunity.records,
    opportunityDegradation: opportunity.degradation,
  });
}
