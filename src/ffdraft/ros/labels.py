"""Rest-of-season labels: what actually happened after the cutoff.

For a snapshot through week N of season Y, the label is the player's production over weeks
``N+1..horizon.last_week`` of season Y, in three parts the model can be judged on separately:

``actual_remaining_games``
    weeks after the cutoff in which the player appeared. This is the availability half.

``actual_remaining_ppg``
    fantasy points per appearance over those weeks, undefined (null) when there are none.
    This is the conditional-performance half.

``actual_remaining_points``
    their product, and the quantity a rest-of-season board is ultimately ranked on.

**A player who never plays again scores zero, not null.** Same rule as the preseason label
(:mod:`ffdraft.labels.fantasy`) and for the same reason: a season-ending injury in week 5 is
the outcome a rest-of-season model most needs to be able to be wrong about, and dropping the
row would train only on players who stayed healthy.

**Remaining is computed forward, then reconciled backward.** The sum runs over weeks
strictly greater than the cutoff; the builder then checks that ``through + remaining`` equals
the season total the existing scoring engine produces for the same player. The two paths
share the panel but not the arithmetic, so a cumulative-window bug shows up as a failed check
rather than as a plausible-looking number.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import polars as pl

from ffdraft.config import ScoringPreset, ScoringRules
from ffdraft.contracts import QualityCheck
from ffdraft.contracts.enums import Severity
from ffdraft.contracts.frames import ColumnSpec, FrameContract
from ffdraft.modeling.preprocessing import scalar_float
from ffdraft.ros.cutoff import FIRST_THROUGH_WEEK, ROS_CUTOFF_RULE_VERSION
from ffdraft.scoring.engine import SCORING_ENGINE_VERSION
from ffdraft.scoring.horizon import fantasy_horizon

__all__ = [
    "ROS_LABEL_CONTRACT",
    "ROS_LABEL_VERSION",
    "build_ros_labels",
    "cumulative_columns",
    "reconcile_ros_labels",
]

#: Bump when the label's definition changes. Recorded on every row.
ROS_LABEL_VERSION = "ros_label_v1"

_RECONCILIATION_TOLERANCE = 1e-6


ROS_LABEL_CONTRACT = FrameContract(
    contract_id="ros_labels",
    version="1.0",
    primary_key=("season", "through_week", "gsis_id", "scoring_preset"),
    columns=(
        ColumnSpec("season", pl.Int32, nullable=False),
        ColumnSpec("through_week", pl.Int32, nullable=False),
        ColumnSpec("gsis_id", pl.String, nullable=False),
        ColumnSpec("scoring_preset", pl.String, nullable=False),
        ColumnSpec("remaining_horizon_weeks", pl.Int32, nullable=False),
        ColumnSpec("actual_remaining_games", pl.Int32, nullable=False),
        ColumnSpec(
            "actual_remaining_points",
            pl.Float64,
            nullable=False,
            description="fantasy points over weeks after the cutoff; zero when never active",
        ),
        ColumnSpec(
            "actual_remaining_ppg",
            pl.Float64,
            description="points per remaining appearance; null when there are none",
        ),
        ColumnSpec("actual_games_to_date", pl.Int32, nullable=False),
        ColumnSpec("actual_points_to_date", pl.Float64, nullable=False),
        ColumnSpec("label_version", pl.String, nullable=False),
        ColumnSpec("cutoff_rule_version", pl.String, nullable=False),
        ColumnSpec("scoring_engine_version", pl.String, nullable=False),
    ),
)


def cumulative_columns(
    panel: pl.DataFrame,
    value_columns: Sequence[str],
    *,
    prefix_to_date: str = "to_date_",
    prefix_remaining: str = "remaining_",
) -> pl.DataFrame:
    """Attach through-cutoff and after-cutoff sums for each named column.

    ``to_date_x`` at week N sums weeks ``1..N``; ``remaining_x`` sums weeks ``N+1..last``.
    Both are computed on the dense panel, so a week the player missed contributes zero to
    both rather than shifting the window.
    """
    ordered = panel.sort("season", "gsis_id", "week")
    to_date = [
        pl.col(name).cum_sum().over("season", "gsis_id").alias(f"{prefix_to_date}{name}")
        for name in value_columns
    ]
    remaining = [
        pl.col(name)
        .cum_sum(reverse=True)
        .over("season", "gsis_id")
        .shift(-1)
        .over("season", "gsis_id")
        .fill_null(0.0)
        .alias(f"{prefix_remaining}{name}")
        for name in value_columns
    ]
    return ordered.with_columns([*to_date, *remaining])


def build_ros_labels(
    panel: pl.DataFrame,
    scoring: Mapping[ScoringPreset, ScoringRules],
) -> pl.DataFrame:
    """Build the ``(season, through_week, gsis_id, scoring_preset)`` label table."""
    if panel.is_empty():
        return ROS_LABEL_CONTRACT.empty()

    presets = sorted(scoring)
    point_columns = [f"fantasy_points_{preset}" for preset in presets]
    accumulated = cumulative_columns(panel, ["played", *point_columns])

    seasons = sorted({int(season) for season in accumulated.get_column("season").unique()})
    last_modelled = {season: fantasy_horizon(season).last_week - 1 for season in seasons}
    horizon_last = {season: fantasy_horizon(season).last_week for season in seasons}

    scoped = accumulated.filter(
        (pl.col("week") >= FIRST_THROUGH_WEEK)
        & (pl.col("week") <= pl.col("season").replace_strict(last_modelled, return_dtype=pl.Int32)),
    )

    frames: list[pl.DataFrame] = []
    for preset in presets:
        points = f"fantasy_points_{preset}"
        frames.append(
            scoped.select(
                pl.col("season"),
                pl.col("week").alias("through_week"),
                pl.col("gsis_id"),
                pl.lit(str(preset)).alias("scoring_preset"),
                (
                    pl.col("season").replace_strict(horizon_last, return_dtype=pl.Int32)
                    - pl.col("week")
                )
                .cast(pl.Int32)
                .alias("remaining_horizon_weeks"),
                pl.col("remaining_played").cast(pl.Int32).alias("actual_remaining_games"),
                pl.col(f"remaining_{points}").alias("actual_remaining_points"),
                pl.when(pl.col("remaining_played") > 0)
                .then(pl.col(f"remaining_{points}") / pl.col("remaining_played"))
                .otherwise(None)
                .alias("actual_remaining_ppg"),
                pl.col("to_date_played").cast(pl.Int32).alias("actual_games_to_date"),
                pl.col(f"to_date_{points}").alias("actual_points_to_date"),
                pl.lit(ROS_LABEL_VERSION).alias("label_version"),
                pl.lit(ROS_CUTOFF_RULE_VERSION).alias("cutoff_rule_version"),
                pl.lit(SCORING_ENGINE_VERSION).alias("scoring_engine_version"),
            ),
        )
    stacked = pl.concat(frames)
    return ROS_LABEL_CONTRACT.coerce(stacked).sort(
        "season",
        "through_week",
        "scoring_preset",
        "gsis_id",
    )


def reconcile_ros_labels(
    labels: pl.DataFrame,
    season_totals: pl.DataFrame,
    *,
    stage: str = "ros_labels",
) -> list[QualityCheck]:
    """Prove ``points through cutoff + points after cutoff == the season total``.

    ``season_totals`` is :func:`ffdraft.scoring.engine.season_totals` output keyed on
    ``(season, gsis_id)``, i.e. the number Release 1 already computes and publishes labels
    from. Agreement is what makes the rest-of-season label the *same* quantity, split.
    """
    if labels.is_empty():
        return [
            QualityCheck.ok(
                "ros_labels.reconciled",
                stage=stage,
                message="no label rows to reconcile",
                observed="rows=0",
            ),
        ]
    checks: list[QualityCheck] = []
    presets = sorted({str(value) for value in labels.get_column("scoring_preset").unique()})
    for preset in presets:
        column = f"fantasy_points_{preset}"
        if column not in season_totals.columns:
            checks.append(
                QualityCheck.fail(
                    "ros_labels.season_total_absent",
                    stage=stage,
                    message="a scoring preset has no season total to reconcile against",
                    observed=preset,
                    expected=f"{column} in season totals",
                ),
            )
            continue
        joined = (
            labels.filter(pl.col("scoring_preset") == preset)
            .join(
                season_totals.select("season", "gsis_id", column),
                on=["season", "gsis_id"],
                how="left",
            )
            .with_columns(pl.col(column).fill_null(0.0))
            .with_columns(
                (
                    pl.col("actual_points_to_date")
                    + pl.col("actual_remaining_points")
                    - pl.col(column)
                )
                .abs()
                .alias("delta"),
            )
        )
        worst = scalar_float(joined.get_column("delta").max(), 0.0)
        offenders = int(joined.filter(pl.col("delta") > _RECONCILIATION_TOLERANCE).height)
        if offenders:
            checks.append(
                QualityCheck.fail(
                    "ros_labels.split_does_not_reconcile",
                    stage=stage,
                    message=(
                        "through-cutoff plus after-cutoff points do not equal the season "
                        "total the scoring engine produces"
                    ),
                    observed=f"{preset}: {offenders} row(s), worst |delta| {worst:.6f}",
                    expected=f"|delta| <= {_RECONCILIATION_TOLERANCE}",
                    severity=Severity.CRITICAL,
                ),
            )
        else:
            checks.append(
                QualityCheck.ok(
                    "ros_labels.reconciled",
                    stage=stage,
                    message="the cutoff split reproduces the season total exactly",
                    observed=f"{preset}: {joined.height} row(s), worst |delta| {worst:.2e}",
                ),
            )
    return checks
