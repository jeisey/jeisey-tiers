"""The weekly point-in-time leakage audit.

Phase 2 proves its leakage rules constructively: it rebuilds every season with that season's
own statistics deleted and asserts the feature table is unchanged. Phase 11 needs the same
kind of proof at a finer grain, because its features deliberately *do* read the target
season - just not past the cutoff.

The audit here is the same argument, one week at a time:

**Delete the future and rebuild.** For a snapshot through week N, throw away every weekly row
after week N, rebuild the in-season feature block from what is left, and compare it with the
block the full build produced for that same snapshot. Any feature that reached forward - a
mis-signed shift, a window that included its own endpoint plus one, a forward fill that ran
the wrong way - produces a different number and fails the check. A feature that is genuinely
a function of weeks 1..N is bit-identical.

**Then delete the future and check the label went to zero.** The same truncated panel must
produce ``actual_remaining_games == 0`` and ``actual_remaining_points == 0`` for every row at
that cutoff, because the label is defined over exactly the weeks that were deleted. This is
the complementary half: the first check proves features do not read the future, the second
proves the label reads nothing else.

Both are cheap enough to run on a sample of cutoffs in a production build and exhaustively in
the test suite over a fixture.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import polars as pl

from ffdraft.config import ScoringPreset, ScoringRules
from ffdraft.contracts import QualityCheck
from ffdraft.contracts.enums import Severity
from ffdraft.modeling.preprocessing import scalar_float
from ffdraft.quality import audit_intrinsic_feature_names
from ffdraft.ros.cutoff import RosCutoff, season_cutoffs
from ffdraft.ros.dictionary import ros_feature_names, ros_in_season_features
from ffdraft.ros.features import build_in_season_features
from ffdraft.ros.labels import build_ros_labels
from ffdraft.ros.panel import build_weekly_panel

__all__ = [
    "DEFAULT_AUDIT_WEEKS",
    "audit_cutoff_independence",
    "audit_ros_feature_names",
    "audit_to_date_monotonicity",
    "sample_cutoffs",
]

#: Weeks a production build audits per season. One before the first byes, one at midseason
#: and one late: the three regimes the cumulative windows behave differently in.
DEFAULT_AUDIT_WEEKS: tuple[int, ...] = (3, 8, 13)

_STAGE = "ros_leakage"


def sample_cutoffs(
    seasons: Sequence[int],
    weeks: Sequence[int] = DEFAULT_AUDIT_WEEKS,
) -> list[RosCutoff]:
    """The cutoffs a sampled audit checks: the declared weeks that exist in each season."""
    wanted = set(int(week) for week in weeks)
    return [
        cutoff
        for season in sorted({int(season) for season in seasons})
        for cutoff in season_cutoffs(season)
        if cutoff.through_week in wanted
    ]


def audit_ros_feature_names(stage: str = _STAGE) -> list[QualityCheck]:
    """The intrinsic firewall, applied to the Phase-11 model input list.

    Same audit the preseason build runs, over a different list. A market signal entering the
    rest-of-season model would fail the build rather than a code review (ADR-002).
    """
    return list(audit_intrinsic_feature_names(ros_feature_names(), stage=stage))


def audit_cutoff_independence(
    weekly: pl.DataFrame,
    scoring: Mapping[ScoringPreset, ScoringRules],
    *,
    universe: pl.DataFrame,
    cutoffs: Sequence[RosCutoff],
    snap_counts: pl.DataFrame | None = None,
    expected_points: pl.DataFrame | None = None,
    schedule: pl.DataFrame | None = None,
    stage: str = _STAGE,
) -> list[QualityCheck]:
    """Rebuild each sampled snapshot with its future deleted and compare.

    The comparison is over the **in-season feature block only**: the preseason block comes
    from Phase 2, whose own independence proof already covers it, and the cutoff block is a
    function of the snapshot key alone.
    """
    if not cutoffs:
        return [
            QualityCheck.ok(
                "ros_leakage.cutoff_independence",
                stage=stage,
                message="no cutoff was sampled",
                observed="cutoffs=0",
            ),
        ]
    checks: list[QualityCheck] = []
    compared = [spec.name for spec in ros_in_season_features() if spec.family != "cutoff"]
    seasons = sorted({cutoff.season for cutoff in cutoffs})

    full_panel = build_weekly_panel(
        weekly,
        scoring,
        seasons=seasons,
        universe=universe,
        snap_counts=snap_counts,
        expected_points=expected_points,
    )
    full_features = build_in_season_features(
        full_panel,
        scoring,
        schedule=schedule,
        universe=universe,
    )

    mismatched: list[str] = []
    leaked_labels: list[str] = []
    for cutoff in cutoffs:
        truncated_weekly = weekly.filter(
            (pl.col("season") != cutoff.season) | (pl.col("week") <= cutoff.through_week),
        )
        truncated_panel = build_weekly_panel(
            truncated_weekly,
            scoring,
            seasons=[cutoff.season],
            universe=universe,
            snap_counts=snap_counts,
            expected_points=expected_points,
        )
        rebuilt = build_in_season_features(
            truncated_panel,
            scoring,
            schedule=schedule,
            universe=universe,
        ).filter(pl.col("through_week") == cutoff.through_week)
        original = full_features.filter(
            (pl.col("season") == cutoff.season) & (pl.col("through_week") == cutoff.through_week),
        )
        keys = ["season", "through_week", "gsis_id", "scoring_preset"]
        columns = [name for name in compared if name in rebuilt.columns]
        left = original.select(*keys, *columns).sort(keys)
        right = rebuilt.select(*keys, *columns).sort(keys)
        if left.height != right.height:
            mismatched.append(
                f"{cutoff.snapshot_id}: {left.height} row(s) become {right.height}",
            )
        elif not left.equals(right):
            differing = [
                name
                for name in columns
                if not left.get_column(name).equals(right.get_column(name), null_equal=True)
            ]
            mismatched.append(f"{cutoff.snapshot_id}: {differing}")

        labels = build_ros_labels(truncated_panel, scoring).filter(
            pl.col("through_week") == cutoff.through_week,
        )
        if labels.height:
            worst_games = scalar_float(labels.get_column("actual_remaining_games").abs().max())
            worst_points = scalar_float(labels.get_column("actual_remaining_points").abs().max())
            if worst_games or worst_points > 1e-9:
                leaked_labels.append(
                    f"{cutoff.snapshot_id}: games={worst_games:.0f}, points={worst_points:.4f}",
                )

    if mismatched:
        checks.append(
            QualityCheck.fail(
                "ros_leakage.feature_reads_after_cutoff",
                stage=stage,
                message=(
                    "an in-season feature changed when the weeks after its own cutoff were "
                    "deleted, so it was reading them"
                ),
                observed="; ".join(mismatched[:5]),
                expected="every in-season feature identical after truncation",
                severity=Severity.CRITICAL,
            ),
        )
    else:
        checks.append(
            QualityCheck.ok(
                "ros_leakage.cutoff_independence",
                stage=stage,
                message=("every sampled snapshot rebuilt identically with its future deleted"),
                observed=f"{len(cutoffs)} cutoff(s), {len(compared)} in-season column(s)",
            ),
        )
    if leaked_labels:
        checks.append(
            QualityCheck.fail(
                "ros_leakage.label_survives_truncation",
                stage=stage,
                message=(
                    "a rest-of-season label was non-zero after the weeks it sums over were "
                    "deleted, so it is reading weeks at or before the cutoff"
                ),
                observed="; ".join(leaked_labels[:5]),
                expected="zero remaining games and points once the future is deleted",
                severity=Severity.CRITICAL,
            ),
        )
    else:
        checks.append(
            QualityCheck.ok(
                "ros_leakage.label_window",
                stage=stage,
                message="every sampled label went to zero once its own weeks were deleted",
                observed=f"{len(cutoffs)} cutoff(s)",
            ),
        )
    return checks


def audit_to_date_monotonicity(frame: pl.DataFrame, stage: str = _STAGE) -> list[QualityCheck]:
    """Appearances to date can only grow as the cutoff advances.

    A cheap invariant with a lot of coverage: a windowing bug that shifts by one, resets at a
    bye, or re-sorts a player-season breaks it immediately.
    """
    if frame.is_empty() or "games_to_date" not in frame.columns:
        return []
    ordered = frame.sort("season", "scoring_preset", "player_id", "through_week")
    offenders = ordered.filter(
        pl.col("games_to_date")
        < pl.col("games_to_date").shift(1).over("season", "scoring_preset", "player_id"),
    )
    if offenders.height:
        return [
            QualityCheck.fail(
                "ros_leakage.games_to_date_not_monotone",
                stage=stage,
                message="appearances to date fell as the cutoff advanced",
                observed=f"{offenders.height} row(s)",
                expected="non-decreasing within a player-season",
                severity=Severity.CRITICAL,
            ),
        ]
    return [
        QualityCheck.ok(
            "ros_leakage.games_to_date_monotone",
            stage=stage,
            message="appearances to date never fall as the cutoff advances",
            observed=f"{frame.height} row(s)",
        ),
    ]
