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
 * retained at one instant — a fact, whether or not a second observation follows it. The slope
 * beside it is an estimate under `behavior_trend_v1`, which will state one from as few as two
 * observations precisely because an add count moves in hours. What makes that honest rather
 * than reckless is that **the span is printed with it, always**: `+320/day over 2 days` is a
 * different claim from `+320/day over 6 days` and the reader gets to see which one they have.
 *
 * **A bar is a snapshot, not a day** (ADR-090). The window is seven days and the snapshots in
 * it are `daily-refresh` runs, which are neither one per day nor evenly spaced: the schedule
 * adds a second run on Tuesdays and a morning spent re-running the workflow adds five. So the
 * strip is as long as the week happened to be sampled — fifteen bars is an ordinary week —
 * and the count of bars is never the count of days. The caption's `/day` figure is unaffected,
 * because `behavior_trend_v1` fits on elapsed days and not on sample index; `observation_days`
 * on the same record is the distinct-day count when one is wanted.
 *
 * **A gap is drawn as a gap.** Sleeper's feed is a top-100 list, so a snapshot the player was
 * outside it carries no count at all — unknown, not zero. Those render as a hairline rather
 * than a zero-height bar, because a floor-height bar reads as "nobody added him" and that is a
 * different fact. The caption says how many there were.
 *
 * **Bars, not a line, and not by accident.** A line implies a value between two samples; a
 * daily transaction count has none. The Opportunity Board makes the same choice for the same
 * reason, and this reuses its geometry vocabulary so the two read as one system.
 *
 * **Never colour alone** (UX_SPEC section 12). Direction is in the caption's words, in the
 * arrow glyph, and in the accessible summary; the tint is the fourth channel, not the first.
 */

import { useId } from "react";

import { EM_DASH, formatInteger } from "../data/format";
import {
  MOMENTUM_GLYPH,
  formatMomentumRate,
  momentumDirection,
  type BehaviorMomentum,
} from "../data/ros";

/*
  The direction and the printed rate come from `data/ros`, not from here (ADR-092). The
  Opportunity Board prints the same reading for five hundred rows at once, and two definitions
  of "rising" — one in this strip, one in the board — would be two answers about one player.
*/
function directionOf(trend: number | null): "rising" | "falling" | "flat" | "unknown" {
  return momentumDirection(trend) ?? "unknown";
}

const GLYPH: Readonly<Record<string, string>> = { ...MOMENTUM_GLYPH, unknown: "·" };

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
  const per = `${formatMomentumRate(trend).replace("/day", "")} adds per day`;
  const word = momentumDirection(trend) ?? "flat";
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
  /*
    **Every retained point, and no cap** (ADR-090).

    This drew the newest twelve and dropped the rest, which read as a sensible guard against a
    long window and was not one. Nothing else on the card truncates: the slope, the span, the
    gap count and `peak` are all measured over the whole window, and `behavior_trend_v1` is
    the artifact's rule rather than this component's, so a truncated strip cannot restate any
    of them for the window it actually drew. A cap therefore does not shorten the reading, it
    just makes the picture describe a different window from the four numbers beside it —
    including the y-axis, because heights are scaled to a peak the cap can push off-screen.

    The window is bounded in *time* (seven days), never in samples, and a sample is one
    `daily-refresh` run: two on a Tuesday, five on an afternoon somebody spent re-running it.
    Fifteen in a week is ordinary. `.momentum-bar` shrinks to fit and `momentum.test.tsx`
    pins the count to the artifact's own.
  */
  const bars = momentum.points;
  const sentence = momentumSentence(momentum);

  return (
    <div className="momentum" data-direction={direction}>
      <span className="readout-label">{label}</span>

      <div className="momentum-body">
        {/*
          `aria-hidden` on the bars and a real sentence beside them: the strip is a picture of
          numbers that are all in the sentence, so announcing every bar would be a dozen-odd
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
            {momentum.trend === null ? EM_DASH : formatMomentumRate(momentum.trend)}
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
