# Data Contracts and Canonical Entities

## 1. Contract philosophy

Dataframe columns are APIs. They must be versioned, validated, and documented.

The project has three layers of contracts:

1. **Source-normalized contracts** — adapter-specific outputs.
2. **Canonical/model contracts** — internal typed entities and feature matrices.
3. **Public artifact contracts** — stable browser/export schemas in `schemas/`.

Breaking changes require a schema version bump and migration/update across producers, consumers, fixtures, and docs.

## 2. Canonical player identity

### 2.1 Keys

Preferred primary key:

- `player_id` = canonical internal string, normally `gsis:<gsis_id>` when GSIS exists.

Store crosswalks separately:

- `gsis_id`
- `sleeper_id`
- `mfl_id`
- `espn_id`
- `pfr_id`
- other IDs supplied by nflverse/ffverse

For players lacking GSIS (e.g. certain prospects), create a deterministic provisional internal ID with namespace, never a bare normalized name.

### 2.2 Name fields

- `display_name`
- `first_name`
- `last_name`
- normalized name may be used for resolver candidates only

A normalized-name match is not authoritative without additional disambiguation such as team, position, birth year, college, or known ID map.

### 2.3 Resolver outputs

Every external record gets one status:

- `resolved_exact_id`
- `resolved_crosswalk`
- `resolved_reviewed_alias`
- `ambiguous`
- `unresolved`

Production model/artifact eligibility excludes ambiguous/unresolved records unless a documented non-player entity contract applies.

## 3. Draft-time anchor

Every historical player-season row has:

- `season`
- `anchor_at_utc`
- `feature_cutoff_rule_version`

Recommended anchor: a consistent date relative to Week 1, such as the Tuesday immediately before the opening game week, matching common final-draft timing. The exact rule must be applied historically without using future knowledge.

Current production inference uses the build timestamp/as-of date and current allowed data.

## 4. Historical feature entity

Logical key:

`(season, player_id, scoring_preset)` if scoring-dependent features are materialized; otherwise `(season, player_id)` with labels generated downstream.

Core descriptive fields:

```text
season
anchor_at_utc
player_id
display_name
position
team
age_at_anchor
experience_years
rookie_flag
```

Feature families should use explicit prefixes, for example:

```text
prev1_fantasy_ppg
prev2_fantasy_ppg
prev1_targets_pg
prev1_carries_pg
prev1_xfp_pg
prev1_snap_share
career_games
career_points_pg
age_position_z
team_change_flag
depth_rank_at_anchor
draft_round
draft_pick
combine_speed_score
prior_games_missed
```

Do not use cryptic numbered features in model cards.

## 5. Label entity

For each scoring preset:

```text
actual_fantasy_points
actual_games_played
actual_points_per_game
actual_vorp
actual_positional_rank
actual_overall_vorp_rank
```

Define fantasy scoring in one module with tests. Do not duplicate scoring formulas across notebooks/model code.

### Fantasy-season horizon

Use a documented fantasy-relevant horizon consistently. Recommended:

- modern 18-week NFL seasons: Weeks 1–17, excluding Week 18;
- older 17-week seasons: Weeks 1–16, excluding final NFL week;

This approximates common fantasy championship timing and prevents historical target drift. If a different horizon materially improves validity, document it as an ADR before changing.

## 6. Current projection contract

Internal projection record should contain:

```text
build_id
model_version
season
as_of_utc
player_id
display_name
team
position
scoring_preset
expected_points
p10_points
p25_points
p50_points
p75_points
p90_points
uncertainty_points
optional expected_games / game quantiles
quality_flags[]
```

Quantiles must be monotonic. Violations are critical.

## 7. Simulated league value contract

For each supported league preset:

```text
league_preset_id
player_id
expected_vorp
p10_vorp
p25_vorp
p50_vorp
p75_vorp
p90_vorp
fair_rank
position_rank
replacement_baseline_summary
```

`fair_rank` is 1-based, deterministic, and unique after documented tie-breaking.

Suggested tie order:

1. higher expected/median VORP
2. higher P50 points
3. lower uncertainty only if still tied
4. stable `player_id` lexical order

## 8. Tier artifact

See `schemas/tier_record.schema.json`.

Required semantic rules beyond JSON Schema:

- `fair_rank >= 1`
- one record per `(build_id, league_preset_id, scoring_preset, player_id)`
- tier index starts at 0 or 1 consistently; public field should expose label and ordinal
- fair ranks strictly unique within preset
- tier ordinals nondecreasing with fair rank
- all members of a tier occupy a contiguous fair-rank interval
- quantiles monotonic
- VORP values finite

## 9. Market snapshot contract

See `schemas/market_snapshot.schema.json`.

Core fields:

```text
source_id
snapshot_at_utc
source_as_of_utc
season
league_size
scoring_preset
player_id
market_adp
market_rank
sample_size
adp_sd or adp_low/adp_high when available
source_format_detail
quality_flags[]
```

ADP semantics must be standardized: lower pick = more expensive/earlier.

Never combine sources into one synthetic ADP without preserving components and method version.

## 10. Arbitrage artifact

See `schemas/arbitrage_record.schema.json`.

Core fields:

```text
build_id
league_preset_id
player_id
display_name
position
team
fair_rank
market_adp
market_rank
rank_gap
arbitrage_mode: baseline|ml
arbitrage_score
expected_surplus_vorp|null
p_positive_surplus|null
market_trend|null
confidence
quality_flags[]
```

`rank_gap` convention:

`market_adp - fair_rank`

Positive = model thinks the player is worth taking earlier than the market typically takes him (potential bargain).

## 11. Build metadata

See `schemas/build_metadata.schema.json`.

Include:

- `build_id`
- `generated_at_utc`
- `git_sha`
- `season`
- artifact schema versions
- production intrinsic model version
- production arbitrage mode/version
- supported presets
- source status array
- quality-gate summary
- warnings
- methodology version

Frontend freshness UI reads this file; do not hardcode update timestamps in JavaScript.

## 12. Data quality thresholds

Initial launch thresholds; tune only with evidence:

### Identity

- >= 95% of current model-eligible QB/RB/WR/TE players resolve canonically.
- 100% of players included in public top-150 overall output resolve canonically.
- zero ambiguous identities in public output.

### Duplicates

- zero duplicate canonical keys in model/public layers.

### Quantiles

- zero non-monotonic quantile records.

### Missingness

- required public fields: zero missing except explicitly nullable contract fields.
- optional model features may be missing only when the production estimator/pipeline intentionally supports it.

### Ranges

Examples:

- `market_adp > 0`
- ranks > 0
- probabilities in [0, 1]
- arbitrage score in [0, 100]
- games played within season maximum
- age plausible bounds

## 13. Contract versioning

Use semantic-ish integer strings for data contracts, e.g. `1.0`.

Public artifact top level or metadata must state schema version. Frontend rejects an unsupported major version with a clear error instead of attempting best-effort rendering.

## 14. Fixtures

Commit compact, hand-reviewable fixtures representing:

- normal veteran
- rookie/prospect
- player changing teams
- same/similar names collision
- missing optional advanced metric
- ambiguous external player mapping
- stale source metadata
- market player missing from intrinsic output
- intrinsic player missing market ADP
- extreme/late ADP
- legitimate single-player S tier

Fixtures must be synthetic or permitted excerpts small enough to comply with source terms.
