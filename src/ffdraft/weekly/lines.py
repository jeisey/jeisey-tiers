"""Pregame sportsbook lines: what the schedule posted, what was retained, and when to reuse it.

``weekly-startsit-v1`` reads a game's total and spread (ADR-096), and every one of its training
rows had both, so a game with no posted line is published as ``lines_pending`` — no
distribution — rather than projected as a zero-point game. That rule is right, and it made one
upstream hiccup cost a whole slate: on 2026-11-06 nflverse's schedule update at 11:45:17Z
(``nflverse/nfldata`` commit ``63cbbc1``) blanked the odds block of every unplayed week-9 game
and the next update ten minutes later restored them, but the day's refresh read the release
built from the blank file and published 1,437 ``lines_pending`` records (ADR-117). Nothing
noticed, because nothing remembered that the lines had been there the evening before.

**Retained observations.** The capture job now keeps, before every build, the lines nflverse
publishes for each regular-season game kicking off within ``CAPTURE_HORIZON`` — posted or not —
with its own retrieval time (``schedule_lines`` under ``gameday/`` in the private store, the same
append-only, content-hashed discipline as the forecast and injury captures, ADR-099). A blank is
recorded as a blank: the store is the evidence of when the source had what.

**The reuse rule, ``pregame_line_reuse_v1``.** For a target-week game whose schedule row has no
total or no spread, the build takes the newest retained observation of the *same* game that

* names the same ``game_id``, season, week, home and away team;
* carries both a total and a spread (never one from here and one from there);
* was observed at or before the build, strictly before the game's scheduled kickoff (which must
  have a published time — an unknown time cannot prove an observation was pregame); and
* is at most ``MAX_AGE`` old at the build.

Otherwise the game stays without lines and its players ``lines_pending``. A schedule row that
has both lines always wins. Nothing is imputed, averaged or carried across games or weeks, and
the reused value is the source's own pregame number — exactly what the build would have read
had it run when that observation was taken. Every target-week game publishes where its lines
came from (``schedule`` or ``retained``) and when they were observed.

This module decides nothing about players and reads no model. It is never applied to training
or evaluation rows: only the serving build's target week passes through it.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import polars as pl

from ffdraft.contracts.enums import normalize_team_code
from ffdraft.season.state import scheduled_kickoff_utc
from ffdraft.timeutil import isoformat_utc, parse_utc
from ffdraft.weekly.capture import LINES_SOURCE_ID

__all__ = [
    "CAPTURE_HORIZON",
    "LINES_SOURCE_ID",
    "LINE_REUSE_RULE_VERSION",
    "MAX_AGE",
    "LineObservation",
    "LineProvenance",
    "apply_retained_lines",
    "line_capture_rows",
    "lines_summary",
    "observations_from_rows",
    "retained_observations",
]

LINE_REUSE_RULE_VERSION = "pregame_line_reuse_v1"
#: How old a retained observation may be at the build. The daily refresh runs at least once a
#: day in season and the capture runs before every build, so a day-old observation is the
#: ordinary fallback and two days covers one missed run; anything older is too stale to stand
#: in for a market that moves with every injury report.
MAX_AGE = timedelta(hours=48)
#: Which games a capture records: every regular-season game kicking off within this window.
#: Lines are posted about two weeks ahead (context.py), so this covers the target week and the
#: next.
CAPTURE_HORIZON = timedelta(days=15)


@dataclass(frozen=True, slots=True)
class LineObservation:
    """One game's posted lines as one capture saw them."""

    game_id: str
    season: int
    week: int
    home_team: str
    away_team: str
    kickoff_utc: datetime | None
    spread_line: float | None
    total_line: float | None
    observed_at_utc: datetime

    @property
    def complete(self) -> bool:
        return self.spread_line is not None and self.total_line is not None


@dataclass(frozen=True, slots=True)
class LineProvenance:
    """Where one target-week game's lines came from: ``schedule``, ``retained`` or nowhere."""

    game_id: str
    source: str | None
    observed_at_utc: datetime | None

    def public(self) -> dict[str, Any]:
        return {
            "line_source": self.source,
            "lines_observed_at_utc": (
                isoformat_utc(self.observed_at_utc) if self.observed_at_utc is not None else None
            ),
        }


def _number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if number != number else number


def _has_time(value: Any) -> bool:
    return value is not None and str(value).strip() != ""


def line_capture_rows(
    schedule: pl.DataFrame,
    *,
    season: int,
    now: datetime,
    horizon: timedelta = CAPTURE_HORIZON,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Every REG game of ``season`` kicking off within ``horizon`` of ``now``, lines as posted.

    A game with no posted line is kept with nulls, so the store shows when the source had none.
    Returns the rows and the counts the capture manifest records.
    """
    rows: list[dict[str, Any]] = []
    for game in schedule.filter(
        (pl.col("season") == season) & (pl.col("game_type") == "REG"),
    ).iter_rows(named=True):
        kickoff = scheduled_kickoff_utc(game.get("gameday"), game.get("gametime"))
        if kickoff is None or not (now < kickoff <= now + horizon):
            continue
        rows.append(
            {
                "game_id": str(game["game_id"]),
                "season": int(game["season"]),
                "week": int(game["week"]),
                "home_team": normalize_team_code(game.get("home_team")),
                "away_team": normalize_team_code(game.get("away_team")),
                "kickoff_utc": isoformat_utc(kickoff),
                "kickoff_time_published": _has_time(game.get("gametime")),
                "spread_line": _number(game.get("spread_line")),
                "total_line": _number(game.get("total_line")),
            },
        )
    rows.sort(key=lambda row: (row["kickoff_utc"], row["game_id"]))
    lined = sum(
        1 for row in rows if row["spread_line"] is not None and row["total_line"] is not None
    )
    by_week: dict[str, dict[str, int]] = {}
    for row in rows:
        week = by_week.setdefault(str(row["week"]), {"games": 0, "lined": 0})
        week["games"] += 1
        week["lined"] += int(row["spread_line"] is not None and row["total_line"] is not None)
    return rows, {
        "rule_version": LINE_REUSE_RULE_VERSION,
        "horizon_days": horizon.total_seconds() / 86400,
        "games": len(rows),
        "lined": lined,
        "unlined": len(rows) - lined,
        "by_week": dict(sorted(by_week.items(), key=lambda item: int(item[0]))),
    }


def observations_from_rows(
    rows: Iterable[Mapping[str, Any]],
    *,
    observed_at_utc: datetime,
) -> list[LineObservation]:
    """A retained capture's rows as observations, each stamped with the capture's time."""
    out: list[LineObservation] = []
    for row in rows:
        if not row.get("kickoff_time_published", True):
            kickoff = None
        else:
            kickoff = parse_utc(str(row["kickoff_utc"])) if row.get("kickoff_utc") else None
        out.append(
            LineObservation(
                game_id=str(row["game_id"]),
                season=int(row["season"]),
                week=int(row["week"]),
                home_team=str(row.get("home_team") or ""),
                away_team=str(row.get("away_team") or ""),
                kickoff_utc=kickoff,
                spread_line=_number(row.get("spread_line")),
                total_line=_number(row.get("total_line")),
                observed_at_utc=observed_at_utc,
            ),
        )
    return out


def retained_observations(
    store_root: Any,
    *,
    season: int,
    as_of: datetime,
    max_age: timedelta = MAX_AGE,
) -> tuple[list[LineObservation], list[str]]:
    """Every observation in captures taken within ``max_age`` before ``as_of`` (never after).

    Returns the observations and the snapshot keys read. A capture that fails its hash is an
    error, not a skip: a corrupt store must not silently decide which lines a build uses.
    """
    from pathlib import Path

    from ffdraft.retention import SnapshotStore, parse_snapshot_key
    from ffdraft.weekly.capture import GAMEDAY_PREFIX, read_gameday_capture

    root = Path(store_root)
    gameday = SnapshotStore(root=root, prefix=GAMEDAY_PREFIX)
    keys = [
        key
        for key in gameday.keys(LINES_SOURCE_ID, season)
        if as_of - max_age <= parse_snapshot_key(key) <= as_of
    ]
    observations: list[LineObservation] = []
    for key in keys:
        capture = read_gameday_capture(
            SnapshotStore(root=root, prefix=""),
            source_id=LINES_SOURCE_ID,
            season=season,
            key=key,
        )
        if capture is None:
            continue
        observations.extend(
            observations_from_rows(capture.rows, observed_at_utc=capture.observed_at_utc),
        )
    return observations, keys


def apply_retained_lines(
    schedule: pl.DataFrame,
    observations: Sequence[LineObservation],
    *,
    season: int,
    week: int,
    as_of: datetime,
    schedule_observed_at: datetime,
    max_age: timedelta = MAX_AGE,
) -> tuple[pl.DataFrame, dict[str, LineProvenance]]:
    """The schedule with ``pregame_line_reuse_v1`` applied to ``season``'s week ``week``.

    Returns the schedule (only that week's unlined regular-season rows may change, and only
    their ``spread_line`` and ``total_line``) and every one of that week's games' provenance.
    """
    provenance: dict[str, LineProvenance] = {}
    by_game: dict[str, list[LineObservation]] = {}
    for observation in observations:
        by_game.setdefault(observation.game_id, []).append(observation)

    patches: dict[str, tuple[float, float]] = {}
    needed = {"game_id", "season", "week", "game_type", "spread_line", "total_line"}
    if schedule.is_empty() or not needed <= set(schedule.columns):
        return schedule, provenance
    target = schedule.filter(
        (pl.col("season") == season) & (pl.col("week") == week) & (pl.col("game_type") == "REG"),
    )
    for game in target.iter_rows(named=True):
        game_id = str(game["game_id"])
        spread, total = _number(game.get("spread_line")), _number(game.get("total_line"))
        if spread is not None and total is not None:
            provenance[game_id] = LineProvenance(game_id, "schedule", schedule_observed_at)
            continue
        kickoff = (
            scheduled_kickoff_utc(game.get("gameday"), game.get("gametime"))
            if _has_time(game.get("gametime"))
            else None
        )
        home = normalize_team_code(game.get("home_team"))
        away = normalize_team_code(game.get("away_team"))
        eligible = [
            observation
            for observation in by_game.get(game_id, ())
            if observation.complete
            and observation.season == season
            and observation.week == week
            and observation.home_team == home
            and observation.away_team == away
            and kickoff is not None
            and observation.observed_at_utc < kickoff
            and observation.observed_at_utc <= as_of
            and as_of - observation.observed_at_utc <= max_age
        ]
        if not eligible:
            provenance[game_id] = LineProvenance(game_id, None, None)
            continue
        chosen = max(eligible, key=lambda observation: observation.observed_at_utc)
        assert chosen.spread_line is not None and chosen.total_line is not None
        patches[game_id] = (chosen.spread_line, chosen.total_line)
        provenance[game_id] = LineProvenance(game_id, "retained", chosen.observed_at_utc)

    if not patches:
        return schedule, provenance
    spread_patch = {key: value[0] for key, value in patches.items()}
    total_patch = {key: value[1] for key, value in patches.items()}
    ids = pl.col("game_id").cast(pl.String)
    patched = schedule.with_columns(
        pl.when(ids.is_in(list(patches)))
        .then(ids.replace_strict(spread_patch, default=None, return_dtype=pl.Float64))
        .otherwise(pl.col("spread_line").cast(pl.Float64))
        .alias("spread_line"),
        pl.when(ids.is_in(list(patches)))
        .then(ids.replace_strict(total_patch, default=None, return_dtype=pl.Float64))
        .otherwise(pl.col("total_line").cast(pl.Float64))
        .alias("total_line"),
    )
    return patched, provenance


def lines_summary(
    provenance: Mapping[str, LineProvenance],
    *,
    schedule_observed_at: datetime,
    max_age: timedelta = MAX_AGE,
) -> dict[str, Any]:
    """``ros_build_metadata.weekly.lines``: what the target week's games were projected from."""
    retained = sorted(
        (item for item in provenance.values() if item.source == "retained"),
        key=lambda item: item.game_id,
    )
    unlined = sorted(game_id for game_id, item in provenance.items() if item.source is None)
    return {
        "rule_version": LINE_REUSE_RULE_VERSION,
        "max_age_hours": int(max_age.total_seconds() // 3600),
        "schedule_retrieved_at_utc": isoformat_utc(schedule_observed_at),
        "target_games": len(provenance),
        "from_schedule": sum(1 for item in provenance.values() if item.source == "schedule"),
        "from_retained": len(retained),
        "unlined": len(unlined),
        "unlined_game_ids": unlined,
        "retained": [
            {
                "game_id": item.game_id,
                "observed_at_utc": isoformat_utc(item.observed_at_utc)
                if item.observed_at_utc is not None
                else None,
            }
            for item in retained
        ],
    }
