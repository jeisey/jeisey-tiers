"""The Phase-12 rest-of-season freeze: the accepted architecture, in one place, in code.

Phase 11 accepted `intrinsic-ros-v1` (`rc1_ros_hurdle_v1`) under `ros_promotion_v2` and then
stopped, because a promotion decision is a claim about an architecture rather than an object
on disk. Every prediction Phase 11 made came out of a fold, and
:mod:`ffdraft.ros.estimators` exposes no fitted object on purpose.

This module is the boundary between "accepted" and "served". It restates the accepted
configuration as constants and hashes them, so a production fit can prove it is the same
architecture rather than assert it. ADR-078 is the rule; this is the rule's fingerprint.

**Nothing here may change in response to a 2026 result.** Every constant is copied from the
Phase-11 candidate that was evaluated, and
``tests/unit/test_ros_production.py::test_frozen_spec_matches_the_evaluated_candidate``
asserts exactly that against :class:`~ffdraft.ros.candidates.RosHurdleCandidate` — a drifted
constant fails the suite rather than shipping a differently-configured model under an
accepted model's name.

The one thing a production fit may vary is the labelled rows it sees (ADR-078's table), and
even that is bounded here: the window starts at Phase 3's inherited W2 season and ends at
:data:`ROS_PRODUCTION_LAST_TRAINING_SEASON`, which is the sealed season whose holdout has
been spent.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any

from ffdraft.modeling.candidates import HURDLE_COMPOSITION_DRAWS
from ffdraft.modeling.folds import DEFAULT_SEED
from ffdraft.modeling.metrics import QUANTILE_LEVELS
from ffdraft.ros.candidates import RC1_NUM_BOOST_ROUND, RC1_PARAMETERS, RC1_VERSION
from ffdraft.ros.folds import ROS_TRAIN_START_SEASON
from ffdraft.ros.value import ROS_VALUE_VERSION, RosReplacementRule
from ffdraft.tiers.algorithms import PRIMARY_ALGORITHM

__all__ = [
    "ROS_ARCHITECTURE",
    "ROS_BUILD_CONFIG",
    "ROS_CONVERGENCE_VERDICT",
    "ROS_MODEL_VERSION",
    "ROS_PRODUCTION_FIT_RULE_VERSION",
    "ROS_PRODUCTION_FIRST_TRAINING_SEASON",
    "ROS_PRODUCTION_LAST_TRAINING_SEASON",
    "ROS_PRODUCTION_SPEC",
    "ROS_SERVING_SEASON",
    "ROS_TIER_STABILITY_VERDICT",
    "RosBuildConfig",
    "RosProductionSpec",
    "RosRefitReason",
]

#: The promoted model's public version. Distinct from the preseason model's, permanently.
ROS_MODEL_VERSION = "intrinsic-ros-v1"

#: The architecture, named the way the artifact records it.
ROS_ARCHITECTURE = "ros_availability_x_conditional_performance"

#: The versioned production-fit protocol (ADR-078). Recorded on every fitted artifact.
ROS_PRODUCTION_FIT_RULE_VERSION = "ros_production_fit_v1"

#: Phase 3's W2 window, inherited by Phase 11 and inherited again here rather than re-argued.
ROS_PRODUCTION_FIRST_TRAINING_SEASON = ROS_TRAIN_START_SEASON

#: The last season a production fit may train on.
#:
#: 2025 is the rest-of-season sealed season (ADR-069) and its holdout was consumed once on
#: 2026-09-04. Including it therefore still requires the explicit token — the seal is a
#: gate, not a date — which is why :func:`ffdraft.ros.production.train_ros_production_model`
#: takes an authorization rather than trusting this constant.
ROS_PRODUCTION_LAST_TRAINING_SEASON = 2025

#: The season the in-season product serves. Never a training season: ADR-078 step 4.
ROS_SERVING_SEASON = 2026

#: Phase 11's measured verdicts, carried into every build so a reader sees them beside the
#: numbers they qualify rather than in a document they have to go and find (ADR-074).
ROS_CONVERGENCE_VERDICT = "fail"
ROS_TIER_STABILITY_VERDICT = "fail"


class RosRefitReason(StrEnum):
    """Why a production fit was run. ADR-078 permits exactly these three."""

    INITIAL_PRODUCTION_FIT = "initial_production_fit"
    NEW_COMPLETED_SEASON = "new_completed_season"
    REPRODUCTION = "reproduction"

    @property
    def description(self) -> str:
        if self is RosRefitReason.INITIAL_PRODUCTION_FIT:
            return "the first fit of the accepted architecture after promotion"
        if self is RosRefitReason.NEW_COMPLETED_SEASON:
            return "a season completed and its labels exist, so the training window extends"
        return "a byte-for-byte rebuild to verify the committed artifact"


@dataclass(frozen=True)
class RosProductionSpec:
    """The frozen architecture a rest-of-season production model is fitted from.

    Every field is copied from the candidate Phase 11 evaluated. :meth:`configuration_hash`
    digests all of them, and it is the single value that decides whether a fitted artifact
    is a *refit of the accepted model* or *a different model wearing its name* (ADR-078).
    """

    model_version: str = ROS_MODEL_VERSION
    candidate_version: str = RC1_VERSION
    architecture: str = ROS_ARCHITECTURE
    parameters: Any = field(default_factory=lambda: MappingProxyType(dict(RC1_PARAMETERS)))
    num_boost_round: int = RC1_NUM_BOOST_ROUND
    composition_draws: int = HURDLE_COMPOSITION_DRAWS
    levels: tuple[float, ...] = QUANTILE_LEVELS
    seed: int = DEFAULT_SEED
    calibration: str = "monotone projection only; no fitted shift"
    dependence: str = "Gaussian copula, one correlation fitted on an inner chronological split"
    #: The Monte Carlo stream key's root. A determinism device, not a modelling choice — the
    #: same distinction the candidate's own docstring draws about its thread count. Phase 11
    #: composed under ``("ros_candidate", "development")``; a production fit declares its own
    #: stream so a served draw is never silently the same draw an experiment reported.
    composition_seed_material: tuple[str, ...] = ("ros_candidate", "production")

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_version": self.model_version,
            "candidate_version": self.candidate_version,
            "architecture": self.architecture,
            "parameters": dict(self.parameters),
            "num_boost_round": self.num_boost_round,
            "composition_draws": self.composition_draws,
            "levels": list(self.levels),
            "seed": self.seed,
            "calibration": self.calibration,
            "dependence": self.dependence,
            "composition_seed_material": list(self.composition_seed_material),
        }

    def configuration_hash(self) -> str:
        """A digest over the whole frozen configuration.

        Excludes everything a refit is allowed to vary — the training rows, the timestamp,
        the code SHA — so two fits of the accepted architecture on different windows agree
        here, and a tuned parameter does not.
        """
        payload = json.dumps(self.to_dict(), sort_keys=True)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]

    @classmethod
    def from_dict(cls, payload: Any) -> RosProductionSpec:
        return cls(
            model_version=str(payload["model_version"]),
            candidate_version=str(payload["candidate_version"]),
            architecture=str(payload["architecture"]),
            parameters=MappingProxyType(dict(payload["parameters"])),
            num_boost_round=int(payload["num_boost_round"]),
            composition_draws=int(payload["composition_draws"]),
            levels=tuple(float(value) for value in payload["levels"]),
            seed=int(payload["seed"]),
            calibration=str(payload["calibration"]),
            dependence=str(payload["dependence"]),
            composition_seed_material=tuple(
                str(value) for value in payload["composition_seed_material"]
            ),
        )


ROS_PRODUCTION_SPEC = RosProductionSpec()


@dataclass(frozen=True)
class RosBuildConfig:
    """The frozen simulation, replacement and segmentation parameters for the ROS board.

    ``draws`` is the **declared fallback**, not a converged count: no count in the frozen
    ladder met every tolerance and the tier partition is what failed to converge (ADR-074).
    ``tier_penalty`` is what `phase4_tier_v1` selected on rest-of-season boards. Both travel
    into build metadata with their verdicts so the board never presents a fallback as a
    settled value.
    """

    draws: int = 10_000
    seed: int = DEFAULT_SEED
    ranking_statistic: str = "median_vorp"
    tier_algorithm: str = PRIMARY_ALGORITHM
    tier_penalty: float = 3.0
    replacement_rule: str = RosReplacementRule.ROSTERED_DEPTH.value
    value_version: str = ROS_VALUE_VERSION
    convergence_verdict: str = ROS_CONVERGENCE_VERDICT
    tier_stability_verdict: str = ROS_TIER_STABILITY_VERDICT

    def to_dict(self) -> dict[str, Any]:
        return {
            "draws": self.draws,
            "draws_status": (
                "declared fallback; no count in the frozen ladder met every convergence "
                "tolerance (ADR-074)"
            ),
            "seed": self.seed,
            "ranking_statistic": self.ranking_statistic,
            "tier_algorithm": self.tier_algorithm,
            "tier_penalty": self.tier_penalty,
            "replacement_rule": self.replacement_rule,
            "replacement_rule_description": RosReplacementRule(self.replacement_rule).description,
            "value_version": self.value_version,
            "convergence_gate": self.convergence_verdict,
            "tier_stability_gate": self.tier_stability_verdict,
        }


ROS_BUILD_CONFIG = RosBuildConfig()
