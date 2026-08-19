"""Fantasy scoring tests.

Every component of `config/league-defaults.yaml` gets a hand-worked case, because the
scoring engine is the definition of the target variable: an error here is invisible in every
downstream metric and makes every model comparison meaningless.
"""

from __future__ import annotations

import polars as pl
import pytest

from ffdraft.config import ScoringPreset, load_league_config
from ffdraft.scoring import (
    STAT_COMPONENTS,
    StatLine,
    fantasy_horizon,
    horizon_weeks,
    is_in_horizon,
    points_expression,
    reconcile_with_upstream,
    regular_season_weeks,
    score_stat_line,
    score_weekly_frame,
    season_totals,
)


@pytest.fixture(scope="module")
def scoring(repo_root):
    return load_league_config(repo_root / "config" / "league-defaults.yaml").scoring


def score(line: StatLine, scoring, preset: ScoringPreset) -> float:
    return score_stat_line(line, scoring[preset])


# --------------------------------------------------------------------------------------
# Components
# --------------------------------------------------------------------------------------


def test_passing_yards_score_one_point_per_twenty_five(scoring):
    assert score(StatLine(passing_yards=250), scoring, ScoringPreset.PPR) == pytest.approx(10.0)


def test_passing_touchdowns_score_four(scoring):
    assert score(StatLine(passing_tds=3), scoring, ScoringPreset.STD) == pytest.approx(12.0)


def test_interceptions_cost_two(scoring):
    assert score(StatLine(interceptions=2), scoring, ScoringPreset.STD) == pytest.approx(-4.0)


def test_rushing_yards_score_one_point_per_ten(scoring):
    assert score(StatLine(rushing_yards=87), scoring, ScoringPreset.STD) == pytest.approx(8.7)


def test_rushing_and_receiving_touchdowns_score_six(scoring):
    line = StatLine(rushing_tds=1, receiving_tds=2)
    assert score(line, scoring, ScoringPreset.STD) == pytest.approx(18.0)


def test_receiving_yards_score_one_point_per_ten(scoring):
    assert score(StatLine(receiving_yards=134), scoring, ScoringPreset.HALF) == pytest.approx(13.4)


def test_lost_fumbles_cost_two(scoring):
    assert score(StatLine(fumbles_lost=3), scoring, ScoringPreset.PPR) == pytest.approx(-6.0)


def test_two_point_conversions_score_two(scoring):
    line = StatLine(two_point_conversions=2)
    assert score(line, scoring, ScoringPreset.STD) == pytest.approx(4.0)


@pytest.mark.parametrize(
    ("preset", "expected"),
    [(ScoringPreset.STD, 0.0), (ScoringPreset.HALF, 4.0), (ScoringPreset.PPR, 8.0)],
)
def test_receptions_are_the_only_difference_between_presets(scoring, preset, expected):
    assert score(StatLine(receptions=8), scoring, preset) == pytest.approx(expected)


def test_half_ppr_is_exactly_the_mean_of_standard_and_full_ppr(scoring):
    line = StatLine(
        passing_yards=310,
        passing_tds=2,
        interceptions=1,
        rushing_yards=22,
        rushing_tds=1,
        receptions=9,
        receiving_yards=101,
        receiving_tds=1,
        fumbles_lost=1,
        two_point_conversions=1,
    )
    std = score(line, scoring, ScoringPreset.STD)
    ppr = score(line, scoring, ScoringPreset.PPR)
    half = score(line, scoring, ScoringPreset.HALF)
    assert half == pytest.approx((std + ppr) / 2)


def test_a_mixed_stat_player_sums_every_component(scoring):
    """A quarterback who also runs and catches: 14.6 + 8 - 2 + 3.5 + 6 + 2 + 4.2 + 2 = 38.3 PPR."""
    line = StatLine(
        passing_yards=365,
        passing_tds=2,
        interceptions=1,
        rushing_yards=35,
        rushing_tds=1,
        receptions=2,
        receiving_yards=42,
        two_point_conversions=1,
    )
    assert score(line, scoring, ScoringPreset.PPR) == pytest.approx(38.3)


def test_stat_lines_add(scoring):
    first = StatLine(receptions=4, receiving_yards=50)
    second = StatLine(receptions=3, receiving_tds=1)
    assert score(first + second, scoring, ScoringPreset.PPR) == pytest.approx(
        score(first, scoring, ScoringPreset.PPR) + score(second, scoring, ScoringPreset.PPR),
    )


def test_scoring_is_deterministic(scoring):
    line = StatLine(receptions=7, receiving_yards=88, receiving_tds=1)
    values = {score(line, scoring, ScoringPreset.PPR) for _ in range(50)}
    assert len(values) == 1


# --------------------------------------------------------------------------------------
# Scalar and frame arithmetic must agree
# --------------------------------------------------------------------------------------

SAMPLE_LINES = [
    StatLine(passing_yards=280, passing_tds=2, interceptions=1),
    StatLine(rushing_yards=104, rushing_tds=1, fumbles_lost=1),
    StatLine(receptions=6, receiving_yards=71, receiving_tds=1),
    StatLine(two_point_conversions=1, receptions=1, receiving_yards=3),
    StatLine(),
]


def test_the_frame_expression_and_the_scalar_function_agree(scoring):
    frame = pl.DataFrame([line.to_dict() for line in SAMPLE_LINES])
    for rules in scoring.values():
        column = frame.select(points_expression(rules).alias("points")).get_column("points")
        expected = [score_stat_line(line, rules) for line in SAMPLE_LINES]
        assert column.to_list() == pytest.approx(expected)


def test_a_frame_missing_a_component_is_rejected(scoring):
    frame = pl.DataFrame({name: [0.0] for name in STAT_COMPONENTS if name != "fumbles_lost"})
    with pytest.raises(ValueError, match="missing scorable components"):
        score_weekly_frame(frame, scoring)


# --------------------------------------------------------------------------------------
# Horizon
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("season", "weeks", "last", "excluded"),
    [(2019, 17, 16, 17), (2020, 17, 16, 17), (2021, 18, 17, 18), (2025, 18, 17, 18)],
)
def test_the_horizon_excludes_the_final_regular_season_week(season, weeks, last, excluded):
    horizon = fantasy_horizon(season)
    assert regular_season_weeks(season) == weeks
    assert horizon.last_week == last
    assert horizon.excluded_week == excluded
    assert horizon_weeks(season)[-1] == last


def test_postseason_rows_are_never_in_the_horizon():
    assert is_in_horizon(2024, 5) is True
    assert is_in_horizon(2024, 5, season_type="POST") is False
    assert is_in_horizon(2024, 18) is False


def _weekly(rows: list[dict[str, object]]) -> pl.DataFrame:
    defaults = {name: 0.0 for name in STAT_COMPONENTS}
    return pl.DataFrame(
        [
            {"season": 2024, "season_type": "REG", "gsis_id": "gsis", **defaults, **row}
            for row in rows
        ],
    )


def test_the_excluded_week_is_dropped_from_season_totals(scoring):
    weekly = _weekly(
        [
            {"week": 1, "receptions": 5, "receiving_yards": 50},
            {"week": 17, "receptions": 5, "receiving_yards": 50},
            {"week": 18, "receptions": 99, "receiving_yards": 999},
        ],
    )
    totals = season_totals(weekly, scoring)
    row = totals.to_dicts()[0]
    assert row["actual_games_played"] == 2
    assert row["receptions"] == pytest.approx(10.0)
    assert row["last_scored_week"] == 17
    assert row["fantasy_points_PPR"] == pytest.approx(20.0)


def test_postseason_rows_are_dropped_from_season_totals(scoring):
    weekly = _weekly(
        [
            {"week": 1, "receiving_yards": 100},
            {"week": 20, "season_type": "POST", "receiving_yards": 500},
        ],
    )
    totals = season_totals(weekly, scoring)
    assert totals.to_dicts()[0]["receiving_yards"] == pytest.approx(100.0)


def test_a_pre_2021_season_stops_at_week_sixteen(scoring):
    weekly = pl.DataFrame(
        [
            {
                "season": 2019,
                "season_type": "REG",
                "gsis_id": "gsis",
                "week": week,
                **{name: 0.0 for name in STAT_COMPONENTS},
                "receiving_yards": 10.0,
            }
            for week in (1, 16, 17)
        ],
    )
    totals = season_totals(weekly, scoring)
    assert totals.to_dicts()[0]["actual_games_played"] == 2
    assert totals.to_dicts()[0]["last_scored_week"] == 16


# --------------------------------------------------------------------------------------
# Upstream reconciliation
# --------------------------------------------------------------------------------------


def test_reconciliation_passes_when_only_return_touchdowns_differ(scoring):
    weekly = _weekly([{"week": 1, "receiving_yards": 50, "receptions": 4}]).with_columns(
        pl.lit(5.0).alias("upstream_fantasy_points_std"),
        pl.lit(9.0).alias("upstream_fantasy_points_ppr"),
        pl.lit(0.0).alias("upstream_special_teams_tds"),
    )
    checks = reconcile_with_upstream(weekly, scoring)
    assert all(check.check_id == "scoring.upstream_agreement" for check in checks)

    with_return_td = weekly.with_columns(
        pl.lit(11.0).alias("upstream_fantasy_points_std"),
        pl.lit(15.0).alias("upstream_fantasy_points_ppr"),
        pl.lit(1.0).alias("upstream_special_teams_tds"),
    )
    assert all(
        check.check_id == "scoring.upstream_agreement"
        for check in reconcile_with_upstream(with_return_td, scoring)
    )


def test_reconciliation_warns_when_a_component_changes_meaning(scoring):
    """Return touchdowns explain a six-point gap; nothing explains a fifty-point one."""
    weekly = _weekly([{"week": 1, "receiving_yards": 50, "receptions": 4}]).with_columns(
        pl.lit(55.0).alias("upstream_fantasy_points_std"),
        pl.lit(59.0).alias("upstream_fantasy_points_ppr"),
        pl.lit(0.0).alias("upstream_special_teams_tds"),
    )
    checks = reconcile_with_upstream(weekly, scoring)
    disagreements = [check for check in checks if check.check_id == "scoring.upstream_disagreement"]
    assert disagreements
    # Our engine stays authoritative, so this can never block a build.
    assert not any(check.blocking for check in disagreements)


def test_a_missing_upstream_column_is_reported_rather_than_ignored(scoring):
    weekly = _weekly([{"week": 1, "receiving_yards": 50}])
    checks = reconcile_with_upstream(weekly, scoring)
    assert all(check.check_id == "scoring.upstream_column_absent" for check in checks)
