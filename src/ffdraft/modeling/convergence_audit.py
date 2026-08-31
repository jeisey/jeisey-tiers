"""The Phase-8 simulation-convergence audit.

**Why this exists.** ADR-034 records a real methodology-quality problem rather than a model
problem. ``phase4_convergence_v1`` asks one question — "is this draw count enough?" — of two
different properties at once:

* whether the Monte Carlo sampling has settled, which is a property of the simulation and
  which more draws fix; and
* whether tier boundaries land in the same places, which is a property of the *value curve*
  and which more draws do not fix, because a boundary is a discrete cut on a nearly
  continuous decline.

Its tier clause (``min_tier_adjusted_rand`` 0.90, ``max_tier_count_difference`` 1) is also
strictly harder than the tier gate it was meant to protect: ADR-035's own bar is a bootstrap
ARI of 0.60, and the promoted configuration measures 0.865 against it. So the composite rule
can report "not converged" on a configuration whose sampling is fine and whose tiers already
pass their own gate — and it did, across a ladder of draw counts including several the tier
rule was never going to select.

**What this module changes, and what it deliberately does not.**

It changes the *question*, not the answer. Every numeric tolerance below is copied verbatim
from ``ConvergenceTolerance``, which was frozen in Phase 4 before any of its evidence
existed. Nothing is loosened. Two things are removed and one is added:

* the two tier clauses come out, because tier-boundary stability is ADR-035's property and is
  measured by ``phase4_tier_stability_v1``; they are still *reported* here, as an observation,
  so removing them cannot quietly hide a result;
* the ladder search comes out. This rule **cannot select a draw count**. It judges the
  promoted production configuration and nothing else, which closes the door on the failure
  mode of reading a smaller count out of a re-specified rule after the fact;
* the scope is pinned to ``PRODUCTION_BUILD_CONFIG.draws``, so the audit cannot be satisfied
  by a configuration production never ran.

**A passing audit does not change production and a failing one does not either.** The draw
count stays at 10,000 whichever way this comes out: if the sampling is converged there is no
reason to move it, and if it is not, lowering it would be worse. The only thing that changes
is what the repository is entitled to say about the residual error.

The rule is frozen here and evaluated in ``ffdraft.cli audit-convergence``, in that order.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from ffdraft.modeling.rules import CONVERGENCE_TOLERANCE, ConvergenceEvidence

__all__ = [
    "SIMULATION_CONVERGENCE_AUDIT",
    "SimulationConvergenceAudit",
    "SimulationConvergenceResult",
    "evidence_from_report",
]

#: Bump when any bound below changes. A change after a decisive result is a new decision and
#: needs its own ADR; it is never an edit in place.
PHASE8_AUDIT_VERSION = "phase8_simulation_convergence_v1"


@dataclass(frozen=True, slots=True)
class SimulationConvergenceResult:
    """What the audit found, in the units the residual is actually measured in."""

    rule: str
    promoted_draws: int
    converged: bool
    comparisons: int
    #: One string per broken tolerance, naming the scenario, the statistic and both numbers.
    failures: tuple[str, ...]
    #: Every criterion, with the worst observed value across the evaluated comparisons.
    residuals: Mapping[str, Mapping[str, float]]
    #: Tier agreement at the promoted count. Reported, never decisive (ADR-035).
    tier_observations: Mapping[str, float]
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule": self.rule,
            "promoted_draws": self.promoted_draws,
            "converged": self.converged,
            "comparisons": self.comparisons,
            "failures": list(self.failures),
            "residuals": {key: dict(value) for key, value in self.residuals.items()},
            "tier_observations": dict(self.tier_observations),
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class SimulationConvergenceAudit:
    """Simulation convergence at the promoted draw count, and nothing else.

    Every bound is ``phase4_convergence_v1``'s own. The audit differs from it in scope and in
    what it is allowed to conclude, not in how strict it is.
    """

    version: str = PHASE8_AUDIT_VERSION
    #: Copied from the Phase-4 freeze so a reader can diff the two dataclasses and see that
    #: no number moved. `field(default_factory=...)` keeps the values in one place.
    mean_abs_expected_vorp: float = field(
        default_factory=lambda: CONVERGENCE_TOLERANCE.mean_abs_expected_vorp,
    )
    p99_abs_expected_vorp: float = field(
        default_factory=lambda: CONVERGENCE_TOLERANCE.p99_abs_expected_vorp,
    )
    mean_abs_p50_vorp: float = field(
        default_factory=lambda: CONVERGENCE_TOLERANCE.mean_abs_p50_vorp,
    )
    p99_abs_p50_vorp: float = field(
        default_factory=lambda: CONVERGENCE_TOLERANCE.p99_abs_p50_vorp,
    )
    mean_abs_outer_vorp: float = field(
        default_factory=lambda: CONVERGENCE_TOLERANCE.mean_abs_outer_vorp,
    )
    p99_abs_outer_vorp: float = field(
        default_factory=lambda: CONVERGENCE_TOLERANCE.p99_abs_outer_vorp,
    )
    max_abs_replacement: float = field(
        default_factory=lambda: CONVERGENCE_TOLERANCE.max_abs_replacement,
    )
    min_fair_rank_spearman: float = field(
        default_factory=lambda: CONVERGENCE_TOLERANCE.min_fair_rank_spearman,
    )
    min_top_50_overlap: float = field(
        default_factory=lambda: CONVERGENCE_TOLERANCE.min_top_50_overlap,
    )
    max_mean_abs_rank_change_top_150: float = field(
        default_factory=lambda: CONVERGENCE_TOLERANCE.max_mean_abs_rank_change_top_150,
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "criteria_version": self.version,
            "inherits_bounds_from": CONVERGENCE_TOLERANCE.version,
            "value_stability": {
                "mean_abs_expected_vorp": self.mean_abs_expected_vorp,
                "p99_abs_expected_vorp": self.p99_abs_expected_vorp,
                "mean_abs_p50_vorp": self.mean_abs_p50_vorp,
                "p99_abs_p50_vorp": self.p99_abs_p50_vorp,
                "mean_abs_outer_vorp": self.mean_abs_outer_vorp,
                "p99_abs_outer_vorp": self.p99_abs_outer_vorp,
            },
            "replacement_stability": {"max_abs_replacement": self.max_abs_replacement},
            "ranking_stability": {
                "min_fair_rank_spearman": self.min_fair_rank_spearman,
                "min_top_50_overlap": self.min_top_50_overlap,
                "max_mean_abs_rank_change_top_150": self.max_mean_abs_rank_change_top_150,
            },
            "excluded": {
                "min_tier_adjusted_rand": (
                    "tier-boundary stability is governed by phase4_tier_stability_v1 "
                    "(ADR-035) and is reported here rather than decided here"
                ),
                "max_tier_count_difference": (
                    "same property; a tier count is a function of the value curve, not of "
                    "the draw count"
                ),
            },
            "rules": [
                "the audit evaluates only the promoted production draw count",
                "it cannot select a draw count, and no result of it lowers one",
                "every bound is inherited unchanged from phase4_convergence_v1",
                "a comparison must satisfy every criterion for the audit to pass",
            ],
        }

    def _checks(
        self,
        evidence: ConvergenceEvidence,
    ) -> tuple[tuple[str, float, float, bool], ...]:
        return (
            (
                "mean_abs_expected_vorp",
                evidence.mean_abs_expected_vorp,
                self.mean_abs_expected_vorp,
                True,
            ),
            (
                "p99_abs_expected_vorp",
                evidence.p99_abs_expected_vorp,
                self.p99_abs_expected_vorp,
                True,
            ),
            ("mean_abs_p50_vorp", evidence.mean_abs_p50_vorp, self.mean_abs_p50_vorp, True),
            ("p99_abs_p50_vorp", evidence.p99_abs_p50_vorp, self.p99_abs_p50_vorp, True),
            ("mean_abs_outer_vorp", evidence.mean_abs_outer_vorp, self.mean_abs_outer_vorp, True),
            ("p99_abs_outer_vorp", evidence.p99_abs_outer_vorp, self.p99_abs_outer_vorp, True),
            ("max_abs_replacement", evidence.max_abs_replacement, self.max_abs_replacement, True),
            (
                "mean_abs_rank_change_top_150",
                evidence.mean_abs_rank_change_top_150,
                self.max_mean_abs_rank_change_top_150,
                True,
            ),
            ("fair_rank_spearman", evidence.fair_rank_spearman, self.min_fair_rank_spearman, False),
            ("top_50_overlap", evidence.top_50_overlap, self.min_top_50_overlap, False),
        )

    def evaluate(
        self,
        evidence: Sequence[ConvergenceEvidence],
        *,
        promoted_draws: int,
    ) -> SimulationConvergenceResult:
        """Judge the promoted configuration. Selects nothing; changes nothing."""
        scoped = [item for item in evidence if item.draws == promoted_draws]
        failures: list[str] = []
        worst: dict[str, dict[str, float]] = {}
        notes: list[str] = []

        for item in scoped:
            for name, observed, bound, upper in self._checks(item):
                record = worst.setdefault(
                    name,
                    {
                        "bound": bound,
                        "worst": float("-inf") if upper else float("inf"),
                        "direction": 1.0 if upper else -1.0,
                    },
                )
                if observed != observed:  # NaN: not measurable
                    failures.append(f"{item.scenario}/{item.comparison}: {name} not measured")
                    continue
                record["worst"] = (
                    max(record["worst"], observed) if upper else min(record["worst"], observed)
                )
                if (upper and observed > bound) or (not upper and observed < bound):
                    relation = "exceeds" if upper else "is below"
                    failures.append(
                        f"{item.scenario}/{item.comparison}: {name} {observed:.4f} "
                        f"{relation} {bound:.4f}",
                    )

        tier = {
            "worst_tier_adjusted_rand": min(
                (item.tier_adjusted_rand for item in scoped),
                default=float("nan"),
            ),
            "worst_abs_tier_count_difference": float(
                max((abs(item.tier_count_difference) for item in scoped), default=0),
            ),
        }

        if not scoped:
            notes.append(
                f"the report holds no comparison at {promoted_draws} draws, so the audit is "
                "undetermined rather than passed",
            )
        degenerate = [
            item.comparison
            for item in scoped
            if item.mean_abs_expected_vorp == 0.0 and item.fair_rank_spearman == 1.0
        ]
        if degenerate:
            notes.append(
                "a comparison of the promoted count against itself is degenerate by "
                f"construction and carries no information: {', '.join(sorted(set(degenerate)))}",
            )

        return SimulationConvergenceResult(
            rule=self.version,
            promoted_draws=promoted_draws,
            converged=bool(scoped) and not failures,
            comparisons=len(scoped),
            failures=tuple(failures),
            residuals={key: dict(value) for key, value in sorted(worst.items())},
            tier_observations=tier,
            notes=tuple(notes),
        )


SIMULATION_CONVERGENCE_AUDIT = SimulationConvergenceAudit()


def evidence_from_report(measurements: Iterable[Mapping[str, Any]]) -> list[ConvergenceEvidence]:
    """Rebuild the Phase-4 evidence records from a committed experiment report.

    The audit reads the report rather than re-running the simulation, deliberately: the
    committed report is the evidence ADR-034 was written against, and re-deriving it would
    make this a different measurement rather than a different question about the same one.
    """
    return [
        ConvergenceEvidence(
            scenario=str(row["scenario"]),
            comparison=str(row["comparison"]),
            draws=int(row["draws"]),
            mean_abs_expected_vorp=float(row["mean_abs_expected_vorp"]),
            p99_abs_expected_vorp=float(row["p99_abs_expected_vorp"]),
            mean_abs_p50_vorp=float(row["mean_abs_p50_vorp"]),
            p99_abs_p50_vorp=float(row["p99_abs_p50_vorp"]),
            mean_abs_outer_vorp=float(row["mean_abs_outer_vorp"]),
            p99_abs_outer_vorp=float(row["p99_abs_outer_vorp"]),
            max_abs_replacement=float(row["max_abs_replacement"]),
            fair_rank_spearman=float(row["fair_rank_spearman"]),
            top_50_overlap=float(row["top_50_overlap"]),
            mean_abs_rank_change_top_150=float(row["mean_abs_rank_change_top_150"]),
            tier_adjusted_rand=float(row["tier_adjusted_rand"]),
            tier_count_difference=int(row["tier_count_difference"]),
        )
        for row in measurements
    ]
