/**
 * The one shape the Tier Board draws.
 *
 * Two boards feed it and they are two different models over two different horizons: the
 * preseason `fair_rank` over `p50_vorp`, and the rest-of-season `ros_fair_rank` over
 * `ros_vorp_p50` (ADR-071). They share a picture and nothing else, so the adapter lives here
 * and the quantities stay in their own modules.
 *
 * **The mapping is the only place the two meet, and it is deliberately lossy.** A `BoardMark`
 * carries a rank and five quantiles and no field name, so nothing downstream can average a
 * preseason value with a rest-of-season one, difference them, or sort them together — the
 * component never learns which board it is drawing. What it does learn is the *wording*, which
 * is why `BoardAxis` carries every string: a board that called remaining VORP "median
 * simulated VORP" would be mislabelling a different quantity with a familiar name.
 */

import type { Position } from "../data/contracts";

/** One player's mark on a board: a rank, five quantiles, and how to say so. */
export interface BoardMark {
  readonly playerId: string;
  readonly rank: number;
  readonly position: Position;
  readonly positionRank: number;
  readonly displayName: string;
  readonly p10: number;
  readonly p25: number;
  readonly p50: number;
  readonly p75: number;
  readonly p90: number;
  /** Badges rendered beside the name — status, long absence. Never the only channel. */
  readonly badges?: React.ReactNode;
  /** The whole accessible label for the mark. Built by the board that owns the quantity. */
  readonly label: string;
}

/** A contiguous run of marks sharing a tier ordinal. A band, never a cut position. */
export interface BoardGroup {
  readonly ordinal: number;
  readonly label: string;
  readonly marks: readonly BoardMark[];
}

/** Every word the board prints about its own quantity. */
export interface BoardAxis {
  /** The axis title, e.g. `Median simulated VORP`. */
  readonly title: string;
  /** The right-hand column heading over the printed value, e.g. `Median`. */
  readonly unit: string;
  /**
   * The quantity's short name, for the tier gutter's accessible label, e.g. `VORP`.
   *
   * Spelled out rather than inferred from `title`, because the two boards' quantities differ
   * by one word — `VORP` against `remaining VORP` — and that word is the whole difference
   * between a season total and what is left of one.
   */
  readonly quantityShort: string;
  /** The note beside the axis title. */
  readonly note: string;
  /** The board's screen-reader summary, in full sentences. */
  readonly summary: string;
}
