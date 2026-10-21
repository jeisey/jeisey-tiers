"""Validation of ``recent_form`` (ADR-113): re-derive every rank and every category.

The artifact publishes every player who appeared in the six-week span, so each weekly rank
and each window rank is checkable from its own rows, and each window's totals are sums of the
span weeks it covers. The category is re-derived from the published evidence alone — season
rank, window rank, prior games, the span's statuses and weekly ranks, and the role readings'
levels against the thresholds in the metadata — by an implementation independent of the
builder's, so a category the evidence does not support cannot be deployed.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from ffdraft.contracts import QualityCheck
from ffdraft.signals.actuals import ACTUALS_POSITIONS, competition_ranks

__all__ = [
    "recent_cross_checks",
    "recent_metadata_checks",
    "recent_record_checks",
    "rederive_category",
]

_STAGE = "artifacts.recent_form"
_WINDOWS = ("1", "2", "3", "4", "6")


def _fail(check_id: str, message: str, offenders: Sequence[str], expected: str) -> QualityCheck:
    return QualityCheck.fail(
        check_id,
        stage=_STAGE,
        message=message,
        observed="; ".join(offenders[:10]) + (" …" if len(offenders) > 10 else ""),
        expected=expected,
    )


def _cents(value: float) -> int:
    return round(float(value) * 100)


def _covered(record: Mapping[str, Any], window: str) -> range:
    """Span indices a window covers: its last ``min(N, span)`` weeks."""
    length = len(str(record.get("span_status") or ""))
    return range(max(0, length - int(window)), length)


def _units(value: float, metric: str) -> int:
    digits = 3 if metric.endswith("_share") else 1
    return int(round(float(value) * 10**digits))


def rederive_category(
    record: Mapping[str, Any],
    window: str,
    rule: Mapping[str, Any],
) -> tuple[str, str]:
    """``breakout_v1`` from the record's published evidence and the rule's thresholds."""
    entry = record["windows"][window]
    verdict = entry["breakout"]
    position = str(record["position"])
    band = int(rule["bands"][position])
    status = str(record["span_status"])
    covered = list(_covered(record, window))
    played = [index for index in covered if status[index] == "P"]
    rank = entry.get("rank")
    season = record.get("season_rank")
    if not played or rank is None:
        return "insufficient", "no_games"
    if rank > band:
        return "none", "outside_band"
    if int(entry["prior_games"]) < int(rule["min_prior_games"]) or season is None:
        return "insufficient", "no_baseline"
    gain = int(season) - int(rank)
    if gain <= 0:
        return "none", "not_improved"
    if gain < int(rule["min_gain_places"]) or gain * 100 < int(rule["min_gain_percent"]) * season:
        return "none", "gain_too_small"
    latest = played[-1]
    missed = sum(1 for index in range(latest + 1, len(status)) if status[index] == "D")
    if missed > int(rule["max_missed_after_latest"]):
        return "none", "stale"
    ranks = record["span_ranks"]
    streak = 0
    for index in reversed(played):
        if ranks[index] is None or ranks[index] > band:
            break
        streak += 1
        if streak == int(rule["takeover_games"]):
            break
    if streak == 0:
        return "none", "latest_not_strong"
    measures = {m["metric"]: m for m in rule["measures"].get(position, ())}
    readings = verdict.get("role") or []

    def role_verdict(size: int) -> str | None:
        # The published readings belong to the last role check made; only that size can be
        # re-derived, and a reading for another size is a contradiction caught by the caller.
        if not readings or any(int(r["games"]) != size for r in readings):
            return None
        passed = False
        unknown = False
        for reading in readings:
            spec = measures.get(reading["metric"])
            level = reading.get("level")
            if spec is None:
                return "contradiction"
            if level is None:
                unknown = True
                continue
            metric = str(reading["metric"])
            if _units(level, metric) >= _units(spec["substantial"], metric) or (
                spec.get("emerging") is not None
                and spec.get("increase") is not None
                and reading.get("baseline") is not None
                and _units(level, metric) >= _units(spec["emerging"], metric)
                and _units(level, metric) - _units(reading["baseline"], metric)
                >= _units(spec["increase"], metric)
            ):
                passed = True
        if len(readings) != len(measures):
            return "contradiction"
        if passed:
            return "pass"
        return "unknown" if unknown else "fail"

    category = str(verdict["category"])
    sizes = [(int(rule["takeover_games"]), "takeover"), (int(rule["sneaking_games"]), "sneaking")]
    for size, name in sizes:
        if streak < size:
            continue
        outcome = role_verdict(size)
        if outcome is None:
            # The published readings are for a smaller check: this size must have failed.
            continue
        if outcome == "pass":
            return name, f"{name}_role"
        if outcome == "unknown":
            return "insufficient", "role_unavailable"
        if outcome == "contradiction":
            return "contradiction", "role readings do not match the position's measures"
    # Every size above was skipped or failed. A skipped size is accepted only if the record
    # does not claim it, so a stronger badge can never pass on readings of a weaker check.
    if category in ("takeover", "sneaking"):
        return "contradiction", f"{category} without matching role readings"
    return "eyebrow", "one_strong" if streak == 1 else "role_not_confirmed"


def recent_record_checks(
    records: Sequence[Mapping[str, Any]],
    stage: str,
    rule: Mapping[str, Any] | None = None,
) -> list[QualityCheck]:
    """Shapes, sums and ranks from the artifact's own rows; categories when a rule is given."""
    checks: list[QualityCheck] = []
    shape: list[str] = []
    arithmetic: list[str] = []
    for record in records:
        key = f"{record.get('scoring_preset')}/{record.get('player_id')}"
        status = str(record.get("span_status") or "")
        points = list(record.get("span_points") or [])
        ranks = list(record.get("span_ranks") or [])
        if not (len(status) == len(points) == len(ranks)):
            shape.append(f"{key}: span lengths {len(status)}/{len(points)}/{len(ranks)}")
            continue
        for index, code in enumerate(status):
            if (code == "P") != (points[index] is not None) or (code == "P") != (
                ranks[index] is not None
            ):
                shape.append(f"{key}: span week {index} status {code} vs {points[index]}")
        for window in _WINDOWS:
            entry = record["windows"][window]
            covered = [index for index in _covered(record, window) if status[index] == "P"]
            games = int(entry["games"])
            if games != len(covered):
                arithmetic.append(f"{key} w{window}: games {games} vs {len(covered)} played")
            total = sum(_cents(points[index]) for index in covered)
            if _cents(entry["points"]) != total:
                arithmetic.append(f"{key} w{window}: points {entry['points']} vs {total / 100}")
            if games == 0:
                if entry["rank"] is not None or entry["points_per_game"] is not None:
                    shape.append(f"{key} w{window}: no games but a rank or rate")
            elif entry["rank"] is None or entry["points_per_game"] is None:
                shape.append(f"{key} w{window}: {games} game(s) but no rank or rate")
            elif abs(float(entry["points_per_game"]) - round(total / 100 / games, 2)) > 1e-9:
                arithmetic.append(f"{key} w{window}: rate {entry['points_per_game']}")
    if shape:
        checks.append(
            _fail(
                "recent_form.shape",
                "span arrays align with the status string, and a window has a rank and rate "
                "exactly when it has a game",
                shape,
                "P ⇔ points and rank; games 0 ⇔ rank null ⇔ rate null",
            ),
        )
    if arithmetic:
        checks.append(
            _fail(
                "recent_form.arithmetic",
                "a window's games and points are the span weeks it covers",
                arithmetic,
                "window totals == sums over its weeks",
            ),
        )

    # Weekly and window ranks, re-derived per (preset, position).
    wrong: list[str] = []
    groups: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    for record in records:
        groups.setdefault((str(record["scoring_preset"]), str(record["position"])), []).append(
            record,
        )
    for (preset, position), members in sorted(groups.items()):
        length = max((len(str(m["span_status"])) for m in members), default=0)
        for index in range(length):
            week = {
                str(m["player_id"]): _cents(m["span_points"][index])
                for m in members
                if len(str(m["span_status"])) == length and m["span_status"][index] == "P"
            }
            for player, rank in competition_ranks(week).items():
                held = next(m for m in members if str(m["player_id"]) == player)
                if held["span_ranks"][index] != rank:
                    wrong.append(f"{preset} {position} {player} span {index}: ≠ {rank}")
        for window in _WINDOWS:
            totals = {
                str(m["player_id"]): _cents(m["windows"][window]["points"])
                for m in members
                if int(m["windows"][window]["games"]) > 0
            }
            ranked = competition_ranks(totals)
            for member in members:
                expected = ranked.get(str(member["player_id"]))
                if member["windows"][window]["rank"] != expected:
                    wrong.append(
                        f"{preset} {position} {member['player_id']} w{window}: "
                        f"{member['windows'][window]['rank']} ≠ {expected}",
                    )
    if wrong:
        checks.append(
            _fail(
                "recent_form.rank_not_rederivable",
                "every weekly and window rank must be the competition rank of the published "
                "points among every player at the position who appeared",
                wrong,
                "ranks re-derived from the artifact's own rows",
            ),
        )

    if rule is not None:
        unsupported: list[str] = []
        for record in records:
            for window in _WINDOWS:
                verdict = record["windows"][window]["breakout"]
                category, reason = rederive_category(record, window, rule)
                if (category, reason) != (verdict["category"], verdict["reason"]):
                    unsupported.append(
                        f"{record['scoring_preset']}/{record['player_id']} w{window}: "
                        f"{verdict['category']}/{verdict['reason']} vs {category}/{reason}",
                    )
        if unsupported:
            checks.append(
                _fail(
                    "recent_form.category_not_rederivable",
                    "every breakout category must follow from its published evidence and the "
                    "published thresholds",
                    unsupported,
                    "breakout_v1 re-derived independently",
                ),
            )

    if not checks:
        checks.append(
            QualityCheck.ok(
                "recent_form.records_consistent",
                stage=stage,
                message=(
                    "recent form re-derives: window totals are sums of span weeks, and every "
                    "weekly and window rank is a competition rank over every appearing player"
                    + ("; every category follows from its evidence" if rule else "")
                ),
                observed=f"{len(records)} record(s)",
            ),
        )
    return checks


def recent_metadata_checks(
    metadata: Mapping[str, Any],
    envelopes: Mapping[str, Mapping[str, Any]],
) -> list[QualityCheck]:
    """The metadata block must describe the artifact beside it, and its categories re-derive."""
    block = metadata.get("recent_form")
    envelope = envelopes.get("recent_form")
    stage = "artifacts.ros_build_metadata"
    if block is None:
        if envelope is None:
            return []
        return [
            QualityCheck.fail(
                "ros_build_metadata.recent_form_undescribed",
                stage=stage,
                message="recent_form.json is published without its windows and thresholds",
                observed="metadata recent_form null",
                expected="a recent_form block",
            ),
        ]
    records = list((envelope or {}).get("records", ()))
    problems: list[str] = []
    status = block.get("status")
    if status == "published" and envelope is None:
        problems.append("status published but no recent_form.json")
    if status == "withheld" and envelope is not None:
        problems.append("status withheld but recent_form.json is present")
    if int(block.get("records", -1)) != len(records):
        problems.append(f"records {block.get('records')} vs artifact {len(records)}")
    if int(block.get("through_week", -1)) != int(metadata.get("through_week", -2)):
        problems.append(f"through_week {block.get('through_week')} vs board")
    span = list(block.get("span_weeks") or [])
    for record in records:
        if len(str(record.get("span_status") or "")) != len(span):
            problems.append(f"{record.get('player_id')}: span length vs {len(span)} weeks")
            break
    if envelope is not None:
        presets = sorted({str(r["scoring_preset"]) for r in records})
        first = presets[0] if presets else None
        for window in _WINDOWS:
            counted = {position: 0 for position in ACTUALS_POSITIONS}
            for record in records:
                if record["scoring_preset"] == first and record["windows"][window]["games"] > 0:
                    counted[str(record["position"])] += 1
            declared = (block.get("population") or {}).get(window) or {}
            if {p: int(declared.get(p, 0)) for p in ACTUALS_POSITIONS} != counted:
                problems.append(f"population w{window} {declared} vs {counted}")
    checks: list[QualityCheck] = []
    if problems:
        checks.append(
            QualityCheck.fail(
                "ros_build_metadata.recent_form_mismatch",
                stage=stage,
                message="ros_build_metadata.recent_form must describe recent_form.json",
                observed="; ".join(problems[:6]),
                expected="status, records, cutoff, span and population that match",
            ),
        )
    if envelope is not None and isinstance(block.get("breakout_rule"), Mapping):
        checks.extend(
            check
            for check in recent_record_checks(records, _STAGE, rule=block["breakout_rule"])
            if check.check_id == "recent_form.category_not_rederivable"
        )
    return checks


def recent_cross_checks(envelopes: Mapping[str, Mapping[str, Any]]) -> list[QualityCheck]:
    """Position and season rank are season actuals'; a span covering the season is the season."""
    recent = envelopes.get("recent_form")
    if recent is None:
        return []
    actuals = envelopes.get("season_actuals")
    if actuals is None:
        return [
            QualityCheck.fail(
                "recent_form.without_season_actuals",
                stage=_STAGE,
                message="recent form is a slice of the season actuals population",
                observed="recent_form.json present, season_actuals.json absent",
                expected="both or neither",
            ),
        ]
    index = {(str(r["scoring_preset"]), str(r["player_id"])): r for r in actuals.get("records", ())}
    problems: list[str] = []
    for record in recent.get("records", ()):
        key = (str(record["scoring_preset"]), str(record["player_id"]))
        season = index.get(key)
        if season is None:
            problems.append(f"{key}: no season_actuals record")
            continue
        if season["position"] != record["position"]:
            problems.append(f"{key}: position {record['position']} vs {season['position']}")
        if season["season_position_rank"] != record["season_rank"]:
            problems.append(f"{key}: season rank {record['season_rank']}")
        six = record["windows"]["6"]
        # Every record's span starts at week 1 exactly when the season has at most six weeks.
        if int(record["through_week"]) <= 6 and (
            _cents(six["points"]) != _cents(season["points"])
            or int(six["games"]) != int(season["games_played"])
        ):
            problems.append(f"{key}: a span that is the season disagrees with the season")
    if problems:
        return [
            _fail(
                "recent_form.disagrees_with_season_actuals",
                "recent form must use season actuals' positions, season ranks and totals",
                problems,
                "one population, one position, one season rank",
            ),
        ]
    return [
        QualityCheck.ok(
            "recent_form.agrees_with_season_actuals",
            stage=_STAGE,
            message="recent form uses season actuals' positions and season ranks",
            observed=f"{len(recent.get('records', ()))} record(s)",
        ),
    ]
