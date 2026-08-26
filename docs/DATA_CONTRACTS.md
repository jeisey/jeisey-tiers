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

> **Phase-1 implementation (ADR-019).** `ffdraft.identity` emits a `ResolutionOutcome` per external record carrying the status above plus a machine-readable `reason`, the bridges that agreed or disagreed, name candidates as diagnostics, and quality flags. Three details are load-bearing:
>
> - a non-resolved outcome **cannot** carry a `player_id` — the type rejects it, so a caller can never use a value the resolver refused to stand behind;
> - `resolved_reviewed_alias` comes only from `config/identity-aliases.yaml`, a human-reviewed file. An alias never overrides an id bridge: if the bridges resolve to a different player the record fails closed as `ambiguous` (`alias_conflicts_with_bridge`), so a stale entry cannot outvote live data. Both the production capture (`ffdraft.market.capture.build_snapshot`) and the fixture pipeline load that file by default; between Phase 1 and 2026-08-26 the capture did not, which meant the escape hatch existed everywhere except where snapshots are actually taken (ADR-054). An alias can only target a player the registry already knows — the registry is built from the current roster, so an unrostered player cannot be aliased into existence and fails `alias_target_unknown`;
> - team units (MFL `Def`/`TM*`) are classified as the documented non-player entity contract and reported separately from identity failures, rather than depressing the coverage metric.

## 3. Draft-time anchor

Every historical player-season row has:

- `season`
- `anchor_at_utc`
- `feature_cutoff_rule_version`

Recommended anchor: a consistent date relative to Week 1, such as the Tuesday immediately before the opening game week, matching common final-draft timing. The exact rule must be applied historically without using future knowledge.

Current production inference uses the build timestamp/as-of date and current allowed data.

> **Phase-2 implementation (ADR-021).** The rule is fixed at `draft_anchor_v1_tuesday_eod_pre_week1`: **23:59:59 America/New_York on the Tuesday immediately preceding the earliest Week-1 regular-season kickoff**, persisted as UTC. `ffdraft.anchors` derives it from `load_schedules` — the Week-1 date is published in May, so reading it is preseason context, not an outcome — and refuses to construct an anchor that does not strictly precede the first kickoff. Measured over 2014-2025 the lead time is 1.85 days in every season. The version string travels on every feature row, and changing the rule requires a new version plus a new ADR; in particular it may not be tuned after seeing model performance.

### 3.1 Preseason eligibility (ADR-022)

The row list is itself a leakage surface. A `(season, player_id)` row exists only when pre-anchor evidence says the player was in the league, and the row records which evidence applied in `eligibility_basis`:

| Basis | Evidence | Available |
|---|---|---|
| `prior_season_roster` | on an NFL roster in season Y-1 | every season |
| `draft_class` | selected in the season-Y NFL draft | every season |
| `depth_snapshot_pre_anchor` | on a timestamped depth chart with `observed_at <= anchor` | 2025 onward only (ADR-015) |

`load_rosters(Y)` and `load_rosters_weekly(Y)` week 1 are **not** used. A week-1 roster carries no observation timestamp, so nothing establishes it was settled by the anchor, and letting eventual participation choose the training rows is survivorship bias. Each season also records `universe_era` (`lagged_only` or `snapshot_2025_plus`) so the boundary is filterable rather than hidden.

## 4. Historical feature entity

Logical key:

`(season, player_id, scoring_preset)` if scoring-dependent features are materialized; otherwise `(season, player_id)` with labels generated downstream.

> **Phase-2 implementation (ADR-023).** Three normalized grains rather than one wide table:
>
> | Table | Grain | Contract |
> |---|---|---|
> | `features.parquet` | `(season, player_id)` — scoring-independent | `historical_features` 1.0 |
> | `labels_fantasy.parquet` | `(season, player_id, scoring_preset)` | `historical_fantasy_labels` 1.0 |
> | `labels_vorp.parquet` | `(season, player_id, scoring_preset, league_preset_id)` | `historical_vorp_labels` 1.0 |
>
> Football features do not depend on scoring, and realized replacement value depends on roster construction as well as scoring, so one wide table would repeat every feature nine times to carry two columns that vary. The feature table's columns are generated from `ffdraft.features.dictionary`, published as `docs/FEATURE_DICTIONARY.md`, and a test asserts the two agree. The prior-production columns (`prev1_fantasy_points_std` / `_ppr`) are the deliberate exception to scoring independence: half-PPR is exactly their mean, so two columns serve all three presets.

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

> **Phase-2 implementation.** The built column set is `docs/FEATURE_DICTIONARY.md`, generated from `ffdraft.features.dictionary` with a test asserting the two agree. The names above are the sketch; the dictionary is the contract.
>
> **Phase-3 model-input view.** A second, narrower contract sits on top of it: `intrinsic_core_v1` in `ffdraft.modeling.features`, the versioned and hashed set of columns a Phase-3 model may consume. It is a strict subset of the Phase-2 model inputs — 78 of 85 — and both its hash and its full included/excluded lists appear in every experiment report and will appear in every promoted model artifact. Two columns named in the sketch above, `team_change_flag` and `depth_rank_at_anchor`, are deliberately **not** in it: they exist only in the 2025 snapshot era, which is the sealed final holdout, so no development fold can validate them (ADR-025, ADR-026). They remain in the dataset as context.

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

> **Phase-2 implementation.** `ffdraft.scoring` owns the arithmetic and the horizon, and labels are aggregated from **weekly** rows because season-level upstream totals already include the excluded final week. Two consequences are worth stating:
>
> - **nflverse `fantasy_points` is a sanity comparison, never the label.** It covers the full regular season *and* awards six points for return touchdowns, which `config/league-defaults.yaml` does not define. `reconcile_with_upstream` proves the gap is exactly return touchdowns rather than reporting a vague mismatch — across 2014, 2020 and 2024 the residual after accounting for them is zero on every row.
> - **Lagged production features use the same horizon as the label**, so a prior-production baseline compares like with like.

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

> **Phase-4 implementation.** `projections.json`/`.csv` carry exactly this record, one row per
> player and scoring preset, with `expected_points` computed from the Monte Carlo draws rather
> than from the quantiles and `uncertainty_points` = `p75_points - p25_points`. Monotonicity is
> guaranteed upstream: the promoted architecture's quantiles are empirical quantiles of one
> sample, and the isotonic projection is applied regardless as a safety net.

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

> **Phase-4 implementation.** `ffdraft.simulation.vorp.fair_ranking` implements exactly that
> order, and which statistic occupies step 1 is the frozen decision in ADR-034 rather than a
> per-call choice. `uncertainty` is the interquartile range of simulated VORP. A player whose
> position had no replacement baseline in any draw sorts last and is withheld from the
> published board with a counted quality check, because a null VORP is a statement about the
> league's depth rather than about the player.

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

> **Phase-4 implementation.** The production build publishes the top 300 fair ranks per
> `(league preset, scoring preset)`, which covers every pick of the deepest launch preset
> (14 teams x 13 roster slots = 182) with headroom while keeping segmentation on the part of
> the board a drafter reads. Tier ordinals are contiguous by construction - the segmentation
> assigns them along the fair-rank-ordered board - so the validator's contiguity rule is a
> check on the serializer rather than on the algorithm. `tier_label` comes from
> `ffdraft.tiers.labels` and is presentation only.

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

### 9.1 Retained snapshots (Phase 5)

The *public* market snapshot record above and the *retained* history are different things. Retention is append-only on the `market-data` branch under the layout in `docs/ARCHITECTURE.md` 6.2, and its record shape is the normalized market quote (`market_quote` contract **2.0**) plus its identity outcome, not this artifact schema.

Contract 2.0 replaces `scoring_preset`, `league_size` and `cohort_approximate` with `cohort_id`. A quote belongs to a *cohort request*; whether that cohort is an exact match for a published preset is a per-preset verdict the frozen selection rule reaches later (ADR-039). Making a row claim a preset it did not describe was the failure ADR-012 was written to prevent.

Unresolved and team-unit rows are retained too, with a null `player_id` and their refusal reason. A snapshot is evidence; dropping the rows that did not join would hide the coverage question a later session needs to answer.

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

### 10.1 Record contract 1.1 (Phase 5)

`arbitrage_record` moves to **1.1**. Record schemas now version independently of the envelope: the envelope's `schema_version` is the bundle version (still 1.0) and `ffdraft.artifacts.RECORD_SCHEMA_VERSIONS` maps each record schema to its own, mirrored in `web/src/data/contracts.ts` and pinned by tests on both sides.

Added fields, all required, all so a row can be judged without a second fetch:

```text
regional_value_gap        ln(market_adp / fair_rank); the A0 draft-region gap (ADR-040)
market_adp_low            minPick; an extreme order statistic, not a standard deviation
market_adp_high           maxPick
market_source_id          which source priced this row
market_cohort_id          which cohort request the price came from
market_cohort_detail      the filters actually sent, plus exact|approximate
market_snapshot_at_utc    when the retained snapshot was taken
```

`market_adp_sd` stays null and the schema now enforces it conditionally: a row whose `market_source_id` is `myfantasyleague_adp` must carry a null, because that source publishes no standard deviation.

`player_status` (1.0) is a new artifact, keyed once per canonical `player_id` and joined in the browser. It is **annotation only**: no field in it participated in producing a projection, a fair rank, a tier or an arbitrage score, and a test proves it by mutating every field and asserting the other artifacts are byte-identical (ADR-043).

`build_metadata` gains three optional blocks — `arbitrage_method_version`, `market` and `player_status` — so a build that produced only the intrinsic board still validates. An arbitrage build **merges** into that file rather than rewriting it, because a rewrite would erase the Phase-4 tier-stability warning (ADR-035).

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

### 12.1 Phase-2 historical thresholds

The Phase-2 gate's thresholds live in `ffdraft.quality.thresholds` as `HistoricalThresholds`, and every one is printed in the quality report with the reason it sits where it does. Each was set from a measurement on the real 2014-2025 dataset **plus deliberate headroom**, never from what the current build happens to score:

| Threshold | Bound | Observed | Basis |
|---|---:|---:|---|
| canonical key coverage | >= 1.0 | 1.0 | The universe is assembled only from GSIS-keyed sources, so anything less is a construction bug. |
| duplicate `(season, player_id)` | 0 | 0 | Named by the Phase-2 exit gate. |
| `age_at_anchor` coverage | >= 0.93 | 0.967 (worst season 0.925) | The gap is 380 deep fringe roster entries for whom no nflverse source publishes a birth date. |
| snap-count bridge coverage | >= 0.90 | 0.977 | Snap counts are keyed by `pfr_id` and must cross an id space; this is the identity join that can genuinely fail. |
| ffopportunity coverage | >= 0.80 (warning) | 0.954 | ffopportunity models only plays it can attribute, so some gaps are legitimate. |
| label coverage | >= 1.0 | 1.0 | A missing label is a join failure; a player who did not play scores zero. |
| season row-count tolerance | <= 0.35 of median (warning) | fires on 2014-2016 | Wide enough for a genuine era change, narrow enough to catch a truncated source. |

A **fixture profile** (`HistoricalThresholds.fixture()`) loosens the statistical thresholds for the deliberately adversarial synthetic fixtures, which are far too small for a production coverage rate to mean anything — the same reasoning Phase 1 recorded for `FIXTURE_IDENTITY_COVERAGE_MINIMUM`. The structural thresholds (canonical key, duplicates, label coverage) do not relax at all, and a test asserts the fixture profile is strictly looser than production on exactly the statistical ones.

### 12.2 Semantic and domain checks

Structural checks catch a column that disappears. `ffdraft.quality.semantic` adds the layer that catches a column that keeps its name, its dtype and its plausibility while its *meaning* changes: categorical-domain validation for positions, teams, depth states and scoring presets; `[0, 1]` bounds on every share and rate; non-negativity on counting statistics; plausible ranges on draft round, combine forty and depth rank; derived-ratio minimum denominators; season/week consistency; impossible age/experience/draft combinations; per-column missingness budgets; per-season row-count anomalies; and informational per-season/per-position distribution summaries. A fixture in which every column exists, every dtype is right and every *value* violates its contract proves the class is detectable.

## 13. Contract versioning

Use semantic-ish integer strings for data contracts, e.g. `1.0`.

Public artifact top level or metadata must state schema version. Frontend rejects an unsupported major version with a clear error instead of attempting best-effort rendering.

### 13.1 The artifact envelope (ADR-020)

Every records-bearing artifact is wrapped in the envelope described by `schemas/artifact_envelope.schema.json`:

```json
{
  "schema_version": "1.0",
  "artifact": "tiers",
  "record_schema": "tier_record",
  "build_id": "...",
  "generated_at_utc": "2026-08-18T12:00:00Z",
  "record_count": 32,
  "arbitrage_mode": "baseline",
  "records": [ ... ]
}
```

The record schemas in `schemas/` are unchanged — they describe one record and the envelope wraps them. Validation is therefore two steps: the envelope against its own schema, then every record against its record schema. Keeping the version outside the records is what lets a frontend reject an unsupported major version before parsing a single record.

`build_metadata.json` is a bare object rather than an envelope: it *is* the metadata, and it carries its own `schema_version`.

### 13.1.1 Source contract changes in Phase 2

Two Phase-1 source contracts changed when historical data exposed grains the 2026-only fixtures could not:

- **`nflverse_roster` 1.0 -> 1.1.** The primary key gains `team`. A player traded mid-season appears once per club, which is not a duplicate: 99 such rows in 2014 and 125 in 2015. Consumers that want one row per player must now say which one they want.
- **`ffopportunity_expected_points` 1.0 -> 1.1.** The primary key gains `position`. A two-way player can receive one expected-points row per position in the same week, and summing the split attributions would double-count a single set of opportunities; `expected_points_by_season` reduces to one row per player-week by taking the largest attribution, with the position name breaking ties.

Separately, `load_draft_picks` and `load_combine` publish Pro Football Reference team abbreviations (`GNB`, `LVR`, `SDG`) while everything else speaks nflverse's (`GB`, `LV`, `LAC`). `ffdraft.contracts.enums.normalize_team_code` maps them, and a domain check over `team_at_anchor` and `prev1_team` catches anything outside the league vocabulary — two abbreviations in one column being exactly the semantic drift section 12.2 exists to notice.

### 13.2 Serialization rules

- **Column order is the schema's property order.** The CSV serializer reads it out of the JSON Schema rather than restating it, so JSON and CSV cannot drift and a reordering is a visible schema edit.
- **Row order is the artifact's declared total ordering**, always ending in `player_id`. Identical inputs therefore produce byte-identical files, which is what `docs/ARCHITECTURE.md` section 13 means by reproducible.
- **Arrays render as `|`-joined values in CSV**; nulls render as an empty cell; booleans as `true`/`false`.
- **Nothing is written until it validates.** A failed check leaves the previous artifacts in place (`docs/OPERATIONS.md` section 8).

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

> **Phase-2 fixture set.** `tests/fixtures/historical/` carries synthetic nflverse-shaped source rows for two target seasons — 2024 in the lagged-only era and 2025 in the snapshot era — read through the real adapters so the integration test exercises the production code path without a network. Its README names which invented player carries which case, including the identity collision, the undrafted rookie visible only on a pre-anchor depth chart, the player with no birth date anywhere, and the eligible player who records nothing all season.

> **Phase-1 fixture set.** `tests/fixtures/pipeline/` carries every case above, entirely synthetic, with a table in its README naming which player or record carries which case. `tests/fixtures/pipeline/collisions/` holds deliberately broken identity inputs used only by the fail-closed tests. `tests/fixtures/artifacts/` holds the committed golden output of the fixture pipeline; the frontend tests read it, so the TypeScript types and the Python serializers are checked against the same bytes. Regenerate it with `uv run ffdraft build-fixture-artifacts --out tests/fixtures/artifacts --git-sha 0000000`.
