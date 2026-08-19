# Experiment reports

Each directory is the committed evidence behind one promotion decision. Every report comes
in two forms written from the same result object, so the prose cannot drift from the numbers
it describes: `experiment.json` is the record of what happened, `experiment.md` is the
argument about what it means.

| Directory | Command | Decides |
|---|---|---|
| `phase3-intrinsic-baselines/` | `ffdraft evaluate-intrinsic` | the training window (ADR-028) and the Phase-3 candidate (ADR-029) |
| `phase4-intrinsic-distribution/` | `ffdraft evaluate-distribution` | quantile monotonicity and calibration (ADR-031), the horizon sensitivity (ADR-032), and Candidate A vs B (ADR-033) |
| `phase4-simulation-ranking/` | `ffdraft evaluate-simulation` | the Monte Carlo draw count and the fair-ranking statistic (ADR-034) |
| `phase4-tier-segmentation/` | `ffdraft evaluate-tiers` | the tier algorithm, its penalty and its stability (ADR-035) |
| `phase4-final-holdout/` | `ffdraft evaluate-intrinsic --final-eval …` | whether the frozen production model is released (ADR-037) |

Three conventions hold across all of them.

**The rule precedes the number.** Every decision in these reports was made by a comparator
frozen in code and committed before the evidence existed — `phase3_promotion_v1` for Phase 3,
`phase4_rules_v1` for Phase 4. Each report prints the rule version it was judged under and
the exact clause that decided it, including the clauses that refused something.

**A failure is a result.** Reports record what did not pass as prominently as what did: B1
failing the Phase-3 gate, the fitted calibration losing on interval width, the horizon
variant making 2021 worse, no draw count meeting every convergence tolerance. None of those
thresholds was moved afterwards.

**Row-level predictions are not committed.** They are reproducible from the command plus the
historical dataset, and they are large. `--write-predictions` produces them locally and they
are gitignored, in the same spirit as `data/historical/`.

The final-holdout directory is different in kind from the others: producing it consumed
season 2025, which can happen exactly once. Its report says so, and nothing in the
repository may take a model-design decision against it afterwards.
