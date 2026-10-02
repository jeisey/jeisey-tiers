/**
 * The Trade method's published constants (ADR-100), apart from the engine.
 *
 * The Data view prints them, and it is in the entry bundle; the engine (`trade.ts`) is loaded
 * only with the Trade tab. A module imported by both would be placed in the entry chunk whole,
 * so the numbers both need live here and the engine re-exports them.
 */

export const TRADE_METHOD_VERSION = "trade_targets_v1";

export const TRADE_DISTRIBUTION_VERSION = "ros_package_quantiles_v1";

/** `member_share_v1`: every member of a 2- or 3-player package carries at least this share. */
export const MEMBER_SHARE_MIN = 0.15;

/** Packages kept after ranking; the dealing order walks these (ADR-100 §6). */
export const POOL_CAP = 200;

/** Tail factor: a linear tail with a Gaussian's conditional tail mean (ADR-100 §5). */
export const TAIL_FACTOR = 1.56;
