"""Chronological, season-blocked folds for the rest-of-season model.

`docs/RELEASE2_ROADMAP.md` 11.4 is unambiguous: never randomly split weekly snapshots across
years. Snapshots from one season are enormously correlated - the same player appears in
sixteen of them - so a random split would put week 5 in training and week 6 in validation
and measure interpolation instead of forecasting.

Every fold therefore trains on seasons **strictly before** the season it is scored on, and
the split is by season alone. A fold is data rather than a loop variable, so the fold table
can be persisted, hashed and compared between runs.

**One training window, inherited rather than re-litigated.** Phase 3 measured the upstream
regime boundary behind the choice - nflverse roster coverage steps up at 2016, so target
seasons 2014-2016 carry ~36% fewer eligible rows - and selected W2, the modern era beginning
2017. Nothing about the rest-of-season grain changes that fact, and re-running a W1-vs-W2
comparison would spend a day rediscovering a repository fact (`AGENTS.md` section 17). ROS
trains from 2017 and records the inheritance.

**Five development validation seasons, one sealed.** 2020-2024 are the development folds -
the earliest gives the expanding window three training seasons, which is the same minimum
Phase 3 fixed. 2025 is sealed (:mod:`ffdraft.ros.holdout`) and is refused here rather than
filtered, because asking for it by accident is a programming error worth surfacing.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from ffdraft.modeling.folds import WindowPolicy
from ffdraft.ros.holdout import (
    ROS_SEALED_SEASON,
    RosFinalEvalAuthorization,
    assert_ros_seasons_sealed,
)

__all__ = [
    "ROS_DEVELOPMENT_VALIDATION_SEASONS",
    "ROS_FOLD_RULE_VERSION",
    "ROS_MINIMUM_TRAINING_SEASONS",
    "ROS_SEED",
    "ROS_TRAIN_START_SEASON",
    "RosFold",
    "RosFoldKind",
    "ros_development_folds",
    "ros_final_fold",
    "ros_fold_table",
]

#: Bump when the fold construction changes.
ROS_FOLD_RULE_VERSION = "ros_folds_v1"

#: Inherited from Phase 3's W2 decision, not re-derived.
ROS_TRAIN_START_SEASON = WindowPolicy.W2.first_train_season

ROS_DEVELOPMENT_VALIDATION_SEASONS: tuple[int, ...] = (2020, 2021, 2022, 2023, 2024)

ROS_MINIMUM_TRAINING_SEASONS = 3

#: Every stochastic step derives from this. Recorded in the report; never varied to shop for
#: a better result.
ROS_SEED = 20260903


class RosFoldKind(StrEnum):
    DEVELOPMENT = "development"
    FINAL_HOLDOUT = "final_holdout"


@dataclass(frozen=True, slots=True)
class RosFold:
    """One chronological train/validate split, by season."""

    train_start_season: int
    train_end_season: int
    validation_season: int
    kind: RosFoldKind = RosFoldKind.DEVELOPMENT

    def __post_init__(self) -> None:
        if self.train_start_season > self.train_end_season:
            raise ValueError(
                f"empty training window {self.train_start_season}-{self.train_end_season}",
            )
        if self.train_end_season >= self.validation_season:
            raise ValueError(
                f"fold trains through {self.train_end_season} and validates on "
                f"{self.validation_season}: training must end strictly before validation",
            )
        if self.train_start_season < ROS_TRAIN_START_SEASON:
            raise ValueError(
                f"the rest-of-season window may not train from {self.train_start_season}; "
                f"its first allowed training season is {ROS_TRAIN_START_SEASON}",
            )

    @property
    def train_seasons(self) -> tuple[int, ...]:
        return tuple(range(self.train_start_season, self.train_end_season + 1))

    @property
    def n_train_seasons(self) -> int:
        return self.train_end_season - self.train_start_season + 1

    @property
    def fold_id(self) -> str:
        return f"ros:{self.train_start_season}-{self.train_end_season}->{self.validation_season}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "fold_id": self.fold_id,
            "kind": str(self.kind),
            "train_start_season": self.train_start_season,
            "train_end_season": self.train_end_season,
            "train_seasons": list(self.train_seasons),
            "n_train_seasons": self.n_train_seasons,
            "validation_season": self.validation_season,
        }


def _expanding(validation_seasons: Iterable[int], kind: RosFoldKind) -> tuple[RosFold, ...]:
    folds: list[RosFold] = []
    for season in sorted(validation_seasons):
        start = ROS_TRAIN_START_SEASON
        end = season - 1
        if end - start + 1 < ROS_MINIMUM_TRAINING_SEASONS:
            raise ValueError(
                f"cannot validate {season}: only {end - start + 1} training season(s) "
                f"available, {ROS_MINIMUM_TRAINING_SEASONS} required",
            )
        folds.append(
            RosFold(
                train_start_season=start,
                train_end_season=end,
                validation_season=season,
                kind=kind,
            ),
        )
    return tuple(folds)


def ros_development_folds(
    validation_seasons: Sequence[int] = ROS_DEVELOPMENT_VALIDATION_SEASONS,
) -> tuple[RosFold, ...]:
    """The development folds. The sealed season is refused, not silently dropped."""
    assert_ros_seasons_sealed(validation_seasons, context="ROS development folds")
    return _expanding(validation_seasons, RosFoldKind.DEVELOPMENT)


def ros_final_fold(*, authorization: RosFinalEvalAuthorization) -> RosFold:
    """The sealed fold. Constructing the authorization is the deliberate act; this is not."""
    assert_ros_seasons_sealed(
        [ROS_SEALED_SEASON],
        authorization=authorization,
        context="ROS final holdout fold",
    )
    return RosFold(
        train_start_season=ROS_TRAIN_START_SEASON,
        train_end_season=ROS_SEALED_SEASON - 1,
        validation_season=ROS_SEALED_SEASON,
        kind=RosFoldKind.FINAL_HOLDOUT,
    )


def ros_fold_table(folds: Sequence[RosFold]) -> list[dict[str, Any]]:
    """The persisted fold table, ordered so two runs serialize identically."""
    return [
        fold.to_dict()
        for fold in sorted(folds, key=lambda item: (item.kind.value, item.validation_season))
    ]
