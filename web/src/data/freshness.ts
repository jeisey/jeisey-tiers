/**
 * Display-only freshness thresholds.
 *
 * `docs/OPERATIONS.md` section 9 puts operational freshness thresholds in config, where the
 * build gate reads them. These two are a different thing and are deliberately separate: they
 * only decide whether the header shows a "stale" chip, they never block a render, and they
 * never contradict the build's own verdict.
 *
 * They live here rather than as literals inside components so there is one place to change
 * them and one place to read them from — the alternative is a magic hour count sprinkled
 * through the UI, which is what the prompt asked to avoid.
 */

/** A daily refresh (`daily-refresh.yml`) plus a full day of slack. */
export const STALE_WARNING_HOURS = 48;

/** Market snapshots are captured on the same daily cadence; three days is clearly behind. */
export const MARKET_STALE_WARNING_HOURS = 72;
