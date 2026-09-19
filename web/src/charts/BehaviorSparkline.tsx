/**
 * Add momentum: a player's retained daily add counts, drawn small (ADR-089).
 *
 * The mockup's fourth readout is a rising bar sparkline labelled `ADD MOMENTUM`, and until
 * this artifact existed it was the one element of that design with **no source**: the store
 * had held a daily add/drop snapshot since the season opened and nothing read more than the
 * newest one, so the card could say "1,120 adds in 24 hours" and could not say "rising for
 * four days" (ADR-088). This draws the window the store was always holding.
 *
 * **It draws observations; the caption states the estimate.** The same separation ADR-081
 * settled for the market chart, and it matters more here, not less. A bar is a count that was
 * retained on a day — a fact, whether or not a second day follows it. The slope beside it is
 * an estimate under `behavior_trend_v1`, which will state one from as few as two observations
 * precisely because an add count moves in hours. What makes that honest rather than reckless
 * is that **the span is printed with it, always**: `+320/day over 2 days` is a different
 * claim from `+320/day over 6 days` and the reader gets to see which one they have.
 *
 * **A gap is drawn as a gap.** Sleeper's feed is a top-100 list, so a day the player was
 * outside it carries no count at all — unknown, not zero. Those days render as a hairline
 * rather than a zero-height bar, because a floor-height bar reads as "nobody added him" and
 * that is a different fact. The caption says how many there were.
 *
 * **Bars, not a line, and not by accident.** A line implies a value between two samples; a
 * daily transaction count has none. The Opportunity Board makes the same choice for the same
 * reason, and this reuses its geometry vocabulary so the two read as one system.
 *
 * **Never colour alone** (UX_SPEC section 12). Direction is in the caption's words, in the
 * arrow glyph, and in the accessible summary; the tint is the fourth channel, not the first.
 */

import { useId } from "react";

import { EM_DASH, formatInteger, formatValue } from "../data/format";
import type { BehaviorMomentum } from "../data/ros";

/** How many bars fit before the strip stops being legible in a card tile. */
const MAX_BARS = 12;

function directionOf(trend: number | null): "rising" | "falling" | "flat" | "unknown" {
  if (trend === null) return "unknown";
  if (trend > 0) return "rising";
  if (trend < 0) return "falling";
  return "flat";
}

const GLYPH: Readonly<Record<string, string>> = {
  rising: "▲",
  falling: "▼",
  flat: "▬",
  unknown: "·",
};

/**
 * The sentence a screen reader gets, and the one printed under the bars.
 *
 * Exported because two surfaces render it and a second copy would be a second wording of one
 * claim. It never prints a percentage and never implies a share of leagues: ADR-088's rule
 * that no surface in this feature may leave room to infer a rostered percentage binds the
 * history exactly as it binds the day.
 */
export function momentumSentence(momentum: BehaviorMomentum): string {
  const { trend, spanLabel, missing, points } = momentum;
  const latest = points[points.length - 1];
  const observed = `${formatInteger(latest?.adds ?? 0)} adds at the latest snapshot`;
  const gap =
    missing > 0
      ? ` ${String(missing)} snapshot${missing === 1 ? "" : "s"} in the window did not carry him, so those days have no count rather than a count of zero.`
      : "";
  if (trend === null) {
    return (
      `${observed}. One observation so far, so there is no direction yet — a direction needs ` +
      `two.${gap}`
    );
  }
  const per = `${trend > 0 ? "+" : ""}${formatValue(trend)} adds per day`;
  const word = trend > 0 ? "rising" : trend < 0 ? "falling" : "flat";
  return `${observed}. ${word.charAt(0).toUpperCase()}${word.slice(1)} at ${per}, ${spanLabel}.${gap}`;
}

export function BehaviorSparkline({
  momentum,
  label = "Add momentum",
}: {
  readonly momentum: BehaviorMomentum;
  readonly label?: string;
}): React.JSX.Element {
  const summaryId = useId();
  const direction = directionOf(momentum.trend);
  // The newest bars, if a long window ever outgrows the strip. Oldest-left is preserved.
  const bars = momentum.points.slice(-MAX_BARS);
  const sentence = momentumSentence(momentum);

  return (
    <div className="momentum" data-direction={direction}>
      <span className="readout-label">{label}</span>

      <div className="momentum-body">
        {/*
          `aria-hidden` on the bars and a real sentence beside them: the strip is a picture of
          numbers that are all in the sentence, so announcing twelve bars would be twelve
          announcements of one reading. This is the same construction every other micro-chart
          in the card uses.
        */}
        <div className="momentum-bars" aria-hidden="true">
          {bars.map((point) => {
            const height = Math.max(6, Math.round((point.adds / momentum.peak) * 100));
            return (
              <span
                key={point.at}
                className="momentum-bar"
                style={{ height: `${String(height)}%` }}
                data-latest={point === bars[bars.length - 1] ? "true" : undefined}
              />
            );
          })}
          {momentum.missing > 0 && (
            /*
              One mark for the whole gap rather than one per missing day: the artifact says
              how many snapshots skipped him, not which ones, and drawing a bar per unknown
              day at a guessed position would invent the very thing the count avoids.
            */
            <span className="momentum-gap" data-count={momentum.missing} />
          )}
        </div>

        <p className="momentum-reading" aria-describedby={summaryId}>
          <span className="momentum-glyph" aria-hidden="true">
            {GLYPH[direction] ?? "·"}
          </span>
          <span className="momentum-value">
            {momentum.trend === null
              ? EM_DASH
              : `${momentum.trend > 0 ? "+" : ""}${formatValue(momentum.trend)}/day`}
          </span>
          {/*
            The span, printed and never optional. `behavior_trend_v1` states a direction from
            two observations, so this is the field that stops a one-day reading being read as
            a week's — see the module docstring and ADR-089.
          */}
          <span className="momentum-span">
            {momentum.trend === null ? "one observation" : momentum.spanLabel}
          </span>
        </p>
      </div>

      <span className="visually-hidden" id={summaryId}>
        {sentence}
      </span>
    </div>
  );
}
