/**
 * The header: what this is, when it was built, and whether anything is degraded.
 *
 * `docs/UX_SPEC.md` section 4 allows a wordmark, a timestamp and a degraded marker. No hero,
 * no tagline above the data. The freshness stamp is derived from `build_metadata.json`; there
 * is no date anywhere in this source (`docs/DATA_CONTRACTS.md` section 11).
 *
 * Phase 9A adopted the design source's command-board header, which is the same five elements
 * in the same order — including a build-notes chip that already matched `mastheadStatus`. The
 * `ffdraft-` CSV prefix is an export contract and is deliberately untouched
 * (`web/src/data/csv.ts`).
 *
 * Phase 9B replaced the typeset wordmark — the notched glyph, `jeisey-tiers` and the mono
 * sub-label — with the owner's own logo artwork. It is the product's real brand mark, so it
 * stands alone: repeating "jeisey-tiers" beside a picture that already says it would be
 * duplicate branding, and repeating it to a screen reader would be duplicate announcements.
 * The artwork's `alt` is the product name, and the `<h1>` around it gives the document the
 * top-level heading it never had while the brand was a `<span>`.
 *
 * The import goes through Vite so the emitted URL carries the build's `base` — the site is
 * served from `/` in development and from `/jeisey-tiers/` on Pages, and a hand-written
 * `/src/...` path would resolve in exactly one of those.
 */

import logoUrl from "../assets/jt_logo.png";
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
  seasonMode,
}: {
  readonly metadata: BuildMetadata;
  readonly degradations: readonly Degradation[];
  readonly onOpenData: () => void;
  readonly now?: Date | undefined;
  /**
   * The season-mode indicator (roadmap 12.4), rendered here because it is status of the same
   * kind as the build stamp beside it — and because a phone cannot afford a band of its own
   * for it without pushing the board below the fold.
   */
  readonly seasonMode?: React.ReactNode;
}): React.JSX.Element {
  const ageHours = buildAgeHours(metadata, now);
  const status = mastheadStatus(metadata, degradations, ageHours);
  return (
    <header className="masthead">
      <h1 className="masthead-brand">
        {/* Intrinsic dimensions are the artwork's own, so the row reserves the right box
            before the image decodes rather than reflowing the freshness stamp into it. */}
        <img className="masthead-logo" src={logoUrl} alt="Jeisey Tiers" width={434} height={145} />
      </h1>
      <div className="masthead-meta">
        {seasonMode}
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
