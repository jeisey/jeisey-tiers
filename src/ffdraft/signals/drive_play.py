"""nflverse play-by-play, reduced to the drive-level opportunities drive breadth reads (ADR-103).

**What is kept.** Thirteen columns of ``load_pbp`` (``DRIVE_PLAY_COLUMNS``), for regular-season
offensive scrimmage plays only. Raw play-by-play never reaches the browser or an ordinary
source commit: it is read through the cached nflverse loader, reduced here, and only per-player
aggregates are published.

**One definition of an eligible team slot, applied to every position** (``drive_breadth_v1``):

* a regular-season (``season_type == "REG"``) ``pass`` or ``run`` play with a possession team
  and a drive number (``fixed_drive``);
* excluded: ``qb_kneel`` and ``qb_spike`` (clock plays — their own ``play_type`` already),
  two-point attempts, aborted snaps (``aborted_play``: no designed opportunity), special-teams
  plays (a fake punt is not an offensive slot), and deleted plays;
* ``no_play`` rows — a penalty that wiped out the snap, a timeout — are not plays. A play that
  stands with a penalty on it (declined, offsetting, after the whistle) is a play;
* a **sack** is a pass play with no receiver: a QB slot, never a target;
* a **scramble** is a run with the quarterback as the rusher (``rush_attempt == 1``);
* a **lateral** credits the original rusher or targeted receiver, as nflverse records it; the
  player who received the lateral gets no opportunity;
* a pass with **no identified receiver** (thrown away, batted) is not a target slot for anyone.

**The four positional variants** (player opportunity → the team slots it is one of):

* QB: his rush attempts, scrambles included → every eligible scrimmage play;
* RB: his carries plus targets → every carry and target that went to a running back;
* WR: his targets → every identified target;
* TE: his targets snapped outside the red zone (``yardline_100 > 20``) → every identified
  target snapped outside the red zone.

Positions come from nflverse's season roster (verified position evidence); a player it does
not place is never counted as a running back's slot, and is counted in the diagnostics.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import polars as pl

from ffdraft.signals.breadth import GameBreadth, game_breadth

__all__ = [
    "BREADTH_POSITIONS",
    "DRIVE_PLAY_COLUMNS",
    "RED_ZONE_YARDLINE",
    "Appearance",
    "drive_plays",
    "game_breadths",
    "position_map",
]

#: The columns read from ``load_pbp``. Missing any of them is a source-contract change.
DRIVE_PLAY_COLUMNS: tuple[str, ...] = (
    "season",
    "week",
    "season_type",
    "game_id",
    "posteam",
    "fixed_drive",
    "play_type",
    "rush_attempt",
    "pass_attempt",
    "sack",
    "qb_kneel",
    "qb_spike",
    "two_point_attempt",
    "aborted_play",
    "special_teams_play",
    "play_deleted",
    "rusher_player_id",
    "receiver_player_id",
    "yardline_100",
)

#: Yards from the opponent's goal line at or inside which a snap is in the red zone.
RED_ZONE_YARDLINE = 20

BREADTH_POSITIONS = ("QB", "RB", "WR", "TE")


def _flag(name: str) -> pl.Expr:
    return pl.col(name).cast(pl.Float64).fill_null(0.0) == 1.0


def drive_plays(pbp: pl.DataFrame) -> pl.DataFrame:
    """The eligible plays, one row each: game, team, drive, kind, player and field position.

    ``kind`` is ``rush`` (a carry or scramble, with its rusher), ``target`` (a non-sack pass
    attempt with an identified receiver) or ``other`` (any other eligible play — a sack, a
    pass with no receiver — which is a QB slot and nothing else).
    """
    missing = [name for name in DRIVE_PLAY_COLUMNS if name not in pbp.columns]
    if missing:
        raise ValueError(f"load_pbp is missing drive-breadth columns: {', '.join(missing)}")
    plays = pbp.select(DRIVE_PLAY_COLUMNS).filter(
        (pl.col("season_type") == "REG")
        & pl.col("play_type").is_in(["pass", "run"])
        & pl.col("posteam").is_not_null()
        & pl.col("fixed_drive").is_not_null()
        & ~_flag("qb_kneel")
        & ~_flag("qb_spike")
        & ~_flag("two_point_attempt")
        & ~_flag("aborted_play")
        & ~_flag("special_teams_play")
        & ~_flag("play_deleted"),
    )
    rush = _flag("rush_attempt") & pl.col("rusher_player_id").is_not_null()
    target = _flag("pass_attempt") & ~_flag("sack") & pl.col("receiver_player_id").is_not_null()
    return plays.select(
        pl.col("season").cast(pl.Int32),
        pl.col("week").cast(pl.Int32),
        pl.col("game_id").cast(pl.String),
        pl.col("posteam").cast(pl.String).alias("team"),
        pl.col("fixed_drive").cast(pl.Int32).alias("drive"),
        pl.when(rush)
        .then(pl.lit("rush"))
        .when(target)
        .then(pl.lit("target"))
        .otherwise(pl.lit("other"))
        .alias("kind"),
        pl.when(rush)
        .then(pl.col("rusher_player_id"))
        .when(target)
        .then(pl.col("receiver_player_id"))
        .otherwise(None)
        .cast(pl.String)
        .alias("player"),
        pl.col("yardline_100").cast(pl.Float64).alias("yardline_100"),
    )


def position_map(rosters: Iterable[pl.DataFrame]) -> dict[tuple[int, str], str]:
    """``(season, gsis_id) -> position`` from nflverse season rosters. QB/RB/WR/TE only.

    A player listed at two positions in one season (rare) keeps the first in sorted order,
    which is the roster's own deterministic choice elsewhere in this repository.
    """
    positions: dict[tuple[int, str], str] = {}
    for roster in rosters:
        if roster.is_empty():
            continue
        ordered = (
            roster.select("season", "gsis_id", "position")
            .drop_nulls()
            .sort(
                "season",
                "gsis_id",
                "position",
            )
        )
        for season, gsis, position in ordered.iter_rows():
            if str(position) in BREADTH_POSITIONS:
                positions.setdefault((int(season), str(gsis)), str(position))
    return positions


@dataclass(frozen=True, slots=True)
class Appearance:
    """A completed appearance: he played for ``team`` in ``week`` (stats row or offensive snap)."""

    season: int
    week: int
    player_id: str  # bare GSIS id
    team: str
    position: str


def _slot_flags(frame: pl.DataFrame, positions: Mapping[tuple[int, str], str]) -> pl.DataFrame:
    """Annotate each play with which variants it is a team slot for."""
    keys = [
        (int(season), str(player))
        for season, player in frame.select("season", "player").iter_rows()
    ]
    player_position = [positions.get(key) if key[1] != "None" else None for key in keys]
    return frame.with_columns(
        pl.Series("player_position", player_position, dtype=pl.String),
    ).with_columns(
        pl.lit(True).alias("slot_QB"),
        (pl.col("kind").is_in(["rush", "target"]) & (pl.col("player_position") == "RB")).alias(
            "slot_RB"
        ),
        (pl.col("kind") == "target").alias("slot_WR"),
        ((pl.col("kind") == "target") & (pl.col("yardline_100") > RED_ZONE_YARDLINE)).alias(
            "slot_TE",
        ),
    )


def _opportunity(position: str) -> pl.Expr:
    """Which of a player's own plays are his opportunities under his position's variant."""
    if position == "QB":
        return pl.col("kind") == "rush"
    if position == "RB":
        return pl.col("slot_RB")
    if position == "WR":
        return pl.col("slot_WR")
    return pl.col("slot_TE")


def game_breadths(
    plays: pl.DataFrame,
    appearances: Sequence[Appearance],
    positions: Mapping[tuple[int, str], str],
) -> tuple[dict[str, list[GameBreadth]], dict[str, Any]]:
    """Per-appearance arithmetic for every appearance, keyed by ``gsis:`` player id.

    Every drive of his team's game that holds an eligible slot is in the denominator,
    including drives he never touched the ball on: this is team-opportunity breadth, not
    route participation, and not proof he was on the field.

    An appearance whose team has no play-by-play for that week (a game not yet published)
    is skipped and counted, never filled.
    """
    flagged = _slot_flags(plays, positions)
    slots: dict[tuple[str, int, int, str], dict[int, int]] = {}
    for position in BREADTH_POSITIONS:
        grouped = (
            flagged.filter(pl.col(f"slot_{position}"))
            .group_by("season", "week", "team", "drive")
            .len()
        )
        for season, week, team, drive, count in grouped.iter_rows():
            slots.setdefault((position, int(season), int(week), str(team)), {})[int(drive)] = int(
                count,
            )

    owned: dict[tuple[str, int, int, str, str], dict[int, int]] = {}
    for position in BREADTH_POSITIONS:
        grouped = (
            flagged.filter(pl.col("player").is_not_null() & _opportunity(position))
            .group_by("season", "week", "team", "player", "drive")
            .len()
        )
        for season, week, team, player, drive, count in grouped.iter_rows():
            owned.setdefault((position, int(season), int(week), str(team), str(player)), {})[
                int(drive)
            ] = int(count)

    teams_with_plays = {
        (int(s), int(w), str(t))
        for s, w, t in plays.select("season", "week", "team").unique().iter_rows()
    }
    result: dict[str, list[GameBreadth]] = {}
    skipped_no_pbp = 0
    unclassified = int(
        flagged.filter(
            pl.col("kind").is_in(["rush", "target"]) & pl.col("player_position").is_null()
        ).height
    )
    for appearance in appearances:
        if appearance.position not in BREADTH_POSITIONS:
            continue
        if (appearance.season, appearance.week, appearance.team) not in teams_with_plays:
            skipped_no_pbp += 1
            continue
        team_slots = slots.get(
            (appearance.position, appearance.season, appearance.week, appearance.team),
            {},
        )
        mine = owned.get(
            (
                appearance.position,
                appearance.season,
                appearance.week,
                appearance.team,
                appearance.player_id,
            ),
            {},
        )
        result.setdefault(f"gsis:{appearance.player_id}", []).append(
            game_breadth(
                season=appearance.season,
                week=appearance.week,
                slots_by_drive=team_slots,
                opportunities_by_drive=mine,
            ),
        )
    diagnostics = {
        "eligible_plays": plays.height,
        "appearances": len(appearances),
        "appearances_without_play_by_play": skipped_no_pbp,
        "rush_or_target_without_verified_position": unclassified,
    }
    return result, diagnostics
