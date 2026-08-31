/**
 * The header: what this is, when it was built, and whether anything is degraded.
 *
 * `docs/UX_SPEC.md` section 4 allows a wordmark, a timestamp and a degraded marker. No hero,
 * no tagline above the data. The freshness stamp is derived from `build_metadata.json`; there
 * is no date anywhere in this source (`docs/DATA_CONTRACTS.md` section 11).
 *
 * Phase 9A adopted the design source's command-board header, which is the same five elements
 * in the same order — including a build-notes chip that already matched `mastheadStatus`. The
 * wordmark is the source's: it names the product `jeisey-tiers`, which is what the repository,
 * the Pages URL and the owner call it. The `ffdraft-` CSV prefix is an export contract and is
 * deliberately untouched (`web/src/data/csv.ts`).
 */

import type { BuildMetadata } from "../data/contracts";
import type { Degradation } from "../data/bundle";
import { formatAge, formatEastern } from "../data/format";
import { buildAgeHours } from "../data/load";
import { STALE_WARNING_HOURS } from "../data/freshness";

export interface MastheadStatus {
  readonly tone: "ok" | "warning";
  readonly label: string;
}

/**
 * The compact status chip.
 *
 * Three different things can be wrong and they are not the same size of problem, so the chip
 * names the most serious one and the Data panel carries the detail. A build warning is not an
 * outage; a limited market cohort is not a broken build.
 */
export function mastheadStatus(
  metadata: BuildMetadata,
  degradations: readonly Degradation[],
  ageHours: number,
): MastheadStatus {
  if (degradations.length > 0) {
    return { tone: "warning", label: `${String(degradations.length)} source degraded` };
  }
  if (ageHours > STALE_WARNING_HOURS) {
    return { tone: "warning", label: "Build is stale" };
  }
  if (metadata.quality_gate.status === "fail") {
    return { tone: "warning", label: "Quality gate failed" };
  }
  if (metadata.warnings.length > 0) {
    return {
      tone: "warning",
      label: `${String(metadata.warnings.length)} build note${metadata.warnings.length === 1 ? "" : "s"}`,
    };
  }
  return { tone: "ok", label: "All checks passed" };
}

export function Masthead({
  metadata,
  degradations,
  onOpenData,
  now,
}: {
  readonly metadata: BuildMetadata;
  readonly degradations: readonly Degradation[];
  readonly onOpenData: () => void;
  readonly now?: Date | undefined;
}): React.JSX.Element {
  const ageHours = buildAgeHours(metadata, now);
  const status = mastheadStatus(metadata, degradations, ageHours);
  return (
    <header className="masthead">
      <div className="masthead-brand">
        {/* The design source's notched command glyph. Decoration, and marked as such. */}
        <span className="masthead-glyph chamfer" aria-hidden="true" />
        <span className="wordmark">jeisey-tiers</span>
        <span className="wordmark-sub" aria-hidden="true">
          / Tiers &amp; arbitrage
        </span>
      </div>
      <div className="masthead-meta">
        <span className="freshness">
          Updated <strong>{formatEastern(metadata.generated_at_utc)}</strong>
          <span className="visually-hidden">{`, ${formatAge(ageHours)}`}</span>
        </span>
        <button
          type="button"
          className="status-chip"
          data-tone={status.tone}
          onClick={onOpenData}
          aria-label={`${status.label}. Open the data and methodology view.`}
        >
          {status.label}
        </button>
      </div>
    </header>
  );
}
