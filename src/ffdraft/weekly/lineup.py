"""Who is missing this week, on his offence and on the defence he faces (``lagged_starters_v1``).

Two questions a manager asks about a game that the weekly v1 model never reads:

* **His offence's health** — are the linemen who usually block for him, the quarterback who
  usually throws to him, or the teammates who usually take the targets and carries he competes
  for, ruled out this week?
* **The opposing defence's health** — are its usual cornerbacks, safeties or defensive linemen
  ruled out?

Both are answered the same way, from information that exists before kickoff:

1. **Who "usually" plays** is decided from the past only: a team's **lagged starters** are the
   players with the largest mean snap share over that team's last
   :data:`STARTER_WINDOW_GAMES` games **through the cutoff** (a game he missed counts as zero),
   per position group, above :data:`STARTER_MIN_SHARE`. Snap counts carry every position since
   2012 and bridge to ``gsis_id`` for more than 99.5% of linemen and defensive backs in every
   season (probed 2026-10-01), so the definition has historical point-in-time parity; depth
   charts do not (their 2025 schema change, ADR-015).
2. **Who is missing** is the league's injury report for the target week, as nflverse publishes
   it: ``Out`` or ``Doubtful`` is a *confirmed* absence (Out starters played 0% of the time,
   Doubtful 2-5%, 2017-2025), ``Questionable`` an *uncertain* one (65-70% played). A player
   placed on injured reserve after the cutoff is not on the report and reads as available —
   about four in ten absent lagged starters carried no designation (probed 2026-10-01), which
   is the price of using only what is known before the game.
3. **Whether the report is final.** A team with no designation at all on the target week's
   report has no published game statuses yet (97-99% of historical team-weeks carry at least
   one). Its health readings are ``null`` — unknown, not healthy — at training and at serving
   alike, by the same rule.

Nothing here reads a model output, and no intrinsic or rest-of-season model reads anything
here (tests/leakage/test_weekly_firewall.py).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import polars as pl

from ffdraft.contracts.enums import normalize_team_code

__all__ = [
    "CONFIRMED_DESIGNATIONS",
    "DEFENSE_HEALTH_COLUMNS",
    "LINEUP_RULE_VERSION",
    "OFFENSE_HEALTH_COLUMNS",
    "STARTER_GROUPS",
    "STARTER_MIN_SHARE",
    "STARTER_WINDOW_GAMES",
    "UNCERTAIN_DESIGNATIONS",
    "StarterGroup",
    "absence_lists",
    "designations_for_week",
    "health_features",
    "lagged_starters",
    "recent_usage_shares",
    "team_health",
    "vacated_shares",
]

LINEUP_RULE_VERSION = "lagged_starters_v1"

#: The window that defines "usually": a month of football is too slow to notice a new
#: starter, one game too noisy to tell a starter from an injury fill-in.
STARTER_WINDOW_GAMES = 3

#: A rotational player is not a starter, whatever his rank: half the snaps would be the
#: natural line, but defensive linemen rotate, so the line is lower.
STARTER_MIN_SHARE = 0.30

CONFIRMED_DESIGNATIONS: frozenset[str] = frozenset({"Out", "Doubtful"})
UNCERTAIN_DESIGNATIONS: frozenset[str] = frozenset({"Questionable"})


@dataclass(frozen=True)
class StarterGroup:
    """One position group's starters: which snap-count labels, which snap share, how many."""

    key: str
    side: str
    positions: frozenset[str]
    count: int
    label: str


#: Snap-count position labels (Pro Football Reference's). ``DB`` is filed with corners, the
#: generic ``LB`` is not counted as a pass rusher (PFR files 3-4 edge rushers as ``LB``, so a
#: line-only group is the one that can be defined cleanly; disclosed in DATA_SOURCES §20).
STARTER_GROUPS: tuple[StarterGroup, ...] = (
    StarterGroup(
        "OL", "offense", frozenset({"T", "G", "C", "OL", "OT", "OG"}), 5, "offensive line"
    ),
    StarterGroup("QB", "offense", frozenset({"QB"}), 1, "quarterback"),
    StarterGroup("CB", "defense", frozenset({"CB", "DB"}), 3, "cornerbacks"),
    StarterGroup("S", "defense", frozenset({"S", "FS", "SS", "SAF"}), 2, "safeties"),
    StarterGroup("DL", "defense", frozenset({"DE", "DT", "NT", "DL"}), 4, "defensive line"),
)

#: A team's own-offence readings (joined to his row by his team).
OFFENSE_HEALTH_COLUMNS: tuple[str, ...] = (
    "own_ol_out",
    "own_ol_questionable",
    "own_qb_out",
)

#: The opposing defence's readings (joined to his row by his opponent).
DEFENSE_HEALTH_COLUMNS: tuple[str, ...] = (
    "opp_cb_out",
    "opp_s_out",
    "opp_dl_out",
    "opp_db_questionable",
    "opp_dl_questionable",
)

#: The per-player share of his teammates' recent targets and carries that is ruled out.
VACATED_COLUMNS: tuple[str, ...] = (
    "own_vacated_targets",
    "own_vacated_carries",
    "own_questionable_targets",
)


def _team(column: str) -> pl.Expr:
    return pl.col(column).map_elements(normalize_team_code, return_dtype=pl.String)


def _window(frame: pl.DataFrame, *, games: int) -> pl.DataFrame:
    """Each team's last ``games`` weeks with a row, as ``(team, week)``."""
    weeks = frame.select("team", "week").unique()
    return (
        weeks.sort(["team", "week"], descending=[False, True])
        .group_by("team", maintain_order=True)
        .head(games)
    )


def lagged_starters(
    snaps: pl.DataFrame,
    *,
    season: int,
    through_week: int,
    window_games: int = STARTER_WINDOW_GAMES,
    min_share: float = STARTER_MIN_SHARE,
) -> pl.DataFrame:
    """Every team's lagged starters per group, from snap counts through ``through_week``.

    Columns: ``team, group, gsis_id, player_name, position, share, starter_rank``. Weeks after
    the cutoff are filtered out **first**, so nothing later can reach a starter.
    """
    empty = pl.DataFrame(
        schema={
            "team": pl.String,
            "group": pl.String,
            "gsis_id": pl.String,
            "player_name": pl.String,
            "position": pl.String,
            "share": pl.Float64,
            "starter_rank": pl.Int32,
        },
    )
    if snaps.is_empty():
        return empty
    rows = snaps.filter(
        (pl.col("season") == season)
        & (pl.col("week") <= through_week)
        & (pl.col("game_type") == "REG")
        & pl.col("gsis_id").is_not_null()
        & pl.col("team").is_not_null(),
    ).with_columns(_team("team").alias("team"))
    if rows.is_empty():
        return empty
    window = _window(rows, games=window_games)
    played = window.group_by("team").agg(pl.len().cast(pl.Float64).alias("team_games"))
    in_window = rows.join(window, on=["team", "week"], how="inner")
    parts: list[pl.DataFrame] = []
    for group in STARTER_GROUPS:
        column = "offense_pct" if group.side == "offense" else "defense_pct"
        if column not in in_window.columns:
            continue
        block = in_window.filter(pl.col("position").is_in(sorted(group.positions)))
        if block.is_empty():
            continue
        ranked = (
            block.sort("week")
            .group_by("team", "gsis_id")
            .agg(
                pl.col(column).fill_null(0.0).cast(pl.Float64).sum().alias("total"),
                pl.col("player_name").last().alias("player_name"),
                pl.col("position").last().alias("position"),
            )
            .join(played, on="team", how="left")
            .with_columns((pl.col("total") / pl.col("team_games")).round(6).alias("share"))
            .filter(pl.col("share") >= min_share)
            .sort(["team", "share", "gsis_id"], descending=[False, True, False])
            .with_columns(
                pl.int_range(1, pl.len() + 1).over("team").cast(pl.Int32).alias("starter_rank"),
            )
            .filter(pl.col("starter_rank") <= group.count)
        )
        parts.append(
            ranked.select(
                "team",
                pl.lit(group.key).alias("group"),
                "gsis_id",
                "player_name",
                "position",
                "share",
                "starter_rank",
            ),
        )
    if not parts:
        return empty
    return pl.concat(parts, how="vertical_relaxed").sort("team", "group", "starter_rank")


def designations_for_week(injuries: pl.DataFrame, *, season: int, week: int) -> pl.DataFrame:
    """The target week's report rows: ``gsis_id, team, position, full_name, status, ...``."""
    columns = {
        "gsis_id": pl.String,
        "team": pl.String,
        "position": pl.String,
        "full_name": pl.String,
        "report_status": pl.String,
        "practice_status": pl.String,
        "primary_injury": pl.String,
    }
    if injuries.is_empty():
        return pl.DataFrame(schema=columns)
    rows = injuries.filter((pl.col("season") == season) & (pl.col("week") == week))
    if "full_name" not in rows.columns:
        rows = rows.with_columns(pl.lit(None, dtype=pl.String).alias("full_name"))
    return rows.select(
        [pl.col(name).cast(dtype) for name, dtype in columns.items()],
    ).with_columns(_team("team").alias("team"))


def _confirmed(column: str = "report_status") -> pl.Expr:
    return pl.col(column).is_in(sorted(CONFIRMED_DESIGNATIONS)).fill_null(False)


def _uncertain(column: str = "report_status") -> pl.Expr:
    return pl.col(column).is_in(sorted(UNCERTAIN_DESIGNATIONS)).fill_null(False)


def _final_teams(report: pl.DataFrame) -> set[str]:
    """Teams whose report already carries a game status for someone."""
    designated = report.filter(_confirmed() | _uncertain())
    return {str(team) for team in designated.get_column("team").drop_nulls().unique()}


def team_health(
    starters: pl.DataFrame,
    report: pl.DataFrame,
    teams: list[str],
) -> pl.DataFrame:
    """Per team: its own-offence and its defence readings, ``null`` when not final.

    Columns: ``team, report_final, own_ol_out, own_ol_questionable, own_qb_out, def_cb_out,
    def_s_out, def_dl_out, def_db_questionable, def_dl_questionable``. The ``def_`` readings
    become ``opp_`` when joined to the other side's rows.
    """
    status = report.select("gsis_id", "report_status")
    marked = starters.join(status, on="gsis_id", how="left").with_columns(
        _confirmed().alias("out"),
        _uncertain().alias("questionable"),
    )
    final = _final_teams(report)
    rows: list[dict[str, Any]] = []
    for team in sorted(set(teams)):
        own = marked.filter(pl.col("team") == team)

        def count(group: str, flag: str, frame: pl.DataFrame = own) -> int:
            return int(frame.filter((pl.col("group") == group) & pl.col(flag)).height)

        known = team in final
        values: dict[str, Any] = {
            "own_ol_out": count("OL", "out"),
            "own_ol_questionable": count("OL", "questionable"),
            "own_qb_out": count("QB", "out"),
            "def_cb_out": count("CB", "out"),
            "def_s_out": count("S", "out"),
            "def_dl_out": count("DL", "out"),
            "def_db_questionable": count("CB", "questionable") + count("S", "questionable"),
            "def_dl_questionable": count("DL", "questionable"),
        }
        rows.append(
            {
                "team": team,
                "report_final": known,
                **{key: (float(value) if known else None) for key, value in values.items()},
            },
        )
    schema: dict[str, pl.DataType] = {"team": pl.String(), "report_final": pl.Boolean()}
    schema.update(
        {
            name: pl.Float64()
            for name in (
                "own_ol_out",
                "own_ol_questionable",
                "own_qb_out",
                "def_cb_out",
                "def_s_out",
                "def_dl_out",
                "def_db_questionable",
                "def_dl_questionable",
            )
        },
    )
    return pl.DataFrame(rows, schema=schema, orient="row")


def recent_usage_shares(
    weekly: pl.DataFrame,
    *,
    season: int,
    through_week: int,
    window_games: int = STARTER_WINDOW_GAMES,
) -> pl.DataFrame:
    """Each player's share of his team's targets and carries over its last games.

    Columns: ``team, gsis_id, target_share_recent, carry_share_recent``. Same window as the
    starters, through the cutoff only.
    """
    schema = {
        "team": pl.String,
        "gsis_id": pl.String,
        "target_share_recent": pl.Float64,
        "carry_share_recent": pl.Float64,
    }
    if weekly.is_empty():
        return pl.DataFrame(schema=schema)
    rows = weekly.filter(
        (pl.col("season") == season)
        & (pl.col("week") <= through_week)
        & (pl.col("season_type") == "REG")
        & pl.col("gsis_id").is_not_null()
        & pl.col("team").is_not_null(),
    ).with_columns(_team("team").alias("team"))
    if rows.is_empty():
        return pl.DataFrame(schema=schema)
    window = _window(rows, games=window_games)
    in_window = rows.join(window, on=["team", "week"], how="inner")
    totals = in_window.group_by("team").agg(
        pl.col("targets").fill_null(0.0).sum().alias("team_targets"),
        pl.col("carries").fill_null(0.0).sum().alias("team_carries"),
    )
    shares = (
        in_window.group_by("team", "gsis_id")
        .agg(
            pl.col("targets").fill_null(0.0).sum().alias("targets"),
            pl.col("carries").fill_null(0.0).sum().alias("carries"),
        )
        .join(totals, on="team", how="left")
        .with_columns(
            pl.when(pl.col("team_targets") > 0)
            .then(pl.col("targets") / pl.col("team_targets"))
            .otherwise(0.0)
            .round(6)
            .alias("target_share_recent"),
            pl.when(pl.col("team_carries") > 0)
            .then(pl.col("carries") / pl.col("team_carries"))
            .otherwise(0.0)
            .round(6)
            .alias("carry_share_recent"),
        )
    )
    return shares.select(list(schema)).sort("team", "gsis_id")


def vacated_shares(shares: pl.DataFrame, report: pl.DataFrame) -> pl.DataFrame:
    """Per team: the recent target and carry share of its ruled-out and questionable players.

    Columns: ``team, out_targets, out_carries, questionable_targets``. A player's own share is
    removed from his row later (:func:`health_features`), so a designated player who still
    appears is not credited with his own absence.
    """
    status = report.select("gsis_id", "report_status")
    marked = shares.join(status, on="gsis_id", how="left")
    return marked.group_by("team").agg(
        pl.when(_confirmed())
        .then(pl.col("target_share_recent"))
        .otherwise(0.0)
        .sum()
        .alias(
            "out_targets",
        ),
        pl.when(_confirmed())
        .then(pl.col("carry_share_recent"))
        .otherwise(0.0)
        .sum()
        .alias(
            "out_carries",
        ),
        pl.when(_uncertain())
        .then(pl.col("target_share_recent"))
        .otherwise(0.0)
        .sum()
        .alias("questionable_targets"),
    )


def health_features(
    rows: pl.DataFrame,
    *,
    snaps: pl.DataFrame,
    weekly: pl.DataFrame,
    injuries: pl.DataFrame,
    season: int,
    through_week: int,
    target_week: int,
    team_column: str = "team",
    opponent_column: str = "opponent",
) -> pl.DataFrame:
    """Attach the lineup and opposing-defence readings to ``rows`` for one cutoff.

    ``rows`` carries ``gsis_id`` and the two team columns. Every reading is from snap counts
    and weekly rows through ``through_week`` and the report for ``target_week``.
    """
    starters = lagged_starters(snaps, season=season, through_week=through_week)
    report = designations_for_week(injuries, season=season, week=target_week)
    teams = sorted(
        {
            str(team)
            for column in (team_column, opponent_column)
            for team in rows.get_column(column).drop_nulls().unique()
        },
    )
    health = team_health(starters, report, teams)
    shares = recent_usage_shares(weekly, season=season, through_week=through_week)
    vacated = vacated_shares(shares, report)
    own = health.select(
        pl.col("team").alias(team_column),
        pl.col("report_final").alias("own_report_final"),
        *OFFENSE_HEALTH_COLUMNS,
    )
    opposing = health.select(
        pl.col("team").alias(opponent_column),
        pl.col("report_final").alias("opp_report_final"),
        pl.col("def_cb_out").alias("opp_cb_out"),
        pl.col("def_s_out").alias("opp_s_out"),
        pl.col("def_dl_out").alias("opp_dl_out"),
        pl.col("def_db_questionable").alias("opp_db_questionable"),
        pl.col("def_dl_questionable").alias("opp_dl_questionable"),
    )
    status = report.select("gsis_id", "report_status")
    mine = shares.join(status, on="gsis_id", how="left").select(
        pl.col("team").alias(team_column),
        "gsis_id",
        pl.when(_confirmed())
        .then(pl.col("target_share_recent"))
        .otherwise(0.0)
        .alias(
            "_own_out_targets",
        ),
        pl.when(_confirmed())
        .then(pl.col("carry_share_recent"))
        .otherwise(0.0)
        .alias(
            "_own_out_carries",
        ),
        pl.when(_uncertain())
        .then(pl.col("target_share_recent"))
        .otherwise(0.0)
        .alias(
            "_own_q_targets",
        ),
    )
    drop = [
        name
        for name in (
            *OFFENSE_HEALTH_COLUMNS,
            *DEFENSE_HEALTH_COLUMNS,
            *VACATED_COLUMNS,
            "own_report_final",
            "opp_report_final",
        )
        if name in rows.columns
    ]
    frame = (
        rows.drop(drop)
        .join(own, on=team_column, how="left")
        .join(opposing, on=opponent_column, how="left")
        .join(vacated.rename({"team": team_column}), on=team_column, how="left")
        .join(mine, on=[team_column, "gsis_id"], how="left")
    )
    final = pl.col("own_report_final").fill_null(False)
    frame = frame.with_columns(
        pl.when(final)
        .then(
            (pl.col("out_targets").fill_null(0.0) - pl.col("_own_out_targets").fill_null(0.0))
            .clip(0.0, None)
            .round(6),
        )
        .otherwise(None)
        .alias("own_vacated_targets"),
        pl.when(final)
        .then(
            (pl.col("out_carries").fill_null(0.0) - pl.col("_own_out_carries").fill_null(0.0))
            .clip(0.0, None)
            .round(6),
        )
        .otherwise(None)
        .alias("own_vacated_carries"),
        pl.when(final)
        .then(
            (
                pl.col("questionable_targets").fill_null(0.0)
                - pl.col("_own_q_targets").fill_null(0.0)
            )
            .clip(0.0, None)
            .round(6),
        )
        .otherwise(None)
        .alias("own_questionable_targets"),
    )
    return frame.drop(
        "out_targets",
        "out_carries",
        "questionable_targets",
        "_own_out_targets",
        "_own_out_carries",
        "_own_q_targets",
    )


#: Skill players worth naming on the page when they are listed: a share of the recent
#: targets or carries that a reader would notice going missing.
NOTABLE_TARGET_SHARE = 0.10
NOTABLE_CARRY_SHARE = 0.20


def absence_lists(
    starters: pl.DataFrame,
    shares: pl.DataFrame,
    report: pl.DataFrame,
    teams: list[str],
) -> dict[str, dict[str, Any]]:
    """Per team, the listed players a reader should see named, for the published context.

    Lagged starters of every group plus skill players with a notable recent share, each with
    his designation; only players the report lists as Out, Doubtful or Questionable.
    """
    final = _final_teams(report)
    status = report.select(
        "gsis_id",
        "report_status",
        "practice_status",
        "primary_injury",
        "full_name",
        pl.col("position").alias("report_position"),
    )
    listed_starters = starters.join(status, on="gsis_id", how="inner").filter(
        _confirmed() | _uncertain(),
    )
    notable = (
        shares.filter(
            (pl.col("target_share_recent") >= NOTABLE_TARGET_SHARE)
            | (pl.col("carry_share_recent") >= NOTABLE_CARRY_SHARE),
        )
        .join(status, on="gsis_id", how="inner")
        .filter(_confirmed() | _uncertain())
    )
    order = {group.key: index for index, group in enumerate(STARTER_GROUPS)}
    result: dict[str, dict[str, Any]] = {}
    for team in sorted(set(teams)):
        entries: list[dict[str, Any]] = []
        seen: set[str] = set()
        for row in listed_starters.filter(pl.col("team") == team).iter_rows(named=True):
            seen.add(str(row["gsis_id"]))
            entries.append(
                {
                    "player_id": f"gsis:{row['gsis_id']}",
                    "name": row["full_name"] or row["player_name"],
                    "position": row["report_position"] or row["position"],
                    "role": f"{row['group']}{row['starter_rank']}",
                    "group": row["group"],
                    "starter_rank": int(row["starter_rank"]),
                    "snap_share": float(row["share"]),
                    "target_share": None,
                    "carry_share": None,
                    "designation": row["report_status"],
                    "practice_status": row["practice_status"],
                    "primary_injury": row["primary_injury"],
                },
            )
        for row in notable.filter(pl.col("team") == team).iter_rows(named=True):
            if str(row["gsis_id"]) in seen:
                continue
            entries.append(
                {
                    "player_id": f"gsis:{row['gsis_id']}",
                    "name": row["full_name"],
                    "position": row["report_position"],
                    "role": "skill",
                    "group": "SKILL",
                    "starter_rank": None,
                    "snap_share": None,
                    "target_share": float(row["target_share_recent"]),
                    "carry_share": float(row["carry_share_recent"]),
                    "designation": row["report_status"],
                    "practice_status": row["practice_status"],
                    "primary_injury": row["primary_injury"],
                },
            )
        entries.sort(
            key=lambda entry: (
                0 if entry["designation"] in CONFIRMED_DESIGNATIONS else 1,
                order.get(str(entry["group"]), len(order)),
                entry["starter_rank"] or 99,
                -(entry["target_share"] or 0.0),
                str(entry["player_id"]),
            ),
        )
        result[team] = {"report_final": team in final, "listed": entries}
    return result
