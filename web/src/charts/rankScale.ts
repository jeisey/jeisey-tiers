/**
 * The RoS chart's positional-rank scale (ADR-105).
 *
 * **Logarithmic, and labelled as such.** A place near the top of a position is worth more
 * than a place near the bottom — QB4 against QB15 is a different conversation from QB34
 * against QB45 — and on a linear scale a 70-deep position squeezes the first twelve into the
 * left sixth of the lane. On a log scale QB1, QB2, QB5, QB10 and QB20 are spread out and every
 * tick prints its rank, so a distance is read off the labels rather than guessed.
 *
 * **Rank 1 is on the left**, the way every rank column on the site reads. The scale's end is
 * the next round number at or past the deepest rank on the whole published block, so a mark's
 * coordinate does not move when the reader searches, filters or collapses a tier.
 */

const ROUND_ENDS = [10, 20, 50, 100, 200, 500, 1000] as const;
const TICKS = [1, 2, 5, 10, 20, 50, 100, 200, 500, 1000] as const;

/** The scale's last rank: the first round end at or past `domain`. */
export function rankScaleEnd(domain: number): number {
  const deepest = Number.isFinite(domain) ? Math.max(2, Math.ceil(domain)) : 2;
  return ROUND_ENDS.find((end) => end >= deepest) ?? deepest;
}

/** A rank's position along the lane, 0-100, on the log scale ending at `end`. */
export function rankPercent(rank: number, end: number): number {
  if (!Number.isFinite(rank) || rank <= 1 || end <= 1) return 0;
  return Math.max(0, Math.min(100, (Math.log(rank) / Math.log(end)) * 100));
}

/** The labelled ticks: round ranks up to the end, thinned on a narrow lane. */
export function rankTicks(end: number, compact: boolean): readonly number[] {
  const all = TICKS.filter((tick) => tick <= end);
  if (!compact) return all;
  // Keep 1, the end, and every other one between, so no two labels collide on a phone.
  return all.filter((tick, index) => tick === 1 || tick === end || index % 2 === 0);
}

/** The lane's gridlines as one background image, so 100 rows add no DOM for them. */
export function rankGridImage(ticks: readonly number[], end: number): string {
  return ticks
    .map((tick) => {
      const at = rankPercent(tick, end);
      return (
        `linear-gradient(90deg, transparent calc(${String(at)}% - 0.5px), ` +
        `rgb(46 204 255 / 11%) calc(${String(at)}% - 0.5px) calc(${String(at)}% + 0.5px), ` +
        `transparent calc(${String(at)}% + 0.5px))`
      );
    })
    .join(", ");
}
