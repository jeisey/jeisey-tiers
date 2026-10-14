"""`skill_tree_v1`: the player card's positional statistical profile (ADR-107).

Every number below is computed by hand from a two-club league small enough to read: MIN and
GB play weeks 1-3, the board's cutoff is week 2, and play-by-play also carries a week-3 game
and a postseason play that must both be ignored. Each claim a node leans on is tested on its
own:

* official totals stay official; play-by-play universes drop two-point tries everywhere and
  kneel-downs from rushing efficiency only;
* rates and shares are pooled — Σ numerator ÷ Σ denominator — and a traded player's shares use
  each club's totals in the games he played for it;
* CPOE pools over attempts (it is not the mean of weekly values);
* zero opportunity, a sample below the minimum, a source that does not cover him and a source
  that failed are four different states, and none of them is a 0;
* ranks are competition ranks and percentiles follow ADR-107's formula, by direction;
* Next Gen Stats is used only from a reconciled week-0 summary that ends at the cutoff;
* the combine cohort is every tester, and an ambiguous link fails closed;
* the validator re-derives ranks and catches a forged one.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import polars as pl
import pytest

from ffdraft.artifacts.schemas import record_schema_version, validate_records
from ffdraft.artifacts.skilltree_checks import (
    skilltree_cross_checks,
    skilltree_definition_checks,
    skilltree_metadata_checks,
    skilltree_record_checks,
)
from ffdraft.contracts import CheckStatus
from ffdraft.contracts.normalized import (
    NEXTGEN_STATS_CONTRACT,
    SCHEDULE_CONTRACT,
    SNAP_COUNTS_CONTRACT,
    WEEKLY_STATS_CONTRACT,
)
from ffdraft.signals.skilltree import (
    MIN_COHORT,
    REASONS,
    SKILL_PLAY_COLUMNS,
    build_skill_tree,
    combine_readings,
    percentile_ranks,
    skill_plays,
)
from ffdraft.signals.skilltree_catalog import CATALOG, TREES, metric_ids_for

_SEASON = 2026
_CUTOFF = 2

Q, G, R = "00-0000101", "00-0000102", "00-0000103"  # MIN QB, GB QB, MIN RB
A, B, C, D, T = "00-0000201", "00-0000202", "00-0000203", "00-0000204", "00-0000205"  # WRs
E = "00-0000301"  # GB TE, snaps only
NEVER = "00-0000999"  # a board WR who has not appeared

_FIELDS = (
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


def _stat(week: int, gsis: str, position: str, team: str, **values: float) -> dict[str, Any]:
    row: dict[str, Any] = {
        "season": _SEASON,
        "week": week,
        "season_type": "REG",
        "gsis_id": gsis,
        "display_name": f"P{gsis[-3:]}",
        "position": position,
        "team": team,
        "opponent_team": "GB" if team == "MIN" else "MIN",
    }
    for name in _FIELDS:
        row[name] = float(values.get(name, 0.0))
    row["passing_epa"] = values.get("passing_epa")
    row["sacks_suffered"] = float(values.get("sacks_suffered", 0.0))
    row["receiving_yards_after_catch"] = float(values.get("yac", 0.0))
    return row


def _weekly() -> pl.DataFrame:
    rows = [
        # week 1
        _stat(
            1,
            Q,
            "QB",
            "MIN",
            pass_attempts=4,
            completions=2,
            passing_yards=33,
            passing_air_yards=35,
            sacks_suffered=1,
            passing_epa=-0.8,
            carries=2,
            rushing_yards=6,
        ),
        _stat(1, R, "RB", "MIN", carries=2, rushing_yards=15),
        _stat(
            1,
            A,
            "WR",
            "MIN",
            targets=2,
            receptions=1,
            receiving_yards=25,
            receiving_air_yards=30,
            yac=5,
        ),
        _stat(
            1,
            T,
            "WR",
            "MIN",
            targets=1,
            receptions=1,
            receiving_yards=8,
            receiving_air_yards=5,
            yac=3,
        ),
        _stat(
            1,
            G,
            "QB",
            "GB",
            pass_attempts=2,
            completions=1,
            passing_yards=15,
            passing_air_yards=40,
            passing_epa=0.4,
        ),
        _stat(
            1,
            C,
            "WR",
            "GB",
            targets=1,
            receptions=1,
            receiving_yards=15,
            receiving_air_yards=10,
            yac=5,
        ),
        _stat(1, D, "WR", "GB", targets=1, receiving_air_yards=30),
        # week 2 — T now plays for GB
        _stat(
            2,
            Q,
            "QB",
            "MIN",
            pass_attempts=1,
            completions=1,
            passing_yards=5,
            passing_air_yards=3,
            passing_epa=0.1,
        ),
        _stat(2, R, "RB", "MIN", carries=1, rushing_yards=2),
        _stat(
            2,
            A,
            "WR",
            "MIN",
            targets=1,
            receptions=1,
            receiving_yards=5,
            receiving_air_yards=3,
            yac=2,
        ),
        _stat(
            2,
            G,
            "QB",
            "GB",
            pass_attempts=2,
            completions=1,
            passing_yards=22,
            passing_air_yards=47,
            passing_epa=0.7,
        ),
        _stat(
            2,
            T,
            "WR",
            "GB",
            targets=1,
            receptions=1,
            receiving_yards=22,
            receiving_air_yards=22,
            yac=10,
        ),
        _stat(2, C, "WR", "GB", targets=1, receiving_air_yards=25),
        # week 3 is after the cutoff
        _stat(
            3,
            Q,
            "QB",
            "MIN",
            pass_attempts=1,
            completions=1,
            passing_yards=50,
            passing_air_yards=40,
            passing_epa=3.0,
        ),
        _stat(
            3, A, "WR", "MIN", targets=1, receptions=1, receiving_yards=50, receiving_air_yards=40
        ),
    ]
    return WEEKLY_STATS_CONTRACT.build(rows)


def _snaps() -> pl.DataFrame:
    rows: list[dict[str, Any]] = []

    def snap(week: int, gsis: str | None, position: str, team: str, pct: float) -> None:
        rows.append(
            {
                "season": _SEASON,
                "week": week,
                "game_type": "REG",
                "pfr_player_id": f"pfr-{gsis}-{week}",
                "player_name": f"P{gsis}",
                "position": position,
                "team": team,
                "offense_snaps": round(60 * pct),
                "offense_pct": pct,
                "gsis_id": gsis,
            },
        )

    for week in (1, 2, 3):
        snap(week, f"00-990000{week}", "OL", "MIN", 1.0)
        snap(week, f"00-990010{week}", "OL", "GB", 1.0)
    snap(1, Q, "QB", "MIN", 1.0)
    snap(2, Q, "QB", "MIN", 1.0)
    snap(1, G, "QB", "GB", 1.0)
    snap(2, G, "QB", "GB", 1.0)
    snap(1, R, "RB", "MIN", 0.5)
    snap(2, R, "RB", "MIN", 0.4)
    snap(1, A, "WR", "MIN", 0.8)
    snap(2, A, "WR", "MIN", 0.9)
    snap(1, B, "WR", "MIN", 0.3)
    snap(2, B, "WR", "MIN", 0.2)
    snap(1, T, "WR", "MIN", 0.5)
    snap(2, T, "WR", "GB", 0.6)
    snap(1, C, "WR", "GB", 0.7)
    snap(2, C, "WR", "GB", 0.7)
    snap(1, D, "WR", "GB", 0.6)
    snap(2, D, "WR", "GB", 0.5)  # a snaps-only appearance: on the field, never targeted
    snap(1, E, "TE", "GB", 0.4)
    snap(2, E, "TE", "GB", 0.4)
    snap(1, None, "WR", "GB", 0.1)  # an unbridged row: no canonical id, excluded
    frame = SNAP_COUNTS_CONTRACT.build(
        [{k: v for k, v in row.items() if k != "gsis_id"} for row in rows],
    )
    return frame.with_columns(
        pl.Series("gsis_id", [row["gsis_id"] for row in rows], dtype=pl.String),
    )


def _schedule(weeks: int = 3) -> pl.DataFrame:
    return SCHEDULE_CONTRACT.build(
        [
            {
                "game_id": f"{_SEASON}_{week:02d}_GB_MIN",
                "season": _SEASON,
                "game_type": "REG",
                "week": week,
                "gameday": None,
                "gametime": None,
                "away_team": "GB",
                "home_team": "MIN",
            }
            for week in range(1, weeks + 1)
        ],
    )


def _play(**fields: Any) -> dict[str, Any]:
    base: dict[str, Any] = {name: None for name in SKILL_PLAY_COLUMNS}
    base.update(
        {
            "season": _SEASON,
            "season_type": "REG",
            "play_type": "pass",
            "pass_attempt": 0.0,
            "rush_attempt": 0.0,
            "sack": 0.0,
            "qb_scramble": 0.0,
            "two_point_attempt": 0.0,
            "yardline_100": 50.0,
            "complete_pass": 0.0,
            "epa": 0.0,
        },
    )
    base.update(fields)
    return base


def _pass(week: int, team: str, passer: str, receiver: str | None, **fields: Any) -> dict:
    return _play(
        week=week,
        posteam=team,
        pass_attempt=1.0,
        passer_player_id=passer,
        receiver_player_id=receiver,
        **fields,
    )


def _run(week: int, team: str, rusher: str, **fields: Any) -> dict[str, Any]:
    values: dict[str, Any] = {"play_type": "run", **fields}
    return _play(week=week, posteam=team, rush_attempt=1.0, rusher_player_id=rusher, **values)


def _pbp() -> pl.DataFrame:
    plays = [
        # MIN week 1
        _pass(
            1,
            "MIN",
            Q,
            A,
            complete_pass=1.0,
            receiving_yards=25.0,
            air_yards=20.0,
            epa=1.0,
            cpoe=30.0,
        ),
        _pass(1, "MIN", Q, A, air_yards=10.0, epa=-0.5, cpoe=-60.0),
        _pass(
            1,
            "MIN",
            Q,
            T,
            complete_pass=1.0,
            receiving_yards=8.0,
            air_yards=5.0,
            yardline_100=15.0,
            epa=0.4,
            cpoe=20.0,
        ),
        _pass(1, "MIN", Q, None, air_yards=0.0, epa=-0.2),  # thrown away: no receiver, no cpoe
        _pass(1, "MIN", Q, None, sack=1.0, epa=-1.5),
        _run(1, "MIN", R, rushing_yards=12.0, yardline_100=30.0, epa=0.6),
        _run(1, "MIN", R, rushing_yards=3.0, yardline_100=4.0, epa=0.3),
        _run(1, "MIN", Q, play_type="qb_kneel", rushing_yards=-1.0, epa=-0.1),
        _run(1, "MIN", Q, qb_scramble=1.0, rushing_yards=7.0, yardline_100=40.0, epa=0.5),
        _run(1, "MIN", R, two_point_attempt=1.0, yardline_100=2.0, rushing_yards=2.0, epa=0.9),
        # GB week 1
        _pass(
            1,
            "GB",
            G,
            C,
            complete_pass=1.0,
            receiving_yards=15.0,
            air_yards=10.0,
            epa=0.8,
            cpoe=10.0,
        ),
        _pass(1, "GB", G, D, air_yards=30.0, epa=-0.4, cpoe=-40.0),
        # MIN week 2
        _pass(
            2, "MIN", Q, A, complete_pass=1.0, receiving_yards=5.0, air_yards=3.0, epa=0.1, cpoe=5.0
        ),
        _run(2, "MIN", R, rushing_yards=2.0, yardline_100=18.0, epa=-0.3),
        # GB week 2
        _pass(
            2,
            "GB",
            G,
            T,
            complete_pass=1.0,
            receiving_yards=22.0,
            air_yards=22.0,
            yardline_100=21.0,
            epa=1.2,
            cpoe=40.0,
        ),
        _pass(2, "GB", G, C, air_yards=25.0, yardline_100=10.0, epa=-0.5, cpoe=-50.0),
        # week 3 (after the cutoff) and the postseason: both ignored
        _pass(
            3,
            "MIN",
            Q,
            A,
            complete_pass=1.0,
            receiving_yards=50.0,
            air_yards=40.0,
            epa=3.0,
            cpoe=30.0,
        ),
        _pass(3, "GB", G, C, epa=0.1),
        _pass(
            19,
            "MIN",
            Q,
            A,
            season_type="POST",
            complete_pass=1.0,
            receiving_yards=60.0,
            epa=4.0,
            cpoe=50.0,
        ),
    ]
    return pl.DataFrame(plays, infer_schema_length=None)


def _nextgen(*, last_week: int = 2, mismatch: bool = True) -> dict[str, pl.DataFrame]:
    def frame(rows: list[dict[str, Any]]) -> pl.DataFrame:
        return NEXTGEN_STATS_CONTRACT.build(rows)

    base = {"season": _SEASON, "season_type": "REG"}
    weekly = lambda kind, gsis, week, volume: {  # noqa: E731
        **base,
        "week": week,
        "stat_type": kind,
        "gsis_id": gsis,
        "volume": volume,
    }
    return {
        "passing": frame(
            [
                {
                    **base,
                    "week": 0,
                    "stat_type": "passing",
                    "gsis_id": Q,
                    "volume": 5.0,
                    "avg_time_to_throw": 2.81,
                },
                weekly("passing", Q, last_week, 15.0),
            ],
        ),
        "rushing": frame(
            [
                {
                    **base,
                    "week": 0,
                    "stat_type": "rushing",
                    "gsis_id": R,
                    "volume": 3.0,
                    "rush_yards_over_expected_per_att": 0.75,
                },
                weekly("rushing", R, last_week, 10.0),
            ],
        ),
        "receiving": frame(
            [
                {
                    **base,
                    "week": 0,
                    "stat_type": "receiving",
                    "gsis_id": A,
                    "volume": 3.0,
                    "receptions": 2.0,
                    "avg_separation": 3.1,
                    "avg_cushion": 6.0,
                    "avg_yac_above_expectation": 1.25,
                },
                {
                    **base,
                    "week": 0,
                    "stat_type": "receiving",
                    "gsis_id": C,
                    "volume": 7.0 if mismatch else 2.0,
                    "receptions": 1.0,
                    "avg_separation": 2.0,
                    "avg_cushion": 5.0,
                    "avg_yac_above_expectation": -0.5,
                },
                weekly("receiving", A, last_week, 5.0),
                # A postseason summary must never be read.
                {
                    **base,
                    "season_type": "POST",
                    "week": 0,
                    "stat_type": "receiving",
                    "gsis_id": D,
                    "volume": 1.0,
                    "avg_separation": 9.9,
                },
            ],
        ),
    }


def _combine() -> tuple[pl.DataFrame, dict[str, str]]:
    rows = [
        {"combine_year": 2023, "pfr_id": "pfr-A", "position": "WR", "forty": 4.40},
        {"combine_year": 2022, "pfr_id": "pfr-T", "position": "WR", "forty": 4.50},
        {"combine_year": 2021, "pfr_id": "pfr-T2", "position": "WR", "forty": 4.60},
        {"combine_year": 1999, "pfr_id": None, "position": "WR", "forty": 4.10},  # before 2000
        *(
            {"combine_year": 2010, "pfr_id": None, "position": "WR", "forty": time}
            for time in (4.30, 4.35, 4.45, 4.50, 4.55, 4.60)
        ),
    ]
    frame = pl.DataFrame(
        rows,
        schema={
            "combine_year": pl.Int32,
            "pfr_id": pl.String,
            "position": pl.String,
            "forty": pl.Float64,
        },
    )
    # Two PFR ids claim T: ambiguous, so he has no reading.
    return frame, {"pfr-A": A, "pfr-T": T, "pfr-T2": T}


_POSITIONS = {
    f"gsis:{gsis}": position
    for gsis, position in (
        (Q, "QB"),
        (G, "QB"),
        (R, "RB"),
        (A, "WR"),
        (B, "WR"),
        (C, "WR"),
        (D, "WR"),
        (T, "WR"),
        (E, "TE"),
        (NEVER, "WR"),
    )
}


def _build(**overrides: Any) -> Any:
    combine, bridge = _combine()
    arguments: dict[str, Any] = {
        "weekly": _weekly(),
        "snap_counts": _snaps(),
        "schedule": _schedule(),
        "pbp": _pbp(),
        "nextgen": _nextgen(),
        "combine": combine,
        "pfr_bridge": bridge,
        "season": _SEASON,
        "through_week": _CUTOFF,
        "positions": _POSITIONS,
        "include": [f"gsis:{NEVER}"],
        "build_id": "test",
        "metric_schema_version": record_schema_version("player_skill_metric"),
        "definition_schema_version": record_schema_version("skill_tree_definition"),
    }
    arguments.update(overrides)
    return build_skill_tree(**arguments)


def _reading(result: Any, gsis: str, metric: str) -> Mapping[str, Any]:
    matches = [
        row
        for row in result.records
        if row["player_id"] == f"gsis:{gsis}" and row["metric_id"] == metric
    ]
    assert len(matches) == 1, f"{gsis}/{metric}: {len(matches)} record(s)"
    return matches[0]


# --------------------------------------------------------------------------- percentiles


def test_percentiles_follow_adr_107_with_ties_and_direction():
    values = {"a": 10.0, "b": 8.0, "c": 8.0, "d": 6.0, "e": 1.0}
    ranks = percentile_ranks(values, direction="higher", decimals=2)
    assert ranks["a"] == (1, 100.0)
    assert ranks["b"] == ranks["c"] == (2, 62.5)  # (2 behind + 1/2) / 4
    assert ranks["d"] == (4, 25.0)
    assert ranks["e"] == (5, 0.0)
    lower = percentile_ranks(values, direction="lower", decimals=2)
    assert lower["e"] == (1, 100.0)
    assert lower["a"] == (5, 0.0)
    # A cohort below the minimum ranks no one.
    assert percentile_ranks({"a": 1.0, "b": 2.0}, direction="higher", decimals=2) == {}
    assert MIN_COHORT == 5


def test_ranks_use_the_published_precision_so_a_visible_tie_is_a_tie():
    values = {"a": 0.12344, "b": 0.12341, "c": 0.1, "d": 0.2, "e": 0.3}
    ranks = percentile_ranks(values, direction="higher", decimals=4)
    assert ranks["a"][0] == ranks["b"][0] == 3


# ------------------------------------------------------------------------ play universes


def test_play_universe_drops_two_point_tries_the_postseason_and_later_weeks():
    plays = skill_plays(_pbp(), season=_SEASON, through_week=_CUTOFF)
    assert set(plays["week"].unique().to_list()) == {1, 2}
    assert plays.filter(pl.col("season_type") != "REG").is_empty()
    assert plays.filter(pl.col("two_point_attempt") == 1.0).is_empty()


def test_a_renamed_play_by_play_column_is_a_contract_failure():
    with pytest.raises(ValueError, match="cpoe"):
        skill_plays(_pbp().drop("cpoe"), season=_SEASON, through_week=_CUTOFF)


# ------------------------------------------------------------------- hand-computed league


def test_official_totals_stay_official_and_efficiency_drops_kneels():
    result = _build()
    # Kneel-downs stay in official carries and yards (2 carries, 6 yards for Q in week 1).
    assert _reading(result, Q, "rushing_yards")["value"] == 6
    # Designed rushes exclude both the kneel and the scramble; scrambles count one.
    assert _reading(result, Q, "designed_rushes")["value"] == 0
    assert _reading(result, Q, "scrambles")["value"] == 1
    # R: three official carries for 17 yards; the two-point run is nowhere.
    assert _reading(result, R, "carries")["value"] == 3
    ypc = _reading(result, R, "yards_per_carry")
    assert ypc["value"] == pytest.approx(17 / 3, abs=0.005)
    assert (ypc["numerator"], ypc["denominator"]) == (17, 3)
    epa = _reading(result, R, "rush_epa_per_carry")
    assert epa["value"] == pytest.approx((0.6 + 0.3 - 0.3) / 3, abs=0.0005)
    success = _reading(result, R, "rush_success_rate")
    assert (success["numerator"], success["denominator"]) == (2, 3)
    assert _reading(result, R, "explosive_runs")["value"] == 1


def test_pass_efficiency_universes_reconcile_with_the_box_score():
    result = _build()
    epa = _reading(result, Q, "pass_epa_per_dropback")
    # ADR-091: passing EPA over attempts + sacks = (-0.8 + 0.1) / (5 + 1).
    assert epa["value"] == pytest.approx(-0.7 / 6, abs=0.0005)
    assert epa["denominator"] == 6
    sack = _reading(result, Q, "sack_rate")
    assert (sack["numerator"], sack["denominator"]) == (1, 6)
    success = _reading(result, Q, "dropback_success_rate")
    assert (success["numerator"], success["denominator"]) == (3, 6)


def test_a_spike_is_a_dropback_and_never_a_target():
    """nflverse counts a spike as an official attempt with no receiver and no probability."""
    plays = _pbp()
    spike = _play(
        week=2,
        posteam="MIN",
        play_type="qb_spike",
        pass_attempt=1.0,
        passer_player_id=Q,
        epa=-0.3,
    )
    base = _build()
    result = _build(pbp=pl.concat([plays, pl.DataFrame([spike], schema=plays.schema)]))
    before = _reading(base, Q, "dropback_success_rate")
    after = _reading(result, Q, "dropback_success_rate")
    # One more dropback, not a successful one.
    assert (after["numerator"], after["denominator"]) == (
        before["numerator"],
        before["denominator"] + 1,
    )
    # No receiver: no target moves; no completion probability: CPOE's attempts do not move.
    for receiver in (A, T):
        assert (
            _reading(result, receiver, "targets")["value"]
            == (_reading(base, receiver, "targets")["value"])
        )
    assert _reading(result, Q, "cpoe")["denominator"] == _reading(base, Q, "cpoe")["denominator"]


def test_cpoe_pools_over_attempts_not_over_weeks():
    result = _build()
    cpoe = _reading(result, Q, "cpoe")
    # Four attempts carry a probability: 30 - 60 + 20 + 5 = -5 over 4. The mean of the two
    # weekly means would be (-3.33 + 5) / 2 = +0.83 — a different, wrong number.
    assert cpoe["value"] == pytest.approx(-1.25)
    assert cpoe["denominator"] == 4
    assert cpoe["numerator"] is None


def test_shares_pool_over_his_games_and_a_trade_keeps_each_clubs_games():
    result = _build()
    # T: one target of MIN's three in week 1, one of GB's two in week 2: 2 / 5.
    traded = _reading(result, T, "target_share")
    assert (traded["numerator"], traded["denominator"]) == (2, 5)
    assert traded["value"] == pytest.approx(0.4)
    # A played both MIN games: 3 of 4.
    assert _reading(result, A, "target_share")["value"] == pytest.approx(0.75)
    # Red-zone targets: T's week-1 target at the 15 is one of MIN's one; GB's week-2 red-zone
    # target was C's, so T has 1 of 2.
    rz = _reading(result, T, "red_zone_target_share")
    assert (rz["numerator"], rz["denominator"]) == (1, 2)
    # Goal-line: R carried MIN's only non-kneel carry inside the 5.
    gl = _reading(result, R, "goal_line_carry_share")
    assert (gl["numerator"], gl["denominator"], gl["value"]) == (1, 1, 1.0)
    # C's week-2 target at the 10 travelled 25 air yards: an end-zone target.
    assert _reading(result, C, "end_zone_targets")["value"] == 1


def test_snap_share_pools_snaps_and_ignores_unbridged_rows():
    result = _build()
    share = _reading(result, A, "offense_snap_share")
    assert (share["numerator"], share["denominator"]) == (48 + 54, 120)
    assert result.metadata["diagnostics"]["unbridged_offense_snap_rows"] == 1


def test_zero_opportunity_below_minimum_and_presence_are_distinct_states():
    result = _build()
    b = _reading(result, B, "catch_rate")
    assert b["state"] == "no_opportunity" and b["value"] is None and b["denominator"] == 0
    assert _reading(result, B, "targets")["value"] == 0  # a real zero, ranked
    a = _reading(result, A, "catch_rate")
    assert a["state"] == "below_minimum"
    assert a["value"] == pytest.approx(2 / 3, abs=0.0001)
    assert a["rank"] is None and a["cohort_size"] is None
    never = [row for row in result.records if row["player_id"] == f"gsis:{NEVER}"]
    assert [(row["metric_id"], row["state"], row["value"]) for row in never] == [
        ("appearances", "no_appearances", 0),
    ]
    # D's week 2 is snaps only: a game with zero targets, not a missing week.
    assert _reading(result, D, "appearances")["value"] == 2


def test_volume_ranks_cover_every_appearing_player_with_zeros_included():
    result = _build()
    ranked = {gsis: _reading(result, gsis, "targets") for gsis in (A, B, C, D, T)}
    assert {gsis: row["rank"] for gsis, row in ranked.items()} == {A: 1, T: 2, C: 2, D: 4, B: 5}
    assert ranked[T]["percentile"] == 62.5
    assert all(row["cohort_size"] == 5 for row in ranked.values())
    # Two quarterbacks are too few to rank: values print, ranks do not.
    q = _reading(result, Q, "pass_attempts")
    assert q["state"] == "small_cohort" and q["value"] == 5 and q["rank"] is None


def test_nothing_after_the_cutoff_counts():
    result = _build()
    assert _reading(result, A, "targets")["value"] == 3
    assert _reading(result, Q, "passing_yards")["value"] == 38


# ------------------------------------------------------------------------- next gen stats


def test_ngs_uses_a_reconciled_season_summary_and_refuses_a_mismatch():
    result = _build()
    assert _reading(result, A, "yac_over_expected")["value"] == 1.25
    assert _reading(result, A, "yac_over_expected")["denominator"] == 2
    assert _reading(result, R, "rush_yards_over_expected_per_att")["value"] == 0.75
    assert _reading(result, Q, "avg_time_to_throw")["value"] == 2.81
    mismatch = _reading(result, C, "avg_separation")
    assert (mismatch["state"], mismatch["reason"]) == ("not_covered", "ngs_volume_mismatch")
    # D appears only in a postseason summary, which is never read.
    absent = _reading(result, D, "avg_separation")
    assert (absent["state"], absent["reason"]) == ("not_covered", "not_in_ngs_summary")


@pytest.mark.parametrize("last_week", [1, 3])
def test_ngs_that_does_not_end_at_the_cutoff_is_not_used(last_week: int):
    result = _build(nextgen=_nextgen(last_week=last_week))
    row = _reading(result, A, "yac_over_expected")
    assert (row["state"], row["value"], row["reason"]) == (
        "unavailable",
        None,
        "next_gen_stats_not_at_cutoff",
    )
    assert result.metadata["sources"]["next_gen_stats"]["status"] == "unavailable"
    # Every other reading is unaffected.
    assert _reading(result, A, "targets")["state"] == "ranked"


def test_ngs_can_be_switched_off():
    result = _build(ngs_published=False)
    assert _reading(result, A, "yac_over_expected")["reason"] == "next_gen_stats_not_published"


# --------------------------------------------------------------------------------- combine


def test_combine_cohort_is_every_tester_and_ambiguity_fails_closed():
    result = _build()
    a = _reading(result, A, "combine_forty")
    # WR testers since 2000: A 4.40, T's two rows 4.50/4.60, six unnamed. 4.30 and 4.35 are
    # faster; six are slower: rank 3, percentile 100 × 6 / 8.
    assert (a["value"], a["rank"], a["percentile"], a["cohort_size"]) == (4.4, 3, 75.0, 9)
    assert a["source_season"] == 2023
    t = _reading(result, T, "combine_forty")
    assert (t["state"], t["reason"]) == ("not_covered", "no_combine_forty")
    readings, cohorts = combine_readings(*_combine())
    assert T not in readings and len(cohorts["WR"]) == 9


# ------------------------------------------------------------------------ source failures


def test_a_failed_play_by_play_load_costs_its_readings_only():
    result = _build(pbp=None, pbp_error="ConnectionError: 500")
    row = _reading(result, R, "rush_success_rate")
    assert (row["state"], row["reason"]) == ("unavailable", "play_by_play_unavailable")
    assert _reading(result, R, "yards_per_carry")["state"] == "below_minimum"
    assert _reading(result, A, "targets")["state"] == "ranked"
    assert result.metadata["status"] == "published"


def test_play_by_play_missing_a_game_withholds_rather_than_shrinks():
    partial = _pbp().filter(~((pl.col("week") == 2) & (pl.col("posteam") == "GB")))
    result = _build(pbp=partial)
    assert result.metadata["sources"]["play_by_play"]["reason"] == "play_by_play_incomplete"
    assert _reading(result, T, "red_zone_targets")["state"] == "unavailable"


def test_weekly_stats_missing_a_team_week_withholds_box_score_readings():
    weekly = _weekly().filter(~((pl.col("week") == 2) & (pl.col("team") == "GB")))
    result = _build(weekly=weekly)
    assert result.metadata["sources"]["player_stats"]["reason"] == "player_stats_incomplete"
    assert _reading(result, A, "targets")["state"] == "unavailable"
    # Snap-based readings still publish.
    assert _reading(result, A, "offense_snap_share")["value"] is not None


def test_the_board_position_decides_the_tree():
    positions = dict(_POSITIONS)
    positions[f"gsis:{T}"] = "TE"
    result = _build(positions=positions)
    held = {row["metric_id"] for row in result.records if row["player_id"] == f"gsis:{T}"}
    assert held == {"appearances", "combine_forty", *metric_ids_for("TE")}


# ---------------------------------------------------------------------------- contract


def test_records_and_definitions_satisfy_their_schemas_and_the_validator():
    result = _build()
    for check in validate_records("player_skill_metric", result.records):
        assert check.status is CheckStatus.PASS, check
    for check in validate_records("skill_tree_definition", result.definitions):
        assert check.status is CheckStatus.PASS, check
    envelopes = {
        "player_skill_tree": {"records": result.records},
        "skill_tree_definitions": {"records": result.definitions},
    }
    checks = [
        *skilltree_record_checks(result.records, "test"),
        *skilltree_definition_checks(result.definitions, "test"),
        *skilltree_cross_checks(envelopes),
        *skilltree_metadata_checks(
            {"skill_tree": result.metadata, "through_week": _CUTOFF},
            envelopes,
        ),
    ]
    assert all(check.status is CheckStatus.PASS for check in checks), [
        check for check in checks if check.status is not CheckStatus.PASS
    ]


#: The characters the site's core font files cover (``web/src/styles/base.css``). A detail that
#: prints any other character downloads a second font file mid-interaction, measured at two
#: seconds on a throttled phone, or falls back to a system face.
_CORE_FONT = {chr(code) for code in range(0x20, 0x7F)} | set("\u00a0±·×–—‘’“”…‹›−")


def test_every_published_word_is_in_the_core_font_subset():
    result = _build()
    texts: list[str] = []
    for row in result.definitions:
        for value in row.values():
            if isinstance(value, str):
                texts.append(value)
            elif isinstance(value, list):
                texts.extend(str(item) for item in value)
    texts.extend(result.metadata["reasons"].values())
    texts.extend(REASONS.values())
    texts.extend([result.metadata["statement"], result.metadata["window"]])
    outside = sorted({char for text in texts for char in text if char not in _CORE_FONT})
    assert outside == []


def test_metadata_carries_exactly_the_reason_sentences_its_readings_use():
    """The block rides in the manifest on every first visit; the lazy tree reads it."""
    result = _build()
    used = {
        row["reason"]
        for row in result.records
        if row["reason"] is not None and not row["reason"].startswith("tested_as:")
    }
    assert used, "the fixture should carry at least one reason"
    assert set(result.metadata["reasons"]) == used
    envelopes = {
        "player_skill_tree": {"records": result.records},
        "skill_tree_definitions": {"records": result.definitions},
    }
    stripped = {**result.metadata, "reasons": {}}
    failed = [
        check
        for check in skilltree_metadata_checks(
            {"skill_tree": stripped, "through_week": _CUTOFF}, envelopes
        )
        if check.status is not CheckStatus.PASS
    ]
    assert failed and "reasons without a sentence" in failed[0].observed


def test_the_validator_catches_a_forged_rank_and_a_value_on_an_empty_state():
    result = _build()
    forged = [dict(row) for row in result.records]
    for row in forged:
        if row["player_id"] == f"gsis:{C}" and row["metric_id"] == "targets":
            row["rank"] = 1
        if row["player_id"] == f"gsis:{B}" and row["metric_id"] == "catch_rate":
            row["value"] = 0.0
    envelopes = {
        "player_skill_tree": {"records": forged},
        "skill_tree_definitions": {"records": result.definitions},
    }
    failed = {
        check.check_id
        for check in (*skilltree_record_checks(forged, "t"), *skilltree_cross_checks(envelopes))
        if check.status is not CheckStatus.PASS
    }
    assert "player_skill_tree.rank_rederivation" in failed
    assert "player_skill_tree.state_inconsistent" in failed


def test_the_validator_holds_games_to_the_season_actuals():
    result = _build()
    actuals = {
        "records": [
            {"player_id": f"gsis:{A}", "games_played": 3, "position": "WR"},
        ],
    }
    checks = skilltree_cross_checks(
        {
            "player_skill_tree": {"records": result.records},
            "skill_tree_definitions": {"records": result.definitions},
            "season_actuals": actuals,
        },
    )
    assert any(check.check_id == "player_skill_tree.actuals_disagree" for check in checks)


# ----------------------------------------------------------------------------- catalogue


def test_the_trees_are_adr_107s():
    nodes = {
        position: sum(len(branch.nodes) for branch in branches)
        for position, branches in TREES.items()
    }
    assert nodes == {"QB": 13, "RB": 13, "WR": 14, "TE": 13}
    assert all(len(branches) == 4 for branches in TREES.values())
    for position in TREES:
        for metric_id in metric_ids_for(position):
            metric = CATALOG[metric_id]
            assert len(metric.short_label) <= 16, metric_id
            assert metric.kind != "rate" or metric.den is not None or metric.cohort == "ngs"
    # WR and TE share statistics but not a tree.
    assert [b.id for b in TREES["WR"]] != [b.id for b in TREES["TE"]]


def test_no_model_or_decision_module_reads_the_skill_tree():
    from pathlib import Path

    root = Path(__file__).resolve().parents[2] / "src" / "ffdraft"
    readers = [
        path.relative_to(root).as_posix()
        for path in root.rglob("*.py")
        if "skilltree" in path.read_text(encoding="utf-8")
    ]
    allowed = {
        "signals/skilltree.py",
        "signals/skilltree_catalog.py",
        "artifacts/skilltree_checks.py",
        "artifacts/validate.py",
        "pipeline/ros.py",
        "pipeline/fixture_pipeline.py",
        "sources/nextgen.py",  # its docstring names the reader; it imports nothing of it
    }
    assert set(readers) <= allowed, sorted(set(readers) - allowed)
