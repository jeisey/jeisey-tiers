"""The rest-of-season sealed season, and the slices it will be reported on.

2025 is the sealed final season for ``intrinsic-ros-v1``. The season is chosen and the
diagnostic slices are declared **before** any candidate is compared, and both are committed
before the experiment that consumes them, so no result can motivate the definition after the
fact.

**Why 2025, and the caveat that comes with it.** It is the most recent fully labelled season
and therefore the closest available analogue of the 2026 in-season environment the model will
actually run in - the same 18-week schedule, the same upstream coverage. It is also the
season Phase 4 already opened as the *preseason* model's final holdout, which is a real
qualification and is stated rather than glossed: this project has seen 2025 season-total
outcomes. It has never seen a 2025 rest-of-season snapshot, a 2025 through-week label or any
metric on them, and the seal here is enforced by the same structural mechanism Release 1
uses - a development run physically does not load the rows. The residual exposure is that
season totals correlate with rest-of-season totals, so a 2025 result should be read as
"strong but not fully naive" evidence. Choosing 2024 instead would trade that qualification
for a season further from production and one fewer development fold; the trade is recorded in
ADR-069 rather than decided silently.

Unsealing requires the ROS-specific confirmation token. Release 1's token does not work here
and this one does not work there: opening one holdout must never open the other.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import polars as pl

from ffdraft.modeling.holdout import HoldoutSealError

__all__ = [
    "PREDECLARED_ROS_SLICES",
    "ROS_FINAL_EVAL_CONFIRMATION_TOKEN",
    "ROS_SEALED_SEASON",
    "ROS_SEALED_SEASONS",
    "RosFinalEvalAuthorization",
    "RosSlice",
    "RosSliceKind",
    "assert_ros_seasons_sealed",
    "is_ros_sealed",
    "ros_holdout_policy",
    "ros_slice_masks",
]

#: The sealed season. Everything from here on is out of bounds for development work.
ROS_SEALED_SEASON = 2025

ROS_SEALED_SEASONS = "season >= 2025"

#: Deliberately distinct from Release 1's token, and deliberately absent from every default.
ROS_FINAL_EVAL_CONFIRMATION_TOKEN = "RELEASE-ROS-FINAL-HOLDOUT-2025"

#: Fixed here, before the comparison, so "early season" cannot be redefined once the early
#: season turns out to be where the model struggles. Weeks 1-3 is the roadmap's own band;
#: 4-9 is the middle of the season; 10 onward is the fantasy playoff run-in.
EARLY_SEASON_LAST_WEEK = 3
MID_SEASON_LAST_WEEK = 9

#: A player who has missed this many consecutive weeks and played before is "returning".
RETURN_ABSENCE_WEEKS = 3

#: Top two rounds. The roadmap's "high draft capital" cohort.
HIGH_DRAFT_CAPITAL_PICK = 64

#: A position-blind floor for "poor recent production", fixed before any result. It sits
#: below every position's starter-quality weekly rate, so the slice is a genuine
#: underperformance cohort rather than a re-labelling of quarterbacks.
POOR_FORM_POINTS_PER_WEEK = 8.0

#: Share of a cell taken as the "extreme uncertainty" tail, measured on the frozen primary
#: baseline's interval so the mask is identical for every model being compared.
EXTREME_UNCERTAINTY_QUANTILE = 0.90


class RosFinalEvalAuthorization:
    """Proof that the ROS sealed season was deliberately opened."""

    __slots__ = ("confirmation", "reason")

    def __init__(self, confirmation: str, reason: str) -> None:
        if confirmation != ROS_FINAL_EVAL_CONFIRMATION_TOKEN:
            raise HoldoutSealError(
                "rest-of-season final evaluation requires the exact confirmation token "
                f"{ROS_FINAL_EVAL_CONFIRMATION_TOKEN!r}; refusing to unseal season "
                f"{ROS_SEALED_SEASON}",
            )
        if not reason.strip():
            raise HoldoutSealError(
                "rest-of-season final evaluation requires a recorded reason; the report has "
                "to say why the holdout was consumed",
            )
        self.confirmation = confirmation
        self.reason = reason

    def to_dict(self) -> dict[str, Any]:
        return {"authorized": True, "reason": self.reason}


def is_ros_sealed(season: int) -> bool:
    return season >= ROS_SEALED_SEASON


def assert_ros_seasons_sealed(
    seasons: Iterable[int],
    *,
    authorization: RosFinalEvalAuthorization | None = None,
    context: str = "",
) -> None:
    """Refuse any sealed season unless an authorization was supplied."""
    if authorization is not None:
        return
    offending = sorted({season for season in seasons if is_ros_sealed(season)})
    if offending:
        where = f" in {context}" if context else ""
        raise HoldoutSealError(
            f"season(s) {offending} are sealed{where}: {ROS_SEALED_SEASONS} is the "
            "rest-of-season final holdout and may not be used for development training, "
            "tuning or evaluation. Pass an explicit RosFinalEvalAuthorization to run the "
            "final evaluation.",
        )


class RosSliceKind(StrEnum):
    PRIMARY = "primary"
    DIAGNOSTIC = "diagnostic"


@dataclass(frozen=True, slots=True)
class RosSlice:
    """One predeclared way the rest-of-season result will be sliced."""

    slice_id: str
    kind: RosSliceKind
    description: str
    predicate: str
    rationale: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "slice_id": self.slice_id,
            "kind": str(self.kind),
            "description": self.description,
            "predicate": self.predicate,
            "rationale": self.rationale,
        }


#: Declared before any candidate comparison. Every predicate reads feature-side metadata or
#: the frozen primary baseline's own interval, never an outcome, so none of them could have
#: been chosen to flatter a result. `docs/RELEASE2_ROADMAP.md` 11.3 names each cohort.
PREDECLARED_ROS_SLICES: tuple[RosSlice, ...] = (
    RosSlice(
        slice_id="full_universe",
        kind=RosSliceKind.PRIMARY,
        description="Every modelled snapshot row, all seasons, weeks, positions and presets",
        predicate="true",
        rationale=(
            "The production-realistic result: an in-season board has to rank everyone, "
            "including the players who will not play again. Nothing may substitute for it."
        ),
    ),
    RosSlice(
        slice_id="position",
        kind=RosSliceKind.DIAGNOSTIC,
        description="Grouped by QB/RB/WR/TE",
        predicate="group_by(position)",
        rationale="A positional collapse is invisible in a pooled number.",
    ),
    RosSlice(
        slice_id="scoring_preset",
        kind=RosSliceKind.DIAGNOSTIC,
        description="Grouped by STD/HALF/PPR",
        predicate="group_by(scoring_preset)",
        rationale="Each preset is a separate model; each gets a separate result.",
    ),
    RosSlice(
        slice_id="season_phase",
        kind=RosSliceKind.DIAGNOSTIC,
        description="Weeks 1-3, 4-9 and 10 onward",
        predicate=f"through_week <= {EARLY_SEASON_LAST_WEEK} | <= {MID_SEASON_LAST_WEEK} | later",
        rationale=(
            "Early snapshots have almost no current-season evidence and a long horizon; late "
            "snapshots have plenty of evidence and almost no horizon. Pooling them hides both."
        ),
    ),
    RosSlice(
        slice_id="rookie",
        kind=RosSliceKind.DIAGNOSTIC,
        description="Rows flagged as rookies by prior-existence evidence",
        predicate="rookie_flag",
        rationale="The lowest-information population; error is expected to be larger and "
        "must not be averaged away.",
    ),
    RosSlice(
        slice_id="veteran",
        kind=RosSliceKind.DIAGNOSTIC,
        description="Rows not flagged as rookies",
        predicate="not rookie_flag",
        rationale="Reported with its complement so the split is exhaustive.",
    ),
    RosSlice(
        slice_id="games_played_band",
        kind=RosSliceKind.DIAGNOSTIC,
        description="Current-season appearances at the cutoff: 0, 1-2, or 3 or more",
        predicate="games_to_date == 0 | 1..2 | >= 3",
        rationale=(
            "11.3 asks for it by name. A zero-game row is a pure preseason-prior prediction "
            "wearing an in-season model's clothes, and pooling it flatters the model."
        ),
    ),
    RosSlice(
        slice_id="returning_from_absence",
        kind=RosSliceKind.DIAGNOSTIC,
        description=(
            f"Has played this season but has missed at least {RETURN_ABSENCE_WEEKS} "
            "consecutive weeks ending at the cutoff"
        ),
        predicate=f"has_played_this_season and consecutive_weeks_missed >= {RETURN_ABSENCE_WEEKS}",
        rationale=(
            "The cohort a model with no injury feed should be worst at, and the one whose "
            "error most needs to be visible rather than pooled away."
        ),
    ),
    RosSlice(
        slice_id="changed_team_in_season",
        kind=RosSliceKind.DIAGNOSTIC,
        description="More than one team observed at or before the cutoff",
        predicate="team_changed_in_season",
        rationale="A role change mid-season breaks the continuity every to-date rate assumes.",
    ),
    RosSlice(
        slice_id="in_season_arrival",
        kind=RosSliceKind.DIAGNOSTIC,
        description="Players absent from the season's preseason eligible universe",
        predicate="not in_preseason_universe",
        rationale=(
            "Their whole preseason feature block is null, so this slice measures what the "
            "in-season block can do on its own."
        ),
    ),
    RosSlice(
        slice_id="high_capital_underperforming",
        kind=RosSliceKind.DIAGNOSTIC,
        description=(
            f"Top-{HIGH_DRAFT_CAPITAL_PICK} draft picks with at least three appearances and "
            f"under {POOR_FORM_POINTS_PER_WEEK} fantasy points per elapsed week"
        ),
        predicate=(
            f"draft_overall <= {HIGH_DRAFT_CAPITAL_PICK} and games_to_date >= 3 and "
            f"points_per_week_to_date < {POOR_FORM_POINTS_PER_WEEK}"
        ),
        rationale=(
            "11.3's 'high draft capital, poor recent production'. The threshold is "
            "position-blind and fixed here before any result; it sits below every position's "
            "starter-quality weekly rate, and the slice is diagnostic, never decisive."
        ),
    ),
    RosSlice(
        slice_id="high_capital_rookie",
        kind=RosSliceKind.DIAGNOSTIC,
        description=f"Rookies drafted inside the top {HIGH_DRAFT_CAPITAL_PICK} picks",
        predicate=f"rookie_flag and draft_overall <= {HIGH_DRAFT_CAPITAL_PICK}",
        rationale="11.3's 'low-history rookies with strong draft capital': the cohort where "
        "the preseason prior is strong and the in-season evidence is thin.",
    ),
    RosSlice(
        slice_id="extreme_uncertainty",
        kind=RosSliceKind.DIAGNOSTIC,
        description=(
            "Rows in the widest decile of the frozen primary baseline's P10-P90 interval, "
            "measured within each evaluation cell"
        ),
        predicate=f"baseline_p90 - baseline_p10 >= cell quantile {EXTREME_UNCERTAINTY_QUANTILE}",
        rationale=(
            "11.3's 'players with extreme uncertainty'. The mask is taken from the frozen "
            "baseline rather than from whichever model is being judged, so every model is "
            "measured on identical rows."
        ),
    ),
)


@dataclass(frozen=True, slots=True)
class RosSliceMask:
    """One concrete partition of an evaluation frame."""

    slice_id: str
    kind: RosSliceKind
    label: str
    mask: pl.Expr


def _grouped(
    frame: pl.DataFrame,
    slice_id: str,
    column: str,
    kind: RosSliceKind,
) -> list[RosSliceMask]:
    values = sorted({str(value) for value in frame.get_column(column).to_list()})
    return [RosSliceMask(slice_id, kind, value, pl.col(column) == value) for value in values]


def ros_slice_masks(frame: pl.DataFrame) -> list[RosSliceMask]:
    """Turn the declarations into executable masks over an evaluation frame.

    The declaration carries its predicate as text so the report is legible; the executable
    form lives here, keyed by slice id, so nothing evaluates a string. A slice that cannot be
    written as a typed expression over feature-side metadata is not a slice this project
    reports.
    """
    masks: list[RosSliceMask] = []
    for declaration in PREDECLARED_ROS_SLICES:
        slice_id, kind = declaration.slice_id, declaration.kind
        if slice_id == "full_universe":
            masks.append(RosSliceMask(slice_id, kind, "all", pl.lit(True)))
        elif slice_id == "position":
            masks.extend(_grouped(frame, slice_id, "position", kind))
        elif slice_id == "scoring_preset":
            masks.extend(_grouped(frame, slice_id, "scoring_preset", kind))
        elif slice_id == "season_phase":
            week = pl.col("through_week")
            masks.extend(
                [
                    RosSliceMask(slice_id, kind, "weeks_1_3", week <= EARLY_SEASON_LAST_WEEK),
                    RosSliceMask(
                        slice_id,
                        kind,
                        "weeks_4_9",
                        (week > EARLY_SEASON_LAST_WEEK) & (week <= MID_SEASON_LAST_WEEK),
                    ),
                    RosSliceMask(slice_id, kind, "weeks_10_plus", week > MID_SEASON_LAST_WEEK),
                ],
            )
        elif slice_id == "rookie":
            masks.append(
                RosSliceMask(slice_id, kind, "rookie", pl.col("rookie_flag").fill_null(False)),
            )
        elif slice_id == "veteran":
            masks.append(
                RosSliceMask(slice_id, kind, "veteran", ~pl.col("rookie_flag").fill_null(False)),
            )
        elif slice_id == "games_played_band":
            games = pl.col("games_to_date")
            masks.extend(
                [
                    RosSliceMask(slice_id, kind, "no_games", games == 0),
                    RosSliceMask(slice_id, kind, "one_or_two_games", (games >= 1) & (games <= 2)),
                    RosSliceMask(slice_id, kind, "three_plus_games", games >= 3),
                ],
            )
        elif slice_id == "returning_from_absence":
            masks.append(
                RosSliceMask(
                    slice_id,
                    kind,
                    "returning",
                    pl.col("has_played_this_season")
                    & (pl.col("consecutive_weeks_missed") >= RETURN_ABSENCE_WEEKS),
                ),
            )
        elif slice_id == "changed_team_in_season":
            masks.append(
                RosSliceMask(slice_id, kind, "changed_team", pl.col("team_changed_in_season")),
            )
        elif slice_id == "in_season_arrival":
            masks.append(
                RosSliceMask(slice_id, kind, "arrival", ~pl.col("in_preseason_universe")),
            )
        elif slice_id == "high_capital_underperforming":
            masks.append(
                RosSliceMask(
                    slice_id,
                    kind,
                    "high_capital_underperforming",
                    (pl.col("draft_overall").fill_null(10_000) <= HIGH_DRAFT_CAPITAL_PICK)
                    & (pl.col("games_to_date") >= 3)
                    & (pl.col("points_per_week_to_date") < POOR_FORM_POINTS_PER_WEEK),
                ),
            )
        elif slice_id == "high_capital_rookie":
            masks.append(
                RosSliceMask(
                    slice_id,
                    kind,
                    "high_capital_rookie",
                    pl.col("rookie_flag").fill_null(False)
                    & (pl.col("draft_overall").fill_null(10_000) <= HIGH_DRAFT_CAPITAL_PICK),
                ),
            )
        elif slice_id == "extreme_uncertainty":
            width = pl.col("baseline_interval_width")
            masks.append(
                RosSliceMask(
                    slice_id,
                    kind,
                    "widest_decile",
                    width
                    >= width.quantile(EXTREME_UNCERTAINTY_QUANTILE).over(
                        "season",
                        "through_week",
                        "position",
                        "scoring_preset",
                    ),
                ),
            )
        else:  # pragma: no cover - a declaration without an implementation is a bug
            raise KeyError(f"predeclared ROS slice {slice_id!r} has no executable mask")
    return masks


def ros_holdout_policy(*, status: str = "UNTOUCHED / NOT EVALUATED") -> dict[str, Any]:
    """The machine-readable declaration written into every ROS experiment report."""
    return {
        "sealed_season": ROS_SEALED_SEASON,
        "sealed_rule": ROS_SEALED_SEASONS,
        "status": status,
        "unseal_requires": [
            "--final-eval",
            f"--confirm-final-eval {ROS_FINAL_EVAL_CONFIRMATION_TOKEN}",
        ],
        "primary_result": "full_universe",
        "prior_exposure": (
            "2025 was opened once, in Phase 4, as the preseason model's final holdout. No "
            "rest-of-season snapshot, label or metric from it has been examined. Season "
            "totals correlate with rest-of-season totals, so the result is strong but not "
            "fully naive evidence (ADR-069)."
        ),
        "slices": [item.to_dict() for item in PREDECLARED_ROS_SLICES],
        "declared_before_candidate_comparison": True,
    }


def ros_slice_ids(kind: RosSliceKind | None = None) -> Sequence[str]:
    return tuple(
        item.slice_id for item in PREDECLARED_ROS_SLICES if kind is None or item.kind is kind
    )
