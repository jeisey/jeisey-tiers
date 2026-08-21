/**
 * Quality flags, in the language of someone drafting rather than someone debugging.
 *
 * Every flag published by the build gets a sentence. A flag this table does not know still
 * renders — as its raw identifier with a generic note — because a build that gains a check
 * should not make a badge silently disappear from the UI (`docs/UX_SPEC.md` section 10).
 */

export interface FlagExplanation {
  /** Two or three words, for a compact chip. */
  readonly label: string;
  /** One sentence, for the accessible description beside it. */
  readonly detail: string;
  readonly severity: "info" | "caution";
}

const MARKET_FLAGS: Readonly<Record<string, FlagExplanation>> = {
  cohort_insufficient: {
    label: "Thin market cohort",
    detail:
      "The keeper-free MyFantasyLeague draft population has not yet reached the draft count " +
      "the confidence rule requires. This describes the market sample, not the player.",
    severity: "caution",
  },
  cohort_approximate: {
    label: "Approximate cohort",
    detail:
      "MyFantasyLeague cannot filter drafts to this exact scoring and league size, so the " +
      "price comes from the closest population it can express.",
    severity: "info",
  },
  low_market_sample: {
    label: "Few drafts priced him",
    detail: "Fewer than 30 drafts in the cohort selected this player, so his average pick moves easily.",
    severity: "caution",
  },
  wide_market_range: {
    label: "Wide pick range",
    detail:
      "The earliest and latest observed picks are more than five rounds apart. These are " +
      "extreme single observations, and they widen with sample size rather than describing " +
      "disagreement — read the low/high picks directly instead.",
    severity: "info",
  },
  insufficient_trend_history: {
    label: "Trend collecting",
    detail:
      "A trend needs at least three observation days spanning three days of our own retained " +
      "snapshots. Until then there is no movement estimate, which is not the same as no movement.",
    severity: "info",
  },
  market_snapshot_stale: {
    label: "Stale snapshot",
    detail: "The retained market snapshot behind this row is older than the freshness rule allows.",
    severity: "caution",
  },
  secondary_identity_bridge_only: {
    label: "Secondary id match",
    detail:
      "Only the secondary identity bridge matched this player to the market row, so the price " +
      "is attached with less corroboration than usual.",
    severity: "caution",
  },
};

const PLAYER_FLAGS: Readonly<Record<string, FlagExplanation>> = {
  rookie: {
    label: "Rookie",
    detail:
      "No NFL production history exists, so the projection rests on draft capital, biography " +
      "and team context. Rookie projections are the lowest-information rows on the board.",
    severity: "info",
  },
  no_prior_season_stats: {
    label: "No prior-season stats",
    detail: "The player recorded no statistics last season, so the lagged features are missing.",
    severity: "info",
  },
  no_depth_context: {
    label: "No depth signal",
    detail: "No pre-anchor depth-chart observation places this player in a role.",
    severity: "info",
  },
  no_current_roster_entry: {
    label: "Not on a current roster",
    detail: "No current nflverse roster entry was found for this player.",
    severity: "caution",
  },
  current_status_reserve: {
    label: "Reserve list",
    detail: "The current roster entry places this player on a reserve list.",
    severity: "caution",
  },
  current_status_cut: {
    label: "Released",
    detail: "The current roster entry records this player as released.",
    severity: "caution",
  },
  current_status_exempt: {
    label: "Exempt list",
    detail: "The current roster entry places this player on the exempt list.",
    severity: "caution",
  },
  sleeper_unavailable: {
    label: "No status source",
    detail: "The Sleeper status capture was unavailable for this build, so no injury annotation exists.",
    severity: "info",
  },
  sleeper_record_missing: {
    label: "No Sleeper record",
    detail: "Sleeper publishes no record for this player, so no injury annotation is available.",
    severity: "info",
  },
  sleeper_identity_conflict: {
    label: "Identity conflict",
    detail:
      "Sleeper's reported league id disagreed with the canonical one, so its annotation was " +
      "refused rather than attached to the wrong player.",
    severity: "caution",
  },
};

export const FLAG_EXPLANATIONS: Readonly<Record<string, FlagExplanation>> = {
  ...MARKET_FLAGS,
  ...PLAYER_FLAGS,
};

/** Unknown flags survive as themselves. A missing entry is a documentation gap, not a bug to hide. */
export function explainFlag(flag: string): FlagExplanation {
  return (
    FLAG_EXPLANATIONS[flag] ?? {
      label: flag,
      detail: "This build published a quality flag this release does not have a description for.",
      severity: "info",
    }
  );
}

export function explainFlags(flags: readonly string[]): readonly (FlagExplanation & { flag: string })[] {
  return flags.map((flag) => ({ flag, ...explainFlag(flag) }));
}

/**
 * `wide_market_range` fires on roughly 90% of the current board, which makes it true and
 * non-discriminating (ADR-041). It stays available in player detail and diagnostics; it does
 * not earn a badge on nearly every row of the table.
 */
export const NON_DISCRIMINATING_FLAGS: readonly string[] = ["wide_market_range"];

/**
 * Flags every row shares are a property of the build, not of the player. They are explained
 * once at the view level and suppressed per row.
 */
export function rowLevelMarketFlags(flags: readonly string[], shared: ReadonlySet<string>): readonly string[] {
  return flags.filter((flag) => !shared.has(flag) && !NON_DISCRIMINATING_FLAGS.includes(flag));
}
