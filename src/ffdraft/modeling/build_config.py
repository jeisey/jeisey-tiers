"""The frozen parameters a production current build runs under.

Separated from :mod:`ffdraft.pipeline.current` for a structural reason rather than a
stylistic one. `ffdraft.modeling.frozen` names this configuration — it is the Phase-4
freeze's output — and importing it from the pipeline module dragged the whole current-build
dependency tree, including the Sleeper status package, into the intrinsic side of the
import graph. `tests/contract/test_architecture_boundary.py` fails on exactly that.

Every field here is the outcome of a Phase-4 study, not a default. The values live in
`ffdraft.modeling.frozen`; this module only says what shape they take.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ffdraft.modeling.metrics import QUANTILE_LEVELS
from ffdraft.tiers.algorithms import ALGORITHM_VERSIONS

__all__ = ["CurrentBuildConfig"]

_LAUNCH_SCORING: tuple[str, ...] = ("STD", "HALF", "PPR")


@dataclass(frozen=True)
class CurrentBuildConfig:
    """The frozen production parameters a current build runs under."""

    draws: int
    ranking_statistic: str
    #: Which of the two documented segmentation algorithms drew these tiers. A board is a
    #: function of the algorithm as much as of the penalty, so a build records both.
    tier_algorithm: str
    tier_penalty: float
    board_depth: int
    seed: int
    #: The frozen tier stability gate's verdict on this configuration, carried into every
    #: build's metadata. It is a finding about the parameters rather than a parameter, but
    #: it travels with them so that no published board can be read as sharper than the
    #: measurement behind it. `ffdraft.modeling.frozen` supplies the production value.
    tier_stability_gate: str = "unmeasured"
    league_preset_ids: tuple[str, ...] = ("redraft-10", "redraft-12", "redraft-14")
    scoring_presets: tuple[str, ...] = _LAUNCH_SCORING
    levels: tuple[float, ...] = QUANTILE_LEVELS

    def to_dict(self) -> dict[str, Any]:
        return {
            "draws": self.draws,
            "ranking_statistic": self.ranking_statistic,
            "tier_algorithm": self.tier_algorithm,
            "tier_algorithm_version": ALGORITHM_VERSIONS[self.tier_algorithm],
            "tier_penalty": self.tier_penalty,
            "tier_stability_gate": self.tier_stability_gate,
            "board_depth": self.board_depth,
            "seed": self.seed,
            "league_preset_ids": list(self.league_preset_ids),
            "scoring_presets": list(self.scoring_presets),
            "levels": list(self.levels),
        }
