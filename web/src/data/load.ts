/**
 * Typed artifact loading with schema-version checks.
 *
 * `docs/DATA_CONTRACTS.md` section 13 requires the frontend to reject an unsupported major
 * version with a clear error rather than attempt best-effort rendering. A half-understood
 * artifact is the worst outcome on draft day: the page looks fine and the numbers are wrong.
 *
 * Nothing here calls a data vendor. `docs/ARCHITECTURE.md` section 3.2 limits the browser to
 * generated files under the artifact base path.
 */

import {
  ARTIFACT_FILENAMES,
  ARTIFACT_SCHEMA_VERSION,
  BUILD_METADATA_FILENAME,
  type ArtifactEnvelope,
  type ArtifactName,
  type BuildMetadata,
} from "./contracts";

export class ArtifactVersionError extends Error {
  readonly artifact: string;
  readonly found: string;
  readonly supported: string;

  constructor(artifact: string, found: string, supported: string) {
    super(
      `${artifact} declares schema version ${found}, but this build supports ${supported}. ` +
        "Refusing to render rather than guess at an incompatible contract.",
    );
    this.name = "ArtifactVersionError";
    this.artifact = artifact;
    this.found = found;
    this.supported = supported;
  }
}

export class ArtifactShapeError extends Error {
  constructor(artifact: string, detail: string) {
    super(`${artifact} is not a valid artifact envelope: ${detail}`);
    this.name = "ArtifactShapeError";
  }
}

/** Major version, i.e. the part before the first dot. Only this has to match. */
export function majorVersion(version: string): string {
  const [major] = version.split(".");
  return major ?? version;
}

export function isSupportedVersion(version: string): boolean {
  return majorVersion(version) === majorVersion(ARTIFACT_SCHEMA_VERSION);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/**
 * Narrow an unknown payload to a typed envelope.
 *
 * Structural checks only: the record bodies were validated against the JSON Schema at build
 * time by `ffdraft validate-artifacts`, and re-implementing that in the browser would be a
 * second source of truth that could disagree with the first.
 */
export function parseEnvelope<TRecord>(
  payload: unknown,
  artifact: ArtifactName,
): ArtifactEnvelope<TRecord> {
  if (!isRecord(payload)) {
    throw new ArtifactShapeError(artifact, "payload is not an object");
  }
  const version = payload.schema_version;
  if (typeof version !== "string") {
    throw new ArtifactShapeError(artifact, "missing schema_version");
  }
  if (!isSupportedVersion(version)) {
    throw new ArtifactVersionError(artifact, version, ARTIFACT_SCHEMA_VERSION);
  }
  if (payload.artifact !== artifact) {
    throw new ArtifactShapeError(
      artifact,
      `envelope declares artifact ${String(payload.artifact)}`,
    );
  }
  const records = payload.records;
  if (!Array.isArray(records)) {
    throw new ArtifactShapeError(artifact, "records is not an array");
  }
  const declared = payload.record_count;
  if (typeof declared !== "number" || declared !== records.length) {
    throw new ArtifactShapeError(
      artifact,
      `record_count ${String(declared)} disagrees with ${String(records.length)} records`,
    );
  }
  return payload as unknown as ArtifactEnvelope<TRecord>;
}

export function parseBuildMetadata(payload: unknown): BuildMetadata {
  if (!isRecord(payload)) {
    throw new ArtifactShapeError(BUILD_METADATA_FILENAME, "payload is not an object");
  }
  const version = payload.schema_version;
  if (typeof version !== "string") {
    throw new ArtifactShapeError(BUILD_METADATA_FILENAME, "missing schema_version");
  }
  if (!isSupportedVersion(version)) {
    throw new ArtifactVersionError(
      BUILD_METADATA_FILENAME,
      version,
      ARTIFACT_SCHEMA_VERSION,
    );
  }
  for (const field of ["build_id", "generated_at_utc", "arbitrage_mode"] as const) {
    if (typeof payload[field] !== "string") {
      throw new ArtifactShapeError(BUILD_METADATA_FILENAME, `missing ${field}`);
    }
  }
  return payload as unknown as BuildMetadata;
}

/**
 * Join the artifact base path and a filename.
 *
 * The base path is a Vite build-time value so a project Pages deployment under `/<repo>/`
 * and a custom-domain deployment under `/` both resolve (architecture section 11).
 */
export function artifactUrl(filename: string, base: string = import.meta.env.BASE_URL): string {
  const prefix = base.endsWith("/") ? base : `${base}/`;
  return `${prefix}data/${filename}`;
}

async function fetchJson(url: string, artifact: string): Promise<unknown> {
  const response = await fetch(url, { headers: { Accept: "application/json" } });
  if (!response.ok) {
    throw new ArtifactShapeError(artifact, `HTTP ${String(response.status)} for ${url}`);
  }
  return (await response.json()) as unknown;
}

export async function loadArtifact<TRecord>(
  artifact: ArtifactName,
  options: { readonly base?: string } = {},
): Promise<ArtifactEnvelope<TRecord>> {
  const url = artifactUrl(ARTIFACT_FILENAMES[artifact], options.base);
  return parseEnvelope<TRecord>(await fetchJson(url, artifact), artifact);
}

export async function loadBuildMetadata(
  options: { readonly base?: string } = {},
): Promise<BuildMetadata> {
  const url = artifactUrl(BUILD_METADATA_FILENAME, options.base);
  return parseBuildMetadata(await fetchJson(url, BUILD_METADATA_FILENAME));
}

/** Freshness for the methodology panel. The UI never hardcodes an update timestamp. */
export function buildAgeHours(metadata: BuildMetadata, now: Date = new Date()): number {
  const generated = Date.parse(metadata.generated_at_utc);
  if (Number.isNaN(generated)) {
    return Number.POSITIVE_INFINITY;
  }
  return (now.getTime() - generated) / 3_600_000;
}

export function degradedSources(metadata: BuildMetadata): readonly string[] {
  return metadata.sources
    .filter((source) => source.status === "failed" || source.status === "warning")
    .map((source) => source.source_id);
}
