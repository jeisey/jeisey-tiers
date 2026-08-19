"""The Phase-3 promotion gate and the training-window selection rule.

Both rules are written here **before** the decisive comparison runs, and the module is
committed before the experiment that consumes it, so the repository history shows the gate
was frozen rather than fitted to whatever the candidate happened to win. Changing a
threshold after seeing results is a different, later decision and needs its own ADR.

What the gate demands of a candidate, against the primary baseline B0:

1. **Aggregate predictive improvement.** Lower macro MAE, with the paired bootstrap 95%
   interval for the delta entirely below zero.
2. **Aggregate probabilistic improvement.** Lower macro mean pinball loss, with its paired
   interval entirely below zero. Point accuracy alone is not enough for a model whose
   product is a distribution.
3. **Ranking stays competitive.** Macro Spearman may not fall more than 0.010 below the
   baseline. It is not required to improve: a draft board is ranked *within* position, and a
   candidate that is better calibrated without reordering anyone is still worth having.
4. **No hidden positional collapse.** For every position, the candidate's MAE may not be
   more than 3% worse than the baseline's, its Spearman may not be more than 0.030 worse,
   and its empirical P10-P90 coverage must stay inside [0.60, 0.95]. A large aggregate win
   that guts QB or TE does not pass.

Deliberately *not* required: that every season-by-position-by-scoring slice improves. With
sixty cells, demanding that of all of them would select for luck, not skill. The positional
rule bounds real deterioration instead, using a materiality threshold rather than a sign
test.

The window rule is equally explicit, and defaults to the conservative choice: unless one
window wins both primary metrics with intervals that exclude zero, W2 (2017+) is selected,
because it avoids the known upstream eligibility regime change rather than averaging across
it.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from ffdraft.modeling.bootstrap import BootstrapDelta
from ffdraft.modeling.folds import WindowPolicy

__all__ = [
    "PROMOTION_CRITERIA",
    "GateResult",
    "PositionalEvidence",
    "PromotionCriteria",
    "WindowDecision",
    "evaluate_promotion_gate",
    "select_training_window",
]


@dataclass(frozen=True)
class PromotionCriteria:
    """The frozen comparison rule. Version it rather than editing it in place."""

    version: str = "phase3_promotion_v1"
    primary_baseline: str = "B0"
    primary_point_metric: str = "mae"
    primary_probabilistic_metric: str = "mean_pinball"
    rank_metric: str = "spearman"
    #: Macro Spearman may fall by at most this much before the candidate is refused.
    max_rank_regression: float = 0.010
    #: A position's MAE may be at most this much worse, relative to the baseline's.
    positional_mae_tolerance: float = 0.03
    #: A position's Spearman may be at most this much worse, in absolute correlation.
    positional_rank_tolerance: float = 0.030
    #: A position's empirical P10-P90 coverage must stay inside this band. Outside it the
    #: intervals are either badly overconfident or so wide they say nothing.
    coverage_band: tuple[float, float] = (0.60, 0.95)
    #: Whether the paired bootstrap interval must exclude zero for the two primary metrics.
    require_interval_excludes_zero: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "criteria_version": self.version,
            "primary_baseline": self.primary_baseline,
            "primary_point_metric": self.primary_point_metric,
            "primary_probabilistic_metric": self.primary_probabilistic_metric,
            "rank_metric": self.rank_metric,
            "max_rank_regression": self.max_rank_regression,
            "positional_mae_tolerance": self.positional_mae_tolerance,
            "positional_rank_tolerance": self.positional_rank_tolerance,
            "coverage_band": list(self.coverage_band),
            "require_interval_excludes_zero": self.require_interval_excludes_zero,
            "rules": [
                "macro MAE improves and its paired 95% CI excludes zero",
                "macro mean pinball loss improves and its paired 95% CI excludes zero",
                "macro Spearman falls by no more than max_rank_regression",
                "no position exceeds the MAE, Spearman or coverage tolerances",
            ],
        }


#: The frozen instance every Phase-3 run uses.
PROMOTION_CRITERIA = PromotionCriteria()


@dataclass(frozen=True)
class PositionalEvidence:
    """Per-position aggregates for the collapse rule."""

    position: str
    baseline_mae: float
    candidate_mae: float
    baseline_spearman: float
    candidate_spearman: float
    candidate_coverage_p10_p90: float

    @property
    def mae_regression(self) -> float:
        """Relative MAE deterioration; negative means the candidate is better."""
        if self.baseline_mae == 0.0:
            return 0.0
        return (self.candidate_mae - self.baseline_mae) / self.baseline_mae

    @property
    def rank_regression(self) -> float:
        return self.baseline_spearman - self.candidate_spearman

    def to_dict(self) -> dict[str, Any]:
        return {
            "position": self.position,
            "baseline_mae": self.baseline_mae,
            "candidate_mae": self.candidate_mae,
            "mae_regression": self.mae_regression,
            "baseline_spearman": self.baseline_spearman,
            "candidate_spearman": self.candidate_spearman,
            "rank_regression": self.rank_regression,
            "candidate_coverage_p10_p90": self.candidate_coverage_p10_p90,
        }


@dataclass(frozen=True)
class GateResult:
    """Whether one candidate passes, and exactly which clause decided it."""

    model_id: str
    window: str
    passed: bool
    criteria: PromotionCriteria
    reasons: tuple[str, ...]
    failures: tuple[str, ...]
    positional_collapse: tuple[str, ...]
    deltas: Mapping[str, BootstrapDelta] = field(default_factory=dict)
    positional: tuple[PositionalEvidence, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "window_policy": self.window,
            "passed": self.passed,
            "criteria": self.criteria.to_dict(),
            "reasons": list(self.reasons),
            "failures": list(self.failures),
            "positional_collapse": list(self.positional_collapse),
            "deltas": {name: delta.to_dict() for name, delta in self.deltas.items()},
            "positional_evidence": [item.to_dict() for item in self.positional],
        }


def evaluate_promotion_gate(
    *,
    model_id: str,
    window: str,
    deltas: Mapping[str, BootstrapDelta],
    positional: Sequence[PositionalEvidence],
    criteria: PromotionCriteria = PROMOTION_CRITERIA,
) -> GateResult:
    """Apply the frozen rule. Pure, so the synthetic tests can drive it directly."""
    reasons: list[str] = []
    failures: list[str] = []

    for metric, label in (
        (criteria.primary_point_metric, "point accuracy"),
        (criteria.primary_probabilistic_metric, "probabilistic quality"),
    ):
        delta = deltas.get(metric)
        if delta is None:
            failures.append(f"{label}: no paired delta for {metric} was computed")
            continue
        if delta.delta >= 0.0:
            failures.append(
                f"{label}: {metric} did not improve (delta {delta.delta:+.4f})",
            )
        elif criteria.require_interval_excludes_zero and not delta.significant:
            failures.append(
                f"{label}: {metric} improved by {delta.delta:+.4f} but the 95% interval "
                f"[{delta.ci_low:+.4f}, {delta.ci_high:+.4f}] includes zero",
            )
        else:
            reasons.append(
                f"{label}: {metric} {delta.delta:+.4f} [{delta.ci_low:+.4f}, {delta.ci_high:+.4f}]",
            )

    rank = deltas.get(criteria.rank_metric)
    if rank is None:
        failures.append(f"ranking: no paired delta for {criteria.rank_metric} was computed")
    elif -rank.delta > criteria.max_rank_regression:
        failures.append(
            f"ranking: {criteria.rank_metric} fell {-rank.delta:.4f}, beyond the "
            f"{criteria.max_rank_regression:.3f} tolerance",
        )
    else:
        reasons.append(f"ranking: {criteria.rank_metric} {rank.delta:+.4f} within tolerance")

    collapse: list[str] = []
    low, high = criteria.coverage_band
    for evidence in positional:
        if evidence.mae_regression > criteria.positional_mae_tolerance:
            collapse.append(
                f"{evidence.position}: MAE {evidence.mae_regression:+.1%} worse than baseline",
            )
        if evidence.rank_regression > criteria.positional_rank_tolerance:
            collapse.append(
                f"{evidence.position}: Spearman {evidence.rank_regression:.3f} below baseline",
            )
        if not (low <= evidence.candidate_coverage_p10_p90 <= high):
            collapse.append(
                f"{evidence.position}: P10-P90 coverage "
                f"{evidence.candidate_coverage_p10_p90:.3f} outside [{low}, {high}]",
            )
    if collapse:
        failures.append("positional collapse: " + "; ".join(collapse))
    elif positional:
        reasons.append(f"no positional collapse across {len(positional)} position(s)")

    return GateResult(
        model_id=model_id,
        window=window,
        passed=not failures,
        criteria=criteria,
        reasons=tuple(reasons),
        failures=tuple(failures),
        positional_collapse=tuple(collapse),
        deltas=dict(deltas),
        positional=tuple(positional),
    )


@dataclass(frozen=True)
class WindowDecision:
    """Which training window Phase 4 inherits, and on what evidence."""

    selected: WindowPolicy
    decisive: bool
    rationale: str
    deltas: Mapping[str, BootstrapDelta] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "selected_window": str(self.selected),
            "decisive": self.decisive,
            "rationale": self.rationale,
            "deltas_w1_relative_to_w2": {
                name: delta.to_dict() for name, delta in self.deltas.items()
            },
        }


def select_training_window(
    deltas: Mapping[str, BootstrapDelta],
    *,
    criteria: PromotionCriteria = PROMOTION_CRITERIA,
    conservative_default: WindowPolicy = WindowPolicy.W2,
) -> WindowDecision:
    """Choose W1 or W2 from paired deltas of W1 relative to W2 on the common folds.

    ``deltas`` must be computed with W2 as the "baseline" and W1 as the "candidate", so a
    negative delta on a loss metric favours W1. A window wins only by taking both primary
    metrics with intervals that exclude zero; anything else is inconclusive and the
    conservative default stands, because W2's eligibility universe is the structurally
    consistent one and a hybrid invented to avoid choosing would be worse than either.
    """
    point = deltas.get(criteria.primary_point_metric)
    probabilistic = deltas.get(criteria.primary_probabilistic_metric)
    if point is None or probabilistic is None:
        return WindowDecision(
            selected=conservative_default,
            decisive=False,
            rationale=(
                "the primary window deltas were not computed, so the conservative tie-break "
                f"selects {conservative_default}"
            ),
            deltas=dict(deltas),
        )

    w1_wins = [delta.delta < 0.0 and delta.significant for delta in (point, probabilistic)]
    w2_wins = [delta.delta > 0.0 and delta.significant for delta in (point, probabilistic)]
    if all(w1_wins):
        return WindowDecision(
            selected=WindowPolicy.W1,
            decisive=True,
            rationale=(
                "W1 improves both primary metrics on the common folds with paired 95% "
                f"intervals excluding zero (MAE {point.delta:+.4f} "
                f"[{point.ci_low:+.4f}, {point.ci_high:+.4f}], pinball "
                f"{probabilistic.delta:+.4f} "
                f"[{probabilistic.ci_low:+.4f}, {probabilistic.ci_high:+.4f}])"
            ),
            deltas=dict(deltas),
        )
    if all(w2_wins):
        return WindowDecision(
            selected=WindowPolicy.W2,
            decisive=True,
            rationale=(
                "W2 improves both primary metrics on the common folds with paired 95% "
                f"intervals excluding zero (MAE {-point.delta:+.4f} "
                f"[{-point.ci_high:+.4f}, {-point.ci_low:+.4f}], pinball "
                f"{-probabilistic.delta:+.4f} "
                f"[{-probabilistic.ci_high:+.4f}, {-probabilistic.ci_low:+.4f}] in W2's favour)"
            ),
            deltas=dict(deltas),
        )
    return WindowDecision(
        selected=conservative_default,
        decisive=False,
        rationale=(
            "neither window wins both primary metrics with an interval excluding zero "
            f"(MAE {point.delta:+.4f} [{point.ci_low:+.4f}, {point.ci_high:+.4f}], pinball "
            f"{probabilistic.delta:+.4f} "
            f"[{probabilistic.ci_low:+.4f}, {probabilistic.ci_high:+.4f}], W1 relative to "
            f"W2), so the predeclared conservative tie-break selects {conservative_default}: "
            "its eligibility universe does not straddle the 2016 roster-coverage step"
        ),
        deltas=dict(deltas),
    )
