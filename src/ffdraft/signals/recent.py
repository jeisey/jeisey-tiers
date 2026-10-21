"""Recent form: a calendar window's points and rank, and a descriptive breakout category.

**The question this answers** (ADR-113). "Whose recent production and role are substantially
better than his season-long rank suggests — and is it sustained, or one big game?" The
season rank (``season_actuals_v1``) answers the first half for the whole season; this module
answers it for the last 1, 2, 3, 4 or 6 completed weeks, and then states — as explicit,
inspectable predicates and never as a score — whether the most recent games inside that window
back the movement up.

Two rules, versioned separately:

``recent_form_v1`` — the window and its standing.

* **Calendar weeks, common to everyone.** Window *N* is the completed regular-season weeks
  ``max(first, W − N + 1)..W`` where *W* is the board's cutoff (the same cutoff season actuals
  use, clipped to the fantasy horizon). At cutoff 5, Last 3 is weeks 3–5 for every player. It
  is never "each player's last three games": a bye or a missed game shows up as fewer games,
  not as a reach back into older weeks. Early in the season a window can be shorter than
  requested; the metadata publishes the real first and last week.
* **Points, games, rank** over that window, with season actuals' definitions exactly: the
  scoring engine's points, an appearance is a stats row or an offensive snap, and the rank is
  a competition rank of points (rounded to 0.01 before ranking) among **every** player at the
  position with an appearance in the window — the league, not a board. A zero or negative
  game is an observation; a player with no appearance in the window has no rank.
* **Per-week facts** for the six-week span: whether he played (``P``), his team had a bye
  (``B``) or he did not play (``D``); his points; his weekly positional rank among every player
  who appeared that week. Byes, missed games and zero-point games stay three different things.

``breakout_v1`` — the category (the rule table is in ADR-113 and in :class:`BreakoutRule`).

* Gates, in order: an appearance in the window; a recent rank inside the position's band;
  enough games **before** the window for the season rank to be a baseline; a recent rank
  better than the season rank by at least 3 places **and** 30% of the season rank; no missed
  team game after his latest appearance (a streak that ended with an absence is not current).
* Production: his weekly positional rank inside the band, game by game, over consecutive
  appearances inside the window, newest first. A bye is not a game and does not break a run.
* Role: one of the position's declared measures reaches a substantial level over the evidence
  games, or an emerging level with a real increase over the pre-window baseline. Never a
  quarterback's targets; never growth from a tiny baseline alone.
* Category: **takeover** — three strong consecutive appearances and a confirmed role over
  them; **sneaking** — two; **eyebrow** — a strong latest appearance only (a one-game watch);
  **none** — the evidence exists and the rules do not pass; **insufficient** — the sample,
  the baseline or the role facts the stronger category needs do not exist.

Observed facts and fixed thresholds only. Nothing here is a model input; nothing here reads a
model output, an add count, an ESPN reading or a market.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import polars as pl

from ffdraft.config import ScoringPreset, ScoringRules
from ffdraft.contracts import QualityCheck
from ffdraft.contracts.enums import Severity, normalize_team_code
from ffdraft.identity.ids import IdNamespace, make_player_id
from ffdraft.scoring.engine import SCORING_ENGINE_VERSION, score_weekly_frame
from ffdraft.scoring.horizon import fantasy_horizon
from ffdraft.signals.actuals import (
    ACTUALS_POSITIONS,
    SeasonActualsResult,
    _cents,
    _scheduled_teams,
    _scoped_snaps,
    _scoped_stats,
    competition_ranks,
)

__all__ = [
    "BREAKOUT_CATEGORIES",
    "BREAKOUT_RULE",
    "BREAKOUT_RULE_VERSION",
    "RECENT_FORM_RULE",
    "RECENT_FORM_RULE_VERSION",
    "RECENT_WINDOWS",
    "BreakoutRule",
    "RecentGame",
    "RecentFormResult",
    "RecentFormRule",
    "RoleMeasure",
    "build_recent_form",
    "evaluate_breakout",
    "window_weeks",
]

#: Bump when the meaning of a window, its points, games or rank changes.
RECENT_FORM_RULE_VERSION = "recent_form_v1"
#: Bump when any breakout threshold or predicate changes.
BREAKOUT_RULE_VERSION = "breakout_v1"

#: The windows the page offers, in weeks. "Season" is season actuals, not a window here.
RECENT_WINDOWS: tuple[int, ...] = (1, 2, 3, 4, 6)

#: Highest first. ``none`` and ``insufficient`` are states, never badges.
BREAKOUT_CATEGORIES: tuple[str, ...] = ("takeover", "sneaking", "eyebrow", "none", "insufficient")

#: Week status codes in ``span_status``.
PLAYED, BYE, DID_NOT_PLAY = "P", "B", "D"


@dataclass(frozen=True, slots=True)
class RecentFormRule:
    version: str = RECENT_FORM_RULE_VERSION
    windows: tuple[int, ...] = RECENT_WINDOWS
    default_window: int = 3
    points_decimals: int = 2
    rank_method: str = "competition"

    @property
    def span(self) -> int:
        return max(self.windows)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "windows": list(self.windows),
            "default_window": self.default_window,
            "points_decimals": self.points_decimals,
            "rank_method": self.rank_method,
            "scoring_engine_version": SCORING_ENGINE_VERSION,
        }


RECENT_FORM_RULE = RecentFormRule()


@dataclass(frozen=True, slots=True)
class RoleMeasure:
    """One role measure and its thresholds, in the measure's own unit.

    ``substantial`` alone confirms a role. ``emerging`` with ``increase`` confirms a *grown*
    role: the level must reach ``emerging`` **and** exceed the pre-window baseline by at least
    ``increase`` — so growth from a tiny baseline to a still-small role never passes.
    """

    metric: str
    #: ``pooled``: his total over his team's total in the same games. ``mean``: per-game mean.
    averaging: str
    substantial: float
    emerging: float | None = None
    increase: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "metric": self.metric,
            "averaging": self.averaging,
            "substantial": self.substantial,
            "emerging": self.emerging,
            "increase": self.increase,
        }


def _default_measures() -> dict[str, tuple[RoleMeasure, ...]]:
    return {
        # A quarterback's role is whether he is the one playing: his snaps and his throws.
        # Never his targets. No growth path: going from backup to starter reaches the level.
        "QB": (
            RoleMeasure("snap_share", "mean", 0.80),
            RoleMeasure("pass_attempts", "mean", 25.0),
        ),
        "RB": (
            RoleMeasure("snap_share", "mean", 0.55, 0.40, 0.15),
            RoleMeasure("carry_share", "pooled", 0.45, 0.30, 0.15),
        ),
        "WR": (
            RoleMeasure("target_share", "pooled", 0.22, 0.16, 0.06),
            RoleMeasure("snap_share", "mean", 0.80, 0.65, 0.15),
        ),
        "TE": (
            RoleMeasure("target_share", "pooled", 0.18, 0.13, 0.05),
            RoleMeasure("snap_share", "mean", 0.70, 0.55, 0.15),
        ),
    }


def _default_bands() -> dict[str, int]:
    # A starter's finish in a 12-team league: one QB and one TE, two RBs and two WRs.
    return {"QB": 12, "RB": 24, "WR": 24, "TE": 12}


@dataclass(frozen=True, slots=True)
class BreakoutRule:
    """``breakout_v1``: editable heuristic constants, not a calibrated probability."""

    version: str = BREAKOUT_RULE_VERSION
    #: Recent rank must be inside this band; also the "strong week" cutoff for a weekly rank.
    bands: Mapping[str, int] = field(default_factory=_default_bands)
    #: Season rank minus recent rank, in places, at least this…
    min_gain_places: int = 3
    #: …and at least this percentage of the season rank.
    min_gain_percent: int = 30
    #: Appearances before the window's first week, so the season rank is a baseline at all.
    min_prior_games: int = 2
    #: Missed team games (not byes) after his latest appearance through the cutoff.
    max_missed_after_latest: int = 0
    takeover_games: int = 3
    sneaking_games: int = 2
    measures: Mapping[str, tuple[RoleMeasure, ...]] = field(default_factory=_default_measures)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "bands": dict(self.bands),
            "min_gain_places": self.min_gain_places,
            "min_gain_percent": self.min_gain_percent,
            "min_prior_games": self.min_prior_games,
            "max_missed_after_latest": self.max_missed_after_latest,
            "takeover_games": self.takeover_games,
            "sneaking_games": self.sneaking_games,
            "measures": {
                position: [measure.to_dict() for measure in measures]
                for position, measures in self.measures.items()
            },
        }


BREAKOUT_RULE = BreakoutRule()

#: The sentences that travel with the numbers.
RECENT_FORM_DEFINITIONS: Mapping[str, str] = {
    "window": (
        "The last N completed regular-season weeks ending at the cutoff, the same calendar "
        "weeks for every player. A bye or a missed game is fewer games, never an older week."
    ),
    "recent_rank": (
        "Rank by total points in the window among every player at the position who appeared "
        "in it, whichever board lists him. Ties share a rank. No appearance, no rank."
    ),
    "recent_vs_season": (
        "Season rank minus recent rank, in places. Positive means the recent rank is better."
    ),
    "breakout": (
        "A descriptive, heuristic category from fixed thresholds over published weekly ranks "
        "and role shares. Not a prediction, not a probability, and read by no model."
    ),
    "takeover": (
        "Three consecutive appearances inside the window, each a top-band weekly finish, with "
        "a substantial or clearly increased role over those games."
    ),
    "sneaking": (
        "His two most recent appearances inside the window are top-band weekly finishes with "
        "a confirmed role; the three-game condition is not met."
    ),
    "eyebrow": (
        "A one-game watch: his latest appearance is a top-band weekly finish, and earlier "
        "games do not establish a sustained pattern."
    ),
    "insufficient": (
        "The sample, the pre-window baseline or the role facts the rule needs do not exist, "
        "so no category is stated — not a 'no'."
    ),
}


@dataclass(slots=True)
class RecentFormResult:
    records: list[dict[str, Any]]
    metadata: dict[str, Any]
    checks: list[QualityCheck] = field(default_factory=list)

    @property
    def published(self) -> bool:
        return self.metadata.get("status") == "published"


def window_weeks(last_week: int, first_week: int, size: int) -> list[int]:
    """The calendar weeks of a window of ``size`` ending at ``last_week``."""
    return list(range(max(first_week, last_week - size + 1), last_week + 1))


# --------------------------------------------------------------------------- weekly facts


@dataclass(slots=True)
class RecentGame:
    """One appearance's facts. Counts are zero on a snaps-only week, which is an observation."""

    week: int
    team: str | None
    cents: dict[str, int]
    snap_share: float | None = None
    targets: float = 0.0
    carries: float = 0.0
    pass_attempts: float = 0.0
    team_targets: float | None = None
    team_carries: float | None = None


def _pooled(games: Sequence[RecentGame], numerator: str, denominator: str) -> float | None:
    if any(getattr(game, denominator) is None for game in games):
        return None
    total = sum(float(getattr(game, denominator) or 0.0) for game in games)
    if total <= 0:
        return None
    return sum(float(getattr(game, numerator)) for game in games) / total


def _measure_value(games: Sequence[RecentGame], measure: RoleMeasure) -> float | None:
    """The measure over these games, or None when any game lacks the fact it needs."""
    if not games:
        return None
    match measure.metric:
        case "target_share":
            return _pooled(games, "targets", "team_targets")
        case "carry_share":
            return _pooled(games, "carries", "team_carries")
        case "snap_share":
            values = [game.snap_share for game in games]
            if any(value is None for value in values):
                return None
            return sum(float(value or 0.0) for value in values) / len(values)
        case "pass_attempts":
            return sum(game.pass_attempts for game in games) / len(games)
    raise ValueError(f"unknown role measure {measure.metric!r}")


def _digits(metric: str) -> int:
    return 3 if metric.endswith("_share") else 1


def _units(value: float, metric: str) -> int:
    """A rounded value in integer units of its published precision: exact comparisons."""
    return int(round(round(value, _digits(metric)) * 10 ** _digits(metric)))


def _role_reading(
    measure: RoleMeasure,
    games: Sequence[RecentGame],
    prior: Sequence[RecentGame],
    rule: BreakoutRule,
) -> dict[str, Any]:
    digits = _digits(measure.metric)
    level = _measure_value(games, measure)
    # The baseline pools only the pre-window games where the fact exists, and needs as many
    # of them as the rank baseline does.
    defined_prior = [game for game in prior if _measure_value([game], measure) is not None]
    baseline = (
        _measure_value(defined_prior, measure)
        if len(defined_prior) >= rule.min_prior_games
        else None
    )
    level_r = None if level is None else round(level, digits)
    baseline_r = None if baseline is None else round(baseline, digits)
    passed: str | None = None
    if level_r is not None:
        if _units(level_r, measure.metric) >= _units(measure.substantial, measure.metric):
            passed = "substantial"
        elif (
            measure.emerging is not None
            and measure.increase is not None
            and baseline_r is not None
            and _units(level_r, measure.metric) >= _units(measure.emerging, measure.metric)
            and _units(level_r, measure.metric) - _units(baseline_r, measure.metric)
            >= _units(measure.increase, measure.metric)
        ):
            passed = "increase"
    return {
        "metric": measure.metric,
        "games": len(games),
        "level": level_r,
        "baseline": baseline_r,
        "baseline_games": len(defined_prior),
        "passed": passed,
    }


def _role_check(
    position: str,
    games: Sequence[RecentGame],
    prior: Sequence[RecentGame],
    rule: BreakoutRule,
) -> tuple[str, list[dict[str, Any]]]:
    """``pass`` / ``fail`` / ``unknown`` and every measure's reading."""
    readings = [_role_reading(m, games, prior, rule) for m in rule.measures.get(position, ())]
    if any(reading["passed"] is not None for reading in readings):
        return "pass", readings
    if not readings or any(reading["level"] is None for reading in readings):
        return "unknown", readings
    return "fail", readings


# ------------------------------------------------------------------------ the category


def evaluate_breakout(
    *,
    position: str,
    season_rank: int | None,
    window_rank: int | None,
    window_games: Sequence[RecentGame],
    week_ranks: Mapping[int, int],
    prior_games: Sequence[RecentGame],
    missed_after_latest: int,
    rule: BreakoutRule = BREAKOUT_RULE,
) -> dict[str, Any]:
    """``breakout_v1`` for one player, one window, one preset. Gates in a fixed order."""
    band = int(rule.bands[position])

    def result(
        category: str,
        reason: str,
        *,
        games: Sequence[int] = (),
        streak: int | None = None,
        role: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        return {
            "category": category,
            "reason": reason,
            "games": list(games),
            "streak": streak,
            "role": role,
        }

    if not window_games or window_rank is None:
        return result("insufficient", "no_games")
    if window_rank > band:
        return result("none", "outside_band")
    if len(prior_games) < rule.min_prior_games or season_rank is None:
        return result("insufficient", "no_baseline")
    gain = season_rank - window_rank
    if gain <= 0:
        return result("none", "not_improved")
    if gain < rule.min_gain_places or gain * 100 < rule.min_gain_percent * season_rank:
        return result("none", "gain_too_small")
    if missed_after_latest > rule.max_missed_after_latest:
        return result("none", "stale")

    newest_first = sorted(window_games, key=lambda game: game.week, reverse=True)
    streak = 0
    for game in newest_first:
        rank = week_ranks.get(game.week)
        if rank is None or rank > band:
            break
        streak += 1
        if streak == rule.takeover_games:
            break
    if streak == 0:
        return result("none", "latest_not_strong", games=[newest_first[0].week], streak=0)

    last_role: list[dict[str, Any]] | None = None
    for size, category in ((rule.takeover_games, "takeover"), (rule.sneaking_games, "sneaking")):
        if streak < size:
            continue
        used = newest_first[:size]
        weeks = sorted(game.week for game in used)
        verdict, readings = _role_check(position, used, prior_games, rule)
        if verdict == "pass":
            return result(category, f"{category}_role", games=weeks, streak=streak, role=readings)
        if verdict == "unknown":
            return result(
                "insufficient",
                "role_unavailable",
                games=weeks,
                streak=streak,
                role=readings,
            )
        last_role = readings
    reason = "one_strong" if streak == 1 else "role_not_confirmed"
    return result(
        "eyebrow",
        reason,
        games=[newest_first[0].week],
        streak=streak,
        role=last_role,
    )


# ------------------------------------------------------------------------------ builder


def build_recent_form(
    *,
    weekly: pl.DataFrame,
    snap_counts: pl.DataFrame,
    schedule: pl.DataFrame,
    scoring: Mapping[ScoringPreset, ScoringRules],
    season: int,
    through_week: int,
    actuals: SeasonActualsResult,
    include: Iterable[str] = (),
    build_id: str,
    schema_version: str,
    rule: RecentFormRule = RECENT_FORM_RULE,
    breakout: BreakoutRule = BREAKOUT_RULE,
) -> RecentFormResult:
    """Every player who appeared in the span, plus every board player, per scoring preset.

    Reads the season actuals the same build produced for positions, names and season ranks,
    and is withheld whenever they are: the windows are slices of the same population, under
    the same completeness check.
    """
    horizon = fantasy_horizon(season)
    last_week = min(int(through_week), horizon.last_week)
    first_week = horizon.first_week
    span = window_weeks(last_week, first_week, rule.span)
    windows = {str(size): window_weeks(last_week, first_week, size) for size in rule.windows}
    presets = sorted(str(preset) for preset in scoring)
    base_metadata: dict[str, Any] = {
        "rule": rule.to_dict(),
        "breakout_rule": breakout.to_dict(),
        "season": season,
        "through_week": int(through_week),
        "span_weeks": span,
        "windows": {
            key: {
                "requested": int(key),
                "first_week": weeks[0] if weeks else None,
                "last_week": weeks[-1] if weeks else None,
                "weeks": len(weeks),
            }
            for key, weeks in windows.items()
        },
        "scoring_presets": presets,
        "definitions": dict(RECENT_FORM_DEFINITIONS),
    }
    if not actuals.published or not span:
        reason = (
            "season actuals are withheld for this build, and recent windows are slices of the "
            "same population under the same completeness check"
            if not actuals.published
            else "no completed regular-season week through the cutoff"
        )
        return RecentFormResult(
            records=[],
            metadata={
                **base_metadata,
                "status": "withheld",
                "withheld_reason": reason,
                "records": 0,
                "population": {},
                "categories": {},
            },
            checks=[
                QualityCheck.fail(
                    "recent_form.withheld",
                    stage="recent_form",
                    message=(
                        "recent-form windows and breakout categories are withheld; every "
                        "board, value and rank is unaffected"
                    ),
                    observed=reason,
                    expected="published season actuals",
                    severity=Severity.WARNING,
                ),
            ],
        )

    # Season actuals decide position, name and season rank, so the two can never disagree.
    standing: dict[tuple[str, str], Mapping[str, Any]] = {
        (str(record["scoring_preset"]), str(record["player_id"])): record
        for record in actuals.records
    }
    positions: dict[str, str] = {}
    names: dict[str, str] = {}
    for record in actuals.records:
        positions[str(record["player_id"])] = str(record["position"])
        names[str(record["player_id"])] = str(record["display_name"])

    games = _season_games(
        weekly=weekly,
        snap_counts=snap_counts,
        season=season,
        last_week=last_week,
        scoring=scoring,
    )
    scheduled = _scheduled_teams(schedule, season=season, last_week=last_week)

    # Weekly positional ranks, per preset, over every player who appeared that week.
    week_ranks: dict[str, dict[int, dict[str, int]]] = {preset: {} for preset in presets}
    for week in span:
        for preset in presets:
            by_position: dict[str, dict[str, int]] = {}
            for player_id, by_week in games.items():
                game = by_week.get(week)
                position = positions.get(player_id)
                if game is None or position not in ACTUALS_POSITIONS:
                    continue
                by_position.setdefault(str(position), {})[player_id] = game.cents[preset]
            ranks: dict[str, int] = {}
            for members in by_position.values():
                ranks.update(competition_ranks(members))
            week_ranks[preset][week] = ranks

    # Window totals and ranks, per preset, over every player who appeared in the window.
    window_rank: dict[tuple[str, str], dict[str, int]] = {}
    window_population: dict[str, dict[str, int]] = {}
    for key, weeks in windows.items():
        counts = {position: 0 for position in ACTUALS_POSITIONS}
        for preset in presets:
            by_position = {}
            for player_id, by_week in games.items():
                position = positions.get(player_id)
                played = [by_week[week] for week in weeks if week in by_week]
                if not played or position not in ACTUALS_POSITIONS:
                    continue
                by_position.setdefault(str(position), {})[player_id] = sum(
                    game.cents[preset] for game in played
                )
            ranks = {}
            for members in by_position.values():
                ranks.update(competition_ranks(members))
            window_rank[(key, preset)] = ranks
            if preset == presets[0]:
                for position, members in by_position.items():
                    counts[position] = len(members)
        window_population[key] = counts

    in_span = {
        player_id
        for player_id, by_week in games.items()
        if positions.get(player_id) in ACTUALS_POSITIONS and any(week in by_week for week in span)
    }
    board = {
        player_id
        for player_id in include
        if any((preset, player_id) in standing for preset in presets)
    }
    population = sorted(in_span | board)

    records: list[dict[str, Any]] = []
    categories: dict[str, dict[str, dict[str, int]]] = {}
    for preset in presets:
        tally = categories.setdefault(preset, {})
        for player_id in population:
            season_record = standing.get((preset, player_id))
            if season_record is None:
                continue
            position = str(season_record["position"])
            by_week = games.get(player_id, {})
            teams = _teams_by_week(by_week, span)
            status = "".join(
                PLAYED
                if week in by_week
                else (
                    BYE
                    if teams.get(week) is not None and teams[week] not in scheduled.get(week, set())
                    else DID_NOT_PLAY
                )
                for week in span
            )
            span_points = [
                round(by_week[week].cents[preset] / 100, rule.points_decimals)
                if week in by_week
                else None
                for week in span
            ]
            span_ranks = [
                week_ranks[preset][week].get(player_id) if week in by_week else None
                for week in span
            ]
            own_ranks = {
                week: rank for week, rank in zip(span, span_ranks, strict=True) if rank is not None
            }
            entries: dict[str, Any] = {}
            for key, weeks in windows.items():
                played = [by_week[week] for week in weeks if week in by_week]
                cents = sum(game.cents[preset] for game in played)
                total = round(cents / 100, rule.points_decimals)
                rank = window_rank[(key, preset)].get(player_id) if played else None
                first = weeks[0]
                prior = [game for week, game in sorted(by_week.items()) if week < first]
                missed = 0
                if played:
                    latest = max(game.week for game in played)
                    missed = sum(
                        1
                        for index, week in enumerate(span)
                        if week > latest and status[index] == DID_NOT_PLAY
                    )
                verdict = evaluate_breakout(
                    position=position,
                    season_rank=season_record.get("season_position_rank"),
                    window_rank=rank,
                    window_games=played,
                    week_ranks=own_ranks,
                    prior_games=prior,
                    missed_after_latest=missed,
                    rule=breakout,
                )
                entries[key] = {
                    "games": len(played),
                    "points": total if played else 0.0,
                    "points_per_game": (
                        round(total / len(played), rule.points_decimals) if played else None
                    ),
                    "rank": rank,
                    "prior_games": len(prior),
                    "breakout": verdict,
                }
                tally.setdefault(key, {}).setdefault(verdict["category"], 0)
                tally[key][verdict["category"]] += 1
            records.append(
                {
                    "schema_version": schema_version,
                    "build_id": build_id,
                    "season": season,
                    "through_week": int(through_week),
                    "scoring_preset": preset,
                    "player_id": player_id,
                    "display_name": names.get(player_id, player_id),
                    "position": position,
                    "season_rank": season_record.get("season_position_rank"),
                    "span_status": status,
                    "span_points": span_points,
                    "span_ranks": span_ranks,
                    "windows": entries,
                },
            )

    return RecentFormResult(
        records=records,
        metadata={
            **base_metadata,
            "status": "published",
            "withheld_reason": None,
            "records": len(records),
            "population": window_population,
            "categories": categories,
        },
        checks=[
            QualityCheck.ok(
                "recent_form.published",
                stage="recent_form",
                message=(
                    f"{rule.version} + {breakout.version}: windows ending week {last_week} "
                    "over every appearing player, with descriptive breakout categories read "
                    "by no model"
                ),
                observed=(
                    f"{len(population)} player(s); default window "
                    f"{window_population.get(str(rule.default_window), {})}"
                ),
            ),
        ],
    )


def _teams_by_week(by_week: Mapping[int, RecentGame], span: Sequence[int]) -> dict[int, str | None]:
    """His club each span week: the week's own, else the latest before it, else the next one.

    A traded player's absence is read against the club he last played for, which is the
    question "did his team play without him?" asks.
    """
    known = sorted((week, game.team) for week, game in by_week.items() if game.team)
    teams: dict[int, str | None] = {}
    for week in span:
        game = by_week.get(week)
        if game is not None and game.team:
            teams[week] = game.team
            continue
        before = [team for seen, team in known if seen <= week]
        after = [team for seen, team in known if seen > week]
        teams[week] = before[-1] if before else (after[0] if after else None)
    return teams


def _season_games(
    *,
    weekly: pl.DataFrame,
    snap_counts: pl.DataFrame,
    season: int,
    last_week: int,
    scoring: Mapping[ScoringPreset, ScoringRules],
) -> dict[str, dict[int, RecentGame]]:
    """``player_id -> week -> RecentGame`` for every appearance through the cutoff.

    The appearance and point definitions are season actuals': the same scoped frames and the
    same scoring engine, so a window's sum over every week equals the season total.
    """
    presets = sorted(str(preset) for preset in scoring)
    stats = _scoped_stats(weekly, season=season, last_week=last_week)
    snaps = _scoped_snaps(snap_counts, season=season, last_week=last_week)
    scored = score_weekly_frame(stats, scoring) if not stats.is_empty() else stats

    team_totals: dict[tuple[int, str], dict[str, float]] = {}
    games: dict[str, dict[int, RecentGame]] = {}
    for row in scored.iter_rows(named=True):
        gsis = row.get("gsis_id")
        if not gsis:
            continue
        week = int(row["week"])
        team = normalize_team_code(row.get("team"))
        targets = float(row.get("targets") or 0.0)
        carries = float(row.get("carries") or 0.0)
        if team is not None:
            totals = team_totals.setdefault((week, team), {"targets": 0.0, "carries": 0.0})
            totals["targets"] += targets
            totals["carries"] += carries
        player_id = make_player_id(IdNamespace.GSIS, str(gsis))
        game = games.setdefault(player_id, {}).get(week)
        if game is None:
            game = RecentGame(week=week, team=team, cents={preset: 0 for preset in presets})
            games[player_id][week] = game
        game.team = game.team or team
        game.targets += targets
        game.carries += carries
        game.pass_attempts += float(row.get("pass_attempts") or 0.0)
        for preset in presets:
            # Sum of exact hundredths: the season total is the sum of the weekly totals.
            game.cents[preset] += _cents(float(row.get(f"fantasy_points_{preset}") or 0.0), 2)

    snap_share = _snap_shares(snap_counts, season=season, last_week=last_week)
    for row in snaps.iter_rows(named=True):
        player_id = make_player_id(IdNamespace.GSIS, str(row["gsis_id"]))
        week = int(row["week"])
        by_week = games.setdefault(player_id, {})
        if week not in by_week:
            by_week[week] = RecentGame(
                week=week,
                team=normalize_team_code(row.get("team")),
                cents={preset: 0 for preset in presets},
            )
    for player_id, by_week in games.items():
        for week, game in by_week.items():
            game.snap_share = snap_share.get((player_id, week))
            if game.team is not None and (week, game.team) in team_totals:
                totals = team_totals[(week, game.team)]
                game.team_targets = totals["targets"]
                game.team_carries = totals["carries"]
    return games


def _snap_shares(
    snap_counts: pl.DataFrame,
    *,
    season: int,
    last_week: int,
) -> dict[tuple[str, int], float]:
    """``(player_id, week) -> offensive snap share``, the usage layer's reading (max per week)."""
    if snap_counts.is_empty() or not {"gsis_id", "offense_pct"} <= set(snap_counts.columns):
        return {}
    scoped = snap_counts.filter(
        (pl.col("season") == season)
        & (pl.col("game_type") == "REG")
        & (pl.col("week") <= last_week)
        & pl.col("gsis_id").is_not_null()
        & pl.col("offense_pct").is_not_null(),
    )
    if scoped.is_empty():
        return {}
    grouped = scoped.group_by("week", "gsis_id").agg(pl.col("offense_pct").max())
    return {
        (make_player_id(IdNamespace.GSIS, str(row["gsis_id"])), int(row["week"])): float(
            row["offense_pct"],
        )
        for row in grouped.iter_rows(named=True)
    }
