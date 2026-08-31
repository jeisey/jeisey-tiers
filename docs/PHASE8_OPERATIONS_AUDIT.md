# Phase-8 production-run audit

Seven consecutive `daily-refresh` runs, read from their own job summaries rather than from
their conclusions. **Five green days is not evidence of correctness** — it is evidence that
nothing failed loudly — so this audit looks for the quiet kind: a warning count creeping up, a
row count drifting, an artifact that stops moving while its inputs do, a label changing without
the surface that renders it changing with it.

Nothing in this file is a private payload. Every number is from a public workflow summary or a
public artifact.

---

## 1. The runs

| # | run | date | trigger | conclusion | duration | code SHA |
|---:|---|---|---|---|---:|---|
| 11 | [32976052695](https://github.com/jeisey/jeisey-tiers/actions/runs/32976052695) | 08-26 | dispatch | **failure** | 5m02s | `1fcbac7` |
| 12 | [32982309252](https://github.com/jeisey/jeisey-tiers/actions/runs/32982309252) | 08-26 | dispatch | success | 6m29s | `d9ca362` |
| 13 | [33085216401](https://github.com/jeisey/jeisey-tiers/actions/runs/33085216401) | 08-27 | schedule | success | 5m45s | `645409b` |
| 14 | [33184685536](https://github.com/jeisey/jeisey-tiers/actions/runs/33184685536) | 08-28 | schedule | success | 6m37s | `645409b` |
| 15 | [33249935607](https://github.com/jeisey/jeisey-tiers/actions/runs/33249935607) | 08-29 | schedule | success | 5m55s | `645409b` |
| 16 | [33308756341](https://github.com/jeisey/jeisey-tiers/actions/runs/33308756341) | 08-30 | schedule | success | 4m25s | `645409b` |
| 17 | [33386902514](https://github.com/jeisey/jeisey-tiers/actions/runs/33386902514) | 08-31 | schedule | success | 5m29s | `645409b` |

Run 11 is the last failure and is included deliberately: it is the `arbitrage.top_board_priced`
break that ADR-054 and ADR-055 diagnosed, and run 12 is the fix landing. Runs 13-17 are the
five green days.

**Deployed code has been identical since run 13.** Every green scheduled run since 08-27 has
built from `645409b`, so every difference below is a *data* difference. That is what makes this
audit worth doing: the code is a constant, so drift is signal.

---

## 2. What moved

| | 08-22 (launch) | 08-27 | 08-30 | 08-31 |
|---|---:|---:|---:|---:|
| `tiers.json` rows | 2,700 | 2,700 | 2,700 | 2,700 |
| `projections.json` rows | 3,510 | 3,504 | 3,498 | 3,435 |
| `arbitrage.json` rows | 2,021 | 1,966 | 1,945 | 1,934 |
| `player_status.json` rows | 315 | 316 | 316 | 316 |
| …matched via Sleeper | 309 | 311 | 311 | 311 |
| selected cohort | `no-mock-no-keeper` | — | `no-keeper` / `ppr-no-keeper` | `no-keeper` / `ppr-no-keeper` |
| cohort drafts | 143 | — | 514 / 386 | **735 / 554** |
| sufficient | no | no | **yes** | **yes** |
| confidence | 2,021 `low` | — | 1,870 `medium`, 75 `low` | 1,889 `medium`, 45 `low` |
| median per-player sample | 93 | — | 345 | 487 |
| trend | null | — | available | available |
| quality gate | pass, 0 critical, 3 warnings | pass, 0/3 | pass, 0/3 | pass, 0/3 |

### 2.1 Tier rows are exactly constant, and that is correct

2,700 = 300 players × 9 preset blocks, every day, from a model that never sees the market. The
tier artifact is a pure function of the committed model and the pre-anchor evidence, so a
*change* here would be the finding. There is none.

### 2.2 Projection and arbitrage rows drift downward, and the two drifts are unrelated

`projections.json` fell 3,510 → 3,435 (−2.1%) and `arbitrage.json` 2,021 → 1,934 (−4.3%) over
nine days. Neither is a defect, and they have different causes:

- **Projections** are one row per (player, scoring preset) over the eligible universe, which is
  rebuilt from the current roster and player master on every run. Late-August cuts remove
  players; the universe shrinks. 3,435/3 = 1,145 players against 1,170 at launch — twenty-five
  players fewer across a roster-cutdown week, which is the right order of magnitude for it.
- **Arbitrage** rows are the intersection of the board with the *selected cohort's* priced
  players. The cohort changed on 08-30, from an all-scoring keeper-free population to a
  narrower one; a narrower cohort prices fewer players. The 08-31 capture shows it directly:
  `unfiltered` prices 400 players, `no-keeper` 362, `ppr-no-keeper` 368. The board traded
  breadth for a population that actually matches the preset, which is what `phase5_cohort_v2`
  is for.

**Watch item, not a finding.** These are gentle monotone declines with an explanation each. A
*step* in either — say arbitrage rows dropping a hundred in one day — would mean a cohort
selection changed or a resolution path broke, and would deserve the ADR-054 treatment.

### 2.3 Warnings are flat at three, and they are the same three

Every run in the window: **0 critical, 3 warnings**, byte-identical text.

1. tiers published having not passed the frozen tier-stability gate (ADR-035);
2. Sleeper's reported `gsis_id` disagreed with the canonical id on some records, which fail
   closed and carry no annotation;
3. top-150 board players with no market price are excluded rather than filled in.

All three are *published limitations by design*, not accumulating debt. The adversarial
question — "what warning has grown while the workflow stayed green?" — has a clean answer here:
none. The count has not moved and neither has the wording.

Per-source warning counts are likewise flat: `ffopportunity` 1, `myfantasyleague_adp` 5,
`nflreadpy` 8, on every run in the window.

### 2.4 Identity resolution rate fell, and it is the benign cause

Coverage over each cohort's resolvable priced players, 08-30 → 08-31:

| cohort | drafts | rows | resolved | coverage |
|---|---:|---:|---|---:|
| `no-keeper` | 514 → 735 | 380 → 362 | 272/353 → 267/335 | 0.771 → **0.797** |
| `ppr-no-keeper` | 386 → 554 | 375 → 368 | 272/348 → 272/341 | 0.782 → **0.798** |
| `unfiltered` | 1,066 → 1,415 | 402 → 400 | 287/375 → 287/373 | 0.765 → **0.769** |

Against Phase 5's ~87%, the current whole-payload figure is lower — and rising again. ADR-052
recorded the cause: a larger aggregate prices more obscure players, including kickers, team
defences and IDP, which this project does not model. **This is not the number the sufficiency
rule judges**, which is measured over core positions only (ADR-039 clarification) and is not
near its bound. `ambiguous` is 0 on every cohort on every run, which is the number that would
matter — an ambiguous identity that *published* would be critical.

### 2.5 Artifacts move whenever their inputs do

Every run in the window appended to the private store (`store_appended: true`), produced a new
`build_id` stamped with that run's own generation time, and deployed. There is no run where a
new snapshot landed and the published artifact did not change — the failure mode where a build
silently reuses yesterday's inputs.

### 2.6 Duration and schedule

Build durations are 4m25s-6m37s with no trend; the longest step is `build-current` at
2m12s-3m44s, which is nflverse download plus inference and varies with cache warmth.

**One scheduling anomaly, upstream and benign.** The cron is 07:17 America/New_York = 11:17
UTC. Runs 13 and 14 started at **14:58** and **15:20** UTC — three and a half to four hours
late. GitHub documents that scheduled workflows are delayed under load and can be dropped
entirely; runs 15-17 started at 11:21-11:25 UTC as expected. Nothing to fix, and nothing to
build on: a product that needed a guaranteed 07:17 refresh would need a different trigger.

### 2.7 The forced-failure proof stayed reachable and stayed skipped

Every green run shows `Corrupt an artifact on purpose (forced-failure proof)` as **skipped**,
which is the correct state for a scheduled run — `inputs` is empty on a schedule and the step
also asserts the event name. The step is present and inert rather than removed, so the proof
can be re-run on demand.

---

## 3. What the audit found that green runs did not say

### 3.1 The verification layer never rendered the state production reached

**Severity: high. Fixed in Phase 8.**

Between 08-27 and 08-30 the product moved from a uniformly `low` board with a null trend to a
mostly-`medium` board with a measured trend and a *sufficient* cohort. Not one test in the
repository rendered the second state. Every market-sensitive assertion — vitest, Playwright,
mobile — was written against the launch condition, and `web/tests/fixtures/artifacts.ts` said
so in its own header: *"Every arbitrage row carries `low` confidence and a null trend, which
mirrors the launch condition."*

That is the same defect class as the Phase-7 trend verifier, which had frozen the null launch
state into an assertion and failed on the first correct build with a trend. The verifier was
fixed; the fixture it shared a premise with was not.

Fixed by `MARKET_CONDITIONS` — a second fixture board carrying mixed confidence, a measured
trend on most rows and a null one on at least one, a cohort clearing every clause, and one
preset the build calls *exact* — with the market-sensitive tests run against both, and neither
treated as the normal one.

### 3.2 UI copy that was true only at launch

**Severity: medium. Fixed in Phase 8.** Three statements were asserted rather than derived:

- the Data view stated that a board with a failed clause *therefore* carries low confidence —
  hardcoding a label the rubric computes;
- "The redraft market population is early", true on 08-22 and false on 08-31;
- "Market trend needs history we are still collecting… until then it is blank", ditto.

All three now read from `build_metadata`. The product moves `low` → `medium` → `high` and back
to a null trend with no code change, and `web/tests/app.test.tsx` runs the same components
against both fixture conditions.

### 3.3 A URL parameter with a bound taken from an assumption

**Severity: medium, self-inflicted, caught by its own test.** The Phase-8 tier-collapse state
serializes open tier ordinals into the URL. The first parser required a *positive* integer;
`schemas/tier_record.schema.json` declares `tier_ordinal` with `minimum: 0`, and the first tier
really is 0. Every shared link would silently have dropped the first tier. Caught by the
end-to-end test written alongside it, and pinned by a regression test that cites the schema.

Worth recording because it is the phase's own lesson turned on itself: the bound came from
what looked reasonable rather than from the contract that was one file away.

---

## 4. Assumptions still standing on today's data

Answers to the adversarial questions, as of 2026-08-31.

| question | answer |
|---|---|
| What assertions still encode today's data? | None found in the frontend after the fixture split. Python test constants are fixture-defined (a test that constructs `total_drafts=125` and asserts the clause it produces is a contract test, not a live-data pin). |
| What source silence are we still treating as absence? | `injury_start_date`, `practice_participation` and `practice_description` are published by Sleeper as keys with null values in the preseason. The UI omits an absent field rather than rendering an em dash, so they will appear when they populate. Not an assumption — a rendering rule. |
| What optional source is accidentally critical? | None. `capture-status` failing degrades annotation only; a missing arbitrage artifact degrades one view; `player_status` and `projections` are both optional in the loader. Only `build_metadata` and `tiers` are critical, and both are refusals rather than silent degradations. |
| What warning has grown while the workflow stayed green? | None. Three warnings, identical text, seven runs. |
| What UI copy becomes false when conditions change? | Fixed — see 3.2. The remaining conditional text is derived from `build_metadata` and covered by both fixture conditions. |
| What artifact could go stale while its card stayed green? | The model cards are generated from committed reports and the artifact; Phase 8 regenerated them and diffed — identical outside `generated_at_utc`, `git_sha` and one block that needs a gitignored input. The `arbitrage-method-a0` card is generated from build outputs and is runner-side. |
| What private value could reach a public artifact? | Nothing found. The build record stages `manifest.json` files only — a whitelist, not a filter — and asserts no `.gz` reached it. Capture logs print aggregate counts, never player rows. See `docs/PHASE8_SECURITY_REVIEW.md`. |
| What status field might enter a model path? | None. `tests/contract/test_architecture_boundary.py` walks the import graph from every intrinsic module, function-local imports included, and fails on any path to market or status data. |
| What works only in Chromium? | Nothing, as of run [33407642729](https://github.com/jeisey/jeisey-tiers/actions/runs/33407642729): the primary flows, focus, dialog semantics, downloads, reflow and reduced motion pass on Chromium, Firefox and WebKit. |
| What looks right with fixtures and wrong with real names? | The fixture board carries the awkward cases deliberately (suffixes, a long name, an unpriced player, no status record, two quarterback premiums). The real board is checked by `npm run verify:board` on every production build. |
| What would make the live site disappear? | Nothing in the graph. `deploy` `needs:` `build` `needs:` `capture`, the deploy job contains only the Pages actions, and no step anywhere clears the live site. Exercised again in §5 of the failure drills. |
| What limitation are we tempted to "fix" without a valid holdout? | Three, all deferred on purpose: correlated player draws, historical injury features, learned arbitrage. The 2025 holdout is spent, so none of them has anything to be promoted against. |

---

## 5. Verdict

No critical or high defect in production behaviour. Two high-severity defects in the
*verification layer* — both instances of pinning a launch condition rather than a contract —
found and fixed. Everything else is a watch item with a measured explanation.

The five green days are real. They are also, on their own, exactly as much evidence as this
audit was written to assume: that nothing failed loudly.
