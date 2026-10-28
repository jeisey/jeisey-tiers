"""Insights (ADR-116): every family on hand-calculated synthetic seasons, plus the guards.

Each scenario is a small league whose numbers can be checked by hand: filler players on their
own clubs give every cohort a population, and each story's subject sits on a club whose team
totals the scenario fixes, so a share is a fraction anyone can recompute. The claims:

* each family qualifies exactly the players its predicates describe, with exact evidence;
* byes, missed games, zero-point and snaps-only weeks stay distinct in every chart;
* an unknown or stale ESPN reading is never 0% and never passes a roster ceiling;
* a game that has kicked off, a designated-out player and a reserve list never make a
  this-week story; rows after the cutoff change nothing;
* selection is deterministic, one story per player, inside every cap;
* the validator refuses a tampered number, a forbidden claim and a broken identity.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

import polars as pl
import pytest

from ffdraft.artifacts import insight_checks
from ffdraft.artifacts.insight_checks import (
    insight_cross_checks,
    insight_metadata_checks,
    insight_record_checks,
)
from ffdraft.artifacts.schemas import record_schema_version, validate_records
from ffdraft.config import load_app_config
from ffdraft.contracts import CheckStatus
from ffdraft.contracts.normalized import (
    SCHEDULE_CONTRACT,
    SNAP_COUNTS_CONTRACT,
    WEEKLY_STATS_CONTRACT,
)
from ffdraft.insights import INSIGHT_RULE, SELECTION_RULE, InsightsResult, build_insights
from ffdraft.insights.families import Draft
from ffdraft.insights.rules import FORBIDDEN_PHRASES
from ffdraft.insights.select import select
from ffdraft.signals.actuals import build_season_actuals
from ffdraft.signals.recent import build_recent_form
from ffdraft.signals.usage import build_player_usage_records

SEASON = 2026
THROUGH = 7
TEAMS = ("MIN", "GB", "DET", "CHI", "NYJ", "BUF", "NE", "MIA")
BUILT = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)
KICKOFF = "2026-11-01T18:00:00Z"
STAT_FIELDS = (
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


class League:
    """Accumulates synthetic nflverse rows and the published records a build would hold."""

    def __init__(self, byes: Mapping[int, Sequence[str]] | None = None) -> None:
        self.stats: list[dict[str, Any]] = []
        self.snaps: list[dict[str, Any]] = []
        self.byes = {week: set(teams) for week, teams in (byes or {}).items()}
        self.subjects: dict[str, dict[str, str]] = {}
        self.espn: list[dict[str, Any]] = []
        self.weekly: list[dict[str, Any]] = []
        self.board: list[dict[str, Any]] = []
        self.context: list[dict[str, Any]] = []

    def play(
        self,
        gsis: str,
        team: str,
        position: str,
        weeks: Sequence[int],
        *,
        snap: float | None = 0.6,
        subject: bool = True,
        **values: float,
    ) -> str:
        for week in weeks:
            assert team not in self.byes.get(week, set()), "a player cannot play on a bye"
            row: dict[str, Any] = {
                "season": SEASON,
                "week": week,
                "season_type": "REG",
                "gsis_id": gsis,
                "display_name": f"P {gsis[-4:]}",
                "position": position,
                "team": team,
                "opponent_team": None,
            }
            for name in STAT_FIELDS:
                row[name] = float(values.get(name, 0.0))
            row["passing_epa"] = None
            row["sacks_suffered"] = 0.0
            self.stats.append(row)
            if snap is not None:
                self.snaps.append(self._snap(week, gsis, team, position, snap))
        player_id = f"gsis:{gsis}"
        if subject:
            self.subjects[player_id] = {"display_name": f"P {gsis[-4:]}", "position": position}
        return player_id

    def snaps_only(self, gsis: str, team: str, position: str, week: int, pct: float) -> None:
        self.snaps.append(self._snap(week, gsis, team, position, pct))

    @staticmethod
    def _snap(week: int, gsis: str, team: str, position: str, pct: float) -> dict[str, Any]:
        return {
            "season": SEASON,
            "week": week,
            "game_type": "REG",
            "pfr_player_id": f"pfr-{gsis}-{week}",
            "player_name": f"P {gsis[-4:]}",
            "position": position,
            "team": team,
            "offense_snaps": 40.0,
            "offense_pct": pct,
            "gsis_id": gsis,
        }

    def fillers(
        self, position: str, count: int, *, base: float, step: float, targets: float = 6.0
    ) -> None:
        """``count`` steady players on NE and MIA: filler i catches 4 for (base − step·i)·10 yds."""
        for index in range(count):
            team = "NE" if index % 2 == 0 else "MIA"
            yards = round((base - step * index - 4.0) * 10, 1)
            self.play(
                f"00-09{position}{index:03d}",
                team,
                position,
                range(1, THROUGH + 1),
                subject=False,
                targets=targets,
                receptions=4.0,
                receiving_yards=yards,
            )

    def schedule(self, weeks: int = THROUGH + 1) -> pl.DataFrame:
        """Games for the clubs that field players (an empty club would fail completeness)."""
        fielded = {row["team"] for row in self.stats} | {row["team"] for row in self.snaps}
        rows = []
        for week in range(1, weeks + 1):
            playing = [t for t in TEAMS if t in fielded and t not in self.byes.get(week, set())]
            if len(playing) % 2:
                playing.append(playing[-1])  # an odd club plays itself: scheduled, not a bye
            for slot in range(0, len(playing) - 1, 2):
                rows.append(
                    {
                        "game_id": f"{SEASON}_{week:02d}_{playing[slot]}_{playing[slot + 1]}",
                        "season": SEASON,
                        "game_type": "REG",
                        "week": week,
                        "gameday": None,
                        "gametime": None,
                        "away_team": playing[slot],
                        "home_team": playing[slot + 1],
                    },
                )
        return SCHEDULE_CONTRACT.build(rows)

    def rostered(self, player_id: str, percent: float | None, state: str = "observed") -> None:
        self.espn.append(
            {
                "player_id": player_id,
                "reading_state": state,
                "percent_rostered": percent,
                "observed_at_utc": "2026-10-27T11:30:00Z",
            },
        )

    def projection(
        self,
        player_id: str,
        team: str,
        position: str,
        *,
        q: tuple[float, float, float],
        typical: tuple[float, float, float] | None = None,
        state: str = "upcoming",
        kickoff: str = KICKOFF,
        designation: str | None = None,
    ) -> None:
        q10, q50, q90 = q
        for preset in ("STD", "HALF", "PPR"):
            self.weekly.append(
                {
                    "player_id": player_id,
                    "scoring_preset": preset,
                    "target_week": THROUGH + 1,
                    "team": team,
                    "position": position,
                    "model_version": "weekly-startsit-v1",
                    "game_state": state,
                    "game": {"kickoff_utc": kickoff, "opponent": "XXX", "home_away": "home"},
                    "quantiles": {
                        "q05": q10 - 1,
                        "q10": q10,
                        "q25": (q10 + q50) / 2,
                        "q50": q50,
                        "q75": (q50 + q90) / 2,
                        "q90": q90,
                        "q95": q90 + 1,
                    },
                    "explanation": None
                    if typical is None
                    else {
                        level: {
                            "typical": value,
                            "terms": {
                                "lines": 0.5,
                                "home": 0.0,
                                "rest": 0.0,
                                "roof": 0.0,
                                "opponent": round(q[i] - value - 0.5, 2),
                            },
                        }
                        for i, (level, value) in enumerate(
                            zip(("q10", "q50", "q90"), typical, strict=True)
                        )
                    },
                    "injury": None
                    if designation is None
                    else {
                        "week": THROUGH + 1,
                        "designation": designation,
                        "practice_status": None,
                        "primary_injury": "Knee",
                    },
                },
            )

    def build(
        self,
        *,
        through: int = THROUGH,
        generated: datetime = BUILT,
        plays: pl.DataFrame | None = None,
    ) -> tuple[InsightsResult, dict[str, list[dict[str, Any]]]]:
        snap_frame = SNAP_COUNTS_CONTRACT.build(
            [{k: v for k, v in row.items() if k != "gsis_id"} for row in self.snaps],
        ).with_columns(
            pl.Series("gsis_id", [row["gsis_id"] for row in self.snaps], dtype=pl.String)
        )
        weekly = WEEKLY_STATS_CONTRACT.build(self.stats)
        schedule = self.schedule()
        scoring = load_app_config().league.scoring
        actuals = build_season_actuals(
            weekly=weekly,
            snap_counts=snap_frame,
            schedule=schedule,
            scoring=scoring,
            season=SEASON,
            through_week=through,
            positions={},
            include=(),
            build_id="test",
            schema_version=record_schema_version("season_actuals_record"),
        )
        recent = build_recent_form(
            weekly=weekly,
            snap_counts=snap_frame,
            schedule=schedule,
            scoring=scoring,
            season=SEASON,
            through_week=through,
            actuals=actuals,
            build_id="test",
            schema_version=record_schema_version("recent_form_record"),
        )
        usage = build_player_usage_records(
            players=self.subjects,
            weekly=weekly,
            snap_counts=snap_frame,
            schedule=schedule,
            scoring=scoring,
            season=SEASON,
            through_week=through,
            build_id="test",
            schema_version=record_schema_version("player_usage"),
        )
        records: dict[str, list[dict[str, Any]]] = {
            "player_usage": usage,
            "season_actuals": actuals.records,
            "recent_form": recent.records,
            "weekly_projections": self.weekly,
            "espn_ownership": self.espn,
            "inseason_opportunity": self.board,
            "weekly_context": self.context,
            "team_matchups": [
                {
                    "team": team,
                    "week": THROUGH + 1,
                    "lines_retrieved_at_utc": "2026-10-27T11:00:00Z",
                }
                for team in TEAMS
            ],
        }
        result = build_insights(
            weekly=weekly,
            snap_counts=snap_frame,
            schedule=schedule,
            scoring=scoring,
            season=SEASON,
            through_week=through,
            records=records,
            plays=plays,
            plays_error=None,
            generated_at=generated,
            build_id="test",
            schema_version=record_schema_version("insight_story"),
        )
        return result, records


def stories(
    result: InsightsResult, family: str | None = None, preset: str = "PPR"
) -> list[dict[str, Any]]:
    return [
        r
        for r in result.records
        if r["scoring_preset"] == preset and (family is None or r["family"] == family)
    ]


def story(result: InsightsResult, story_id: str, preset: str = "PPR") -> dict[str, Any]:
    matches = [r for r in stories(result, preset=preset) if r["story_id"] == story_id]
    assert len(matches) == 1, [r["story_id"] for r in stories(result, preset=preset)]
    return matches[0]


def passed(checks: Sequence[Any]) -> bool:
    return all(check.status is not CheckStatus.FAIL for check in checks)


# ======================================================================== volume_vs_results


@pytest.fixture(scope="module")
def volume() -> tuple[InsightsResult, dict[str, list[dict[str, Any]]]]:
    """LAG: 12 targets a game at 6.5 PPR points. SHR: 30% → 13% of GB's 30 targets a game."""
    league = League()
    league.fillers("WR", 20, base=10.0, step=0.2)  # filler i scores 10 − 0.2·i PPR
    weeks = range(1, THROUGH + 1)
    lag = league.play(
        "00-0000001", "MIN", "WR", weeks, targets=12.0, receptions=4.0, receiving_yards=25.0
    )
    league.play(
        "00-0000002",
        "MIN",
        "WR",
        weeks,
        subject=False,
        targets=12.0,
        receptions=8.0,
        receiving_yards=100.0,
    )
    league.play(
        "00-0000003", "GB", "WR", range(1, 5), targets=9.0, receptions=6.0, receiving_yards=80.0
    )
    shr = "gsis:00-0000003"
    league.play(
        "00-0000003",
        "GB",
        "WR",
        range(5, THROUGH + 1),
        subject=True,
        targets=4.0,
        receptions=3.0,
        receiving_yards=30.0,
    )
    league.play(
        "00-0000004",
        "GB",
        "WR",
        range(1, 5),
        subject=False,
        targets=21.0,
        receptions=15.0,
        receiving_yards=150.0,
    )
    league.play(
        "00-0000004",
        "GB",
        "WR",
        range(5, THROUGH + 1),
        subject=False,
        targets=26.0,
        receptions=15.0,
        receiving_yards=150.0,
    )
    league.rostered(lag, 95.0)
    league.rostered(shr, 60.0)
    return league.build()


def test_lagging_workload_has_exact_ranks_and_shares(volume):
    result, _ = volume
    record = story(result, "volume-00-0000001")
    e = record["evidence"]
    assert record["variant"] == "lagging"
    # Cohort: 20 fillers, LAG, his teammate, SHR and SHR's teammate — every WR with 2+ games.
    assert e["cohort_size"] == 24
    # Workload: SHR's teammate 26 a game is first; LAG and his teammate share second at 12.
    assert (e["window_opportunities"], e["window_opportunities_per_game"]) == (36.0, 12.0)
    assert e["workload_rank"] == 2
    # Production: the two teammates (30.0, 18.0) and 18 fillers above 6.5 → 21st.
    assert (e["window_points"], e["window_points_per_game"]) == (19.5, 6.5)
    assert e["production_rank"] == 21
    assert e["gap_places"] == 19
    # 36 of MIN's 72 targets; 75 yards on 36 targets.
    assert (e["window_share"], e["window_share_numerator"], e["window_share_denominator"]) == (
        0.5,
        36.0,
        72.0,
    )
    assert e["yards_per_opportunity"] == 2.1
    assert e["window_td_points"] == 0.0
    assert record["headline"] == "P 0001: 12.0 targets a game (WR2), 6.5 points a game (WR21)"
    assert record["window"] == {
        "label": "W5–W7",
        "first_week": 5,
        "last_week": 7,
        "weeks": 3,
        "baseline_first_week": 1,
        "baseline_last_week": 4,
    }


def test_shrinking_role_reads_the_pooled_share(volume):
    result, _ = volume
    record = story(result, "volume-00-0000003")
    e = record["evidence"]
    assert record["variant"] == "shrinking"
    # 36 of 120 targets before (0.300), 12 of 90 in the window (0.133).
    assert (e["baseline_share"], e["window_share"]) == (0.3, 0.133)
    assert record["headline"] == "P 0003's target share fell from 30% to 13% over W5–W7"
    assert [q["rule"] for q in record["qualification"]] == [
        "window_games",
        "baseline_games",
        "baseline_role",
        "share_drop",
    ]


def test_a_heavily_rostered_disappointment_leads_its_variant(volume):
    result, _ = volume
    lagging = [r for r in stories(result, "volume_vs_results") if r["variant"] == "lagging"]
    assert lagging[0]["story_id"] == "volume-00-0000001"
    assert lagging[0]["evidence"]["espn_rostered"] == 95.0


def test_volume_strip_marks_every_week_and_sums_to_the_window(volume):
    result, _ = volume
    weeks = story(result, "volume-00-0000001")["chart"]["weeks"]
    assert [w["week"] for w in weeks] == list(range(1, THROUGH + 1))
    assert all(w["status"] == "P" for w in weeks)
    assert sum(w["points"] for w in weeks if w["in_window"]) == pytest.approx(19.5)


# ============================================================================ weekly_upside


@pytest.fixture(scope="module")
def upside() -> tuple[InsightsResult, dict[str, list[dict[str, Any]]]]:
    league = League()
    league.fillers("WR", 10, base=9.0, step=0.2)
    weeks = range(1, THROUGH + 1)
    # DET: UPS draws 8 of 30 targets a game (0.267, a substantial role).
    ups = league.play(
        "00-0000010", "DET", "WR", weeks, targets=8.0, receptions=5.0, receiving_yards=60.0
    )
    league.play(
        "00-0000011",
        "DET",
        "WR",
        weeks,
        subject=False,
        targets=22.0,
        receptions=10.0,
        receiving_yards=90.0,
    )
    # The same role on four other clubs, each excluded for one reason.
    gone = {}
    for gsis, team in (
        ("00-0000012", "CHI"),
        ("00-0000013", "BUF"),
        ("00-0000014", "NYJ"),
        ("00-0000015", "GB"),
    ):
        gone[team] = league.play(
            gsis, team, "WR", weeks, targets=8.0, receptions=5.0, receiving_yards=60.0
        )
        league.play(
            f"{gsis}9",
            team,
            "WR",
            weeks,
            subject=False,
            targets=22.0,
            receptions=10.0,
            receiving_yards=90.0,
        )
    league.rostered(ups, 20.0)
    league.rostered(gone["CHI"], 50.0)  # at the ceiling, not below it
    league.rostered(gone["BUF"], 10.0)
    league.rostered(gone["NYJ"], 5.0)
    league.rostered(gone["GB"], None, state="stale")  # unknown is not 0%
    league.projection(ups, "DET", "WR", q=(2.5, 9.0, 18.0), typical=(2.0, 8.5, 16.5))
    league.projection(gone["CHI"], "CHI", "WR", q=(3.0, 10.0, 21.0))
    league.projection(
        gone["BUF"],
        "BUF",
        "WR",
        q=(3.0, 10.0, 21.0),
        state="kicked_off",
        kickoff="2026-10-26T17:00:00Z",
    )
    league.projection(gone["NYJ"], "NYJ", "WR", q=(3.0, 10.0, 21.0), designation="Out")
    league.projection(gone["GB"], "GB", "WR", q=(3.0, 10.0, 21.0))
    return league.build()


def test_upside_takes_only_an_eligible_fresh_low_rostered_role(upside):
    result, _ = upside
    found = stories(result, "weekly_upside")
    assert [r["story_id"] for r in found] == ["upside-00-0000010"]
    record = found[0]
    e = record["evidence"]
    assert (e["q10"], e["q50"], e["q90"]) == (2.5, 9.0, 18.0)
    assert e["matchup_delta_q90"] == 1.5
    assert e["ceiling_ranks"] == {"50": 1, "25": 1, "10": None}
    assert e["role_metric"] == "target_share" and e["role_level"] == 0.267
    assert record["horizon"] == "this_week" and record["kickoff_utc"] == KICKOFF
    assert record["headline"] == "P 0010: a 18.0-point ceiling at 20% rostered"
    assert "not a 90% chance" in record["caveat"]


def test_upside_counts_the_prescreen_refusal(upside):
    result, _ = upside
    suppressed = result.metadata["families"]["weekly_upside"]["suppressed"]
    assert suppressed.get("prescreen") == 3  # the designated-Out player, once per preset


def test_a_kickoff_before_the_build_is_never_a_this_week_story(upside):
    result, _ = upside
    for record in result.records:
        if record["kickoff_utc"] is not None:
            assert datetime.fromisoformat(record["kickoff_utc"].replace("Z", "+00:00")) > BUILT


def test_upside_without_espn_is_unavailable_and_says_why():
    league = League()
    league.fillers("WR", 4, base=9.0, step=0.2)
    ups = league.play(
        "00-0000010",
        "DET",
        "WR",
        range(1, THROUGH + 1),
        targets=8.0,
        receptions=5.0,
        receiving_yards=60.0,
    )
    league.play("00-0000011", "DET", "WR", range(1, THROUGH + 1), subject=False, targets=22.0)
    league.projection(ups, "DET", "WR", q=(2.5, 9.0, 18.0))
    result, _ = league.build()
    family = result.metadata["families"]["weekly_upside"]
    assert family["status"] == "unavailable" and "ESPN" in family["reason"]
    assert result.metadata["status"] == "published"


# ====================================================================== opportunity_opening


@pytest.fixture(scope="module")
def opening() -> tuple[InsightsResult, dict[str, list[dict[str, Any]]]]:
    """CHI: ABS (8 of 30 targets) misses W6–W7; NXT goes from 4 of 30 to 10 of 30 without him."""
    league = League()
    league.fillers("WR", 6, base=9.0, step=0.2)
    absent = league.play(
        "00-0000020", "CHI", "TE", range(1, 6), targets=8.0, receptions=5.0, receiving_yards=50.0
    )
    nxt = league.play(
        "00-0000021", "CHI", "WR", range(1, 6), targets=4.0, receptions=3.0, receiving_yards=30.0
    )
    league.play(
        "00-0000021",
        "CHI",
        "WR",
        range(6, THROUGH + 1),
        targets=10.0,
        receptions=6.0,
        receiving_yards=70.0,
    )
    league.play(
        "00-0000022",
        "CHI",
        "WR",
        range(1, THROUGH + 1),
        subject=False,
        targets=18.0,
        receptions=9.0,
        receiving_yards=90.0,
    )
    league.play("00-0000023", "CHI", "TE", range(6, THROUGH + 1), subject=False, targets=2.0)
    league.rostered(nxt, 12.0)
    del absent
    return league.build()


def test_observed_opening_quantifies_with_and_without(opening):
    result, _ = opening
    record = story(result, "opening-00-0000020")
    e = record["evidence"]
    assert record["variant"] == "observed" and record["horizon"] == "role_watch"
    assert record["player_id"] == "gsis:00-0000021"
    # ABS: 40 of 150 CHI targets over his 5 games.
    assert (e["absent_share"], e["absent_games"], e["absent_per_game"]) == (0.267, 5, 8.0)
    # NXT: 20 of 150 with him (0.133), 20 of 60 without (0.333), exactly two games.
    assert (e["share_with"], e["games_with"]) == (0.133, 5)
    assert (e["share_without"], e["games_without"]) == (0.333, 2)
    assert e["missed_weeks"] == [6, 7]
    assert record["counterpoint"].startswith("2 games without him")
    assert record["headline"] == "Without P 0020, P 0021's share of CHI targets rose to 33%"


def test_an_absence_that_began_before_the_window_is_not_an_opening():
    league = League()
    league.fillers("WR", 4, base=9.0, step=0.2)
    league.play("00-0000020", "CHI", "TE", range(1, 4), targets=8.0)  # last played W3
    league.play("00-0000021", "CHI", "WR", range(1, 4), targets=4.0)
    league.play("00-0000021", "CHI", "WR", range(4, THROUGH + 1), targets=10.0)
    league.play("00-0000022", "CHI", "WR", range(1, THROUGH + 1), subject=False, targets=18.0)
    result, _ = league.build()
    assert stories(result, "opportunity_opening") == []


def test_a_documented_absence_is_prospective_and_states_the_unknown():
    league = League()
    league.fillers("WR", 4, base=9.0, step=0.2)
    absent = league.play("00-0000020", "CHI", "WR", range(1, THROUGH + 1), targets=9.0)
    nxt = league.play("00-0000021", "CHI", "WR", range(1, THROUGH + 1), targets=6.0)
    league.play("00-0000022", "CHI", "WR", range(1, THROUGH + 1), subject=False, targets=15.0)
    league.context.append(
        {
            "team": "CHI",
            "lineup": {
                "report_available": True,
                "report_final": True,
                "listed": [{"player_id": absent, "designation": "Out"}],
            },
        },
    )
    league.projection(nxt, "CHI", "WR", q=(2.0, 8.0, 17.0))
    result, _ = league.build()
    record = story(result, "opening-00-0000020")
    assert record["variant"] == "prospective" and record["horizon"] == "this_week"
    assert record["evidence"]["games_without"] == 0
    assert record["headline"] == "P 0020 (30% of CHI targets) is listed Out for week 8"
    assert "has not played without him" in record["counterpoint"]
    assert "nflverse_injuries" in record["sources"]


# =============================================================================== role_battle


@pytest.fixture(scope="module")
def backfield() -> tuple[InsightsResult, dict[str, list[dict[str, Any]]]]:
    """GB backs: R1 14 → 6 of 20 carries; R2 4 → 12; R3 2 of 20 throughout."""
    league = League()
    league.fillers("RB", 6, base=9.0, step=0.2, targets=1.0)
    league.play("00-0000031", "GB", "RB", range(1, 5), carries=14.0, rushing_yards=60.0, snap=0.7)
    league.play(
        "00-0000031", "GB", "RB", range(5, THROUGH + 1), carries=6.0, rushing_yards=25.0, snap=0.4
    )
    league.play("00-0000032", "GB", "RB", range(1, 5), carries=4.0, rushing_yards=15.0, snap=0.25)
    league.play(
        "00-0000032", "GB", "RB", range(5, THROUGH + 1), carries=12.0, rushing_yards=55.0, snap=0.55
    )
    league.play(
        "00-0000033", "GB", "RB", range(1, THROUGH + 1), carries=2.0, rushing_yards=8.0, snap=0.1
    )
    return league.build()


def test_role_battle_counts_reconcile_to_team_carries(backfield):
    result, _ = backfield
    record = story(result, "role-gb-backfield")
    chart = record["chart"]
    assert record["player_id"] == "gsis:00-0000032"
    assert (chart["team_count"], chart["team_games"]) == (60, 3)
    rows = {row["player_id"]: row for row in chart["rows"]}
    assert [row["player_id"] for row in chart["rows"]] == [
        "gsis:00-0000032",
        "gsis:00-0000031",
        "gsis:00-0000033",
    ]
    assert (rows["gsis:00-0000032"]["count"], rows["gsis:00-0000032"]["share"]) == (36, 0.6)
    assert rows["gsis:00-0000032"]["share_baseline"] == 0.2
    assert (rows["gsis:00-0000031"]["share"], rows["gsis:00-0000031"]["share_baseline"]) == (
        0.3,
        0.7,
    )
    assert sum(row["count"] for row in chart["rows"]) == chart["team_count"]
    # Snap shares overlap and are never stacked: they are not required to sum to anything.
    assert rows["gsis:00-0000032"]["snap_share"] == 0.55


def test_role_battles_are_identical_in_every_preset(backfield):
    result, _ = backfield
    # Present wherever the riser has no story in a higher-priority family (one per player).
    per_preset = [
        r
        for preset in ("STD", "HALF", "PPR")
        for r in stories(result, "role_battle", preset)
        if r["story_id"] == "role-gb-backfield"
    ]
    assert per_preset
    volatile = {"scoring_preset", "lead_rank", "family_rank", "also_qualifies"}
    stripped = [{k: v for k, v in r.items() if k not in volatile} for r in per_preset]
    assert all(row == stripped[0] for row in stripped)
    assert per_preset[0]["scoring_dependent"] is False


def test_red_zone_counts_come_from_complete_play_by_play_only(backfield):
    result, _ = backfield
    assert story(result, "role-gb-backfield")["chart"]["team_red_zone"] is None
    assert result.metadata["sources"]["nflverse_pbp"]["state"] == "unavailable"


# ============================================================================== streak_watch


@pytest.fixture(scope="module")
def streak() -> tuple[InsightsResult, dict[str, list[dict[str, Any]]]]:
    """HOT: three top-6 TE weeks on 2 of 30 NYJ targets and a 40% snap share."""
    league = League()
    for index in range(30):  # TE i scores 15 − 0.4·i every week on 2 targets
        team = "NE" if index % 2 == 0 else "MIA"
        yards = round((15 - 0.4 * index - 2.0) * 10, 1)
        league.play(
            f"00-09TE{index:03d}",
            team,
            "TE",
            range(1, THROUGH + 1),
            subject=False,
            targets=2.0,
            receptions=2.0,
            receiving_yards=yards,
        )
    league.play(
        "00-0000040",
        "NYJ",
        "TE",
        range(1, 5),
        targets=2.0,
        receptions=1.0,
        receiving_yards=5.0,
        snap=0.4,
    )
    league.play(
        "00-0000040",
        "NYJ",
        "TE",
        range(5, THROUGH + 1),
        targets=2.0,
        receptions=2.0,
        receiving_yards=50.0,
        receiving_tds=1.0,
        snap=0.4,
    )
    league.play(
        "00-0000041",
        "NYJ",
        "WR",
        range(1, THROUGH + 1),
        subject=False,
        targets=28.0,
        receptions=10.0,
    )
    return league.build()


def test_production_without_role_reuses_breakout_v1(streak):
    result, records = streak
    record = story(result, "streak-00-0000040")
    e = record["evidence"]
    assert record["variant"] == "production_without_role"
    assert (e["category"], e["reason"], e["streak"]) == ("eyebrow", "role_not_confirmed", 3)
    # 3 × (2 + 5 + 6) = 39 points, 18 of them touchdowns: 46%.
    assert (e["window_points"], e["window_td_points"], e["td_share"]) == (39.0, 18.0, 46)
    recent = next(
        r
        for r in records["recent_form"]
        if r["player_id"] == "gsis:00-0000040" and r["scoring_preset"] == "PPR"
    )
    assert e["window_rank"] == recent["windows"]["3"]["rank"]
    strong = [w for w in record["chart"]["weeks"] if w["in_window"]]
    assert all(w["rank"] is not None and w["rank"] <= record["chart"]["band"] for w in strong)


# =========================================================================== pace_perspective


@pytest.fixture(scope="module")
def pace() -> tuple[InsightsResult, dict[str, list[dict[str, Any]]]]:
    """PACE plays three BUF games at 22 PPR points; fillers score 12 − 0.3·i every week."""
    league = League(byes={3: ("BUF", "NYJ")})
    league.fillers("WR", 20, base=12.0, step=0.3)
    league.play(
        "00-0000050", "BUF", "WR", (1, 6, 7), targets=8.0, receptions=8.0, receiving_yards=140.0
    )
    league.play("00-0000051", "BUF", "TE", (1, 2, 4, 5, 6, 7), subject=False, targets=4.0)
    return league.build()


def test_per_game_hidden_compares_like_with_like(pace):
    result, _ = pace
    record = story(result, "pace-00-0000050")
    e = record["evidence"]
    assert record["variant"] == "per_game_hidden"
    # 3 games of BUF's 6 (W3 is a bye, not a missed game).
    assert (e["games"], e["team_games"], e["missed_games"]) == (3, 6, 3)
    assert (e["points"], e["points_per_game"], e["pace"]) == (66.0, 22.0, 374.0)
    # Per game he is first of 21 WRs with 3+ games; nine fillers out-total his 66.
    assert (e["ppg_rank"], e["total_rank"], e["cohort_size"]) == (1, 10, 21)
    assert record["headline"] == "P 0050: WR1 in points a game, WR10 in total"
    statuses = {
        w["week"]: w["status"] for w in story(result, "pace-00-0000050")["chart"].get("weeks", [])
    }
    assert statuses == {}  # a stat line, not a strip


def test_bye_missed_game_and_zero_stay_distinct():
    league = League(byes={3: ("MIN", "GB")})
    league.fillers("WR", 24, base=10.0, step=0.2)
    weeks = (1, 2, 5, 6, 7)
    league.play(
        "00-0000060", "MIN", "WR", weeks, targets=12.0, receptions=4.0, receiving_yards=20.0
    )
    league.play("00-0000060", "MIN", "WR", (4,), targets=3.0)  # a zero-point game, still a game
    league.play("00-0000061", "MIN", "WR", (1, 2, 4, 5, 6, 7), subject=False, targets=12.0)
    league.play("00-0000062", "GB", "WR", (1, 2, 4, 5, 6, 7), subject=False, targets=6.0)
    league.rostered("gsis:00-0000060", 90.0)
    result, _ = league.build()
    record = story(result, "volume-00-0000060")
    status = {w["week"]: (w["status"], w["points"]) for w in record["chart"]["weeks"]}
    assert status[3] == ("B", None)
    assert status[4] == ("P", 0.0)
    assert all(status[w][0] == "P" for w in weeks)


def test_a_snaps_only_week_is_an_appearance_with_zero_counts():
    league = League()
    league.fillers("WR", 24, base=10.0, step=0.2)
    league.play(
        "00-0000070",
        "MIN",
        "WR",
        (1, 2, 3, 4, 5, 6),
        targets=12.0,
        receptions=4.0,
        receiving_yards=20.0,
    )
    league.snaps_only("00-0000070", "MIN", "WR", 7, 0.7)
    league.play("00-0000071", "MIN", "WR", range(1, THROUGH + 1), subject=False, targets=12.0)
    result, _ = league.build()
    for record in stories(result):
        if record["player_id"] == "gsis:00-0000070" and record["chart"]["type"] == "week_strip":
            w7 = record["chart"]["weeks"][-1]
            assert (w7["status"], w7["points"], w7["opportunity"]) == ("P", 0.0, 0.0)


# =============================================================================== guards


def test_rows_after_the_cutoff_change_nothing(volume):
    league = League()
    league.fillers("WR", 20, base=10.0, step=0.2)
    league.play(
        "00-0000001",
        "MIN",
        "WR",
        range(1, THROUGH + 2),
        targets=12.0,
        receptions=4.0,
        receiving_yards=25.0,
    )
    league.play(
        "00-0000002",
        "MIN",
        "WR",
        range(1, THROUGH + 2),
        subject=False,
        targets=12.0,
        receptions=8.0,
        receiving_yards=100.0,
    )
    with_future, _ = league.build()
    league.stats = [row for row in league.stats if row["week"] <= THROUGH]
    league.snaps = [row for row in league.snaps if row["week"] <= THROUGH]
    without_future, _ = league.build()
    assert with_future.records == without_future.records


def test_the_build_is_deterministic(volume):
    result, records = volume
    league_again = League()
    league_again.fillers("WR", 20, base=10.0, step=0.2)
    assert result.records == volume[0].records
    del records, league_again


def test_reserve_list_subjects_get_no_watch_story():
    league = League()
    league.fillers("WR", 20, base=10.0, step=0.2)
    lag = league.play(
        "00-0000001",
        "MIN",
        "WR",
        range(1, THROUGH + 1),
        targets=12.0,
        receptions=4.0,
        receiving_yards=25.0,
    )
    league.play(
        "00-0000002",
        "MIN",
        "WR",
        range(1, THROUGH + 1),
        subject=False,
        targets=12.0,
        receptions=8.0,
        receiving_yards=100.0,
    )
    league.board.append({"player_id": lag, "current_status": "RES", "employment_status": "signed"})
    result, _ = league.build()
    assert not [r for r in stories(result) if r["player_id"] == lag]
    assert (
        result.metadata["families"]["volume_vs_results"]["suppressed"]["subject_unavailable"] == 3
    )


def test_a_withheld_core_input_withholds_every_story():
    league = League()
    league.fillers("WR", 4, base=10.0, step=0.2)
    league.subjects = {}
    result, _ = league.build()
    assert result.records == [] and result.metadata["status"] == "withheld"
    assert all(f["status"] == "unavailable" for f in result.metadata["families"].values())


# ============================================================================ selection


def _draft(
    family: str, variant: str, pid: str, team: str, order: int, position: str = "WR"
) -> Draft:
    return Draft(
        family=family,
        variant=variant,
        horizon="role_watch",
        nature="fact",
        player_id=f"gsis:{pid}",
        position=position,
        team=team,
        subject=pid,
        order=(order,),
        evidence={},
        chart={},
        qualification=[],
        sources=[],
        window=None,
    )


def test_selection_is_round_robin_capped_and_one_story_per_player():
    drafts = {
        "weekly_upside": [
            _draft("weekly_upside", "ceiling", f"00-1{i}", "DET" if i < 3 else f"T{i}", i)
            for i in range(5)
        ],
        "volume_vs_results": [
            _draft(
                "volume_vs_results", "lagging", "00-10", "DET", 0
            ),  # same player as an upside story
            _draft("volume_vs_results", "shrinking", "00-20", "GB", 0),
            _draft("volume_vs_results", "lagging", "00-21", "GB", 1),
        ],
        "pace_perspective": [
            _draft("pace_perspective", "overlooked", f"00-3{i}", f"P{i}", i) for i in range(3)
        ],
    }
    chosen = select(drafts, rule=INSIGHT_RULE, selection=SELECTION_RULE)
    ids = [d.story_id for d in chosen.stories]
    assert "volume-00-10" not in ids and chosen.also["upside-00-10"] == ["volume-00-10"]
    lead = sorted(chosen.lead_rank, key=chosen.lead_rank.__getitem__)
    # Upside DET#1, volume (shrinking #1 follows the deduplicated lagging #1), pace; …
    assert lead[:3] == ["upside-00-10", "volume-00-20", "pace-00-30"]
    families = [d.family for d in chosen.stories if d.story_id in chosen.lead_rank]
    assert families.count("weekly_upside") <= SELECTION_RULE.family_caps["weekly_upside"]
    assert families.count("pace_perspective") == 1
    teams = [d.team for d in chosen.stories if d.story_id in chosen.lead_rank]
    assert max(teams.count(team) for team in set(teams)) <= SELECTION_RULE.team_cap
    again = select(drafts, rule=INSIGHT_RULE, selection=SELECTION_RULE)
    assert again.lead_rank == chosen.lead_rank


# ============================================================================ validator


def test_validator_constants_match_the_published_rule():
    assert insight_checks.FORBIDDEN_PHRASES == FORBIDDEN_PHRASES
    assert SELECTION_RULE.lead_max == insight_checks.LEAD_MAX
    assert SELECTION_RULE.team_cap == insight_checks.TEAM_CAP
    assert dict(insight_checks.FAMILY_CAPS) == dict(SELECTION_RULE.family_caps)
    assert INSIGHT_RULE.upside_per_position == insight_checks.UPSIDE_PER_POSITION


@pytest.mark.parametrize("fixture", ["volume", "upside", "opening", "backfield", "streak", "pace"])
def test_every_scenario_validates(fixture, request):
    result, records = request.getfixturevalue(fixture)
    assert result.records, fixture
    assert passed(insight_record_checks(result.records))
    assert passed(validate_records("insight_story", result.records, stage="test"))
    envelopes = {name: {"records": rows} for name, rows in records.items()}
    envelopes["insights"] = {"records": result.records}
    assert passed(insight_cross_checks(envelopes))
    assert passed(
        insight_metadata_checks({"through_week": THROUGH, "insights": result.metadata}, envelopes)
    )


def test_validator_refuses_a_number_the_evidence_does_not_hold(volume):
    result, _ = volume
    tampered = [dict(r) for r in result.records]
    tampered[0] = {**tampered[0], "headline": tampered[0]["headline"].replace("12.0", "13.0")}
    ids = {c.check_id for c in insight_record_checks(tampered) if c.status is CheckStatus.FAIL}
    assert "insights.text_number_not_in_evidence" in ids


@pytest.mark.parametrize(
    "phrase",
    [
        "He is due for a big game.",
        "His route tree fits.",
        "Points over expected say so.",
        "A lock this week.",
    ],
)
def test_validator_refuses_forbidden_claims(volume, phrase):
    result, _ = volume
    tampered = [{**result.records[0], "dek": phrase}]
    ids = {c.check_id for c in insight_record_checks(tampered) if c.status is CheckStatus.FAIL}
    assert "insights.forbidden_claim" in ids


def test_validator_refuses_a_strip_that_does_not_add_up(volume):
    result, _ = volume
    record = story(result, "volume-00-0000001")
    weeks = [dict(w) for w in record["chart"]["weeks"]]
    weeks[-1]["points"] += 5
    tampered = {**record, "chart": {**record["chart"], "weeks": weeks}}
    ids = {c.check_id for c in insight_record_checks([tampered]) if c.status is CheckStatus.FAIL}
    assert "insights.identity" in ids


def test_cross_check_refuses_numbers_that_disagree_with_usage(volume):
    result, records = volume
    record = story(result, "volume-00-0000001")
    weeks = [dict(w) for w in record["chart"]["weeks"]]
    weeks[0]["points"] = 99.0
    envelopes = {name: {"records": rows} for name, rows in records.items()}
    envelopes["insights"] = {"records": [{**record, "chart": {**record["chart"], "weeks": weeks}}]}
    ids = {c.check_id for c in insight_cross_checks(envelopes) if c.status is CheckStatus.FAIL}
    assert "insights.disagrees_with_sources" in ids
