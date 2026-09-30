/**
 * The two ways a load can end short of a full board, shared by the opener and the store.
 *
 * A **degradation** is an optional artifact the build did not publish, or published in a
 * version this build does not read: the board it feeds says so and every intrinsic number is
 * unaffected. A **critical** failure is the refusal the page has always made — no tier board
 * or build metadata it understands, so nothing is rendered rather than something half-read
 * (`docs/DATA_CONTRACTS.md` section 13).
 */

import type { ArtifactName } from "./contracts";
import { ArtifactVersionError } from "./load";

/** Why an optional artifact is missing, in the words the Data panel will use. */
export interface Degradation {
  readonly artifact: ArtifactName;
  readonly reason: "incompatible" | "unavailable";
  readonly message: string;
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
