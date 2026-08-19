"""The frozen Phase-4 decision rules.

Phase 3 froze its promotion gate in :mod:`ffdraft.modeling.gate` *before* the decisive
comparison ran, and the repository history is the evidence that it did. Phase 4 has more
decisions to make than Phase 3 did - a calibration method, a second candidate family, a
target-scale sensitivity, a Monte Carlo draw count, a production ranking statistic, a tier
penalty and a final-holdout acceptance rule - so all of them are written here, in one
module, and committed before any of their results exist.

Every rule follows the same three-part shape:

1. a frozen :class:`~dataclasses.dataclass` of thresholds with a version string;
2. a **pure** evaluation function that turns measured evidence into a decision and the exact
   clause that decided it;
3. a default instance the Phase-4 studies use.

Purity matters: a rule that can be driven by synthetic numbers in a test is a rule whose
behaviour is checkable without running a five-minute experiment, and one that cannot quietly
consult the data it is judging.

Two conventions run through the whole module.

**Simplicity is the default, and complexity must earn itself.** The calibration rule keeps
the plain monotone projection unless the fitted variant demonstrably improves calibration;
the candidate rule keeps Candidate A unless Candidate B wins on probabilistic quality *and*
something else; the ranking rule keeps median VORP unless expected VORP measurably improves
the top of the board. Mixed or indistinguishable evidence always resolves to the simpler
incumbent, never to the more interesting option.

**Deterioration is bounded, improvement is not demanded everywhere.** With sixty-odd
evaluation cells, requiring every one to improve would select for luck. So the positional
clauses bound how much worse a position may get, exactly as ``phase3_promotion_v1`` does.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "CALIBRATION_ACCEPTANCE",
    "CANDIDATE_COMPARISON",
    "CONVERGENCE_TOLERANCE",
    "FINAL_HOLDOUT_GATE",
    "HORIZON_SENSITIVITY",
    "PHASE4_RULES_VERSION",
    "RANKING_SELECTION",
    "TIER_BOARD_DEPTH",
    "TIER_PENALTY_GRID",
    "TIER_SELECTION",
    "TIER_STABILITY_GATE",
    "CalibrationAcceptance",
    "CalibrationEvidence",
    "CandidateComparison",
    "ConvergenceEvidence",
    "ConvergenceTolerance",
    "Decision",
    "FinalHoldoutGate",
    "HorizonEvidence",
    "HorizonSensitivity",
    "PairedDelta",
    "PositionalCalibration",
    "RankingEvidence",
    "RankingSelection",
    "TierCandidateEvidence",
    "TierSelection",
    "TierStabilityEvidence",
    "TierStabilityGate",
    "all_rules",
    "evaluate_calibration_choice",
    "evaluate_candidate_choice",
    "evaluate_convergence",
    "evaluate_final_holdout",
    "evaluate_horizon_choice",
    "evaluate_ranking_choice",
    "evaluate_tier_stability",
    "select_tier_penalty",
]

#: Bump when any rule below changes. A change after a decisive result is a new decision and
#: needs its own ADR; it is never an edit in place.
PHASE4_RULES_VERSION = "phase4_rules_v1"


@dataclass(frozen=True, slots=True)
class Decision:
    """What a rule decided, and the clauses that decided it."""

    rule: str
    selected: str
    decisive: bool
    reasons: tuple[str, ...] = ()
    failures: tuple[str, ...] = ()
    evidence: Mapping[str, Any] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return not self.failures

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule": self.rule,
            "rules_version": PHASE4_RULES_VERSION,
            "selected": self.selected,
            "decisive": self.decisive,
            "reasons": list(self.reasons),
            "failures": list(self.failures),
            "evidence": dict(self.evidence),
        }


@dataclass(frozen=True, slots=True)
class PairedDelta:
    """A paired bootstrap delta, candidate minus reference.

    Mirrors :class:`ffdraft.modeling.bootstrap.BootstrapDelta` without importing it, so the
    rules stay drivable from plain numbers in a test.
    """

    metric: str
    delta: float
    ci_low: float
    ci_high: float

    @property
    def significant(self) -> bool:
        """Whether the 95% interval excludes zero."""
        return self.ci_low > 0.0 or self.ci_high < 0.0

    @property
    def improves(self) -> bool:
        """For a loss metric: lower is better and the interval excludes zero."""
        return self.delta < 0.0 and self.significant

    def render(self) -> str:
        return f"{self.metric} {self.delta:+.4f} [{self.ci_low:+.4f}, {self.ci_high:+.4f}]"

    def to_dict(self) -> dict[str, Any]:
        return {
            "metric": self.metric,
            "delta": self.delta,
            "ci_low": self.ci_low,
            "ci_high": self.ci_high,
            "significant": self.significant,
        }


# ---------------------------------------------------------------------------------------
# 1. Calibration and quantile monotonicity
# ---------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PositionalCalibration:
    """One position's measured interval coverage for a distribution variant."""

    position: str
    coverage_p10_p90: float
    coverage_p25_p75: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "position": self.position,
            "coverage_p10_p90": self.coverage_p10_p90,
            "coverage_p25_p75": self.coverage_p25_p75,
        }


@dataclass(frozen=True, slots=True)
class CalibrationEvidence:
    """Everything measured about one candidate predictive distribution.

    All aggregates are macro means over validation season x position x scoring cells, the
    same convention Phase 3 used, so a large position cannot outvote a small one.
    """

    variant_id: str
    macro_mean_pinball: float
    macro_mae: float
    coverage_p10_p90: float
    coverage_p25_p75: float
    mean_width_p10_p90: float
    crossing_rate_raw: float
    crossing_rate_post: float
    positional: tuple[PositionalCalibration, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "variant_id": self.variant_id,
            "macro_mean_pinball": self.macro_mean_pinball,
            "macro_mae": self.macro_mae,
            "coverage_p10_p90": self.coverage_p10_p90,
            "coverage_p25_p75": self.coverage_p25_p75,
            "mean_width_p10_p90": self.mean_width_p10_p90,
            "crossing_rate_raw": self.crossing_rate_raw,
            "crossing_rate_post": self.crossing_rate_post,
            "positional": [item.to_dict() for item in self.positional],
        }


@dataclass(frozen=True)
class CalibrationAcceptance:
    """When a fitted calibration layer may replace plain monotone projection.

    The objective is *not* to hit nominal coverage exactly. Any interval can be made to
    cover 80% of observations by making it wide enough, and a draft sheet whose floor and
    ceiling are 250 points apart has told the reader nothing. So coverage improvement is
    required to arrive without a pinball regression and without width inflation, and every
    variant, fitted or not, has to clear the same hard requirements first.
    """

    version: str = "phase4_calibration_v1"
    #: Nominal coverage of the two reported intervals.
    nominal_p10_p90: float = 0.80
    nominal_p25_p75: float = 0.50
    #: Hard requirement: production quantiles may not cross at all after post-processing.
    max_post_crossing_rate: float = 0.0
    #: Hard requirement: no position may be severely miscalibrated.
    positional_p10_p90_band: tuple[float, float] = (0.70, 0.90)
    positional_p25_p75_band: tuple[float, float] = (0.40, 0.60)
    #: The fitted variant may not lose more than this share of the reference's pinball loss.
    max_pinball_regression_ratio: float = 0.005
    #: ... and must close the P10-P90 coverage gap by at least this much to be worth it.
    min_coverage_gain: float = 0.010
    #: The inner interval's coverage gap may not widen by more than this.
    max_inner_coverage_loss: float = 0.010
    #: Interval width may grow by at most this share. Beyond it, coverage was bought.
    max_width_inflation_ratio: float = 0.15

    def to_dict(self) -> dict[str, Any]:
        return {
            "criteria_version": self.version,
            "nominal_p10_p90": self.nominal_p10_p90,
            "nominal_p25_p75": self.nominal_p25_p75,
            "max_post_crossing_rate": self.max_post_crossing_rate,
            "positional_p10_p90_band": list(self.positional_p10_p90_band),
            "positional_p25_p75_band": list(self.positional_p25_p75_band),
            "max_pinball_regression_ratio": self.max_pinball_regression_ratio,
            "min_coverage_gain": self.min_coverage_gain,
            "max_inner_coverage_loss": self.max_inner_coverage_loss,
            "max_width_inflation_ratio": self.max_width_inflation_ratio,
            "rules": [
                "every variant: zero post-processing quantile crossings",
                "every variant: each position's P10-P90 coverage inside the declared band",
                "every variant: each position's P25-P75 coverage inside the declared band",
                "the fitted variant replaces monotone projection only if it also: "
                "closes the P10-P90 coverage gap by min_coverage_gain, does not widen the "
                "P25-P75 gap by more than max_inner_coverage_loss, does not lose more than "
                "max_pinball_regression_ratio of pinball loss, and inflates mean P10-P90 "
                "width by no more than max_width_inflation_ratio",
                "otherwise the simpler variant stands",
            ],
        }

    def hard_requirement_failures(self, evidence: CalibrationEvidence) -> list[str]:
        """The clauses every production distribution must satisfy, fitted or not."""
        failures: list[str] = []
        if evidence.crossing_rate_post > self.max_post_crossing_rate:
            failures.append(
                f"{evidence.variant_id}: post-processing crossing rate "
                f"{evidence.crossing_rate_post:.4f} exceeds "
                f"{self.max_post_crossing_rate:.4f}",
            )
        outer_low, outer_high = self.positional_p10_p90_band
        inner_low, inner_high = self.positional_p25_p75_band
        for item in evidence.positional:
            if not outer_low <= item.coverage_p10_p90 <= outer_high:
                failures.append(
                    f"{evidence.variant_id}/{item.position}: P10-P90 coverage "
                    f"{item.coverage_p10_p90:.3f} outside [{outer_low}, {outer_high}]",
                )
            if not inner_low <= item.coverage_p25_p75 <= inner_high:
                failures.append(
                    f"{evidence.variant_id}/{item.position}: P25-P75 coverage "
                    f"{item.coverage_p25_p75:.3f} outside [{inner_low}, {inner_high}]",
                )
        return failures


CALIBRATION_ACCEPTANCE = CalibrationAcceptance()


def evaluate_calibration_choice(
    reference: CalibrationEvidence,
    candidate: CalibrationEvidence,
    *,
    criteria: CalibrationAcceptance = CALIBRATION_ACCEPTANCE,
) -> Decision:
    """Choose between plain monotone projection and a fitted calibration layer.

    ``reference`` is the simpler variant (C0: raw quantiles projected onto the monotone
    cone). ``candidate`` is the fitted one (C1). The simpler variant wins every tie.
    """
    reasons: list[str] = []
    failures: list[str] = []

    reference_hard = criteria.hard_requirement_failures(reference)
    candidate_hard = criteria.hard_requirement_failures(candidate)

    outer_gap_reference = abs(reference.coverage_p10_p90 - criteria.nominal_p10_p90)
    outer_gap_candidate = abs(candidate.coverage_p10_p90 - criteria.nominal_p10_p90)
    inner_gap_reference = abs(reference.coverage_p25_p75 - criteria.nominal_p25_p75)
    inner_gap_candidate = abs(candidate.coverage_p25_p75 - criteria.nominal_p25_p75)
    coverage_gain = outer_gap_reference - outer_gap_candidate
    inner_loss = inner_gap_candidate - inner_gap_reference
    pinball_ratio = (
        (candidate.macro_mean_pinball - reference.macro_mean_pinball) / reference.macro_mean_pinball
        if reference.macro_mean_pinball
        else 0.0
    )
    width_ratio = (
        (candidate.mean_width_p10_p90 - reference.mean_width_p10_p90) / reference.mean_width_p10_p90
        if reference.mean_width_p10_p90
        else 0.0
    )

    upgrade_blockers: list[str] = list(candidate_hard)
    if coverage_gain < criteria.min_coverage_gain:
        upgrade_blockers.append(
            f"P10-P90 coverage gap closed by only {coverage_gain:+.4f}, below the "
            f"{criteria.min_coverage_gain:.3f} required",
        )
    if inner_loss > criteria.max_inner_coverage_loss:
        upgrade_blockers.append(
            f"P25-P75 coverage gap widened by {inner_loss:+.4f}, beyond the "
            f"{criteria.max_inner_coverage_loss:.3f} tolerance",
        )
    if pinball_ratio > criteria.max_pinball_regression_ratio:
        upgrade_blockers.append(
            f"mean pinball loss worsened by {pinball_ratio:+.2%}, beyond the "
            f"{criteria.max_pinball_regression_ratio:.2%} tolerance",
        )
    if width_ratio > criteria.max_width_inflation_ratio:
        upgrade_blockers.append(
            f"mean P10-P90 width inflated by {width_ratio:+.2%}, beyond the "
            f"{criteria.max_width_inflation_ratio:.0%} tolerance",
        )

    if not upgrade_blockers:
        selected, decisive = candidate.variant_id, True
        reasons.append(
            f"{candidate.variant_id} closes the P10-P90 coverage gap by {coverage_gain:+.4f} "
            f"at {pinball_ratio:+.2%} pinball and {width_ratio:+.2%} width",
        )
    elif not reference_hard:
        selected, decisive = reference.variant_id, False
        reasons.append(
            f"{reference.variant_id} stands: " + "; ".join(upgrade_blockers),
        )
    else:
        # Both variants breach a hard requirement. That is not a tie to be broken; it is a
        # blocked phase, and saying so is the whole reason the requirements are hard.
        selected, decisive = reference.variant_id, False
        failures.extend(reference_hard)
        failures.extend(candidate_hard)

    return Decision(
        rule=criteria.version,
        selected=selected,
        decisive=decisive,
        reasons=tuple(reasons),
        failures=tuple(failures),
        evidence={
            "criteria": criteria.to_dict(),
            "reference": reference.to_dict(),
            "candidate": candidate.to_dict(),
            "coverage_gain_p10_p90": coverage_gain,
            "inner_coverage_loss_p25_p75": inner_loss,
            "pinball_regression_ratio": pinball_ratio,
            "width_inflation_ratio": width_ratio,
            "reference_hard_requirement_failures": reference_hard,
            "candidate_hard_requirement_failures": candidate_hard,
            "upgrade_blockers": upgrade_blockers,
        },
    )


# ---------------------------------------------------------------------------------------
# 2. Horizon-normalization sensitivity
# ---------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class HorizonEvidence:
    """Measured comparison of the horizon-normalized variant against ordinary Q1."""

    #: Paired deltas, Q1-H minus Q1, over the common development folds.
    deltas: Mapping[str, PairedDelta]
    #: Macro MAE per validation season for each variant, keyed by season.
    baseline_mae_by_season: Mapping[int, float]
    candidate_mae_by_season: Mapping[int, float]

    def relative_mae_change(self, season: int) -> float:
        base = self.baseline_mae_by_season.get(season, float("nan"))
        cand = self.candidate_mae_by_season.get(season, float("nan"))
        if not base:
            return float("nan")
        return (cand - base) / base

    def to_dict(self) -> dict[str, Any]:
        return {
            "deltas": {name: delta.to_dict() for name, delta in self.deltas.items()},
            "baseline_mae_by_season": dict(self.baseline_mae_by_season),
            "candidate_mae_by_season": dict(self.candidate_mae_by_season),
        }


@dataclass(frozen=True)
class HorizonSensitivity:
    """When the horizon-normalized target replaces the plain season total.

    The 2021 validation fold is the reason this sensitivity exists: it is the one
    development fold trained entirely on 16-week fantasy seasons and validated on a 17-week
    one, so its target is on a ~6% different scale from every training row. Two ways to earn
    the change are declared, and only two - a clean win on both primary metrics, or a
    specific repair of the 2021 discontinuity that costs nothing elsewhere.
    """

    version: str = "phase4_horizon_v1"
    #: The one fold whose training window and validation season straddle the horizon change.
    discontinuity_season: int = 2021
    #: Route (b): the relative MAE improvement required on that fold.
    min_discontinuity_gain: float = 0.02
    #: Route (b): how much any other fold's MAE may worsen.
    max_other_fold_regression: float = 0.01

    def to_dict(self) -> dict[str, Any]:
        return {
            "criteria_version": self.version,
            "discontinuity_season": self.discontinuity_season,
            "min_discontinuity_gain": self.min_discontinuity_gain,
            "max_other_fold_regression": self.max_other_fold_regression,
            "rules": [
                "route (a): macro MAE and macro mean pinball both improve with paired 95% "
                "intervals excluding zero",
                "route (b): the discontinuity fold's macro MAE improves by at least "
                "min_discontinuity_gain relative, no other development fold's macro MAE "
                "worsens by more than max_other_fold_regression relative, and the overall "
                "macro mean pinball does not worsen",
                "otherwise ordinary Q1 is retained and no further horizon variant is built",
            ],
        }


HORIZON_SENSITIVITY = HorizonSensitivity()


def evaluate_horizon_choice(
    evidence: HorizonEvidence,
    *,
    criteria: HorizonSensitivity = HORIZON_SENSITIVITY,
    baseline_id: str = "Q1",
    candidate_id: str = "Q1H",
) -> Decision:
    """Decide whether the horizon-normalized target is adopted."""
    reasons: list[str] = []
    mae = evidence.deltas.get("mae")
    pinball = evidence.deltas.get("mean_pinball")

    route_a = bool(mae and pinball and mae.improves and pinball.improves)
    if route_a and mae is not None and pinball is not None:
        reasons.append(
            f"route (a): both primary metrics improve ({mae.render()}, {pinball.render()})"
        )

    discontinuity_change = evidence.relative_mae_change(criteria.discontinuity_season)
    other_regressions = {
        season: evidence.relative_mae_change(season)
        for season in sorted(evidence.baseline_mae_by_season)
        if season != criteria.discontinuity_season
    }
    worst_other = max(other_regressions.values(), default=float("nan"))
    route_b = (
        discontinuity_change == discontinuity_change  # not NaN
        and discontinuity_change <= -criteria.min_discontinuity_gain
        and (worst_other != worst_other or worst_other <= criteria.max_other_fold_regression)
        and pinball is not None
        and pinball.delta <= 0.0
    )
    if route_b:
        reasons.append(
            f"route (b): {criteria.discontinuity_season} MAE {discontinuity_change:+.2%} with "
            f"worst other fold {worst_other:+.2%}",
        )

    if route_a or route_b:
        return Decision(
            rule=criteria.version,
            selected=candidate_id,
            decisive=True,
            reasons=tuple(reasons),
            evidence={
                "criteria": criteria.to_dict(),
                **evidence.to_dict(),
                "discontinuity_relative_mae_change": discontinuity_change,
                "other_fold_relative_mae_change": other_regressions,
                "route_a": route_a,
                "route_b": route_b,
            },
        )
    detail: list[str] = []
    if mae is not None:
        detail.append(mae.render())
    if pinball is not None:
        detail.append(pinball.render())
    detail.append(
        f"{criteria.discontinuity_season} MAE {discontinuity_change:+.2%}, "
        f"worst other fold {worst_other:+.2%}",
    )
    return Decision(
        rule=criteria.version,
        selected=baseline_id,
        decisive=False,
        reasons=(f"{baseline_id} retained: " + "; ".join(detail),),
        evidence={
            "criteria": criteria.to_dict(),
            **evidence.to_dict(),
            "discontinuity_relative_mae_change": discontinuity_change,
            "other_fold_relative_mae_change": other_regressions,
            "route_a": route_a,
            "route_b": route_b,
        },
    )


# ---------------------------------------------------------------------------------------
# 3. Candidate A versus Candidate B
# ---------------------------------------------------------------------------------------


@dataclass(frozen=True)
class CandidateComparison:
    """When the availability x performance candidate replaces the calibrated direct model.

    Candidate B is a hurdle model: two fitted components, a dependency parameter and a
    composition step, against Candidate A's one booster per quantile. That extra machinery
    is worth carrying only if it buys a genuinely better *distribution* and at least one
    other thing a draft board cares about. Anything short of that keeps Candidate A, which
    is what `AGENTS.md` section 8's baseline-first rule means in practice.
    """

    version: str = "phase4_candidate_v1"
    primary_probabilistic_metric: str = "mean_pinball"
    #: Candidate B must win probabilistic quality with an interval excluding zero, and then
    #: also take at least one of these secondary improvements.
    min_rank_gain: float = 0.005
    min_top_k_gain: float = 0.010
    #: Bounded deterioration, exactly as ``phase3_promotion_v1`` bounds it.
    positional_mae_tolerance: float = 0.03
    positional_rank_tolerance: float = 0.030
    coverage_band: tuple[float, float] = (0.60, 0.95)
    #: Candidate B's absolute P10-P90 coverage gap may exceed A's by at most this much.
    max_coverage_gap_increase: float = 0.02
    nominal_p10_p90: float = 0.80

    def to_dict(self) -> dict[str, Any]:
        return {
            "criteria_version": self.version,
            "primary_probabilistic_metric": self.primary_probabilistic_metric,
            "min_rank_gain": self.min_rank_gain,
            "min_top_k_gain": self.min_top_k_gain,
            "positional_mae_tolerance": self.positional_mae_tolerance,
            "positional_rank_tolerance": self.positional_rank_tolerance,
            "coverage_band": list(self.coverage_band),
            "max_coverage_gap_increase": self.max_coverage_gap_increase,
            "rules": [
                "mean pinball loss improves with a paired 95% interval excluding zero",
                "and at least one of: MAE improves with an interval excluding zero; macro "
                "Spearman improves by min_rank_gain; macro top-K recall improves by "
                "min_top_k_gain",
                "and no position exceeds the MAE, Spearman or coverage tolerances",
                "and the absolute P10-P90 coverage gap does not grow by more than "
                "max_coverage_gap_increase",
                "otherwise Candidate A is retained",
            ],
        }


CANDIDATE_COMPARISON = CandidateComparison()


def evaluate_candidate_choice(
    *,
    deltas: Mapping[str, PairedDelta],
    reference: CalibrationEvidence,
    candidate: CalibrationEvidence,
    positional_mae_regression: Mapping[str, float],
    positional_rank_regression: Mapping[str, float],
    criteria: CandidateComparison = CANDIDATE_COMPARISON,
    reference_id: str = "A",
    candidate_id: str = "B",
) -> Decision:
    """Decide whether Candidate B replaces Candidate A.

    ``deltas`` are candidate minus reference on the common development folds.
    ``positional_*_regression`` are per-position deteriorations, positive meaning worse.
    """
    reasons: list[str] = []
    blockers: list[str] = []

    pinball = deltas.get(criteria.primary_probabilistic_metric)
    if pinball is None:
        blockers.append(f"no paired delta for {criteria.primary_probabilistic_metric}")
    elif not pinball.improves:
        blockers.append(f"probabilistic quality: {pinball.render()} is not a decisive improvement")
    else:
        reasons.append(f"probabilistic quality: {pinball.render()}")

    mae = deltas.get("mae")
    spearman = deltas.get("spearman")
    top_k = deltas.get("top_k_recall")
    secondary: list[str] = []
    if mae is not None and mae.improves:
        secondary.append(f"MAE {mae.render()}")
    if spearman is not None and spearman.delta >= criteria.min_rank_gain:
        secondary.append(f"Spearman {spearman.delta:+.4f}")
    if top_k is not None and top_k.delta >= criteria.min_top_k_gain:
        secondary.append(f"top-K recall {top_k.delta:+.4f}")
    if secondary:
        reasons.append("secondary improvement: " + "; ".join(secondary))
    else:
        blockers.append(
            "no secondary improvement: neither MAE, ranking nor top-K retrieval improved "
            "by the declared margin",
        )

    low, high = criteria.coverage_band
    for position in sorted(set(positional_mae_regression) | set(positional_rank_regression)):
        mae_regression = positional_mae_regression.get(position, 0.0)
        rank_regression = positional_rank_regression.get(position, 0.0)
        if mae_regression > criteria.positional_mae_tolerance:
            blockers.append(f"{position}: MAE {mae_regression:+.1%} worse than Candidate A")
        if rank_regression > criteria.positional_rank_tolerance:
            blockers.append(f"{position}: Spearman {rank_regression:.3f} below Candidate A")
    for item in candidate.positional:
        if not low <= item.coverage_p10_p90 <= high:
            blockers.append(
                f"{item.position}: P10-P90 coverage {item.coverage_p10_p90:.3f} "
                f"outside [{low}, {high}]",
            )

    gap_reference = abs(reference.coverage_p10_p90 - criteria.nominal_p10_p90)
    gap_candidate = abs(candidate.coverage_p10_p90 - criteria.nominal_p10_p90)
    if gap_candidate - gap_reference > criteria.max_coverage_gap_increase:
        blockers.append(
            f"P10-P90 coverage gap grew {gap_candidate - gap_reference:+.4f}, beyond the "
            f"{criteria.max_coverage_gap_increase:.3f} tolerance",
        )

    selected = candidate_id if not blockers else reference_id
    return Decision(
        rule=criteria.version,
        selected=selected,
        decisive=not blockers,
        reasons=tuple(reasons),
        failures=(),
        evidence={
            "criteria": criteria.to_dict(),
            "deltas": {name: delta.to_dict() for name, delta in deltas.items()},
            "reference": reference.to_dict(),
            "candidate": candidate.to_dict(),
            "positional_mae_regression": dict(positional_mae_regression),
            "positional_rank_regression": dict(positional_rank_regression),
            "coverage_gap_reference": gap_reference,
            "coverage_gap_candidate": gap_candidate,
            "blockers": blockers,
        },
    )


# ---------------------------------------------------------------------------------------
# 4. Monte Carlo convergence
# ---------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ConvergenceEvidence:
    """One measured comparison between two Monte Carlo runs of the same scenario."""

    scenario: str
    comparison: str
    draws: int
    mean_abs_expected_vorp: float
    p99_abs_expected_vorp: float
    mean_abs_p50_vorp: float
    p99_abs_p50_vorp: float
    mean_abs_outer_vorp: float
    p99_abs_outer_vorp: float
    max_abs_replacement: float
    fair_rank_spearman: float
    top_50_overlap: float
    mean_abs_rank_change_top_150: float
    tier_adjusted_rand: float
    tier_count_difference: int

    def to_dict(self) -> dict[str, Any]:
        return {key: getattr(self, key) for key in self.__slots__}


@dataclass(frozen=True)
class ConvergenceTolerance:
    """How close two Monte Carlo runs must be before the smaller one is enough.

    The tolerances are stated on quantities a reader of the draft board actually sees -
    value in fantasy points, fair rank, tier membership - rather than on the simulation's
    internals. Dispersion is summarised at the 99th percentile rather than the maximum,
    because a single extreme-variance player would otherwise choose the draw count for the
    whole board; the maximum is still reported, it just does not decide.

    Two comparisons must both pass at a candidate draw count: against the largest count in
    the ladder at the same seed, and between two seeds at the candidate count. The first
    measures bias against the best available reference, the second measures the Monte Carlo
    error directly.
    """

    version: str = "phase4_convergence_v1"
    #: Ordered smallest to largest. The last entry is the reference.
    draw_ladder: tuple[int, ...] = (1000, 2500, 5000, 10000)
    mean_abs_expected_vorp: float = 0.25
    p99_abs_expected_vorp: float = 1.50
    mean_abs_p50_vorp: float = 0.35
    p99_abs_p50_vorp: float = 3.00
    mean_abs_outer_vorp: float = 0.60
    p99_abs_outer_vorp: float = 5.00
    max_abs_replacement: float = 0.50
    min_fair_rank_spearman: float = 0.9990
    min_top_50_overlap: float = 0.96
    max_mean_abs_rank_change_top_150: float = 1.5
    min_tier_adjusted_rand: float = 0.90
    max_tier_count_difference: int = 1

    @property
    def reference_draws(self) -> int:
        return self.draw_ladder[-1]

    def to_dict(self) -> dict[str, Any]:
        return {
            "criteria_version": self.version,
            "draw_ladder": list(self.draw_ladder),
            "reference_draws": self.reference_draws,
            "mean_abs_expected_vorp": self.mean_abs_expected_vorp,
            "p99_abs_expected_vorp": self.p99_abs_expected_vorp,
            "mean_abs_p50_vorp": self.mean_abs_p50_vorp,
            "p99_abs_p50_vorp": self.p99_abs_p50_vorp,
            "mean_abs_outer_vorp": self.mean_abs_outer_vorp,
            "p99_abs_outer_vorp": self.p99_abs_outer_vorp,
            "max_abs_replacement": self.max_abs_replacement,
            "min_fair_rank_spearman": self.min_fair_rank_spearman,
            "min_top_50_overlap": self.min_top_50_overlap,
            "max_mean_abs_rank_change_top_150": self.max_mean_abs_rank_change_top_150,
            "min_tier_adjusted_rand": self.min_tier_adjusted_rand,
            "max_tier_count_difference": self.max_tier_count_difference,
            "rules": [
                "a draw count qualifies only if every tolerance holds in every evaluated "
                "scenario, both against the reference draw count and between two seeds",
                "the smallest qualifying draw count in the ladder is selected",
            ],
        }

    def violations(self, evidence: ConvergenceEvidence) -> list[str]:
        """Every tolerance this comparison breaks, named."""
        breaches: list[str] = []
        checks: tuple[tuple[str, float, float, bool], ...] = (
            (
                "mean |Δ expected VORP|",
                evidence.mean_abs_expected_vorp,
                self.mean_abs_expected_vorp,
                True,
            ),
            (
                "p99 |Δ expected VORP|",
                evidence.p99_abs_expected_vorp,
                self.p99_abs_expected_vorp,
                True,
            ),
            ("mean |Δ P50 VORP|", evidence.mean_abs_p50_vorp, self.mean_abs_p50_vorp, True),
            ("p99 |Δ P50 VORP|", evidence.p99_abs_p50_vorp, self.p99_abs_p50_vorp, True),
            ("mean |Δ outer VORP|", evidence.mean_abs_outer_vorp, self.mean_abs_outer_vorp, True),
            ("p99 |Δ outer VORP|", evidence.p99_abs_outer_vorp, self.p99_abs_outer_vorp, True),
            ("max |Δ replacement|", evidence.max_abs_replacement, self.max_abs_replacement, True),
            (
                "mean |Δ rank| top 150",
                evidence.mean_abs_rank_change_top_150,
                self.max_mean_abs_rank_change_top_150,
                True,
            ),
            ("fair-rank Spearman", evidence.fair_rank_spearman, self.min_fair_rank_spearman, False),
            ("top-50 overlap", evidence.top_50_overlap, self.min_top_50_overlap, False),
            ("tier ARI", evidence.tier_adjusted_rand, self.min_tier_adjusted_rand, False),
        )
        for label, observed, bound, upper in checks:
            if observed != observed:  # NaN: the comparison could not be measured
                breaches.append(f"{label} could not be measured")
            elif upper and observed > bound:
                breaches.append(f"{label} {observed:.4f} exceeds {bound:.4f}")
            elif not upper and observed < bound:
                breaches.append(f"{label} {observed:.4f} below {bound:.4f}")
        if abs(evidence.tier_count_difference) > self.max_tier_count_difference:
            breaches.append(
                f"tier count differs by {evidence.tier_count_difference}, beyond "
                f"{self.max_tier_count_difference}",
            )
        return [f"{evidence.scenario}/{evidence.comparison}: {item}" for item in breaches]


CONVERGENCE_TOLERANCE = ConvergenceTolerance()


def evaluate_convergence(
    evidence: Sequence[ConvergenceEvidence],
    *,
    criteria: ConvergenceTolerance = CONVERGENCE_TOLERANCE,
) -> Decision:
    """Pick the smallest draw count in the ladder that satisfies every tolerance."""
    by_draws: dict[int, list[str]] = {draws: [] for draws in criteria.draw_ladder}
    measured: dict[int, int] = dict.fromkeys(criteria.draw_ladder, 0)
    for item in evidence:
        if item.draws not in by_draws:
            continue
        measured[item.draws] += 1
        by_draws[item.draws].extend(criteria.violations(item))

    qualifying = [
        draws for draws in criteria.draw_ladder if measured[draws] > 0 and not by_draws[draws]
    ]
    if qualifying:
        chosen = qualifying[0]
        return Decision(
            rule=criteria.version,
            selected=str(chosen),
            decisive=True,
            reasons=(
                f"{chosen} draws satisfies every tolerance across "
                f"{measured[chosen]} comparison(s); it is the smallest count in the ladder "
                "that does",
            ),
            evidence={
                "criteria": criteria.to_dict(),
                "violations_by_draws": {str(k): v for k, v in by_draws.items()},
                "comparisons_by_draws": {str(k): v for k, v in measured.items()},
                "measurements": [item.to_dict() for item in evidence],
            },
        )
    reference = criteria.reference_draws
    return Decision(
        rule=criteria.version,
        selected=str(reference),
        decisive=False,
        reasons=(
            f"no draw count satisfied every tolerance; the largest declared count "
            f"({reference}) is used and the breaches are recorded",
        ),
        failures=tuple(by_draws.get(reference, ())),
        evidence={
            "criteria": criteria.to_dict(),
            "violations_by_draws": {str(k): v for k, v in by_draws.items()},
            "comparisons_by_draws": {str(k): v for k, v in measured.items()},
            "measurements": [item.to_dict() for item in evidence],
        },
    )


# ---------------------------------------------------------------------------------------
# 5. Expected versus median simulated VORP
# ---------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RankingEvidence:
    """How one ranking statistic ordered the board against realized VORP."""

    statistic: str
    macro_spearman: float
    macro_kendall: float
    macro_top_k_recall: float
    macro_top_k_precision: float
    top_k_recall_by_position: Mapping[str, float]
    seed_rank_stability: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "statistic": self.statistic,
            "macro_spearman": self.macro_spearman,
            "macro_kendall": self.macro_kendall,
            "macro_top_k_recall": self.macro_top_k_recall,
            "macro_top_k_precision": self.macro_top_k_precision,
            "top_k_recall_by_position": dict(self.top_k_recall_by_position),
            "seed_rank_stability": self.seed_rank_stability,
        }


@dataclass(frozen=True)
class RankingSelection:
    """When expected simulated VORP replaces median simulated VORP as the fair rank.

    `docs/MODELING.md` section 13 makes median the preferred initial default for robustness.
    Phase 3 measured the cost of that robustness - Q1's P50 point ordering retrieved less of
    the actual top-K than a linear model did - which is why the question is settled with a
    measurement here rather than a preference. The top of the board is where a draft sheet
    earns its keep, so top-K retrieval is the metric allowed to move the decision, subject
    to global ranking not deteriorating and no position collapsing.
    """

    version: str = "phase4_ranking_v1"
    default_statistic: str = "median_vorp"
    challenger_statistic: str = "expected_vorp"
    min_top_k_gain: float = 0.010
    max_rank_regression: float = 0.005
    max_positional_top_k_regression: float = 0.020

    def to_dict(self) -> dict[str, Any]:
        return {
            "criteria_version": self.version,
            "default_statistic": self.default_statistic,
            "challenger_statistic": self.challenger_statistic,
            "min_top_k_gain": self.min_top_k_gain,
            "max_rank_regression": self.max_rank_regression,
            "max_positional_top_k_regression": self.max_positional_top_k_regression,
            "rules": [
                "expected VORP is selected only if macro top-K recall improves by at least "
                "min_top_k_gain",
                "and macro Spearman and Kendall each fall by no more than max_rank_regression",
                "and no position's top-K recall falls by more than max_positional_top_k_regression",
                "otherwise median VORP stands, as the conservative default in "
                "docs/MODELING.md section 13",
            ],
        }


RANKING_SELECTION = RankingSelection()


def evaluate_ranking_choice(
    median: RankingEvidence,
    expected: RankingEvidence,
    *,
    criteria: RankingSelection = RANKING_SELECTION,
) -> Decision:
    """Choose the production fair-ranking statistic."""
    blockers: list[str] = []
    reasons: list[str] = []

    top_k_gain = expected.macro_top_k_recall - median.macro_top_k_recall
    if top_k_gain < criteria.min_top_k_gain:
        blockers.append(
            f"top-K recall gain {top_k_gain:+.4f} below the {criteria.min_top_k_gain:.3f} required",
        )
    else:
        reasons.append(f"top-K recall {top_k_gain:+.4f}")

    spearman_regression = median.macro_spearman - expected.macro_spearman
    kendall_regression = median.macro_kendall - expected.macro_kendall
    if spearman_regression > criteria.max_rank_regression:
        blockers.append(
            f"macro Spearman falls {spearman_regression:.4f}, beyond "
            f"{criteria.max_rank_regression:.3f}",
        )
    if kendall_regression > criteria.max_rank_regression:
        blockers.append(
            f"macro Kendall falls {kendall_regression:.4f}, beyond "
            f"{criteria.max_rank_regression:.3f}",
        )

    for position in sorted(median.top_k_recall_by_position):
        regression = median.top_k_recall_by_position[
            position
        ] - expected.top_k_recall_by_position.get(
            position,
            float("nan"),
        )
        if regression == regression and regression > criteria.max_positional_top_k_regression:
            blockers.append(
                f"{position}: top-K recall falls {regression:.4f}, beyond "
                f"{criteria.max_positional_top_k_regression:.3f}",
            )

    selected = criteria.challenger_statistic if not blockers else criteria.default_statistic
    if blockers:
        reasons.append(f"{criteria.default_statistic} stands: " + "; ".join(blockers))
    return Decision(
        rule=criteria.version,
        selected=selected,
        decisive=not blockers,
        reasons=tuple(reasons),
        evidence={
            "criteria": criteria.to_dict(),
            "median": median.to_dict(),
            "expected": expected.to_dict(),
            "top_k_gain": top_k_gain,
            "spearman_regression": spearman_regression,
            "kendall_regression": kendall_regression,
            "blockers": blockers,
        },
    )


# ---------------------------------------------------------------------------------------
# 6. Tier penalty selection and the tier stability gate
# ---------------------------------------------------------------------------------------

#: How deep the published tier board goes, per preset. The deepest launch preset drafts
#: 14 teams x 13 roster slots = 182 players, so 300 covers every pick with headroom while
#: keeping segmentation on the part of the board a drafter actually reads.
TIER_BOARD_DEPTH = 300

#: The fixed candidate penalty grid for the change-point segmentation. Six values spanning
#: roughly an order of magnitude, declared before any of them was run. There is no search
#: outside this grid, and no "one more value" after seeing the diagnostics.
TIER_PENALTY_GRID: tuple[float, ...] = (1.0, 2.0, 3.0, 5.0, 8.0, 12.0)


@dataclass(frozen=True, slots=True)
class TierCandidateEvidence:
    """Diagnostics measured for one penalty on the development scenarios."""

    penalty: float
    mean_tier_count: float
    singleton_rate: float
    largest_tier_share: float
    mean_boundary_effect_size: float
    median_within_tier_effect_size: float
    bootstrap_adjusted_rand: float
    boundary_agreement: float

    def to_dict(self) -> dict[str, Any]:
        return {key: getattr(self, key) for key in self.__slots__}


@dataclass(frozen=True)
class TierSelection:
    """Which penalty is promoted, judged on stability and utility rather than looks.

    Admissibility comes first and is scale-free wherever it can be: a board must have enough
    tiers to be a tiering and few enough to be readable, must not dissolve into singletons,
    must not hide most of the board in one tier, and its boundaries must separate players
    more than an average adjacent pair inside a tier does. Only among admissible penalties
    does stability choose, and ties resolve towards the larger penalty - fewer, sturdier
    tiers - because that is the simpler board.
    """

    version: str = "phase4_tier_v1"
    algorithm: str = "ruptures.Pelt(model='rbf')"
    board_depth: int = TIER_BOARD_DEPTH
    penalties: tuple[float, ...] = TIER_PENALTY_GRID
    min_mean_tier_count: float = 6.0
    max_mean_tier_count: float = 24.0
    max_singleton_rate: float = 0.20
    max_largest_tier_share: float = 0.25
    #: Boundaries must separate more than a typical adjacent pair inside a tier.
    min_boundary_effect_ratio: float = 1.0
    #: Ties on stability inside this band resolve on separation, then on the larger penalty.
    stability_tie_band: float = 0.010

    def to_dict(self) -> dict[str, Any]:
        return {
            "criteria_version": self.version,
            "algorithm": self.algorithm,
            "board_depth": self.board_depth,
            "penalties": list(self.penalties),
            "min_mean_tier_count": self.min_mean_tier_count,
            "max_mean_tier_count": self.max_mean_tier_count,
            "max_singleton_rate": self.max_singleton_rate,
            "max_largest_tier_share": self.max_largest_tier_share,
            "min_boundary_effect_ratio": self.min_boundary_effect_ratio,
            "stability_tie_band": self.stability_tie_band,
            "rules": [
                "admissible: mean tier count inside the declared band",
                "admissible: singleton rate at or below max_singleton_rate",
                "admissible: no tier holds more than max_largest_tier_share of the board",
                "admissible: mean boundary effect size exceeds the median within-tier "
                "adjacent-pair effect size by at least min_boundary_effect_ratio",
                "among admissible penalties, the highest bootstrap adjusted Rand index wins",
                "ties inside stability_tie_band resolve on boundary separation, then on the "
                "larger penalty",
            ],
        }

    def inadmissibility(self, evidence: TierCandidateEvidence) -> list[str]:
        reasons: list[str] = []
        if evidence.mean_tier_count < self.min_mean_tier_count:
            reasons.append(
                f"mean tier count {evidence.mean_tier_count:.2f} below {self.min_mean_tier_count}",
            )
        if evidence.mean_tier_count > self.max_mean_tier_count:
            reasons.append(
                f"mean tier count {evidence.mean_tier_count:.2f} above {self.max_mean_tier_count}",
            )
        if evidence.singleton_rate > self.max_singleton_rate:
            reasons.append(
                f"singleton rate {evidence.singleton_rate:.3f} above {self.max_singleton_rate}",
            )
        if evidence.largest_tier_share > self.max_largest_tier_share:
            reasons.append(
                f"largest tier holds {evidence.largest_tier_share:.3f} of the board, above "
                f"{self.max_largest_tier_share}",
            )
        separation = evidence.median_within_tier_effect_size
        if separation > 0.0:
            ratio = evidence.mean_boundary_effect_size / separation
            if ratio < self.min_boundary_effect_ratio:
                reasons.append(
                    f"boundary effect size is only {ratio:.2f}x the within-tier effect size",
                )
        return reasons


TIER_SELECTION = TierSelection()


def select_tier_penalty(
    evidence: Sequence[TierCandidateEvidence],
    *,
    criteria: TierSelection = TIER_SELECTION,
) -> Decision:
    """Choose the production tier penalty from the frozen grid."""
    inadmissible: dict[float, list[str]] = {}
    admissible: list[TierCandidateEvidence] = []
    for item in evidence:
        reasons = criteria.inadmissibility(item)
        if reasons:
            inadmissible[item.penalty] = reasons
        else:
            admissible.append(item)

    if not admissible:
        return Decision(
            rule=criteria.version,
            selected="none",
            decisive=False,
            failures=tuple(
                f"penalty {penalty}: {'; '.join(reasons)}"
                for penalty, reasons in sorted(inadmissible.items())
            ),
            evidence={
                "criteria": criteria.to_dict(),
                "candidates": [item.to_dict() for item in evidence],
                "inadmissible": {str(k): v for k, v in inadmissible.items()},
            },
        )

    best = max(item.bootstrap_adjusted_rand for item in admissible)
    tied = [
        item
        for item in admissible
        if best - item.bootstrap_adjusted_rand <= criteria.stability_tie_band
    ]
    winner = max(tied, key=lambda item: (item.mean_boundary_effect_size, item.penalty))
    return Decision(
        rule=criteria.version,
        selected=f"{winner.penalty}",
        decisive=True,
        reasons=(
            f"penalty {winner.penalty} is admissible with bootstrap ARI "
            f"{winner.bootstrap_adjusted_rand:.3f}, mean tier count "
            f"{winner.mean_tier_count:.2f}, singleton rate {winner.singleton_rate:.3f} and "
            f"boundary effect size {winner.mean_boundary_effect_size:.3f}",
        ),
        evidence={
            "criteria": criteria.to_dict(),
            "candidates": [item.to_dict() for item in evidence],
            "admissible": [item.penalty for item in admissible],
            "inadmissible": {str(k): v for k, v in inadmissible.items()},
            "tied_within_band": [item.penalty for item in tied],
            "selected": winner.to_dict(),
        },
    )


@dataclass(frozen=True, slots=True)
class TierStabilityEvidence:
    """Measured stability of the promoted segmentation."""

    bootstrap_adjusted_rand: float
    boundary_agreement: float
    singleton_rate: float
    tier_count_cv: float
    monotonic_pair_share: float
    cross_preset_adjusted_rand: float

    def to_dict(self) -> dict[str, Any]:
        return {key: getattr(self, key) for key in self.__slots__}


@dataclass(frozen=True)
class TierStabilityGate:
    """The bar the promoted segmentation must clear before it reaches a draft sheet.

    A tier that moves when the data is resampled is a drawing, not a finding. The thresholds
    are set where standard practice puts "substantial agreement" for a partition-similarity
    index, and the monotonicity clause allows some noise deep in the board while refusing a
    board whose tiers do not generally order realized value.

    If PELT fails this gate, the response is the documented dynamic-programming alternative
    in `docs/MODELING.md` section 14.3, not a wider penalty search.
    """

    version: str = "phase4_tier_stability_v1"
    min_bootstrap_adjusted_rand: float = 0.60
    min_boundary_agreement: float = 0.50
    max_singleton_rate: float = 0.20
    max_tier_count_cv: float = 0.25
    min_monotonic_pair_share: float = 0.80
    min_cross_preset_adjusted_rand: float = 0.50

    def to_dict(self) -> dict[str, Any]:
        return {
            "criteria_version": self.version,
            "min_bootstrap_adjusted_rand": self.min_bootstrap_adjusted_rand,
            "min_boundary_agreement": self.min_boundary_agreement,
            "max_singleton_rate": self.max_singleton_rate,
            "max_tier_count_cv": self.max_tier_count_cv,
            "min_monotonic_pair_share": self.min_monotonic_pair_share,
            "min_cross_preset_adjusted_rand": self.min_cross_preset_adjusted_rand,
            "rules": [
                "bootstrap membership similarity at or above min_bootstrap_adjusted_rand",
                "at least min_boundary_agreement of promoted boundaries recovered by a "
                "majority of bootstrap replicates",
                "singleton rate at or below max_singleton_rate",
                "tier-count coefficient of variation at or below max_tier_count_cv",
                "realized mean VORP non-increasing across at least min_monotonic_pair_share "
                "of adjacent tier pairs",
                "membership similarity between scoring/league presets at or above "
                "min_cross_preset_adjusted_rand",
            ],
        }


TIER_STABILITY_GATE = TierStabilityGate()


def evaluate_tier_stability(
    evidence: TierStabilityEvidence,
    *,
    criteria: TierStabilityGate = TIER_STABILITY_GATE,
) -> Decision:
    """Apply the tier stability gate to the promoted segmentation."""
    failures: list[str] = []
    reasons: list[str] = []
    checks: tuple[tuple[str, float, float, bool], ...] = (
        (
            "bootstrap ARI",
            evidence.bootstrap_adjusted_rand,
            criteria.min_bootstrap_adjusted_rand,
            False,
        ),
        ("boundary agreement", evidence.boundary_agreement, criteria.min_boundary_agreement, False),
        ("singleton rate", evidence.singleton_rate, criteria.max_singleton_rate, True),
        ("tier-count CV", evidence.tier_count_cv, criteria.max_tier_count_cv, True),
        (
            "monotonic tier pairs",
            evidence.monotonic_pair_share,
            criteria.min_monotonic_pair_share,
            False,
        ),
        (
            "cross-preset ARI",
            evidence.cross_preset_adjusted_rand,
            criteria.min_cross_preset_adjusted_rand,
            False,
        ),
    )
    for label, observed, bound, upper in checks:
        if observed != observed:
            failures.append(f"{label} could not be measured")
        elif upper and observed > bound:
            failures.append(f"{label} {observed:.4f} above {bound:.4f}")
        elif not upper and observed < bound:
            failures.append(f"{label} {observed:.4f} below {bound:.4f}")
        else:
            reasons.append(f"{label} {observed:.4f}")
    return Decision(
        rule=criteria.version,
        selected="pass" if not failures else "fail",
        decisive=not failures,
        reasons=tuple(reasons),
        failures=tuple(failures),
        evidence={"criteria": criteria.to_dict(), "measured": evidence.to_dict()},
    )


# ---------------------------------------------------------------------------------------
# 7. The final-holdout acceptance gate
# ---------------------------------------------------------------------------------------


@dataclass(frozen=True)
class FinalHoldoutGate:
    """What the frozen production model must do on 2025 to be released.

    Same methodology as ``phase3_promotion_v1``: the primary comparison is against B0 on the
    **full 2025 universe**, macro over position x scoring, with paired uncertainty on the two
    primary metrics, a bounded ranking regression and a positional collapse clause. Two
    things are added because Phase 4 ships a distribution rather than an experiment: the
    production quantiles must not cross at all, and every prediction must be finite.

    The predeclared ADR-025 slices are reported beside the primary result. They are
    diagnostics; not one of them can replace or override it, and none of them is in the gate.
    """

    version: str = "phase4_final_holdout_v1"
    primary_slice: str = "full_universe"
    primary_baseline: str = "B0"
    max_rank_regression: float = 0.010
    positional_mae_tolerance: float = 0.03
    positional_rank_tolerance: float = 0.030
    coverage_band: tuple[float, float] = (0.60, 0.95)
    max_post_crossing_rate: float = 0.0
    require_interval_excludes_zero: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "criteria_version": self.version,
            "primary_slice": self.primary_slice,
            "primary_baseline": self.primary_baseline,
            "max_rank_regression": self.max_rank_regression,
            "positional_mae_tolerance": self.positional_mae_tolerance,
            "positional_rank_tolerance": self.positional_rank_tolerance,
            "coverage_band": list(self.coverage_band),
            "max_post_crossing_rate": self.max_post_crossing_rate,
            "require_interval_excludes_zero": self.require_interval_excludes_zero,
            "rules": [
                "full-universe macro MAE improves on B0 with a paired 95% interval excluding zero",
                "full-universe macro mean pinball loss improves on B0 with a paired 95% "
                "interval excluding zero",
                "full-universe macro Spearman falls by no more than max_rank_regression",
                "no position exceeds the MAE, Spearman or coverage tolerances",
                "production quantiles do not cross and every prediction is finite",
                "predeclared ADR-025 slices are reported as diagnostics and are not part of "
                "the gate",
            ],
        }


FINAL_HOLDOUT_GATE = FinalHoldoutGate()


def evaluate_final_holdout(
    *,
    deltas: Mapping[str, PairedDelta],
    positional_mae_regression: Mapping[str, float],
    positional_rank_regression: Mapping[str, float],
    positional_coverage: Mapping[str, float],
    post_crossing_rate: float,
    all_finite: bool,
    criteria: FinalHoldoutGate = FINAL_HOLDOUT_GATE,
) -> Decision:
    """Apply the frozen 2025 acceptance rule to measured full-universe evidence."""
    reasons: list[str] = []
    failures: list[str] = []

    for metric, label in (("mae", "point accuracy"), ("mean_pinball", "probabilistic quality")):
        delta = deltas.get(metric)
        if delta is None:
            failures.append(f"{label}: no paired delta for {metric} was computed")
        elif delta.delta >= 0.0:
            failures.append(f"{label}: {metric} did not improve (delta {delta.delta:+.4f})")
        elif criteria.require_interval_excludes_zero and not delta.significant:
            failures.append(
                f"{label}: {metric} improved by {delta.delta:+.4f} but the 95% interval "
                f"[{delta.ci_low:+.4f}, {delta.ci_high:+.4f}] includes zero",
            )
        else:
            reasons.append(f"{label}: {delta.render()}")

    rank = deltas.get("spearman")
    if rank is None:
        failures.append("ranking: no paired delta for spearman was computed")
    elif -rank.delta > criteria.max_rank_regression:
        failures.append(
            f"ranking: spearman fell {-rank.delta:.4f}, beyond the "
            f"{criteria.max_rank_regression:.3f} tolerance",
        )
    else:
        reasons.append(f"ranking: spearman {rank.delta:+.4f} within tolerance")

    collapse: list[str] = []
    low, high = criteria.coverage_band
    for position in sorted(
        set(positional_mae_regression) | set(positional_rank_regression) | set(positional_coverage),
    ):
        mae_regression = positional_mae_regression.get(position, 0.0)
        rank_regression = positional_rank_regression.get(position, 0.0)
        coverage = positional_coverage.get(position, float("nan"))
        if mae_regression > criteria.positional_mae_tolerance:
            collapse.append(f"{position}: MAE {mae_regression:+.1%} worse than baseline")
        if rank_regression > criteria.positional_rank_tolerance:
            collapse.append(f"{position}: Spearman {rank_regression:.3f} below baseline")
        if coverage != coverage or not low <= coverage <= high:
            collapse.append(f"{position}: P10-P90 coverage {coverage:.3f} outside [{low}, {high}]")
    if collapse:
        failures.append("positional collapse: " + "; ".join(collapse))
    elif positional_coverage:
        reasons.append(f"no positional collapse across {len(positional_coverage)} position(s)")

    if post_crossing_rate > criteria.max_post_crossing_rate:
        failures.append(
            f"distribution validity: post-processing crossing rate {post_crossing_rate:.4f} "
            f"exceeds {criteria.max_post_crossing_rate:.4f}",
        )
    else:
        reasons.append("distribution validity: no production quantile crossings")
    if not all_finite:
        failures.append("distribution validity: a non-finite prediction was produced")

    return Decision(
        rule=criteria.version,
        selected="pass" if not failures else "fail",
        decisive=not failures,
        reasons=tuple(reasons),
        failures=tuple(failures),
        evidence={
            "criteria": criteria.to_dict(),
            "deltas": {name: delta.to_dict() for name, delta in deltas.items()},
            "positional_mae_regression": dict(positional_mae_regression),
            "positional_rank_regression": dict(positional_rank_regression),
            "positional_coverage": dict(positional_coverage),
            "post_crossing_rate": post_crossing_rate,
            "all_finite": all_finite,
            "positional_collapse": collapse,
        },
    )


def all_rules() -> dict[str, Any]:
    """Every frozen Phase-4 rule, for the reports and the freeze checkpoint."""
    return {
        "rules_version": PHASE4_RULES_VERSION,
        "calibration": CALIBRATION_ACCEPTANCE.to_dict(),
        "horizon_sensitivity": HORIZON_SENSITIVITY.to_dict(),
        "candidate_comparison": CANDIDATE_COMPARISON.to_dict(),
        "monte_carlo_convergence": CONVERGENCE_TOLERANCE.to_dict(),
        "ranking_statistic": RANKING_SELECTION.to_dict(),
        "tier_selection": TIER_SELECTION.to_dict(),
        "tier_stability": TIER_STABILITY_GATE.to_dict(),
        "final_holdout": FINAL_HOLDOUT_GATE.to_dict(),
    }
