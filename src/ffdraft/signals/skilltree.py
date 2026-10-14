"""The Skill Tree: a positional statistical profile, described and never scored (ADR-107).

``skill_tree_v1`` turns the season-to-date box score, snap counts, play-by-play, the Next Gen
Stats season summary and the combine into one record per player per metric, each with its
value, its sample, its state and — when the sample and the cohort allow — its rank and
percentile among qualified players at his position. :mod:`ffdraft.signals.skilltree_catalog`
holds what each metric *is*; this module counts.

**Read by nothing.** No model, board, rank, tier, pick, trade search or lineup reads this
module's output. It runs after every board exists and reads them for one thing only: which
players a board publishes, so each one has a record saying whether he has appeared.

The rules, each from ADR-107 and each tested:

* **One window** — regular season, weeks ``1..through_week``, the board's cutoff. Nothing after
  it (a Thursday game already in the file is ignored), nothing from last season, no recent
  window.
* **Official totals stay official**; play-by-play universes drop two-point tries everywhere
  and kneel-downs from rushing efficiency only, and every universe reconciles to the box score
  (dropbacks = attempts + sacks, targets = targets, carries − kneels = non-kneel carries).
* **Pooled, never averaged**: a rate is Σ numerator ÷ Σ denominator over his games, and a
  share's denominator is his team's total *in the games he played*, keyed by the club he
  played for that week.
* **Incomplete withholds**: a scheduled team-week missing from a source makes that source's
  metrics ``unavailable`` for the build rather than ranking a smaller league.
* **States are never merged**: ranked, below the minimum, small cohort, no opportunity, not
  covered, unavailable, no appearances. A missing value is never zero.
"""

from __future__ import annotations

import bisect
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import polars as pl

from ffdraft.contracts import QualityCheck
from ffdraft.contracts.enums import Severity, normalize_team_code
from ffdraft.identity.ids import IdNamespace, make_player_id, parse_player_id
from ffdraft.signals.skilltree_catalog import (
    CATALOG,
    COMBINE_METRIC,
    PRESENCE_METRIC,
    SKILL_TREE_POSITIONS,
    SOURCE_LABELS,
    TREES,
    Metric,
    Source,
    metric_ids_for,
    minimum_for,
)

__all__ = [
    "COMBINE_FIRST_YEAR",
    "GOAL_LINE_YARDLINE",
    "MIN_COHORT",
    "NGS_PUBLISHED",
    "NGS_VOLUME_TOLERANCE",
    "RED_ZONE_YARDLINE",
    "REASONS",
    "SKILL_PLAY_COLUMNS",
    "SKILL_TREE_RULE_VERSION",
    "STATES",
    "SkillTreeResult",
    "build_skill_tree",
    "combine_readings",
    "combine_testers",
    "ngs_season_readings",
    "percentile_ranks",
    "skill_plays",
]

#: Bump when the meaning of any published quantity changes.
SKILL_TREE_RULE_VERSION = "skill_tree_v1"

#: ADR-107: Next Gen Stats figures are published (source registry, nflreadpy
#: `known_issues.nextgen_summary_only`). False removes every NGS reading from the artifact
#: and the card.
NGS_PUBLISHED = True

#: Ranks and percentiles need at least this many qualified players.
MIN_COHORT = 5
RED_ZONE_YARDLINE = 20
GOAL_LINE_YARDLINE = 5
EXPLOSIVE_RUN_YARDS = 10
EXPLOSIVE_CATCH_YARDS = 20
#: Combine testers from this year on form the cohort (nflverse's combine file starts here).
COMBINE_FIRST_YEAR = 2000
#: An NGS season summary is used only when its volume is within this many plays of official.
NGS_VOLUME_TOLERANCE = 1

STATES: tuple[str, ...] = (
    "ranked",
    "below_minimum",
    "small_cohort",
    "no_opportunity",
    "not_covered",
    "unavailable",
    "no_appearances",
)

#: The sentence each ``reason`` code stands for; published in the build metadata.
REASONS: Mapping[str, str] = {
    "player_stats_incomplete": (
        "A scheduled team-week is missing from the weekly stats, so box-score readings are "
        "withheld for this build rather than ranked over a smaller league."
    ),
    "snap_counts_incomplete": (
        "A scheduled team-week is missing from the snap counts, so snap shares are withheld "
        "for this build."
    ),
    "play_by_play_unavailable": "Play-by-play could not be read for this build.",
    "play_by_play_incomplete": (
        "A completed game is missing from play-by-play, so play-by-play readings are withheld "
        "for this build."
    ),
    "next_gen_stats_unavailable": "Next Gen Stats could not be read for this build.",
    "next_gen_stats_not_at_cutoff": (
        "Next Gen Stats does not yet end at the board's cutoff week (or already includes a "
        "later week), so its season summary is not used for this build."
    ),
    "next_gen_stats_not_published": "Next Gen Stats readings are switched off for this site.",
    "not_in_ngs_summary": (
        "Next Gen Stats publishes no season summary for him (it qualifies players by volume)."
    ),
    "ngs_volume_mismatch": (
        "His Next Gen Stats season summary does not match his official volume through the "
        "cutoff, so it is not used."
    ),
    "no_snap_rows": (
        "No snap-count row could be linked to him for the games he played (none was published, "
        "or its Pro Football Reference id could not be matched to his player id), so his snap "
        "share is unknown, not zero."
    ),
    "combine_unavailable": "The combine file could not be read for this build.",
    "no_combine_forty": "No linked NFL Scouting Combine 40-yard dash on file for him.",
}

#: Play-by-play columns the skill tree reads. Missing any is a source-contract change.
SKILL_PLAY_COLUMNS: tuple[str, ...] = (
    "season",
    "week",
    "season_type",
    "posteam",
    "play_type",
    "pass_attempt",
    "rush_attempt",
    "sack",
    "qb_scramble",
    "two_point_attempt",
    "passer_player_id",
    "rusher_player_id",
    "receiver_player_id",
    "yardline_100",
    "air_yards",
    "receiving_yards",
    "rushing_yards",
    "complete_pass",
    "epa",
    "cpoe",
)

_NGS_SPEC: Mapping[str, tuple[str, str]] = {
    # stat type -> (NGS volume column, official volume column on the player table)
    "passing": ("volume", "att"),
    "rushing": ("volume", "car"),
    "receiving": ("volume", "tgt"),
}

#: NGS reading -> (stat type, column on the normalized NGS frame, denominator column).
_NGS_READINGS: Mapping[str, tuple[str, str, str]] = {
    "ngs_time_to_throw": ("passing", "avg_time_to_throw", "volume"),
    "ngs_ryoe": ("rushing", "rush_yards_over_expected_per_att", "volume"),
    "ngs_yacoe": ("receiving", "avg_yac_above_expectation", "receptions"),
    "ngs_separation": ("receiving", "avg_separation", "volume"),
    "ngs_cushion": ("receiving", "avg_cushion", "volume"),
}


@dataclass(slots=True)
class SkillTreeResult:
    """Records and definitions (empty when withheld), the metadata block, and the checks."""

    records: list[dict[str, Any]]
    definitions: list[dict[str, Any]]
    metadata: dict[str, Any]
    checks: list[QualityCheck] = field(default_factory=list)

    @property
    def published(self) -> bool:
        return self.metadata.get("status") == "published"


@dataclass(slots=True)
class _SourceState:
    status: str = "published"
    reason: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status == "published"

    def to_dict(self) -> dict[str, Any]:
        return {"status": self.status, "reason": self.reason, **self.detail}


# ------------------------------------------------------------------------- primitives


def _flag(name: str) -> pl.Expr:
    return pl.col(name).cast(pl.Float64).fill_null(0.0) == 1.0


def _team(expr: pl.Expr) -> pl.Expr:
    return expr.cast(pl.String).map_elements(normalize_team_code, return_dtype=pl.String)


def _scaled(value: float, decimals: int) -> int:
    return int(round(round(float(value), decimals) * 10**decimals))


def percentile_ranks(
    values: Mapping[str, float],
    *,
    direction: str,
    decimals: int,
    min_cohort: int = MIN_COHORT,
) -> dict[str, tuple[int, float]]:
    """``key -> (rank, percentile)`` over one cohort, on the values as published.

    Rank is a competition rank (1, 2, 2, 4) in the metric's direction — highest first for
    ``higher`` and ``neutral``, lowest first for ``lower``. Percentile is
    ``100 × (behind + (ties − 1) / 2) ÷ (n − 1)``: the best is 100, the worst 0, ties share one
    value. A cohort smaller than ``min_cohort`` ranks no one.
    """
    if len(values) < max(min_cohort, 2):
        return {}
    sign = -1 if direction == "lower" else 1
    adjusted = {key: sign * _scaled(value, decimals) for key, value in values.items()}
    ordered = sorted(adjusted.values())
    n = len(ordered)
    out: dict[str, tuple[int, float]] = {}
    for key, mine in adjusted.items():
        behind = bisect.bisect_left(ordered, mine)
        ahead = n - bisect.bisect_right(ordered, mine)
        ties = n - behind - ahead
        out[key] = (ahead + 1, round(100.0 * (behind + (ties - 1) / 2) / (n - 1), 1))
    return out


# ------------------------------------------------------------------------- the sources


def skill_plays(pbp: pl.DataFrame, *, season: int, through_week: int) -> pl.DataFrame:
    """Regular-season plays of ``season`` through the cutoff, reduced to the columns read.

    Two-point tries are dropped here, once, for every universe. Raises ``ValueError`` when a
    column is missing: a renamed upstream field is a contract change, not a column of nulls.
    """
    missing = [name for name in SKILL_PLAY_COLUMNS if name not in pbp.columns]
    if missing:
        raise ValueError(f"load_pbp is missing skill-tree columns: {', '.join(missing)}")
    return (
        pbp.select(SKILL_PLAY_COLUMNS)
        .filter(
            (pl.col("season") == season)
            & (pl.col("season_type") == "REG")
            & (pl.col("week") <= through_week)
            & pl.col("posteam").is_not_null()
            & ~_flag("two_point_attempt"),
        )
        .with_columns(
            pl.col("week").cast(pl.Int32),
            _team(pl.col("posteam")).alias("team"),
            pl.col("yardline_100").cast(pl.Float64),
            pl.col("epa").cast(pl.Float64),
        )
    )


def ngs_season_readings(
    frames: Mapping[str, pl.DataFrame],
    *,
    season: int,
    through_week: int,
) -> tuple[dict[str, dict[str, float | None]], _SourceState]:
    """``gsis -> {reading: value}`` from the week-0 REG season summaries, or why not.

    ``frames`` are normalized by :mod:`ffdraft.sources.nextgen` (one per stat type). The
    summary is used only when every file's REG weekly rows end exactly at ``through_week``:
    earlier means the summary is short of the board's window, later means it already holds a
    game the board does not. Weekly rows are never summed (they cover qualifying weeks only).
    """
    state = _SourceState(detail={"files": {}})
    readings: dict[str, dict[str, float | None]] = {}
    for stat_type in ("passing", "rushing", "receiving"):
        frame = frames.get(stat_type)
        if frame is None or frame.is_empty():
            return {}, _SourceState("unavailable", "next_gen_stats_unavailable", state.detail)
        scoped = frame.filter((pl.col("season") == season) & (pl.col("season_type") == "REG"))
        weekly = scoped.filter(pl.col("week") > 0)
        last = int(weekly.select(pl.col("week").max()).item() or 0) if weekly.height else 0
        summary = scoped.filter(pl.col("week") == 0)
        state.detail["files"][stat_type] = {
            "last_week": last,
            "summary_rows": summary.height,
        }
        if last != through_week:
            state.status, state.reason = "unavailable", "next_gen_stats_not_at_cutoff"
            continue
        for row in summary.iter_rows(named=True):
            gsis = str(row["gsis_id"])
            target = readings.setdefault(gsis, {})
            target[f"ngs_{stat_type}_volume"] = row.get("volume")
            if stat_type == "receiving":
                target["ngs_receiving_receptions"] = row.get("receptions")
            for reading, (kind, column, _) in _NGS_READINGS.items():
                if kind == stat_type:
                    value = row.get(column)
                    target[reading] = None if value is None else float(value)
    if not state.ok:
        return {}, state
    return readings, state


def combine_testers(raw: pl.DataFrame) -> pl.DataFrame:
    """Raw ``load_combine`` rows → every tester: year, PFR id (nullable), position, forty.

    The tester cohort is everyone who ran, so rows without a PFR id stay (the normalized
    combine frame drops them because they cannot be joined to a player; here they only
    populate the cohort).
    """
    needed = ("season", "pfr_id", "pos", "forty")
    missing = [name for name in needed if name not in raw.columns]
    if missing:
        raise ValueError(f"load_combine is missing skill-tree columns: {', '.join(missing)}")
    return raw.select(
        pl.col("season").cast(pl.Int32).alias("combine_year"),
        pl.col("pfr_id").cast(pl.String).str.strip_chars().alias("pfr_id"),
        pl.col("pos").cast(pl.String).str.strip_chars().alias("position"),
        pl.col("forty").cast(pl.Float64, strict=False).alias("forty"),
    ).with_columns(
        pl.when(pl.col("pfr_id") == "").then(None).otherwise(pl.col("pfr_id")).alias("pfr_id"),
    )


def combine_readings(
    combine: pl.DataFrame,
    bridge: Mapping[str, str],
    *,
    first_year: int = COMBINE_FIRST_YEAR,
) -> tuple[dict[str, tuple[float, int, str]], dict[str, list[float]]]:
    """``gsis -> (forty, test year, combine position)`` and each position's tester times.

    The cohort is every tester at a combine position since ``first_year`` with a recorded
    time, linked or not. A player's own reading requires an unambiguous PFR → GSIS link: a
    GSIS id that two combine rows map to is dropped (fail closed).
    """
    if combine.is_empty():
        return {}, {}
    rows = combine.filter(
        pl.col("forty").is_not_null()
        & (pl.col("combine_year") >= first_year)
        & pl.col("position").is_not_null(),
    )
    cohorts: dict[str, list[float]] = {}
    linked: dict[str, list[tuple[float, int, str]]] = {}
    for pfr, year, position, forty in rows.select(
        "pfr_id", "combine_year", "position", "forty"
    ).iter_rows():
        pos = str(position)
        cohorts.setdefault(pos, []).append(float(forty))
        gsis = bridge.get(str(pfr)) if pfr is not None else None
        if gsis is not None:
            linked.setdefault(gsis, []).append((float(forty), int(year), pos))
    unique = {gsis: entries[0] for gsis, entries in linked.items() if len(entries) == 1}
    return unique, cohorts


# --------------------------------------------------------------------- per-player table


def _scheduled(schedule: pl.DataFrame, *, season: int, through_week: int) -> set[tuple[int, str]]:
    if schedule.is_empty():
        return set()
    games = schedule.filter(
        (pl.col("season") == season)
        & (pl.col("game_type") == "REG")
        & (pl.col("week") <= through_week),
    )
    out: set[tuple[int, str]] = set()
    for week, home, away in games.select("week", "home_team", "away_team").iter_rows():
        for raw in (home, away):
            team = normalize_team_code(raw)
            if team is not None:
                out.add((int(week), team))
    return out


def _present(frame: pl.DataFrame) -> set[tuple[int, str]]:
    if frame.is_empty():
        return set()
    return {
        (int(week), str(team))
        for week, team in frame.select("week", "team").drop_nulls().unique().iter_rows()
    }


def _missing(expected: set[tuple[int, str]], present: set[tuple[int, str]]) -> list[str]:
    return [f"week {week} {team}" for week, team in sorted(expected - present)]


def _stats_frame(weekly: pl.DataFrame, *, season: int, through_week: int) -> pl.DataFrame:
    if weekly.is_empty():
        return weekly
    frame = weekly.filter(
        (pl.col("season") == season)
        & (pl.col("season_type") == "REG")
        & (pl.col("week") <= through_week)
        & pl.col("gsis_id").is_not_null(),
    )
    for name in ("passing_epa", "sacks_suffered", "receiving_yards_after_catch"):
        if name not in frame.columns:
            frame = frame.with_columns(pl.lit(None, dtype=pl.Float64).alias(name))
    return frame.with_columns(_team(pl.col("team")).alias("team"), pl.col("week").cast(pl.Int32))


def _snap_frame(snap_counts: pl.DataFrame, *, season: int, through_week: int) -> pl.DataFrame:
    if snap_counts.is_empty():
        return snap_counts
    return snap_counts.filter(
        (pl.col("season") == season)
        & (pl.col("game_type") == "REG")
        & (pl.col("week") <= through_week),
    ).with_columns(_team(pl.col("team")).alias("team"), pl.col("week").cast(pl.Int32))


def _team_snaps(snaps: pl.DataFrame) -> pl.DataFrame:
    """Team offensive snaps per (week, team): snaps ÷ share of the highest-share player."""
    rows = snaps.filter(
        pl.col("offense_pct").is_not_null()
        & (pl.col("offense_pct") > 0)
        & pl.col("team").is_not_null(),
    )
    if rows.is_empty():
        return pl.DataFrame(schema={"week": pl.Int32, "team": pl.String, "team_snaps": pl.Float64})
    return (
        rows.sort(["offense_pct", "offense_snaps"], descending=True)
        .group_by("week", "team", maintain_order=True)
        .agg((pl.col("offense_snaps") / pl.col("offense_pct")).first().round(0).alias("team_snaps"))
    )


_PBP_PLAYER_COLUMNS: tuple[str, ...] = (
    "db_pbp",
    "db_success",
    "cpoe_sum",
    "cpoe_n",
    "rz_db",
    "scrambles",
    "designed",
    "car_nk",
    "rush_epa",
    "rush_success",
    "run10",
    "rz_car",
    "gl_car",
    "tgt_pbp",
    "rec_epa",
    "catch20",
    "rz_tgt",
    "ez_tgt",
)


def _pbp_player_sums(plays: pl.DataFrame) -> pl.DataFrame:
    """Per-player play-by-play numerators and denominators (ADR-107 universes)."""
    dropbacks = plays.filter(_flag("pass_attempt") & pl.col("passer_player_id").is_not_null())
    rushes = plays.filter(_flag("rush_attempt") & pl.col("rusher_player_id").is_not_null())
    carries = rushes.filter(pl.col("play_type") != "qb_kneel")
    targets = plays.filter(
        _flag("pass_attempt") & ~_flag("sack") & pl.col("receiver_player_id").is_not_null(),
    )
    parts = [
        dropbacks.group_by(pl.col("passer_player_id").alias("gsis")).agg(
            pl.len().alias("db_pbp"),
            (pl.col("epa") > 0).sum().alias("db_success"),
            pl.col("cpoe").cast(pl.Float64).sum().alias("cpoe_sum"),
            pl.col("cpoe").is_not_null().sum().alias("cpoe_n"),
            (pl.col("yardline_100") <= RED_ZONE_YARDLINE).sum().alias("rz_db"),
        ),
        rushes.group_by(pl.col("rusher_player_id").alias("gsis")).agg(
            _flag("qb_scramble").sum().alias("scrambles"),
        ),
        carries.group_by(pl.col("rusher_player_id").alias("gsis")).agg(
            (~_flag("qb_scramble")).sum().alias("designed"),
            pl.len().alias("car_nk"),
            pl.col("epa").sum().alias("rush_epa"),
            (pl.col("epa") > 0).sum().alias("rush_success"),
            (pl.col("rushing_yards").cast(pl.Float64) >= EXPLOSIVE_RUN_YARDS).sum().alias("run10"),
            (pl.col("yardline_100") <= RED_ZONE_YARDLINE).sum().alias("rz_car"),
            (pl.col("yardline_100") <= GOAL_LINE_YARDLINE).sum().alias("gl_car"),
        ),
        targets.group_by(pl.col("receiver_player_id").alias("gsis")).agg(
            pl.len().alias("tgt_pbp"),
            pl.col("epa").sum().alias("rec_epa"),
            (
                _flag("complete_pass")
                & (pl.col("receiving_yards").cast(pl.Float64) >= EXPLOSIVE_CATCH_YARDS)
            )
            .sum()
            .alias("catch20"),
            (pl.col("yardline_100") <= RED_ZONE_YARDLINE).sum().alias("rz_tgt"),
            (pl.col("air_yards").cast(pl.Float64) >= pl.col("yardline_100")).sum().alias("ez_tgt"),
        ),
    ]
    out = parts[0]
    for part in parts[1:]:
        out = out.join(part, on="gsis", how="full", coalesce=True)
    return out.with_columns(pl.col("gsis").cast(pl.String))


def _pbp_team_sums(plays: pl.DataFrame) -> pl.DataFrame:
    carries = plays.filter(
        _flag("rush_attempt")
        & pl.col("rusher_player_id").is_not_null()
        & (pl.col("play_type") != "qb_kneel"),
    )
    targets = plays.filter(
        _flag("pass_attempt") & ~_flag("sack") & pl.col("receiver_player_id").is_not_null(),
    )
    team_carries = carries.group_by("week", "team").agg(
        (pl.col("yardline_100") <= RED_ZONE_YARDLINE).sum().alias("team_rz_car"),
        (pl.col("yardline_100") <= GOAL_LINE_YARDLINE).sum().alias("team_gl_car"),
    )
    team_targets = targets.group_by("week", "team").agg(
        (pl.col("yardline_100") <= RED_ZONE_YARDLINE).sum().alias("team_rz_tgt"),
    )
    return team_carries.join(team_targets, on=["week", "team"], how="full", coalesce=True)


@dataclass(slots=True)
class _Table:
    rows: dict[str, dict[str, float]]
    positions: dict[str, str]
    diagnostics: dict[str, Any]


def _player_table(
    *,
    stats: pl.DataFrame,
    snaps: pl.DataFrame,
    plays: pl.DataFrame | None,
    positions: Mapping[str, str],
) -> _Table:
    """``player_id -> column -> float`` over every appearance, plus his position."""
    stat_rows = stats.select("gsis_id", "week", "team").unique(["gsis_id", "week"])
    bridged = (
        snaps.filter(pl.col("gsis_id").is_not_null())
        if not snaps.is_empty() and "gsis_id" in snaps.columns
        else pl.DataFrame(
            schema={
                "gsis_id": pl.String,
                "week": pl.Int32,
                "team": pl.String,
                "offense_snaps": pl.Float64,
            }
        )
    )
    snap_rows = bridged.group_by("gsis_id", "week").agg(
        pl.col("team").first().alias("snap_team"),
        pl.col("offense_snaps").fill_null(0.0).sum().alias("snaps"),
    )
    appear = (
        stat_rows.rename({"team": "stat_team"})
        .join(snap_rows, on=["gsis_id", "week"], how="full", coalesce=True)
        .filter(pl.col("stat_team").is_not_null() | (pl.col("snaps").fill_null(0.0) > 0))
        .with_columns(
            pl.coalesce("stat_team", "snap_team").alias("team"),
            pl.col("snaps").is_not_null().alias("has_snap_row"),
        )
    )
    team_box = (
        stats.filter(pl.col("team").is_not_null())
        .group_by("week", "team")
        .agg(
            pl.col("targets").sum().alias("team_tgt"),
            pl.col("carries").sum().alias("team_car"),
            pl.col("receiving_air_yards").sum().alias("team_air"),
        )
    )
    joined = appear.join(team_box, on=["week", "team"], how="left").join(
        _team_snaps(snaps)
        if not snaps.is_empty()
        else pl.DataFrame(schema={"week": pl.Int32, "team": pl.String, "team_snaps": pl.Float64}),
        on=["week", "team"],
        how="left",
    )
    if plays is not None:
        joined = joined.join(_pbp_team_sums(plays), on=["week", "team"], how="left")
    else:
        joined = joined.with_columns(
            pl.lit(0.0).alias(name) for name in ("team_rz_car", "team_gl_car", "team_rz_tgt")
        )
    snap_side = pl.col("has_snap_row")
    per_player = joined.group_by("gsis_id").agg(
        pl.len().alias("games"),
        pl.col("team").n_unique().alias("teams"),
        pl.when(snap_side).then(pl.col("snaps")).otherwise(0.0).sum().alias("snaps"),
        pl.when(snap_side)
        .then(pl.col("team_snaps"))
        .otherwise(0.0)
        .fill_null(0.0)
        .sum()
        .alias("team_snaps"),
        (~snap_side).sum().alias("games_without_snap_row"),
        *[
            pl.col(name).cast(pl.Float64).fill_null(0.0).sum()
            for name in (
                "team_tgt",
                "team_car",
                "team_air",
                "team_rz_car",
                "team_gl_car",
                "team_rz_tgt",
            )
        ],
    )
    box = stats.group_by("gsis_id").agg(
        pl.col("pass_attempts").sum().alias("att"),
        pl.col("completions").sum().alias("cmp"),
        pl.col("passing_yards").sum().alias("pass_yds"),
        pl.col("passing_tds").sum().alias("pass_td"),
        pl.col("interceptions").sum().alias("int"),
        pl.col("passing_air_yards").sum().alias("pass_air"),
        pl.col("sacks_suffered").fill_null(0.0).sum().alias("sacks"),
        # ADR-091's EPA per dropback: weeks with a published passing EPA only.
        pl.col("passing_epa").sum().alias("pass_epa"),
        pl.when(pl.col("passing_epa").is_not_null())
        .then(pl.col("pass_attempts") + pl.col("sacks_suffered").fill_null(0.0))
        .otherwise(0.0)
        .sum()
        .alias("epa_dropbacks"),
        pl.col("passing_epa").is_not_null().any().alias("has_pass_epa"),
        pl.col("carries").sum().alias("car"),
        pl.col("rushing_yards").sum().alias("rush_yds"),
        pl.col("rushing_tds").sum().alias("rush_td"),
        pl.col("targets").sum().alias("tgt"),
        pl.col("receptions").sum().alias("rec"),
        pl.col("receiving_yards").sum().alias("rec_yds"),
        pl.col("receiving_tds").sum().alias("rec_td"),
        pl.col("receiving_air_yards").sum().alias("rec_air"),
        pl.col("receiving_yards_after_catch").fill_null(0.0).sum().alias("yac"),
    )
    table = per_player.join(box, on="gsis_id", how="left")
    if plays is not None:
        table = table.join(
            _pbp_player_sums(plays).rename({"gsis": "gsis_id"}), on="gsis_id", how="left"
        )

    # Position: the board's, then the latest box-score row's, then the latest snap row's.
    latest_stat = (
        stats.filter(pl.col("position").is_not_null())
        .sort("week")
        .group_by("gsis_id")
        .agg(pl.col("position").last())
    )
    stat_position = dict(latest_stat.iter_rows())
    snap_position: dict[str, str] = {}
    if not bridged.is_empty() and "position" in bridged.columns:
        latest_snap = (
            bridged.filter(pl.col("position").is_not_null())
            .sort("week")
            .group_by("gsis_id")
            .agg(pl.col("position").last())
        )
        snap_position = dict(latest_snap.iter_rows())

    rows: dict[str, dict[str, float]] = {}
    held: dict[str, str] = {}
    for record in table.iter_rows(named=True):
        gsis = str(record["gsis_id"])
        player_id = make_player_id(IdNamespace.GSIS, gsis)
        position = positions.get(player_id) or stat_position.get(gsis) or snap_position.get(gsis)
        if position not in SKILL_TREE_POSITIONS:
            continue
        held[player_id] = str(position)
        values: dict[str, float] = {}
        for key, value in record.items():
            if key == "gsis_id":
                continue
            if isinstance(value, bool):
                values[key] = 1.0 if value else 0.0
            else:
                values[key] = 0.0 if value is None else float(value)
        values["dropbacks"] = values.get("att", 0.0) + values.get("sacks", 0.0)
        values["db_all"] = values.get("db_pbp", 0.0) + values.get("scrambles", 0.0)
        values["rz_rush"] = values.get("rz_car", 0.0)
        values["gl_rush"] = values.get("gl_car", 0.0)
        rows[player_id] = values
    diagnostics = {
        "games_without_snap_row": int(
            sum(values.get("games_without_snap_row", 0.0) for values in rows.values())
        ),
        "players_on_two_or_more_teams": sum(
            1 for values in rows.values() if values.get("teams", 1.0) > 1
        ),
        "unbridged_offense_snap_rows": int(
            snaps.filter(pl.col("gsis_id").is_null() & (pl.col("offense_snaps") > 0)).height
        )
        if not snaps.is_empty() and "gsis_id" in snaps.columns
        else 0,
    }
    return _Table(rows=rows, positions=held, diagnostics=diagnostics)


# ------------------------------------------------------------------------ the builder


def build_skill_tree(
    *,
    weekly: pl.DataFrame,
    snap_counts: pl.DataFrame,
    schedule: pl.DataFrame,
    pbp: pl.DataFrame | None,
    pbp_error: str | None = None,
    nextgen: Mapping[str, pl.DataFrame] | None,
    nextgen_error: str | None = None,
    combine: pl.DataFrame | None,
    pfr_bridge: Mapping[str, str],
    season: int,
    through_week: int,
    positions: Mapping[str, str],
    include: Iterable[str] = (),
    build_id: str,
    metric_schema_version: str,
    definition_schema_version: str,
    ngs_published: bool = NGS_PUBLISHED,
) -> SkillTreeResult:
    """Every appearing QB/RB/WR/TE's tree, plus a presence record for each board player.

    ``weekly`` and ``snap_counts`` are the normalized frames the in-season build already holds
    (snap counts bridged to ``gsis_id``); ``pbp`` is the raw play-by-play frame loaded once per
    build (None with ``pbp_error`` when it could not be read); ``nextgen`` maps a stat type to
    its normalized frame. ``positions`` is the board's position for each canonical id.
    """
    checks: list[QualityCheck] = []
    through_week = int(through_week)
    scheduled = _scheduled(schedule, season=season, through_week=through_week)
    stats = _stats_frame(weekly, season=season, through_week=through_week)
    snaps = _snap_frame(snap_counts, season=season, through_week=through_week)

    sources: dict[Source, _SourceState] = {
        "player_stats": _SourceState(),
        "snap_counts": _SourceState(),
        "play_by_play": _SourceState(),
        "next_gen_stats": _SourceState(),
        "combine": _SourceState(),
    }
    missing_stats = _missing(scheduled, _present(stats))
    if not scheduled or missing_stats:
        sources["player_stats"] = _SourceState(
            "unavailable", "player_stats_incomplete", {"missing": missing_stats[:12]}
        )
    missing_snaps = _missing(scheduled, _present(snaps))
    if missing_snaps:
        sources["snap_counts"] = _SourceState(
            "unavailable", "snap_counts_incomplete", {"missing": missing_snaps[:12]}
        )

    plays: pl.DataFrame | None = None
    if pbp is None:
        sources["play_by_play"] = _SourceState(
            "unavailable", "play_by_play_unavailable", {"error": pbp_error}
        )
    else:
        try:
            plays = skill_plays(pbp, season=season, through_week=through_week)
        except Exception as exc:  # noqa: BLE001 - a source failure costs its metrics only
            sources["play_by_play"] = _SourceState(
                "unavailable", "play_by_play_unavailable", {"error": f"{type(exc).__name__}: {exc}"}
            )
        else:
            missing_games = _missing(scheduled, _present(plays))
            if missing_games:
                sources["play_by_play"] = _SourceState(
                    "unavailable", "play_by_play_incomplete", {"missing": missing_games[:12]}
                )
                plays = None
            else:
                sources["play_by_play"].detail = {"plays": plays.height}

    ngs: dict[str, dict[str, float | None]] = {}
    if not ngs_published:
        sources["next_gen_stats"] = _SourceState("unavailable", "next_gen_stats_not_published")
    elif nextgen is None:
        sources["next_gen_stats"] = _SourceState(
            "unavailable", "next_gen_stats_unavailable", {"error": nextgen_error}
        )
    else:
        ngs, sources["next_gen_stats"] = ngs_season_readings(
            nextgen, season=season, through_week=through_week
        )

    combine_by_player: dict[str, tuple[float, int, str]] = {}
    combine_cohorts: dict[str, list[float]] = {}
    if combine is None or combine.is_empty():
        sources["combine"] = _SourceState("unavailable", "combine_unavailable")
    else:
        combine_by_player, combine_cohorts = combine_readings(combine, pfr_bridge)
        sources["combine"].detail = {
            "testers_since": COMBINE_FIRST_YEAR,
            "testers": {pos: len(times) for pos, times in sorted(combine_cohorts.items())},
        }

    table = _player_table(
        stats=stats,
        snaps=snaps,
        plays=plays,
        positions=positions,
    )

    # NGS: a player's reading counts only when its volume matches his official volume.
    ngs_covered: dict[str, dict[str, float | None]] = {}
    ngs_mismatch: set[str] = set()
    for player_id, values in table.rows.items():
        gsis = player_id.split(":", 1)[1]
        ngs_row = ngs.get(gsis)
        if not ngs_row:
            continue
        kept: dict[str, float | None] = {}
        for stat_type, (_, official) in _NGS_SPEC.items():
            volume = ngs_row.get(f"ngs_{stat_type}_volume")
            if volume is None:
                continue
            if abs(float(volume) - values.get(official, 0.0)) > NGS_VOLUME_TOLERANCE:
                ngs_mismatch.add(f"{player_id}|{stat_type}")
                continue
            kept[f"ngs_{stat_type}_volume"] = float(volume)
            if stat_type == "receiving":
                kept["ngs_receiving_receptions"] = ngs_row.get("ngs_receiving_receptions")
            for name, (kind, _, _) in _NGS_READINGS.items():
                if kind == stat_type:
                    kept[name] = ngs_row.get(name)
        if kept:
            ngs_covered[player_id] = kept

    records: list[dict[str, Any]] = []
    cohorts: dict[tuple[str, str], int] = {}
    base = {
        "schema_version": metric_schema_version,
        "build_id": build_id,
        "season": season,
        "through_week": through_week,
    }

    # Readings per (position, metric), then ranks over each cohort.
    readings: dict[tuple[str, str], dict[str, _Reading]] = {}
    for player_id, position in table.positions.items():
        values = table.rows[player_id]
        for metric_id in metric_ids_for(position):
            metric = CATALOG[metric_id]
            readings.setdefault((position, metric_id), {})[player_id] = _reading(
                metric,
                position=position,
                values=values,
                ngs=ngs_covered.get(player_id),
                ngs_mismatch=ngs_mismatch,
                player_id=player_id,
                sources=sources,
            )
    ranked: dict[tuple[str, str], dict[str, tuple[int, float]]] = {}
    for (position, metric_id), by_player in readings.items():
        metric = CATALOG[metric_id]
        qualified = {
            player_id: reading.value
            for player_id, reading in by_player.items()
            if reading.qualified and reading.value is not None
        }
        cohorts[(position, metric_id)] = len(qualified)
        ranked[(position, metric_id)] = percentile_ranks(
            qualified, direction=metric.direction, decimals=metric.decimals
        )

    population = {position: 0 for position in SKILL_TREE_POSITIONS}
    for position in table.positions.values():
        population[position] += 1
    games_ranks: dict[str, dict[str, tuple[int, float]]] = {
        position: percentile_ranks(
            {
                player_id: table.rows[player_id].get("games", 0.0)
                for player_id, held in table.positions.items()
                if held == position
            },
            direction="higher",
            decimals=0,
        )
        for position in SKILL_TREE_POSITIONS
    }
    for player_id, position in sorted(table.positions.items()):
        values = table.rows[player_id]
        games = int(values.get("games", 0.0))
        games_rank = games_ranks[position].get(player_id)
        records.append(
            {
                **base,
                "player_id": player_id,
                "position": position,
                "metric_id": PRESENCE_METRIC.id,
                "state": "ranked" if games_rank is not None else "small_cohort",
                "value": games,
                "numerator": games,
                "denominator": None,
                "rank": None if games_rank is None else games_rank[0],
                "percentile": None if games_rank is None else games_rank[1],
                "cohort_size": population[position],
                "games": games,
                "source_season": None,
                "reason": None,
            },
        )
        for metric_id in metric_ids_for(position):
            metric = CATALOG[metric_id]
            reading = readings[(position, metric_id)][player_id]
            rank = ranked[(position, metric_id)].get(player_id)
            cohort_size = cohorts[(position, metric_id)]
            state = reading.state
            if state == "qualified":
                state = "ranked" if rank is not None else "small_cohort"
            records.append(
                {
                    **base,
                    "player_id": player_id,
                    "position": position,
                    "metric_id": metric_id,
                    "state": state,
                    "value": _publish(reading.value, metric),
                    "numerator": _publish_side(reading.numerator, metric, "numerator"),
                    "denominator": _publish_side(reading.denominator, metric, "denominator"),
                    "rank": rank[0] if rank is not None and state == "ranked" else None,
                    "percentile": rank[1] if rank is not None and state == "ranked" else None,
                    "cohort_size": cohort_size if state in ("ranked", "small_cohort") else None,
                    "games": games,
                    "source_season": None,
                    "reason": reading.reason,
                },
            )
        records.append(
            _combine_record(
                base,
                player_id=player_id,
                position=position,
                games=games,
                source=sources["combine"],
                reading=combine_by_player.get(player_id.split(":", 1)[1]),
                cohorts=combine_cohorts,
            ),
        )

    absent = 0
    for player_id in sorted(set(include)):
        if player_id in table.positions:
            continue
        try:
            namespace, _ = parse_player_id(player_id)
        except ValueError:
            continue
        board_position = positions.get(player_id)
        if namespace != IdNamespace.GSIS or board_position not in SKILL_TREE_POSITIONS:
            continue
        absent += 1
        records.append(
            {
                **base,
                "player_id": player_id,
                "position": board_position,
                "metric_id": PRESENCE_METRIC.id,
                "state": "no_appearances",
                "value": 0,
                "numerator": None,
                "denominator": None,
                "rank": None,
                "percentile": None,
                "cohort_size": None,
                "games": 0,
                "source_season": None,
                "reason": None,
            },
        )

    definitions = skill_tree_definitions(
        season=season,
        through_week=through_week,
        build_id=build_id,
        schema_version=definition_schema_version,
        sources=sources,
    )
    metadata = {
        "method_version": SKILL_TREE_RULE_VERSION,
        "status": "published",
        "season": season,
        "through_week": through_week,
        "window": f"{season} regular season, weeks 1–{through_week}",
        "records": len(records),
        "players": len(table.positions),
        "players_without_appearance": absent,
        "population": population,
        "minimum_cohort": MIN_COHORT,
        "ngs_published": ngs_published,
        "sources": {name: state.to_dict() for name, state in sources.items()},
        "diagnostics": {
            **table.diagnostics,
            "ngs_volume_mismatches": len(ngs_mismatch),
            "ngs_covered_players": len(ngs_covered),
            "combine_linked_players": sum(
                1
                for player_id in table.positions
                if player_id.split(":", 1)[1] in combine_by_player
            ),
        },
        # Only the sentences this build uses: the manifest carries this block on every first
        # visit, and only the lazy tree reads it.
        "reasons": {
            code: sentence
            for code, sentence in REASONS.items()
            if code in {record["reason"] for record in records}
            or any(state.reason == code for state in sources.values())
        },
        "statement": (
            "Descriptive context only: observed regular-season statistics through the board's "
            "cutoff, each ranked only against qualified players at the same position. No "
            "model, ranking, pick or trade reads it, and nothing is combined into a score."
        ),
    }
    down = [name for name, state in sources.items() if not state.ok]
    checks.append(
        QualityCheck.ok(
            "skill_tree.published",
            stage="skill_tree",
            message=(
                f"{SKILL_TREE_RULE_VERSION}: positional statistical profiles through week "
                f"{through_week}, descriptive context read by no model"
            ),
            observed=(
                ", ".join(f"{position} {population[position]}" for position in SKILL_TREE_POSITIONS)
                + f"; {len(records)} record(s); {absent} board player(s) with no appearance"
            ),
        ),
    )
    if down:
        checks.append(
            QualityCheck.fail(
                "skill_tree.source_withheld",
                stage="skill_tree",
                message=(
                    "a skill-tree source was withheld for this build; its readings publish as "
                    "unavailable and every other reading, board and value is unaffected"
                ),
                observed="; ".join(f"{name}: {sources[name].reason}" for name in down),
                expected="every source published",
                severity=Severity.WARNING,
            ),
        )
    return SkillTreeResult(
        records=records, definitions=definitions, metadata=metadata, checks=checks
    )


@dataclass(slots=True)
class _Reading:
    #: ``qualified`` (rank decided later), or a final state.
    state: str
    value: float | None
    numerator: float | None
    denominator: float | None
    reason: str | None = None

    @property
    def qualified(self) -> bool:
        return self.state == "qualified"


def _reading(
    metric: Metric,
    *,
    position: str,
    values: Mapping[str, float],
    ngs: Mapping[str, float | None] | None,
    ngs_mismatch: set[str],
    player_id: str,
    sources: Mapping[Source, _SourceState],
) -> _Reading:
    """One player's reading of one metric, before ranking."""
    source = sources[metric.source]
    if not source.ok:
        return _Reading("unavailable", None, None, None, source.reason)
    if metric.source == "next_gen_stats":
        stat_type = {
            "avg_time_to_throw": "passing",
            "rush_yards_over_expected_per_att": "rushing",
        }.get(metric.id, "receiving")
        if ngs is None or metric.num not in ngs or ngs.get(metric.num) is None:
            reason = (
                "ngs_volume_mismatch"
                if f"{player_id}|{stat_type}" in ngs_mismatch
                else "not_in_ngs_summary"
            )
            return _Reading("not_covered", None, None, None, reason)
        denominator_key = {
            "ngs_yacoe": "ngs_receiving_receptions",
            "ngs_time_to_throw": "ngs_passing_volume",
            "ngs_ryoe": "ngs_rushing_volume",
        }.get(metric.num, "ngs_receiving_volume")
        value = ngs.get(metric.num)
        return _Reading("qualified", value, None, ngs.get(denominator_key))
    numerator = values.get(metric.num, 0.0)
    if metric.cohort == "appearing":
        return _Reading("qualified", numerator, numerator, None)
    if metric.den is None:  # pragma: no cover - the catalogue gives every rate a denominator
        return _Reading("unavailable", None, None, None, "catalogue")
    denominator = values.get(metric.den, 0.0)
    if metric.id == "pass_epa_per_dropback":
        # ADR-091: over the weeks nflverse publishes a passing EPA for.
        denominator = values.get("epa_dropbacks", 0.0)
    if (
        metric.id == "offense_snap_share"
        and denominator <= 0
        and values.get("games_without_snap_row", 0.0) >= values.get("games", 0.0)
    ):
        return _Reading("not_covered", None, None, None, "no_snap_rows")
    if denominator <= 0:
        return _Reading("no_opportunity", None, numerator, denominator)
    value = numerator / denominator
    minimum = minimum_for(position, metric) or 0.0
    sample = values.get("games", 0.0) if metric.cohort == "games" else denominator
    if sample < minimum:
        return _Reading("below_minimum", value, numerator, denominator)
    return _Reading("qualified", value, numerator, denominator)


def _publish(value: float | None, metric: Metric) -> float | int | None:
    if value is None:
        return None
    if metric.decimals == 0:
        return int(round(value))
    return round(float(value), metric.decimals)


def _publish_side(value: float | None, metric: Metric, side: str) -> float | int | None:
    """A numerator or denominator as published: counts as integers, EPA and yards rounded."""
    if value is None:
        return None
    if metric.kind == "volume":
        return None if side == "denominator" else _publish(value, metric)
    if side == "numerator" and metric.numerator_label is None:
        return None
    if float(value).is_integer():
        return int(value)
    return round(float(value), 3)


def _combine_record(
    base: Mapping[str, Any],
    *,
    player_id: str,
    position: str,
    games: int,
    source: _SourceState,
    reading: tuple[float, int, str] | None,
    cohorts: Mapping[str, list[float]],
) -> dict[str, Any]:
    record: dict[str, Any] = {
        **base,
        "player_id": player_id,
        "position": position,
        "metric_id": COMBINE_METRIC.id,
        "state": "unavailable",
        "value": None,
        "numerator": None,
        "denominator": None,
        "rank": None,
        "percentile": None,
        "cohort_size": None,
        "games": games,
        "source_season": None,
        "reason": source.reason,
    }
    if not source.ok:
        return record
    if reading is None:
        record.update({"state": "not_covered", "reason": "no_combine_forty"})
        return record
    forty, year, tested_as = reading
    cohort = cohorts.get(tested_as, [])
    located = _locate(forty, cohort, decimals=COMBINE_METRIC.decimals)
    record.update(
        {
            "state": "ranked" if located is not None else "small_cohort",
            "value": round(forty, COMBINE_METRIC.decimals),
            "rank": None if located is None else located[0],
            "percentile": None if located is None else located[1],
            "cohort_size": len(cohort),
            "source_season": year,
            # The combine position he was ranked within, when it is not the board's.
            "reason": None if tested_as == position else f"tested_as:{tested_as}",
        },
    )
    return record


def _locate(value: float, cohort: Sequence[float], *, decimals: int) -> tuple[int, float] | None:
    """Rank and percentile of a tester's own time among every tester (faster first)."""
    n = len(cohort)
    if n < max(MIN_COHORT, 2):
        return None
    mine = -_scaled(value, decimals)
    ordered = sorted(-_scaled(time, decimals) for time in cohort)
    behind = bisect.bisect_left(ordered, mine)
    ahead = n - bisect.bisect_right(ordered, mine)
    ties = n - behind - ahead
    if ties < 1:  # pragma: no cover - a linked tester is always in his own cohort
        return None
    return ahead + 1, round(100.0 * (behind + (ties - 1) / 2) / (n - 1), 1)


# ------------------------------------------------------------------------ definitions


def _cohort_rule(metric: Metric, position: str) -> str:
    noun = {
        "QB": "quarterbacks",
        "RB": "running backs",
        "WR": "wide receivers",
        "TE": "tight ends",
    }[position]
    minimum = minimum_for(position, metric)
    small = f" A cohort smaller than {MIN_COHORT} ranks no one."
    if metric.cohort == "appearing":
        return (
            f"Ranked among every one of the {noun} who has appeared this season, zeros included."
            + small
        )
    if metric.cohort == "games":
        return (
            f"Ranked among {noun} with at least {int(minimum or 2)} games and a team total above "
            "zero in them; with fewer games the value prints unranked." + small
        )
    if metric.cohort == "minimum":
        return (
            f"Ranked among {noun} with at least {int(minimum or 0)} {metric.minimum_unit}; below "
            "that the value prints unranked with its sample." + small
        )
    if metric.cohort == "ngs":
        return (
            f"Ranked among {noun} whose Next Gen Stats season summary matches their official "
            "volume through the cutoff (Next Gen Stats' own qualification is the minimum)." + small
        )
    if metric.cohort == "combine":
        return (
            "Ranked among every NFL Scouting Combine tester at the same combine position since "
            f"{COMBINE_FIRST_YEAR} with a recorded time, faster first." + small
        )
    return "Not ranked."


def skill_tree_definitions(
    *,
    season: int,
    through_week: int,
    build_id: str,
    schema_version: str,
    sources: Mapping[Source, _SourceState],
) -> list[dict[str, Any]]:
    """One definition record per position × metric, in each tree's reading order."""
    window = f"{season} regular season, weeks 1–{through_week}"
    out: list[dict[str, Any]] = []
    for position in SKILL_TREE_POSITIONS:
        entries: list[tuple[Metric, str, str | None, str | None, int | None, int, str | None]] = [
            (PRESENCE_METRIC, "presence", None, None, None, 0, None)
        ]
        for branch_order, branch in enumerate(TREES[position], start=1):
            for order, node in enumerate(branch.nodes, start=1):
                entries.append(
                    (
                        CATALOG[node.metric],
                        "node",
                        branch.id,
                        branch.label,
                        branch_order,
                        order,
                        None,
                    )
                )
                for detail_order, detail in enumerate(node.details, start=1):
                    entries.append(
                        (
                            CATALOG[detail],
                            "detail",
                            branch.id,
                            branch.label,
                            branch_order,
                            detail_order,
                            node.metric,
                        ),
                    )
        entries.append((COMBINE_METRIC, "archive", None, None, None, 0, None))
        for metric, role, branch_id, branch_label, place, order, parent in entries:
            state = sources[metric.source]
            minimum = (
                minimum_for(position, metric) if metric.cohort in ("minimum", "games") else None
            )
            minimum_unit = None
            if minimum is not None:
                minimum_unit = metric.minimum_unit if metric.cohort == "minimum" else "games"
            out.append(
                {
                    "schema_version": schema_version,
                    "build_id": build_id,
                    "season": season,
                    "through_week": through_week,
                    "method_version": SKILL_TREE_RULE_VERSION,
                    "position": position,
                    "metric_id": metric.id,
                    "role": role,
                    "branch_id": branch_id,
                    "branch_label": branch_label,
                    "branch_order": place,
                    "order": order,
                    "parent_metric_id": parent,
                    "label": metric.label,
                    "short_label": metric.short_label,
                    "kind": metric.kind,
                    "direction": metric.direction,
                    "unit": metric.unit,
                    "decimals": metric.decimals,
                    "source_id": metric.source,
                    "source_label": SOURCE_LABELS[metric.source],
                    "source_fields": list(metric.source_fields),
                    "formula": metric.formula,
                    "numerator_label": metric.numerator_label,
                    "denominator_label": metric.denominator_label,
                    "minimum": minimum,
                    "minimum_unit": minimum_unit,
                    "cohort_rule": _cohort_rule(metric, position),
                    "definition": metric.definition,
                    "interpretation": metric.interpretation,
                    "limitations": metric.limitations,
                    "window": (
                        "Tested before his NFL career" if metric.cohort == "combine" else window
                    ),
                    "source_status": state.status,
                    "source_reason": state.reason,
                },
            )
    return out
