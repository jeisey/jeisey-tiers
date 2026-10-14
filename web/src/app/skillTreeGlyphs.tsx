/**
 * The Skill Tree's football glyphs (ADR-107): original line drawings on a 24-unit grid, drawn
 * in `currentColor` so a node's state sets their colour. No game asset, image file or icon
 * font: each glyph is a few SVG primitives, and the whole set costs less than one portrait.
 */

import type { ReactNode } from "react";

type GlyphName =
  | "ball"
  | "throw"
  | "yards"
  | "goal"
  | "crosshair"
  | "arc"
  | "bolt"
  | "check"
  | "shield"
  | "intercept"
  | "run"
  | "zigzag"
  | "endzone"
  | "goalline"
  | "pie"
  | "helmet"
  | "target"
  | "hands"
  | "yac"
  | "burst"
  | "radar"
  | "separation"
  | "cushion"
  | "stopwatch"
  | "calendar"
  | "depth";

const ball = <ellipse cx="12" cy="12" rx="8.5" ry="5" transform="rotate(-35 12 12)" />;
const laces = <path d="M9.6 13.9 14.4 10.1M10.6 10.9l1.3 1.6M12.1 9.7l1.3 1.6M9.1 12.1l1.3 1.6" />;

const GLYPHS: Readonly<Record<GlyphName, ReactNode>> = {
  ball: (
    <>
      {ball}
      {laces}
    </>
  ),
  throw: (
    <>
      <ellipse cx="14" cy="10" rx="6.5" ry="4" transform="rotate(-35 14 10)" />
      <path d="M2.5 16.5h5M4 19.5h5M5.5 13.5h3" />
    </>
  ),
  yards: (
    <>
      <path d="M3 9h18v6H3z" />
      <path d="M6 9v3M9 9v2M12 9v3M15 9v2M18 9v3" />
    </>
  ),
  goal: <path d="M12 21v-9M5.5 3.5V12h13V3.5" />,
  crosshair: (
    <>
      <circle cx="12" cy="12" r="6.5" />
      <path d="M12 2.5v5M12 16.5v5M2.5 12h5M16.5 12h5" />
      <circle cx="12" cy="12" r="1" />
    </>
  ),
  arc: (
    <>
      <path d="M3 19C6 7 15 5 21 9" />
      <path d="m18 5.5 3 3.5-3.8 1.4" />
    </>
  ),
  bolt: <path d="M13.5 2.5 5.5 13.5h5.5l-1 8 8.5-11.5h-5.5z" />,
  check: (
    <>
      <path d="m12 2.8 8 4.6v9.2l-8 4.6-8-4.6V7.4z" />
      <path d="m8.3 12.2 2.6 2.7 4.9-5.4" />
    </>
  ),
  shield: (
    <>
      <path d="M12 3 19.5 6v5.5c0 4.6-3.2 7.9-7.5 9.5-4.3-1.6-7.5-4.9-7.5-9.5V6z" />
      <path d="m10.5 7.5 2 4-2.5 2 2.5 3" />
    </>
  ),
  intercept: (
    <>
      {ball}
      <path d="M4.5 19.5 19.5 4.5" />
    </>
  ),
  run: <path d="m5 5.5 6.5 6.5L5 18.5M12.5 5.5 19 12l-6.5 6.5" />,
  zigzag: (
    <>
      <path d="m3 17 4.5-5.5 4 4L17 8" />
      <path d="M13.6 7.6 17.4 7.4 17.6 11.2" />
    </>
  ),
  endzone: (
    <>
      <path d="M3.5 4.5h17v15h-17z" />
      <path d="M3.5 11.5 10.5 4.5M3.5 18.5 17.5 4.5M10.5 19.5 20.5 9.5M17.5 19.5l3-3" />
    </>
  ),
  goalline: (
    <>
      <path d="M17.5 2.5v19" />
      <ellipse cx="9" cy="12" rx="5.5" ry="3.4" transform="rotate(-25 9 12)" />
    </>
  ),
  pie: (
    <>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M12 12V3.5A8.5 8.5 0 0 1 20.2 14.3z" />
    </>
  ),
  helmet: (
    <>
      <path d="M4 14c0-5.5 3.6-9.5 9-9.5 4.4 0 7.5 3 7.5 7.3V14h-6l-1.5 4H8z" />
      <path d="M14.5 14h4.5v4.5M16 11.5h4.5" />
    </>
  ),
  target: (
    <>
      <circle cx="12" cy="12" r="8.5" />
      <circle cx="12" cy="12" r="4.8" />
      <circle cx="12" cy="12" r="1.3" />
    </>
  ),
  hands: (
    <>
      <path d="M4 10.5c0 5 3.6 9 8 9s8-4 8-9" />
      <path d="M7.5 11V7.5M10.5 11V5.5M13.5 11V5.5M16.5 11V7.5" />
    </>
  ),
  yac: (
    <>
      <circle cx="6" cy="12" r="2.6" />
      <path d="M10.5 12h10M16.5 8l4 4-4 4" />
    </>
  ),
  burst: <path d="m12 2.5 2 5.6 5.7-2.1-3.1 5.2L21.5 14l-5.9.7.7 5.8-4.3-4-4.3 4 .7-5.8-5.9-.7 4.9-2.8L4.3 6l5.7 2.1z" />,
  radar: (
    <>
      <path d="M4 18a10 10 0 0 1 16 0" />
      <path d="M7.5 18a5.5 5.5 0 0 1 9 0" />
      <path d="M12 18 17 7" />
      <circle cx="17" cy="7" r="1.3" />
    </>
  ),
  separation: (
    <>
      <circle cx="5.5" cy="12" r="2.6" />
      <circle cx="18.5" cy="12" r="2.6" />
      <path d="M9.5 12h5M9.5 9.5v5M14.5 9.5v5" />
    </>
  ),
  cushion: (
    <>
      <circle cx="12" cy="5.5" r="2.4" />
      <circle cx="12" cy="18.5" r="2.4" />
      <path d="M7 9.5v5M17 9.5v5M7 12h10" />
    </>
  ),
  stopwatch: (
    <>
      <circle cx="12" cy="13.5" r="7.5" />
      <path d="M12 13.5V9M10 2.5h4M12 2.5V6M18 6.5l1.5-1.5" />
    </>
  ),
  calendar: (
    <>
      <path d="M3.5 5.5h17v15h-17zM3.5 10h17M8 3v4.5M16 3v4.5" />
      <path d="m8.5 15 2.2 2.2 4.6-4.6" />
    </>
  ),
  depth: (
    <>
      <path d="M12 21V4M7.5 8.5 12 4l4.5 4.5" />
      <path d="M8 15h8M9 18.5h6" />
    </>
  ),
};

const METRIC_GLYPHS: Readonly<Record<string, GlyphName>> = {
  appearances: "calendar",
  combine_forty: "stopwatch",
  pass_attempts: "throw",
  completions: "hands",
  passing_yards: "yards",
  passing_tds: "goal",
  passing_td_rate: "goal",
  cpoe: "crosshair",
  completion_pct: "crosshair",
  yards_per_attempt: "yards",
  intended_air_yards: "arc",
  pass_epa_per_dropback: "bolt",
  dropback_success_rate: "check",
  sack_rate: "shield",
  avg_time_to_throw: "stopwatch",
  interception_rate: "intercept",
  designed_rushes: "run",
  scrambles: "zigzag",
  scramble_rate: "zigzag",
  rushing_yards: "yards",
  rushing_tds: "goal",
  red_zone_rushes: "endzone",
  goal_line_rushes: "goalline",
  red_zone_dropbacks: "endzone",
  carries: "ball",
  carry_share: "pie",
  offense_snap_share: "helmet",
  yards_per_carry: "yards",
  rush_epa_per_carry: "bolt",
  rush_success_rate: "check",
  explosive_run_rate: "burst",
  explosive_runs: "burst",
  rush_yards_over_expected_per_att: "radar",
  targets: "target",
  receptions: "hands",
  receiving_yards: "yards",
  receiving_tds: "goal",
  target_share: "pie",
  air_yards_share: "arc",
  catch_rate: "hands",
  yards_per_target: "yards",
  yards_per_reception: "yards",
  adot: "depth",
  yac_per_reception: "yac",
  rec_epa_per_target: "bolt",
  explosive_catches: "burst",
  explosive_catch_rate: "burst",
  yac_over_expected: "radar",
  avg_separation: "separation",
  avg_cushion: "cushion",
  red_zone_carries: "endzone",
  red_zone_carry_share: "endzone",
  goal_line_carries: "goalline",
  goal_line_carry_share: "goalline",
  red_zone_targets: "endzone",
  red_zone_target_share: "endzone",
  end_zone_targets: "goal",
};

const BRANCH_GLYPHS: Readonly<Record<string, GlyphName>> = {
  passing_volume: "throw",
  accuracy_depth: "crosshair",
  efficiency_security: "bolt",
  legs_scoring: "run",
  ground_workload: "ball",
  rushing_efficiency: "bolt",
  receiving: "target",
  scoring_role: "goal",
  target_earning: "target",
  depth_big_plays: "arc",
  catch_contribution: "hands",
  usage: "helmet",
  reliability: "hands",
  production: "yards",
  scoring_depth: "goal",
};

function Glyph({ name }: { readonly name: GlyphName }): React.JSX.Element {
  return (
    <svg
      className="st-glyph"
      viewBox="0 0 24 24"
      width="24"
      height="24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      {GLYPHS[name]}
    </svg>
  );
}

export function MetricGlyph({ metric }: { readonly metric: string }): React.JSX.Element {
  return <Glyph name={METRIC_GLYPHS[metric] ?? "target"} />;
}

export function BranchGlyph({ branch }: { readonly branch: string }): React.JSX.Element {
  return <Glyph name={BRANCH_GLYPHS[branch] ?? "target"} />;
}

/** The tree's core: the position in a framed hexagon on a circuit stub. */
export function CoreEmblem({ position }: { readonly position: string }): React.JSX.Element {
  return (
    <svg className="st-core" viewBox="0 0 64 64" width="64" height="64" aria-hidden="true" focusable="false">
      <path className="st-core-frame" d="M32 3 57 17.5v29L32 61 7 46.5v-29z" />
      <path className="st-core-inner" d="M32 9.5 51.5 20.75v22.5L32 54.5 12.5 43.25v-22.5z" />
      <path className="st-core-trace" d="M32 54.5V64M12.5 43.25 3 49M51.5 43.25 61 49" />
      <text x="32" y="38" textAnchor="middle" className="st-core-text">
        {position}
      </text>
    </svg>
  );
}
