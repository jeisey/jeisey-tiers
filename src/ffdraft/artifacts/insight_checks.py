"""Validation of ``insights`` (ADR-116): every printed number is evidence, every chart adds up.

Independent of the builder: nothing here imports :mod:`ffdraft.insights` except its published
constants. The checks re-derive what a story prints from what it carries, and what it carries
from the artifacts beside it:

* **Text.** Every number in a headline, dek, fact, counterpoint or caveat is one of the story's
  own evidence, chart or window values in a published format (``insights.text_number_not_in_
  evidence``); no forbidden claim — routes, first reads, expected points, "due", confidence —
  appears (``insights.forbidden_claim``).
* **Identities.** Edition and window arithmetic, interval order, strip sums equal the window
  totals, a room's shares are its counts over the team's, pace is points a game × 17, every
  qualification predicate holds against its threshold (``insights.identity``).
* **Selection.** Lead ranks are 1..n ≤ 12; one story per player per preset; the per-team and
  per-family caps hold; a scoring-independent story is identical in every preset.
* **Reconciliation.** Weekly points equal the usage series and recent form's span; season
  totals and ranks equal season actuals; quantiles and kickoffs equal the weekly projections;
  roster shares equal ESPN's readings (``insights.disagrees_with_sources``).
* **Time.** A ``this_week`` story carries a kickoff after the build; nothing else does.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from ffdraft.contracts import QualityCheck
from ffdraft.timeutil import parse_utc

__all__ = [
    "insight_cross_checks",
    "insight_metadata_checks",
    "insight_record_checks",
    "printed_numbers",
]

_STAGE = "artifacts.insights"

#: The validator's own copy of ADR-116's published limits. It imports nothing from the builder
#: (which reaches the signal layer); ``tests/unit/test_insights.py`` pins these to
#: :mod:`ffdraft.insights.rules` so the two cannot drift.
FORBIDDEN_PHRASES: tuple[str, ...] = (
    "due",
    "due for",
    "regression",
    "unlucky",
    "luck",
    "xfp",
    "expected points",
    "expected fantasy",
    "over expected",
    "route",
    "first read",
    "first-read",
    "tprr",
    "per route",
    "coverage",
    "confidence",
    "guarantee",
    "lock",
    "boom score",
)
LEAD_MAX = 12
TEAM_CAP = 2
FAMILY_CAPS: Mapping[str, int] = {
    "weekly_upside": 3,
    "opportunity_opening": 2,
    "volume_vs_results": 3,
    "streak_watch": 2,
    "role_battle": 2,
    "pace_perspective": 1,
}
#: The ceiling-rank cut: a published per-ceiling rank is within the first three.
UPSIDE_PER_POSITION = 3
_NUMBER = re.compile(r"\d+(?:\.\d+)?")
_FORBIDDEN: list[re.Pattern[str]] = []
#: Text that names, rather than measures: P10/P50/P90 are levels, W5 a week label.
_LABELS = re.compile(r"\bP(?:10|50|90)\b|\bW\d+\b|breakout_v1|\b\d+\+")
_EPS = 0.0101


def _forbidden() -> list[re.Pattern[str]]:
    if not _FORBIDDEN:
        _FORBIDDEN.extend(
            re.compile(rf"\b{re.escape(phrase.strip())}\b", re.IGNORECASE)
            for phrase in FORBIDDEN_PHRASES
        )
    return _FORBIDDEN


def _fail(check_id: str, message: str, offenders: Sequence[str], expected: str) -> QualityCheck:
    return QualityCheck.fail(
        check_id,
        stage=_STAGE,
        message=message,
        observed="; ".join(offenders[:8]) + (" …" if len(offenders) > 8 else ""),
        expected=expected,
    )


def _leaves(value: Any) -> Iterable[float]:
    if isinstance(value, bool) or value is None:
        return
    if isinstance(value, int | float):
        yield float(value)
    elif isinstance(value, Mapping):
        for item in value.values():
            yield from _leaves(item)
    elif isinstance(value, list | tuple):
        for item in value:
            yield from _leaves(item)


def _formats(value: float) -> set[str]:
    out = {f"{value:.1f}", f"{value:.2f}", str(round(value))}
    if value.is_integer():
        out.add(str(int(value)))
    if 0 <= value <= 1:
        out.add(str(round(value * 100)))
    out.add(f"{abs(value):.1f}")
    return out


def printed_numbers(record: Mapping[str, Any]) -> list[tuple[str, str]]:
    """``(field, number)`` for every number the story prints, labels and names removed."""
    names = {str(record.get("display_name") or "")}
    evidence = record.get("evidence") or {}
    for key in ("name", "absent_name", "other_name", "absent_member"):
        if evidence.get(key):
            names.add(str(evidence[key]))
    texts: list[tuple[str, str]] = [
        ("headline", str(record.get("headline") or "")),
        ("dek", str(record.get("dek") or "")),
        ("counterpoint", str(record.get("counterpoint") or "")),
        ("caveat", str(record.get("caveat") or "")),
    ]
    for fact in record.get("facts") or ():
        texts.append(("fact", f"{fact.get('label', '')} {fact.get('value', '')}"))
    out: list[tuple[str, str]] = []
    for field, text in texts:
        for name in sorted(names, key=len, reverse=True):
            if name:
                text = text.replace(name, " ")
        text = _LABELS.sub(" ", text)
        out.extend((field, number) for number in _NUMBER.findall(text))
    return out


def _allowed(record: Mapping[str, Any]) -> set[str]:
    allowed: set[str] = set()
    for source in (record.get("evidence"), record.get("chart"), record.get("window")):
        for value in _leaves(source):
            allowed |= _formats(value)
    for key in ("target_week", "through_week"):
        if isinstance(record.get(key), int):
            allowed.add(str(record[key]))
    return allowed


def _close(a: Any, b: Any, eps: float = _EPS) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return abs(float(a) - float(b)) <= eps


# ------------------------------------------------------------------------------ records


def insight_record_checks(
    records: Sequence[Mapping[str, Any]], stage: str = _STAGE
) -> list[QualityCheck]:
    del stage  # one stage name for every insights check, so a log groups them
    text_problems: list[str] = []
    forbidden: list[str] = []
    identity: list[str] = []
    selection: list[str] = []
    for record in records:
        key = f"{record.get('scoring_preset')}:{record.get('story_id')}"
        allowed = _allowed(record)
        for field, number in printed_numbers(record):
            if number not in allowed:
                text_problems.append(f"{key} {field} '{number}'")
        for field in ("headline", "dek", "counterpoint", "caveat"):
            text = str(record.get(field) or "")
            for pattern in _forbidden():
                if pattern.search(text):
                    forbidden.append(f"{key} {field} /{pattern.pattern}/")
        for fact in record.get("facts") or ():
            text = f"{fact.get('label', '')} {fact.get('value', '')}"
            for pattern in _forbidden():
                if pattern.search(text):
                    forbidden.append(f"{key} fact /{pattern.pattern}/")
        identity.extend(f"{key}: {problem}" for problem in _identity(record))
    selection.extend(_selection(records))
    checks: list[QualityCheck] = []
    if text_problems:
        checks.append(
            _fail(
                "insights.text_number_not_in_evidence",
                "every number a story prints must be one of its own evidence values",
                text_problems,
                "headline, dek, facts, counterpoint and caveat numbers drawn from evidence",
            ),
        )
    if forbidden:
        checks.append(
            _fail(
                "insights.forbidden_claim",
                "a story may not claim routes, first reads, expected points, regression or "
                "confidence",
                forbidden,
                "none of the forbidden phrases",
            ),
        )
    if identity:
        checks.append(
            _fail(
                "insights.identity",
                "a story's edition, window, chart and qualification must add up",
                identity,
                "every identity holds",
            ),
        )
    if selection:
        checks.append(
            _fail(
                "insights.selection",
                "the lead and the one-story-per-player rule must hold per preset",
                selection,
                "insights_select_v1's caps",
            ),
        )
    if not checks:
        checks.append(
            QualityCheck.ok(
                "insights.records_valid",
                stage=_STAGE,
                message="every insights story's text, identities and selection hold",
                observed=f"{len(records)} record(s)",
            ),
        )
    return checks


def _identity(record: Mapping[str, Any]) -> list[str]:  # noqa: C901 - one list of identities
    problems: list[str] = []
    season, through = record.get("season"), record.get("through_week")
    if record.get("edition") != f"{season}w{int(through or 0):02d}":
        problems.append(f"edition {record.get('edition')} vs {season} week {through}")
    window = record.get("window")
    if window is not None:
        first, last = int(window["first_week"]), int(window["last_week"])
        if last != through or first > last or int(window["weeks"]) != last - first + 1:
            problems.append(f"window {first}-{last} ({window['weeks']}) vs cutoff {through}")
        base_last = window.get("baseline_last_week")
        if base_last is not None and int(base_last) != first - 1:
            problems.append(f"baseline ends W{base_last}, window starts W{first}")
    horizon = record.get("horizon")
    evidence_values = record.get("evidence") or {}
    if record.get("espn_rostered") != evidence_values.get("espn_rostered"):
        problems.append("espn_rostered differs from its evidence")
    upside = record.get("family") == "weekly_upside"
    if record.get("ceiling_ranks") != (evidence_values.get("ceiling_ranks") if upside else None):
        problems.append("ceiling_ranks differs from its evidence")
    if record.get("injury") != (evidence_values.get("injury") if horizon == "this_week" else None):
        problems.append("injury differs from its evidence")
    if (horizon == "this_week") != (record.get("kickoff_utc") is not None):
        problems.append(f"horizon {horizon} with kickoff {record.get('kickoff_utc')}")
    if horizon in ("this_week", "stash") and record.get("target_week") is None:
        problems.append(f"horizon {horizon} without a target week")
    for predicate in record.get("qualification") or ():
        if predicate.get("passed") is not True:
            problems.append(f"predicate {predicate.get('rule')} not passed")
    chart = record.get("chart") or {}
    evidence = record.get("evidence") or {}
    kind = chart.get("type")
    if kind == "week_strip":
        problems.extend(_strip_identities(record, chart, evidence))
    elif kind == "interval":
        q10, q50, q90 = chart["q10"], chart["q50"], chart["q90"]
        if not (q10 <= q50 <= q90):
            problems.append(f"interval out of order {q10}/{q50}/{q90}")
        for level in ("q10", "q50", "q90"):
            if not _close(chart[level], evidence.get(level)):
                problems.append(f"chart {level} vs evidence")
        rostered, ceiling = evidence.get("espn_rostered"), evidence.get("ceiling")
        if rostered is None or ceiling is None or not float(rostered) < float(ceiling):
            problems.append(f"rostered {rostered} not below ceiling {ceiling}")
        ranks = evidence.get("ceiling_ranks") or {}
        if ranks.get(str(ceiling)) != evidence.get("ceiling_rank"):
            problems.append("ceiling rank disagrees with its ceiling")
        for rank in ranks.values():
            if rank is not None and not 1 <= int(rank) <= UPSIDE_PER_POSITION:
                problems.append(f"published ceiling rank {rank} outside the top 3")
    elif kind == "with_without":
        rows = chart.get("rows") or []
        if not rows or rows[0]["player_id"] != record.get("player_id"):
            problems.append("first with/without row is not the focal player")
        for row in rows:
            for name in ("share_with", "share_without", "latest_share"):
                value = row.get(name)
                if value is not None and not 0 <= float(value) <= 1:
                    problems.append(f"{row['player_id']} {name} {value}")
        if record.get("variant") == "observed":
            if int(evidence.get("games_without") or 0) < 1:
                problems.append("observed opening without a game without him")
            missed = evidence.get("missed_weeks") or []
            if not missed or int(missed[0]) < int((window or {}).get("first_week", 0)):
                problems.append(f"observed absence began before the window: {missed}")
        if not _close(chart["absent"]["share"], evidence.get("absent_share")):
            problems.append("absent share chart vs evidence")
    elif kind == "room":
        team_count = int(chart["team_count"])
        rows = chart.get("rows") or []
        if record.get("player_id") not in {row["player_id"] for row in rows}:
            problems.append("room rows omit the focal player")
        if sum(int(row["count"]) for row in rows) > team_count:
            problems.append("room counts exceed the team's")
        for row in rows:
            if abs(float(row["share"]) - int(row["count"]) / team_count) > 0.0006:
                problems.append(
                    f"{row['player_id']} share {row['share']} vs {row['count']}/{team_count}"
                )
            rz, team_rz = row.get("red_zone"), chart.get("team_red_zone")
            if rz is not None and (team_rz is None or int(rz) > int(team_rz)):
                problems.append(f"{row['player_id']} red zone {rz} vs team {team_rz}")
        if record.get("scoring_dependent") is not False:
            problems.append("a role battle depends on no scoring")
    elif kind == "stat_line":
        games, points = int(chart["games"]), float(chart["points"])
        if games > int(chart["team_games"]):
            problems.append("more games than team games")
        if not _close(chart["points_per_game"], round(points / games, 2)):
            problems.append("points a game is not points / games")
        if not _close(chart["pace_17"], round(float(chart["points_per_game"]) * 17, 1), 0.06 * 17):
            problems.append("pace is not points a game × 17")
        if int(chart["ppg_rank"]) > int(chart["cohort_size"]):
            problems.append("rank beyond its cohort")
    family = record.get("family")
    if family == "volume_vs_results":
        if record.get("variant") == "lagging":
            if int(evidence["production_rank"]) - int(evidence["workload_rank"]) < int(
                evidence["required_gap_places"]
            ):
                problems.append("lagging gap below its threshold")
            if int(evidence["workload_rank"]) > int(evidence["band"]):
                problems.append("lagging workload rank outside the band")
        else:
            drop = round(float(evidence["baseline_share"]) - float(evidence["window_share"]), 3)
            if drop + 1e-9 < float(evidence["role_step"]):
                problems.append(f"shrinking drop {drop} below {evidence['role_step']}")
        if not _close(
            evidence["window_opportunities_per_game"],
            round(float(evidence["window_opportunities"]) / int(evidence["window_games"]), 1),
            0.051,
        ):
            problems.append("opportunities a game is not opportunities / games")
    return problems


def _strip_identities(
    record: Mapping[str, Any],
    chart: Mapping[str, Any],
    evidence: Mapping[str, Any],
) -> list[str]:
    problems: list[str] = []
    weeks = chart.get("weeks") or []
    numbers = [int(week["week"]) for week in weeks]
    if not numbers or numbers != list(range(numbers[0], numbers[0] + len(numbers))):
        problems.append(f"strip weeks not consecutive: {numbers}")
    window = record.get("window") or {}
    first, last = window.get("first_week"), window.get("last_week")
    played = 0
    points = 0.0
    opportunities = 0.0
    for week in weeks:
        in_window = (
            first is not None and last is not None and int(first) <= int(week["week"]) <= int(last)
        )
        if bool(week["in_window"]) != in_window:
            problems.append(f"W{week['week']} in_window {week['in_window']}")
        if week["status"] == "P":
            if week["points"] is None:
                problems.append(f"W{week['week']} played without points")
            elif in_window:
                played += 1
                points += float(week["points"])
                opportunities += float(week["opportunity"] or 0.0)
        elif any(
            week[name] is not None
            for name in ("points", "td_points", "opportunity", "share", "rank")
        ):
            problems.append(f"W{week['week']} {week['status']} carries numbers")
    if "window_games" in evidence and played != int(evidence["window_games"]):
        problems.append(f"strip has {played} window games vs {evidence['window_games']}")
    if "window_points" in evidence and not _close(points, evidence["window_points"], 0.05):
        problems.append(f"strip window points {points:.2f} vs {evidence['window_points']}")
    if "window_opportunities" in evidence and not _close(
        opportunities, evidence["window_opportunities"], 0.11
    ):
        problems.append(
            f"strip window opportunities {opportunities} vs {evidence['window_opportunities']}"
        )
    band = chart.get("band")
    if band is not None:
        streak = evidence.get("streak")
        if streak:
            recent = [w for w in weeks if w["status"] == "P" and w["in_window"]][-int(streak) :]
            if any(w["rank"] is None or int(w["rank"]) > int(band) for w in recent):
                problems.append("streak weeks are not all inside the band")
    return problems


def _selection(records: Sequence[Mapping[str, Any]]) -> list[str]:
    problems: list[str] = []
    by_preset: dict[str, list[Mapping[str, Any]]] = {}
    for record in records:
        by_preset.setdefault(str(record["scoring_preset"]), []).append(record)
    caps = FAMILY_CAPS
    for preset, rows in sorted(by_preset.items()):
        players = Counter(str(row["player_id"]) for row in rows)
        problems.extend(f"{preset}: {pid} has {n} stories" for pid, n in players.items() if n > 1)
        ids = Counter(str(row["story_id"]) for row in rows)
        problems.extend(f"{preset}: story id {sid} repeated" for sid, n in ids.items() if n > 1)
        lead = sorted(int(row["lead_rank"]) for row in rows if row.get("lead_rank") is not None)
        if lead != list(range(1, len(lead) + 1)) or len(lead) > LEAD_MAX:
            problems.append(f"{preset}: lead ranks {lead}")
        leaders = [row for row in rows if row.get("lead_rank") is not None]
        teams = Counter(str(row["team"]) for row in leaders if row.get("team"))
        problems.extend(f"{preset}: {team} leads {n}" for team, n in teams.items() if n > TEAM_CAP)
        families = Counter(str(row["family"]) for row in leaders)
        problems.extend(
            f"{preset}: {family} leads {n}"
            for family, n in families.items()
            if n > caps.get(family, 0)
        )
    shared: dict[str, list[Mapping[str, Any]]] = {}
    for record in records:
        if record.get("scoring_dependent") is False:
            shared.setdefault(str(record["story_id"]), []).append(record)
    volatile = {"scoring_preset", "lead_rank", "family_rank", "also_qualifies"}
    for story_id, rows in shared.items():
        first = {k: v for k, v in rows[0].items() if k not in volatile}
        for row in rows[1:]:
            if {k: v for k, v in row.items() if k not in volatile} != first:
                problems.append(f"{story_id} differs between presets though scoring-independent")
    return problems


# ----------------------------------------------------------------------------- metadata


def insight_metadata_checks(
    metadata: Mapping[str, Any],
    envelopes: Mapping[str, Mapping[str, Any]],
) -> list[QualityCheck]:
    """The block describes the artifact beside it; this-week stories kick off after the build."""
    block = metadata.get("insights")
    envelope = envelopes.get("insights")
    stage = "artifacts.ros_build_metadata"
    if block is None:
        if envelope is None:
            return []
        return [
            QualityCheck.fail(
                "ros_build_metadata.insights_undescribed",
                stage=stage,
                message="insights.json is published without its rules and family states",
                observed="metadata insights null",
                expected="an insights block",
            ),
        ]
    records = list((envelope or {}).get("records", ()))
    problems: list[str] = []
    status = block.get("status")
    if status == "published" and envelope is None:
        problems.append("status published but no insights.json")
    if status == "withheld" and records:
        problems.append("status withheld but stories are present")
    if int(block.get("through_week", -1)) != int(metadata.get("through_week", -2)):
        problems.append(f"through_week {block.get('through_week')} vs board")
    counts = block.get("counts") or {}
    for preset in sorted({str(r["scoring_preset"]) for r in records}):
        rows = [r for r in records if r["scoring_preset"] == preset]
        declared = counts.get(preset) or {}
        lead = sum(1 for r in rows if r.get("lead_rank") is not None)
        if int(declared.get("stories", -1)) != len(rows) or int(declared.get("lead", -1)) != lead:
            problems.append(f"{preset}: counts {declared} vs {len(rows)} stories, {lead} lead")
    families = block.get("families") or {}
    for record in records:
        family = families.get(record["family"]) or {}
        if family.get("status") != "published":
            problems.append(f"{record['story_id']} published under a {family.get('status')} family")
            break
    generated = block.get("generated_at_utc")
    if generated:
        built = parse_utc(str(generated))
        for record in records:
            kickoff = record.get("kickoff_utc")
            if kickoff is not None and parse_utc(str(kickoff)) <= built:
                problems.append(f"{record['story_id']} kicks off before the build")
                break
    if problems:
        return [
            QualityCheck.fail(
                "ros_build_metadata.insights_mismatch",
                stage=stage,
                message="ros_build_metadata.insights must describe insights.json",
                observed="; ".join(problems[:6]),
                expected="status, cutoff, counts and family states that match",
            ),
        ]
    return [
        QualityCheck.ok(
            "ros_build_metadata.insights_described",
            stage=stage,
            message="the insights block describes insights.json",
            observed=f"{len(records)} record(s)",
        ),
    ]


# --------------------------------------------------------------------------- cross checks


def insight_cross_checks(envelopes: Mapping[str, Mapping[str, Any]]) -> list[QualityCheck]:
    """Every story's numbers are the published artifacts' numbers."""
    insights = envelopes.get("insights")
    if insights is None:
        return []
    usage = {
        str(r["player_id"]): r for r in (envelopes.get("player_usage") or {}).get("records", ())
    }
    actuals = {
        (str(r["scoring_preset"]), str(r["player_id"])): r
        for r in (envelopes.get("season_actuals") or {}).get("records", ())
    }
    recent = {
        (str(r["scoring_preset"]), str(r["player_id"])): r
        for r in (envelopes.get("recent_form") or {}).get("records", ())
    }
    weekly = {
        (str(r["scoring_preset"]), str(r["player_id"])): r
        for r in (envelopes.get("weekly_projections") or {}).get("records", ())
    }
    espn = {
        str(r["player_id"]): r for r in (envelopes.get("espn_ownership") or {}).get("records", ())
    }
    problems: list[str] = []
    for record in insights.get("records", ()):
        preset, pid = str(record["scoring_preset"]), str(record["player_id"])
        key = f"{preset}:{record['story_id']}"
        if pid not in usage:
            problems.append(f"{key}: no usage record (no card can open him)")
            continue
        chart, evidence = record.get("chart") or {}, record.get("evidence") or {}
        if chart.get("type") == "week_strip":
            series = {int(w["week"]): w for w in usage[pid].get("weeks", ())}
            for week in chart["weeks"]:
                published = series.get(int(week["week"]))
                if (
                    published is None
                    or week["status"] != "P"
                    or published.get("status") != "played"
                ):
                    continue
                points = (published.get("fantasy_points") or {}).get(preset)
                if not _close(week["points"], points, 0.011):
                    problems.append(
                        f"{key}: W{week['week']} points {week['points']} vs usage {points}"
                    )
            span = recent.get((preset, pid))
            if span is not None and week_ranks_disagree(record, span):
                problems.append(f"{key}: weekly ranks disagree with recent form")
        if record["family"] == "pace_perspective":
            season = actuals.get((preset, pid))
            if (
                season is None
                or int(season["games_played"]) != int(evidence["games"])
                or not _close(season["points"], evidence["points"])
            ):
                problems.append(f"{key}: pace totals vs season actuals")
            elif season.get("season_position_rank") != evidence.get("total_rank"):
                problems.append(f"{key}: total rank vs season actuals")
        if record["family"] == "streak_watch" and record["variant"] != "quiet_role_growth":
            span = recent.get((preset, pid))
            published = (((span or {}).get("windows") or {}).get("3") or {}).get("breakout") or {}
            if published.get("category") != evidence.get("category"):
                problems.append(f"{key}: category {evidence.get('category')} vs recent form")
        if record["family"] == "weekly_upside":
            projection = weekly.get((preset, pid))
            quantiles = (projection or {}).get("quantiles") or {}
            if any(
                not _close(quantiles.get(level), evidence.get(level))
                for level in ("q10", "q50", "q90")
            ):
                problems.append(f"{key}: quantiles vs weekly projections")
            if ((projection or {}).get("game") or {}).get("kickoff_utc") != record.get(
                "kickoff_utc"
            ):
                problems.append(f"{key}: kickoff vs weekly projections")
        rostered = evidence.get("espn_rostered")
        if rostered is not None:
            reading = espn.get(pid) or {}
            if reading.get("reading_state") != "observed" or not _close(
                round(float(reading.get("percent_rostered") or -99), 1), rostered, 0.051
            ):
                problems.append(f"{key}: ESPN rostered {rostered} vs reading")
    if problems:
        return [
            _fail(
                "insights.disagrees_with_sources",
                "every story's numbers must be the published artifacts' numbers",
                problems,
                "usage, season actuals, recent form, weekly projections and ESPN agree",
            ),
        ]
    return [
        QualityCheck.ok(
            "insights.agrees_with_sources",
            stage=_STAGE,
            message="insights stories reconcile with the artifacts they read",
            observed=f"{len(insights.get('records', ()))} record(s)",
        ),
    ]


def week_ranks_disagree(record: Mapping[str, Any], span: Mapping[str, Any]) -> bool:
    """A strip's weekly ranks are recent form's ``span_ranks`` over the span's weeks."""
    weeks = {int(w["week"]): w for w in (record.get("chart") or {}).get("weeks", ())}
    if not weeks:
        return False
    through = int(record["through_week"])
    ranks = list(span.get("span_ranks") or [])
    first = through - len(ranks) + 1
    for offset, rank in enumerate(ranks):
        week = weeks.get(first + offset)
        if week is None or week.get("rank") is None or rank is None:
            continue
        if int(week["rank"]) != int(rank):
            return True
    return False
