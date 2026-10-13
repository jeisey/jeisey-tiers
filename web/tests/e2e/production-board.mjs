/**
 * The size model's rest-of-season board, made production-shaped (ADR-100, ADR-106).
 *
 * The size model (ADR-098) is built to have production's *bytes*, not its values: its
 * quantiles are drawn independently and often cross, so many of its rows are correctly
 * unpriced. The interaction benchmarks rewrite every `ros_tiers` row's value fields into a
 * production-shaped board — 500 rows a block, expected value falling from ~150 to ~−15 with
 * ~170 above replacement, monotone right-skewed quantiles, 6% long absences and 4% reserve
 * codes — then re-package it with the production packager. Shared by `measure-trade.mjs` and
 * `measure-leagues.mjs`, so both measure the same board.
 */

import { execFileSync } from "node:child_process";
import { readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";

/** Deterministic jitter in [-0.5, 0.5). */
function jitter(seed) {
  const x = Math.sin(seed * 12.9898) * 43758.5453;
  return x - Math.floor(x) - 0.5;
}

function realistic(record, index, factor) {
  const mean = (170 * Math.exp(-index / 70) - 15 + 4 * jitter(index + 1)) * factor;
  const sigma = 0.35 * Math.abs(mean) + 12;
  const round = (value) => Number(value.toFixed(4));
  return {
    ...record,
    ros_expected_vorp: round(mean),
    ros_vorp_p10: round(mean - 1.35 * sigma),
    ros_vorp_p25: round(mean - 0.67 * sigma),
    ros_vorp_p50: round(mean - 0.05 * sigma),
    ros_vorp_p75: round(mean + 0.65 * sigma),
    ros_vorp_p90: round(mean + 1.3 * sigma),
    ros_expected_points: round(mean + (record.position === "QB" ? 150 : 100)),
    long_absence: index % 17 === 5,
    current_status: index % 23 === 7 ? "RES" : null,
  };
}

export function makeProductionShaped(dist, repo) {
  const path = join(dist, "data", "ros_tiers.json");
  const envelope = JSON.parse(readFileSync(path, "utf-8"));
  const blocks = new Map();
  for (const record of envelope.records) {
    const key = `${record.league_preset_id}|${record.scoring_preset}`;
    if (!blocks.has(key)) blocks.set(key, []);
    blocks.get(key).push(record);
  }
  const out = [];
  let blockIndex = 0;
  for (const rows of blocks.values()) {
    rows.sort((a, b) => a.ros_fair_rank - b.ros_fair_rank);
    const factor = 1 + 0.03 * blockIndex;
    rows.forEach((record, index) => out.push(realistic(record, index, factor)));
    blockIndex += 1;
  }
  envelope.records = out;
  writeFileSync(path, `${JSON.stringify(envelope)}\n`);
  execFileSync("uv", ["run", "--frozen", "ffdraft", "package-site-data", join(dist, "data")], {
    cwd: repo,
    stdio: ["ignore", "ignore", "inherit"],
  });
}
