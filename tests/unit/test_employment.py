"""Unsigned NFL players stay identifiable, and a previous club is never a current one (ADR-102).

The 2026-10-06 trace: Tyreek Hill (released in February, unsigned since) and Joe Mixon
(signed by Seattle on 2026-10-05, not yet on nflverse's 2026 roster) were the fifth- and
tenth-most-added players on Sleeper and invisible in-season, because every annotation-side
registry was built from `load_rosters(2026)` alone. These tests pin the rule that replaced it,
``employment_evidence_v1``, on synthetic players: identity from this season's roster plus the
previous season's as identity only; employment from the roster, then a fresh Sleeper record.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import polars as pl
import pytest

from ffdraft.behavior.history import sleeper_to_canonical
from ffdraft.identity.ids import IdNamespace
from ffdraft.identity.registry import LookupStatus
from ffdraft.opportunity.board import (
    SURFACE_ADD_COUNT_MINIMUM,
    BehaviorSignals,
    build_opportunity_records,
    resolve_behavior_signals,
)
from ffdraft.quality import QualityGate
from ffdraft.signals.usage import current_teams_from_roster
from ffdraft.sources.nflverse import NflversePlayersAdapter, NflverseRosterAdapter
from ffdraft.status.build import build_player_status_records
from ffdraft.status.capture import StatusCapture
from ffdraft.status.employment import (
    EMPLOYMENT_MAX_AGE_HOURS,
    EmploymentSource,
    EmploymentStatus,
    build_identity_registry,
    current_teams_with_employment,
    employment_catalog,
    identity_spine,
    resolve_employment,
)

SEASON = 2026
NOW = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)


def _row(
    gsis: str,
    name: str,
    *,
    season: int,
    team: str | None,
    status: str | None,
    sleeper: str | None,
    position: str = "WR",
) -> dict[str, Any]:
    return {
        "season": season,
        "gsis_id": gsis,
        "full_name": name,
        "position": position,
        "team": team,
        "status": status,
        "depth_chart_position": position,
        "espn_id": f"9{gsis[-6:]}",
        "sleeper_id": sleeper,
        "pfr_id": None,
        "sportradar_id": None,
        "yahoo_id": None,
        "birth_date": None,
        "years_exp": 9,
        "rookie_year": season - 9,
    }


def _roster(rows: list[dict[str, Any]], season: int) -> pl.DataFrame:
    return NflverseRosterAdapter().normalize(rows, season=season, retrieved_at=NOW).frame


def _sleeper(
    pid: str, *, team: str | None, status: str = "Active", gsis: str | None = None
) -> dict[str, Any]:
    return {
        "source_id": "sleeper",
        "external_player_id": pid,
        "observed_at_utc": NOW.isoformat(),
        "team": team,
        "status": status,
        "injury_status": None,
        "injury_body_part": None,
        "injury_notes": None,
        "injury_start_date": None,
        "practice_participation": None,
        "practice_description": None,
        "depth_chart_position": None,
        "depth_chart_order": None,
        "reported_gsis_id": gsis,
        "quality_flags": "",
    }


def _capture(rows: list[dict[str, Any]], *, observed: datetime = NOW) -> StatusCapture:
    return StatusCapture(
        source_id="sleeper",
        season=SEASON,
        snapshot_key="k",
        observed_at_utc=observed,
        adapter_version="1.1",
        source_policy_version="test",
        rows=[{**row, "observed_at_utc": observed.isoformat()} for row in rows],
    )


#: On this season's roster.
ROSTERED = _row(
    "00-0000001", "Terry Rostered", season=SEASON, team="WAS", status="ACT", sleeper="5000001"
)
#: A veteran released in the spring: last season's roster only, with his old club.
UNSIGNED_PRIOR = _row(
    "00-0000002", "Vince Veteran", season=SEASON - 1, team="MIA", status="RES", sleeper="5000002"
)
#: Signed after the roster file was cut.
SIGNED_LATE_PRIOR = _row(
    "00-0000003",
    "Sid Latesign",
    season=SEASON - 1,
    team="HOU",
    status="RES",
    sleeper="5000003",
    position="RB",
)


def _employment(
    current: list[dict[str, Any]],
    prior: list[dict[str, Any]],
    sleeper: list[dict[str, Any]] | None,
    *,
    observed: datetime = NOW,
):
    roster = _roster(current, SEASON)
    registry = build_identity_registry(roster, [_roster(prior, SEASON - 1)])
    capture = None if sleeper is None else _capture(sleeper, observed=observed)
    return (
        registry,
        roster,
        resolve_employment(
            registry=registry,
            current_roster=roster,
            capture=capture,
            as_of=NOW,
        ),
    )


def test_an_unsigned_veteran_from_last_season_is_identified_and_unsigned() -> None:
    """last_season = the previous season is how an unsigned veteran looks, not retirement."""
    registry, _, employment = _employment(
        [ROSTERED],
        [UNSIGNED_PRIOR],
        [_sleeper("5000001", team="WAS"), _sleeper("5000002", team=None, gsis="00-0000002")],
    )
    reading = employment.get("gsis:00-0000002")
    assert reading is not None
    assert reading.status is EmploymentStatus.UNSIGNED
    assert reading.source is EmploymentSource.SLEEPER
    assert reading.team is None
    # The historical crosswalk verified who he is; it did not say where he plays.
    assert registry.lookup(IdNamespace.SLEEPER, "5000002").player_id == "gsis:00-0000002"
    assert registry.get("gsis:00-0000002").team is None  # type: ignore[union-attr]
    assert employment_catalog(employment) == ["gsis:00-0000002"]


def test_a_stale_previous_club_never_becomes_the_current_one() -> None:
    """The prior roster's MIA and the player master's latest_team are history, not employment."""
    _, roster, employment = _employment(
        [ROSTERED],
        [UNSIGNED_PRIOR],
        [_sleeper("5000002", team=None)],
    )
    teams = current_teams_with_employment(current_teams_from_roster(roster), employment)
    assert "gsis:00-0000002" in teams and teams["gsis:00-0000002"] is None
    # The player master's own reading of him — latest_team MIA, last_season 2025 — is dropped
    # by the market supplement and reaches nothing here.
    master = NflversePlayersAdapter().normalize(
        [
            {
                "gsis_id": "00-0000002",
                "display_name": "Vince Veteran",
                "position": "WR",
                "latest_team": "MIA",
                "status": "RES",
                "last_season": SEASON - 1,
                "espn_id": "9000002",
            },
        ],
        season=SEASON,
        retrieved_at=NOW,
    )
    assert master.frame.is_empty()
    assert master.metadata.detail["players_rows_before_target_season"] == "1"


def test_a_null_team_with_no_current_evidence_is_unknown_not_fa() -> None:
    """No Sleeper record for him: we do not know, so nothing may print "FA"."""
    _, _, employment = _employment([ROSTERED], [UNSIGNED_PRIOR], [_sleeper("5000001", team="WAS")])
    reading = employment.get("gsis:00-0000002")
    assert reading is not None and reading.status is EmploymentStatus.UNKNOWN
    assert employment_catalog(employment) == []


def test_identity_needs_a_crosswalk_the_spine_carries() -> None:
    """Absent from the current roster, present (with his Sleeper id) on last season's."""
    spine = identity_spine(_roster([ROSTERED], SEASON), [_roster([UNSIGNED_PRIOR], SEASON - 1)])
    prior = spine.filter(pl.col("gsis_id") == "00-0000002").row(0, named=True)
    assert prior["sleeper_id"] == "5000002"
    assert prior["team"] is None and prior["status"] is None
    # A player on both rosters keeps his current row only.
    moved = _row(
        "00-0000001",
        "Terry Rostered",
        season=SEASON - 1,
        team="SEA",
        status="ACT",
        sleeper="5000001",
    )
    spine = identity_spine(_roster([ROSTERED], SEASON), [_roster([moved], SEASON - 1)])
    assert spine.filter(pl.col("gsis_id") == "00-0000001").get_column("team").to_list() == ["WAS"]


def test_an_unsigned_player_without_a_projection_is_an_unprojected_row() -> None:
    """Trending, verified unsigned, on no board: identity, club and adds; every number null."""
    registry, _, employment = _employment(
        [ROSTERED],
        [UNSIGNED_PRIOR],
        [_sleeper("5000002", team=None)],
    )
    signals = BehaviorSignals(
        available=True,
        source_id="sleeper",
        snapshot_at_utc=NOW,
        lookback_hours=24,
        request_limit=100,
        add_counts={"gsis:00-0000002": SURFACE_ADD_COUNT_MINIMUM + 1},
        drop_counts={},
    )
    gate = QualityGate()
    rows, _, diagnostics = build_opportunity_records(
        ros_records=[],
        full_board=[
            {
                "player_id": "gsis:00-0000001",
                "fair_rank": 1,
                "position_rank": 1,
                "display_name": "Terry Rostered",
                "position": "WR",
                "team": "WAS",
                "scoring_preset": "PPR",
                "league_preset_id": "redraft-12",
                "expected_vorp": 1.0,
                "p50_vorp": 1.0,
                "uncertainty": 1.0,
                "expected_points": 1.0,
                "expected_games": 1.0,
            },
        ],
        context={},
        signals=signals,
        build_id="b",
        season=SEASON,
        through_week=4,
        gate=gate,
        employment=employment.readings,
        catalog={
            pid: {"display_name": p.display_name, "position": str(p.position)}
            for pid, p in registry.players.items()
        },
    )
    unprojected = [row for row in rows if row["model_coverage"] == "unprojected"]
    assert diagnostics["unprojected_rows"] == 1
    assert len(unprojected) == 1
    row = unprojected[0]
    assert row["player_id"] == "gsis:00-0000002"
    assert row["employment_status"] == "unsigned" and row["team"] is None
    assert row["add_count"] == SURFACE_ADD_COUNT_MINIMUM + 1
    for field in (
        "ros_fair_rank",
        "ros_position_rank",
        "ros_expected_vorp",
        "ros_vorp_p50",
        "ros_expected_points",
        "ros_expected_games",
        "ros_uncertainty",
        "ros_tier",
    ):
        assert row[field] is None, field
    # Below the bar he is not surfaced: the population is bounded by the feed.
    quiet = BehaviorSignals(**{**signals.__dict__, "add_counts": {"gsis:00-0000002": 10}})
    rows, _, _ = build_opportunity_records(
        ros_records=[],
        full_board=[],
        context={},
        signals=quiet,
        build_id="b",
        season=SEASON,
        through_week=4,
        gate=QualityGate(),
        employment=employment.readings,
        catalog={"gsis:00-0000002": {"display_name": "Vince Veteran", "position": "WR"}},
    )
    assert rows == []


def test_a_signing_updates_the_same_player_on_refresh() -> None:
    """FA -> signed (Sleeper first, then the roster file): one canonical id throughout."""
    prior = [UNSIGNED_PRIOR, SIGNED_LATE_PRIOR]
    _, _, day_one = _employment([ROSTERED], prior, [_sleeper("5000003", team=None)])
    assert day_one.get("gsis:00-0000003").status is EmploymentStatus.UNSIGNED  # type: ignore[union-attr]

    _, _, day_two = _employment([ROSTERED], prior, [_sleeper("5000003", team="SEA")])
    signed = day_two.get("gsis:00-0000003")
    assert signed is not None
    assert (signed.status, signed.team, signed.source) == (
        EmploymentStatus.SIGNED,
        "SEA",
        EmploymentSource.SLEEPER,
    )

    on_file = _row(
        "00-0000003",
        "Sid Latesign",
        season=SEASON,
        team="SEA",
        status="DEV",
        sleeper="5000003",
        position="RB",
    )
    _, _, day_three = _employment([ROSTERED, on_file], prior, [_sleeper("5000003", team="SEA")])
    settled = day_three.get("gsis:00-0000003")
    assert settled is not None
    assert (settled.team, settled.source) == ("SEA", EmploymentSource.NFLVERSE_ROSTER)
    # The stale FA label and the old club (HOU) are both gone; the id never changed.
    assert "gsis:00-0000003" not in employment_catalog(day_three)


def test_the_official_roster_wins_and_a_disagreement_is_recorded() -> None:
    _, _, employment = _employment([ROSTERED], [], [_sleeper("5000001", team=None)])
    reading = employment.get("gsis:00-0000001")
    assert reading is not None
    assert (reading.status, reading.team) == (EmploymentStatus.SIGNED, "WAS")
    assert reading.sources_disagree


def test_a_retired_player_is_never_catalogued() -> None:
    retired_now = _row(
        "00-0000004", "Rex Retired", season=SEASON, team=None, status="RET", sleeper="5000004"
    )
    inactive_prior = _row(
        "00-0000005", "Ian Inactive", season=SEASON - 1, team="NYJ", status="ACT", sleeper="5000005"
    )
    _, _, employment = _employment(
        [ROSTERED, retired_now],
        [inactive_prior],
        [_sleeper("5000004", team=None), _sleeper("5000005", team=None, status="Inactive")],
    )
    assert employment.get("gsis:00-0000004").status is EmploymentStatus.RETIRED  # type: ignore[union-attr]
    # Sleeper's "Inactive" with no club is not evidence of free agency either.
    assert employment.get("gsis:00-0000005").status is EmploymentStatus.UNKNOWN  # type: ignore[union-attr]
    assert employment_catalog(employment) == []


def test_an_ambiguous_sleeper_id_fails_closed_everywhere() -> None:
    """Two canonical players claiming one sleeper_id across seasons: neither gets the record."""
    clash = _row(
        "00-0000006", "Cal Clash", season=SEASON - 1, team="DAL", status="ACT", sleeper="5000001"
    )
    registry, _, employment = _employment(
        [ROSTERED],
        [clash],
        [_sleeper("5000001", team=None)],
    )
    assert registry.lookup(IdNamespace.SLEEPER, "5000001").status is LookupStatus.AMBIGUOUS
    assert employment.ambiguous_ids == 2
    assert employment.get("gsis:00-0000006").status is EmploymentStatus.UNKNOWN  # type: ignore[union-attr]
    assert "5000001" not in sleeper_to_canonical(registry)
    # The rostered player keeps his roster reading; no Sleeper data reaches either.
    assert employment.get("gsis:00-0000001").status is EmploymentStatus.SIGNED  # type: ignore[union-attr]
    assert not employment.get("gsis:00-0000001").sources_disagree  # type: ignore[union-attr]


@pytest.mark.parametrize(
    "observed",
    [None, NOW - timedelta(hours=EMPLOYMENT_MAX_AGE_HOURS + 1), NOW + timedelta(hours=3)],
    ids=["missing feed", "stale feed", "capture from the future"],
)
def test_a_missing_or_stale_feed_calls_nobody_unsigned(observed: datetime | None) -> None:
    sleeper = None if observed is None else [_sleeper("5000002", team=None)]
    _, _, employment = _employment(
        [ROSTERED],
        [UNSIGNED_PRIOR],
        sleeper,
        observed=observed or NOW,
    )
    assert employment.get("gsis:00-0000002").status is EmploymentStatus.UNKNOWN  # type: ignore[union-attr]
    assert employment.get("gsis:00-0000001").status is EmploymentStatus.SIGNED  # type: ignore[union-attr]
    assert not employment.sleeper_fresh
    check = employment.check(stage="test")
    assert check.check_id == "employment.sleeper_not_current" and not check.blocking


def test_the_status_row_prints_fa_from_evidence_and_add_history_joins() -> None:
    """End to end on the annotation side: status row, club, and the behaviour join."""
    registry, roster, employment = _employment(
        [ROSTERED],
        [UNSIGNED_PRIOR],
        [_sleeper("5000002", team=None)],
    )
    result = build_player_status_records(
        registry=registry,
        roster=roster,
        capture=_capture([_sleeper("5000002", team=None)]),
        build_id="b",
        season=SEASON,
        generated_at=NOW,
        player_ids=["gsis:00-0000002"],
        employment=employment,
    )
    (record,) = result.records
    assert record["current_team"] is None
    assert record["employment_status"] == "unsigned"
    assert record["employment_source"] == "sleeper"
    assert record["sleeper_status"] == "Active"

    # His adds reach him now that the identity spine knows his Sleeper id (Hill's real
    # 2026-10-06 counts, on a synthetic player).
    from ffdraft.behavior.capture import BehaviorCapture

    capture = BehaviorCapture(
        source_id="sleeper",
        season=SEASON,
        snapshot_key="k",
        observed_at_utc=NOW,
        adapter_version="1.0",
        source_policy_version="test",
        rows=[
            {"external_player_id": "5000002", "behavior_type": "add", "count": 660_496, "rank": 5},
            {"external_player_id": "5000002", "behavior_type": "drop", "count": 52_880, "rank": 58},
        ],
    )
    signals = resolve_behavior_signals(capture, registry=registry, as_of=NOW)
    assert signals.add_counts["gsis:00-0000002"] == 660_496
    assert signals.drop_counts["gsis:00-0000002"] == 52_880
    assert signals.unresolved_rows == 0
    # The roster-only registry the builds used before ADR-102 could not reach him.
    from ffdraft.identity.registry import build_registry

    before = resolve_behavior_signals(capture, registry=build_registry(roster), as_of=NOW)
    assert "gsis:00-0000002" not in before.add_counts and before.unresolved_rows == 2
