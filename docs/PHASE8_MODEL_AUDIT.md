# Phase-8 model, backtest and card audit

Four questions. Is the production artifact the one the repository thinks it is; do the committed
reports still reproduce; do the cards describe the artifact on disk; and is the intrinsic
firewall still intact.

**What this audit deliberately does not do.** The sealed 2025 holdout was consumed once, at
`2f0e725`, and is spent (ADR-036). It is checked here for *integrity* — that the committed
report corresponds to the code and the artifact — and it is not re-run, not re-read for a
decision, and not used to justify anything. There is no route in this phase from a number in
that report to a change in the product.

---

## 1. Artifact integrity

`models/production/intrinsic-cb-hurdle-v1/`, re-hashed and re-checked against the code.

| check | result |
|---|---|
| boosters checked | **120** |
| digest mismatches | **0** |
| serialized-object files (`.pkl`, `.joblib`, `.npy`, `.pt`, `.h5`) | **0** |
| features: artifact / code | **78 / 78**, identical lists |
| `feature_set_hash`: artifact / code | `7203befaa5be25a2` / `7203befaa5be25a2` |
| `feature_schema_hash` | `c495ba3177dcb989` |
| training seasons | 2014–2025 |

**A note on how the digests are computed, because getting it wrong looks like catastrophe.**
`ProductionModel.save` hashes the booster's LightGBM **text** (`model_to_string()`) and *then*
gzips it with `mtime=0`. Hashing the `.gz` container compares the compressor rather than the
model and reports 120 mismatches on a perfectly good artifact — which is what the first run of
this audit did. The loader gets it right (`_read_booster` decompresses, then verifies), so a
tampered booster fails closed at load time.

## 2. Forbidden-feature audit

The intrinsic model may never receive ADP, ECR, expert rank, FantasyPros or FantasyCalc output,
a sportsbook proxy, or the arbitrage model's own output (ADR-002, AGENTS.md §8).

- **Token scan** over the artifact's 78 feature names for `adp`, `ecr`, `expert`, `consensus`,
  `fantasypros`, `fantasycalc`, `market`, `arbitrage`, `rank_gap`, `sportsbook`, `odds`,
  `vegas`: **0 matches**.
- **The repository's own rule**, `assert_no_forbidden_features`, run against the artifact's
  feature list rather than against the code's: **passes**. This is the stricter check — the
  Phase-3 view may only *narrow* the Phase-2 model inputs, so a feature that entered the
  artifact from anywhere else would be caught even if its name looked innocent.
- **The structural check** is unchanged and still green:
  `tests/contract/test_architecture_boundary.py` walks the import graph from every intrinsic
  module, function-local imports included, and fails on any path to market or status data.

## 3. Report and card reproduction

`uv run ffdraft model-card` regenerates the intrinsic model card and the tier-method report
from the committed experiment reports and the artifact — nothing is hand-written. Regenerated
into a scratch directory and deep-diffed against the committed pair.

| card | differences outside `generated_at_utc` / `git_sha` |
|---|---|
| `intrinsic-cb-hurdle-v1.json` | **0** |
| `tier-method.json` | **0** |

One block, `interval_coverage_by_participation`, is absent from the regenerated card because it
is computed from `oof_predictions.parquet` and `labels_fantasy.parquet`, both gitignored. The
card degrades to *"Participation-split coverage was not supplied to this card"* rather than
inventing a number, which is the correct behaviour. Every other value — the development
aggregates, the final-holdout slice table, the frozen rules, the simulation and tier blocks,
the dataset manifest with its five content hashes — is byte-identical.

**What that establishes.** The committed cards describe *this* artifact and *these* reports,
under the current code. A retrain that forgot to regenerate them would show up here as a diff,
and the risk recorded in `SESSION_STATE.md` — "a card is only as current as the last
`ffdraft model-card` run" — is therefore live but currently clean.

**Not reproduced here, and why.** `evaluate-intrinsic`, `evaluate-distribution`,
`evaluate-simulation` and `evaluate-tiers` all read `data/historical/`, which is gitignored and
rebuilt from nflverse over the network. That is a runner-side reproduction, not a sandbox one
(ADR-009), and Phase 4 already ran the strongest version of it: `evaluate-intrinsic` was re-run
and diffed against the committed Phase-3 report, identical on every number, decision and check
with only the timestamped `experiment_id` differing. The determinism claim is established; what
Phase 8 adds is that the *artifact and cards* still agree with those reports.

**`arbitrage-method-a0` is runner-side.** It is generated from the built arbitrage artifact and
the cohort report, both of which need the retained store. It regenerates on every production
build path rather than here.

## 4. Monte Carlo convergence

Recorded in full in **ADR-057**. The short version:

`phase4_convergence_v1` asked one question of two properties and its tier clause was stricter
than the tier gate it protected. `phase8_simulation_convergence_v1` — frozen and committed at
`87db5e5` *before* it was pointed at any report — evaluates the promoted configuration only,
inherits every bound unchanged, reports tier agreement instead of deciding on it, and has no
code path to selecting a draw count.

**Result: not converged, for a much narrower reason.** At 10,000 draws, across eight
comparisons:

- **converged**: fair-rank Spearman 0.9994 (≥0.9990), top-50 overlap 0.98 (≥0.96), mean top-150
  rank change 1.35 (≤1.5), replacement 0.249 (≤0.5), outer-interval mean 0.451 (≤0.6) and p99
  2.72 (≤5.0), median-interval p99 2.85 (≤3.0);
- **not converged**: mean |Δ expected VORP| 0.314 (≤0.25), mean |Δ P50 VORP| 0.416 (≤0.35),
  p99 |Δ expected VORP| 1.93 (≤1.50).

*Ranking is operationally converged and value is not.* The board's published order barely moves
between seeds; a player's printed VORP carries about ±0.3 points of Monte Carlo noise. Tier
agreement at the promoted count is ARI 0.499 with a five-tier count difference — recorded, and
owned by ADR-035 rather than by this rule.

**Nothing changed.** The production draw count is 10,000 and stays there. `ffdraft
audit-convergence` reproduces the table above from the committed report.

## 5. What was deliberately not done

Each of these was considered and declined for a stated reason, not skipped.

| | why not |
|---|---|
| retrain the intrinsic model | the 2025 holdout is spent; a new model has nothing to be promoted against (ADR-036) |
| create `intrinsic_core_v2` | same, and Phase 8 is hardening |
| reuse 2025 as a fresh holdout | the seal is one-way in code and there is no softer path; adding one would be the single most damaging change available |
| add historical injury features | a 2027 refresh candidate, needing a new feature set and evaluation protocol (ADR-044) |
| add correlated player draws | it changes the simulated joint distribution that produces replacement, VORP, fair rank and tiers — a structural model change during hardening, with no valid holdout |
| train a learned arbitrage model | needs three complete seasons of retained point-in-time market history; 2029 at the earliest (ADR-010) |
| lower the production draw count | the audit found sampling that has not fully settled, which is not an argument for fewer samples |
| lower `min_boundary_agreement` | ADR-035's measurement is the finding; the redesign makes boundary positions less prominent instead |

## 6. Findings

**None critical or high.** Two carried forward, both already published limitations rather than
new discoveries:

1. **The value residual at 10,000 draws** (§4). Narrowed from "the convergence rule disagrees
   with itself" to a measured 19–29% overshoot on three criteria. A 2027 simulation-refresh
   target.
2. **Tier boundaries remain unidentified.** Membership reproduces (ARI 0.865); positions do not
   (boundary agreement 0.239). Published with the failure attached, and the Phase-8 board now
   draws overlapping tier spans rather than implying edges.

## Reproducing this audit

```bash
uv run ffdraft audit-convergence                       # §4
uv run ffdraft model-card --out /tmp/cards             # §3, then diff against models/cards/
uv run pytest tests/contract/test_architecture_boundary.py tests/leakage    # §2
```

Artifact integrity (§1) is a short script rather than a command: re-hash each
`boosters/*.txt.gz` after `gzip.decompress` and compare with `metadata.json`'s
`booster_sha256`, then compare the artifact's `features` and `feature_set_hash` with
`core_feature_selection()`.
