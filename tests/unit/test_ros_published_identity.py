"""ADR-097: every published rest-of-season row has a real name, and a team where one is known.

Measured on the 2026 week-3 build before the fix: four in-season arrivals printed as the
string ``"None"`` and 69 rows per preset had no team, 17 of them on an active roster.
"""

from __future__ import annotations

import polars as pl

from ffdraft.pipeline.ros import fill_published_identity
from ffdraft.quality import QualityGate


def _context() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "player_id": [
                "gsis:00-A",  # named and placed: untouched
                "gsis:00-B",  # in-season arrival: no preseason name
                "gsis:00-C",  # only the player master knows him
                "gsis:00-D",  # nobody knows him
                "gsis:00-E",  # traded: on two roster rows
            ],
            "display_name": ["Kept Name", None, None, None, None],
            "team": ["BUF", None, None, None, None],
            "team_remaining_scheduled_games": [9.0, None, None, None, None],
        },
    )


def _weekly() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "season": [2025, 2026, 2026],
            "week": [17, 2, 3],
            "gsis_id": ["00-B", "00-B", "00-B"],
            "display_name": ["Old Spelling", "B. Arrival", "Bo Arrival"],
        },
    )


def _roster() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "gsis_id": ["00-A", "00-B", "00-E", "00-E"],
            "display_name": ["Roster A", "Roster B", "Roster E", "Roster E"],
            "team": ["MIA", "KC", "NYJ", "DAL"],
        },
    )


def _master() -> pl.DataFrame:
    return pl.DataFrame({"gsis_id": ["00-C", "00-B"], "display_name": ["Master C", "Master B"]})


def _filled(gate: QualityGate | None = None) -> dict[str, dict[str, object]]:
    frame = fill_published_identity(
        _context(),
        weekly=_weekly(),
        roster=_roster(),
        player_master=_master(),
        season=2026,
        gate=gate or QualityGate(),
    )
    return {row["player_id"]: row for row in frame.iter_rows(named=True)}


def test_a_known_name_and_team_are_never_overwritten() -> None:
    row = _filled()["gsis:00-A"]
    assert row["display_name"] == "Kept Name"
    assert row["team"] == "BUF"


def test_this_seasons_latest_weekly_name_beats_the_roster_and_the_master() -> None:
    row = _filled()["gsis:00-B"]
    assert row["display_name"] == "Bo Arrival"
    assert row["team"] == "KC"


def test_the_player_master_is_the_last_named_fallback() -> None:
    assert _filled()["gsis:00-C"]["display_name"] == "Master C"


def test_nobody_is_ever_published_as_none() -> None:
    rows = _filled()
    assert rows["gsis:00-D"]["display_name"] == "gsis:00-D"
    assert all(row["display_name"] not in (None, "None") for row in rows.values())


def test_a_player_on_two_clubs_is_not_placed_by_guess() -> None:
    assert _filled()["gsis:00-E"]["team"] is None


def test_the_model_input_column_is_untouched() -> None:
    """Annotation only: the one team-derived model input stays exactly as the snapshot had it."""
    before = _context().get_column("team_remaining_scheduled_games")
    after = fill_published_identity(
        _context(),
        weekly=_weekly(),
        roster=_roster(),
        player_master=_master(),
        season=2026,
        gate=QualityGate(),
    ).get_column("team_remaining_scheduled_games")
    assert before.equals(after)


def test_the_gate_records_what_was_filled() -> None:
    gate = QualityGate()
    _filled(gate)
    check = next(check for check in gate.checks if check.check_id == "ros.published_identity")
    assert (
        check.observed
        == "3 name(s) filled, 1 left as the player id; 1 team(s) filled from the roster; "
        "0 row(s) whose club the employment reading settled (ADR-102)"
    )


def test_employment_settles_the_club_for_off_roster_players_only() -> None:
    """ADR-102: a released, unsigned player's last club (`team_to_date`) is not his current
    one; a signing only Sleeper has reported names the new club; rostered rows are untouched.
    """
    from ffdraft.status.employment import (
        Employment,
        EmploymentResult,
        EmploymentSource,
        EmploymentStatus,
    )

    context = pl.DataFrame(
        {
            "player_id": ["gsis:00-A", "gsis:00-F", "gsis:00-G"],
            "display_name": ["Kept Name", "Released Unsigned", "Signed Late"],
            "team": ["BUF", "MIA", None],
            "team_remaining_scheduled_games": [9.0, 9.0, None],
        },
    )
    employment = EmploymentResult(
        readings={
            "gsis:00-A": Employment(
                "gsis:00-A", EmploymentStatus.SIGNED, "MIA", EmploymentSource.NFLVERSE_ROSTER, None
            ),
            "gsis:00-F": Employment(
                "gsis:00-F", EmploymentStatus.UNSIGNED, None, EmploymentSource.SLEEPER, None
            ),
            "gsis:00-G": Employment(
                "gsis:00-G", EmploymentStatus.SIGNED, "SEA", EmploymentSource.SLEEPER, None
            ),
        },
        sleeper_fresh=True,
    )
    frame = fill_published_identity(
        context,
        weekly=_weekly(),
        roster=_roster(),
        player_master=_master(),
        season=2026,
        gate=QualityGate(),
        employment=employment,
    )
    rows = {row["player_id"]: row for row in frame.iter_rows(named=True)}
    assert rows["gsis:00-A"]["team"] == "BUF"  # roster-signed: the existing rule, unchanged
    assert rows["gsis:00-F"]["team"] is None
    assert rows["gsis:00-G"]["team"] == "SEA"
    # Annotation only: the model input column is exactly the snapshot's.
    assert frame.get_column("team_remaining_scheduled_games").equals(
        context.get_column("team_remaining_scheduled_games"),
    )
