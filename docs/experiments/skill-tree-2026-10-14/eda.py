"""Skill Tree EDA: what nflverse can honestly say about a player's positional profile.

Reproducible analysis behind ADR-107. Reads nflverse through this repository's retrying loader
(``ffdraft.sources.nflverse_http.nflverse_loaders``) and the nflreadpy cache configured by
``NFLREADPY_CACHE`` / ``NFLREADPY_CACHE_DIR``; raw downloads stay in that cache, never in the
repository. Writes one result object as ``report.json`` and renders ``report.md`` from it, so
the prose tables cannot drift from the numbers.

Run (network; ~2-4 minutes with a warm cache)::

    NFLREADPY_CACHE=filesystem NFLREADPY_CACHE_DIR=/tmp/nflcache \\
      uv run python docs/experiments/skill-tree-2026-10-14/eda.py \\
        --current 2026 --cutoff-week 5 --history 2023 2024 2025 \\
        --out docs/experiments/skill-tree-2026-10-14

Every candidate metric is computed here *independently* of the production module
(``ffdraft.signals.skilltree``): plain Polars over the raw loader frames. ``--check-artifact``
recomputes every reading of a built ``player_skill_tree.json`` and reports any difference,
which is how the production numbers were cross-checked.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

POSITIONS = ("QB", "RB", "WR", "TE")
RED_ZONE = 20
GOAL_LINE = 5
EXPLOSIVE_RUN_YARDS = 10
EXPLOSIVE_CATCH_YARDS = 20

PBP_COLUMNS = (
    "season",
    "week",
    "season_type",
    "game_id",
    "game_date",
    "posteam",
    "play_type",
    "pass_attempt",
    "rush_attempt",
    "sack",
    "qb_scramble",
    "qb_dropback",
    "two_point_attempt",
    "aborted_play",
    "play_deleted",
    "passer_player_id",
    "rusher_player_id",
    "receiver_player_id",
    "yardline_100",
    "air_yards",
    "yards_after_catch",
    "passing_yards",
    "receiving_yards",
    "rushing_yards",
    "complete_pass",
    "interception",
    "pass_touchdown",
    "rush_touchdown",
    "epa",
    "qb_epa",
    "success",
    "cpoe",
)


def _flag(name: str) -> pl.Expr:
    return pl.col(name).cast(pl.Float64).fill_null(0.0) == 1.0


def _ratio(num: float | None, den: float | None) -> float | None:
    if num is None or den is None or den <= 0:
        return None
    return num / den


def _round(value: float | None, digits: int = 4) -> float | None:
    if value is None or (isinstance(value, float) and not math.isfinite(value)):
        return None
    return round(float(value), digits)


# ----------------------------------------------------------------------------- loading


@dataclass
class SeasonFrames:
    season: int
    pbp: pl.DataFrame
    stats: pl.DataFrame
    snaps: pl.DataFrame
    schedule: pl.DataFrame
    roster: pl.DataFrame
    ngs: dict[str, pl.DataFrame]


def _loaders() -> Any:
    sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))
    from ffdraft.sources.nflverse_http import nflverse_loaders

    return nflverse_loaders()


def load_season(loaders: Any, season: int) -> SeasonFrames:
    pbp = loaders.load_pbp(seasons=[season])
    pbp = pbp.select([c for c in PBP_COLUMNS if c in pbp.columns])
    stats = loaders.load_player_stats(seasons=[season], summary_level="week")
    snaps = loaders.load_snap_counts(seasons=[season])
    schedule = loaders.load_schedules().filter(pl.col("season") == season)
    roster = loaders.load_rosters(seasons=[season])
    ngs = {}
    for kind in ("passing", "rushing", "receiving"):
        try:
            ngs[kind] = loaders.load_nextgen_stats(seasons=[season], stat_type=kind)
        except Exception as exc:  # noqa: BLE001 - recorded, never silently filled
            ngs[kind] = pl.DataFrame({"error": [f"{type(exc).__name__}: {exc}"]})
    return SeasonFrames(season, pbp, stats, snaps, schedule, roster, ngs)


# ---------------------------------------------------------------------------- inventory


def _missing(frame: pl.DataFrame, columns: Iterable[str]) -> dict[str, float]:
    out: dict[str, float] = {}
    for name in columns:
        if name in frame.columns and frame.height:
            out[name] = round(frame[name].null_count() / frame.height, 4)
    return out


def inventory(frames: SeasonFrames, through_week: int | None) -> dict[str, Any]:
    s = frames.season
    stats = frames.stats
    reg = stats.filter(pl.col("season_type") == "REG")
    if through_week is not None:
        reg = reg.filter(pl.col("week") <= through_week)
    out: dict[str, Any] = {"season": s, "through_week": through_week}
    out["player_stats"] = {
        "grain": "player x week x season_type",
        "rows": stats.height,
        "season_types": sorted(stats["season_type"].unique().to_list()),
        "reg_weeks": sorted(reg["week"].unique().to_list()),
        "duplicates_player_week": int(
            reg.group_by("player_id", "week").len().filter(pl.col("len") > 1).height
        ),
        "reg_players_by_position": {
            pos: int(reg.filter(pl.col("position") == pos)["player_id"].n_unique())
            for pos in POSITIONS
        },
        "missing_player_id": int(reg["player_id"].null_count()),
        "missing_share": _missing(
            reg.filter(pl.col("position").is_in(POSITIONS)),
            (
                "team",
                "passing_epa",
                "passing_cpoe",
                "rushing_epa",
                "receiving_epa",
                "target_share",
                "air_yards_share",
            ),
        ),
    }
    snaps = frames.snaps.filter(pl.col("game_type") == "REG")
    if through_week is not None:
        snaps = snaps.filter(pl.col("week") <= through_week)
    out["snap_counts"] = {
        "grain": "player x game (PFR id)",
        "rows": snaps.height,
        "weeks": sorted(snaps["week"].unique().to_list()),
        "duplicates_player_game": int(
            snaps.group_by("pfr_player_id", "game_id").len().filter(pl.col("len") > 1).height
        ),
        "offense_rows": int(snaps.filter(pl.col("offense_snaps") > 0).height),
    }
    sched = frames.schedule.filter(pl.col("game_type") == "REG")
    played = sched.filter(pl.col("result").is_not_null())
    if through_week is not None:
        played = played.filter(pl.col("week") <= through_week)
    out["schedule"] = {
        "reg_games": sched.height,
        "completed_reg_games_through_cutoff": played.height,
        "latest_completed_gameday": str(played["gameday"].max()) if played.height else None,
    }
    pbp = frames.pbp.filter(pl.col("season_type") == "REG")
    if through_week is not None:
        pbp = pbp.filter(pl.col("week") <= through_week)
    out["pbp"] = {
        "grain": "play",
        "rows": pbp.height,
        "latest_game_date": str(pbp["game_date"].max()) if pbp.height else None,
        "games": int(pbp["game_id"].n_unique()),
        "weeks": sorted(pbp["week"].unique().to_list()),
        "play_types": {
            str(k): int(v)
            for k, v in pbp.group_by("play_type").len().sort("len", descending=True).iter_rows()
        },
        "two_point_attempts": int(pbp.filter(_flag("two_point_attempt")).height),
        "deleted_plays": int(pbp.filter(_flag("play_deleted")).height),
        "aborted_plays": int(pbp.filter(_flag("aborted_play")).height),
        "qb_spikes": int(pbp.filter(pl.col("play_type") == "qb_spike").height),
        "qb_kneels": int(pbp.filter(pl.col("play_type") == "qb_kneel").height),
        "missing_share_on_pass_attempts": _missing(
            pbp.filter(_flag("pass_attempt") & ~_flag("sack") & ~_flag("two_point_attempt")),
            ("receiver_player_id", "air_yards", "cpoe", "epa", "yards_after_catch"),
        ),
        "missing_share_on_rush_attempts": _missing(
            pbp.filter(_flag("rush_attempt") & ~_flag("two_point_attempt")),
            ("rusher_player_id", "epa", "yardline_100", "rushing_yards"),
        ),
    }
    roster = frames.roster
    out["roster"] = {
        "grain": "player x team (season roster)",
        "rows": roster.height,
        "players": int(roster["gsis_id"].n_unique()),
        "players_on_two_teams": int(
            roster.group_by("gsis_id")
            .agg(pl.col("team").n_unique().alias("n"))
            .filter(pl.col("n") > 1)
            .height
        ),
        "missing_share": _missing(roster, ("gsis_id", "pfr_id", "position")),
    }
    ngs: dict[str, Any] = {}
    for kind, frame in frames.ngs.items():
        if "error" in frame.columns:
            ngs[kind] = {"error": frame["error"][0]}
            continue
        weekly = frame.filter((pl.col("week") > 0) & (pl.col("season_type") == "REG"))
        summary = frame.filter((pl.col("week") == 0) & (pl.col("season_type") == "REG"))
        volume = {"passing": "attempts", "rushing": "rush_attempts", "receiving": "targets"}[kind]
        ngs[kind] = {
            "grain": "player x week (week 0 = season summary)",
            "rows": frame.height,
            "season_types": sorted(frame["season_type"].unique().to_list()),
            "weekly_weeks": sorted(weekly["week"].unique().to_list()),
            "weekly_rows": weekly.height,
            "season_summary_rows": summary.height,
            "summary_positions": {
                str(k): int(v) for k, v in summary.group_by("player_position").len().iter_rows()
            },
            "weekly_min_volume": _num(weekly[volume].min()) if weekly.height else None,
            "summary_min_volume": _num(summary[volume].min()) if summary.height else None,
            "duplicates_player_week": int(
                frame.group_by("player_gsis_id", "week", "season_type")
                .len()
                .filter(pl.col("len") > 1)
                .height
            ),
            "missing_gsis": int(frame["player_gsis_id"].null_count()),
        }
    out["nextgen_stats"] = ngs
    return out


def _num(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


# ------------------------------------------------------------------------ identity joins


def position_map(roster: pl.DataFrame) -> dict[str, str]:
    """``gsis_id -> position`` from the season roster; first in sorted order (QB/RB/WR/TE)."""
    out: dict[str, str] = {}
    rows = roster.select("gsis_id", "position").drop_nulls().sort("gsis_id", "position")
    for gsis, position in rows.iter_rows():
        if position in POSITIONS:
            out.setdefault(str(gsis), str(position))
    return out


def pfr_bridge(rosters: Sequence[pl.DataFrame], players: pl.DataFrame | None) -> dict[str, str]:
    pairs: dict[str, set[str]] = {}
    frames = list(rosters) + ([players] if players is not None else [])
    for frame in frames:
        if "pfr_id" not in frame.columns:
            continue
        for pfr, gsis in frame.select("pfr_id", "gsis_id").drop_nulls().iter_rows():
            pairs.setdefault(str(pfr), set()).add(str(gsis))
    return {pfr: next(iter(g)) for pfr, g in pairs.items() if len(g) == 1}


def identity_coverage(
    frames: SeasonFrames, bridge: Mapping[str, str], through_week: int | None
) -> dict[str, Any]:
    roster_ids = set(frames.roster["gsis_id"].drop_nulls().to_list())
    pbp = frames.pbp.filter(pl.col("season_type") == "REG")
    if through_week is not None:
        pbp = pbp.filter(pl.col("week") <= through_week)
    out: dict[str, Any] = {}
    for col in ("passer_player_id", "rusher_player_id", "receiver_player_id"):
        ids = pbp[col].drop_nulls()
        out[col] = {
            "plays_with_id": ids.len(),
            "share_of_plays_in_roster": round(float(ids.is_in(list(roster_ids)).mean() or 0), 4),
        }
    stats = frames.stats.filter(pl.col("season_type") == "REG")
    ids = stats["player_id"].drop_nulls()
    out["player_stats_in_roster"] = round(float(ids.is_in(list(roster_ids)).mean() or 0), 4)
    snaps = frames.snaps.filter((pl.col("game_type") == "REG") & (pl.col("offense_snaps") > 0))
    if through_week is not None:
        snaps = snaps.filter(pl.col("week") <= through_week)
    bridged = snaps["pfr_player_id"].map_elements(
        lambda v: bridge.get(str(v)), return_dtype=pl.String
    )
    positions = snaps.filter(pl.col("position").is_in(POSITIONS))
    bridged_pos = positions["pfr_player_id"].map_elements(
        lambda v: bridge.get(str(v)), return_dtype=pl.String
    )
    out["snap_rows_bridged_to_gsis"] = {
        "all_offense_rows": snaps.height,
        "bridged_share": round(1 - bridged.null_count() / max(1, snaps.height), 4),
        "qb_rb_wr_te_rows": positions.height,
        "qb_rb_wr_te_unbridged": int(bridged_pos.null_count()),
    }
    for kind, frame in frames.ngs.items():
        if "error" in frame.columns:
            continue
        ids = frame["player_gsis_id"].drop_nulls()
        out[f"ngs_{kind}_in_roster"] = round(float(ids.is_in(list(roster_ids)).mean() or 0), 4)
    return out


# --------------------------------------------------------------------------- player rows


def appearances(
    frames: SeasonFrames, bridge: Mapping[str, str], weeks: Sequence[int]
) -> pl.DataFrame:
    """One row per (gsis, week): he appeared (stats row or offensive snap) and for whom."""
    stats = (
        frames.stats.filter((pl.col("season_type") == "REG") & pl.col("week").is_in(weeks))
        .select(pl.col("player_id").alias("gsis"), "week", pl.col("team").alias("team_s"))
        .unique(["gsis", "week"])
    )
    snaps = frames.snaps.filter(
        (pl.col("game_type") == "REG") & pl.col("week").is_in(weeks) & (pl.col("offense_snaps") > 0)
    )
    snaps = snaps.with_columns(
        pl.col("pfr_player_id")
        .map_elements(lambda v: bridge.get(str(v)), return_dtype=pl.String)
        .alias("gsis")
    ).filter(pl.col("gsis").is_not_null())
    snap_rows = snaps.group_by("gsis", "week").agg(
        pl.col("team").first().alias("team_n"),
        pl.col("offense_snaps").sum().alias("snaps"),
    )
    joined = stats.join(snap_rows, on=["gsis", "week"], how="full", coalesce=True)
    return joined.with_columns(
        pl.coalesce("team_s", "team_n").alias("team"), pl.col("snaps").fill_null(0.0)
    ).select("gsis", "week", "team", "snaps")


def team_snaps(frames: SeasonFrames, weeks: Sequence[int]) -> tuple[pl.DataFrame, dict[str, Any]]:
    """Team offensive snaps per (week, team): snaps / pct of the player with the highest pct.

    nflverse's snap file has no team total. A player on the field for every snap (pct 1.0,
    ordinarily an offensive lineman) carries it exactly; otherwise his snaps / pct is the
    least-rounded estimate, because pct is published to two decimals.
    """
    s = frames.snaps.filter(
        (pl.col("game_type") == "REG") & pl.col("week").is_in(weeks) & (pl.col("offense_pct") > 0)
    ).with_columns((pl.col("offense_snaps") / pl.col("offense_pct")).alias("implied"))
    top = (
        s.sort(["offense_pct", "offense_snaps"], descending=True)
        .group_by("week", "team", maintain_order=True)
        .agg(
            pl.col("implied").first().round(0).alias("team_snaps"),
            pl.col("offense_pct").first().alias("top_pct"),
            pl.col("implied").median().round(0).alias("median_implied"),
        )
    )
    diag = {
        "team_games": top.height,
        "top_player_pct_is_1": round(float((top["top_pct"] >= 0.999).mean() or 0), 4),
        "median_implied_differs_from_top": int((top["team_snaps"] != top["median_implied"]).sum()),
        "team_snaps_p10_p50_p90": [_num(top["team_snaps"].quantile(q)) for q in (0.1, 0.5, 0.9)],
    }
    return top.select("week", "team", "team_snaps"), diag


def play_universes(frames: SeasonFrames, weeks: Sequence[int]) -> dict[str, pl.DataFrame]:
    p = frames.pbp.filter((pl.col("season_type") == "REG") & pl.col("week").is_in(weeks))
    not2 = ~_flag("two_point_attempt")
    dropbacks = p.filter(_flag("pass_attempt") & not2 & pl.col("passer_player_id").is_not_null())
    targets = p.filter(
        _flag("pass_attempt") & ~_flag("sack") & not2 & pl.col("receiver_player_id").is_not_null()
    )
    rushes = p.filter(_flag("rush_attempt") & not2 & pl.col("rusher_player_id").is_not_null())
    carries = rushes.filter(pl.col("play_type") != "qb_kneel")
    return {"dropbacks": dropbacks, "targets": targets, "rushes": rushes, "carries": carries}


def player_table(
    frames: SeasonFrames,
    bridge: Mapping[str, str],
    weeks: Sequence[int],
) -> pl.DataFrame:
    """Every candidate numerator and denominator per player, over ``weeks`` (REG)."""
    apps = appearances(frames, bridge, weeks)
    pos = position_map(frames.roster)
    stats = frames.stats.filter((pl.col("season_type") == "REG") & pl.col("week").is_in(weeks))
    box = stats.group_by("player_id").agg(
        pl.col("attempts").sum().alias("att"),
        pl.col("completions").sum().alias("cmp"),
        pl.col("passing_yards").sum().alias("pass_yds"),
        pl.col("passing_tds").sum().alias("pass_td"),
        pl.col("passing_interceptions").sum().alias("int"),
        pl.col("sacks_suffered").sum().alias("sacks"),
        pl.col("passing_epa").sum().alias("pass_epa"),
        pl.col("passing_air_yards").sum().alias("pass_air"),
        pl.col("carries").sum().alias("car"),
        pl.col("rushing_yards").sum().alias("rush_yds"),
        pl.col("rushing_tds").sum().alias("rush_td"),
        pl.col("targets").sum().alias("tgt"),
        pl.col("receptions").sum().alias("rec"),
        pl.col("receiving_yards").sum().alias("rec_yds"),
        pl.col("receiving_tds").sum().alias("rec_td"),
        pl.col("receiving_air_yards").sum().alias("rec_air"),
        pl.col("receiving_yards_after_catch").sum().alias("yac"),
        pl.col("position").first().alias("stats_position"),
        pl.col("player_display_name").first().alias("name"),
    )
    # Team totals per (week, team) from the player rows (usage_signals_v1's provenance).
    team_box = stats.group_by("week", "team").agg(
        pl.col("targets").sum().alias("team_tgt"),
        pl.col("carries").sum().alias("team_car"),
        pl.col("receiving_air_yards").sum().alias("team_air"),
    )
    u = play_universes(frames, weeks)
    db = (
        u["dropbacks"]
        .group_by("passer_player_id")
        .agg(
            pl.len().alias("db_pbp"),
            (pl.col("epa") > 0).sum().alias("db_success"),
            pl.col("epa").sum().alias("db_epa"),
            pl.col("cpoe").sum().alias("cpoe_sum"),
            pl.col("cpoe").is_not_null().sum().alias("cpoe_n"),
            (pl.col("yardline_100") <= RED_ZONE).sum().alias("rz_db"),
        )
    )
    qb_rush = (
        u["rushes"]
        .group_by("rusher_player_id")
        .agg(
            (_flag("qb_scramble")).sum().alias("scrambles"),
            (pl.col("play_type") == "qb_kneel").sum().alias("kneels"),
            (~_flag("qb_scramble") & (pl.col("play_type") != "qb_kneel")).sum().alias("designed"),
            ((pl.col("yardline_100") <= RED_ZONE) & (pl.col("play_type") != "qb_kneel"))
            .sum()
            .alias("rz_rush"),
            ((pl.col("yardline_100") <= GOAL_LINE) & (pl.col("play_type") != "qb_kneel"))
            .sum()
            .alias("gl_rush"),
        )
    )
    car = (
        u["carries"]
        .group_by("rusher_player_id")
        .agg(
            pl.len().alias("car_nk"),
            pl.col("epa").sum().alias("rush_epa"),
            (pl.col("epa") > 0).sum().alias("rush_success"),
            (pl.col("rushing_yards") >= EXPLOSIVE_RUN_YARDS).sum().alias("run10"),
            (pl.col("yardline_100") <= RED_ZONE).sum().alias("rz_car"),
            (pl.col("yardline_100") <= GOAL_LINE).sum().alias("gl_car"),
            pl.col("rushing_yards").sum().alias("rush_yds_nk"),
        )
    )
    tg = (
        u["targets"]
        .group_by("receiver_player_id")
        .agg(
            pl.len().alias("tgt_pbp"),
            pl.col("epa").sum().alias("rec_epa"),
            (pl.col("epa") > 0).sum().alias("rec_success"),
            ((pl.col("receiving_yards") >= EXPLOSIVE_CATCH_YARDS) & _flag("complete_pass"))
            .sum()
            .alias("catch20"),
            (pl.col("yardline_100") <= RED_ZONE).sum().alias("rz_tgt"),
            (pl.col("air_yards") >= pl.col("yardline_100")).sum().alias("ez_tgt"),
        )
    )
    team_pbp = (
        u["carries"]
        .group_by("week", "posteam")
        .agg(
            pl.len().alias("team_car_nk"),
            (pl.col("yardline_100") <= RED_ZONE).sum().alias("team_rz_car"),
            (pl.col("yardline_100") <= GOAL_LINE).sum().alias("team_gl_car"),
        )
        .join(
            u["targets"]
            .group_by("week", "posteam")
            .agg(
                (pl.col("yardline_100") <= RED_ZONE).sum().alias("team_rz_tgt"),
                (pl.col("air_yards") >= pl.col("yardline_100")).sum().alias("team_ez_tgt"),
            ),
            on=["week", "posteam"],
            how="full",
            coalesce=True,
        )
        .rename({"posteam": "team"})
    )
    tsnaps, _ = team_snaps(frames, weeks)
    denoms = (
        apps.join(team_box, on=["week", "team"], how="left")
        .join(team_pbp, on=["week", "team"], how="left")
        .join(tsnaps, on=["week", "team"], how="left")
        .group_by("gsis")
        .agg(
            pl.len().alias("games"),
            pl.col("snaps").sum(),
            pl.col("team_snaps").sum(),
            pl.col("team_snaps").null_count().alias("games_missing_team_snaps"),
            *[
                pl.col(c).fill_null(0).sum()
                for c in (
                    "team_tgt",
                    "team_car",
                    "team_air",
                    "team_car_nk",
                    "team_rz_car",
                    "team_gl_car",
                    "team_rz_tgt",
                    "team_ez_tgt",
                )
            ],
            pl.col("team").n_unique().alias("teams"),
        )
    )
    table = (
        denoms.join(box, left_on="gsis", right_on="player_id", how="left")
        .join(db, left_on="gsis", right_on="passer_player_id", how="left")
        .join(qb_rush, left_on="gsis", right_on="rusher_player_id", how="left")
        .join(car, left_on="gsis", right_on="rusher_player_id", how="left")
        .join(tg, left_on="gsis", right_on="receiver_player_id", how="left")
    )
    numeric = [c for c, t in table.schema.items() if t.is_numeric() and c not in ("teams",)]
    table = table.with_columns([pl.col(c).cast(pl.Float64).fill_null(0.0) for c in numeric])
    table = table.with_columns(
        pl.col("gsis").map_elements(lambda g: pos.get(str(g)), return_dtype=pl.String).alias("pos")
    )
    return table


# ----------------------------------------------------------------------------- metrics


@dataclass(frozen=True)
class Metric:
    id: str
    position: tuple[str, ...]
    num: str
    den: str
    kind: str  # total | rate | share
    minimum: float  # denominator minimum for a qualified rate (totals: 0)
    direction: str  # higher | lower | context
    source: str  # pbp | official | snaps | ngs
    scale: float = 1.0


def _m(*args: Any, **kwargs: Any) -> Metric:
    return Metric(*args, **kwargs)


ALL = POSITIONS
CANDIDATES: tuple[Metric, ...] = (
    # QB
    _m("pass_attempts", ("QB",), "att", "one", "total", 0, "higher", "official"),
    _m("completions", ("QB",), "cmp", "one", "total", 0, "higher", "official"),
    _m("passing_yards", ("QB",), "pass_yds", "one", "total", 0, "higher", "official"),
    _m("passing_tds", ("QB",), "pass_td", "one", "total", 0, "higher", "official"),
    _m("completion_pct", ("QB",), "cmp", "att", "rate", 50, "higher", "official"),
    _m("yards_per_attempt", ("QB",), "pass_yds", "att", "rate", 50, "higher", "official"),
    _m("cpoe", ("QB",), "cpoe_sum", "cpoe_n", "rate", 50, "higher", "pbp"),
    _m("intended_air_yards", ("QB",), "pass_air", "att", "rate", 50, "context", "official"),
    _m("epa_per_dropback", ("QB",), "pass_epa", "dropbacks", "rate", 50, "higher", "official"),
    _m("dropback_success", ("QB",), "db_success", "db_pbp", "rate", 50, "higher", "pbp"),
    _m("sack_rate", ("QB",), "sacks", "dropbacks", "rate", 50, "lower", "official"),
    _m("int_rate", ("QB",), "int", "att", "rate", 50, "lower", "official"),
    _m("td_rate", ("QB",), "pass_td", "att", "rate", 50, "higher", "official"),
    _m("designed_rushes", ("QB",), "designed", "one", "total", 0, "higher", "pbp"),
    _m("scrambles", ("QB",), "scrambles", "one", "total", 0, "higher", "pbp"),
    _m("scramble_rate", ("QB",), "scrambles", "db_all", "rate", 50, "context", "pbp"),
    _m("rushing_yards", ("QB", "RB"), "rush_yds", "one", "total", 0, "higher", "official"),
    _m("rushing_tds", ("QB", "RB"), "rush_td", "one", "total", 0, "higher", "official"),
    _m("red_zone_dropbacks", ("QB",), "rz_db", "one", "total", 0, "higher", "pbp"),
    _m("red_zone_rushes", ("QB",), "rz_rush", "one", "total", 0, "higher", "pbp"),
    _m("goal_line_rushes", ("QB",), "gl_rush", "one", "total", 0, "higher", "pbp"),
    # RB
    _m("carries", ("RB",), "car", "one", "total", 0, "higher", "official"),
    _m("carry_share", ("RB",), "car", "team_car", "share", 2, "higher", "official"),
    _m("carry_share_no_kneel", ("RB",), "car_nk", "team_car_nk", "share", 2, "higher", "pbp"),
    _m("snap_share", ("RB", "WR", "TE"), "snaps", "team_snaps", "share", 2, "higher", "snaps"),
    _m("yards_per_carry", ("RB",), "rush_yds", "car", "rate", 25, "higher", "official"),
    _m("rush_epa_per_carry", ("RB",), "rush_epa", "car_nk", "rate", 25, "higher", "pbp"),
    _m("rush_success", ("RB",), "rush_success", "car_nk", "rate", 25, "higher", "pbp"),
    _m("explosive_run_rate", ("RB",), "run10", "car_nk", "rate", 25, "higher", "pbp"),
    _m("red_zone_carries", ("RB",), "rz_car", "one", "total", 0, "higher", "pbp"),
    _m("red_zone_carry_share", ("RB",), "rz_car", "team_rz_car", "share", 2, "higher", "pbp"),
    _m("goal_line_carries", ("RB",), "gl_car", "one", "total", 0, "higher", "pbp"),
    _m("goal_line_carry_share", ("RB",), "gl_car", "team_gl_car", "share", 2, "higher", "pbp"),
    # receiving (RB/WR/TE)
    _m("targets", ("RB", "WR", "TE"), "tgt", "one", "total", 0, "higher", "official"),
    _m("receptions", ("RB", "WR", "TE"), "rec", "one", "total", 0, "higher", "official"),
    _m("receiving_yards", ("RB", "WR", "TE"), "rec_yds", "one", "total", 0, "higher", "official"),
    _m("receiving_tds", ("RB", "WR", "TE"), "rec_td", "one", "total", 0, "higher", "official"),
    _m("target_share", ("RB", "WR", "TE"), "tgt", "team_tgt", "share", 2, "higher", "official"),
    _m("air_yards_share", ("WR", "TE"), "rec_air", "team_air", "share", 2, "higher", "official"),
    _m("catch_rate", ("WR", "TE"), "rec", "tgt", "rate", 15, "higher", "official"),
    _m("catch_rate_rb", ("RB",), "rec", "tgt", "rate", 10, "higher", "official"),
    _m("yards_per_target", ("WR", "TE"), "rec_yds", "tgt", "rate", 15, "higher", "official"),
    _m("yards_per_target_rb", ("RB",), "rec_yds", "tgt", "rate", 10, "higher", "official"),
    _m("yards_per_reception", ("WR", "TE"), "rec_yds", "rec", "rate", 10, "higher", "official"),
    _m("adot", ("WR", "TE"), "rec_air", "tgt", "rate", 15, "context", "official"),
    _m("yac_per_reception", ("RB", "WR", "TE"), "yac", "rec", "rate", 10, "higher", "official"),
    _m("rec_epa_per_target", ("WR", "TE"), "rec_epa", "tgt_pbp", "rate", 15, "higher", "pbp"),
    _m("rec_epa_per_target_rb", ("RB",), "rec_epa", "tgt_pbp", "rate", 10, "higher", "pbp"),
    _m("explosive_catches", ("WR", "TE"), "catch20", "one", "total", 0, "higher", "pbp"),
    _m("explosive_catch_rate", ("WR", "TE"), "catch20", "tgt_pbp", "rate", 15, "higher", "pbp"),
    _m("red_zone_targets", ("RB", "WR", "TE"), "rz_tgt", "one", "total", 0, "higher", "pbp"),
    _m(
        "red_zone_target_share",
        ("WR", "TE"),
        "rz_tgt",
        "team_rz_tgt",
        "share",
        2,
        "higher",
        "pbp",
    ),
    _m("end_zone_targets", ("WR", "TE"), "ez_tgt", "one", "total", 0, "higher", "pbp"),
)


def add_derived(table: pl.DataFrame) -> pl.DataFrame:
    return table.with_columns(
        (pl.col("att") + pl.col("sacks")).alias("dropbacks"),
        (pl.col("db_pbp") + pl.col("scrambles")).alias("db_all"),
        pl.lit(1.0).alias("one"),
    )


def metric_values(table: pl.DataFrame, metric: Metric, *, qualified: bool = True) -> pl.DataFrame:
    """Rows of (gsis, name, pos, value, den) for the metric's positions."""
    t = table.filter(pl.col("pos").is_in(metric.position))
    if metric.kind == "total":
        return t.select("gsis", "name", "pos", pl.col(metric.num).alias("value"), "games")
    den_ok = pl.col(metric.den) >= metric.minimum if metric.kind == "rate" else pl.lit(True)
    if metric.kind == "share":
        den_ok = (pl.col("games") >= metric.minimum) & (pl.col(metric.den) > 0)
    if qualified:
        t = t.filter(den_ok & (pl.col(metric.den) > 0))
    else:
        t = t.filter(pl.col(metric.den) > 0)
    return t.select(
        "gsis",
        "name",
        "pos",
        (pl.col(metric.num) / pl.col(metric.den)).alias("value"),
        pl.col(metric.den).alias("den"),
    )


def summarize(values: pl.Series) -> dict[str, Any]:
    if values.len() == 0:
        return {"n": 0}
    v = values.drop_nulls()
    q = {
        k: _round(_num(v.quantile(p, "linear")))
        for k, p in (("p10", 0.1), ("p25", 0.25), ("p50", 0.5), ("p75", 0.75), ("p90", 0.9))
    }
    return {"n": v.len(), "min": _round(_num(v.min())), **q, "max": _round(_num(v.max()))}


def outliers(frame: pl.DataFrame) -> list[dict[str, Any]]:
    if frame.height < 8:
        return []
    q1, q3 = frame["value"].quantile(0.25), frame["value"].quantile(0.75)
    if q1 is None or q3 is None:
        return []
    iqr = q3 - q1
    lo, hi = q1 - 1.5 * iqr, q3 + 1.5 * iqr
    out = frame.filter((pl.col("value") < lo) | (pl.col("value") > hi)).sort("value")
    return [
        {"name": n, "value": _round(v), "den": _round(d, 1)}
        for n, v, d in out.select("name", "value", "den").iter_rows()
    ][:6]


# -------------------------------------------------------------------------- statistics


def spearman(a: Sequence[float], b: Sequence[float]) -> float | None:
    if len(a) < 6:
        return None
    ra = pl.Series(a).rank("average").to_numpy()
    rb = pl.Series(b).rank("average").to_numpy()
    if np.std(ra) == 0 or np.std(rb) == 0:
        return None
    return float(np.corrcoef(ra, rb)[0, 1])


def pearson(a: Sequence[float], b: Sequence[float]) -> float | None:
    if len(a) < 6:
        return None
    x, y = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    if np.std(x) == 0 or np.std(y) == 0:
        return None
    return float(np.corrcoef(x, y)[0, 1])


def spearman_brown(r: float | None) -> float | None:
    if r is None or r <= -1:
        return None
    return 2 * r / (1 + r)


def joined_values(
    a: pl.DataFrame, b: pl.DataFrame, metric: Metric
) -> tuple[list[float], list[float]]:
    j = a.select("gsis", pl.col("value").alias("a")).join(
        b.select("gsis", pl.col("value").alias("b")), on="gsis", how="inner"
    )
    return j["a"].to_list(), j["b"].to_list()


# ------------------------------------------------------------------------------ analyses


def coverage_current(table: pl.DataFrame) -> dict[str, Any]:
    """Per metric x position: appearing, zero-opportunity, insufficient, qualified."""
    out: dict[str, Any] = {}
    for metric in CANDIDATES:
        for pos in metric.position:
            t = table.filter(pl.col("pos") == pos)
            appearing = t.height
            if metric.kind == "total":
                nonzero = t.filter(pl.col(metric.num) > 0).height
                out[f"{metric.id}|{pos}"] = {
                    "appearing": appearing,
                    "nonzero": nonzero,
                    "zero": appearing - nonzero,
                }
                continue
            zero = t.filter(pl.col(metric.den) <= 0).height
            if metric.kind == "share":
                qual = t.filter((pl.col("games") >= metric.minimum) & (pl.col(metric.den) > 0))
            else:
                qual = t.filter(pl.col(metric.den) >= metric.minimum)
            out[f"{metric.id}|{pos}"] = {
                "appearing": appearing,
                "zero_opportunity": zero,
                "insufficient": appearing - zero - qual.height,
                "qualified": qual.height,
                "minimum": metric.minimum,
                "minimum_on": "games" if metric.kind == "share" else metric.den,
            }
    return out


def distributions(table: pl.DataFrame) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for metric in CANDIDATES:
        for pos in metric.position:
            vals = metric_values(table.filter(pl.col("pos") == pos), metric)
            entry = summarize(vals["value"])
            if metric.kind != "total":
                entry["outliers"] = outliers(vals)
            out[f"{metric.id}|{pos}"] = entry
    return out


def redundancy(table: pl.DataFrame, threshold: float = 0.8) -> dict[str, Any]:
    """Spearman between candidate metrics among players qualified for both."""
    out: dict[str, Any] = {}
    for pos in POSITIONS:
        metrics = [m for m in CANDIDATES if pos in m.position]
        vals = {m.id: metric_values(table.filter(pl.col("pos") == pos), m) for m in metrics}
        pairs = []
        for i, a in enumerate(metrics):
            for b in metrics[i + 1 :]:
                x, y = joined_values(vals[a.id], vals[b.id], a)
                rho = spearman(x, y)
                if rho is not None:
                    pairs.append({"a": a.id, "b": b.id, "n": len(x), "rho": round(rho, 3)})
        pairs.sort(key=lambda p: -abs(p["rho"]))
        out[pos] = {
            "high": [p for p in pairs if abs(p["rho"]) >= threshold],
            "all_pairs": len(pairs),
        }
    return out


def reliability(frames: SeasonFrames, bridge: Mapping[str, str], last_week: int) -> dict[str, Any]:
    """Split-half (odd vs even weeks), Spearman-Brown corrected, per rate metric."""
    weeks = list(range(1, last_week + 1))
    odd = add_derived(player_table(frames, bridge, [w for w in weeks if w % 2]))
    even = add_derived(player_table(frames, bridge, [w for w in weeks if not w % 2]))
    out: dict[str, Any] = {}
    for metric in CANDIDATES:
        if metric.kind == "total":
            continue
        half = Metric(**{**metric.__dict__, "minimum": metric.minimum / 2})
        for pos in metric.position:
            a = metric_values(odd.filter(pl.col("pos") == pos), half)
            b = metric_values(even.filter(pl.col("pos") == pos), half)
            x, y = joined_values(a, b, metric)
            r = pearson(x, y)
            out[f"{metric.id}|{pos}"] = {
                "n": len(x),
                "split_half_r": _round(r, 3),
                "full_season_reliability": _round(spearman_brown(r), 3),
            }
    return out


def early_season(
    frames: SeasonFrames, bridge: Mapping[str, str], early: int, last_week: int
) -> dict[str, Any]:
    """Weeks 1..early against weeks early+1..last and against the full season."""
    a = add_derived(player_table(frames, bridge, list(range(1, early + 1))))
    b = add_derived(player_table(frames, bridge, list(range(early + 1, last_week + 1))))
    full = add_derived(player_table(frames, bridge, list(range(1, last_week + 1))))
    out: dict[str, Any] = {}
    for metric in CANDIDATES:
        for pos in metric.position:
            ea = metric_values(a.filter(pl.col("pos") == pos), metric)
            rest = metric_values(b.filter(pl.col("pos") == pos), metric)
            fu = metric_values(full.filter(pl.col("pos") == pos), metric)
            x, y = joined_values(ea, rest, metric)
            x2, y2 = joined_values(ea, fu, metric)
            out[f"{metric.id}|{pos}"] = {
                "n_early_vs_rest": len(x),
                "rho_early_vs_rest": _round(spearman(x, y), 3),
                "n_early_vs_full": len(x2),
                "rho_early_vs_full": _round(spearman(x2, y2), 3),
            }
    return out


def recent_window(
    frames: SeasonFrames, bridge: Mapping[str, str], at_week: int, last_week: int, games: int = 3
) -> dict[str, Any]:
    """Does a last-``games`` window anticipate the rest of the season better than to-date?"""
    to_date = add_derived(player_table(frames, bridge, list(range(1, at_week + 1))))
    recent = add_derived(
        player_table(frames, bridge, list(range(at_week - games + 1, at_week + 1)))
    )
    future = add_derived(player_table(frames, bridge, list(range(at_week + 1, last_week + 1))))
    out: dict[str, Any] = {}
    for metric in CANDIDATES:
        if metric.kind == "total":
            continue
        recent_metric = Metric(**{**metric.__dict__, "minimum": metric.minimum * games / at_week})
        for pos in metric.position:
            td = metric_values(to_date.filter(pl.col("pos") == pos), metric)
            rc = metric_values(recent.filter(pl.col("pos") == pos), recent_metric)
            fu = metric_values(future.filter(pl.col("pos") == pos), metric)
            both = td.select("gsis").join(rc.select("gsis"), on="gsis")
            td2, rc2 = td.join(both, on="gsis"), rc.join(both, on="gsis")
            x, y = joined_values(td2, fu, metric)
            x2, y2 = joined_values(rc2, fu, metric)
            out[f"{metric.id}|{pos}"] = {
                "n": min(len(x), len(x2)),
                "rho_to_date_vs_future": _round(spearman(x, y), 3),
                "rho_last3_vs_future": _round(spearman(x2, y2), 3),
            }
    return out


def threshold_sensitivity(
    frames: SeasonFrames, bridge: Mapping[str, str], early: int, last_week: int
) -> dict[str, Any]:
    """Rank agreement of week-``early`` readings with full-season readings by sample size."""
    a = add_derived(player_table(frames, bridge, list(range(1, early + 1))))
    full = add_derived(player_table(frames, bridge, list(range(1, last_week + 1))))
    out: dict[str, Any] = {}
    for metric in CANDIDATES:
        if metric.kind != "rate":
            continue
        for pos in metric.position:
            rows = []
            fu = metric_values(full.filter(pl.col("pos") == pos), metric)
            for factor in (0.25, 0.5, 1.0, 1.5, 2.0):
                m = Metric(**{**metric.__dict__, "minimum": metric.minimum * factor})
                ea = metric_values(a.filter(pl.col("pos") == pos), m)
                x, y = joined_values(ea, fu, m)
                rows.append(
                    {
                        "minimum": m.minimum,
                        "n": len(x),
                        "rho_early_vs_full": _round(spearman(x, y), 3),
                    }
                )
            out[f"{metric.id}|{pos}"] = rows
    return out


def goal_line_sparsity(table: pl.DataFrame) -> dict[str, Any]:
    rbs = table.filter(pl.col("pos") == "RB")
    out = {}
    for col in ("gl_car", "rz_car", "team_gl_car", "team_rz_car"):
        out[col] = summarize(rbs[col])
    out["rbs_with_zero_goal_line_carries"] = int(rbs.filter(pl.col("gl_car") == 0).height)
    out["rbs_appearing"] = rbs.height
    wr = table.filter(pl.col("pos").is_in(["WR", "TE"]))
    out["wr_te_ez_targets"] = summarize(wr["ez_tgt"])
    out["wr_te_zero_ez_targets"] = int(wr.filter(pl.col("ez_tgt") == 0).height)
    return out


def reconcile(
    frames: SeasonFrames, through_week: int | None, bridge: Mapping[str, str]
) -> dict[str, Any]:
    """PBP-derived counts against nflverse's own weekly player totals."""
    weeks = list(range(1, (through_week or 22) + 1))
    t = player_table(frames, bridge, weeks)
    out: dict[str, Any] = {}
    for a, b, label in (
        ("db_pbp", None, "dropbacks: pbp pass_attempt (incl. sacks) vs attempts + sacks"),
        ("tgt_pbp", "tgt", "targets"),
        ("car_nk", None, "carries excluding kneels vs official carries - kneels"),
    ):
        if a == "db_pbp":
            diff = t.filter((pl.col("db_pbp") - pl.col("att") - pl.col("sacks")).abs() > 0.5)
            out[label] = {"players_differing": diff.height}
        elif a == "car_nk":
            diff = t.filter((pl.col("car_nk") - (pl.col("car") - pl.col("kneels"))).abs() > 0.5)
            out[label] = {"players_differing": diff.height}
        else:
            diff = t.filter((pl.col(a) - pl.col(str(b))).abs() > 0.5)
            out[label] = {"players_differing": diff.height}
    # CPOE: nflverse's weekly passing_cpoe is a mean per week; the pooled season value differs.
    stats = frames.stats.filter((pl.col("season_type") == "REG") & pl.col("week").is_in(weeks))
    unweighted = (
        stats.filter(pl.col("passing_cpoe").is_not_null())
        .group_by("player_id")
        .agg(pl.col("passing_cpoe").mean().alias("mean_of_weeks"))
    )
    pooled = t.filter(pl.col("cpoe_n") >= 50).select(
        "gsis", "name", (pl.col("cpoe_sum") / pl.col("cpoe_n")).alias("pooled")
    )
    j = pooled.join(unweighted, left_on="gsis", right_on="player_id")
    gap = (j["pooled"] - j["mean_of_weeks"]).abs()
    out["cpoe_pooled_vs_mean_of_weekly"] = {
        "qbs": j.height,
        "median_abs_gap_pp": _round(_num(gap.median()), 3),
        "max_abs_gap_pp": _round(_num(gap.max()), 3),
    }
    # Carry share: official carries (incl. QB kneels) vs a kneel-free denominator.
    rb = add_derived(t).filter((pl.col("pos") == "RB") & (pl.col("games") >= 2))
    a1 = rb["car"] / rb["team_car"]
    a2 = rb["car_nk"] / rb["team_car_nk"]
    out["carry_share_kneel_effect_pp"] = {
        "rbs": rb.height,
        "median": _round(_num(((a2 - a1) * 100).median()), 3),
        "max": _round(_num(((a2 - a1) * 100).max()), 3),
    }
    return out


def ngs_summary_checks(
    frames: SeasonFrames, through_week: int, table: pl.DataFrame
) -> dict[str, Any]:
    """Season-summary (week 0) rows: do they cover exactly the cutoff window, and whom?"""
    out: dict[str, Any] = {}
    official = table.select("gsis", "pos", "att", "car", "tgt", "rec", "cpoe_sum", "cpoe_n")
    spec = {
        "passing": ("attempts", "att"),
        "rushing": ("rush_attempts", "car"),
        "receiving": ("targets", "tgt"),
    }
    for kind, frame in frames.ngs.items():
        if "error" in frame.columns:
            out[kind] = {"error": frame["error"][0]}
            continue
        weekly = frame.filter((pl.col("week") > 0) & (pl.col("season_type") == "REG"))
        summary = frame.filter((pl.col("week") == 0) & (pl.col("season_type") == "REG"))
        ngs_col, off_col = spec[kind]
        j = summary.join(official, left_on="player_gsis_id", right_on="gsis", how="left")
        diff = (j[ngs_col] - j[off_col]).abs()
        entry: dict[str, Any] = {
            "max_weekly_week": int(weekly["week"].max() or 0),
            "weeks_beyond_cutoff": int(weekly.filter(pl.col("week") > through_week).height),
            "summary_rows": summary.height,
            "volume_equal_official": int((diff == 0).sum()),
            "volume_within_1": int((diff <= 1).sum()),
            "volume_unmatched_player": int(j[off_col].null_count()),
            "weekly_rows_cover_share_of_official_volume": None,
        }
        wk = weekly.group_by("player_gsis_id").agg(pl.col(ngs_col).sum().alias("weekly_vol"))
        jj = official.join(wk, left_on="gsis", right_on="player_gsis_id", how="left")
        for pos in POSITIONS:
            sub = jj.filter((pl.col("pos") == pos) & (pl.col(off_col) > 0))
            if sub.height and sub[off_col].sum() > 0:
                entry.setdefault("weekly_rows_by_position", {})[pos] = round(
                    float(sub["weekly_vol"].fill_null(0).sum() / sub[off_col].sum()), 3
                )
        entry["weekly_rows_cover_share_of_official_volume"] = entry.pop(
            "weekly_rows_by_position", {}
        )
        if kind == "passing":
            jq = j.with_columns((pl.col("cpoe_sum") / pl.col("cpoe_n")).alias("pbp_cpoe"))
            entry["ngs_cpoe_vs_pbp_cpoe_rho"] = _round(
                spearman(
                    jq["completion_percentage_above_expectation"].to_list(),
                    jq["pbp_cpoe"].to_list(),
                ),
                3,
            )
            jq2 = j.with_columns((pl.col("att") > 0).alias("ok")).filter(pl.col("ok"))
            entry["summary_metrics"] = {
                c: summarize(summary[c])
                for c in (
                    "avg_time_to_throw",
                    "avg_intended_air_yards",
                    "aggressiveness",
                    "completion_percentage_above_expectation",
                )
            }
            del jq2
        if kind == "rushing":
            entry["summary_metrics"] = {
                c: summarize(summary[c])
                for c in (
                    "rush_yards_over_expected_per_att",
                    "efficiency",
                    "percent_attempts_gte_eight_defenders",
                )
            }
        if kind == "receiving":
            entry["summary_metrics"] = {
                c: summarize(summary[c])
                for c in ("avg_separation", "avg_cushion", "avg_yac_above_expectation")
            }
        out[kind] = entry
    return out


def ngs_redundancy(frames: SeasonFrames, table: pl.DataFrame) -> dict[str, Any]:
    """How NGS season readings relate to the PBP/official metrics they sit beside."""
    out: dict[str, Any] = {}
    t = add_derived(table)
    rec = frames.ngs.get("receiving")
    if rec is not None and "error" not in rec.columns:
        s = rec.filter((pl.col("week") == 0) & (pl.col("season_type") == "REG"))
        j = s.join(t, left_on="player_gsis_id", right_on="gsis")
        j = j.with_columns(
            (pl.col("rec_air") / pl.col("tgt")).alias("adot"),
            (pl.col("yac") / pl.col("rec")).alias("yac_rec"),
            (pl.col("rec_epa") / pl.col("tgt_pbp")).alias("epa_tgt"),
            (pl.col("rec") / pl.col("tgt")).alias("catch_rate"),
        )
        for a, b in (
            ("avg_separation", "adot"),
            ("avg_separation", "catch_rate"),
            ("avg_cushion", "adot"),
            ("avg_yac_above_expectation", "yac_rec"),
            ("avg_yac_above_expectation", "epa_tgt"),
            ("avg_intended_air_yards", "adot"),
        ):
            out[f"{a}~{b}"] = {
                "n": j.height,
                "rho": _round(spearman(j[a].to_list(), j[b].to_list()), 3),
            }
    rush = frames.ngs.get("rushing")
    if rush is not None and "error" not in rush.columns:
        s = rush.filter((pl.col("week") == 0) & (pl.col("season_type") == "REG"))
        j = s.join(t, left_on="player_gsis_id", right_on="gsis").with_columns(
            (pl.col("rush_yds") / pl.col("car")).alias("ypc"),
            (pl.col("rush_epa") / pl.col("car_nk")).alias("epa_car"),
            (pl.col("rush_success") / pl.col("car_nk")).alias("succ"),
        )
        for b in ("ypc", "epa_car", "succ"):
            out[f"rush_yards_over_expected_per_att~{b}"] = {
                "n": j.height,
                "rho": _round(
                    spearman(j["rush_yards_over_expected_per_att"].to_list(), j[b].to_list()), 3
                ),
            }
    return out


def combine_context(
    loaders: Any, table: pl.DataFrame, bridge: Mapping[str, str], season: int
) -> dict[str, Any]:
    combine = loaders.load_combine()
    out: dict[str, Any] = {
        "rows": combine.height,
        "years": [int(combine["season"].min()), int(combine["season"].max())],
        "pfr_id_present": round(1 - combine["pfr_id"].null_count() / combine.height, 4),
    }
    pos = combine.filter(pl.col("pos").is_in(POSITIONS))
    out["forty_recorded_share_by_position"] = {
        p: round(float(pos.filter(pl.col("pos") == p)["forty"].is_not_null().mean() or 0), 4)
        for p in POSITIONS
    }
    gsis_of = {pfr: g for pfr, g in bridge.items()}
    linked = pos.filter(pl.col("pfr_id").is_not_null()).with_columns(
        pl.col("pfr_id")
        .map_elements(lambda v: gsis_of.get(str(v)), return_dtype=pl.String)
        .alias("gsis")
    )
    dup = (
        linked.filter(pl.col("gsis").is_not_null()).group_by("gsis").len().filter(pl.col("len") > 1)
    )
    out["gsis_linked_rows"] = int(linked["gsis"].is_not_null().sum())
    out["gsis_with_two_combine_rows"] = dup.height
    appearing = table.filter(pl.col("pos").is_in(POSITIONS))
    have = appearing.join(
        linked.filter(pl.col("gsis").is_not_null()).select("gsis", "forty", "season", "pos"),
        on="gsis",
        how="left",
    )
    out[f"{season}_appearing_with_combine_row_by_position"] = {
        p: {
            "appearing": int(have.filter(pl.col("pos") == p).height),
            "combine_row": int(
                have.filter((pl.col("pos") == p) & pl.col("season").is_not_null()).height
            ),
            "forty": int(have.filter((pl.col("pos") == p) & pl.col("forty").is_not_null()).height),
        }
        for p in POSITIONS
    }
    out["position_mismatch_combine_vs_roster"] = (
        int(
            have.filter(
                pl.col("pos_right").is_not_null() & (pl.col("pos") != pl.col("pos_right"))
            ).height
        )
        if "pos_right" in have.columns
        else None
    )
    cohort = pos.filter(pl.col("forty").is_not_null() & (pl.col("season") >= 2000))
    out["forty_cohort_2000_on"] = {
        p: summarize(cohort.filter(pl.col("pos") == p)["forty"]) for p in POSITIONS
    }
    return out


#: The volume each position's examples are chosen by (descending): star, role, sparse.
_EXAMPLE_VOLUME = {"QB": "dropbacks", "RB": "car", "WR": "tgt", "TE": "tgt"}


def pick_examples(table: pl.DataFrame, named: Mapping[str, Sequence[str]]) -> dict[str, list[str]]:
    """Per position: the volume leader (star), the median of players with any volume (role),
    the fewest-opportunity player who still appeared twice (sparse), plus named players."""
    t = add_derived(table)
    out: dict[str, list[str]] = {}
    for pos in POSITIONS:
        col = _EXAMPLE_VOLUME[pos]
        rows = t.filter((pl.col("pos") == pos) & (pl.col(col) > 0)).sort(
            [col, "gsis"], descending=[True, False]
        )
        picks: list[str] = []
        if rows.height:
            picks.append(str(rows["name"][0]))
            picks.append(str(rows["name"][rows.height // 2]))
            sparse = rows.filter(pl.col("games") >= 2)
            if sparse.height:
                picks.append(str(sparse["name"][sparse.height - 1]))
        for name in named.get(pos, ()):
            if name not in picks:
                picks.append(name)
        out[pos] = picks
    return out


def examples(table: pl.DataFrame, picks: Mapping[str, Sequence[str]]) -> dict[str, Any]:
    t = add_derived(table)
    out: dict[str, Any] = {}
    for pos, names in picks.items():
        for name in names:
            row = t.filter((pl.col("pos") == pos) & (pl.col("name") == name))
            if row.is_empty():
                out[f"{pos}|{name}"] = {"found": False}
                continue
            r = row.row(0, named=True)
            entry: dict[str, Any] = {"games": r["games"], "teams": r["teams"]}
            for metric in CANDIDATES:
                if pos not in metric.position:
                    continue
                den = r[metric.den] if metric.kind != "total" else 1.0
                value = r[metric.num] if metric.kind == "total" else _ratio(r[metric.num], den)
                qualified = metric.kind == "total" or (
                    den >= metric.minimum if metric.kind == "rate" else r["games"] >= metric.minimum
                )
                entry[metric.id] = {
                    "value": _round(value),
                    "num": _round(r[metric.num], 2),
                    "den": _round(den, 2),
                    "qualified": bool(qualified and den > 0),
                }
            out[f"{pos}|{name}"] = entry
    return out


def probes(loaders: Any, season: int) -> dict[str, Any]:
    """Datasets considered and not used: is there current-season data at all?"""
    out: dict[str, Any] = {}
    for name, call in (
        ("load_participation", lambda: loaders.load_participation(seasons=[season])),
        ("load_ftn_charting", lambda: loaders.load_ftn_charting(seasons=[season])),
        (
            "load_pfr_advstats_rec_week",
            lambda: loaders.load_pfr_advstats(
                seasons=[season], stat_type="rec", summary_level="week"
            ),
        ),
    ):
        try:
            frame = call()
            weeks = sorted(frame["week"].unique().to_list()) if "week" in frame.columns else None
            out[name] = {"rows": frame.height, "weeks": weeks, "columns": len(frame.columns)}
        except Exception as exc:  # noqa: BLE001 - the refusal is the finding
            out[name] = {"error": f"{type(exc).__name__}: {str(exc)[:200]}"}
    return out


# ------------------------------------------------------------------------------ report


def render_markdown(result: Mapping[str, Any]) -> str:
    lines = [
        "# Skill Tree EDA — generated tables",
        "",
        f"Generated {result['generated_at_utc']} by `eda.py`. Current season "
        f"{result['current']['season']} through week {result['current']['through_week']}; "
        f"history {', '.join(str(s) for s in result['history_seasons'])}. The argument is in "
        "`README.md`; this file is only the numbers.",
        "",
        "## Current-season coverage (appearing / zero opportunity / insufficient / qualified)",
        "",
        "| metric | pos | appearing | zero | insufficient | qualified | minimum |",
        "|---|---|---:|---:|---:|---:|---|",
    ]
    for key, c in result["current"]["coverage"].items():
        mid, pos = key.split("|")
        if "qualified" in c:
            lines.append(
                f"| {mid} | {pos} | {c['appearing']} | {c['zero_opportunity']} | "
                f"{c['insufficient']} | {c['qualified']} | {c['minimum']:g} {c['minimum_on']} |"
            )
        else:
            lines.append(
                f"| {mid} | {pos} | {c['appearing']} | {c['zero']} | — | "
                f"{c['nonzero']} (non-zero) | total |"
            )
    lines += [
        "",
        "## Current-season distributions (qualified players)",
        "",
        "| metric | pos | n | p10 | p50 | p90 | min | max |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for key, d in result["current"]["distributions"].items():
        mid, pos = key.split("|")
        if d.get("n", 0) == 0:
            lines.append(f"| {mid} | {pos} | 0 | | | | | |")
            continue
        lines.append(
            f"| {mid} | {pos} | {d['n']} | {d['p10']} | {d['p50']} | {d['p90']} | "
            f"{d['min']} | {d['max']} |"
        )
    hist = result["history"]
    last = str(result["history_seasons"][-1])
    lines += [
        "",
        f"## Reliability and early-season stability ({last})",
        "",
        "Split-half = odd vs even weeks, Spearman-Brown corrected. Early = weeks 1–"
        f"{result['early_weeks']} against the rest of the season and against the full season.",
        "",
        "| metric | pos | split-half n | full-season reliability | early→rest ρ | early→full ρ |",
        "|---|---|---:|---:|---:|---:|",
    ]
    rel = hist[last]["reliability"]
    early = hist[last]["early_season"]
    for key, e in early.items():
        mid, pos = key.split("|")
        r = rel.get(key, {})
        lines.append(
            f"| {mid} | {pos} | {r.get('n', '—')} | {r.get('full_season_reliability', '—')} | "
            f"{e['rho_early_vs_rest']} | {e['rho_early_vs_full']} |"
        )
    lines += [
        "",
        f"## Recent window (last 3 games at week {result['recent_window_week']}) "
        f"vs season to date ({last})",
        "",
        "| metric | pos | n | to-date→future ρ | last-3→future ρ |",
        "|---|---|---:|---:|---:|",
    ]
    for key, e in hist[last]["recent_window"].items():
        mid, pos = key.split("|")
        lines.append(
            f"| {mid} | {pos} | {e['n']} | {e['rho_to_date_vs_future']} | "
            f"{e['rho_last3_vs_future']} |"
        )
    lines += ["", "## Redundancy (|ρ| ≥ 0.8, current season, qualified for both)", ""]
    for pos, r in result["current"]["redundancy"].items():
        pairs = ", ".join(f"{p['a']}~{p['b']} {p['rho']} (n {p['n']})" for p in r["high"])
        lines.append(f"* **{pos}**: {pairs or 'none'}")
    lines += ["", f"## Redundancy ({last} full season)", ""]
    for pos, r in hist[last]["redundancy"].items():
        pairs = ", ".join(f"{p['a']}~{p['b']} {p['rho']} (n {p['n']})" for p in r["high"])
        lines.append(f"* **{pos}**: {pairs or 'none'}")
    lines += ["", "## Next Gen Stats season-summary checks", ""]
    for season, checks in [("current", result["current"]["ngs_checks"])] + [
        (s, hist[s]["ngs_checks"]) for s in hist
    ]:
        for kind, c in checks.items():
            if "error" in c:
                lines.append(f"* {season} {kind}: error {c['error']}")
                continue
            lines.append(
                f"* {season} {kind}: {c['summary_rows']} summary rows; volume equal to official "
                f"{c['volume_equal_official']}, within 1 {c['volume_within_1']}; weekly rows cover "
                f"{c['weekly_rows_cover_share_of_official_volume']} of official volume; "
                f"max weekly week {c['max_weekly_week']}, "
                f"rows beyond cutoff {c['weeks_beyond_cutoff']}"
            )
    cur = result["current"]
    lines += ["", "## Combine (historical athletic context)", ""]
    comb = cur["combine"]
    lines.append(
        f"* {comb['rows']} rows, {comb['years'][0]}–{comb['years'][1]}; pfr_id present "
        f"{comb['pfr_id_present']}; forty recorded share {comb['forty_recorded_share_by_position']}"
    )
    for pos, c in comb[f"{cur['season']}_appearing_with_combine_row_by_position"].items():
        lines.append(
            f"* {pos}: {c['appearing']} appearing, {c['combine_row']} with a linked combine row, "
            f"{c['forty']} with a forty"
        )
    lines += ["", "## Datasets probed and not used", ""]
    for name, probe in cur["unused_dataset_probes"].items():
        lines.append(f"* `{name}`: {probe}")
    lines += [
        "",
        "## Player examples (current season)",
        "",
        "Value / denominator; `*` = below the qualification minimum (no rank would be published).",
        "",
    ]
    for key, entry in cur["examples"].items():
        if not entry.get("found", True):
            lines.append(f"* **{key}**: not found")
            continue
        cells = []
        for mid, m in entry.items():
            if not isinstance(m, dict):
                continue
            star = "" if m["qualified"] else "*"
            den = "" if m["den"] in (None, 1.0) else f"/{m['den']:g}"
            cells.append(f"{mid} {m['value']}{den}{star}")
        lines.append(f"* **{key}** ({entry['games']:g} g): " + "; ".join(cells))
    lines.append("")
    return "\n".join(lines)


# --------------------------------------------------------------------------------- main

#: Named examples beside the data-chosen star / role / sparse ones (earlier ADRs' cases).
EXAMPLES: Mapping[str, Sequence[str]] = {
    "QB": ("Tyler Shough", "Jalen Hurts"),
    "RB": ("David Montgomery", "Jahmyr Gibbs"),
    "WR": ("Rashid Shaheed",),
    "TE": ("Trey McBride",),
}


# ------------------------------------------------------------------ artifact cross-check

#: Next Gen Stats summary columns each published NGS metric copies (week 0, REG).
NGS_COLUMNS = {
    "avg_time_to_throw": ("passing", "avg_time_to_throw"),
    "rush_yards_over_expected_per_att": ("rushing", "rush_yards_over_expected_per_att"),
    "avg_separation": ("receiving", "avg_separation"),
    "avg_cushion": ("receiving", "avg_cushion"),
    "yac_over_expected": ("receiving", "avg_yac_above_expectation"),
}


def check_artifact(loaders: Any, path: Path) -> dict[str, Any]:
    """Recompute a built ``player_skill_tree.json`` from this script's own tables.

    The production module and this script share only the column vocabulary the ADR names
    (``att``, ``team_rz_tgt``...): every number here comes from ``player_table`` above, plain
    Polars over the loader frames. For each published reading with a value, its value,
    numerator, denominator, games and state must match; a Next Gen Stats reading must equal the
    week-0 summary's own column and a combine reading the combine file's forty. Ranks are not
    rechecked here: ``validate-artifacts`` re-derives every rank from the published values.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))
    from ffdraft.signals.skilltree_catalog import CATALOG, minimum_for

    payload = json.loads(path.read_text(encoding="utf-8"))
    records = payload["records"]
    season = int(records[0]["season"])
    through = int(records[0]["through_week"])
    frames = load_season(loaders, season)
    bridge = pfr_bridge([frames.roster], loaders.load_players())
    table = add_derived(player_table(frames, bridge, list(range(1, through + 1))))
    rows = {str(row["gsis"]): row for row in table.iter_rows(named=True)}

    summaries: dict[str, dict[str, dict[str, Any]]] = {}
    for kind, frame in frames.ngs.items():
        if "error" in frame.columns:
            continue
        week0 = frame.filter((pl.col("week") == 0) & (pl.col("season_type") == "REG"))
        summaries[kind] = {str(r["player_gsis_id"]): r for r in week0.iter_rows(named=True)}
    combine = loaders.load_combine().filter(pl.col("pfr_id").is_not_null())
    forty_of = {
        bridge[str(r["pfr_id"])]: r
        for r in combine.iter_rows(named=True)
        if str(r["pfr_id"]) in bridge and r["forty"] is not None
    }

    # A player with no snap-count row in any game has an unknown snap share, not a zero one:
    # ``player_table`` fills a missing row with 0 snaps, so the check names those players.
    snap_rows = frames.snaps.filter(
        (pl.col("game_type") == "REG") & (pl.col("week") <= through)
    ).with_columns(
        pl.col("pfr_player_id")
        .map_elements(lambda v: bridge.get(str(v)), return_dtype=pl.String)
        .alias("gsis")
    )
    with_snap_row = set(snap_rows["gsis"].drop_nulls().to_list())
    # Production refuses a malformed id before any join (``ffdraft.identity.normalize_id``). A
    # snap share it withholds for that reason is explained, not wrong, and is listed apart.
    from ffdraft.identity.ids import IdNamespace, normalize_id

    refused_pfr = {
        str(gsis)
        for pfr, gsis in snap_rows.select("pfr_player_id", "gsis").drop_nulls().iter_rows()
        if normalize_id(IdNamespace.PFR, pfr).value is None
    }
    explained: list[dict[str, Any]] = []

    compared: dict[str, int] = {}
    mismatches: list[dict[str, Any]] = []
    unchecked: dict[str, int] = {}

    def miss(record: Mapping[str, Any], field: str, published: Any, expected: Any) -> None:
        mismatches.append(
            {
                "player_id": record["player_id"],
                "metric_id": record["metric_id"],
                "field": field,
                "published": published,
                "expected": expected,
            }
        )

    def close(a: float | None, b: float | None, decimals: int) -> bool:
        if a is None or b is None:
            return a is b
        return abs(a - b) <= 0.5 * 10 ** (-decimals) + 1e-9

    for record in records:
        metric_id = record["metric_id"]
        gsis = str(record["player_id"]).removeprefix("gsis:")
        row = rows.get(gsis)
        state = record["state"]
        if state == "no_appearances":
            compared["no_appearances"] = compared.get("no_appearances", 0) + 1
            if row is not None and row["games"] > 0:
                miss(record, "state", state, f"{int(row['games'])} games")
            continue
        if row is None:
            miss(record, "games", record["games"], "no appearance in this script's table")
            continue
        if int(record["games"]) != int(row["games"]):
            miss(record, "games", record["games"], int(row["games"]))
        if metric_id in NGS_COLUMNS:
            kind, column = NGS_COLUMNS[metric_id]
            summary = summaries.get(kind, {}).get(gsis)
            if record["value"] is None:
                if summary is not None and state == "not_covered":
                    miss(record, "state", state, "a week-0 summary row exists")
            elif summary is None:
                miss(record, "value", record["value"], "no week-0 summary row")
            elif not close(record["value"], _num(summary[column]), CATALOG[metric_id].decimals):
                miss(record, "value", record["value"], _round(_num(summary[column]), 4))
            compared[metric_id] = compared.get(metric_id, 0) + 1
            continue
        if metric_id == "combine_forty":
            entry = forty_of.get(gsis)
            if record["value"] is not None:
                if entry is None or not close(record["value"], _num(entry["forty"]), 2):
                    miss(
                        record, "value", record["value"], None if entry is None else entry["forty"]
                    )
                elif record["source_season"] != entry["season"]:
                    miss(record, "source_season", record["source_season"], entry["season"])
            compared[metric_id] = compared.get(metric_id, 0) + 1
            continue
        metric = CATALOG.get(metric_id)
        if metric is None or metric.num is None or metric.num not in row:
            unchecked[metric_id] = unchecked.get(metric_id, 0) + 1
            continue
        num = float(row[metric.num])
        if metric.den is None:
            if not close(record["value"], num, metric.decimals):
                miss(record, "value", record["value"], num)
        else:
            den = float(row[metric.den])
            # Published samples are integers or rounded to three places (EPA and yards).
            if record["denominator"] is not None and not close(record["denominator"], den, 3):
                miss(record, "denominator", record["denominator"], den)
            if record["numerator"] is not None and not close(record["numerator"], num, 3):
                miss(record, "numerator", record["numerator"], num)
            expected = None if den == 0 else num / den
            if state in ("ranked", "below_minimum", "small_cohort") and not close(
                record["value"], expected, metric.decimals
            ):
                miss(record, "value", record["value"], _round(expected, 6))
            minimum = minimum_for(record["position"], metric)
            sample = float(row["games"]) if metric.minimum_unit == "games" else den
            want = (
                "not_covered"
                if metric.den == "team_snaps" and gsis not in with_snap_row
                else "no_opportunity"
                if den == 0
                else "below_minimum"
                if minimum is not None and sample < minimum
                else "ranked"
            )
            if (
                state == "not_covered"
                and record["reason"] == "no_snap_rows"
                and want != state
                and gsis in refused_pfr
            ):
                explained.append(
                    {
                        "player_id": record["player_id"],
                        "metric_id": metric_id,
                        "published": state,
                        "this_script": want,
                        "why": "his snap rows carry a PFR id ffdraft.identity.normalize_id "
                        "refuses (a period in the id), so production cannot link them",
                    }
                )
            elif state != want and not (want == "ranked" and state == "small_cohort"):
                miss(record, "state", state, want)
        compared[metric_id] = compared.get(metric_id, 0) + 1

    published = {str(r["player_id"]).removeprefix("gsis:") for r in records}
    missing = sorted(
        g
        for g, r in rows.items()
        if r["pos"] in POSITIONS and r["games"] > 0 and g not in published
    )
    return {
        "artifact": path.name,
        "build_id": records[0]["build_id"],
        "season": season,
        "through_week": through,
        "records": len(records),
        "players": len(published),
        "readings_compared": sum(compared.values()),
        "compared_by_metric": dict(sorted(compared.items())),
        "unchecked_by_metric": dict(sorted(unchecked.items())),
        "appearing_players_missing_from_artifact": missing,
        "mismatches": len(mismatches),
        "first_mismatches": mismatches[:50],
        "explained_differences": explained,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--current", type=int, default=2026)
    parser.add_argument("--cutoff-week", type=int, default=5)
    parser.add_argument("--history", type=int, nargs="*", default=[2023, 2024, 2025])
    parser.add_argument("--early-weeks", type=int, default=5)
    parser.add_argument("--recent-window-week", type=int, default=8)
    parser.add_argument("--out", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument(
        "--check-artifact",
        type=Path,
        default=None,
        help="recompute a built player_skill_tree.json and write artifact_check.json to --out",
    )
    args = parser.parse_args(argv)

    loaders = _loaders()
    if args.check_artifact is not None:
        check = check_artifact(loaders, args.check_artifact)
        check["generated_at_utc"] = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "artifact_check.json").write_text(
            json.dumps(check, indent=1, default=str) + "\n", encoding="utf-8"
        )
        print(json.dumps({k: check[k] for k in ("records", "readings_compared", "mismatches")}))
        return (
            0
            if check["mismatches"] == 0 and not check["appearing_players_missing_from_artifact"]
            else 1
        )
    players = loaders.load_players()
    result: dict[str, Any] = {
        "generated_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "nflreadpy_version": getattr(sys.modules.get("nflreadpy"), "__version__", None),
        "history_seasons": args.history,
        "early_weeks": args.early_weeks,
        "recent_window_week": args.recent_window_week,
        "constants": {
            "red_zone_yardline_100_max": RED_ZONE,
            "goal_line_yardline_100_max": GOAL_LINE,
            "explosive_run_yards": EXPLOSIVE_RUN_YARDS,
            "explosive_catch_yards": EXPLOSIVE_CATCH_YARDS,
        },
        "candidates": [m.__dict__ | {"position": list(m.position)} for m in CANDIDATES],
        "history": {},
    }
    rosters: list[pl.DataFrame] = []
    for season in [*args.history, args.current]:
        frames = load_season(loaders, season)
        rosters.append(frames.roster)
        bridge = pfr_bridge(rosters, players)
        if season == args.current:
            weeks = list(range(1, args.cutoff_week + 1))
            table = add_derived(player_table(frames, bridge, weeks))
            _, snap_diag = team_snaps(frames, weeks)
            result["current"] = {
                "season": season,
                "through_week": args.cutoff_week,
                "inventory": inventory(frames, args.cutoff_week),
                "identity": identity_coverage(frames, bridge, args.cutoff_week),
                "team_snaps": snap_diag,
                "appearing_by_position": {
                    p: int(table.filter(pl.col("pos") == p).height) for p in POSITIONS
                },
                "skill_stats_without_roster_position": int(
                    table.filter(
                        pl.col("pos").is_null() & pl.col("stats_position").is_in(POSITIONS)
                    ).height
                ),
                "roster_vs_stats_position_disagreements": int(
                    table.filter(
                        pl.col("pos").is_not_null()
                        & pl.col("stats_position").is_not_null()
                        & (pl.col("pos") != pl.col("stats_position"))
                    ).height
                ),
                "traded_players_appearing_for_two_teams": table.filter(
                    (pl.col("teams") > 1) & pl.col("pos").is_not_null()
                )["name"].to_list(),
                "coverage": coverage_current(table),
                "distributions": distributions(table),
                "redundancy": redundancy(table),
                "goal_line": goal_line_sparsity(table),
                "reconciliation": reconcile(frames, args.cutoff_week, bridge),
                "ngs_checks": ngs_summary_checks(frames, args.cutoff_week, table),
                "ngs_redundancy": ngs_redundancy(frames, table),
                "combine": combine_context(loaders, table, bridge, season),
                "examples": examples(table, pick_examples(table, EXAMPLES)),
                "unused_dataset_probes": probes(loaders, season),
            }
        else:
            last = 18 if season >= 2021 else 17
            full = add_derived(player_table(frames, bridge, list(range(1, last + 1))))
            result["history"][str(season)] = {
                "inventory": inventory(frames, None),
                "identity": identity_coverage(frames, bridge, None),
                "reliability": reliability(frames, bridge, last),
                "early_season": early_season(frames, bridge, args.early_weeks, last),
                "recent_window": recent_window(frames, bridge, args.recent_window_week, last),
                "threshold_sensitivity": threshold_sensitivity(
                    frames, bridge, args.early_weeks, last
                ),
                "redundancy": redundancy(full),
                "reconciliation": reconcile(frames, last, bridge),
                "ngs_checks": ngs_summary_checks(frames, last, full),
                "ngs_redundancy": ngs_redundancy(frames, full),
            }
        print(f"season {season} done", file=sys.stderr)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "report.json").write_text(
        json.dumps(result, indent=1, sort_keys=False, default=str) + "\n", encoding="utf-8"
    )
    (args.out / "report.md").write_text(render_markdown(result), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
