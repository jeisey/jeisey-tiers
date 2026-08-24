# Session State

This file is durable cross-session state for coding agents. Keep it concise and factual.

## Current phase

Phase 7 — **complete** (2026-08-22; owner actions completed the same day). The site is live at **<https://jeisey.github.io/jeisey-tiers/>**, public, and refreshing itself daily at 07:17 America/New_York from sources it captures into a private store. Phase 8 (hardening, and the owner's live UI feedback) has not been started.

**The phase did not start where its task list said it did.** The append-only capture store lived on a `market-data` branch of this repository, and ADR-038's own consequences said that was safe *because the repository is private*. GitHub visibility is a property of a repository, not of a branch — there is no private branch inside a public repository — so going public would have published thousands of retained MyFantasyLeague payloads and normalized Sleeper rows, which are a private research cache under non-commercial terms. Excluding the branch from the Pages artifact would have done nothing, because `git clone` hands any visitor every branch. The store had to move first (ADR-049), and that reordered everything after it.

Three things are worth carrying forward as ideas rather than as file paths:

1. **Last-known-good is a job graph, not a checklist** (ADR-050). `capture → build → deploy`, the deploy job contains only the Pages actions, and nothing anywhere clears the live site before a new one validates. "A gate failed" and "the previous site is still serving" are therefore the same event rather than two facts that have to agree — and it has now held three times in production, twice for defects nobody designed a test for.
2. **The forced-failure proof breaks a real invariant.** It corrupts quantile monotonicity in a generated artifact and lets the ordinary validator reject it, so what stops the deploy is `artifact.non_monotonic_quantiles` — a production critical check — not an `exit 1` added for the test.
3. **Splitting the data out made permissions narrower, not wider.** The capture job used to need `contents: write` here; it now needs `contents: read` plus a token scoped to one other repository.

## Current target gate

Phase 8 — hardening and quality. Its first input is `docs/PHASE8_UI_FEEDBACK.md`, which is seeded and waiting for the owner to use the live site. **Read that file before touching the frontend**: the Tier Board's vertical density, the tier lane treatment, the Draft Rail and the player card are all recorded there as things a human intends to judge in person, and Phase 7 deliberately did not pre-empt any of them.

The visibility question ADR-016 deferred is closed: the repository is **public**, serving a public Pages project site from standard GitHub-hosted Actions, free and non-commercial — which is a licence condition rather than a preference, because `player_status.json` carries Sleeper fields to every visitor.

## Last validated commit

The Phase-7 branch `claude/fantasy-draft-phase-7-ktp7qm`, branched from the merged Phase-6 state on `main` (`86e2857`).

```
uv sync --frozen
uv run ruff check .                 # clean
uv run ruff format --check .        # clean
uv run mypy                         # clean, strict, 110 source files
uv run pytest                       # 1013 selected, all pass (4 live-network deselected)
uv run ffdraft config-check

# The retained store, now a separate PRIVATE repository (ADR-049)
git clone https://github.com/jeisey/jeisey-tiers-market-data ../market-data
uv run ffdraft validate-market-history ../market-data --season 2026   # 3 snapshots, 3 status captures: pass

npm ci
npm run lint            # clean (2 known React-Compiler/TanStack warnings, ADR-048)
npm run typecheck       # clean, strict
npm run test -- --run   # 194 frontend tests
npm run build                                    # root base path
VITE_BASE_PATH=/jeisey-tiers/ npm run build      # project Pages base path
npm run e2e             # 39 Playwright tests over five built sites
```

**One environment note that cost time and should not cost it again.** This sandbox ships Chromium build 1194 at `/opt/pw-browsers` while the pinned Playwright 1.62.1 wants 1234, so `npm run e2e` fails every test with "Executable doesn't exist" until `PLAYWRIGHT_CHROMIUM_EXECUTABLE=/opt/pw-browsers/chromium-1194/chrome-linux/chrome` is exported. `playwright.config.ts` already reads that variable. And **`npm run e2e | tail` reports `tail`'s exit code, not Playwright's** — without `set -o pipefail` a completely red suite looks green. On the runner neither applies: `npx playwright install` fetches the matching build.

`build-current`, `build-arbitrage` and `verify:board` on real data are **runner-only** here: the sandbox answers 403 to CONNECT for nflverse, MyFantasyLeague and Sleeper (ADR-009), which is the whole reason source work happens in Actions.

## Production status

**A production model and a production arbitrage board exist.** `intrinsic-cb-hurdle-v1`, trained on 2014-2025, promoted through a sealed single-use holdout, serving a 2026 board for every launch preset; and the deterministic A0 arbitrage baseline built on top of it from retained market history. There is still no deployed site.

- `models/production/intrinsic-cb-hurdle-v1/` — **committed**, not gitignored (`PRD.md` section 15). 120 gzipped LightGBM boosters plus `metadata.json` carrying the spec, seed, training seasons, library versions, dataset manifest, `feature_set_hash` `7203befaa5be25a2`, `feature_schema_hash` `c495ba3177dcb989` and a SHA-256 per booster. No pickles anywhere: loading reads JSON and LightGBM's documented text format, and a tampered booster fails closed.
- `models/cards/` — the model card and the tier-method report, generated from the committed experiment reports and the artifact, never hand-written.
- `models/cards/arbitrage-method-a0.{json,md}` — the arbitrage method card, generated from the artifacts, the cohort report and the frozen constants.
- `web/public/data/` — the 2026 build: `tiers`, `projections`, `arbitrage`, `player_status`, `build_metadata`. Gitignored and reproducible.
- **`jeisey/jeisey-tiers-market-data`** — the append-only point-in-time capture store, a private repository since Phase 7 (ADR-038 as amended by ADR-049). Not in this working tree; clone it separately.

The fixture stub `fixture-stub-0` is gone from the production path, and so is the Phase-1 stub arbitrage score: the fixture pipeline now drives the real A0 code.

What was there before and still is:

- `src/ffdraft/` — config, contracts, sources, identity, quality, artifacts, pipeline, CLI (Phase 1) plus `anchors.py`, `scoring/`, `features/`, `labels/`, `simulation/`, `leakage.py` (Phase 2) plus `modeling/` (Phase 3) plus `market/`, `arbitrage/`, `status/`, `retention/` and `pipeline/market.py` (Phase 5).
- `data/historical/` — the modelling dataset. Gitignored and reproducible; see "Phase-2 dataset" below.
- `docs/FEATURE_DICTIONARY.md` — every model feature with formula, sources and availability rule, generated from code and pinned by a test.
- `docs/experiments/phase3-intrinsic-baselines/` — the committed Phase-3 experiment reports, machine-readable and human-readable. Row-level predictions are gitignored.
- `.github/workflows/` — `ci.yml` (fixture-only gates, no vendor network, no store credential), `daily-refresh.yml` (the production path), `retrain.yml` (an evidence gate that mostly declines), `market-capture.yml` (out-of-band capture) and `source-probe.yml` (Phase-0). `.github/actions/market-data-store/` is the one way any of them reaches the private store.
- `docs/visual-qa/` — committed screenshots and the written review, regenerated with `npm run e2e:screens`.
- `scripts/workflow_summary.py` and `scripts/retrain_gate.py` — the two Phase-7 gate/report scripts, both runnable locally.
- `web/` — the Phase-6 draft sheet: `src/data/` (contracts, loader, indexes, market derivations, flags, formats, CSV, URL state), `src/app/` (shell, controls, two tables, player detail, data view), `src/charts/` (Tier Board, Draft Rail), `src/components/`, `src/styles/base.css`.
- `tests/` — 991 network-free Python tests (4 live-network deselected); `web/tests/` adds 194 vitest plus 39 Playwright.
- `docs/experiments/` — four committed experiment report pairs: the Phase-3 baselines and the three Phase-4 studies, plus the single final-holdout report. Row-level predictions are gitignored.

## Phase-2 dataset — the validated build

Target seasons **2014-2025**, positions QB/RB/WR/TE. Source windows: statistics 2009-2025 (the deepest declared lookback is five seasons), rosters 2013-2024 (always the *previous* season), depth charts 2025 only (the one target season with timestamped snapshots).

| Season | Rows | Rookies | Observed depth | Role proxy | No depth | Zero-point share (PPR) |
|---:|---:|---:|---:|---:|---:|---:|
| 2014 | 672 | 75 | 0 | 538 | 134 | 34.7% |
| 2015 | 667 | 78 | 0 | 537 | 130 | 33.1% |
| 2016 | 684 | 77 | 0 | 543 | 141 | 36.0% |
| 2017 | 1056 | 83 | 0 | 562 | 494 | 53.4% |
| 2018 | 1078 | 83 | 0 | 566 | 512 | 54.1% |
| 2019 | 1092 | 80 | 0 | 583 | 509 | 54.6% |
| 2020 | 1065 | 77 | 0 | 586 | 479 | 50.2% |
| 2021 | 1056 | 75 | 0 | 626 | 430 | 46.9% |
| 2022 | 1008 | 79 | 0 | 671 | 337 | 47.2% |
| 2023 | 1073 | 80 | 0 | 625 | 448 | 53.2% |
| 2024 | 1050 | 77 | 0 | 617 | 433 | 51.7% |
| 2025 | 1103 | 106 | 549 | 197 | 357 | 51.7% |

Quality metrics over the whole dataset: canonical key coverage 1.0, duplicate `(season, player_id)` keys 0, `age_at_anchor` coverage 0.967, snap-count `pfr_id` bridge coverage 0.977, ffopportunity coverage 0.954, label coverage 1.0 for every scoring and league preset. Excluded candidates: 25,476 non-core positions, 15 with no anchor-safe position, 12 with no canonical id, 1 ambiguous identity.

Anchors (all rule `draft_anchor_v1_tuesday_eod_pre_week1`, lead time 1.85 days in every season): 2014-09-03T03:59:59Z through 2025-09-03T03:59:59Z.

## Phase-3 results — the frozen evaluation

Development folds 2020-2024 (plus W1-only diagnostics 2017-2019), 468 evaluation cells, seed 20260819, 1000 bootstrap replicates. Season **2025 is sealed and was not evaluated**.

Macro aggregates over season x position x scoring, window `W1_all_history`:

| Model | MAE | RMSE | Spearman | Kendall | Top-K | Pinball | P10-P90 cov | P10-P90 width | Raw crossing |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| B0 | 25.60 | 44.06 | 0.659 | 0.524 | 0.535 | 9.98 | 0.793 | 83.1 | 0.000 |
| B1 | 26.98 | 42.21 | 0.711 | 0.550 | 0.593 | 9.74 | 0.798 | 80.4 | 0.000 |
| **Q1** | **22.07** | **41.03** | **0.726** | **0.570** | 0.544 | **8.13** | 0.771 | 62.7 | 0.387 |

Paired deltas against B0 under W1: MAE **-3.53** (95% CI -3.87 to -3.18), mean pinball **-1.85** (-1.98 to -1.72), Spearman **+0.066** (+0.058 to +0.075). Q1 passes the frozen gate under **both** windows; B1 fails under both, losing to B0 on MAE at every position.

Per position under W1 (B0 -> Q1): QB 39.50 -> 34.50 MAE, RB 27.38 -> 23.10, TE 14.80 -> 13.00, WR 20.73 -> 17.68; Spearman 0.642 -> 0.670, 0.641 -> 0.742, 0.665 -> 0.742, 0.689 -> 0.748. No position triggers the collapse rule. Per scoring preset the ordering is identical (PPR is the hardest: Q1 MAE 24.40 against STD's 19.78, which is scale, not skill).

Training window (ADR-028): W1 beats W2 on the common folds with Q1 by MAE **-0.286** (-0.474 to -0.107) and pinball **-0.083** (-0.134 to -0.037), Spearman indistinguishable. Per fold the MAE advantage is -0.911 (2020), -0.023 (2021), -0.024 (2022), -0.158 (2023), -0.315 (2024) - concentrated in the fold where W2 has only three training seasons, which is the honest reading of *why* W1 wins.

Selected for Phase 4 (ADR-029): **Q1**, window **W1**, feature set `intrinsic_core_v1` (`7203befaa5be25a2`), 78 inputs.

## Phase-4 results — the frozen production system

Development folds 2020-2024, seed 20260819, 1000 bootstrap replicates. Every decision below was made by a rule written into `ffdraft.modeling.rules` **before** the run that decided it, and the whole set was committed at `2f0e725` before 2025 was opened.

| Decision | Rule | Outcome |
|---|---|---|
| calibration | `phase4_calibration_v1` | monotone (PAV) projection only; the fitted conformal layer was measured and refused |
| target scale | `phase4_horizon_v1` | season total; horizon normalization refused on both declared routes |
| architecture | `phase4_candidate_v1` | **CB**, availability x performance hurdle |
| draw count | `phase4_convergence_v1` | 10,000 — **by the fallback clause; no count passed** |
| fair rank | `phase4_ranking_v1` | median simulated VORP; expected VORP refused |
| tier penalty | `phase4_tier_v1` | 1.0, the only admissible penalty in the grid |
| tier stability | `phase4_tier_stability_v1` | **FAIL** on boundary agreement, after escalating from PELT to dp_quantile |
| final holdout | `phase4_final_holdout_v1` | **PASS** |

**Development macro aggregates (CB vs the A0 direct-quantile candidate):** MAE 21.91 vs 22.11, pinball 8.080 vs 8.142, Spearman 0.750, top-K 0.577, P10-P90 coverage 0.827, raw crossing rate **0.000** (against Q1's 0.387). Paired deltas: pinball -0.0614 [-0.1002, -0.0236], MAE -0.205 [-0.332, -0.073], Spearman +0.0298, top-K +0.0326.

**Final holdout, 2025, run once (ADR-036):** CB MAE 20.19 vs B0 23.93; pinball 7.197 vs 9.331; Spearman 0.780 vs 0.679; P10-P90 coverage 0.845 against nominal 0.80; width 56.9 vs 80.7. Paired: MAE **-3.738** [-4.364, -3.102], pinball **-2.134** [-2.377, -1.874], Spearman **+0.1015**. CB improves MAE and pinball on **all eleven** predeclared slices; rookies go 34.29 -> 29.83 MAE with coverage 0.675 -> 0.747.

**The two failures, in the units that matter.**

- *Convergence.* Ranking tolerances pass comfortably (fair-rank Spearman 0.99993 between seeds, top-50 overlap 0.96+); value tolerances miss by 10-20% (mean |Δ expected VORP| 0.29-0.31 against 0.25); the tier clause misses badly (ARI 0.50-0.75 against 0.90). More draws would close the value gap; they would not close the tier gap, because a boundary is a discrete cut on a nearly continuous curve.
- *Tier stability.* Boundary agreement 0.239 against 0.500. Everything else passes: ARI 0.865, singleton rate 0.040, tier-count CV 0.045, monotonic pairs 0.845, cross-preset ARI 0.529. Across 1,200 replicates the segmentation used 283 of 299 cut sites and only 4 survived in a majority (ranks 267, 99, 16, 68). The median promoted boundary sits on a 0.55-point P50 cliff against an 80-130 point interval, and P(player below outscores player above) is 0.497.

**The 2026 board looks right.** PPR/redraft-12 top eight: Bijan Robinson, Amon-Ra St. Brown, Ja'Marr Chase, Jahmyr Gibbs, De'Von Achane, Puka Nacua, Jaxon Smith-Njigba, CeeDee Lamb. Top 12 is 6 RB and 6 WR; the first QB is 15th (Josh Allen) and the first TE 19th (Trey McBride), which is the correct shape for a 1-QB league where those positions' VORP is compressed. Tier sizes 8/14/25/33/29/42/45/69/35. 34 rookies make the 300-deep board, the best at rank 72. Zero quantile-monotonicity violations, zero non-finite values.

## Phase-5 results — market history, cohorts and the arbitrage baseline

Every rule was frozen at `455f08b` before it had been run against live data.

**The store.** Two real 2026 snapshots on the `market-data` branch:

| snapshot | commit | contents |
|---|---|---|
| `2026-08-20T14-11-48Z` | `36303e6` | 13 cohorts, 3,293 normalized rows, 2,606-row player directory |
| `2026-08-20T14-38-44Z` | `57ee0c1` | 16 cohorts, 4,110 normalized rows |
| `status/sleeper/2026/2026-08-20T14-12-17Z` | `36303e6` | 12,240 normalized status rows |

`validate-market-history` re-hashes all 35 files clean. Roughly 590 KB per study capture; a production capture (three cohorts) is far smaller.

**The cohort measurement** (`docs/market-cohorts/2026-08-20/`, reproducible offline from the retained snapshot). Aggregate volume has barely moved since Phase 0: 426 drafts against 410. Exact scoring × league-size intersections are still thin or empty, so ADR-012 stands. Two things the measurement found that Phase 0 could not:

- **`IS_MOCK=0` is inert** — 426 drafts, byte-identical to unfiltered. No mocks in the aggregate.
- **`IS_KEEPER=N` returns 125 drafts, and the other 301 are dynasty rookie drafts.** 2026 rookies price three to five times earlier in the aggregate than in the keeper-free cohort while established veterans do not move at all. Ty Simpson 35.6 → 162.3; Emmett Johnson 50.4 → 193.1; Bijan Robinson 2.5 → 2.6. In a dynasty rookie draft only rookies are selectable, so a rookie's `averagePick` there is a pick number in a rookie-only draft.

That produced ADR-045 and `phase5_cohort_v2`: a redraft board may only be priced by a keeper-free cohort. **No bound moved.** Every keeper-free cohort then fails `min_total_drafts` (125 and 115 against 300), so the rule falls through to its documented last resort and flags the result.

**Identity coverage depends on the population counted**: ~87% over the whole priced payload, **98.2–98.5%** over the QB/RB/WR/TE rows the board is made of. MFL also prices kickers, team defences and IDP. The rule counts the core positions its clauses are written about (ADR-039 clarification).

**Per-player sample is the statistic that matters.** Medians over the priced top-150: unfiltered 141, `IS_PPR=1` 129, `IS_KEEPER=N` **105**, `FCOUNT=12` 62, `FCOUNT=14` 7. That `no-keeper` scores 105 on the direct measure while failing a cohort-level bar of 300 is the open question ADR-045 records and deliberately does not answer.

**The 2026 arbitrage board.** 2,124 rows across nine preset blocks, `a0_rank_gap_v1`, built from snapshot `2026-08-20T14-38-44Z`. Confidence: 2,124 `low`, all for the same recorded reason. Trend: null on every row — the store holds two snapshots against a requirement of three observation days spanning three days. 42 top-150 board players carry no price and are excluded rather than filled in.

PPR/redraft-12, the biggest signals, and why they are believable:

| | player | fair rank | ADP | gap | score |
|---|---|---:|---:|---:|---:|
| bargain | Amon-Ra St. Brown | 2 | 10.5 | +8.5 | 99.8 |
| bargain | De'Von Achane | 4 | 18.5 | +14.5 | 99.0 |
| premium | Joe Burrow | 234 | 28.1 | −205.9 | 0.2 |
| premium | Jayden Daniels | 267 | 34.5 | −232.5 | 0.6 |
| premium | Christian McCaffrey | 43 | 12.9 | −30.1 | 1.9 |

The quarterbacks are the known 1-QB-league VORP compression from Phase 4, not a defect: the model ranks them where their league-relative value sits and the market takes them where positional scarcity feels. McCaffrey is `Questionable/Undisclosed` in the status artifact — which is exactly the join Phase 6 exists to render.

**Player status.** 315 rows for the published board, 309 matched through `sleeper_id`, one failed the `gsis_id` cross-check closed. 61 players carry an `injury_status`, 13 carry `injury_notes`. `injury_start_date`, `practice_participation` and `practice_description` are published by Sleeper as keys with null values across the whole preseason payload; they are normalized anyway because Sleeper declares them and they populate in season.

## Phase-6 results — the draft sheet

Built against the real 2026 build, in ADR-008's order: tables first, because a table is the truth surface a chart is checked against.

**What shipped.** One page, three tabs, state in the URL.

| Surface | What it does |
|---|---|
| Tier board | Tier groups as soft bands over a **median simulated VORP** axis, P25-P75 interval per player, position-coloured marks with position rank, one tab stop with arrow-key movement. Defaults to the top 100; a shareable control shows the whole board. |
| Tier table | TanStack v8, default `fair_rank` ASC, sticky header, 11 columns, ~38px rows. The canonical accessible equivalent of the board. |
| Draft rail | Paired anchors per player — filled diamond for fair rank, open circle for MFL ADP — with a signed sentence per row (`+14.5 picks later`). Bargains / Premiums / All, top 30. |
| Arbitrage table | Default `arbitrage_score` DESC. **No** surplus columns: V1 has no learned model and will not grow a header for one. |
| Player detail | One `<dialog>` reachable from all four surfaces: intrinsic, market and current-status sections, with the annotation-only disclosure standing in the status section. |
| Data | Definitions, the build read from metadata, a source freshness table, market provenance, ten current limitations and source attribution. No metric is hardcoded; the model cards are linked. |
| Export | `Download full CSV` links the artifact the build wrote; `Export filtered CSV` writes exactly the visible rows in visible order, named `ffdraft-<board>-<scoring>-<teams>-<build date>.csv`. |

**Verified against the real artifacts** (`npm run verify:board`, 0 disagreements): 40 tier rows, 25 chart-mark labels, 30 arbitrage rows and 56 injury badges match `tiers.json`, `arbitrage.json` and `player_status.json` exactly. The 2026 PPR/redraft-12 board renders 300 tier rows, 238 priced arbitrage rows and the expected quarterback premiums (Joe Burrow −207.9, Jayden Daniels −230.5, Christian McCaffrey −31.1 picks).

**Two contract corrections the frontend surfaced.**

- `build_metadata.market.assignments[]` now carries `failed_clauses` — the frozen rule's own words, e.g. `total_drafts 125 < 300`. Without it the UI would have to hardcode today's measurement to explain a low-confidence board (ADR-047). The market block was already `additionalProperties: true`, so no version moved; the schema now declares the field.
- `expected_games` is **optional** in `player_projection.schema.json` and the production current build omits it while the fixture pipeline emits it. `web/src/data/contracts.ts` claimed it was always present; it is now optional there too.

**Visual QA found nine real defects**, all fixed and written up in `docs/visual-qa/2026-08-21/REVIEW.md`. The two worth remembering: the Tier Board was scaled to P10-P90 while drawing P25-P75, which parked every median in the middle third of the plot; and the arbitrage page scrolled sideways by ~700px on a phone because `.table-scroll` was not a containing block, so the absolutely positioned screen-reader-only spans inside its cells escaped the scroller and dragged the document's scroll width out to the table's width — an accessibility affordance silently breaking the mobile layout.

**Dependencies added:** TanStack Table v8, `d3-scale`, `d3-array`, `@playwright/test`, `@testing-library/user-event` (ADR-048). No router, no UI kit, no charting framework, no CSS framework.

## Phase-7 results — deployment, and the storage change it forced

**The topology, which is the durable part.**

```text
jeisey/jeisey-tiers                PUBLIC     code, schemas, the production model, the frontend
  main                                        -> GitHub Pages at /jeisey-tiers/

jeisey/jeisey-tiers-market-data    PRIVATE    the append-only capture store
  market-data                                 immutable MFL + Sleeper captures
```

**The migration.** Byte-faithful and verified before anything irreversible happened: 40/40 files compare equal, both trees hash to `1e60a55283e69c763a9dbc0bbb5fe4eb2e10cd476716fa2fbd5653c4822434f2`, and `validate-market-history` passes on the migrated checkout. Zero objects from the old branch were reachable from `main` — it shared no history with it — which is why deleting the branch while still private left nothing recoverable in a public repository.

**The credential.** `MARKET_DATA_REPO_TOKEN`, a fine-grained token scoped to the data repository alone. It reaches `actions/checkout` through `token:` and never a shell; read-only jobs use `persist-credentials: false`; `ci.yml` never references it. The address is in `config/source-registry.yaml` and nowhere else.

**What ran on GitHub-hosted runners, and what it proved.**

| run | outcome |
|---|---|
| `market-capture` [32590470088](https://github.com/jeisey/jeisey-tiers/actions/runs/32590470088) | first capture into the private repository |
| `ci` [32590972677](https://github.com/jeisey/jeisey-tiers/actions/runs/32590972677) | three jobs green on a clean checkout |
| `daily-refresh` [32591545618](https://github.com/jeisey/jeisey-tiers/actions/runs/32591545618) | **found a real Phase-5 defect** — see below |
| `daily-refresh` [32594084631](https://github.com/jeisey/jeisey-tiers/actions/runs/32594084631) | capture + build green end to end; deploy blocked at the visibility gate |
| `daily-refresh` [32594602638](https://github.com/jeisey/jeisey-tiers/actions/runs/32594602638) | forced-failure proof: real gate rejected it, deploy skipped |
| `retrain` [32594603959](https://github.com/jeisey/jeisey-tiers/actions/runs/32594603959) | declined in 23 seconds, candidate job skipped |

**The 2026 production build, from the runner's own summary** (build `2026-intrinsic-cb-hurdle-v1-20260822T193501Z`, snapshot `2026-08-22T19-34-24Z`): 2,700 tier rows, 3,510 projections, 2,021 arbitrage rows, 315 player-status rows with 309 matched through Sleeper. Nine preset blocks — `redraft-14` joined the supported set. Quality gate **pass**, 0 critical, 3 warnings (the tier-stability warning, Sleeper `gsis_id` conflicts failing closed, unpriced top-150 players excluded). Cohort `no-mock-no-keeper` for every preset: **143 drafts**, up from Phase 5's 125, still `low` confidence on `total_drafts 143 < 300`, median per-player sample 93. Trend still null — ADR-042 wants three observation days spanning three days. `verify:board` at the project base path: 40 tier rows, 25 chart marks, 30 arbitrage rows, 63 injury badges, **0 disagreements**.

**Running the production path for the first time found a defect nothing else could have.** `PRODUCTION_COHORT_IDS` was frozen under `phase5_cohort_v1` as `("unfiltered", "ppr", "std")`; ADR-045 later made keeper-free a *qualifying* condition; so a daily capture retained nothing the frozen rule could legally select and `select_cohorts` refused to price a board. Every board Phase 5 built came from a `study` capture, which retains all sixteen candidates — so the production path had never actually been run. The rule was right; the capture was wrong. Fixed by retaining what the rule needs (ADR-045 amendment, 2026-08-22), with two tests that price every launch preset from `PRODUCTION_COHORT_IDS` alone.

**The workflows.**

| workflow | trigger | may do |
|---|---|---|
| `ci.yml` | PR, push to `main`, dispatch | fixtures only — no vendor, no store, no `pages:` scope |
| `daily-refresh.yml` | 07:17 America/New_York, dispatch | capture → build → deploy |
| `retrain.yml` | Sunday 06:43 America/New_York, dispatch | an evidence gate, and at most a candidate report |
| `market-capture.yml` | dispatch, or a request-file bump | an out-of-band capture |

Exactly one job in the repository holds a `pages:` scope: `daily-refresh`'s `deploy`, which also holds `id-token: write` and the `github-pages` environment. Everything else is `contents: read`, including both capture jobs — they write to another repository through a token scoped to it, so they need no write scope here at all.

**The public-release audit.** 517 paths and 56 commits scanned. No `.env`, no key material, no raw payload, no `data/historical/`, no `web/public/data/`, no identifying filesystem path. One credential-*shaped* match: the old workflow's `https://x-access-token:${GH_TOKEN}@github.com/...`, a shell variable reference expanded at runtime, and that construction is now gone. Full record in `docs/PHASE7_DEPLOYMENT.md`.

**The retrain gate, and why it says no.** `intrinsic-cb-hurdle-v1` trained through 2025; 2025 is the spent holdout; 2026 unplayed. `scripts/retrain_gate.py` asks whether a season after the last training season has a **complete fantasy horizon** upstream. 404 is "no", a short weekly file is "no", and it exits 0 either way. Every weekly run this preseason stops there in about two minutes, which is the gate being exercised rather than asserted.

## Confirmed decisions

- Static GitHub Pages runtime.
- Python modeling/data + React/TypeScript/Vite frontend.
- Intrinsic model cannot use market/expert rank features.
- Arbitrage may use market data; historical intrinsic inputs must be OOF.
- Phase-gated implementation.
- **Arbitrage V1 ships in deterministic baseline mode** — historical ADP is dense but not point-in-time (ADR-010).
- **Current player status comes from nflverse rosters/depth charts plus Sleeper**, never `load_injuries` (ADR-011).
- **Market cohorts are approximate and must be labelled**; cohort mix is re-measured at the start of Phase 5 (ADR-012, amended 2026-08-18).
- **FantasyCalc disabled** (ADR-013). **FantasyPros-derived ECR is `benchmark_only`** — internal comparison allowed, redistribution and DraftValue use forbidden (ADR-014, amended 2026-08-18).
- **Depth charts have two upstream schemas**; pre-2025 seasons have no draft-time depth observation (ADR-015).
- **Repository stays private through Phase 6**; visibility is a required Phase-7 decision (ADR-016).
- **MFL developer client provisioned**; the adapter reads env-variable names and never touches credentials on the unauthenticated ADP path (ADR-017).
- **Historical anchor depth**: point-in-time for 2025+, prior-season role proxy before that, explicit missingness for rookies (ADR-018).
- **Canonical identity**: namespaced ids, two independent market bridges, fail closed on any ambiguity (ADR-019).
- **Public artifacts use the bundled Shape A** with a shared envelope (ADR-020).
- **Draft anchor is 23:59:59 America/New_York on the Tuesday before the earliest Week-1 kickoff**, versioned `draft_anchor_v1_tuesday_eod_pre_week1` (ADR-021). It may not be re-tuned after seeing model performance.
- **The preseason universe is built only from pre-anchor evidence** — previous-season roster, target-season draft class, pre-anchor depth snapshot. Week-1 rosters are refused (ADR-022).
- **The historical dataset is Parquet at three normalized grains, outside version control**, reproducible with a manifest of content hashes (ADR-023).
- **Phase-3 modelling dependencies are LightGBM and NumPy only**; ridge, every metric and the bootstrap are written in-house, SciPy is a test-only cross-check (ADR-024).
- **Season 2025 is the sealed final holdout**, with primary and diagnostic slices predeclared before any comparison (ADR-025).
- **The Phase-3 core feature set is `intrinsic_core_v1`**, 78 of the 85 Phase-2 model inputs; snapshot-era-only columns, era indicators, the horizon index and the calendar index are excluded with recorded evidence (ADR-026).
- **The promotion and window-selection rules were frozen in code before the decisive comparison** (ADR-027).
- **The training window is W1, the full 2014+ expanding history** (ADR-028).
- **Q1, the direct-total LightGBM quantile model, advances to Phase 4** (ADR-029).
- **The Phase-4 decision rules were frozen in code before their results existed** (ADR-030).
- **Quantile monotonicity is an isotonic projection, not a sort**; the fitted calibration layer was measured and not adopted (ADR-031).
- **Horizon normalization was measured and rejected** on both declared routes; no calendar-year feature was added (ADR-032).
- **Candidate B, the availability x performance hurdle, is the production intrinsic model** (ADR-033).
- **Median simulated VORP is the fair rank**; the draw count is the convergence rule's predeclared fallback, and that rule's tier clause is stricter than the tier gate it protects (ADR-034).
- **Tiers come from the dynamic-programming alternative at penalty 1.0, and the stability gate fails** on boundary agreement; they ship with the failure attached (ADR-035).
- **The sealed 2025 holdout was evaluated once, at `2f0e725`, and passed** (ADR-036). It is spent.
- **`intrinsic-cb-hurdle-v1` is the production artifact**, trained through 2025, committed, digest-verified; a 2026 build uses `min(as_of, anchor)` and never loads target-season statistics (ADR-037).
- **Point-in-time captures live on the dedicated long-lived `market-data` branch**, immutable and timestamp-keyed, fail-closed on a differing rewrite (ADR-038).
- **The cohort sufficiency rule and its selection policy were frozen before their measurement** (ADR-039), and the measured population is core positions only.
- **A0 is the arbitrage baseline**: `rank_gap = market_adp - fair_rank`, `regional_value_gap = ln(market_adp / fair_rank)`, score = within-preset midpoint percentile, no reliability multiplier (ADR-040).
- **`confidence` is market-data quality, not a probability**, and dispersion is described rather than scored (ADR-041).
- **Trend is a trailing 7-day negated OLS slope over our own snapshots**, null until three observation days spanning three days exist (ADR-042).
- **Current player status is a separate artifact, keyed once per player, and is annotation only** (ADR-043).
- **Richer historical injury features are a 2027 refresh candidate**; the 2025 holdout is spent, so there is nothing to promote them against (ADR-044).
- **A redraft board may only be priced by a keeper-free cohort** (`phase5_cohort_v2`, ADR-045). No bound moved; the resulting insufficiency is published.
- **The frontend draws a tier as a band, never as a line** (ADR-046).
- **A shared market condition is explained once at view level, from `build_metadata`** (ADR-047).
- **The frontend's dependency set is TanStack Table v8, d3-scale/d3-array and Playwright** — no router, no UI kit, no charting framework (ADR-048).
- **V1 deploys as a public repository on a public GitHub Pages project site**, standard GitHub-hosted Actions, no external paid host; the repository stays private through Phase 6 (ADR-016 as amended 2026-08-21).
- **FantasyPros terms review is complete**; the source is `benchmark_only` and is *not* a production input, so it is absent from the site's source list (ADR-014 as amended).
- Source verification runs on a GitHub runner, not in an egress-restricted sandbox (ADR-009).

## Verified source facts a later phase should not re-derive

Full Phase-0 detail in `docs/DATA_SOURCES.md` section 13; Phase-2 additions in section 14. The load-bearing ones:

- Market ADP: `https://api.myfantasyleague.com/{season}/export?TYPE=adp&JSON=1`, no auth, **no standard-deviation field**, `DAYS` ignored, response `timestamp` is generation time not data-as-of.
- Market → canonical identity works by id alone: 100% of priced QB/RB/WR/TE, two independent bridges, zero disagreements.
- Sleeper `gsis_id` coverage is only 31.9%, so join **nflverse → Sleeper on `sleeper_id`**, never the reverse.
- `nflreadpy.get_current_season()` returns the *prior* season in August; take the draft-target season from config.
- **Snap counts start at 2013** — `load_snap_counts(2012)` returns an empty file. That is why 2014 is the first target season.
- **nflverse roster coverage steps up at 2016** (2,190 rows in 2015 → 3,061 in 2016), which is why 2014-2016 carry ~670 eligible rows against ~1,050 afterwards.
- **The 2016 roster leaves `years_exp` null on 510 rows.** Treating that as zero experience would misclassify 247 established players as 2017 rookies.
- **A seasonal roster's grain is `(season, gsis_id, team)`** — a traded player appears once per club.
- **`load_players` keys ~24% of its rows by an ESB id, not GSIS**, and misses ~70 skill players a season; birth dates fall back to season rosters.
- **ffopportunity can emit one row per position per player-week**; the largest attribution wins rather than summing.
- **nflverse `fantasy_points` includes six points per return touchdown**, which this project's presets do not define. That is the entire difference between the two, proven by reconciliation rather than assumed.

## Phase-1 facts a later phase should not re-derive

- **Adapters split into a pure `normalize` and an I/O `fetch`.** Every fixture test drives `normalize`; only opt-in live tests touch `fetch`.
- **Each adapter declares `required_source_columns` and `recorded_schema_fixture`**, checked against a recorded schema. Add both to any new adapter.
- **Column order in CSV comes from the JSON Schema**, not from Python.
- **Artifacts are byte-reproducible** for identical inputs.
- **`QualityCheck` records rather than exceptions.** A build collects every finding, then the gate decides once.
- **Ambiguity severity is contextual** — producing an ambiguous outcome is the resolver working; publishing one is critical.
- **`FIXTURE_IDENTITY_COVERAGE_MINIMUM` (0.80) is a local relaxation for the adversarial 16-player fixture**; production stays at 0.95.

## Phase-2 facts a later phase should not re-derive

- **The anchor is the spine.** Every feature row carries `anchor_at_utc` and `feature_cutoff_rule_version`, and every leakage argument is written against them. Do not compute a new anchor anywhere else.
- **Leakage rules 1 and 6 are proved by construction, not inspection.** `audit_target_season_independence` rebuilds each season with its own statistics deleted and compares content hashes. It roughly triples build time and is on by default; `--skip-independence-check` exists for iteration only.
- **The feature dictionary is code.** `HISTORICAL_FEATURE_CONTRACT` is generated from it, `docs/FEATURE_DICTIONARY.md` is rendered from it, and tests pin both. Add a column by adding a `FeatureSpec`, never by editing a contract or the Markdown.
- **`prev1_fantasy_points_std` and `_ppr` are the only scoring-flavoured features**, and half-PPR is exactly their mean. Do not add a third.
- **Lagged aggregates use the fantasy horizon**, the same one the label uses, so a prior-production baseline compares like with like.
- **Efficiency ratios are null below a declared minimum denominator** (20 carries, 20 targets, 100 pass attempts) with a paired `*_denominator_met` indicator. Do not impute them.
- **`ffdraft.simulation.allocation` is shared with Phase 4.** Feed it sampled points rather than writing a second replacement algorithm.
- **`HistoricalThresholds.fixture()` exists because production coverage thresholds are meaningless on a thirty-row fixture.** The structural thresholds do not relax, and a test asserts the fixture profile is strictly looser only on the statistical ones.
- **Two feature families were deliberately deferred with reasons**: vacated-opportunity (needs pre-anchor roster knowledge, so it would exist for one labelled season and be era-confounded) and NGS/PFR/FTN advanced metrics (unproven value, and FTN carries a share-alike obligation). Both are documented in `docs/MODELING.md` section 5.1.

## Phase-3 facts a later phase should not re-derive

- **A model implements one method.** `fit_predict(train, validate, context)` is the whole interface, so there is no fitted object that could outlive a fold and nowhere to keep a statistic computed over the whole dataset. Fold isolation is structural, not a convention to remember.
- **The seal is at load time.** `load_modeling_dataset` drops sealed seasons before anything sees the frame, and the fold generator refuses to build a fold that validates one. `tests/model/test_folds_and_holdout.py` proves it by construction: poisoning every 2025 label leaves a development run byte-identical. Do not add a second, softer path to the holdout.
- **Residual quantiles come from an inner chronological split** of the training window - fit on the earlier seasons, residuals from the latest one or two, stratified by predicted level where a stratum has 100+ rows. That is how B0 and B1 get honest intervals; never give a baseline a fixed-width band.
- **B0 is a strong baseline on purpose.** Prior-season points per game times the training-fold mean games for the same availability *and* age cohort beats a raw prior-season total on every development season tried, and beats ridge on MAE at every position. If a future candidate "beats the baseline", check which baseline.
- **Macro before row-weighted.** Aggregates are means over season x position x scoring cells. WR and RB cells carry two to three times the rows of QB and TE ones, so a pooled mean lets them decide positional questions on their own. Row-weighted numbers are emitted as diagnostics.
- **Metrics are the project's own code** (ADR-024), pinned by hand-worked examples and cross-checked against SciPy. Spearman is Pearson on average ranks; Kendall is the tie-corrected tau-b. Do not swap in a library mid-project without re-pinning the report numbers.
- **The paired bootstrap resamples within cells and carries both models through the same resample.** Two models differing by a constant produce a degenerate interval, which is the property that makes the interval mean anything; independent resampling would not.
- **Q1's raw quantiles cross on 38.7% of rows** with a mean magnitude of 0.53 points against a 62.7-point P10-P90 width. Phase 3 sorts them and reports the raw rate separately. Phase 4 should fix the cause, not keep sorting.
- **Top-K retrieval does not follow rank correlation.** Q1 has the better Spearman but B1 retrieves more of the actual top-K (0.593 against 0.544). A median-quantile point prediction is robust, and robustness compresses the top of the board. Measure top-K on simulated VORP in Phase 4 rather than assuming the point ordering carries over.
- **`prev1_games_missed` was clamped to zero when either component was missing.** Phase 3 fixed it to null, matching what the dictionary always declared, and added the regression test. 4,946 of 11,604 rows are affected; a dataset built before this fix disagrees.

## Phase-4 facts a later phase should not re-derive

- **`ffdraft.modeling.rules` is the freeze, and `ffdraft.modeling.frozen` is its output.** Every Phase-4 threshold lives in the first as a frozen dataclass with a pure evaluator; every decision those rules made lives in the second as a constant. If you want to know what the production system is, read `frozen.py` — it is one screen and every value cites the ADR that produced it. Do not add a decision to `frozen.py` that no rule made.
- **A rule that fails is a result.** Two did. The convergence rule fell through to its own fallback clause and the tier stability gate failed outright, and both are published rather than repaired. If a future session is tempted to move `min_boundary_agreement` or `max_largest_tier_share`, that is a new rule version with its own evidence and its own ADR — not an edit.
- **Crossing is fixed by projection, not by sorting.** PAV projects the raw quantile vector onto the monotone cone, which is an L2 projection onto a closed convex set that contains the true quantile vector, so it provably cannot move the estimate further from the truth. Sorting has no such guarantee. Raw crossing went 0.387 -> 0.000 and CB's own components do not cross at all.
- **The hurdle's two components are coupled, not independent.** A Gaussian copula carries one fold-fitted rank correlation between availability and per-game performance, estimated from probability-integral transforms on an inner chronological split. Assuming independence would have understated the spread of the season total.
- **VORP is simulated, never differenced against a fixed replacement.** Every draw allocates starters and derives *that draw's* replacement level. Subtracting one deterministic baseline from every quantile would have made VORP a shifted copy of points and destroyed the league-scarcity information the whole simulation exists to produce.
- **Point draws deliberately do not depend on the league preset.** The same simulated seasons are re-allocated under every roster shape, so a preset-to-preset difference is a scarcity difference rather than Monte Carlo noise. Per-player BLAKE2b streams make a board independent of player order and pool membership too.
- **`ffdraft.simulation.allocation` is still the only allocator.** Phase 4 fed it sampled points instead of realized ones; it did not write a second one, and neither should Phase 5+.
- **Tier membership is reproducible; tier boundaries are not.** ARI 0.865 beside boundary agreement 0.239 is not a contradiction, it is the finding. Simulated VORP declines almost smoothly, so "where a tier ends" is mostly not an identified quantity — only about four cut sites on a 300-deep board are. Any UI that draws a hard line overstates the measurement.
- **The board's deep tail genuinely is one group.** At penalty 3.0 the segmentation wants tiers of 82 and 110 players. The frozen 25%-of-board cap forbids that, which is what forces the unstable cuts. A future tier rule should let the undifferentiated tail be one wide tier rather than slicing it.
- **The holdout is spent and the seal is one-way in code.** `--final-eval` needs a fixed token *and* a written reason; `train-production --allow-unsealed` needs the same token and refuses unless the holdout has already been consumed. There is no softer path, and none should be added.
- **A current build never loads target-season statistics.** `include_target_statistics=False` is correct in general — a preseason board may not consume the season it predicts — and not a workaround for 2026 being unplayed. The 404 from nflverse for an unplayed season is a symptom of the same fact.
- **A pre-anchor build uses its own timestamp, not the anchor.** `min(as_of, anchor)`. Stamping a future anchor onto a build that ran before it would claim knowledge the build does not have.
- **Current roster status is metadata, never a feature.** It can drop a retired player from the board and it annotates rows with flags, but it has no development-era support and cannot enter a prediction.
- **The Phase-3 harness reproduces exactly.** `evaluate-intrinsic` was re-run at Phase 4 and diffed against the committed report: identical on every number, decision and check, with only the timestamped `experiment_id` differing. Determinism here is real, not aspirational.
- **Model cards are generated, like the feature dictionary.** `ffdraft model-card` reads the committed experiment reports and the artifact. A number in a card that no command produces is a number that can drift.

## Phase-5 facts a later phase should not re-derive

- **The firewall is a test, not a habit.** `tests/contract/test_architecture_boundary.py` walks the import graph — function-local imports included — from every intrinsic module and fails on any path to market data. It found a real edge on its first run. If a new module needs the append-only store, import `ffdraft.retention`, not `ffdraft.market`.
- **A quote belongs to a cohort, not a preset.** `market_quote` 2.0 records `cohort_id`; exactness is a per-preset verdict the selection rule reaches later. Do not reintroduce a preset column on a quote row.
- **The analysis is offline by construction.** Only `snapshot-market` and `capture-status` touch a vendor. Cohort measurement, arbitrage and the cards all read retained bytes, which is why a session behind an egress policy can still build and validate the whole product, and why every report can be regenerated and diffed.
- **`build_metadata.json` is merged, never rewritten.** An arbitrage build that overwrote it would erase the Phase-4 tier-stability warning. A test asserts the warning survives.
- **`source_as_of_utc` is null for MFL everywhere, forever.** Its response `timestamp` is generation time. It is retained as `response_timestamp` vendor metadata and a semantic check fails the build if the field is ever populated.
- **Two snapshots on the same day are two observations but one observation day.** That is what stops a "7-day trend" from silently becoming a 6-hour one.
- **The status build goes through the frame contract, not schema inference.** A 12,000-row Sleeper capture is mostly nulls; Polars infers from the first rows, so the first injury note several thousand rows in used to kill the build.
- **An empty *cohort* is a finding; an empty *capture* is an outage.** The adapter's `source.too_few_records` is downgraded per cohort and re-raised at capture level, because a study that refused to record a collapsed cohort could not prove the collapse.
- **`no-keeper` and `no-mock-no-keeper` are the same cohort on this data**, because `IS_MOCK=0` does nothing. The fallback tie-break picks the latter; it is an arbitrary but deterministic choice between identical populations.

## Phase-6 facts a later phase should not re-derive

- **The browser filters, joins and formats. It computes nothing.** No component derives a VORP, a fair rank, a tier or an arbitrage score. `npm run verify:board` proves it against the artifact bytes on the live build; if a future change makes a chart "smarter", that command is what fails.
- **`web/tests/fixtures/artifacts.ts` is the test board, and it is not the real one.** Ten players carrying the cases that are easy to get wrong: an injury designation, a status record with no designation, no status record at all, a tier player with no market price, a generational suffix, and two quarterback premiums. Every arbitrage row reads `low` with a null trend, mirroring the launch condition. The real generated artifacts change on every rebuild; a test bound to them proves nothing.
- **An overflow container only clips absolutely positioned descendants when it is itself positioned.** `.table-scroll` carries `position: relative` for that reason and only that reason. Remove it and the screen-reader-only spans inside table cells escape a horizontally scrolled table and give the whole page an invisible horizontal scrollbar on mobile.
- **The tier axis spans the interval the chart draws.** P25-P75, not P10-P90. Scaling to the outer interval spends a third of the width on tails the chart does not render and parks every median in the middle third. P10-P90 lives in player detail and in every mark's accessible label.
- **Almost nothing shares a lane row on the real board, and that is the finding.** A top back's interquartile interval is wider than the entire gap between the first and twentieth median. Packing two players side by side would only be possible by drawing intervals too short to be true.
- **Charts are one tab stop, not three hundred.** `useRovingMarks` implements the composite-widget pattern; the table beside each chart remains the definitive accessible equivalent.
- **The end-to-end run builds five sites**: root, `/jeisey-tiers/`, and three that withhold or corrupt an artifact. Each scenario is its own build at its own base path, so no test can see another's outage, and none of them can silently read the healthy build's `data/`.
- **Every spec fails a request that leaves localhost.** That is what makes `docs/ARCHITECTURE.md` section 3.2 a check rather than a convention.
- **`docs/visual-qa/` captures the *fixture* build, deliberately.** Two runs of the same code produce the same images, so a review is reproducible; the real board is reviewed live during a build because it changes every time.
- **jsdom has no `HTMLDialogElement.showModal` and no `ResizeObserver`.** Both are polyfilled in `web/tests/setup.ts` rather than worked around in components; production code should use the platform API.
- **TanStack Table is pinned to v8**, not the v9 rewrite (ADR-048). The two React-Compiler warnings it produces are left visible rather than silenced.

## Phase-7 facts a later phase should not re-derive

- **Visibility is a repository property, not a branch property.** This is the fact the whole phase turned on. There is no private branch inside a public repository, and no amount of Pages-artifact hygiene changes that, because `git clone` hands over every branch. If a future phase wants to publish something new, ask what a clone would carry before asking what the build copies.
- **The store's address lives in `config/source-registry.yaml` and nowhere else.** `.github/actions/market-data-store` reads it; `tests/unit/test_workflows.py` fails if a workflow grows the literal. Moving the store again is one edit to one file.
- **Last-known-good is `needs:`, not `if:`.** `deploy` needs `build` needs `capture`, and the deploy job contains only the Pages actions. Do not merge them "for speed" — the separation *is* the guarantee, and a real unplanned failure ([32591545618](https://github.com/jeisey/jeisey-tiers/actions/runs/32591545618)) demonstrated it before the rehearsed one did.
- **Concurrency queues rather than cancels, on purpose.** A cancellation between `git commit` and `git push` in the capture job would drop a validated snapshot. Queueing also gives the ordering: a superseding run deploys *after* the one it supersedes.
- **The forced-failure proof breaks a real invariant.** It corrupts quantile monotonicity and lets `validate-artifacts` reject it, so `artifact.non_monotonic_quantiles` is what stops the deploy. If a future change makes this an `exit 1`, the proof stops proving anything.
- **A production capture must retain a cohort the frozen rule can pick.** This was not true for two phases and no test noticed, because every selection test handed `select_cohorts` all sixteen candidates. When a rule gains a qualifying condition, check the *capture set* against it, not only the rule.
- **A verification check must assert the contract, not the day's data.** `verify-real-build.mjs` asserted that every arbitrage Trend cell renders an em dash. That was true in Phase 6 only because the store was too young for ADR-042, and the first build with a real trend failed it — a green product failing a test that had frozen the launch condition. The check now compares the rendered cell with the artifact's own `market_trend`, like every other assertion in that file. When a value is null *because the system is young*, do not pin the null. The same audit found a second instance in the same file: the tier-row name assertion stripped the injury badge out of the cell text with a pattern that assumed `IR · Knee`, so a designation reported without a body part would have failed a correct board; it now reads the name from `.player-name` instead of un-rendering the cell.
- **The nflverse cache key contains the UTC date and has no `restore-keys`.** A prefix fallback would make a cache hit serve staler rosters than a miss, which inverts the "correct, only slower" rule. Do not add restore-keys to that one.
- **A workflow artifact on a public repository is world-readable.** The build record therefore stages the store's *manifests* only, and asserts no `.gz` reached it. Adding anything from `market-data/` to an artifact needs that same thought.
- **`persist-credentials: false` on read-only store checkouts is load-bearing**, not tidiness: it is what keeps a credential out of the workspace while the frontend builds and the Pages artifact is packaged. Confirmed in the post-job cleanup logs.
- **`npm run e2e | tail` reports `tail`'s exit code.** Without `set -o pipefail` a completely red Playwright suite reads as green. This cost real time; do not pipe a gate's output without pipefail.
- **This sandbox's Chromium build does not match the pinned Playwright release.** Export `PLAYWRIGHT_CHROMIUM_EXECUTABLE=/opt/pw-browsers/chromium-1194/chrome-linux/chrome` before `npm run e2e` here. On a runner, `npx playwright install` fetches the matching build and none of this applies.
- **`api.github.com` is unreachable from this environment and the git proxy rejects ref deletions.** Repository visibility and branch deletion are owner actions; do not plan a phase around automating them.

## Open questions requiring evidence

- **How to make tier boundaries meet a stability bar, or how to stop pretending they are lines.** The measurement says a 300-deep board supports about four reproducible cut sites. Two candidate remedies, both new decisions needing their own rule version and evidence: let the undifferentiated tail be one wide tier by re-specifying `max_largest_tier_share`, or keep the segmentation and present membership with a boundary-confidence band instead of a hard edge. **Do not simply lower the threshold** (ADR-035).
- **How to re-specify the Monte Carlo convergence rule.** Its tier clause is stricter than the tier stability gate it was meant to protect and is decided partly by penalties the tier rule may never select. A revision should measure the tier clause on the promoted configuration only, and set its bar consistently with the gate (ADR-034).
- **Whether correlated player draws are worth building.** V1 samples every player independently, so it cannot express that a quarterback's collapse takes his receivers with him. That is the largest structural simplification in the simulation and it was never measured.
- **Whether `min_total_drafts` is the right instrument for a filtered cohort.** It is the only clause any format-pure or preset-specific cohort fails, and filtering shrinks the cohort-level count structurally while leaving per-player evidence intact — `no-keeper` carries 125 drafts but a median of 105 drafts per top-150 player, against a bar of 25, with the best top-150 coverage of any cohort measured. Re-specifying it needs its own rule version and its own evidence, and must not be done in the same breath as reading the result it would change (ADR-045).
- **Whether the fallback should prefer specificity when candidates are close.** With nothing sufficient, "widest" hands the PPR presets a 125-draft all-scoring cohort over a 115-draft PPR-only one. Answering this after seeing which cohort it picks is the trap ADR-045 avoids.
- **Whether a learned arbitrage model is ever worth it.** Not before three draft seasons of our own snapshots (ADR-010), which is 2029 at the earliest. Until then, snapshot retention is still the highest-value arbitrage work in the repository.
- **Repository visibility** — deferred to Phase 7 by ADR-016.
- **Market cohort mix closer to peak draft season** — re-measure at the start of Phase 5 (ADR-012 amendment).
- **Whether `load_ftn_charting` earns its CC-BY-SA obligation** — still open, and still not needed.

## Known risks (non-blocking)

- **Two owner actions gate the live site**, and they are ordered: delete `market-data` from `jeisey/jeisey-tiers`, *then* make it public. Doing the second without the first publishes every retained vendor payload, and that is not undone by deleting the branch afterwards. `docs/PHASE7_DEPLOYMENT.md` section 7 is the checklist.
- **`MARKET_DATA_REPO_TOKEN` expires.** When it does the daily refresh fails at its first job with a message naming the secret, the deploy job is never reached, and the deployed site stays live and stale. Loud and non-destructive, but it needs a calendar reminder; rotation steps are `docs/OPERATIONS.md` section 5.3.
- **Scheduled-workflow inactivity got slightly worse.** The daily capture now commits to the *private data* repository, so a run of `daily-refresh.yml` creates no activity in the application repository at all. GitHub disables scheduled workflows in public repositories after long inactivity; re-enabling steps are in `docs/OPERATIONS.md` section 12.
- **Three MyFantasyLeague player-database requests were made on 2026-08-22** — the out-of-band capture, the first production refresh, and the refresh that validated the cohort fix. MFL asks for at most one per day. This was a migration day and the third was needed to prove the fix; a routine day takes exactly one, and `skip_capture` exists so a re-deploy does not take a second.

- **Every arbitrage row reads `low` confidence**, because no keeper-free cohort clears the frozen cohort-level draft-count bar. The label is correct under the rule and pessimistic against the per-player evidence, and it makes `confidence` non-discriminating for Phase 6. The rubric returns the clause that fired, so the UI can explain it rather than just show it.
- **`wide_market_range` fires on 1,914 of 2,124 rows.** True and useless at this sample size: with ~125 drafts the min-to-max span really does exceed five rounds for most players. Phase 6 should render `market_adp_low`/`market_adp_high` directly and treat the flag as a footnote.
- **The 2026 board is priced by 125 real redraft drafts** taken on one afternoon in late August. It will get better on its own as the season matures and the store fills; nothing about the code needs to change for that.
- **STD and HALF are served by an all-scoring cohort.** The dilution is about ten non-PPR drafts out of 125 and is stated in the cohort report's composition caveat, but a standard-scoring reader is looking at a board whose price is set mostly by PPR drafters.
- **Sleeper publishes `practice_participation`, `practice_description` and `injury_start_date` as keys with null values in the preseason.** They are normalized and will populate in season; a Phase-6 UI must not assume they are present.
- **Tiers are published having failed their stability gate.** `build_metadata.json` carries a `current.tier_stability` warning and the cards say so, but nothing stops a consumer from rendering a hard line anyway. The Phase-6 frontend is where this becomes a user-visible risk rather than a documented one.
- **Residual Monte Carlo error is real and unmeasured beyond the ladder.** At 10,000 draws two seeds differ by about 0.3 fantasy points on a player's expected VORP and under 1.5 rank positions in the top 150. Tier boundaries move more than that, which is part of why boundary agreement is low. A build is deterministic for a fixed seed; it is not seed-invariant.
- **CB's pooled P25-P75 coverage is 0.614 against a nominal 0.50**, driven by zero-game rows: among players with at least one game it is 0.456, among zero-game rows 0.836, and 18.4% of rows have `q25 == q75 == 0`. The hurdle is right that many players score nothing; the inner interval is consequently wide where it should be degenerate. Recorded as an ADR-033 limitation rather than patched.
- **The model card and tier report are only as current as the last `ffdraft model-card` run.** They are generated from committed experiment reports, so a retrain without regenerating them leaves published numbers describing a model that no longer exists.
- **The 2014-2016 era boundary is real and is reported as a warning, not hidden.** It comes from upstream roster coverage, not from this code. Any metric averaged across all twelve seasons mixes two different universes. ADR-028 chose to train across it anyway, on measured evidence, and records that W1's advantage is largest where W2 has least data.
- **The fantasy horizon changed at 2021** (weeks 1-16 to weeks 1-17), so season totals are on a ~6% different scale either side of it. It affects every candidate identically within a fold and is not corrected for; validation season 2021 is the one fold trained entirely on 16-week seasons. `prev1_team_games`, which is that horizon expressed as a lagged count, is excluded from the feature set for the same reason (ADR-026).
- **B0 and B1 predictive intervals under-cover slightly** because their residual quantiles are estimated on one or two inner-split seasons, which understates season-to-season variance. Q1's P10-P90 coverage is 0.771 against a nominal 0.80. Calibration is Phase-4 work and must be fitted on development folds only.
- **`team_at_anchor` is null for almost every pre-2025 veteran.** Free agency and trades are unobservable before the snapshot era, so `team_change_flag` is null there too, with `team_change_known` saying so. Overall `team_at_anchor` coverage is 12%; that is honest, not a defect.
- **Pre-2025 rookies have no depth or role signal at all** (`depth_unavailable`), by ADR-018. Their preseason signal is draft capital, biography and team context. Coverage is reported per season and position rather than patched over.
- **One upstream GSIS id names two different players** (`00-0035718`, 2019). Failed closed and excluded; re-check if nflverse corrects it.
- **Source-schema drift is detected, not prevented.** Phase 2 adds a semantic layer over the structural one, but a column that changes meaning *inside* its declared domain would still pass. Re-run `scripts/source_probe.py` and `scripts/capture_source_schemas.py` if more than a few weeks pass.
- **`mypy --strict` covers `src/ffdraft` only.** Tests are covered by execution.
- **The historical build takes a few minutes** of nflverse downloads plus the independence proof. There is no incremental mode; if that becomes painful, cache the normalized frames rather than weakening the proof.

- **The Tier Board is tall by construction.** One hundred players at ~17px plus lane padding is roughly 1,800px, because intervals this wide force one player per row. It reads as a board and scrolls like one; a future tier rule that produced fewer, wider tiers would not change that, since the constraint is interval width rather than tier count.
- **The React Compiler skips optimising the two table components**, because `useReactTable` returns functions it cannot memoise. A warning, not an error, and not measurable on a 300-row board (ADR-048).
- **`expected_games` is absent from the production projection artifact** even though the schema allows it and the fixture pipeline emits it. The UI hides the field rather than showing an em dash. If a future build starts emitting it, it appears with no code change.
- **The visual-QA screenshots are of the fixture board.** They prove layout, not data. A regression that only appears at production row counts would not show up there; `npm run verify:board` and a live look are what cover that.

## Repository notes

- **`BUNDLE_MANIFEST.txt` is a snapshot of the original specification bundle, not a live checksum.** The frozen set (`AGENTS.md`, `PRD.md`, `MASTER_SPEC.md`, `PROMPT_START_HERE.md`, `docs/IMPLEMENTATION_PLAN.md`, `docs/TEST_STRATEGY.md`, `docs/UX_SPEC.md`, `docs/BASELINE_FFTIERS_ANALYSIS.md`, `repo-tree.txt`) is untouched. The living records — `README.md`, `TASKS.md`, `SESSION_STATE.md`, `docs/DECISIONS.md`, `docs/DATA_SOURCES.md`, `docs/DATA_CONTRACTS.md`, `docs/MODELING.md`, `docs/ARCHITECTURE.md`, `docs/OPERATIONS.md`, `docs/SECURITY_LICENSE.md`, `docs/FEATURE_DICTIONARY.md`, `config/*` — are updated as the contract requires.
- **`ruff` 0.16 formats Python code blocks inside Markdown.** Markdown is excluded from ruff in `pyproject.toml`; do not remove that exclusion.
- **Regenerating the golden artifacts is a deliberate act**, not a fix for a red test: `uv run ffdraft build-fixture-artifacts --out tests/fixtures/artifacts --git-sha 0000000`. Read the diff first.
- **`docs/FEATURE_DICTIONARY.md` is generated.** Regenerate from `uv run ffdraft feature-dictionary` after changing `ffdraft.features.dictionary`; a test fails if it is stale.
- **`data/historical/` is gitignored.** Rebuild it rather than looking for it in a clone.
- **The retained store is a separate private repository** (ADR-049). `git clone https://github.com/jeisey/jeisey-tiers-market-data ../market-data`, then pass `--store ../market-data` to the Phase-5 commands. It is not in this working tree, is never merged, and is not in this repository at all — which is what makes a public application repository safe. A contributor without access to it can still run every fixture-based gate, the whole frontend and the entire test suite; the only thing they cannot do is rebuild the production board.
- **`docs/market-cohorts/` is committed evidence**, like `docs/source-probes/` and `docs/experiments/`. Regenerate with `ffdraft measure-market-cohorts` and read the diff.
- **`models/cards/arbitrage-method-a0.*` is generated.** Regenerate with `ffdraft arbitrage-card` after any rebuild; a number in a card that no command produces is a number that can drift.
- **The Phase-3 experiment reports are committed; the row-level predictions are not.** `docs/experiments/phase3-intrinsic-baselines/{experiment.json,experiment.md}` are the evidence behind ADR-028 and ADR-029, in the same spirit as `docs/source-probes/`. `predictions.parquet` is written only with `--write-predictions` and is gitignored.

## Known blockers

**None.** The two owner-only actions Phase 7 stopped at were completed on 2026-08-22, in order: the `market-data` branch was deleted from `jeisey/jeisey-tiers`, then the repository was made public. A third was discovered by doing it — **Settings → Pages → Source → GitHub Actions** is required, and `enablement: true` on `configure-pages` cannot substitute for it, because creating a Pages site is an admin-level API call and a `GITHUB_TOKEN` never holds admin. That flag has been removed rather than left as a false promise.

The four analytical findings are unchanged and none is a blocker: the Monte Carlo convergence rule (ADR-034), tier boundary stability (ADR-035), the cohort volume clause (ADR-045, now re-framed by ADR-052) and the non-discriminating `wide_market_range` flag (ADR-041).

## Next action

**Phase 8, and its first action is not code.** The site has been live and refreshing since 2026-08-22. Open it, use it as you would the night before a real draft, and write what you notice into `docs/PHASE8_UI_FEEDBACK.md`. That file is seeded with what is already known — the Tier Board is ~1,800px because interval width, not tier count, forbids packing; the tier lane treatment, Draft Rail and player card are all up for review — and Phase 7 deliberately did not pre-empt any of it.

**Two ADRs are waiting for an owner decision** and should be read before any market work: **ADR-052** (market-data confidence is self-resolving; do not re-specify `min_total_drafts` to make it pass) and **ADR-053** (the free-source sweep, and what each candidate would and would not fix). Both are `Proposed`.

The rest of the non-UI Phase-8 queue is listed at the bottom of `docs/PHASE8_UI_FEEDBACK.md` so a session sees it at once: ADR-034's convergence rule, ADR-035's tier stability, ADR-041's `wide_market_range`, correlated player draws, ADR-044's injury features and ADR-010's learned arbitrage. None of them is answered by looking at the site.
