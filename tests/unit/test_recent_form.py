"""`recent_form_v1` windows and `breakout_v1` categories (ADR-113).

The claims the Opportunity Board leans on, each tested on its own:

* a window is the same **calendar weeks** for everyone, ending at the cutoff, and never reaches
  back past a bye or a missed game;
* window and weekly ranks are **competition ranks over every appearing player**, independent of
  which players a board publishes and of league size, and can change with the scoring preset;
* byes, missed games, zero-point and snaps-only appearances stay distinct;
* a badge needs an upward, meaningful, in-band rank gain over a real pre-window baseline, current
  evidence, consecutive strong appearances and — for the two stronger badges — a confirmed role;
* missing role facts are ``insufficient``, never a weaker badge or ``none``;
* the validator re-derives every rank and category, and refuses a tampered one.
"""

from __future__ import annotations

from typing import Any

import polars as pl
import pytest

from ffdraft.artifacts.recent_checks import (
    recent_cross_checks,
    recent_metadata_checks,
    recent_record_checks,
)
from ffdraft.artifacts.schemas import record_schema_version, validate_records
from ffdraft.config import load_app_config
from ffdraft.contracts import CheckStatus
from ffdraft.contracts.normalized import (
    SCHEDULE_CONTRACT,
    SNAP_COUNTS_CONTRACT,
    WEEKLY_STATS_CONTRACT,
)
from ffdraft.signals.actuals import build_season_actuals
from ffdraft.signals.recent import (
    BREAKOUT_RULE,
    RecentGame,
    build_recent_form,
    evaluate_breakout,
    window_weeks,
)

_SEASON = 2026
_TEAMS = ("MIN", "GB", "DET", "CHI")
_STAT_FIELDS = (
    "pass_attempts",
    "completions",
    "passing_yards",
    "passing_tds",
    "interceptions",
    "passing_air_yards",
    "carries",
    "rushing_yards",
    "rushing_tds",
    "targets",
    "receptions",
    "receiving_yards",
    "receiving_tds",
    "receiving_air_yards",
    "fumbles_lost",
    "two_point_conversions",
)


def _stat(week: int, gsis: str, *, position: str = "TE", team: str = "MIN", **values: float):
    row: dict[str, Any] = {
        "season": _SEASON,
        "week": week,
        "season_type": "REG",
        "gsis_id": gsis,
        "display_name": f"Player {gsis}",
        "position": position,
        "team": team,
        "opponent_team": None,
    }
    for name in _STAT_FIELDS:
        row[name] = float(values.get(name, 0.0))
    row["passing_epa"] = None
    row["sacks_suffered"] = 0.0
    return row


def _snap(week: int, gsis: str, *, team: str = "MIN", position: str = "TE", pct: float = 0.5):
    return {
        "season": _SEASON,
        "week": week,
        "game_type": "REG",
        "pfr_player_id": f"pfr-{gsis}-{team}-{week}",
        "player_name": f"Player {gsis}",
        "position": position,
        "team": team,
        "offense_snaps": 30.0,
        "offense_pct": pct,
        "gsis_id": gsis,
    }


def _schedule(weeks: int, byes: dict[int, tuple[str, ...]] | None = None) -> pl.DataFrame:
    rows = []
    for week in range(1, weeks + 1):
        resting = set((byes or {}).get(week, ()))
        playing = [team for team in _TEAMS if team not in resting]
        for slot in range(0, len(playing) - 1, 2):
            rows.append(
                {
                    "game_id": f"{_SEASON}_{week:02d}_{playing[slot]}_{playing[slot + 1]}",
                    "season": _SEASON,
                    "game_type": "REG",
                    "week": week,
                    "gameday": None,
                    "gametime": None,
                    "away_team": playing[slot],
                    "home_team": playing[slot + 1],
                },
            )
    return SCHEDULE_CONTRACT.build(rows)


def _league(weeks: int, players: int = 30, byes: dict[int, tuple[str, ...]] | None = None):
    """``players`` steady tight ends: TE i scores 15 − 0.4·i every week and draws 2 targets."""
    stats: list[dict[str, Any]] = []
    snaps: list[dict[str, Any]] = []
    for index in range(players):
        gsis = f"00-00010{index:02d}"
        team = _TEAMS[index % len(_TEAMS)]
        for week in range(1, weeks + 1):
            if team in (byes or {}).get(week, ()):
                continue
            yards = round((15 - 0.4 * index) * 10, 1)
            stats.append(_stat(week, gsis, team=team, receiving_yards=yards, targets=2.0))
            snaps.append(_snap(week, gsis, team=team))
    return stats, snaps


def _build(
    stats: list[dict[str, Any]],
    snaps: list[dict[str, Any]],
    *,
    through_week: int,
    schedule: pl.DataFrame | None = None,
    include: tuple[str, ...] = (),
) -> tuple[Any, Any]:
    plan = schedule if schedule is not None else _schedule(through_week + 1)
    snap_frame = SNAP_COUNTS_CONTRACT.build(
        [{k: v for k, v in row.items() if k != "gsis_id"} for row in snaps],
    ).with_columns(pl.Series("gsis_id", [row["gsis_id"] for row in snaps], dtype=pl.String))
    weekly = WEEKLY_STATS_CONTRACT.build(stats)
    scoring = load_app_config().league.scoring
    actuals = build_season_actuals(
        weekly=weekly,
        snap_counts=snap_frame,
        schedule=plan,
        scoring=scoring,
        season=_SEASON,
        through_week=through_week,
        positions={},
        include=include,
        build_id="test",
        schema_version=record_schema_version("season_actuals_record"),
    )
    recent = build_recent_form(
        weekly=weekly,
        snap_counts=snap_frame,
        schedule=plan,
        scoring=scoring,
        season=_SEASON,
        through_week=through_week,
        actuals=actuals,
        include=include,
        build_id="test",
        schema_version=record_schema_version("recent_form_record"),
    )
    return actuals, recent


def _rec(result: Any, gsis: str, preset: str = "PPR") -> dict[str, Any]:
    matches = [
        r
        for r in result.records
        if r["player_id"] == f"gsis:{gsis}" and r["scoring_preset"] == preset
    ]
    assert len(matches) == 1, f"{gsis}/{preset}: {len(matches)} record(s)"
    return matches[0]


def _cat(record: dict[str, Any], window: str) -> tuple[str, str]:
    verdict = record["windows"][window]["breakout"]
    return verdict["category"], verdict["reason"]


_RISER = "00-0002001"


def _riser_league(*, late_points: float = 13.1, targets: float = 8.0, through_week: int = 5):
    """TE16-ish all season, TE6 over weeks 3–5: two snaps-only games, then three strong ones."""
    stats, snaps = _league(through_week)
    for week in range(1, through_week + 1):
        snaps.append(_snap(week, _RISER, team="MIN"))
        if week >= 3:
            stats.append(
                _stat(week, _RISER, receiving_yards=late_points * 10, targets=targets),
            )
    return stats, snaps


# ---------------------------------------------------------------------- the illustration


def test_a_sustained_riser_with_a_confirmed_role_is_a_takeover():
    actuals, recent = _build(*_riser_league(), through_week=5)
    assert recent.published
    record = _rec(recent, _RISER)
    assert record["season_rank"] == 19
    three = record["windows"]["3"]
    assert (three["rank"], three["games"], three["prior_games"]) == (6, 3, 2)
    assert _cat(record, "3") == ("takeover", "takeover_role")
    verdict = three["breakout"]
    assert verdict["games"] == [3, 4, 5]
    assert verdict["streak"] == 3
    target = next(r for r in verdict["role"] if r["metric"] == "target_share")
    assert target["passed"] == "substantial" and target["level"] >= 0.18
    # The other windows say only what their weeks can support.
    assert _cat(record, "2") == ("sneaking", "sneaking_role")
    assert _cat(record, "1") == ("eyebrow", "one_strong")
    # Last 4 and Last 6 include his quiet weeks: their totals rank outside the band.
    assert _cat(record, "4") == ("none", "outside_band")
    assert _cat(record, "6") == ("none", "outside_band")
    # Rule outcomes are the same in every preset here (no receptions).
    assert _cat(_rec(recent, _RISER, "STD"), "3") == ("takeover", "takeover_role")


def test_the_same_production_without_a_role_is_at_most_an_eyebrow():
    stats, snaps = _riser_league(targets=1.0)
    snaps = [{**row, "offense_pct": 0.3} if row["gsis_id"] == _RISER else row for row in snaps]
    _, recent = _build(stats, snaps, through_week=5)
    record = _rec(recent, _RISER)
    assert _cat(record, "3") == ("eyebrow", "role_not_confirmed")
    assert record["windows"]["3"]["breakout"]["games"] == [5]


def test_two_strong_recent_games_after_an_ordinary_one_are_sneaking():
    stats, snaps = _league(5)
    for week in range(1, 6):
        snaps.append(_snap(week, _RISER))
        points = {3: 9.0, 4: 13.1, 5: 13.1}.get(week, 0.0)
        if points:
            stats.append(_stat(week, _RISER, receiving_yards=points * 10, targets=8.0))
    _, recent = _build(stats, snaps, through_week=5)
    record = _rec(recent, _RISER)
    assert record["windows"]["3"]["rank"] <= 12
    assert record["span_ranks"][2] > 12  # week 3 is not a top-12 week
    assert _cat(record, "3") == ("sneaking", "sneaking_role")
    assert record["windows"]["3"]["breakout"]["games"] == [4, 5]
    assert _cat(record, "2") == ("sneaking", "sneaking_role")


def test_one_touchdown_heavy_outlier_cannot_be_more_than_an_eyebrow():
    stats, snaps = _league(5)
    for week in range(1, 6):
        snaps.append(_snap(week, _RISER))
    # A 3-touchdown week 5 on two targets after nothing: a big window total from one game.
    stats.append(_stat(5, _RISER, receiving_yards=40.0, receiving_tds=3.0, targets=2.0))
    _, recent = _build(stats, snaps, through_week=5)
    record = _rec(recent, _RISER)
    # Over weeks 3–5 the one game is not even a top-12 total…
    assert _cat(record, "3") == ("none", "outside_band")
    # …and alone it is a one-game watch, never a sustained badge.
    assert _cat(record, "1") == ("eyebrow", "one_strong")
    assert _cat(record, "2")[0] not in {"takeover", "sneaking"}


def test_an_early_outlier_with_a_quiet_latest_game_is_none():
    stats, snaps = _league(5)
    for week in range(1, 6):
        snaps.append(_snap(week, _RISER))
    stats.append(_stat(3, _RISER, receiving_yards=200.0, receiving_tds=3.0, targets=8.0))
    stats.append(_stat(5, _RISER, receiving_yards=10.0, targets=1.0))
    _, recent = _build(stats, snaps, through_week=5)
    assert _cat(_rec(recent, _RISER), "3") == ("none", "latest_not_strong")


# ----------------------------------------------------------------- no unjustified badge


def test_a_stable_elite_player_has_no_badge():
    _, recent = _build(*_riser_league(), through_week=5)
    assert _cat(_rec(recent, "00-0001000"), "3") == ("none", "not_improved")


def test_a_worsening_player_has_no_badge_and_keeps_a_negative_gap():
    stats, snaps = _league(5)
    for week in range(1, 6):
        snaps.append(_snap(week, _RISER))
        points = 30.0 if week <= 2 else 3.0
        stats.append(_stat(week, _RISER, receiving_yards=points * 10, targets=8.0))
    _, recent = _build(stats, snaps, through_week=5)
    record = _rec(recent, _RISER)
    assert record["windows"]["3"]["rank"] > record["season_rank"]
    assert _cat(record, "3")[0] == "none"


def test_a_tiny_movement_at_the_top_is_not_a_breakout():
    # TE2 all season edges to TE1 recently: 50% better, one place.
    stats, snaps = _league(5)
    for week in range(1, 6):
        snaps.append(_snap(week, _RISER))
        points = 14.0 if week <= 2 else 15.4
        stats.append(_stat(week, _RISER, receiving_yards=points * 10, targets=8.0))
    _, recent = _build(stats, snaps, through_week=5)
    record = _rec(recent, _RISER)
    assert (record["season_rank"], record["windows"]["3"]["rank"]) == (2, 1)
    assert _cat(record, "3") == ("none", "gain_too_small")


def test_a_fringe_improvement_outside_the_band_is_not_a_breakout():
    stats, snaps = _league(5, players=60)
    for week in range(1, 6):
        snaps.append(_snap(week, _RISER))
        points = 0.0 if week <= 2 else 6.0
        stats.append(_stat(week, _RISER, receiving_yards=points * 10, targets=8.0))
    _, recent = _build(stats, snaps, through_week=5)
    record = _rec(recent, _RISER)
    assert record["windows"]["3"]["rank"] > 12
    assert record["season_rank"] - record["windows"]["3"]["rank"] > 3
    assert _cat(record, "3") == ("none", "outside_band")


def test_a_streak_that_ended_with_a_missed_game_is_stale():
    stats, snaps = _league(6)
    for week in range(1, 6):  # appears weeks 1–5, misses week 6 while MIN plays
        snaps.append(_snap(week, _RISER))
        if week >= 3:
            stats.append(_stat(week, _RISER, receiving_yards=200.0, targets=8.0))
    _, recent = _build(stats, snaps, through_week=6)
    record = _rec(recent, _RISER)
    assert record["span_status"].endswith("D")
    assert _cat(record, "4") == ("none", "stale")


def test_no_pre_window_baseline_is_insufficient_not_none():
    stats, snaps = _league(5)
    for week in range(3, 6):  # debuts in week 3
        snaps.append(_snap(week, _RISER))
        stats.append(_stat(week, _RISER, receiving_yards=131.0, targets=8.0))
    _, recent = _build(stats, snaps, through_week=5)
    record = _rec(recent, _RISER)
    assert record["windows"]["3"]["prior_games"] == 0
    assert _cat(record, "3") == ("insufficient", "no_baseline")


# ---------------------------------------------------------------- the rule, directly


def _game(week: int, *, snap: float | None = 0.8, targets: float = 6.0, team_targets=30.0):
    return RecentGame(
        week=week,
        team="MIN",
        cents={"PPR": 1000},
        snap_share=snap,
        targets=targets,
        team_targets=team_targets,
        team_carries=20.0,
    )


def _evaluate(**overrides: Any) -> dict[str, Any]:
    arguments: dict[str, Any] = {
        "position": "TE",
        "season_rank": 16,
        "window_rank": 4,
        "window_games": [_game(3), _game(4), _game(5)],
        "week_ranks": {3: 4, 4: 5, 5: 3},
        "prior_games": [_game(1, targets=2.0), _game(2, targets=2.0)],
        "missed_after_latest": 0,
    }
    arguments.update(overrides)
    return evaluate_breakout(**arguments)


def test_te16_to_te4_with_three_strong_games_and_a_role_is_a_takeover():
    verdict = _evaluate()
    assert (verdict["category"], verdict["games"], verdict["streak"]) == (
        "takeover",
        [3, 4, 5],
        3,
    )


def test_missing_role_facts_are_insufficient_not_a_weaker_badge():
    games = [_game(week, snap=None, team_targets=None) for week in (3, 4, 5)]
    verdict = _evaluate(window_games=games)
    assert (verdict["category"], verdict["reason"]) == ("insufficient", "role_unavailable")


def test_a_bye_inside_the_window_is_not_a_bad_game_but_leaves_two_games():
    verdict = _evaluate(window_games=[_game(3), _game(5)], week_ranks={3: 4, 5: 3})
    assert verdict["category"] == "sneaking"


def test_a_role_grown_from_a_tiny_baseline_to_a_small_one_does_not_pass():
    # 10% of targets after 2%: an increase, but below the emerging level.
    games = [_game(w, snap=0.4, targets=3.0) for w in (3, 4, 5)]
    prior = [_game(w, snap=0.4, targets=0.6) for w in (1, 2)]
    verdict = _evaluate(window_games=games, prior_games=prior)
    assert verdict["category"] == "eyebrow"
    assert all(reading["passed"] is None for reading in verdict["role"])


def test_an_emerging_role_with_a_real_increase_passes():
    games = [_game(w, snap=0.4, targets=4.5) for w in (3, 4, 5)]  # 15%
    prior = [_game(w, snap=0.4, targets=1.5) for w in (1, 2)]  # 5%
    verdict = _evaluate(window_games=games, prior_games=prior)
    assert verdict["category"] == "takeover"
    target = next(r for r in verdict["role"] if r["metric"] == "target_share")
    assert (target["passed"], target["level"], target["baseline"]) == ("increase", 0.15, 0.05)


def test_a_quarterback_role_is_snaps_and_throws_never_targets():
    games = [
        RecentGame(week=w, team="MIN", cents={"PPR": 2500}, snap_share=1.0, pass_attempts=34.0)
        for w in (3, 4, 5)
    ]
    verdict = _evaluate(position="QB", window_games=games)
    assert verdict["category"] == "takeover"
    assert {r["metric"] for r in verdict["role"]} == {"snap_share", "pass_attempts"}


def test_tie_at_the_band_edge_is_inside_the_band():
    verdict = _evaluate(season_rank=20, window_rank=12, week_ranks={3: 12, 4: 12, 5: 12})
    assert verdict["category"] == "takeover"


@pytest.mark.parametrize(
    ("season", "recent", "expected"),
    [(2, 1, "gain_too_small"), (9, 7, "gain_too_small"), (10, 7, None), (4, 4, "not_improved")],
)
def test_the_gain_needs_three_places_and_thirty_percent(season, recent, expected):
    verdict = _evaluate(season_rank=season, window_rank=recent)
    assert (verdict["reason"] if verdict["category"] == "none" else None) == expected


# ------------------------------------------------------------- windows and populations


def test_window_weeks_are_calendar_weeks_clipped_to_the_season():
    assert window_weeks(5, 1, 3) == [3, 4, 5]
    assert window_weeks(2, 1, 3) == [1, 2]
    assert window_weeks(8, 1, 6) == [3, 4, 5, 6, 7, 8]


def test_a_window_never_reaches_back_past_absences():
    stats, snaps = _league(5)
    stats.append(_stat(1, _RISER, receiving_yards=100.0))
    stats.append(_stat(2, _RISER, receiving_yards=100.0))
    _, recent = _build(stats, snaps, through_week=5)
    record = _rec(recent, _RISER)
    assert record["span_status"] == "PPDDD"
    assert record["windows"]["3"] == {
        **record["windows"]["3"],
        "games": 0,
        "points": 0.0,
        "rank": None,
        "points_per_game": None,
    }
    assert _cat(record, "3") == ("insufficient", "no_games")


def test_byes_missed_games_zero_and_snaps_only_weeks_stay_distinct():
    schedule = _schedule(6, byes={4: ("MIN", "GB")})
    stats, snaps = _league(5, byes={4: ("MIN", "GB")})
    snaps.append(_snap(2, _RISER))  # snaps only: an appearance worth 0
    stats.append(_stat(3, _RISER, receiving_yards=-10.0, receptions=0.0, fumbles_lost=1.0))
    stats.append(_stat(5, _RISER, receiving_yards=50.0))
    _, recent = _build(stats, snaps, through_week=5, schedule=schedule)
    record = _rec(recent, _RISER)
    assert record["span_status"] == "DPPBP"
    points = record["span_points"]
    assert points[0] is None and points[1] == 0.0 and points[2] < 0 and points[3] is None
    assert record["span_ranks"][1] is not None and record["span_ranks"][2] is not None


def test_ranks_do_not_depend_on_which_players_a_board_publishes():
    stats, snaps = _riser_league()
    _, plain = _build(stats, snaps, through_week=5)
    _, boarded = _build(stats, snaps, through_week=5, include=(f"gsis:{_RISER}",))
    for a, b in zip(plain.records, boarded.records, strict=True):
        assert a["windows"] == b["windows"] and a["span_ranks"] == b["span_ranks"]


def test_an_off_board_leader_takes_rank_one_and_a_board_player_without_games_has_a_record():
    stats, snaps = _riser_league()
    idle = "00-0003000"
    _, recent = _build(stats, snaps, through_week=5, include=(f"gsis:{idle}",))
    assert _rec(recent, "00-0001000")["windows"]["3"]["rank"] == 1  # nobody publishes him
    actuals_ids = {r["player_id"] for r in recent.records}
    # A board player with no actuals record at all (no position) gets no recent record either.
    assert f"gsis:{idle}" not in actuals_ids


def test_a_preset_can_change_a_window_rank():
    stats, snaps = _league(3, players=4)
    stats.append(_stat(3, _RISER, receiving_yards=100.0, team="GB"))  # STD 10.0
    stats.append(_stat(3, "00-0002002", receiving_yards=60.0, receptions=8.0, team="DET"))
    snaps += [_snap(3, _RISER, team="GB"), _snap(3, "00-0002002", team="DET")]
    _, recent = _build(stats, snaps, through_week=3)
    std = _rec(recent, _RISER, "STD")["windows"]["1"]["rank"]
    ppr = _rec(recent, _RISER, "PPR")["windows"]["1"]["rank"]
    assert _rec(recent, "00-0002002", "PPR")["windows"]["1"]["rank"] < ppr
    assert std < _rec(recent, "00-0002002", "STD")["windows"]["1"]["rank"]


def test_ties_share_a_window_rank():
    stats, snaps = _league(3, players=4)
    stats.append(_stat(3, _RISER, receiving_yards=150.0, team="GB"))
    snaps.append(_snap(3, _RISER, team="GB"))
    _, recent = _build(stats, snaps, through_week=3)
    assert _rec(recent, _RISER)["windows"]["1"]["rank"] == 1
    assert _rec(recent, "00-0001000")["windows"]["1"]["rank"] == 1
    assert _rec(recent, "00-0001001")["windows"]["1"]["rank"] == 3


def test_nothing_after_the_cutoff_counts():
    stats, snaps = _riser_league(through_week=5)
    stats.append(_stat(6, _RISER, receiving_yards=500.0))
    _, recent = _build(stats, snaps, through_week=5)
    assert len(_rec(recent, _RISER)["span_status"]) == 5


def test_a_span_that_is_the_season_equals_the_season_actuals():
    actuals, recent = _build(*_riser_league(), through_week=5)
    season = {(r["scoring_preset"], r["player_id"]): r for r in actuals.records}
    for record in recent.records:
        held = season[(record["scoring_preset"], record["player_id"])]
        assert record["windows"]["6"]["points"] == held["points"]
        assert record["windows"]["6"]["games"] == held["games_played"]


def test_early_season_windows_are_shorter_and_say_so():
    _, recent = _build(*_league(2), through_week=2)
    assert recent.metadata["windows"]["3"] == {
        "requested": 3,
        "first_week": 1,
        "last_week": 2,
        "weeks": 2,
    }
    categories = {r["windows"]["3"]["breakout"]["category"] for r in recent.records}
    assert categories <= {"none", "insufficient"}


def test_a_traded_players_absence_is_read_against_his_latest_club():
    schedule = _schedule(5, byes={4: ("GB",)})
    stats, snaps = _league(4)
    stats.append(_stat(1, _RISER, team="MIN", receiving_yards=50.0))
    stats.append(_stat(2, _RISER, team="MIN", receiving_yards=50.0))
    stats.append(_stat(3, _RISER, team="GB", receiving_yards=50.0))
    _, recent = _build(stats, snaps, through_week=4, schedule=schedule)
    # Week 4: GB has a bye. His latest club is GB, so it is a bye, not a missed game.
    assert _rec(recent, _RISER)["span_status"] == "PPPB"


def test_a_missing_team_week_withholds_recent_form_with_the_season_actuals():
    stats, snaps = _riser_league()
    stats = [row for row in stats if not (row["team"] == "DET" and row["week"] == 4)]
    actuals, recent = _build(stats, snaps, through_week=5)
    assert not actuals.published
    assert not recent.published and recent.records == []
    assert recent.metadata["status"] == "withheld"


# ---------------------------------------------------------------------------- validator


def test_records_match_the_schema_and_rederive():
    _, recent = _build(*_riser_league(), through_week=5)
    schema = validate_records("recent_form_record", recent.records)
    assert all(c.status == CheckStatus.PASS for c in schema), [c.observed for c in schema]
    checks = recent_record_checks(recent.records, "test", rule=recent.metadata["breakout_rule"])
    assert [c.status for c in checks] == [CheckStatus.PASS], [c.observed for c in checks]


def test_a_tampered_category_or_rank_fails_validation():
    _, recent = _build(*_riser_league(targets=1.0), through_week=5)
    records = [dict(r) for r in recent.records]
    target = next(r for r in records if r["player_id"] == f"gsis:{_RISER}")
    windows = {k: dict(v) for k, v in target["windows"].items()}
    windows["3"]["breakout"] = {**windows["3"]["breakout"], "category": "takeover"}
    windows["1"]["rank"] = 99
    target["windows"] = windows
    checks = recent_record_checks(records, "test", rule=recent.metadata["breakout_rule"])
    failed = {c.check_id for c in checks if c.status != CheckStatus.PASS}
    assert {"recent_form.rank_not_rederivable", "recent_form.category_not_rederivable"} <= failed


def test_metadata_and_season_agreement_checks():
    actuals, recent = _build(*_riser_league(), through_week=5)
    envelopes = {
        "recent_form": {"records": recent.records},
        "season_actuals": {"records": actuals.records},
    }
    metadata = {"through_week": 5, "recent_form": recent.metadata}
    assert all(c.status == CheckStatus.PASS for c in recent_metadata_checks(metadata, envelopes))
    assert all(c.status == CheckStatus.PASS for c in recent_cross_checks(envelopes))
    bad = [{**r, "season_rank": 1} for r in recent.records]
    checks = recent_cross_checks({**envelopes, "recent_form": {"records": bad}})
    assert any(c.status != CheckStatus.PASS for c in checks)


def test_the_rule_constants_are_published_whole():
    rule = BREAKOUT_RULE.to_dict()
    assert rule["bands"] == {"QB": 12, "RB": 24, "WR": 24, "TE": 12}
    assert (rule["min_gain_places"], rule["min_gain_percent"], rule["min_prior_games"]) == (
        3,
        30,
        2,
    )
    assert "target_share" not in {m["metric"] for m in rule["measures"]["QB"]}
