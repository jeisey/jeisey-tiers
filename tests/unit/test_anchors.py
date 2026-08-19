"""Draft-time anchor tests (ADR-021).

The anchor is the single value every leakage argument in Phase 2 rests on, so these tests
attack it from the directions that actually break date logic: time zones, daylight saving,
an opener on an unusual weekday, and an opener on the anchor day itself.
"""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import polars as pl
import pytest

from ffdraft.anchors import (
    ANCHOR_TIMEZONE,
    DRAFT_ANCHOR_RULE_VERSION,
    AnchorError,
    Kickoff,
    SeasonAnchor,
    anchor_for_kickoff,
    anchors_to_frame,
    build_season_anchors,
    check_anchor_precedes_kickoff,
    first_week1_kickoff,
)

EASTERN = ZoneInfo(ANCHOR_TIMEZONE)


def kickoff(season: int, text: str, *, game_id: str = "GAME") -> Kickoff:
    naive = datetime.fromisoformat(text)
    return Kickoff(
        season=season,
        game_id=game_id,
        kickoff_local=naive.replace(tzinfo=EASTERN),
    )


# Real Week-1 openers. The expected anchors are the Tuesday before each, at 23:59:59
# Eastern, converted to UTC - which is 03:59:59 the following day while Eastern is on
# daylight time, and would be 04:59:59 on standard time.
HISTORICAL_OPENERS = [
    (2014, "2014-09-04T20:30", "2014-09-03T03:59:59Z"),
    (2016, "2016-09-08T20:30", "2016-09-07T03:59:59Z"),
    (2019, "2019-09-05T20:20", "2019-09-04T03:59:59Z"),
    (2021, "2021-09-09T20:20", "2021-09-08T03:59:59Z"),
    (2024, "2024-09-05T20:20", "2024-09-04T03:59:59Z"),
    (2025, "2025-09-04T20:20", "2025-09-03T03:59:59Z"),
    # 2012 and 2026 both opened on a Wednesday, which a "kickoff minus two days" shortcut
    # would get right by luck for Thursday openers and wrong here. Note the UTC date is the
    # day *after* the local anchor date, because 23:59:59 Eastern is the next morning in UTC.
    (2012, "2012-09-05T20:30", "2012-09-05T03:59:59Z"),
    (2026, "2026-09-09T20:20", "2026-09-09T03:59:59Z"),
]


@pytest.mark.parametrize(("season", "opener", "expected"), HISTORICAL_OPENERS)
def test_the_anchor_is_the_tuesday_before_the_opener(season, opener, expected):
    anchor = anchor_for_kickoff(kickoff(season, opener))
    assert anchor.anchor_at_utc == datetime.fromisoformat(expected.replace("Z", "+00:00"))
    assert anchor.anchor_local.tzinfo is not None
    assert anchor.anchor_date_local.weekday() == 1, "anchor day must be a Tuesday"


@pytest.mark.parametrize(("season", "opener", "_expected"), HISTORICAL_OPENERS)
def test_every_anchor_strictly_precedes_its_kickoff(season, opener, _expected):
    anchor = anchor_for_kickoff(kickoff(season, opener))
    assert anchor.anchor_at_utc < anchor.first_kickoff_utc


def test_the_anchor_is_expressed_in_the_league_time_zone_not_machine_local_time():
    anchor = anchor_for_kickoff(kickoff(2024, "2024-09-05T20:20"))
    assert str(anchor.anchor_local.tzinfo) == ANCHOR_TIMEZONE
    # 23:59:59 Eastern in early September is 03:59:59 UTC the next day. If the rule had used
    # machine-local time this offset would depend on where the build ran.
    assert anchor.anchor_at_utc.hour == 3
    assert anchor.anchor_at_utc.tzinfo is UTC
    assert (anchor.anchor_at_utc - anchor.anchor_local).total_seconds() == 0


def test_daylight_saving_changes_the_utc_offset_but_not_the_local_rule():
    """A hypothetical March opener falls inside a different DST regime.

    The rule is stated in local time, so the local instant is identical and only the UTC
    conversion moves. A fixed `-04:00` offset would silently produce the wrong instant.
    """
    september = anchor_for_kickoff(kickoff(2024, "2024-09-05T20:20"))
    march = anchor_for_kickoff(kickoff(2024, "2024-03-07T20:20"))
    assert september.anchor_local.time() == march.anchor_local.time()
    assert september.anchor_at_utc.hour == 3
    assert march.anchor_at_utc.hour == 4


def test_a_tuesday_opener_steps_back_a_full_week():
    """If the opener were a Tuesday evening, that Tuesday's end of day is too late."""
    anchor = anchor_for_kickoff(kickoff(2030, "2030-09-03T20:20"))
    assert anchor.anchor_date_local.isoformat() == "2030-08-27"
    assert anchor.anchor_date_local.weekday() == 1
    assert anchor.anchor_at_utc < anchor.first_kickoff_utc


def test_an_anchor_that_does_not_precede_kickoff_cannot_be_constructed():
    with pytest.raises(AnchorError, match="does not precede"):
        SeasonAnchor(
            season=2024,
            anchor_at_utc=datetime(2024, 9, 10, tzinfo=UTC),
            anchor_local=datetime(2024, 9, 10, tzinfo=EASTERN),
            rule_version=DRAFT_ANCHOR_RULE_VERSION,
            first_kickoff_utc=datetime(2024, 9, 5, tzinfo=UTC),
            first_kickoff_game_id="GAME",
        )


def test_a_naive_kickoff_is_rejected():
    naive = Kickoff(season=2024, game_id="G", kickoff_local=datetime(2024, 9, 5, 20, 20))
    with pytest.raises(AnchorError, match="timezone-aware"):
        anchor_for_kickoff(naive)


def test_every_anchor_records_the_versioned_rule():
    anchor = anchor_for_kickoff(kickoff(2024, "2024-09-05T20:20"))
    assert anchor.rule_version == DRAFT_ANCHOR_RULE_VERSION
    assert anchor.rule_version == "draft_anchor_v1_tuesday_eod_pre_week1"


# --------------------------------------------------------------------------------------
# Deriving the opener from a schedule
# --------------------------------------------------------------------------------------

SCHEDULE = pl.DataFrame(
    [
        # The Sunday games are listed first so the test proves the *earliest* kickoff wins
        # rather than the first row.
        ("2024_01_A_B", 2024, "REG", 1, "2024-09-08", "13:00", "A", "B"),
        ("2024_01_C_D", 2024, "REG", 1, "2024-09-05", "20:20", "C", "D"),
        ("2024_02_A_B", 2024, "REG", 2, "2024-09-15", "13:00", "A", "B"),
        ("2024_00_E_F", 2024, "PRE", 1, "2024-08-10", "19:00", "E", "F"),
        ("2025_01_G_H", 2025, "REG", 1, "2025-09-04", "20:20", "G", "H"),
    ],
    schema={
        "game_id": pl.String,
        "season": pl.Int32,
        "game_type": pl.String,
        "week": pl.Int32,
        "gameday": pl.String,
        "gametime": pl.String,
        "away_team": pl.String,
        "home_team": pl.String,
    },
    orient="row",
)


def test_the_earliest_week_one_regular_season_kickoff_is_chosen():
    found = first_week1_kickoff(SCHEDULE, 2024)
    assert found.game_id == "2024_01_C_D"
    assert found.kickoff_local.hour == 20


def test_preseason_and_later_weeks_are_ignored():
    found = first_week1_kickoff(SCHEDULE, 2024)
    assert found.kickoff_local.date().isoformat() == "2024-09-05"


def test_a_season_with_no_week_one_games_cannot_be_anchored():
    with pytest.raises(AnchorError, match="no week-1"):
        first_week1_kickoff(SCHEDULE, 1999)


def test_build_season_anchors_returns_one_anchor_per_season():
    anchors = build_season_anchors(SCHEDULE, [2024, 2025])
    assert sorted(anchors) == [2024, 2025]
    assert all(anchor.rule_version == DRAFT_ANCHOR_RULE_VERSION for anchor in anchors.values())


def test_the_precedence_check_reports_a_pass_and_flags_an_unusual_lead_time():
    anchors = build_season_anchors(SCHEDULE, [2024, 2025])
    checks = check_anchor_precedes_kickoff(anchors)
    assert any(check.check_id == "anchor.precedes_first_kickoff" for check in checks)
    assert not any(check.blocking for check in checks)

    stretched = {2030: anchor_for_kickoff(kickoff(2030, "2030-09-03T20:20"))}
    warnings = check_anchor_precedes_kickoff(stretched)
    assert any(check.check_id == "anchor.unusual_lead_time" for check in warnings)


def test_no_anchors_at_all_is_a_critical_finding():
    checks = check_anchor_precedes_kickoff({})
    assert checks[0].blocking


def test_anchors_render_to_a_typed_frame():
    frame = anchors_to_frame(build_season_anchors(SCHEDULE, [2024, 2025]))
    assert frame.height == 2
    assert frame.schema["anchor_at_utc"].time_zone == "UTC"
    assert frame.get_column("feature_cutoff_rule_version").unique().to_list() == [
        DRAFT_ANCHOR_RULE_VERSION,
    ]


def test_covers_answers_the_availability_question():
    anchor = anchor_for_kickoff(kickoff(2024, "2024-09-05T20:20"))
    before = datetime(2024, 9, 3, tzinfo=UTC)
    after = datetime(2024, 9, 5, tzinfo=UTC)
    assert anchor.covers(before) is True
    assert anchor.covers(after) is False
