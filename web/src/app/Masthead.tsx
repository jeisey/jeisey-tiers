/**
 * The header: the logo (the link home) and when the build was made. Nothing else.
 *
 * `docs/UX_SPEC.md` section 4. No hero, no tagline above the data. The freshness stamp is
 * derived from `build_metadata.json`; there is no date anywhere in this source
 * (`docs/DATA_CONTRACTS.md` section 11).
 *
 * The 2026-10-06 housekeeping pass removed the build-status chip and the season-mode label
 * that used to sit beside the stamp (PRD CR-005 as revised). The chip's readings — degraded
 * artifacts, a stale build, the quality gate and the build notes — are all in the Data view,
 * which stays one tab away; the season mode is the switch in the controls and the tabs it
 * changes. The `ffdraft-` CSV prefix is an export contract and is deliberately untouched
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

import logoUrl from "../assets/jt_logo-96.png";
import logoUrl3x from "../assets/jt_logo-145.png";
import type { BuildMetadata } from "../data/contracts";
import { formatAge, formatEastern } from "../data/format";
import { buildAgeHours } from "../data/load";
import { homeHref } from "./useAppState";

/**
 * The logo, as the link home (the default, season-aware landing view).
 *
 * A real `<a href>` so keyboard, middle-click, "open in new tab" and "copy link" behave as a
 * reader expects, resolved from Vite's base so `/` and `/jeisey-tiers/` both land on the right
 * page. The `<h1>` stays the document's one top-level heading; the link's accessible name says
 * where it goes as well as what the picture is.
 */
export function BrandLogo(): React.JSX.Element {
  return (
    <h1 className="masthead-brand">
      <a className="masthead-home" href={homeHref()} aria-label="Jeisey Tiers home">
        {/* Intrinsic dimensions are the artwork's own, so the row reserves the right box
            before the image decodes rather than reflowing the freshness stamp into it. */}
        <img
          className="masthead-logo"
          src={logoUrl}
          srcSet={`${logoUrl} 2x, ${logoUrl3x} 3x`}
          alt="Jeisey Tiers"
          width={434}
          height={145}
        />
      </a>
    </h1>
  );
}

export function Masthead({
  metadata,
  now,
}: {
  readonly metadata: BuildMetadata;
  readonly now?: Date | undefined;
}): React.JSX.Element {
  const ageHours = buildAgeHours(metadata, now);
  return (
    <header className="masthead">
      <BrandLogo />
      <div className="masthead-meta">
        <span className="freshness">
          Updated <strong>{formatEastern(metadata.generated_at_utc)}</strong>
          <span className="visually-hidden">{`, ${formatAge(ageHours)}`}</span>
        </span>
      </div>
    </header>
  );
}
