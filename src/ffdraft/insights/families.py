"""The six story families: qualification predicates, effect, ordering and evidence.

Each detector returns :class:`Draft` objects — structured evidence, a chart payload and the
predicates the story passed, in the order the rule checks them — and never prose (that is
:mod:`ffdraft.insights.text`). A detector reads the facts (:mod:`ffdraft.insights.facts`) and
the build's published records only, through :class:`Context`. The predicate table, thresholds
and orderings are ADR-116's; every constant is :class:`~ffdraft.insights.rules.InsightRule`.

A story's subject is always a player a card can open (a published usage record). Cohorts are
wider — every player at the position who appeared — because a rank over a board is a rank over
a page, not the league (ADR-105).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from statistics import median
from typing import Any

from ffdraft.identity.ids import parse_player_id
from ffdraft.insights.facts import Line, SeasonFacts, competition_rank_of, pooled
from ffdraft.insights.rules import (
    FAMILY_SHORT,
    PRESCREEN_DESIGNATIONS,
    PRESCREEN_EMPLOYMENT,
    PRESCREEN_ROSTER_CODES,
    InsightRule,
)
from ffdraft.insights.text import window_label
from ffdraft.signals.recent import (
    BREAKOUT_RULE,
    DID_NOT_PLAY,
    PLAYED,
    _role_check,
    _role_reading,
)
from ffdraft.timeutil import parse_utc

__all__ = [
    "DETECTORS",
    "ROOMS",
    "Context",
    "Draft",
    "detect_opening",
    "detect_pace",
    "detect_roles",
    "detect_streak",
    "detect_upside",
    "detect_volume",
]

#: The weekly context's "notable recent share" floors (``ffdraft.weekly.lineup``), reused as
#: the smallest current share a teammate needs to be named next in line for vacated work. A
#: quarterback's is half his team's attempts: next in line means taking the snaps.
NOTABLE_SHARE: Mapping[str, float] = {"target_share": 0.10, "carry_share": 0.20, "pass_share": 0.50}

#: Rooms: which positions share an opportunity, the count it is measured in, and the share.
ROOMS: Mapping[str, tuple[tuple[str, ...], str, str]] = {
    "backfield": (("RB",), "carries", "carry_share"),
    "receiving": (("WR", "TE"), "targets", "target_share"),
}

#: Openings also read the passing room: a documented quarterback change is the starter's
#: absence and the attempts that moved, never a claim about his receivers' fit.
OPENING_ROOMS: Mapping[str, tuple[tuple[str, ...], str, str]] = {
    **ROOMS,
    "passing": (("QB",), "pass attempts", "pass_share"),
}

#: Reserve-type roster codes: a documented absence for the target week (ADR-101's list).
RESERVE_CODES: frozenset[str] = frozenset({"RES", "PUP", "NFI", "SUS", "EXE"})

ESPN_SOURCE = "espn_fantasy_ownership"
WEEKLY_SOURCE = "weekly_startsit_v1"
BASE_SOURCES = ("nflverse_player_stats", "nflverse_snap_counts", "nflverse_schedule")


@dataclass(slots=True)
class Draft:
    family: str
    variant: str
    horizon: str
    nature: str
    player_id: str
    position: str
    team: str | None
    subject: str
    order: tuple[Any, ...]
    evidence: dict[str, Any]
    chart: dict[str, Any]
    qualification: list[dict[str, Any]]
    sources: list[str]
    window: dict[str, Any] | None
    kickoff_utc: str | None = None
    target_week: int | None = None
    scoring_dependent: bool = True
    source_times: dict[str, Any] = field(default_factory=dict)
    #: Set by the selection: order within its family group, 1-based.
    family_rank: int = 0

    @property
    def story_id(self) -> str:
        return f"{FAMILY_SHORT[self.family]}-{self.subject}"


@dataclass(slots=True)
class Context:
    facts: SeasonFacts
    rule: InsightRule
    preset: str
    #: Players a card can open: the published usage records, by id.
    subjects: Mapping[str, Mapping[str, Any]]
    names: Mapping[str, str]
    actuals: Mapping[str, Mapping[str, Any]]
    recent: Mapping[str, Mapping[str, Any]]
    weekly: Mapping[str, Mapping[str, Any]]
    team_context: Mapping[str, Mapping[str, Any]]
    matchups: Mapping[str, Mapping[str, Any]]
    espn: Mapping[str, Mapping[str, Any]] | None
    board: Mapping[str, Mapping[str, Any]]
    generated_at: datetime
    target_week: int | None
    #: ``(family, reason) -> candidates refused`` for the metadata's suppression counts.
    suppressed: Counter[tuple[str, str]] = field(default_factory=Counter)

    @property
    def window(self) -> list[int]:
        return self.facts.window

    @property
    def baseline(self) -> list[int]:
        return self.facts.baseline

    @property
    def window_dict(self) -> dict[str, Any]:
        window, baseline = self.facts.window, self.facts.baseline
        return {
            "label": window_label(window[0], window[-1]),
            "first_week": window[0],
            "last_week": window[-1],
            "weeks": len(window),
            "baseline_first_week": baseline[0] if baseline else None,
            "baseline_last_week": baseline[-1] if baseline else None,
        }

    def name(self, player_id: str) -> str:
        return str(self.names.get(player_id) or player_id)

    def position(self, player_id: str) -> str | None:
        subject = self.subjects.get(player_id)
        if subject is not None and subject.get("position"):
            return str(subject["position"])
        return self.facts.positions.get(player_id)

    def espn_reading(self, player_id: str) -> tuple[float | None, str]:
        """``(percent rostered, state)``: a number only for an observed, fresh reading."""
        if self.espn is None:
            return None, "unavailable"
        record = self.espn.get(player_id)
        if record is None:
            return None, "no_reading"
        state = str(record.get("reading_state"))
        value = record.get("percent_rostered")
        if state != "observed" or value is None:
            return None, state
        return round(float(value), 1), state

    def espn_time(self, player_id: str) -> str | None:
        record = (self.espn or {}).get(player_id) or {}
        value = record.get("observed_at_utc")
        return str(value) if value else None

    def prescreen(self, player_id: str) -> str | None:
        """Why the build-time pre-screen refuses a ``this_week`` story for him, or None."""
        weekly = self.weekly.get(player_id) or {}
        designation = (weekly.get("injury") or {}).get("designation")
        if designation in PRESCREEN_DESIGNATIONS:
            return f"designated {designation}"
        board = self.board.get(player_id) or {}
        code = board.get("current_status")
        if code in PRESCREEN_ROSTER_CODES:
            return f"roster status {code}"
        employment = board.get("employment_status")
        if employment in PRESCREEN_EMPLOYMENT:
            return f"employment {employment}"
        return None

    def unavailable(self, player_id: str) -> str | None:
        """Why a watch story about him is moot now — a reserve list, released, retired, unsigned."""
        board = self.board.get(player_id) or {}
        code = board.get("current_status")
        if code in PRESCREEN_ROSTER_CODES:
            return f"roster status {code}"
        employment = board.get("employment_status")
        if employment in PRESCREEN_EMPLOYMENT:
            return f"employment {employment}"
        return None

    def current(self, player_id: str, family: str) -> bool:
        """His evidence is current and he is available to act on; counts the refusals."""
        lines = self.facts.lines.get(player_id, {})
        if not lines:
            return False
        if self.facts.missed_after(player_id, max(lines)) > 0:
            self.suppressed[(family, "missed_latest_game")] += 1
            return False
        if self.unavailable(player_id) is not None:
            self.suppressed[(family, "subject_unavailable")] += 1
            return False
        return True

    def upcoming(self, player_id: str) -> Mapping[str, Any] | None:
        """His target-week projection when its game is still ahead of the build, else None."""
        record = self.weekly.get(player_id)
        if record is None or record.get("game_state") != "upcoming":
            return None
        game = record.get("game") or {}
        kickoff = game.get("kickoff_utc")
        if not kickoff or parse_utc(str(kickoff)) <= self.generated_at:
            return None
        return record

    def team_on_bye(self, team: str | None) -> bool:
        """His team has no game in the target week (its next game is a later week)."""
        if team is None or self.target_week is None:
            return False
        matchup = self.matchups.get(team)
        return matchup is not None and int(matchup.get("week") or 0) != self.target_week

    def lines_time(self, team: str | None) -> str | None:
        matchup = self.matchups.get(team or "") or {}
        value = matchup.get("lines_retrieved_at_utc")
        return str(value) if value else None

    def report_final(self, team: str | None) -> bool | None:
        record = self.team_context.get(team or "")
        if record is None:
            return None
        lineup = record.get("lineup") or {}
        return bool(lineup.get("report_final")) if lineup.get("report_available") else None

    def week_source_times(self, player_id: str, team: str | None) -> dict[str, Any]:
        return {
            "espn_observed_at_utc": self.espn_time(player_id),
            "lines_retrieved_at_utc": self.lines_time(team),
            "injury_report_final": self.report_final(team),
        }


# ------------------------------------------------------------------------------- helpers


def _digits(player_id: str) -> str:
    return parse_player_id(player_id)[1].lower()


def _rounded(value: float | None, digits: int) -> float | None:
    return None if value is None else round(float(value), digits)


def _units(value: float, digits: int) -> int:
    """A rounded value in integer units of its published precision: exact comparisons."""
    return int(round(round(float(value), digits) * 10**digits))


def _share_of(lines: Sequence[Line], metric: str) -> float | None:
    numerator: Callable[[Line], float]
    denominator: Callable[[Line], float | None]
    if metric == "carry_share":
        numerator, denominator = (lambda line: line.carries), (lambda line: line.team_carries)
    elif metric == "pass_share":
        numerator, denominator = (
            (lambda line: line.pass_attempts),
            (lambda line: line.team_pass_attempts),
        )
    else:
        numerator, denominator = (lambda line: line.targets), (lambda line: line.team_targets)
    got = pooled(lines, numerator, denominator)
    return None if got is None else got[0] / got[1]


def _mean_snap(lines: Sequence[Line]) -> float | None:
    values = [line.snap_share for line in lines]
    if not values or any(value is None for value in values):
        return None
    return sum(float(value or 0.0) for value in values) / len(values)


def _per_game(total: float, games: int) -> float:
    return total / games if games else 0.0


def _predicate(rule: str, label: str, value: Any, threshold: Any) -> dict[str, Any]:
    return {"rule": rule, "label": label, "value": value, "threshold": threshold, "passed": True}


def _metric_value(line: Line, metric: str) -> float | None:
    if metric == "snap_share":
        return line.snap_share
    if metric == "pass_attempts":
        return None
    return _share_of([line], metric)


def _weekly_ranks(facts: SeasonFacts, position: str, preset: str) -> dict[int, dict[str, int]]:
    """``week -> player -> weekly positional rank`` over every player who appeared that week.

    recent_form_v1's ``span_ranks`` definition: competition rank of points in hundredths.
    """
    by_week: dict[int, dict[str, int]] = {}
    for player_id, lines in facts.lines.items():
        if facts.positions.get(player_id) != position:
            continue
        for week, line in lines.items():
            by_week.setdefault(week, {})[player_id] = _units(line.points[preset], 2)
    return {
        week: {pid: competition_rank_of(values, pid) or 0 for pid in values}
        for week, values in by_week.items()
    }


def _strip(
    ctx: Context,
    player_id: str,
    position: str,
    *,
    share_metric: str | None,
    ranks: Mapping[int, Mapping[str, int]] | None = None,
) -> list[dict[str, Any]]:
    """The season's weeks for a ``week_strip``: played weeks carry numbers, B and D are marks."""
    out: list[dict[str, Any]] = []
    for week in ctx.facts.weeks():
        line = ctx.facts.lines.get(player_id, {}).get(week)
        share = None if line is None or share_metric is None else _metric_value(line, share_metric)
        rank = None
        if line is not None and ranks is not None:
            rank = ranks.get(week, {}).get(player_id)
        out.append(
            {
                "week": week,
                "status": ctx.facts.status(player_id, week),
                "in_window": week in ctx.window,
                "points": None if line is None else round(line.points[ctx.preset], 2),
                "td_points": None if line is None else round(line.td_points[ctx.preset], 2),
                "opportunity": None if line is None else round(line.opportunities(position), 1),
                "share": _rounded(share, 3),
                "rank": rank,
            },
        )
    return out


def _roster_order(evidence: Mapping[str, Any]) -> tuple[int, float]:
    """Most-rostered first, unknown readings last (an unknown is never read as 0%)."""
    rostered = evidence.get("espn_rostered")
    return (0, -float(rostered)) if rostered is not None else (1, 0.0)


def _discovery_order(ctx: Context, player_id: str) -> tuple[int, float]:
    """Least-rostered on ESPN first, unknown readings last (never read as 0%)."""
    rostered, _ = ctx.espn_reading(player_id)
    return (0, float(rostered)) if rostered is not None else (1, 0.0)


def _team_games(facts: SeasonFacts, team: str, weeks: Sequence[int]) -> list[int]:
    return [week for week in weeks if team in facts.scheduled.get(week, set())]


# ================================================================== volume_vs_results


def detect_volume(ctx: Context) -> list[Draft]:
    """Production lagging an intact workload (``lagging``), and a shrinking role (``shrinking``).

    Cohort: every player at the position with ``min_window_games`` appearances in the window.
    Workload rank: opportunities a game, in tenths. Production rank: points a game, in
    hundredths. Both are competition ranks over the same cohort, so their difference in places
    compares two orderings of one population — never a rank against a total.
    """
    rule, facts, preset = ctx.rule, ctx.facts, ctx.preset
    drafts: list[Draft] = []
    for position in rule.volume_positions:
        cohort: dict[str, list[Line]] = {}
        for player_id, by_week in facts.lines.items():
            if facts.positions.get(player_id) != position:
                continue
            games = [by_week[week] for week in ctx.window if week in by_week]
            if len(games) >= rule.min_window_games:
                cohort[player_id] = games
        if not cohort:
            continue
        workload = {
            pid: _units(_per_game(sum(g.opportunities(position) for g in games), len(games)), 1)
            for pid, games in cohort.items()
        }
        production = {
            pid: _units(_per_game(sum(g.points[preset] for g in games), len(games)), 2)
            for pid, games in cohort.items()
        }
        rates = [
            sum(g.yards(position) for g in games) / total
            for games in cohort.values()
            if (total := sum(g.opportunities(position) for g in games)) > 0
        ]
        cohort_median = round(median(rates), 1) if rates else None
        for player_id, games in sorted(cohort.items()):
            if player_id not in ctx.subjects:
                continue
            baseline = facts.played(player_id, ctx.baseline)
            if len(baseline) < rule.min_baseline_games:
                continue
            evidence = _volume_evidence(
                ctx,
                player_id,
                position,
                games,
                baseline,
                workload_rank=competition_rank_of(workload, player_id) or 0,
                production_rank=competition_rank_of(production, player_id) or 0,
                cohort_size=len(cohort),
                cohort_median=cohort_median,
            )
            found = [
                draft
                for build in (_lagging, _shrinking)
                if (draft := build(ctx, player_id, position, evidence)) is not None
            ]
            # Currency is checked once he qualifies, so the count is of stories withheld.
            if found and ctx.current(player_id, "volume_vs_results"):
                drafts.extend(found)
    return drafts


def _volume_evidence(
    ctx: Context,
    player_id: str,
    position: str,
    games: Sequence[Line],
    baseline: Sequence[Line],
    *,
    workload_rank: int,
    production_rank: int,
    cohort_size: int,
    cohort_median: float | None,
) -> dict[str, Any]:
    preset, facts, rule = ctx.preset, ctx.facts, ctx.rule
    share_metric = rule.share_metric[position]
    opportunities = sum(g.opportunities(position) for g in games)
    points = sum(g.points[preset] for g in games)
    td_points = sum(g.td_points[preset] for g in games)
    numerator = (
        (lambda line: line.carries)
        if share_metric == "carry_share"
        else (lambda line: line.targets)
    )
    denominator = (
        (lambda line: line.team_carries)
        if share_metric == "carry_share"
        else (lambda line: line.team_targets)
    )
    share = pooled(games, numerator, denominator)
    red_zone = [g.red_zone(position) for g in games]
    team_rz: int | None = None
    if facts.red_zone_available and all(value is not None for value in red_zone):
        team_rz = 0
        for g in games:
            totals = facts.team_weeks.get((g.week, g.team or ""))
            if totals is not None:
                team_rz += totals.red_zone_targets + (
                    totals.red_zone_carries if position == "RB" else 0
                )
    rostered, state = ctx.espn_reading(player_id)
    yards = sum(g.yards(position) for g in games)
    return {
        "name": ctx.name(player_id),
        "position": position,
        "team": games[-1].team,
        "window_label": ctx.window_dict["label"],
        "opportunity_label": "carries + targets" if position == "RB" else "targets",
        "window_games": len(games),
        "baseline_games": len(baseline),
        "min_window_games": rule.min_window_games,
        "min_baseline_games": rule.min_baseline_games,
        "window_opportunities": round(opportunities, 1),
        "window_opportunities_per_game": round(_per_game(opportunities, len(games)), 1),
        "baseline_opportunities_per_game": round(
            _per_game(sum(g.opportunities(position) for g in baseline), len(baseline)),
            1,
        ),
        "workload_rank": workload_rank,
        "production_rank": production_rank,
        "cohort_size": cohort_size,
        "band": rule.bands[position],
        "gap_places": production_rank - workload_rank,
        "required_gap_places": rule.volume_gap_places[position],
        "hold_percent": rule.volume_hold_percent,
        "window_points": round(points, 2),
        "window_points_per_game": round(_per_game(points, len(games)), 2),
        "baseline_points_per_game": round(
            _per_game(sum(g.points[preset] for g in baseline), len(baseline)),
            2,
        ),
        "window_td_points": round(td_points, 2),
        "window_touchdowns": round(sum(g.touchdowns for g in games)),
        "share_metric": share_metric,
        "window_share": None if share is None else round(share[0] / share[1], 3),
        "window_share_numerator": None if share is None else round(share[0], 1),
        "window_share_denominator": None if share is None else round(share[1], 1),
        "baseline_share": _rounded(_share_of(baseline, share_metric), 3),
        "role_step": rule.role_step[position],
        "role_floor": rule.role_floor[position],
        "window_yards": round(yards, 1),
        "yards_per_opportunity": round(yards / opportunities, 1) if opportunities > 0 else None,
        "cohort_median_yards_per_opportunity": cohort_median,
        "red_zone_opportunities": (
            sum(int(value or 0) for value in red_zone) if team_rz is not None else None
        ),
        "team_red_zone_opportunities": team_rz,
        "snap_share_window": _rounded(_mean_snap(games), 3),
        "snap_share_baseline": _rounded(_mean_snap(baseline), 3),
        "espn_rostered": rostered,
        "espn_state": state,
    }


def _volume_draft(
    ctx: Context,
    player_id: str,
    position: str,
    evidence: dict[str, Any],
    *,
    variant: str,
    order: tuple[Any, ...],
    qualification: list[dict[str, Any]],
) -> Draft:
    share_metric = evidence["share_metric"]
    sources = [*BASE_SOURCES]
    if variant == "lagging" and evidence["team_red_zone_opportunities"] is not None:
        sources.append("nflverse_pbp")
    if evidence["espn_rostered"] is not None:
        sources.append(ESPN_SOURCE)
    return Draft(
        family="volume_vs_results",
        variant=variant,
        horizon="role_watch",
        nature="thesis",
        player_id=player_id,
        position=position,
        team=evidence["team"],
        subject=_digits(player_id),
        order=order,
        evidence=evidence,
        chart={
            "type": "week_strip",
            "weeks": _strip(ctx, player_id, position, share_metric=share_metric),
            "opportunity_label": "Carries + targets" if position == "RB" else "Targets",
            "share_label": "Carry share" if share_metric == "carry_share" else "Target share",
            "band": None,
        },
        qualification=qualification,
        sources=sources,
        window=ctx.window_dict,
        source_times={"espn_observed_at_utc": ctx.espn_time(player_id)},
    )


def _sample_predicates(ctx: Context, e: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [
        _predicate(
            "window_games",
            f"Games in {e['window_label']}",
            e["window_games"],
            ctx.rule.min_window_games,
        ),
        _predicate(
            "baseline_games",
            "Games before the window",
            e["baseline_games"],
            ctx.rule.min_baseline_games,
        ),
    ]


def _lagging(ctx: Context, player_id: str, position: str, e: dict[str, Any]) -> Draft | None:
    rule = ctx.rule
    band = rule.bands[position]
    if e["workload_rank"] > band:
        return None
    window_units = _units(e["window_opportunities_per_game"], 1)
    baseline_units = _units(e["baseline_opportunities_per_game"], 1)
    if 100 * window_units < rule.volume_hold_percent * baseline_units:
        return None
    gap = rule.volume_gap_places[position]
    if e["gap_places"] < gap:
        return None
    unit = "Opportunities" if position == "RB" else "Targets"
    qualification = [
        *_sample_predicates(ctx, e),
        _predicate(
            "workload_rank",
            f"{unit} a game, rank among {e['cohort_size']} {position}s",
            e["workload_rank"],
            band,
        ),
        _predicate(
            "workload_holds",
            f"{unit} a game, at least {rule.volume_hold_percent}% of the earlier rate",
            e["window_opportunities_per_game"],
            round(e["baseline_opportunities_per_game"] * rule.volume_hold_percent / 100, 2),
        ),
        _predicate(
            "production_gap",
            "Points-a-game rank minus workload rank, in places",
            e["gap_places"],
            gap,
        ),
    ]
    return _volume_draft(
        ctx,
        player_id,
        position,
        e,
        variant="lagging",
        order=(*_roster_order(e), -e["gap_places"], player_id),
        qualification=qualification,
    )


def _shrinking(ctx: Context, player_id: str, position: str, e: dict[str, Any]) -> Draft | None:
    before, now = e["baseline_share"], e["window_share"]
    if before is None or now is None:
        return None
    floor, step = ctx.rule.role_floor[position], ctx.rule.role_step[position]
    if _units(before, 3) < _units(floor, 3):
        return None
    drop = _units(before, 3) - _units(now, 3)
    if drop < _units(step, 3):
        return None
    qualification = [
        *_sample_predicates(ctx, e),
        _predicate("baseline_role", "Share before the window, at least", before, floor),
        _predicate("share_drop", "Share fell by at least", round(drop / 1000, 3), step),
    ]
    return _volume_draft(
        ctx,
        player_id,
        position,
        e,
        variant="shrinking",
        order=(*_roster_order(e), -drop, player_id),
        qualification=qualification,
    )


# ======================================================================= weekly_upside


def detect_upside(ctx: Context) -> list[Draft]:
    """Lower-rostered players with a confirmed role and a strong weekly ceiling.

    Eligible: an upcoming target-week game after the build, an observed ESPN reading below the
    widest ceiling, ``breakout_v1``'s role confirmation over his latest two appearances (the
    latest inside the window, no missed team game since), and the build-time pre-screen.
    Ordered within position by P90, then P50, then id. Published when he is among the first
    ``upside_per_position`` under any ceiling; the adds feed is deliberately not a gate.
    """
    rule = ctx.rule
    if ctx.espn is None or not ctx.weekly:
        return []
    widest = max(rule.upside_ceilings)
    pool: dict[str, list[dict[str, Any]]] = {}
    for player_id in sorted(ctx.subjects):
        position = ctx.position(player_id)
        if position is None:
            continue
        record = ctx.upcoming(player_id)
        if record is None or not record.get("quantiles"):
            continue
        rostered, _state = ctx.espn_reading(player_id)
        if rostered is None or rostered >= widest:
            continue
        games = ctx.facts.games.get(player_id, {})
        played = sorted(games)
        if len(played) < rule.upside_role_games:
            continue
        latest = played[-rule.upside_role_games :]
        if latest[-1] < ctx.window[0] or ctx.facts.missed_after(player_id, latest[-1]) > 0:
            continue
        used = [games[week] for week in latest]
        prior = [games[week] for week in played[: -rule.upside_role_games]]
        verdict, readings = _role_check(position, used, prior, BREAKOUT_RULE)
        if verdict != "pass":
            continue
        refused = ctx.prescreen(player_id)
        if refused is not None:
            ctx.suppressed[("weekly_upside", "prescreen")] += 1
            continue
        passed = next(reading for reading in readings if reading["passed"] is not None)
        pool.setdefault(position, []).append(
            {
                "player_id": player_id,
                "record": record,
                "rostered": rostered,
                "reading": passed,
                "weeks": latest,
            },
        )

    drafts: list[Draft] = []
    for position, entries in sorted(pool.items()):
        entries.sort(
            key=lambda entry: (
                -float(entry["record"]["quantiles"]["q90"]),
                -float(entry["record"]["quantiles"]["q50"]),
                entry["player_id"],
            ),
        )
        ranks: dict[str, dict[str, int | None]] = {entry["player_id"]: {} for entry in entries}
        counts: dict[str, int] = {}
        for ceiling in rule.upside_ceilings:
            below = [entry for entry in entries if entry["rostered"] < ceiling]
            counts[str(ceiling)] = len(below)
            for index, entry in enumerate(below, start=1):
                ranks[entry["player_id"]][str(ceiling)] = (
                    index if index <= rule.upside_per_position else None
                )
        for entry in entries:
            mine = {str(c): ranks[entry["player_id"]].get(str(c)) for c in rule.upside_ceilings}
            shown = [c for c in rule.upside_ceilings if mine[str(c)] is not None]
            if not shown:
                ctx.suppressed[("weekly_upside", "below_top_per_ceiling")] += 1
                continue
            drafts.append(_upside_draft(ctx, position, entry, mine, counts, ceiling=shown[0]))
    return drafts


def _upside_draft(
    ctx: Context,
    position: str,
    entry: Mapping[str, Any],
    ranks: Mapping[str, int | None],
    counts: Mapping[str, int],
    *,
    ceiling: int,
) -> Draft:
    rule = ctx.rule
    player_id, record = str(entry["player_id"]), entry["record"]
    quantiles = record["quantiles"]
    explanation = record.get("explanation") or {}
    game = record.get("game") or {}
    typical = {
        level: (explanation.get(level) or {}).get("typical") for level in ("q10", "q50", "q90")
    }
    terms = (explanation.get("q90") or {}).get("terms")
    delta = (
        None
        if typical["q90"] is None
        else round(float(quantiles["q90"]) - float(typical["q90"]), 2)
    )
    reading = entry["reading"]
    measure = next(m for m in BREAKOUT_RULE.measures[position] if m.metric == reading["metric"])
    bar = measure.substantial if reading["passed"] == "substantial" else measure.emerging
    team = record.get("team")
    evidence: dict[str, Any] = {
        "name": ctx.name(player_id),
        "position": position,
        "team": team,
        "opponent": game.get("opponent"),
        "home_away": game.get("home_away"),
        "kickoff_utc": game.get("kickoff_utc"),
        "target_week": record.get("target_week"),
        "q10": round(float(quantiles["q10"]), 2),
        "q50": round(float(quantiles["q50"]), 2),
        "q90": round(float(quantiles["q90"]), 2),
        "typical_q10": _rounded(typical["q10"], 2),
        "typical_q50": _rounded(typical["q50"], 2),
        "typical_q90": _rounded(typical["q90"], 2),
        "matchup_delta_q90": delta,
        "terms_q90": None if terms is None else {k: round(float(v), 2) for k, v in terms.items()},
        "espn_rostered": entry["rostered"],
        "espn_state": "observed",
        "ceiling": ceiling,
        "ceiling_level": 90,
        "ceiling_rank": ranks[str(ceiling)],
        "eligible": counts[str(ceiling)],
        "ceiling_ranks": dict(ranks),
        "eligible_counts": dict(counts),
        "role_metric": reading["metric"],
        "role_level": reading["level"],
        "role_baseline": reading["baseline"],
        "role_passed": reading["passed"],
        "role_bar": bar,
        "role_games": rule.upside_role_games,
        "role_weeks": list(entry["weeks"]),
        "injury": record.get("injury"),
        "model_version": record.get("model_version"),
    }
    qualification = [
        _predicate(
            "game_upcoming",
            "Target-week kickoff after the build",
            game.get("kickoff_utc"),
            "after build",
        ),
        _predicate("espn_observed", "ESPN reading state", "observed", "observed"),
        _predicate("espn_below_ceiling", "ESPN rostered %, below", entry["rostered"], ceiling),
        _predicate(
            "role_confirmed",
            (
                f"{reading['metric'].replace('_', ' ')} over his last "
                f"{rule.upside_role_games} games ({reading['passed']})"
            ),
            reading["level"],
            bar,
        ),
        _predicate(
            "latest_current",
            "Latest appearance in the window, no missed game since",
            entry["weeks"][-1],
            ctx.window[0],
        ),
        _predicate(
            "prescreen",
            "Not Out/Doubtful, on a reserve list, released or unsigned",
            "clear",
            "clear",
        ),
        _predicate(
            "ceiling_rank",
            f"Ceiling rank among {position}s under {ceiling}%",
            ranks[str(ceiling)],
            rule.upside_per_position,
        ),
    ]
    return Draft(
        family="weekly_upside",
        variant="ceiling",
        horizon="this_week",
        nature="thesis",
        player_id=player_id,
        position=position,
        team=team,
        subject=_digits(player_id),
        order=(ranks.get("50") or 99, ranks.get("25") or 99, ranks.get("10") or 99, player_id),
        evidence=evidence,
        chart={
            "type": "interval",
            "q10": evidence["q10"],
            "q50": evidence["q50"],
            "q90": evidence["q90"],
            "typical_q10": evidence["typical_q10"],
            "typical_q50": evidence["typical_q50"],
            "typical_q90": evidence["typical_q90"],
        },
        qualification=qualification,
        sources=[WEEKLY_SOURCE, ESPN_SOURCE, *BASE_SOURCES],
        window=ctx.window_dict,
        kickoff_utc=game.get("kickoff_utc"),
        target_week=record.get("target_week"),
        source_times=ctx.week_source_times(player_id, team),
    )


# ================================================================ opportunity_opening


def _documented_absence(ctx: Context, player_id: str, team: str) -> tuple[str, str | None] | None:
    """``(reason, designation)`` when the target week's absence is documented, else None."""
    if ctx.target_week is None:
        return None
    context = ctx.team_context.get(team) or {}
    for entry in (context.get("lineup") or {}).get("listed") or ():
        if (
            entry.get("player_id") == player_id
            and entry.get("designation") in PRESCREEN_DESIGNATIONS
        ):
            designation = str(entry["designation"])
            return f"listed {designation} for week {ctx.target_week}", designation
    code = (ctx.board.get(player_id) or {}).get("current_status")
    if code in RESERVE_CODES:
        return "on a reserve list", None
    return None


def _recent_misses(facts: SeasonFacts, player_id: str, team: str) -> list[int]:
    """His team's latest games he missed, consecutively, ending at the cutoff (byes skipped)."""
    missed: list[int] = []
    for week in range(facts.last_week, facts.first_week - 1, -1):
        if team not in facts.scheduled.get(week, set()):
            continue
        if facts.status(player_id, week) != DID_NOT_PLAY:
            break
        missed.append(week)
    return sorted(missed)


def detect_opening(ctx: Context) -> list[Draft]:
    """A teammate with a substantial role is absent: observed redistribution or a prospect.

    ``prospective``: his absence for the target week is documented (the official report lists
    him Out or Doubtful, or he is on a reserve list). ``observed``: he missed his team's latest
    games and nothing documents the target week. Games without him are every team game he did
    not play this season; vacated work is never assigned to the next name on a list.
    """
    rule, facts = ctx.rule, ctx.facts
    drafts: list[Draft] = []
    for room, (positions, unit, metric) in OPENING_ROOMS.items():
        for absent in sorted(facts.lines):
            absent_position = ctx.position(absent)
            if absent_position not in positions:
                continue
            team = facts.teams_by_week(absent).get(facts.last_week)
            if team is None:
                continue
            team_lines = [line for line in facts.lines[absent].values() if line.team == team]
            if len(team_lines) < rule.absent_min_games:
                continue
            share = _share_of(team_lines, metric)
            if share is None or _units(share, 3) < _units(rule.absent_floor[metric], 3):
                continue
            documented = _documented_absence(ctx, absent, team)
            recent = _recent_misses(facts, absent, team)
            if documented is not None:
                variant, reason, designation = "prospective", documented[0], documented[1]
            elif recent and recent[0] >= ctx.window[0]:
                # Observed only while the change is new: an absence that began before the
                # window is an established role, which the role battles describe.
                variant = "observed"
                reason = "missed " + ", ".join(f"W{week}" for week in recent)
                designation = None
            else:
                continue
            draft = _opening_draft(
                ctx,
                room=room,
                positions=positions,
                unit=unit,
                metric=metric,
                absent=absent,
                absent_position=str(absent_position),
                team=team,
                team_lines=team_lines,
                share=share,
                variant=variant,
                reason=reason,
                designation=designation,
                recent=recent,
            )
            if draft is not None:
                drafts.append(draft)
    return drafts


def _opening_draft(
    ctx: Context,
    *,
    room: str,
    positions: tuple[str, ...],
    unit: str,
    metric: str,
    absent: str,
    absent_position: str,
    team: str,
    team_lines: Sequence[Line],
    share: float,
    variant: str,
    reason: str,
    designation: str | None,
    recent: Sequence[int],
) -> Draft | None:
    rule, facts = ctx.rule, ctx.facts
    absent_teams = facts.teams_by_week(absent)
    without_weeks = [
        week
        for week in facts.weeks()
        if facts.status(absent, week) == DID_NOT_PLAY and absent_teams.get(week) == team
    ]
    with_weeks = [line.week for line in team_lines]
    rows: list[dict[str, Any]] = []
    for candidate in sorted(ctx.subjects):
        position = ctx.position(candidate)
        if candidate == absent or position not in positions:
            continue
        if facts.teams_by_week(candidate).get(facts.last_week) != team:
            continue
        lines = facts.lines.get(candidate, {})

        def on_team(weeks: Sequence[int], lines: Mapping[int, Line] = lines) -> list[Line]:
            return [lines[week] for week in weeks if week in lines and lines[week].team == team]

        current = on_team(ctx.window)
        if not current:
            continue
        with_lines, without_lines = on_team(with_weeks), on_team(without_weeks)
        rows.append(
            {
                "player_id": candidate,
                "name": ctx.name(candidate),
                "position": str(position),
                "share_with": _rounded(_share_of(with_lines, metric), 3),
                "games_with": len(with_lines),
                "share_without": _rounded(_share_of(without_lines, metric), 3),
                "games_without": len(without_lines),
                "latest_share": _rounded(_share_of(current, metric), 3),
            },
        )
    eligible: list[tuple[float, dict[str, Any]]] = []
    for row in rows:
        position = row["position"]
        if variant == "observed":
            without, with_ = row["share_without"], row["share_with"]
            if row["games_without"] < 1 or without is None:
                continue
            if _units(without, 3) < _units(rule.role_floor[position], 3):
                continue
            if with_ is not None and _units(without, 3) - _units(with_, 3) < _units(
                rule.role_step[position], 3
            ):
                continue
            eligible.append((without, row))
        else:
            key = row["share_without"] if row["games_without"] else row["latest_share"]
            if key is None or _units(key, 3) < _units(NOTABLE_SHARE[metric], 3):
                continue
            eligible.append((key, row))
    eligible.sort(key=lambda item: (-item[0], item[1]["player_id"]))
    horizon = "role_watch"
    focal: dict[str, Any] | None = None
    record: Mapping[str, Any] | None = None
    for _, row in eligible:
        if variant == "prospective":
            if ctx.team_on_bye(team):
                horizon = "stash"
            else:
                horizon = "this_week"
                record = ctx.upcoming(row["player_id"])
                if record is None:
                    ctx.suppressed[("opportunity_opening", "game_not_upcoming")] += 1
                    continue
                if ctx.prescreen(row["player_id"]) is not None:
                    ctx.suppressed[("opportunity_opening", "prescreen")] += 1
                    continue
        focal = row
        break
    if focal is None:
        return None
    ordered = [focal] + sorted(
        (row for row in rows if row is not focal),
        key=lambda row: (
            -((row["share_without"] if row["games_without"] else row["latest_share"]) or 0.0),
            row["player_id"],
        ),
    )
    shown = ordered[: rule.opening_rows]
    absent_count = sum(
        line.targets if metric == "target_share" else line.carries for line in team_lines
    )
    focal_id = str(focal["player_id"])
    rostered, state = ctx.espn_reading(focal_id)
    game = (record or {}).get("game") or {}
    evidence: dict[str, Any] = {
        "name": focal["name"],
        "position": focal["position"],
        "team": team,
        "room": room,
        "metric": metric,
        "window_label": ctx.window_dict["label"],
        "absent_player_id": absent,
        "absent_name": ctx.name(absent),
        "absent_position": absent_position,
        "absent_share": round(share, 3),
        "absent_games": len(team_lines),
        "absent_per_game": round(absent_count / len(team_lines), 1),
        "absent_reason": reason,
        "absent_designation": designation,
        "absent_floor": rule.absent_floor[metric],
        "missed_weeks": list(recent),
        "games_without_weeks": without_weeks,
        "share_with": focal["share_with"],
        "games_with": focal["games_with"],
        "share_without": focal["share_without"],
        "games_without": focal["games_without"],
        "latest_share": focal["latest_share"],
        "role_step": rule.role_step[focal["position"]],
        "role_floor": rule.role_floor[focal["position"]],
        "notable_share": NOTABLE_SHARE[metric],
        "espn_rostered": rostered,
        "espn_state": state,
        "target_week": ctx.target_week if variant == "prospective" else None,
        "opponent": game.get("opponent"),
        "kickoff_utc": game.get("kickoff_utc") if horizon == "this_week" else None,
        "injury": (record or {}).get("injury") if horizon == "this_week" else None,
    }
    qualification = [
        _predicate(
            "absent_games",
            f"{evidence['absent_name']}'s games with {team}",
            len(team_lines),
            rule.absent_min_games,
        ),
        _predicate(
            "absent_role",
            f"{evidence['absent_name']}'s {metric.replace('_', ' ')}, at least",
            round(share, 3),
            rule.absent_floor[metric],
        ),
        _predicate(
            "absence",
            "Documented for the target week"
            if variant == "prospective"
            else "Missed his team's latest games",
            reason,
            "official report or reserve list" if variant == "prospective" else "at least 1",
        ),
    ]
    if variant == "observed":
        qualification.append(
            _predicate(
                "share_without",
                f"{focal['name']}'s share without him, at least",
                focal["share_without"],
                rule.role_floor[focal["position"]],
            ),
        )
        if focal["share_with"] is not None:
            qualification.append(
                _predicate(
                    "share_rise",
                    "Rise against his share with him, at least",
                    round(
                        (_units(focal["share_without"], 3) - _units(focal["share_with"], 3)) / 1000,
                        3,
                    ),
                    rule.role_step[focal["position"]],
                ),
            )
    else:
        qualification.append(
            _predicate(
                "next_share",
                f"{focal['name']}'s share (without him, else {evidence['window_label']}), at least",
                focal["share_without"] if focal["games_without"] else focal["latest_share"],
                NOTABLE_SHARE[metric],
            ),
        )
    sources = [*BASE_SOURCES]
    if variant == "prospective" and designation is not None:
        sources.append("nflverse_injuries")
    if horizon == "this_week":
        sources.append(WEEKLY_SOURCE)
    if rostered is not None:
        sources.append(ESPN_SOURCE)
    return Draft(
        family="opportunity_opening",
        variant=variant,
        horizon=horizon,
        nature="thesis",
        player_id=focal_id,
        position=str(focal["position"]),
        team=team,
        subject=_digits(absent),
        order=(-evidence["absent_per_game"], team, absent),
        evidence=evidence,
        chart={
            "type": "with_without",
            "metric": metric,
            "absent": {
                "player_id": absent,
                "name": evidence["absent_name"],
                "position": absent_position,
                "share": evidence["absent_share"],
                "games": evidence["absent_games"],
                "per_game": evidence["absent_per_game"],
                "reason": reason,
            },
            "rows": shown,
        },
        qualification=qualification,
        sources=sources,
        window=ctx.window_dict,
        kickoff_utc=evidence["kickoff_utc"],
        target_week=evidence["target_week"],
        source_times=ctx.week_source_times(focal_id, team),
    )


# ======================================================================== role_battle


def detect_roles(ctx: Context) -> list[Draft]:
    """A backfield or receiving room whose split of carries or targets changed materially.

    Shares here are of **the team's** carries or targets in its own games over the window (and
    before it), so a missed game lowers a share — the question is who gets the ball, not how
    busy each player was when he played. A riser needs two games on each side, a rise of at
    least ``role_step`` and a level of at least ``role_floor``. Identical in every preset.
    """
    rule, facts = ctx.rule, ctx.facts
    team_totals: dict[tuple[int, str], tuple[float, float]] = {}
    for by_week in facts.lines.values():
        for week, line in by_week.items():
            if line.team and line.team_targets is not None and line.team_carries is not None:
                team_totals[(week, line.team)] = (line.team_targets, line.team_carries)
    teams = sorted({team for _, team in team_totals})
    drafts: list[Draft] = []
    for team in teams:
        window_games = [w for w in _team_games(facts, team, ctx.window) if (w, team) in team_totals]
        baseline_games = [
            w for w in _team_games(facts, team, ctx.baseline) if (w, team) in team_totals
        ]
        if (
            len(window_games) < rule.min_window_games
            or len(baseline_games) < rule.min_baseline_games
        ):
            continue
        for room, (positions, unit, metric) in ROOMS.items():
            draft = _room_draft(
                ctx,
                team=team,
                room=room,
                positions=positions,
                unit=unit,
                metric=metric,
                window_games=window_games,
                baseline_games=baseline_games,
                team_totals=team_totals,
            )
            if draft is not None:
                drafts.append(draft)
    return drafts


def _room_draft(
    ctx: Context,
    *,
    team: str,
    room: str,
    positions: tuple[str, ...],
    unit: str,
    metric: str,
    window_games: Sequence[int],
    baseline_games: Sequence[int],
    team_totals: Mapping[tuple[int, str], tuple[float, float]],
) -> Draft | None:
    rule, facts = ctx.rule, ctx.facts
    index = 0 if unit == "targets" else 1
    team_count = round(sum(team_totals[(w, team)][index] for w in window_games))
    team_before = round(sum(team_totals[(w, team)][index] for w in baseline_games))
    if team_count <= 0 or team_before <= 0:
        return None
    team_rz: int | None = None
    team_i5: int | None = None
    if facts.red_zone_available:
        team_rz, team_i5 = 0, 0
        for week in window_games:
            totals = facts.team_weeks.get((week, team))
            if totals is None:
                continue
            team_rz += totals.red_zone_targets if unit == "targets" else totals.red_zone_carries
            team_i5 += (
                totals.inside_five_targets if unit == "targets" else totals.inside_five_carries
            )
    members: list[dict[str, Any]] = []
    for player_id in sorted(ctx.subjects):
        position = ctx.position(player_id)
        if position not in positions:
            continue
        lines = facts.lines.get(player_id, {})
        now = [lines[w] for w in window_games if w in lines and lines[w].team == team]
        before = [lines[w] for w in baseline_games if w in lines and lines[w].team == team]
        if not now and not before:
            continue
        count = round(sum(line.targets if unit == "targets" else line.carries for line in now))
        count_before = round(
            sum(line.targets if unit == "targets" else line.carries for line in before)
        )
        red_zone = inside_five = None
        if facts.red_zone_available:
            red_zone = sum(
                int((line.red_zone_targets if unit == "targets" else line.red_zone_carries) or 0)
                for line in now
            )
            inside_five = sum(
                int(
                    (line.inside_five_targets if unit == "targets" else line.inside_five_carries)
                    or 0
                )
                for line in now
            )
        members.append(
            {
                "player_id": player_id,
                "name": ctx.name(player_id),
                "position": str(position),
                "window_games": len(now),
                "baseline_games": len(before),
                "snap_share": _rounded(_mean_snap(now), 3),
                "snap_share_baseline": _rounded(_mean_snap(before), 3),
                "count": count,
                "share": round(count / team_count, 3),
                "share_baseline": round(count_before / team_before, 3),
                "red_zone": red_zone,
                "inside_five": inside_five,
            },
        )
    risers = []
    for member in members:
        position = member["position"]
        if (
            member["window_games"] < rule.min_window_games
            or member["baseline_games"] < rule.min_baseline_games
        ):
            continue
        rise = _units(member["share"], 3) - _units(member["share_baseline"], 3)
        if rise < _units(rule.role_step[position], 3):
            continue
        if _units(member["share"], 3) < _units(rule.role_floor[position], 3):
            continue
        if not ctx.current(str(member["player_id"]), "role_battle"):
            continue
        risers.append((rise, member))
    if not risers:
        return None
    risers.sort(key=lambda item: (-item[0], item[1]["player_id"]))
    rise, focal = risers[0]
    rows = sorted(members, key=lambda member: (-member["share"], member["player_id"]))[
        : rule.room_rows
    ]
    if focal not in rows:
        rows = [*rows[:-1], focal]
    if len(rows) < 2:
        return None
    others = [member for member in rows if member is not focal]
    other = others[0] if others else None
    absent_member = next(
        (
            member
            for member in sorted(members, key=lambda m: (-m["share_baseline"], m["player_id"]))
            if member is not focal
            and _units(member["share_baseline"], 3)
            >= _units(rule.role_floor[member["position"]], 3)
            and member["window_games"] < len(window_games)
        ),
        None,
    )
    window = ctx.window_dict
    evidence: dict[str, Any] = {
        "name": focal["name"],
        "position": focal["position"],
        "team": team,
        "room": room,
        "metric": unit,
        "window_label": window["label"],
        "team_count": team_count,
        "team_count_baseline": team_before,
        "team_games": len(window_games),
        "team_games_baseline": len(baseline_games),
        "riser_count": focal["count"],
        "riser_share": focal["share"],
        "riser_share_baseline": focal["share_baseline"],
        "riser_increase": round(rise / 1000, 3),
        "riser_games": focal["window_games"],
        "riser_snap_share": focal["snap_share"],
        "role_step": rule.role_step[focal["position"]],
        "role_floor": rule.role_floor[focal["position"]],
        "other_name": None if other is None else other["name"],
        "other_count": None if other is None else other["count"],
        "absent_member": None if absent_member is None else absent_member["name"],
        "absent_member_games": None if absent_member is None else absent_member["window_games"],
        "red_zone_available": facts.red_zone_available,
    }
    qualification = [
        _predicate(
            "team_games",
            f"{team} games in {window['label']}",
            len(window_games),
            rule.min_window_games,
        ),
        _predicate(
            "riser_games",
            f"{focal['name']}'s games in {window['label']} and before",
            min(focal["window_games"], focal["baseline_games"]),
            rule.min_window_games,
        ),
        _predicate(
            "share_rise",
            f"Rise in share of {team} {unit}, at least",
            evidence["riser_increase"],
            rule.role_step[focal["position"]],
        ),
        _predicate(
            "share_level",
            f"Share of {team} {unit} in {window['label']}, at least",
            focal["share"],
            rule.role_floor[focal["position"]],
        ),
    ]
    sources = [*BASE_SOURCES]
    if facts.red_zone_available:
        sources.append("nflverse_pbp")
    return Draft(
        family="role_battle",
        variant=room,
        horizon="role_watch",
        nature="fact",
        player_id=str(focal["player_id"]),
        position=str(focal["position"]),
        team=team,
        subject=f"{team.lower()}-{room}",
        order=(-rise, team, room),
        evidence=evidence,
        chart={
            "type": "room",
            "room": room,
            "metric": unit,
            "team_count": team_count,
            "team_games": len(window_games),
            "team_red_zone": team_rz,
            "team_inside_five": team_i5,
            "rows": rows,
        },
        qualification=qualification,
        sources=sources,
        window=window,
        scoring_dependent=False,
    )


# ======================================================================== streak_watch


def detect_streak(ctx: Context) -> list[Draft]:
    """Breakouts (recent form's own categories), hot streaks without the role, quiet growth.

    ``breakout``: ``breakout_v1``'s Takeover or Sneaking over the Last-3 window, as published.
    ``production_without_role``: ``breakout_v1``'s Eyebrow with ``role_not_confirmed`` — two or
    more strong weeks whose role measures failed. ``quiet_role_growth``: a role measure grew by
    ``breakout_v1``'s increase to at least its emerging level while his window rank is still
    outside the band. Nothing here re-decides a category.
    """
    rule, facts = ctx.rule, ctx.facts
    key = str(rule.window_weeks)
    ranks_cache: dict[str, dict[int, dict[str, int]]] = {}
    drafts: list[Draft] = []
    for player_id in sorted(ctx.subjects):
        record = ctx.recent.get(player_id)
        position = ctx.position(player_id)
        if record is None or position is None or not ctx.facts.lines.get(player_id):
            continue
        window = (record.get("windows") or {}).get(key) or {}
        breakout = window.get("breakout") or {}
        category, reason = breakout.get("category"), breakout.get("reason")
        games = facts.played(player_id, ctx.window)
        baseline = facts.played(player_id, ctx.baseline)
        variant: str | None = None
        measure: dict[str, Any] | None = None
        growth: float | None = None
        if category in ("takeover", "sneaking"):
            variant = "breakout"
            measure = next((r for r in breakout.get("role") or () if r.get("passed")), None)
        elif category == "eyebrow" and reason == "role_not_confirmed":
            variant = "production_without_role"
            measure = next(iter(breakout.get("role") or ()), None)
        elif (
            position != "QB"
            and len(games) >= rule.min_window_games
            and len(baseline) >= rule.min_baseline_games
            and window.get("rank") is not None
            and int(window["rank"]) > rule.bands[position]
        ):
            recent_games = facts.recent_games(player_id, ctx.window)
            prior_games = facts.recent_games(player_id, ctx.baseline)
            best: tuple[int, dict[str, Any]] | None = None
            for m in BREAKOUT_RULE.measures[position]:
                if m.emerging is None or m.increase is None:
                    continue
                reading = _role_reading(m, recent_games, prior_games, BREAKOUT_RULE)
                level, base = reading["level"], reading["baseline"]
                if level is None or base is None:
                    continue
                step = _units(level, 3) - _units(base, 3)
                grew = step >= _units(m.increase, 3) and _units(level, 3) >= _units(m.emerging, 3)
                if grew and (best is None or step > best[0]):
                    best = (step, {**reading, "emerging": m.emerging, "increase": m.increase})
            if best is not None:
                variant, measure, growth = "quiet_role_growth", best[1], best[0] / 1000
        if variant is None:
            continue
        # breakout_v1 already refuses a run that ended in a missed game; quiet growth applies
        # the same currency rule here, and every variant skips a player who cannot be acted on.
        if not ctx.current(player_id, "streak_watch"):
            continue
        if position not in ranks_cache:
            ranks_cache[position] = _weekly_ranks(facts, position, ctx.preset)
        drafts.append(
            _streak_draft(
                ctx,
                player_id,
                position,
                variant=variant,
                record=record,
                window=window,
                breakout=breakout,
                measure=measure,
                growth=growth,
                games=games,
                ranks=ranks_cache[position],
            ),
        )
    return drafts


def _streak_draft(
    ctx: Context,
    player_id: str,
    position: str,
    *,
    variant: str,
    record: Mapping[str, Any],
    window: Mapping[str, Any],
    breakout: Mapping[str, Any],
    measure: Mapping[str, Any] | None,
    growth: float | None,
    games: Sequence[Line],
    ranks: Mapping[int, Mapping[str, int]],
) -> Draft:
    rule, preset = ctx.rule, ctx.preset
    points = sum(line.points[preset] for line in games)
    td_points = sum(line.td_points[preset] for line in games)
    metric = None if measure is None else str(measure.get("metric"))
    window_info = ctx.window_dict
    band = rule.bands[position]
    evidence: dict[str, Any] = {
        "name": ctx.name(player_id),
        "position": position,
        "team": games[-1].team if games else None,
        "window_label": window_info["label"],
        "category": breakout.get("category"),
        "reason": breakout.get("reason"),
        "window_rank": window.get("rank"),
        "season_rank": record.get("season_rank"),
        "band": band,
        "streak": breakout.get("streak"),
        "window_games": len(games),
        "window_points": round(points, 2),
        "window_points_per_game": round(_per_game(points, len(games)), 2),
        "window_td_points": round(td_points, 2),
        "td_share": round(100 * td_points / points) if points > 0 else None,
        "td_led_percent": rule.td_led_percent,
        "measure": metric,
        "level": None if measure is None else measure.get("level"),
        "baseline": None if measure is None else measure.get("baseline"),
        "growth": None if growth is None else round(growth, 3),
        "growth_bar": None if measure is None else measure.get("increase"),
        "role": breakout.get("role"),
    }
    if variant == "breakout":
        qualification = [
            _predicate(
                "category",
                f"breakout_v1 over {window_info['label']}",
                breakout.get("category"),
                "takeover or sneaking",
            ),
            _predicate("streak", f"Consecutive top-{band} weeks", breakout.get("streak"), 2),
        ]
        # Discovery first: Takeover before Sneaking, then the least-rostered on ESPN (unknown
        # last), then the better window rank.
        order: tuple[Any, ...] = (
            0 if breakout.get("category") == "takeover" else 1,
            *_discovery_order(ctx, player_id),
            window.get("rank") or 999,
            player_id,
        )
        nature = "fact"
    elif variant == "production_without_role":
        qualification = [
            _predicate(
                "category", f"breakout_v1 over {window_info['label']}", "eyebrow", "eyebrow"
            ),
            _predicate(
                "role_not_confirmed",
                "Strong weeks without a confirmed role",
                breakout.get("streak"),
                2,
            ),
        ]
        order = (
            -(breakout.get("streak") or 0),
            *_discovery_order(ctx, player_id),
            window.get("rank") or 999,
            player_id,
        )
        nature = "thesis"
    else:
        assert measure is not None and growth is not None
        qualification = [
            _predicate(
                "window_games",
                f"Games in {window_info['label']}",
                len(games),
                rule.min_window_games,
            ),
            _predicate(
                "baseline_games",
                "Games before the window",
                len(ctx.facts.played(player_id, ctx.baseline)),
                rule.min_baseline_games,
            ),
            _predicate(
                "role_growth",
                f"{metric.replace('_', ' ') if metric else ''} rise, at least",
                round(growth, 3),
                measure.get("increase"),
            ),
            _predicate(
                "role_level",
                "Level in the window, at least",
                measure.get("level"),
                measure.get("emerging"),
            ),
            _predicate(
                "outside_band",
                f"Points rank over {window_info['label']}, worse than",
                window.get("rank"),
                band,
            ),
        ]
        order = (*_discovery_order(ctx, player_id), -growth, player_id)
        nature = "thesis"
    chart_metric = metric if metric in ("target_share", "carry_share", "snap_share") else None
    share_label = {
        "target_share": "Target share",
        "carry_share": "Carry share",
        "snap_share": "Snap share",
    }.get(chart_metric or "")
    return Draft(
        family="streak_watch",
        variant=variant,
        horizon="role_watch",
        nature=nature,
        player_id=player_id,
        position=position,
        team=evidence["team"],
        subject=_digits(player_id),
        order=order,
        evidence=evidence,
        chart={
            "type": "week_strip",
            "weeks": _strip(ctx, player_id, position, share_metric=chart_metric, ranks=ranks),
            "opportunity_label": "Carries + targets"
            if position == "RB"
            else ("Pass attempts" if position == "QB" else "Targets"),
            "share_label": share_label,
            "band": band,
        },
        qualification=qualification,
        sources=[*BASE_SOURCES],
        window=window_info,
    )


# ==================================================================== pace_perspective


def detect_pace(ctx: Context) -> list[Draft]:
    """Per-game output a season total hides, and strong per-game output at low roster share.

    The per-game cohort is every player at the position with ``pace_min_games`` appearances in
    season actuals (the published points and games); ranks compare points a game with points a
    game, and the total rank is season actuals' own. Pace is arithmetic, labelled as such.
    """
    rule, facts = ctx.rule, ctx.facts
    drafts: list[Draft] = []
    by_position: dict[str, dict[str, int]] = {}
    for player_id, record in ctx.actuals.items():
        games = int(record.get("games_played") or 0)
        if games < rule.pace_min_games or record.get("points_per_game") is None:
            continue
        by_position.setdefault(str(record["position"]), {})[player_id] = _units(
            float(record["points"]) / games,
            2,
        )
    for position, values in sorted(by_position.items()):
        band = rule.bands.get(position)
        if band is None:
            continue
        for player_id in sorted(values):
            if player_id not in ctx.subjects:
                continue
            record = ctx.actuals[player_id]
            ppg_rank = competition_rank_of(values, player_id) or 0
            if ppg_rank > band:
                continue
            if ctx.unavailable(player_id) is not None:
                ctx.suppressed[("pace_perspective", "subject_unavailable")] += 1
                continue
            games = int(record["games_played"])
            teams = facts.teams_by_week(player_id)
            team_games = sum(
                1 for week in facts.weeks() if teams.get(week) in facts.scheduled.get(week, set())
            )
            total_rank = record.get("season_position_rank")
            rostered, state = ctx.espn_reading(player_id)
            ppg = float(record["points"]) / games
            evidence: dict[str, Any] = {
                "name": ctx.name(player_id),
                "position": position,
                "team": teams.get(facts.last_week),
                "games": games,
                "team_games": max(team_games, games),
                "points": round(float(record["points"]), 2),
                "points_per_game": round(ppg, 2),
                "pace": round(ppg * rule.pace_games, 1),
                "pace_games": rule.pace_games,
                "ppg_rank": ppg_rank,
                "total_rank": total_rank,
                "cohort_size": len(values),
                "cohort_min_games": rule.pace_min_games,
                "band": band,
                "gap_places": None if total_rank is None else int(total_rank) - ppg_rank,
                "missed_games": max(team_games, games) - games,
                "required_gap_places": rule.pace_hidden_gap_places,
                "espn_rostered": rostered,
                "espn_state": state,
                "ceiling": rule.upside_default_ceiling,
            }
            base = [
                _predicate("games", "Games played, at least", games, rule.pace_min_games),
                _predicate(
                    "ppg_rank",
                    f"Points-a-game rank among {len(values)} {position}s",
                    ppg_rank,
                    band,
                ),
            ]
            if (
                total_rank is not None
                and int(total_rank) - ppg_rank >= rule.pace_hidden_gap_places
                and games < evidence["team_games"]
            ):
                drafts.append(
                    _pace_draft(
                        ctx,
                        player_id,
                        position,
                        evidence,
                        variant="per_game_hidden",
                        qualification=[
                            *base,
                            _predicate(
                                "hidden_gap",
                                "Total rank minus points-a-game rank, in places",
                                evidence["gap_places"],
                                rule.pace_hidden_gap_places,
                            ),
                            _predicate(
                                "missed_games",
                                "Team games missed, at least",
                                evidence["missed_games"],
                                1,
                            ),
                        ],
                    ),
                )
            if rostered is not None and rostered < rule.upside_default_ceiling:
                drafts.append(
                    _pace_draft(
                        ctx,
                        player_id,
                        position,
                        evidence,
                        variant="overlooked",
                        qualification=[
                            *base,
                            _predicate(
                                "espn_below",
                                "ESPN rostered %, below",
                                rostered,
                                rule.upside_default_ceiling,
                            ),
                        ],
                    ),
                )
    return drafts


def _pace_draft(
    ctx: Context,
    player_id: str,
    position: str,
    evidence: dict[str, Any],
    *,
    variant: str,
    qualification: list[dict[str, Any]],
) -> Draft:
    sources = [*BASE_SOURCES]
    if variant == "overlooked":
        sources.append(ESPN_SOURCE)
    return Draft(
        family="pace_perspective",
        variant=variant,
        horizon="season_view",
        nature="fact",
        player_id=player_id,
        position=position,
        team=evidence["team"],
        subject=_digits(player_id),
        order=(evidence["ppg_rank"], player_id),
        evidence=evidence,
        chart={
            "type": "stat_line",
            "games": evidence["games"],
            "team_games": evidence["team_games"],
            "points": evidence["points"],
            "points_per_game": evidence["points_per_game"],
            "pace_17": evidence["pace"],
            "ppg_rank": evidence["ppg_rank"],
            "total_rank": evidence["total_rank"],
            "cohort_size": evidence["cohort_size"],
            "cohort_min_games": evidence["cohort_min_games"],
        },
        qualification=qualification,
        sources=sources,
        window=None,
        source_times={"espn_observed_at_utc": ctx.espn_time(player_id)}
        if variant == "overlooked"
        else {},
    )


#: Every family's detector, by family name.
DETECTORS: Mapping[str, Callable[[Context], list[Draft]]] = {
    "weekly_upside": detect_upside,
    "opportunity_opening": detect_opening,
    "volume_vs_results": detect_volume,
    "streak_watch": detect_streak,
    "role_battle": detect_roles,
    "pace_perspective": detect_pace,
}

#: Kept for the validator and tests: the statuses a strip week may take.
STRIP_STATUSES = (PLAYED, "B", DID_NOT_PLAY)
