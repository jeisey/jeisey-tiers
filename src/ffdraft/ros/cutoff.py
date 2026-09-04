"""The rest-of-season cutoff rule.

Phase 11's whole leakage argument rests on one sentence, and this module is that sentence
in code:

> A snapshot taken **through week N** of season Y may use every completed regular-season
> week ``1..N`` of season Y and every season strictly before Y, and nothing else. It
> predicts weeks ``N+1`` through the fantasy horizon's last week of season Y.

Three consequences are worth stating because each one is a decision rather than an
inevitability.

**The horizon is the project's existing one, unchanged.** :mod:`ffdraft.scoring.horizon`
already excludes the final NFL week from every label, and a rest-of-season label that
included it would be a different quantity from the preseason label it has to be comparable
with. So the remaining horizon ends where the preseason horizon ends.

**``through_week = 0`` is deliberately absent.** That snapshot is the preseason board, and
the preseason board is ``intrinsic-cb-hurdle-v1``'s job. Phase 11 answers "given the season
so far", which needs at least one completed week; a Phase-11 model asked for week 0 would be
a worse preseason model, not a rest-of-season one.

**The last modelled snapshot is ``last_week - 1``.** A snapshot through the final scored week
has an empty remaining horizon and no label to learn from. It is refused rather than emitted
with a zero target, because a row whose target is structurally zero teaches a model that the
season ends, which it already knows from ``remaining_horizon_weeks``.

The operational counterpart lives in `docs/OPERATIONS.md`: a production week-N snapshot may
only be built once the upstream weekly release covering week N exists, because the rule says
"week N is *available*", not "week N has been played".
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Any

from ffdraft.scoring.horizon import FantasyHorizon, fantasy_horizon

__all__ = [
    "ROS_CUTOFF_RULE",
    "ROS_CUTOFF_RULE_VERSION",
    "FIRST_THROUGH_WEEK",
    "RosCutoff",
    "cutoff_rule_document",
    "season_cutoffs",
]

#: Bump when the meaning of a snapshot changes. Model metadata and every written dataset
#: record it, so a stale dataset can never be mistaken for a current one.
ROS_CUTOFF_RULE_VERSION = "ros_cutoff_v1"

#: The earliest snapshot Phase 11 models. See the module docstring for why it is not zero.
FIRST_THROUGH_WEEK = 1

ROS_CUTOFF_RULE = (
    "A snapshot through week N of season Y may read completed regular-season weeks 1..N of "
    "season Y and any season strictly before Y. It predicts weeks N+1..horizon.last_week of "
    "season Y. Snapshots run from week 1 to horizon.last_week - 1 inclusive."
)


@dataclass(frozen=True, slots=True)
class RosCutoff:
    """One point-in-time snapshot key, and everything derivable from it alone."""

    season: int
    through_week: int

    def __post_init__(self) -> None:
        horizon = fantasy_horizon(self.season)
        if self.through_week < FIRST_THROUGH_WEEK:
            raise ValueError(
                f"through_week {self.through_week} is below {FIRST_THROUGH_WEEK}: a "
                "rest-of-season snapshot needs at least one completed week; week 0 is the "
                "preseason model's grain, not this one",
            )
        if self.through_week > horizon.last_week - 1:
            raise ValueError(
                f"through_week {self.through_week} leaves no remaining horizon in "
                f"{self.season} ({horizon.describe()}); the last modelled snapshot is "
                f"week {horizon.last_week - 1}",
            )

    @property
    def horizon(self) -> FantasyHorizon:
        return fantasy_horizon(self.season)

    @property
    def observed_weeks(self) -> tuple[int, ...]:
        """Weeks a feature may read. The empty-set complement of this is the leakage test."""
        return tuple(range(self.horizon.first_week, self.through_week + 1))

    @property
    def remaining_weeks(self) -> tuple[int, ...]:
        """Weeks the label sums over."""
        return tuple(range(self.through_week + 1, self.horizon.last_week + 1))

    @property
    def remaining_horizon_weeks(self) -> int:
        """Calendar weeks left in the scored horizon, byes included. Not games."""
        return self.horizon.last_week - self.through_week

    @property
    def observed_horizon_weeks(self) -> int:
        return self.through_week - self.horizon.first_week + 1

    @property
    def season_share_remaining(self) -> float:
        return self.remaining_horizon_weeks / self.horizon.week_count

    @property
    def snapshot_id(self) -> str:
        return f"{self.season}w{self.through_week:02d}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "season": self.season,
            "through_week": self.through_week,
            "observed_weeks": list(self.observed_weeks),
            "remaining_weeks": list(self.remaining_weeks),
            "remaining_horizon_weeks": self.remaining_horizon_weeks,
            "cutoff_rule_version": ROS_CUTOFF_RULE_VERSION,
        }


def season_cutoffs(season: int) -> tuple[RosCutoff, ...]:
    """Every modelled snapshot for one season, in week order."""
    horizon = fantasy_horizon(season)
    return tuple(
        RosCutoff(season=season, through_week=week)
        for week in range(FIRST_THROUGH_WEEK, horizon.last_week)
    )


def all_cutoffs(seasons: Sequence[int]) -> Iterator[RosCutoff]:
    for season in sorted(seasons):
        yield from season_cutoffs(season)


def cutoff_rule_document(seasons: Sequence[int] = ()) -> dict[str, Any]:
    """The machine-readable freeze, written into every ROS dataset and report."""
    return {
        "cutoff_rule_version": ROS_CUTOFF_RULE_VERSION,
        "rule": ROS_CUTOFF_RULE,
        "first_through_week": FIRST_THROUGH_WEEK,
        "excluded_snapshot": "through_week=0 (the preseason model's grain)",
        "horizon_source": "ffdraft.scoring.horizon.fantasy_horizon; unchanged from Release 1",
        "snapshots_per_season": {
            str(season): len(season_cutoffs(season)) for season in sorted(seasons)
        },
    }
