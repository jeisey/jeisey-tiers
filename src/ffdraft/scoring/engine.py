"""The fantasy scoring engine.

`docs/DATA_CONTRACTS.md` section 5: "Define fantasy scoring in one module with tests. Do not
duplicate scoring formulas across notebooks/model code." This is that module, and it is the
only place in the repository that turns football statistics into fantasy points.

Two rules shape it.

**Points are computed from stat components, never taken from upstream.** nflverse publishes
``fantasy_points``/``fantasy_points_ppr``, but those cover the full regular season, and the
project's horizon excludes the final NFL week (:mod:`ffdraft.scoring.horizon`). A season
total that includes week 18 is a different label from the one this project defines, so the
upstream columns can only ever be a *sanity comparison* - :func:`reconcile_with_upstream`
does exactly that, and nothing depends on its result.

**Half-PPR is the exact mean of standard and full PPR.** Every rule in
`config/league-defaults.yaml` is identical across the three presets except ``reception``
(0.0 / 0.5 / 1.0), so ``HALF = (STD + PPR) / 2`` holds arithmetically. That is asserted in
the tests and is why the feature table can carry two prior-production columns rather than
three.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import cast

import polars as pl

from ffdraft.config import ScoringPreset, ScoringRules
from ffdraft.contracts import QualityCheck
from ffdraft.contracts.enums import Severity
from ffdraft.scoring.horizon import fantasy_horizon

__all__ = [
    "RETURN_TOUCHDOWN_POINTS",
    "SCORING_ENGINE_VERSION",
    "STAT_COMPONENTS",
    "StatLine",
    "points_expression",
    "reconcile_with_upstream",
    "score_stat_line",
    "score_weekly_frame",
    "season_totals",
]

#: Bump when the arithmetic changes. Model cards record it alongside the label definition.
SCORING_ENGINE_VERSION = "scoring_v1"

#: Points a return touchdown is worth *to nflverse*. `config/league-defaults.yaml` declares
#: no return-touchdown rule, so this project's presets score them at zero; nflverse's own
#: ``fantasy_points`` awards six. That is the entire difference between the two, and
#: :func:`reconcile_with_upstream` uses this constant to prove it is the entire difference
#: rather than leaving a vague mismatch that could hide a real component change.
RETURN_TOUCHDOWN_POINTS = 6.0

#: The statistical components a fantasy point total is built from. Anything not listed here
#: scores zero, by construction rather than by omission: return touchdowns, kicking and
#: defensive scoring are not part of the QB/RB/WR/TE contract in
#: `config/league-defaults.yaml`, so they must not silently enter a label.
STAT_COMPONENTS: tuple[str, ...] = (
    "passing_yards",
    "passing_tds",
    "interceptions",
    "rushing_yards",
    "rushing_tds",
    "receptions",
    "receiving_yards",
    "receiving_tds",
    "fumbles_lost",
    "two_point_conversions",
)


@dataclass(frozen=True, slots=True)
class StatLine:
    """One player's scorable production over any period (a week, a season, a fixture row)."""

    passing_yards: float = 0.0
    passing_tds: float = 0.0
    interceptions: float = 0.0
    rushing_yards: float = 0.0
    rushing_tds: float = 0.0
    receptions: float = 0.0
    receiving_yards: float = 0.0
    receiving_tds: float = 0.0
    fumbles_lost: float = 0.0
    two_point_conversions: float = 0.0

    def to_dict(self) -> dict[str, float]:
        return {name: float(getattr(self, name)) for name in STAT_COMPONENTS}

    def __add__(self, other: StatLine) -> StatLine:
        return StatLine(
            **{name: getattr(self, name) + getattr(other, name) for name in STAT_COMPONENTS},
        )


def score_stat_line(line: StatLine, rules: ScoringRules) -> float:
    """Fantasy points for one stat line under one preset's rules.

    Yardage rules are *yards per point* divisors as written in the YAML (25 passing yards
    per point), so they divide rather than multiply.
    """
    return (
        line.passing_yards / rules.passing_yards_per_point
        + line.passing_tds * rules.passing_td
        + line.interceptions * rules.interception
        + line.rushing_yards / rules.rushing_yards_per_point
        + line.rushing_tds * rules.rushing_td
        + line.receptions * rules.reception
        + line.receiving_yards / rules.receiving_yards_per_point
        + line.receiving_tds * rules.receiving_td
        + line.fumbles_lost * rules.fumble_lost
        + line.two_point_conversions * rules.two_point_conversion
    )


def points_expression(rules: ScoringRules) -> pl.Expr:
    """The same arithmetic as :func:`score_stat_line`, as a Polars expression.

    Both forms exist because the scalar version is what a hand-worked test reads, and the
    frame version is what a 300,000-row historical build needs. A test asserts they agree
    on every fixture row, so the duplication cannot drift into two different scoring systems.
    """
    column = {name: pl.col(name).cast(pl.Float64).fill_null(0.0) for name in STAT_COMPONENTS}
    return (
        column["passing_yards"] / rules.passing_yards_per_point
        + column["passing_tds"] * rules.passing_td
        + column["interceptions"] * rules.interception
        + column["rushing_yards"] / rules.rushing_yards_per_point
        + column["rushing_tds"] * rules.rushing_td
        + column["receptions"] * rules.reception
        + column["receiving_yards"] / rules.receiving_yards_per_point
        + column["receiving_tds"] * rules.receiving_td
        + column["fumbles_lost"] * rules.fumble_lost
        + column["two_point_conversions"] * rules.two_point_conversion
    )


def score_weekly_frame(
    weekly: pl.DataFrame,
    scoring: Mapping[ScoringPreset, ScoringRules],
) -> pl.DataFrame:
    """Add one ``fantasy_points_<preset>`` column per scoring preset.

    ``weekly`` must already carry the :data:`STAT_COMPONENTS` columns; the weekly-stats
    adapter is what maps nflverse's names onto them.
    """
    missing = [name for name in STAT_COMPONENTS if name not in weekly.columns]
    if missing:
        raise ValueError(f"weekly frame is missing scorable components: {missing}")
    return weekly.with_columns(
        [
            points_expression(rules).alias(f"fantasy_points_{preset}")
            for preset, rules in sorted(scoring.items())
        ],
    )


def season_totals(
    weekly: pl.DataFrame,
    scoring: Mapping[ScoringPreset, ScoringRules],
    *,
    key: Sequence[str] = ("season", "gsis_id"),
) -> pl.DataFrame:
    """Aggregate scored weekly rows into per-key season totals over the fantasy horizon.

    Rows outside the horizon are dropped here rather than by the caller, so no code path can
    produce a season total that quietly includes the excluded final NFL week.
    """
    scored = score_weekly_frame(weekly, scoring)
    horizons = {
        season: fantasy_horizon(season) for season in scored.get_column("season").unique().to_list()
    }
    in_horizon = pl.lit(False)
    for season, horizon in horizons.items():
        in_horizon = in_horizon | (
            (pl.col("season") == season)
            & (pl.col("week") >= horizon.first_week)
            & (pl.col("week") <= horizon.last_week)
        )
    filtered = scored.filter((pl.col("season_type") == "REG") & in_horizon)

    point_columns = [f"fantasy_points_{preset}" for preset in sorted(scoring)]
    aggregations: list[pl.Expr] = [
        pl.col(name).sum().alias(name) for name in (*STAT_COMPONENTS, *point_columns)
    ]
    aggregations.append(pl.len().cast(pl.Int32).alias("actual_games_played"))
    aggregations.append(pl.col("week").min().cast(pl.Int32).alias("first_scored_week"))
    aggregations.append(pl.col("week").max().cast(pl.Int32).alias("last_scored_week"))
    return filtered.group_by(list(key)).agg(aggregations).sort(list(key))


def reconcile_with_upstream(
    weekly: pl.DataFrame,
    scoring: Mapping[ScoringPreset, ScoringRules],
    *,
    tolerance: float = 0.02,
    stage: str = "scoring",
) -> list[QualityCheck]:
    """Compare our week-level STD/PPR totals against nflverse's own columns.

    This is a **sanity check, never a source of truth**. nflverse's ``fantasy_points`` uses
    the same standard formula this project's STD preset encodes, so a systematic divergence
    means one of us changed - most likely a renamed or re-meaninged upstream component,
    which is precisely the semantic drift a column-presence check cannot see.

    A mismatch is a warning rather than a failure: legitimate reasons exist (an upstream
    scoring tweak, a preset edit in `config/league-defaults.yaml`), and the authoritative
    label is ours either way. What must not happen is the divergence going unnoticed.
    """
    pairs = [
        (ScoringPreset.STD, "upstream_fantasy_points_std"),
        (ScoringPreset.PPR, "upstream_fantasy_points_ppr"),
    ]
    checks: list[QualityCheck] = []
    scored = score_weekly_frame(weekly, scoring)
    return_tds = (
        pl.col("upstream_special_teams_tds").cast(pl.Float64).fill_null(0.0)
        if "upstream_special_teams_tds" in scored.columns
        else pl.lit(0.0)
    )
    for preset, upstream in pairs:
        if upstream not in scored.columns:
            checks.append(
                QualityCheck.fail(
                    "scoring.upstream_column_absent",
                    stage=stage,
                    message=f"{upstream} is no longer published; the sanity check is blind",
                    observed=upstream,
                    expected="present",
                    severity=Severity.WARNING,
                ),
            )
            continue
        raw_delta = pl.col(f"fantasy_points_{preset}") - pl.col(upstream).cast(pl.Float64)
        comparison = scored.select(
            raw_delta.abs().alias("delta"),
            (raw_delta + return_tds * RETURN_TOUCHDOWN_POINTS).abs().alias("residual"),
        ).drop_nulls()
        if comparison.is_empty():
            continue
        worst = cast(float, comparison.get_column("delta").max() or 0.0)
        explained = int(comparison.filter(pl.col("delta") > tolerance).height)
        unexplained = int(comparison.filter(pl.col("residual") > tolerance).height)
        worst_residual = cast(float, comparison.get_column("residual").max() or 0.0)
        if unexplained:
            checks.append(
                QualityCheck.fail(
                    "scoring.upstream_disagreement",
                    stage=stage,
                    message=(
                        f"our {preset} weekly points differ from nflverse {upstream} by more "
                        "than return touchdowns explain; our engine remains authoritative, "
                        "but a component has changed meaning"
                    ),
                    observed=(
                        f"{unexplained} unexplained row(s), max residual {worst_residual:.4f}"
                    ),
                    expected=f"|residual| <= {tolerance}",
                    severity=Severity.WARNING,
                ),
            )
        else:
            checks.append(
                QualityCheck.ok(
                    "scoring.upstream_agreement",
                    stage=stage,
                    message=(
                        f"{preset} weekly points reconcile with nflverse {upstream} once "
                        "return touchdowns are accounted for"
                    ),
                    observed=(
                        f"{comparison.height} row(s); {explained} differ by a return "
                        f"touchdown (max delta {worst:.4f}), 0 otherwise"
                    ),
                ),
            )
    return checks
