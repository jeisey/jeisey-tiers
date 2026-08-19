"""Chronological rolling-origin folds and the two training-window policies.

ADR-004 forbids random splits: production is future-season forecasting, so every fold
trains on seasons strictly before the season it is scored on. This module is the only place
that decides what "before" means, and it is deliberately declarative - a fold is data, not
a loop variable, so the fold table can be persisted, hashed and compared between runs.

Two expanding-window policies are compared on identical validation seasons:

``W1`` — all usable history, training from 2014;
``W2`` — the modern roster-coverage era, training from 2017.

Phase 2 measured a real upstream regime boundary behind that choice: nflverse roster
coverage steps up at 2016, so target seasons 2014-2016 carry ~670 eligible rows against
~1,050 from 2017 on. The policies exist so the question is answered with evidence rather
than taste, and the common validation seasons 2020-2024 give W2 at least three training
seasons before its first fold so the comparison is like for like.

Folds whose validation season W2 cannot reproduce (2017-2019) are emitted separately as W1
diagnostics. They may inform the discussion; they may not decide the window.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from ffdraft.modeling.holdout import (
    FINAL_HOLDOUT_SEASON,
    FinalEvalAuthorization,
    assert_seasons_sealed,
)

__all__ = [
    "DEVELOPMENT_VALIDATION_SEASONS",
    "DEFAULT_SEED",
    "Fold",
    "FoldKind",
    "W1_DIAGNOSTIC_VALIDATION_SEASONS",
    "WindowPolicy",
    "development_folds",
    "diagnostic_folds",
    "final_holdout_fold",
    "fold_table",
]

#: Common development validation seasons. Both window policies produce exactly these, which
#: is what makes the W1-vs-W2 comparison paired at the row level.
DEVELOPMENT_VALIDATION_SEASONS: tuple[int, ...] = (2020, 2021, 2022, 2023, 2024)

#: Earlier validation seasons W2 cannot reproduce with three training seasons. W1-only, and
#: barred from the window decision for exactly that reason.
W1_DIAGNOSTIC_VALIDATION_SEASONS: tuple[int, ...] = (2017, 2018, 2019)

#: Every stochastic step derives from this. Recorded in the report; never varied to shop
#: for a better result.
DEFAULT_SEED = 20260819

#: A window needs enough seasons to estimate anything at all. Three is the minimum, and is
#: what fixes 2020 as the first common validation season under W2.
MINIMUM_TRAINING_SEASONS = 3


class WindowPolicy(StrEnum):
    """Which historical seasons an expanding training window may start from."""

    W1 = "W1_all_history"
    W2 = "W2_modern_era"

    @property
    def first_train_season(self) -> int:
        return 2014 if self is WindowPolicy.W1 else 2017

    @property
    def rationale(self) -> str:
        if self is WindowPolicy.W1:
            return (
                "Every usable target season. More rows and more history, at the cost of "
                "mixing in 2014-2016, whose eligible universe is ~36% smaller because "
                "nflverse roster coverage steps up at 2016."
            )
        return (
            "The modern roster-coverage era only. Fewer training rows, one structurally "
            "consistent eligibility universe."
        )


class FoldKind(StrEnum):
    """What a fold is allowed to decide."""

    #: Counts towards model selection and the window decision.
    DEVELOPMENT = "development"
    #: Reported, never decisive: W2 cannot reproduce these validation seasons.
    W1_DIAGNOSTIC = "w1_diagnostic"
    #: The sealed final holdout. Never produced without an explicit authorization.
    FINAL_HOLDOUT = "final_holdout"


@dataclass(frozen=True, slots=True)
class Fold:
    """One chronological train/validate split."""

    window: WindowPolicy
    train_start_season: int
    train_end_season: int
    validation_season: int
    kind: FoldKind = FoldKind.DEVELOPMENT

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
        if self.train_start_season < self.window.first_train_season:
            raise ValueError(
                f"{self.window} may not train from {self.train_start_season}; its first "
                f"allowed training season is {self.window.first_train_season}",
            )

    @property
    def train_seasons(self) -> tuple[int, ...]:
        return tuple(range(self.train_start_season, self.train_end_season + 1))

    @property
    def n_train_seasons(self) -> int:
        return self.train_end_season - self.train_start_season + 1

    @property
    def fold_id(self) -> str:
        return (
            f"{self.window.value}:{self.train_start_season}-{self.train_end_season}"
            f"->{self.validation_season}"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "fold_id": self.fold_id,
            "window_policy": str(self.window),
            "kind": str(self.kind),
            "train_start_season": self.train_start_season,
            "train_end_season": self.train_end_season,
            "train_seasons": list(self.train_seasons),
            "n_train_seasons": self.n_train_seasons,
            "validation_season": self.validation_season,
        }


def _expanding(
    window: WindowPolicy,
    validation_seasons: Iterable[int],
    kind: FoldKind,
) -> tuple[Fold, ...]:
    folds: list[Fold] = []
    for season in sorted(validation_seasons):
        start = window.first_train_season
        end = season - 1
        if end - start + 1 < MINIMUM_TRAINING_SEASONS:
            raise ValueError(
                f"{window} cannot validate {season}: only {end - start + 1} training "
                f"season(s) available, {MINIMUM_TRAINING_SEASONS} required",
            )
        folds.append(
            Fold(
                window=window,
                train_start_season=start,
                train_end_season=end,
                validation_season=season,
                kind=kind,
            ),
        )
    return tuple(folds)


def development_folds(
    window: WindowPolicy,
    validation_seasons: Sequence[int] = DEVELOPMENT_VALIDATION_SEASONS,
) -> tuple[Fold, ...]:
    """The common development folds for one window policy.

    The final holdout is refused here rather than filtered: asking for it by accident is a
    programming error worth surfacing, not something to silently drop.
    """
    assert_seasons_sealed(validation_seasons, context="development folds")
    return _expanding(window, validation_seasons, FoldKind.DEVELOPMENT)


def diagnostic_folds(
    window: WindowPolicy = WindowPolicy.W1,
    validation_seasons: Sequence[int] = W1_DIAGNOSTIC_VALIDATION_SEASONS,
) -> tuple[Fold, ...]:
    """Earlier validation seasons only one window can reach. Never decisive."""
    assert_seasons_sealed(validation_seasons, context="diagnostic folds")
    return _expanding(window, validation_seasons, FoldKind.W1_DIAGNOSTIC)


def final_holdout_fold(
    window: WindowPolicy,
    *,
    authorization: FinalEvalAuthorization,
) -> Fold:
    """The sealed fold. Constructing the authorization is the deliberate act; this is not."""
    assert_seasons_sealed(
        [FINAL_HOLDOUT_SEASON],
        authorization=authorization,
        context="final holdout fold",
    )
    return Fold(
        window=window,
        train_start_season=window.first_train_season,
        train_end_season=FINAL_HOLDOUT_SEASON - 1,
        validation_season=FINAL_HOLDOUT_SEASON,
        kind=FoldKind.FINAL_HOLDOUT,
    )


def fold_table(folds: Sequence[Fold]) -> list[dict[str, Any]]:
    """The persisted fold table, ordered so two runs serialize identically."""
    return [
        fold.to_dict()
        for fold in sorted(
            folds,
            key=lambda f: (f.window.value, f.kind.value, f.validation_season),
        )
    ]
