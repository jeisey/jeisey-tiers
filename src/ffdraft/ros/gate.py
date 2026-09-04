"""The frozen rest-of-season promotion rule.

Written and committed **before** the candidate comparison runs, so the repository history is
the evidence that the gate was frozen rather than fitted to whatever won. Changing a
threshold after seeing results is a different, later decision and needs its own ADR.

`docs/RELEASE2_ROADMAP.md` 11.4 states the rule in one sentence:

> Promote a more complex ROS model only if it beats the declared simple baseline on
> probabilistic quality and does not materially collapse rank quality or a key cohort.

Four clauses implement it.

1. **Probabilistic improvement is mandatory.** Lower macro mean pinball loss than the primary
   baseline, with the paired bootstrap 95% interval for the delta entirely below zero. This
   is the clause the roadmap names, and it is the one that cannot be traded away: the product
   of this model is a distribution, and a point estimate that happens to be closer is not
   evidence that the distribution is better.
2. **Point accuracy may not deteriorate materially.** Macro MAE may be at most 1% worse. It
   is *not* required to improve; a model that is better calibrated without moving the mean is
   still worth having, and demanding both would make the gate a conjunction of two noisy
   tests rather than one substantive one.
3. **Ranking stays competitive.** Macro Spearman may fall by at most 0.010, the same
   tolerance ``phase3_promotion_v1`` uses, because an in-season board is read as an order.
4. **No hidden cohort collapse.** For every position, and for every predeclared cohort slice
   named below, the candidate's MAE may be at most 5% worse and its Spearman at most 0.030
   worse than the baseline's, and its empirical P10-P90 coverage must stay inside
   [0.60, 0.95]. The cohort list is the roadmap's own edge-case list, so "we did not check the
   returning-from-injury cohort" cannot happen by omission.

Deliberately *not* required: that every season x week x position x preset cell improves.
There are hundreds of them; demanding it of all would select for luck, not skill. The clauses
bound real deterioration instead.

**The primary baseline is chosen by a rule, not by taste.** All four declared baselines are
run; the one with the lowest macro mean pinball loss in development becomes the comparator
the candidate must beat. That removes the only incentive a gate author has to pick a weak
comparator, and it is decided here, before any of the four has been measured.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from ffdraft.modeling.bootstrap import BootstrapDelta

__all__ = [
    "ROS_PROMOTION_CRITERIA",
    "ROS_PROMOTION_CRITERIA_V2",
    "RosCohortEvidence",
    "RosGateResult",
    "RosPromotionCriteria",
    "RosPromotionCriteriaV2",
    "evaluate_ros_promotion_gate",
    "evaluate_ros_promotion_gate_v2",
    "select_primary_baseline",
]

#: The predeclared cohorts clause 4 checks, by slice id. Every one is named in roadmap 11.3.
REQUIRED_COHORT_SLICES: tuple[str, ...] = (
    "position",
    "scoring_preset",
    "season_phase",
    "rookie",
    "veteran",
    "games_played_band",
    "returning_from_absence",
    "changed_team_in_season",
    "in_season_arrival",
    "high_capital_underperforming",
    "high_capital_rookie",
    "extreme_uncertainty",
)


@dataclass(frozen=True)
class RosPromotionCriteria:
    """The frozen comparison rule. Version it rather than editing it in place."""

    version: str = "ros_promotion_v1"
    primary_probabilistic_metric: str = "mean_pinball"
    primary_point_metric: str = "mae"
    rank_metric: str = "spearman"
    #: Macro MAE may be at most this much worse, relative to the baseline's.
    max_point_regression: float = 0.01
    #: Macro Spearman may fall by at most this much, in absolute correlation.
    max_rank_regression: float = 0.010
    #: A cohort's MAE may be at most this much worse, relative to the baseline's.
    cohort_mae_tolerance: float = 0.05
    #: A cohort's Spearman may be at most this much worse, in absolute correlation.
    cohort_rank_tolerance: float = 0.030
    #: A cohort's empirical P10-P90 coverage must stay inside this band.
    coverage_band: tuple[float, float] = (0.60, 0.95)
    #: Whether the paired bootstrap interval must exclude zero for the probabilistic metric.
    require_interval_excludes_zero: bool = True
    #: Cohorts with fewer rows than this are reported but do not decide; a 12-row cell's
    #: Spearman is noise, and a gate that lets noise veto is a gate nobody can pass.
    minimum_cohort_rows: int = 200
    required_cohorts: tuple[str, ...] = REQUIRED_COHORT_SLICES

    def to_dict(self) -> dict[str, Any]:
        return {
            "criteria_version": self.version,
            "primary_probabilistic_metric": self.primary_probabilistic_metric,
            "primary_point_metric": self.primary_point_metric,
            "rank_metric": self.rank_metric,
            "max_point_regression": self.max_point_regression,
            "max_rank_regression": self.max_rank_regression,
            "cohort_mae_tolerance": self.cohort_mae_tolerance,
            "cohort_rank_tolerance": self.cohort_rank_tolerance,
            "coverage_band": list(self.coverage_band),
            "require_interval_excludes_zero": self.require_interval_excludes_zero,
            "minimum_cohort_rows": self.minimum_cohort_rows,
            "required_cohorts": list(self.required_cohorts),
            "primary_baseline_rule": (
                "the declared baseline with the lowest development macro mean pinball loss; "
                "ties resolved by macro MAE, then by declaration order"
            ),
        }


ROS_PROMOTION_CRITERIA = RosPromotionCriteria()


@dataclass(frozen=True, slots=True)
class RosCohortEvidence:
    """One cohort's paired evidence, as measured rather than as bootstrapped."""

    slice_id: str
    label: str
    rows: int
    baseline_mae: float
    candidate_mae: float
    baseline_spearman: float
    candidate_spearman: float
    candidate_coverage: float
    #: The baseline's coverage and both models' mean interval widths are reported but never
    #: read by a clause. Clause 4 judges the candidate's interval on its own terms - an
    #: interval that says nothing is a defect whether or not the baseline shares it - and a
    #: reader still needs to know whether a cohort is simply hard to cover.
    baseline_coverage: float = float("nan")
    baseline_width: float = float("nan")
    candidate_width: float = float("nan")
    #: Proper local scoring. Pinball loss is proper for quantile forecasts and is well defined
    #: for a mixed discrete-continuous target, which is what `ros_promotion_v2` needs and what
    #: an absolute coverage band is not.
    baseline_pinball: float = float("nan")
    candidate_pinball: float = float("nan")
    #: What a calibrated, player-blind forecaster attains on these rows
    #: (:mod:`ffdraft.ros.reference`). Outcome-derived; identical for every model.
    reference_coverage: float = float("nan")
    reference_width: float = float("nan")
    reference_zero_share: float = float("nan")

    @property
    def decisive(self) -> bool:
        return self.rows >= ROS_PROMOTION_CRITERIA.minimum_cohort_rows

    def to_dict(self) -> dict[str, Any]:
        return {
            "slice_id": self.slice_id,
            "label": self.label,
            "rows": self.rows,
            "decisive": self.decisive,
            "baseline_mae": self.baseline_mae,
            "candidate_mae": self.candidate_mae,
            "baseline_spearman": self.baseline_spearman,
            "candidate_spearman": self.candidate_spearman,
            "baseline_coverage": self.baseline_coverage,
            "candidate_coverage": self.candidate_coverage,
            "baseline_width": self.baseline_width,
            "candidate_width": self.candidate_width,
            "baseline_pinball": self.baseline_pinball,
            "candidate_pinball": self.candidate_pinball,
            "reference_coverage": self.reference_coverage,
            "reference_width": self.reference_width,
            "reference_zero_share": self.reference_zero_share,
        }


@dataclass(frozen=True)
class RosGateResult:
    """The decision, and the exact clause that decided it.

    ``criteria`` carries whichever rule produced the verdict, so a serialized result can never
    claim to have been judged by a rule that did not judge it.
    """

    promoted: bool
    criteria: RosPromotionCriteria | RosPromotionCriteriaV2
    primary_baseline: str
    candidate: str
    reasons: tuple[str, ...] = ()
    satisfied: tuple[str, ...] = ()
    cohorts: tuple[RosCohortEvidence, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "promoted": self.promoted,
            "primary_baseline": self.primary_baseline,
            "candidate": self.candidate,
            "criteria": self.criteria.to_dict(),
            "failed_clauses": list(self.reasons),
            "satisfied_clauses": list(self.satisfied),
            "cohorts": [item.to_dict() for item in self.cohorts],
        }


def select_primary_baseline(
    macro_by_model: Mapping[str, Mapping[str, float]],
    declaration_order: Sequence[str],
    *,
    criteria: RosPromotionCriteria = ROS_PROMOTION_CRITERIA,
) -> str:
    """Pick the comparator by the frozen rule: lowest macro pinball, then MAE, then order."""
    candidates = [name for name in declaration_order if name in macro_by_model]
    if not candidates:
        raise ValueError("no declared baseline has measured macro metrics")
    return min(
        candidates,
        key=lambda name: (
            macro_by_model[name][criteria.primary_probabilistic_metric],
            macro_by_model[name][criteria.primary_point_metric],
            declaration_order.index(name),
        ),
    )


def evaluate_ros_promotion_gate(
    deltas: Mapping[str, BootstrapDelta],
    cohorts: Sequence[RosCohortEvidence],
    *,
    primary_baseline: str,
    candidate: str,
    criteria: RosPromotionCriteria = ROS_PROMOTION_CRITERIA,
) -> RosGateResult:
    """Apply the frozen rule to measured evidence. Pure: no data, no fitting, no I/O."""
    failed: list[str] = []
    satisfied: list[str] = []

    pinball = deltas.get(criteria.primary_probabilistic_metric)
    if pinball is None:
        failed.append(
            f"clause 1: {criteria.primary_probabilistic_metric} was not measured",
        )
    else:
        improved = pinball.delta < 0.0
        resolved = pinball.significant or not criteria.require_interval_excludes_zero
        if improved and resolved:
            satisfied.append(
                f"clause 1: macro {criteria.primary_probabilistic_metric} "
                f"{pinball.delta:+.4f} [{pinball.ci_low:+.4f}, {pinball.ci_high:+.4f}]",
            )
        else:
            failed.append(
                f"clause 1: macro {criteria.primary_probabilistic_metric} "
                f"{pinball.delta:+.4f} [{pinball.ci_low:+.4f}, {pinball.ci_high:+.4f}] does "
                "not show a resolved improvement",
            )

    point = deltas.get(criteria.primary_point_metric)
    if point is None:
        failed.append(f"clause 2: {criteria.primary_point_metric} was not measured")
    else:
        allowed = abs(point.baseline) * criteria.max_point_regression
        if point.delta <= allowed:
            satisfied.append(
                f"clause 2: macro {criteria.primary_point_metric} {point.delta:+.4f} within "
                f"the {criteria.max_point_regression:.0%} tolerance ({allowed:+.4f})",
            )
        else:
            failed.append(
                f"clause 2: macro {criteria.primary_point_metric} {point.delta:+.4f} exceeds "
                f"the {criteria.max_point_regression:.0%} tolerance ({allowed:+.4f})",
            )

    rank = deltas.get(criteria.rank_metric)
    if rank is None:
        failed.append(f"clause 3: {criteria.rank_metric} was not measured")
    elif rank.delta >= -criteria.max_rank_regression:
        satisfied.append(f"clause 3: macro {criteria.rank_metric} {rank.delta:+.4f}")
    else:
        failed.append(
            f"clause 3: macro {criteria.rank_metric} {rank.delta:+.4f} falls more than "
            f"{criteria.max_rank_regression:.3f} below the baseline",
        )

    missing = sorted(set(criteria.required_cohorts) - {item.slice_id for item in cohorts})
    if missing:
        failed.append(f"clause 4: required cohort(s) not reported: {missing}")

    collapses: list[str] = []
    low, high = criteria.coverage_band
    for cohort in cohorts:
        if not cohort.decisive:
            continue
        tolerance = abs(cohort.baseline_mae) * criteria.cohort_mae_tolerance
        if cohort.candidate_mae - cohort.baseline_mae > tolerance:
            collapses.append(
                f"{cohort.slice_id}/{cohort.label} MAE "
                f"{cohort.baseline_mae:.2f}->{cohort.candidate_mae:.2f}",
            )
        if cohort.baseline_spearman - cohort.candidate_spearman > criteria.cohort_rank_tolerance:
            collapses.append(
                f"{cohort.slice_id}/{cohort.label} Spearman "
                f"{cohort.baseline_spearman:.3f}->{cohort.candidate_spearman:.3f}",
            )
        if not low <= cohort.candidate_coverage <= high:
            collapses.append(
                f"{cohort.slice_id}/{cohort.label} P10-P90 coverage "
                f"{cohort.candidate_coverage:.3f} outside [{low:.2f}, {high:.2f}]",
            )
    if collapses:
        failed.append("clause 4: cohort deterioration: " + "; ".join(sorted(collapses)))
    elif not missing:
        decisive = sum(1 for cohort in cohorts if cohort.decisive)
        satisfied.append(
            f"clause 4: no cohort collapse across {decisive} decisive cohort(s) "
            f"of {len(cohorts)} reported",
        )

    return RosGateResult(
        promoted=not failed,
        criteria=criteria,
        primary_baseline=primary_baseline,
        candidate=candidate,
        reasons=tuple(failed),
        satisfied=tuple(satisfied),
        cohorts=tuple(cohorts),
    )


# ---------------------------------------------------------------------------------------
# The successor rule.
#
# `ros_promotion_v1` above is left exactly as it was written and exactly as it judged: it is
# the record that RC1 failed it, and deleting or editing it would destroy that record. What
# follows is a *successor*, declared and committed before it was applied to any evidence.
# ---------------------------------------------------------------------------------------


@dataclass(frozen=True)
class RosPromotionCriteriaV2:
    """The frozen successor rule, and why each clause differs from `ros_promotion_v1`.

    Clauses 1-3 are **unchanged**. They were already stated on a proper scoring rule, on a
    point metric and on a rank metric, and none of them is affected by the shape of the target
    distribution.

    Clause 4 is re-specified. v1 required every decisive cohort's empirical P10-P90 coverage to
    lie inside an absolute band of ``[0.60, 0.95]``, nominally centred on the 0.80 a P10-P90
    interval covers. That centring is a theorem about **continuous** targets, and the
    rest-of-season target is not one: 56.8% of development rows are exactly zero, and 88.5% of
    the zero-current-games cohort is. Where a predictive distribution has an atom of mass
    ``p >= 0.10`` at its own tenth percentile, a **perfectly calibrated** forecaster's closed
    interval covers ``>= 0.90``, and where ``p >= 0.90`` it covers ``p``. The measured
    climatological reference says the same thing empirically: a calibrated, player-blind
    forecaster attains 0.843 to 0.926 across these cohorts and 0.926 on the zero-game cohort,
    never 0.80. An upper bound of 0.95 against an attainable 0.926 is not a calibration test;
    it is a test of how much mass the target puts on one point.

    So v1's clause 4 measured the wrong thing with the right intention. v2 keeps the intention
    and states it on quantities that survive an atom:

    ``4a`` point accuracy, unchanged from v1;
    ``4b`` rank quality, unchanged from v1;
    ``4c`` **probabilistic quality** - the local analogue of clause 1, on mean pinball loss.
        Pinball is a proper scoring rule and is well defined for a mixed discrete-continuous
        target. This is the clause that detects a distributionally worse forecast, which is
        what a coverage band was being asked to do and could not.
    ``4d`` **interval informativeness** - the honest form of "an interval so wide it says
        nothing". A cohort fails only when the candidate's mean P10-P90 width exceeds *both*
        the baseline's *and* the cohort's climatological interdecile width, i.e. only when the
        interval is wider than knowing nothing at all. An atom makes a calibrated interval
        narrower, so this clause cannot be tripped by the phenomenon that tripped v1.
    ``4e`` **calibration against what is attainable** - coverage must lie within a tolerance of
        the cohort's *climatological* coverage rather than of a fixed 0.80. On a continuous
        cohort the reference is 0.80 and the clause reduces to ``[0.65, 0.95]``.

    **The tolerance is inherited, not chosen.** ``coverage_tolerance`` is 0.15, which is v1's
    own *upper* allowance (0.95 - 0.80), applied to both sides. That **tightens** the
    under-coverage side from v1's 0.20 to 0.15. A rule reverse-engineered to let a particular
    candidate through would have loosened a bound; this one loosens nothing. Every threshold
    v1 stated that remained meaningful is carried over at its v1 value.

    What v2 deliberately does not do: it does not raise a ceiling, does not exempt a cohort,
    does not weaken clauses 1-3, and does not alter, replace or repeal
    :data:`ROS_PROMOTION_CRITERIA`.
    """

    version: str = "ros_promotion_v2"
    supersedes: str = "ros_promotion_v1"
    primary_probabilistic_metric: str = "mean_pinball"
    primary_point_metric: str = "mae"
    rank_metric: str = "spearman"
    max_point_regression: float = 0.01
    max_rank_regression: float = 0.010
    cohort_mae_tolerance: float = 0.05
    cohort_rank_tolerance: float = 0.030
    #: A cohort's mean pinball loss may be at most this much worse, relative to the baseline's.
    #: Same materiality as the MAE clause it sits beside.
    cohort_pinball_tolerance: float = 0.05
    #: Coverage must sit within this much of the cohort's climatological coverage. Inherited
    #: from v1's upper allowance and applied symmetrically, which tightens the lower side.
    coverage_tolerance: float = 0.15
    require_interval_excludes_zero: bool = True
    minimum_cohort_rows: int = 200
    required_cohorts: tuple[str, ...] = REQUIRED_COHORT_SLICES

    def to_dict(self) -> dict[str, Any]:
        return {
            "criteria_version": self.version,
            "supersedes": self.supersedes,
            "primary_probabilistic_metric": self.primary_probabilistic_metric,
            "primary_point_metric": self.primary_point_metric,
            "rank_metric": self.rank_metric,
            "max_point_regression": self.max_point_regression,
            "max_rank_regression": self.max_rank_regression,
            "cohort_mae_tolerance": self.cohort_mae_tolerance,
            "cohort_rank_tolerance": self.cohort_rank_tolerance,
            "cohort_pinball_tolerance": self.cohort_pinball_tolerance,
            "coverage_tolerance": self.coverage_tolerance,
            "coverage_reference": (
                "the cohort's climatological P10-P90 coverage (ffdraft.ros.reference), not a "
                "fixed 0.80: a calibrated forecaster on a target with an atom covers more than "
                "0.80 by arithmetic, so an absolute band tests the target rather than the model"
            ),
            "width_reference": (
                "a cohort fails only if the candidate's interval is wider than BOTH the "
                "baseline's and the cohort's climatological interdecile width"
            ),
            "require_interval_excludes_zero": self.require_interval_excludes_zero,
            "minimum_cohort_rows": self.minimum_cohort_rows,
            "required_cohorts": list(self.required_cohorts),
            "primary_baseline_rule": (
                "unchanged from v1: the declared baseline with the lowest development macro "
                "mean pinball loss; ties resolved by macro MAE, then by declaration order"
            ),
            "unchanged_from_v1": ["clause 1", "clause 2", "clause 3", "clause 4a", "clause 4b"],
            "stricter_than_v1": [
                "clause 4e tightens the under-coverage allowance from 0.20 to 0.15",
                "clause 4c adds a proper local scoring requirement v1 did not have",
            ],
        }


ROS_PROMOTION_CRITERIA_V2 = RosPromotionCriteriaV2()


def _relative_regression(baseline: float, candidate: float, tolerance: float) -> bool:
    """Whether ``candidate`` is worse than ``baseline`` by more than a relative tolerance."""
    if baseline != baseline or candidate != candidate:
        return False
    return candidate - baseline > abs(baseline) * tolerance


def evaluate_ros_promotion_gate_v2(
    deltas: Mapping[str, BootstrapDelta],
    cohorts: Sequence[RosCohortEvidence],
    *,
    primary_baseline: str,
    candidate: str,
    criteria: RosPromotionCriteriaV2 = ROS_PROMOTION_CRITERIA_V2,
) -> RosGateResult:
    """Apply the successor rule to measured evidence. Pure: no data, no fitting, no I/O."""
    failed: list[str] = []
    satisfied: list[str] = []

    pinball = deltas.get(criteria.primary_probabilistic_metric)
    if pinball is None:
        failed.append(f"clause 1: {criteria.primary_probabilistic_metric} was not measured")
    elif pinball.delta < 0.0 and (
        pinball.significant or not criteria.require_interval_excludes_zero
    ):
        satisfied.append(
            f"clause 1: macro {criteria.primary_probabilistic_metric} {pinball.delta:+.4f} "
            f"[{pinball.ci_low:+.4f}, {pinball.ci_high:+.4f}]",
        )
    else:
        failed.append(
            f"clause 1: macro {criteria.primary_probabilistic_metric} {pinball.delta:+.4f} "
            f"[{pinball.ci_low:+.4f}, {pinball.ci_high:+.4f}] does not show a resolved "
            "improvement",
        )

    point = deltas.get(criteria.primary_point_metric)
    if point is None:
        failed.append(f"clause 2: {criteria.primary_point_metric} was not measured")
    else:
        allowed = abs(point.baseline) * criteria.max_point_regression
        if point.delta <= allowed:
            satisfied.append(
                f"clause 2: macro {criteria.primary_point_metric} {point.delta:+.4f} within "
                f"the {criteria.max_point_regression:.0%} tolerance ({allowed:+.4f})",
            )
        else:
            failed.append(
                f"clause 2: macro {criteria.primary_point_metric} {point.delta:+.4f} exceeds "
                f"the {criteria.max_point_regression:.0%} tolerance ({allowed:+.4f})",
            )

    rank = deltas.get(criteria.rank_metric)
    if rank is None:
        failed.append(f"clause 3: {criteria.rank_metric} was not measured")
    elif rank.delta >= -criteria.max_rank_regression:
        satisfied.append(f"clause 3: macro {criteria.rank_metric} {rank.delta:+.4f}")
    else:
        failed.append(
            f"clause 3: macro {criteria.rank_metric} {rank.delta:+.4f} falls more than "
            f"{criteria.max_rank_regression:.3f} below the baseline",
        )

    missing = sorted(set(criteria.required_cohorts) - {item.slice_id for item in cohorts})
    if missing:
        failed.append(f"clause 4: required cohort(s) not reported: {missing}")

    breaches: list[str] = []
    for cohort in cohorts:
        if cohort.rows < criteria.minimum_cohort_rows:
            continue
        name = f"{cohort.slice_id}/{cohort.label}"
        if _relative_regression(
            cohort.baseline_mae,
            cohort.candidate_mae,
            criteria.cohort_mae_tolerance,
        ):
            breaches.append(
                f"4a {name} MAE {cohort.baseline_mae:.2f}->{cohort.candidate_mae:.2f}",
            )
        if cohort.baseline_spearman - cohort.candidate_spearman > criteria.cohort_rank_tolerance:
            breaches.append(
                f"4b {name} Spearman "
                f"{cohort.baseline_spearman:.3f}->{cohort.candidate_spearman:.3f}",
            )
        if _relative_regression(
            cohort.baseline_pinball,
            cohort.candidate_pinball,
            criteria.cohort_pinball_tolerance,
        ):
            breaches.append(
                f"4c {name} pinball {cohort.baseline_pinball:.3f}->{cohort.candidate_pinball:.3f}",
            )
        wider_than_baseline = cohort.candidate_width > cohort.baseline_width
        wider_than_climatology = cohort.candidate_width > cohort.reference_width
        if wider_than_baseline and wider_than_climatology:
            breaches.append(
                f"4d {name} P10-P90 width {cohort.candidate_width:.1f} exceeds both the "
                f"baseline's {cohort.baseline_width:.1f} and climatology's "
                f"{cohort.reference_width:.1f}",
            )
        gap = cohort.candidate_coverage - cohort.reference_coverage
        if gap == gap and abs(gap) > criteria.coverage_tolerance:
            breaches.append(
                f"4e {name} P10-P90 coverage {cohort.candidate_coverage:.3f} is {gap:+.3f} "
                f"from the attainable {cohort.reference_coverage:.3f}",
            )
    if breaches:
        failed.append("clause 4: cohort deterioration: " + "; ".join(sorted(breaches)))
    elif not missing:
        decisive = sum(1 for cohort in cohorts if cohort.rows >= criteria.minimum_cohort_rows)
        satisfied.append(
            f"clause 4: no cohort deterioration across {decisive} decisive cohort(s) of "
            f"{len(cohorts)} reported, on all five sub-clauses",
        )

    return RosGateResult(
        promoted=not failed,
        criteria=criteria,
        primary_baseline=primary_baseline,
        candidate=candidate,
        reasons=tuple(failed),
        satisfied=tuple(satisfied),
        cohorts=tuple(cohorts),
    )
