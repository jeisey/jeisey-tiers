"""Semantic and data-domain check tests.

Phase 1 proved a *structural* break is detectable: a column an adapter reads disappears and
the build stops. The failure this file is about is different and quieter - the columns are
all present, the dtypes are all right, and the *values* stop meaning what they meant. Every
test here builds exactly that: a frame that would pass every Phase-1 check and still be
wrong.
"""

from __future__ import annotations

import polars as pl
import pytest

from ffdraft.contracts.enums import CheckStatus, Severity
from ffdraft.quality import semantic


def failing(checks) -> list[str]:
    return [check.check_id for check in checks if check.status is CheckStatus.FAIL]


# --------------------------------------------------------------------------------------
# Categorical domain
# --------------------------------------------------------------------------------------


def test_a_new_position_code_is_caught():
    frame = pl.DataFrame({"position": ["QB", "RB", "FB"]})
    checks = semantic.check_categorical_domain(
        frame,
        column="position",
        allowed=("QB", "RB", "WR", "TE"),
        stage="test",
    )
    assert failing(checks) == ["semantic.categorical_domain"]
    assert "FB" in checks[0].observed


def test_a_clean_vocabulary_passes():
    frame = pl.DataFrame({"position": ["QB", "RB", "WR", "TE"]})
    checks = semantic.check_categorical_domain(
        frame,
        column="position",
        allowed=("QB", "RB", "WR", "TE"),
        stage="test",
    )
    assert not failing(checks)


def test_nulls_are_a_domain_violation_unless_explicitly_allowed():
    frame = pl.DataFrame({"position": ["QB", None]})
    strict = semantic.check_categorical_domain(
        frame,
        column="position",
        allowed=("QB",),
        stage="test",
    )
    lenient = semantic.check_categorical_domain(
        frame,
        column="position",
        allowed=("QB",),
        stage="test",
        allow_null=True,
    )
    assert failing(strict)
    assert not failing(lenient)


def test_an_absent_column_cannot_be_checked_and_says_so():
    checks = semantic.check_categorical_domain(
        pl.DataFrame({"other": [1]}),
        column="position",
        allowed=("QB",),
        stage="test",
    )
    assert failing(checks) == ["semantic.column_absent"]


# --------------------------------------------------------------------------------------
# The unit-change failure: a share that starts arriving as a percentage
# --------------------------------------------------------------------------------------


def test_a_share_published_as_a_percentage_is_caught():
    """The columns still exist, the dtype is still Float64, only the unit changed.

    This is the canonical semantic drift a structural check cannot see: 82.0 is a perfectly
    valid float in a column that is supposed to hold 0.82.
    """
    frame = pl.DataFrame({"prev1_snap_share": [0.82, 0.55, 82.0]})
    checks = semantic.check_bounded_share(frame, columns=("prev1_snap_share",), stage="test")
    assert failing(checks) == ["semantic.share_out_of_unit_interval"]
    assert "82" in checks[0].observed


def test_shares_inside_the_unit_interval_pass():
    frame = pl.DataFrame({"a": [0.0, 0.5, 1.0], "b": [None, 0.25, 0.75]})
    assert not failing(semantic.check_bounded_share(frame, columns=("a", "b"), stage="test"))


def test_a_sign_convention_flip_shows_up_as_a_negative_count():
    frame = pl.DataFrame({"prev1_games": [16, 15, -3]})
    checks = semantic.check_non_negative(frame, columns=("prev1_games",), stage="test")
    assert failing(checks) == ["semantic.negative_count"]


def test_a_value_outside_its_plausible_range_is_caught():
    frame = pl.DataFrame({"combine_forty": [4.32, 4.55, 12.0]})
    checks = semantic.check_numeric_bounds(
        frame,
        column="combine_forty",
        minimum=4.0,
        maximum=6.5,
        stage="test",
    )
    assert failing(checks) == ["semantic.numeric_out_of_range"]


def test_a_value_below_the_minimum_is_also_caught():
    frame = pl.DataFrame({"draft_round": [1, 0]})
    checks = semantic.check_numeric_bounds(
        frame,
        column="draft_round",
        minimum=1,
        maximum=7,
        stage="test",
    )
    assert failing(checks) == ["semantic.numeric_out_of_range"]


# --------------------------------------------------------------------------------------
# Derived-ratio sanity
# --------------------------------------------------------------------------------------


def test_a_ratio_computed_on_too_small_a_denominator_is_caught():
    frame = pl.DataFrame(
        {
            "prev1_yards_per_carry": [4.3, 14.0],
            "prev1_carries": [180.0, 1.0],
        },
    )
    checks = semantic.check_ratio_denominator(
        frame,
        ratio="prev1_yards_per_carry",
        denominator="prev1_carries",
        minimum=20,
        stage="test",
    )
    assert failing(checks) == ["semantic.ratio_below_minimum_denominator"]


def test_a_ratio_null_below_its_minimum_passes():
    frame = pl.DataFrame(
        {"prev1_yards_per_carry": [4.3, None], "prev1_carries": [180.0, 1.0]},
    )
    checks = semantic.check_ratio_denominator(
        frame,
        ratio="prev1_yards_per_carry",
        denominator="prev1_carries",
        minimum=20,
        stage="test",
    )
    assert not failing(checks)


# --------------------------------------------------------------------------------------
# Season / week and career consistency
# --------------------------------------------------------------------------------------


def test_an_impossible_week_for_its_season_is_caught():
    frame = pl.DataFrame({"season": [2019, 2019], "week": [17, 18]})
    checks = semantic.check_season_week_consistency(
        frame,
        stage="test",
        max_week_by_season={2019: 17},
    )
    assert failing(checks) == ["semantic.season_week_inconsistent"]


def test_a_season_with_no_declared_week_count_is_reported():
    frame = pl.DataFrame({"season": [2019, 2030], "week": [5, 5]})
    checks = semantic.check_season_week_consistency(
        frame,
        stage="test",
        max_week_by_season={2019: 17},
    )
    assert failing(checks)
    assert "2030" in checks[0].observed


@pytest.mark.parametrize(
    ("row", "expected"),
    [
        ({"season": 2020, "draft_year": 2021}, True),
        (
            {"season": 2020, "draft_year": 2018, "experience_years": 5, "seasons_since_draft": 2},
            True,
        ),
        ({"season": 2020, "rookie_flag": True, "experience_years": 4}, True),
        ({"season": 2020, "age_at_anchor": 9.0}, True),
        (
            {"season": 2020, "draft_year": 2018, "experience_years": 2, "seasons_since_draft": 2},
            False,
        ),
    ],
)
def test_impossible_career_combinations_are_caught(row, expected):
    base = {
        "season": 2020,
        "draft_year": None,
        "experience_years": 0,
        "seasons_since_draft": None,
        "rookie_flag": False,
        "age_at_anchor": 25.0,
    }
    frame = pl.DataFrame([{**base, **row}])
    checks = semantic.check_age_experience_draft_consistency(frame, stage="test")
    assert bool(failing(checks)) is expected


# --------------------------------------------------------------------------------------
# Missingness and row counts
# --------------------------------------------------------------------------------------


def test_a_column_that_has_gone_mostly_null_is_flagged():
    frame = pl.DataFrame({"prev1_snap_share": [None, None, None, 0.5]})
    checks = semantic.check_missingness(
        frame,
        column="prev1_snap_share",
        max_null_rate=0.5,
        stage="test",
    )
    assert failing(checks) == ["semantic.missingness_above_budget"]
    assert checks[0].severity is Severity.WARNING


def test_missingness_inside_its_budget_passes():
    frame = pl.DataFrame({"a": [1.0, 2.0, None, 4.0]})
    assert not failing(semantic.check_missingness(frame, column="a", max_null_rate=0.5, stage="t"))


def test_a_season_whose_source_returned_a_fraction_of_its_rows_is_flagged():
    counts = {2020: 1000, 2021: 1010, 2022: 990, 2023: 120}
    checks = semantic.check_row_count_stability(counts, stage="test", tolerance=0.35)
    assert failing(checks) == ["semantic.row_count_anomaly"]
    assert "2023" in checks[0].observed


def test_stable_row_counts_pass():
    counts = {2020: 1000, 2021: 1010, 2022: 990}
    assert not failing(semantic.check_row_count_stability(counts, stage="test"))


def test_too_few_seasons_to_have_a_median_is_not_an_anomaly():
    assert semantic.check_row_count_stability({2020: 10, 2021: 900}, stage="test") == []


# --------------------------------------------------------------------------------------
# Distribution summaries
# --------------------------------------------------------------------------------------


def test_distribution_summaries_are_informational_and_sliced():
    frame = pl.DataFrame(
        {
            "season": [2024, 2024, 2025, 2025],
            "position": ["WR", "WR", "WR", "WR"],
            "value": [1.0, 3.0, 10.0, 30.0],
        },
    )
    checks = semantic.describe_distribution(
        frame,
        column="value",
        by=("season", "position"),
        stage="test",
    )
    assert len(checks) == 1
    assert checks[0].status is CheckStatus.PASS
    assert "2024/WR" in checks[0].observed
    assert "2025/WR" in checks[0].observed


# --------------------------------------------------------------------------------------
# The composite case: a frame that passes every structural check and is still wrong
# --------------------------------------------------------------------------------------


def test_a_structurally_valid_frame_with_violated_semantics_is_detected():
    """Every column present, every dtype right, every key unique - and every value wrong.

    A snap share arriving as a percentage, a negative game count, a forty-yard dash of 12
    seconds, a position code nobody declared and a rookie with nine years of experience.
    A schema check sees none of it.
    """
    frame = pl.DataFrame(
        [
            {
                "season": 2024,
                "player_id": "gsis:00-0000001",
                "position": "FB",
                "prev1_snap_share": 91.0,
                "prev1_games": -2,
                "combine_forty": 12.0,
                "rookie_flag": True,
                "experience_years": 9,
                "seasons_since_draft": 1,
                "draft_year": 2023,
                "age_at_anchor": 24.0,
            },
        ],
    )
    checks = [
        *semantic.check_categorical_domain(
            frame,
            column="position",
            allowed=("QB", "RB", "WR", "TE"),
            stage="test",
        ),
        *semantic.check_bounded_share(frame, columns=("prev1_snap_share",), stage="test"),
        *semantic.check_non_negative(frame, columns=("prev1_games",), stage="test"),
        *semantic.check_numeric_bounds(
            frame,
            column="combine_forty",
            minimum=4.0,
            maximum=6.5,
            stage="test",
        ),
        *semantic.check_age_experience_draft_consistency(frame, stage="test"),
    ]
    assert sorted(failing(checks)) == [
        "semantic.career_fields_inconsistent",
        "semantic.categorical_domain",
        "semantic.negative_count",
        "semantic.numeric_out_of_range",
        "semantic.share_out_of_unit_interval",
    ]
    assert all(check.blocking for check in checks if check.status is CheckStatus.FAIL)
