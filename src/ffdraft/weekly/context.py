"""The game a projection is for: its environment and its opponent (``weekly_game_context_v1``).

Two families of weekly-model input that the rest-of-season model does not have, because a
rest-of-season total averages over a dozen games and a start/sit decision is about one:

**Game environment**, from nflverse's schedule. The sportsbook total, this team's side of the
spread, the implied team total derived from them, home or away, the rest difference and
whether the game is indoors. For a completed season every game carries its closing lines;
for the current one, lines are posted about two weeks ahead, which covers the one game this
model projects. A missing line is null, never a pick'em — LightGBM routes a null natively.

**Opponent**, from the weekly rows themselves: fantasy points the defence has allowed to this
position per game, **through the cutoff only**, shrunk toward the league's rate at the same
cutoff by ``OPPONENT_SHRINKAGE_GAMES`` games, plus the defence's full previous-season rate.
Point-in-time by construction — :func:`opponent_allowed` accepts the cutoff and never reads a
later week, and ``tests/unit/test_weekly_context.py`` proves it by deleting the future and
asserting nothing moves.

Nothing here reads a model output, and nothing here is read by an intrinsic model.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime

import polars as pl

from ffdraft.config import ScoringPreset, ScoringRules
from ffdraft.contracts.enums import normalize_team_code
from ffdraft.scoring.engine import score_weekly_frame
from ffdraft.scoring.horizon import fantasy_horizon
from ffdraft.season.state import scheduled_kickoff_utc
from ffdraft.weekly.frozen import OPPONENT_SHRINKAGE_GAMES, WEEKLY_POSITIONS
from ffdraft.weekly.venues import VenueRegistry, published_roof

__all__ = [
    "GAME_CONTEXT_COLUMNS",
    "OPPONENT_COLUMNS",
    "opponent_allowed",
    "scored_position_rows",
    "team_game_context",
]

GAME_CONTEXT_COLUMNS: tuple[str, ...] = (
    "game_total_line",
    "game_team_margin",
    "game_team_points",
    "game_is_home",
    "game_rest_advantage",
    "game_indoors",
)

OPPONENT_COLUMNS: tuple[str, ...] = (
    "opp_allowed_ppg",
    "opp_allowed_index",
    "opp_allowed_prior_ppg",
    "opp_games_to_date",
)

_INDOOR_ROOFS = frozenset({"dome", "closed"})


def _hundredths(column: str) -> pl.Expr:
    """Fantasy points as integer hundredths: exact for every preset, summable in any order."""
    return (pl.col(column) * 100.0).round(0).cast(pl.Int64)


def team_game_context(
    schedule: pl.DataFrame,
    seasons: Sequence[int],
    *,
    venues: VenueRegistry | None = None,
) -> pl.DataFrame:
    """One row per ``(season, week, team)`` regular-season game inside the fantasy horizon.

    Each game appears twice, once from each side, with the spread re-expressed from the
    team's own side: nflverse's ``spread_line`` is positive when the **home** team is
    favoured (probed 2026-09-22, ADR-091), so the away side is its negation.

    **An unannounced roof.** A retractable roof's state is recorded after kickoff, so a future
    game there has none (the 2026 week-4 DAL @ HOU game, observed 2026-09-30). ``roof`` stays
    null, because that is what the schedule says, but ``game_indoors`` takes the state of the
    home team's latest earlier non-neutral home game this season: a schedule fact already
    recorded, never a guess. With no such game it stays null, which the model reads as open
    air. Every training row has a recorded roof, so this never fires on history.

    **A verified fixed roof wins** (``venues``, serving only; ADR-099). Before an international
    game nflverse can file an open-air stadium as ``dome``: in 2026 the Melbourne Cricket
    Ground (kept ``dome`` after the game, beside a recorded 57 F and 4 mph wind), the Stade de
    France and the Allianz Arena, all open to the sky. Where the game resolves to a registry
    venue whose roof is ``open`` or ``dome``, ``roof`` is
    :func:`~ffdraft.weekly.venues.published_roof` (the venue's label when the schedule
    contradicts it), ``game_indoors`` follows it, and nothing is ``roof_inferred``; a
    retractable, unverified or unresolved venue keeps the schedule's roof as above. The
    schedule's own value is published beside it as ``weekly_context``'s ``roof.recorded``.
    Training passes no registry: over every 2017-2025 regular-season game the verified registry
    roof and nflverse's recorded roof agree (DATA_SOURCES 20.1), so the rule reproduces history
    exactly, and an edit to the registry can never move v1's frozen training rows.
    """
    wanted = {int(season) for season in seasons}
    rows: list[dict[str, object]] = []
    if schedule.is_empty():
        return _empty_context()
    games = schedule.filter(
        pl.col("season").is_in(sorted(wanted)) & (pl.col("game_type") == "REG"),
    )
    recorded_roofs: dict[tuple[int, str], list[tuple[int, str]]] = {}
    for game in games.iter_rows(named=True):
        home = normalize_team_code(game.get("home_team"))
        known = str(game.get("roof") or "").strip().lower()
        neutral = str(game.get("location") or "").strip().lower() == "neutral"
        if home is not None and known and not neutral:
            recorded_roofs.setdefault((int(game["season"]), home), []).append(
                (int(game["week"]), known),
            )
    for game in games.iter_rows(named=True):
        season = int(game["season"])
        week = int(game["week"])
        if not fantasy_horizon(season).contains(week):
            continue
        home = normalize_team_code(game.get("home_team"))
        away = normalize_team_code(game.get("away_team"))
        if home is None or away is None:
            continue
        spread = _number(game.get("spread_line"))
        total = _number(game.get("total_line"))
        home_rest = _number(game.get("home_rest"))
        away_rest = _number(game.get("away_rest"))
        roof = str(game.get("roof") or "").strip().lower()
        neutral = str(game.get("location") or "").strip().lower() == "neutral"
        kickoff = scheduled_kickoff_utc(game.get("gameday"), game.get("gametime"))
        indoors_roof = roof
        if not roof and not neutral:
            earlier = [
                (played, state)
                for played, state in recorded_roofs.get((season, home), [])
                if played < week
            ]
            indoors_roof = max(earlier)[1] if earlier else ""
        inferred = not roof and bool(indoors_roof)
        venue = (
            venues.resolve(
                season=season,
                stadium_id=game.get("stadium_id"),
                stadium=game.get("stadium"),
            )
            if venues is not None
            else None
        )
        if venue is not None and venue.roof_type in ("open", "dome"):
            roof = published_roof(venue, roof) or ""
            indoors_roof = roof
            inferred = False
        for team, opponent, is_home in ((home, away, True), (away, home, False)):
            margin = None if spread is None else (spread if is_home else -spread) + 0.0
            implied = None if margin is None or total is None else (total + margin) / 2.0
            team_rest = home_rest if is_home else away_rest
            opponent_rest = away_rest if is_home else home_rest
            rows.append(
                {
                    "season": season,
                    "week": week,
                    "team": team,
                    "game_id": str(game.get("game_id")),
                    "opponent": opponent,
                    "home_away": "home" if is_home else "away",
                    "neutral_site": neutral,
                    "kickoff_utc": kickoff,
                    "roof": roof or None,
                    # The unannounced-roof fill above, made visible: the page must say "assumed".
                    "roof_inferred": inferred,
                    "game_total_line": total,
                    "game_team_margin": margin,
                    "game_team_points": implied,
                    # A neutral site is nobody's home, whatever the schedule calls it.
                    "game_is_home": 0.0 if neutral else (1.0 if is_home else 0.0),
                    "game_rest_advantage": (
                        None
                        if team_rest is None or opponent_rest is None
                        else team_rest - opponent_rest
                    ),
                    "game_indoors": (
                        None
                        if not indoors_roof
                        else (1.0 if indoors_roof in _INDOOR_ROOFS else 0.0)
                    ),
                },
            )
    if not rows:
        return _empty_context()
    return pl.DataFrame(rows, schema=_CONTEXT_SCHEMA, orient="row").sort("season", "week", "team")


_CONTEXT_SCHEMA: Mapping[str, pl.DataType] = {
    "season": pl.Int32(),
    "week": pl.Int32(),
    "team": pl.String(),
    "game_id": pl.String(),
    "opponent": pl.String(),
    "home_away": pl.String(),
    "neutral_site": pl.Boolean(),
    "kickoff_utc": pl.Datetime("us", "UTC"),
    "roof": pl.String(),
    "roof_inferred": pl.Boolean(),
    "game_total_line": pl.Float64(),
    "game_team_margin": pl.Float64(),
    "game_team_points": pl.Float64(),
    "game_is_home": pl.Float64(),
    "game_rest_advantage": pl.Float64(),
    "game_indoors": pl.Float64(),
}


def _empty_context() -> pl.DataFrame:
    return pl.DataFrame(schema=dict(_CONTEXT_SCHEMA))


def scored_position_rows(
    weekly: pl.DataFrame,
    scoring: Mapping[ScoringPreset, ScoringRules],
    seasons: Sequence[int],
) -> pl.DataFrame:
    """Scorable regular-season horizon rows, one per player-week, points per preset, long.

    Columns: ``season, week, gsis_id, team, defense, position, scoring_preset, points``. The
    defence is the row's own ``opponent_team``; a row without one cannot say who allowed it and
    is dropped from the opponent reading (it still counts for the player's own target).
    """
    wanted = sorted({int(season) for season in seasons})
    if weekly.is_empty() or not wanted:
        return _empty_scored()
    in_horizon = pl.lit(False)
    for season in wanted:
        horizon = fantasy_horizon(season)
        in_horizon = in_horizon | (
            (pl.col("season") == season)
            & (pl.col("week") >= horizon.first_week)
            & (pl.col("week") <= horizon.last_week)
        )
    rows = weekly.filter(
        pl.col("season").is_in(wanted) & (pl.col("season_type") == "REG") & in_horizon,
    )
    if rows.is_empty():
        return _empty_scored()
    scored = score_weekly_frame(rows, scoring)
    presets = [str(preset) for preset in sorted(scoring)]
    opponent = "opponent_team" if "opponent_team" in scored.columns else None
    base = scored.select(
        pl.col("season").cast(pl.Int32),
        pl.col("week").cast(pl.Int32),
        pl.col("gsis_id").cast(pl.String),
        pl.col("team").map_elements(normalize_team_code, return_dtype=pl.String).alias("team"),
        (
            pl.col(opponent).map_elements(normalize_team_code, return_dtype=pl.String)
            if opponent
            else pl.lit(None, dtype=pl.String)
        ).alias("defense"),
        pl.col("position").cast(pl.String),
        *[pl.col(f"fantasy_points_{preset}").alias(preset) for preset in presets],
    )
    return base.unpivot(
        index=["season", "week", "gsis_id", "team", "defense", "position"],
        on=presets,
        variable_name="scoring_preset",
        value_name="points",
    )


def _empty_scored() -> pl.DataFrame:
    return pl.DataFrame(
        schema={
            "season": pl.Int32,
            "week": pl.Int32,
            "gsis_id": pl.String,
            "team": pl.String,
            "defense": pl.String,
            "position": pl.String,
            "scoring_preset": pl.String,
            "points": pl.Float64,
        },
    )


def opponent_allowed(
    scored: pl.DataFrame,
    *,
    season: int,
    through_week: int,
    shrinkage_games: float = OPPONENT_SHRINKAGE_GAMES,
) -> pl.DataFrame:
    """Points each defence has allowed to each position, per game, through ``through_week``.

    One row per ``(defense, position, scoring_preset)`` for every defence that has played at
    least once by the cutoff. Weeks after the cutoff are filtered out **here**, first, so a
    caller cannot hand in the future by accident.

    ``opp_allowed_ppg`` is shrunk: ``(allowed + k * league) / (games + k)``, where ``league``
    is every defence's allowed total over every defence's games at the same cutoff.
    ``opp_allowed_index`` is that over ``league`` — 1.20 means twenty percent more than an
    average defence. ``opp_allowed_prior_ppg`` is the unshrunk full previous season.
    """
    if scored.is_empty():
        return _empty_allowed()
    current = scored.filter(
        (pl.col("season") == season)
        & (pl.col("week") <= through_week)
        & pl.col("defense").is_not_null()
        & pl.col("position").is_in(list(WEEKLY_POSITIONS)),
    )
    prior = scored.filter(
        (pl.col("season") == season - 1)
        & pl.col("defense").is_not_null()
        & pl.col("position").is_in(list(WEEKLY_POSITIONS)),
    )
    if current.is_empty():
        return _empty_allowed()

    games = (
        scored.filter(
            (pl.col("season") == season)
            & (pl.col("week") <= through_week)
            & pl.col("defense").is_not_null(),
        )
        .select("defense", "week")
        .unique()
        .group_by("defense")
        .agg(pl.len().cast(pl.Float64).alias("opp_games_to_date"))
    )
    # Summed in integer hundredths. Every scoring rule here awards multiples of 0.02 points, so
    # the conversion is exact — and an integer sum, unlike Polars' parallel float sum, is the
    # same in every order it is added in. Two builds of the same weeks used to differ by
    # ~1e-15, enough to move a LightGBM bin edge and make two fits different bytes (ADR-096).
    allowed = current.group_by("defense", "position", "scoring_preset").agg(
        _hundredths("points").sum().alias("allowed_cents"),
    )
    presets = current.select("scoring_preset").unique()
    positions = pl.DataFrame({"position": list(WEEKLY_POSITIONS)})
    grid = games.join(positions, how="cross").join(presets, how="cross")
    frame = (
        grid.join(allowed, on=["defense", "position", "scoring_preset"], how="left")
        .with_columns(pl.col("allowed_cents").fill_null(0))
        .with_columns((pl.col("allowed_cents") / 100.0).alias("allowed"))
    )
    league = frame.group_by("position", "scoring_preset").agg(
        (pl.col("allowed_cents").sum() / 100.0 / pl.col("opp_games_to_date").sum()).alias(
            "league_ppg",
        ),
    )
    frame = frame.join(league, on=["position", "scoring_preset"], how="left").with_columns(
        (
            (pl.col("allowed") + shrinkage_games * pl.col("league_ppg"))
            / (pl.col("opp_games_to_date") + shrinkage_games)
        ).alias("opp_allowed_ppg"),
    )
    frame = frame.with_columns(
        pl.when(pl.col("league_ppg") > 0)
        .then(pl.col("opp_allowed_ppg") / pl.col("league_ppg"))
        .otherwise(None)
        .alias("opp_allowed_index"),
    )

    if prior.is_empty():
        frame = frame.with_columns(pl.lit(None, dtype=pl.Float64).alias("opp_allowed_prior_ppg"))
    else:
        prior_games = (
            prior.select("defense", "week")
            .unique()
            .group_by("defense")
            .agg(pl.len().cast(pl.Float64).alias("prior_games"))
        )
        prior_allowed = (
            prior.group_by("defense", "position", "scoring_preset")
            .agg((_hundredths("points").sum() / 100.0).alias("prior_allowed"))
            .join(prior_games, on="defense", how="left")
            .with_columns(
                (pl.col("prior_allowed") / pl.col("prior_games")).alias("opp_allowed_prior_ppg"),
            )
            .select("defense", "position", "scoring_preset", "opp_allowed_prior_ppg")
        )
        frame = frame.join(
            prior_allowed,
            on=["defense", "position", "scoring_preset"],
            how="left",
        )
    frame = frame.with_columns(
        pl.col("opp_allowed_ppg")
        .rank(method="min", descending=True)
        .over("position", "scoring_preset")
        .cast(pl.Int32)
        .alias("opp_allowed_rank"),
        pl.col("defense").n_unique().over("position", "scoring_preset").alias("opp_defenses"),
    )
    return frame.select(
        pl.lit(season, dtype=pl.Int32).alias("season"),
        pl.lit(through_week, dtype=pl.Int32).alias("through_week"),
        "defense",
        "position",
        "scoring_preset",
        "opp_allowed_ppg",
        "opp_allowed_index",
        "opp_allowed_prior_ppg",
        "opp_games_to_date",
        "league_ppg",
        "opp_allowed_rank",
        pl.col("opp_defenses").cast(pl.Int32),
    ).sort("position", "scoring_preset", "defense")


def _empty_allowed() -> pl.DataFrame:
    return pl.DataFrame(
        schema={
            "season": pl.Int32,
            "through_week": pl.Int32,
            "defense": pl.String,
            "position": pl.String,
            "scoring_preset": pl.String,
            "opp_allowed_ppg": pl.Float64,
            "opp_allowed_index": pl.Float64,
            "opp_allowed_prior_ppg": pl.Float64,
            "opp_games_to_date": pl.Float64,
            "league_ppg": pl.Float64,
            "opp_allowed_rank": pl.Int32,
            "opp_defenses": pl.Int32,
        },
    )


def _number(value: object) -> float | None:
    if value is None:
        return None
    try:
        parsed = float(str(value))
    except (TypeError, ValueError):
        return None
    return None if parsed != parsed else parsed


def kickoff_after(kickoff: datetime | None, as_of: datetime) -> bool:
    """True when the game has not started at ``as_of``. An unknown kickoff is not after."""
    return kickoff is not None and kickoff > as_of
