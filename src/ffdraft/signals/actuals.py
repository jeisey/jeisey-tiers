"""Season-to-date actuals: what a player has already scored, ranked within his position.

**The question this answers.** The rest-of-season board orders *modelled remaining value*.
A manager also wants the plain fact beside it — "he is QB5 by points scored so far" — and
needs both numbers on one basis to read the gap between them. Until this module the site
published the totals (`ros_tiers.points_to_date`) for the players on the board only, with no
rank, and a rank computed in the browser over whatever rows happened to be loaded would have
been a rank over the published depth, the search box and the page size rather than over the
league.

This module computes one representation, ``season_actuals_v1``, at build time, and every
surface reads it (ADR-105):

* **Total points** — the scoring engine (:mod:`ffdraft.scoring.engine`) over nflverse's weekly
  player rows, regular season, inside the fantasy horizon, weeks ``1..through_week`` only.
  The cutoff is the board's own, so a Thursday game of the next week that is already in the
  upstream file is never mixed into a total that otherwise stops at the previous week.
* **Games played** — an *appearance*: a week with a weekly stats row **or** at least one
  offensive snap. This is the usage layer's definition (``usage_signals_v1``), so a card's
  week strip and its games count agree. The rest-of-season *model* counts stats rows only
  (``games_to_date``); that feature is untouched, and the difference — a snaps-only week, which
  scores zero — is documented rather than hidden.
* **Points per game** — total points over games played. Byes and missed weeks are not games.
  Null for a player with no appearances, never zero.
* **Season position rank** — competition rank (1, 2, 2, 4) of total points, descending, among
  every player at the position who has appeared, in one scoring preset. Points are rounded to
  the declared precision (0.01, at which every rule in `config/league-defaults.yaml` is exact)
  *before* ranking, so floating-point dust cannot split a tie. League size is not an input: the
  same rank is published for every league preset.

**The population is the league, not the board.** Ranks are computed before the
rest-of-season publication depth, model eligibility, availability, search, filters or
pagination exist: an injured star's six weeks of points still count, and a player no board
publishes still occupies his place. Every appearing QB/RB/WR/TE is published, so the ranks can
be re-derived from the artifact alone, and the validator does exactly that.

**Position is the board's.** A player is ranked within the position the site shows for him:
the rest-of-season snapshot's position, then the identity registry's, then his latest
box-score row, then his latest snap row. QB4 and RB4 are separate standings.

**Incomplete data withholds; it never shrinks.** Before publishing, every scheduled
team-week through the cutoff must appear in the weekly rows and in the snap counts. A missing
club would remove its players from the population and move every rank behind them, which is
the plausible-looking wrong answer this check exists to refuse. When it fails, no record is
published and the build metadata says why; the surfaces print "unavailable" rather than ranks.

Observed facts only. Nothing here is a model input, and nothing here reads a model output
beyond *which players a board publishes*.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import polars as pl

from ffdraft.config import ScoringPreset, ScoringRules
from ffdraft.contracts import QualityCheck
from ffdraft.contracts.enums import Severity, normalize_team_code
from ffdraft.identity.ids import IdNamespace, make_player_id, parse_player_id
from ffdraft.scoring.engine import SCORING_ENGINE_VERSION, score_weekly_frame
from ffdraft.scoring.horizon import fantasy_horizon

__all__ = [
    "ACTUALS_POSITIONS",
    "SEASON_ACTUALS_DEFINITIONS",
    "SEASON_ACTUALS_RULE",
    "SEASON_ACTUALS_RULE_VERSION",
    "SeasonActualsResult",
    "SeasonActualsRule",
    "build_season_actuals",
    "competition_ranks",
]

#: Bump when the meaning of any published actuals quantity changes.
SEASON_ACTUALS_RULE_VERSION = "season_actuals_v1"

#: The supported scoring population. Kickers and defences are not scored by this project.
ACTUALS_POSITIONS: tuple[str, ...] = ("QB", "RB", "WR", "TE")

#: The sentences that travel with the numbers, so no surface has to paraphrase a definition.
SEASON_ACTUALS_DEFINITIONS: Mapping[str, str] = {
    "appearance": (
        "A game played is a regular-season week with a weekly stats row or at least one "
        "offensive snap. Byes and weeks he did not appear are not games."
    ),
    "points": (
        "Total fantasy points scored in weeks 1 through the cutoff, in the selected scoring "
        "preset, from the same scoring engine as every projection on the site."
    ),
    "points_per_game": (
        "Total points divided by games played. Blank for a player with no appearances."
    ),
    "season_rank": (
        "Rank by total points among every player at the position who has appeared this "
        "season, whatever board publishes him. Ties share a rank (1, 2, 2, 4). The same in "
        "every league size; it can change with the scoring preset."
    ),
    "comparison": (
        "Season rank measures points already scored. Rest-of-season rank orders the model's "
        "value from here on. Different scoring pace, expected remaining appearances and the "
        "model's wider football history can make the two orderings differ; the gap is not a "
        "change over time and is not by itself evidence of a model error."
    ),
    "model_difference": (
        "The rest-of-season model counts appearances by weekly stats rows only. A week with "
        "snaps and no statistic counts as a game here and not in the model's own inputs."
    ),
}


@dataclass(frozen=True, slots=True)
class SeasonActualsRule:
    """The declared choices, versioned together."""

    version: str = SEASON_ACTUALS_RULE_VERSION
    #: Every rule in `config/league-defaults.yaml` is exact at a hundredth of a point.
    points_decimals: int = 2
    rank_method: str = "competition"

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "points_decimals": self.points_decimals,
            "rank_method": self.rank_method,
            "scoring_engine_version": SCORING_ENGINE_VERSION,
        }


SEASON_ACTUALS_RULE = SeasonActualsRule()


@dataclass(slots=True)
class SeasonActualsResult:
    """Records (empty when withheld), the metadata block, and the build's checks."""

    records: list[dict[str, Any]]
    metadata: dict[str, Any]
    checks: list[QualityCheck] = field(default_factory=list)

    @property
    def published(self) -> bool:
        return self.metadata.get("status") == "published"


def competition_ranks(values: Mapping[str, int]) -> dict[str, int]:
    """``key -> rank`` by value descending; ties share the best rank (1, 2, 2, 4).

    ``values`` are integers (hundredths of a point) so equality is exact.
    """
    ordered = sorted(values.values(), reverse=True)
    first: dict[int, int] = {}
    for index, value in enumerate(ordered):
        first.setdefault(value, index + 1)
    return {key: first[value] for key, value in values.items()}


def _cents(value: float, decimals: int) -> int:
    return int(round(round(float(value), decimals) * 10**decimals))


def build_season_actuals(
    *,
    weekly: pl.DataFrame,
    snap_counts: pl.DataFrame,
    schedule: pl.DataFrame,
    scoring: Mapping[ScoringPreset, ScoringRules],
    season: int,
    through_week: int,
    positions: Mapping[str, str],
    names: Mapping[str, str] | None = None,
    include: Iterable[str] = (),
    build_id: str,
    schema_version: str,
    rule: SeasonActualsRule = SEASON_ACTUALS_RULE,
) -> SeasonActualsResult:
    """Every appearing QB/RB/WR/TE's season to date, per scoring preset.

    ``positions`` maps a canonical id to the position a board shows for him (the
    rest-of-season snapshot's, then the identity registry's); a player it does not name is
    placed by his latest box-score row, then his latest snap row. ``include`` names players a
    board publishes, so one with no appearance still gets a record saying so — a known zero,
    distinguishable from a missing record. ``snap_counts`` must already carry ``gsis_id``
    (:func:`ffdraft.ros.dataset.bridged_snap_counts`).
    """
    horizon = fantasy_horizon(season)
    last_week = min(int(through_week), horizon.last_week)
    weeks = list(range(horizon.first_week, last_week + 1))
    presets = sorted(scoring)
    checks: list[QualityCheck] = []
    base_metadata: dict[str, Any] = {
        "rule": rule.to_dict(),
        "season": season,
        "through_week": int(through_week),
        "weeks": weeks,
        "horizon": horizon.describe(),
        "scoring_presets": [str(preset) for preset in presets],
        "definitions": dict(SEASON_ACTUALS_DEFINITIONS),
    }

    stats = _scoped_stats(weekly, season=season, last_week=last_week)
    snaps = _scoped_snaps(snap_counts, season=season, last_week=last_week)
    scheduled = _scheduled_teams(schedule, season=season, last_week=last_week)

    coverage, problems = _coverage(stats, snaps, scheduled, weeks)
    coverage["unbridged_snap_rows"] = _unbridged_snap_rows(
        snap_counts,
        season=season,
        last_week=last_week,
    )
    if problems:
        checks.append(
            QualityCheck.fail(
                "season_actuals.incomplete_sources",
                stage="season_actuals",
                message=(
                    "season-to-date actuals are withheld: a scheduled team-week through the "
                    "cutoff is missing upstream, and ranking over the rows that are present "
                    "would move every rank behind the missing players; every board, value "
                    "and rank is unaffected"
                ),
                observed="; ".join(problems[:6]) + (" …" if len(problems) > 6 else ""),
                expected="every scheduled team in the weekly rows and the snap counts",
                severity=Severity.WARNING,
            ),
        )
        return SeasonActualsResult(
            records=[],
            metadata={
                **base_metadata,
                "status": "withheld",
                "withheld_reason": "; ".join(problems[:6]),
                "records": 0,
                "population": {position: 0 for position in ACTUALS_POSITIONS},
                "coverage": coverage,
            },
            checks=checks,
        )

    scored = score_weekly_frame(stats, scoring) if not stats.is_empty() else stats
    appearances: dict[str, set[int]] = {}
    points: dict[str, dict[str, float]] = {}
    stat_position: dict[str, tuple[int, str]] = {}
    stat_name: dict[str, tuple[int, str]] = {}
    for row in scored.iter_rows(named=True):
        gsis = row.get("gsis_id")
        if not gsis:
            continue
        player_id = make_player_id(IdNamespace.GSIS, str(gsis))
        week = int(row["week"])
        appearances.setdefault(player_id, set()).add(week)
        totals = points.setdefault(player_id, {str(p): 0.0 for p in presets})
        for preset in presets:
            totals[str(preset)] += float(row.get(f"fantasy_points_{preset}") or 0.0)
        _latest(stat_position, player_id, week, row.get("position"))
        _latest(stat_name, player_id, week, row.get("display_name"))

    snap_only_weeks: dict[str, int] = {}
    snap_position: dict[str, tuple[int, str]] = {}
    snap_name: dict[str, tuple[int, str]] = {}
    for row in snaps.iter_rows(named=True):
        player_id = make_player_id(IdNamespace.GSIS, str(row["gsis_id"]))
        week = int(row["week"])
        weeks_seen = appearances.setdefault(player_id, set())
        if week not in weeks_seen:
            snap_only_weeks[player_id] = snap_only_weeks.get(player_id, 0) + 1
            weeks_seen.add(week)
        points.setdefault(player_id, {str(p): 0.0 for p in presets})
        _latest(snap_position, player_id, week, row.get("position"))
        _latest(snap_name, player_id, week, row.get("player_name"))

    def position_of(player_id: str) -> str | None:
        for source in (
            positions.get(player_id),
            (stat_position.get(player_id) or (0, None))[1],
            (snap_position.get(player_id) or (0, None))[1],
        ):
            if source:
                return str(source)
        return None

    known_names = names or {}

    def name_of(player_id: str) -> str:
        return str(
            known_names.get(player_id)
            or (stat_name.get(player_id) or (0, None))[1]
            or (snap_name.get(player_id) or (0, None))[1]
            or player_id,
        )

    population: dict[str, str] = {}
    for player_id in appearances:
        position = position_of(player_id)
        if position in ACTUALS_POSITIONS:
            population[player_id] = str(position)
    # Only the ranked population's snaps-only weeks: a lineman's snaps are not a game here.
    snap_only = sum(snap_only_weeks.get(player_id, 0) for player_id in population)
    coverage["snap_only_appearances"] = snap_only

    # A board player with no appearance: a record that says so, never a guessed one.
    absent: dict[str, str] = {}
    for player_id in sorted(set(include)):
        if player_id in population:
            continue
        try:
            namespace, _ = parse_player_id(player_id)
        except ValueError:
            continue
        if namespace != IdNamespace.GSIS:
            continue
        position = positions.get(player_id)
        if position in ACTUALS_POSITIONS:
            absent[player_id] = str(position)

    records: list[dict[str, Any]] = []
    counts = {position: 0 for position in ACTUALS_POSITIONS}
    for position in population.values():
        counts[position] += 1
    for preset in presets:
        key = str(preset)
        ranks: dict[str, int] = {}
        for position in ACTUALS_POSITIONS:
            members = {
                player_id: _cents(points[player_id][key], rule.points_decimals)
                for player_id, held in population.items()
                if held == position
            }
            ranks.update(competition_ranks(members))
        for player_id, position in sorted(population.items()):
            games = len(appearances[player_id])
            total = round(points[player_id][key], rule.points_decimals)
            records.append(
                _record(
                    schema_version=schema_version,
                    build_id=build_id,
                    season=season,
                    through_week=int(through_week),
                    scoring_preset=key,
                    player_id=player_id,
                    display_name=name_of(player_id),
                    position=position,
                    games=games,
                    total=total,
                    ppg=round(total / games, rule.points_decimals),
                    rank=ranks[player_id],
                ),
            )
        for player_id, position in sorted(absent.items()):
            records.append(
                _record(
                    schema_version=schema_version,
                    build_id=build_id,
                    season=season,
                    through_week=int(through_week),
                    scoring_preset=key,
                    player_id=player_id,
                    display_name=name_of(player_id),
                    position=position,
                    games=0,
                    total=0.0,
                    ppg=None,
                    rank=None,
                ),
            )

    checks.append(
        QualityCheck.ok(
            "season_actuals.published",
            stage="season_actuals",
            message=(
                f"{rule.version}: season-to-date points, games and positional ranks through "
                f"week {through_week}, over every appearing player rather than the published "
                "board; observed facts, read by no model"
            ),
            observed=(
                ", ".join(f"{position} {counts[position]}" for position in ACTUALS_POSITIONS)
                + f"; {len(absent)} board player(s) with no appearance; "
                f"{snap_only} snaps-only appearance(s)"
            ),
        ),
    )
    return SeasonActualsResult(
        records=records,
        metadata={
            **base_metadata,
            "status": "published",
            "withheld_reason": None,
            "records": len(records),
            "population": counts,
            "coverage": coverage,
        },
        checks=checks,
    )


def _record(
    *,
    schema_version: str,
    build_id: str,
    season: int,
    through_week: int,
    scoring_preset: str,
    player_id: str,
    display_name: str,
    position: str,
    games: int,
    total: float,
    ppg: float | None,
    rank: int | None,
) -> dict[str, Any]:
    return {
        "schema_version": schema_version,
        "build_id": build_id,
        "season": season,
        "through_week": through_week,
        "scoring_preset": scoring_preset,
        "player_id": player_id,
        "display_name": display_name,
        "position": position,
        "games_played": games,
        "points": total,
        "points_per_game": ppg,
        "season_position_rank": rank,
    }


def _latest(
    target: dict[str, tuple[int, str]],
    player_id: str,
    week: int,
    value: Any,
) -> None:
    if not value:
        return
    held = target.get(player_id)
    if held is None or week >= held[0]:
        target[player_id] = (week, str(value))


def _scoped_stats(weekly: pl.DataFrame, *, season: int, last_week: int) -> pl.DataFrame:
    """Regular-season rows of ``season`` in weeks ``1..last_week`` — nothing after the cutoff."""
    if weekly.is_empty():
        return weekly
    first = fantasy_horizon(season).first_week
    return weekly.filter(
        (pl.col("season") == season)
        & (pl.col("season_type") == "REG")
        & (pl.col("week") >= first)
        & (pl.col("week") <= last_week)
        & pl.col("gsis_id").is_not_null(),
    )


def _scoped_snaps(snap_counts: pl.DataFrame, *, season: int, last_week: int) -> pl.DataFrame:
    """One row per ``(week, gsis_id)`` with at least one offensive snap, through the cutoff."""
    empty = pl.DataFrame(
        schema={
            "week": pl.Int32,
            "gsis_id": pl.String,
            "team": pl.String,
            "position": pl.String,
            "player_name": pl.String,
        },
    )
    if snap_counts.is_empty() or "gsis_id" not in snap_counts.columns:
        return empty
    first = fantasy_horizon(season).first_week
    scoped = snap_counts.filter(
        (pl.col("season") == season)
        & (pl.col("game_type") == "REG")
        & (pl.col("week") >= first)
        & (pl.col("week") <= last_week)
        & pl.col("gsis_id").is_not_null()
        & (pl.col("offense_snaps").fill_null(0.0) > 0),
    )
    if scoped.is_empty():
        return empty
    for column in ("position", "player_name", "team"):
        if column not in scoped.columns:
            scoped = scoped.with_columns(pl.lit(None, dtype=pl.String).alias(column))
    return scoped.group_by("week", "gsis_id").agg(
        pl.col("team").first(),
        pl.col("position").first(),
        pl.col("player_name").first(),
    )


def _unbridged_snap_rows(snap_counts: pl.DataFrame, *, season: int, last_week: int) -> int:
    """Core-position snap rows with no canonical id: excluded (fail closed) and counted."""
    if snap_counts.is_empty() or "gsis_id" not in snap_counts.columns:
        return 0
    position = (
        pl.col("position").is_in(list(ACTUALS_POSITIONS))
        if "position" in snap_counts.columns
        else pl.lit(True)
    )
    return int(
        snap_counts.filter(
            (pl.col("season") == season)
            & (pl.col("game_type") == "REG")
            & (pl.col("week") <= last_week)
            & pl.col("gsis_id").is_null()
            & (pl.col("offense_snaps").fill_null(0.0) > 0)
            & position,
        ).height,
    )


def _scheduled_teams(schedule: pl.DataFrame, *, season: int, last_week: int) -> dict[int, set[str]]:
    if schedule.is_empty():
        return {}
    games = schedule.filter(
        (pl.col("season") == season)
        & (pl.col("game_type") == "REG")
        & (pl.col("week") <= last_week),
    )
    teams: dict[int, set[str]] = {}
    for row in games.select("week", "home_team", "away_team").iter_rows(named=True):
        for raw in (row["home_team"], row["away_team"]):
            team = normalize_team_code(raw)
            if team is not None:
                teams.setdefault(int(row["week"]), set()).add(team)
    return teams


def _teams_by_week(frame: pl.DataFrame) -> dict[int, set[str]]:
    if frame.is_empty() or "team" not in frame.columns:
        return {}
    seen: dict[int, set[str]] = {}
    for week, raw in frame.select("week", "team").iter_rows():
        team = normalize_team_code(raw)
        if team is not None:
            seen.setdefault(int(week), set()).add(team)
    return seen


def _coverage(
    stats: pl.DataFrame,
    snaps: pl.DataFrame,
    scheduled: Mapping[int, set[str]],
    weeks: Sequence[int],
) -> tuple[dict[str, Any], list[str]]:
    """Whether every scheduled team-week is present in both sources, and what is missing."""
    stat_teams = _teams_by_week(stats)
    snap_teams = _teams_by_week(snaps)
    problems: list[str] = []
    if not scheduled:
        problems.append("no regular-season schedule through the cutoff")
    missing_stats = 0
    missing_snaps = 0
    for week in weeks:
        expected = scheduled.get(week, set())
        lost_stats = sorted(expected - stat_teams.get(week, set()))
        lost_snaps = sorted(expected - snap_teams.get(week, set()))
        missing_stats += len(lost_stats)
        missing_snaps += len(lost_snaps)
        if lost_stats:
            problems.append(f"week {week} weekly stats missing {', '.join(lost_stats)}")
        if lost_snaps:
            problems.append(f"week {week} snap counts missing {', '.join(lost_snaps)}")
    coverage = {
        "weeks_checked": len(weeks),
        "scheduled_team_weeks": sum(len(scheduled.get(week, set())) for week in weeks),
        "weekly_stats_missing_team_weeks": missing_stats,
        "snap_counts_missing_team_weeks": missing_snaps,
        "snap_only_appearances": 0,
    }
    return coverage, problems
