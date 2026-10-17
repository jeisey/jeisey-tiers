"""Validation of ``espn_ownership`` and ``espn_ownership_series`` (ADR-112).

The schema already bounds every percentage to [0, 100] and pins the vocabulary of states.
These checks hold what a schema cannot: that a state and its values agree (a reading that is
not observed has no value, a missing start reading is never a zero), that each published
change is exactly ``current − baseline`` over a span inside its window, that no instant is in
the future, that a series ascends with unique instants inside 28 days, and — across artifacts
— that the latest summary, the series and the Opportunity Board describe the same players
and the same newest reading.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from typing import Any

from ffdraft.contracts import QualityCheck

__all__ = [
    "ownership_cross_checks",
    "ownership_record_checks",
    "ownership_series_checks",
]

_STAGE = "artifacts.espn_ownership"
#: Two-decimal inputs; their difference is exact to the cent, plus float noise.
_PP_TOLERANCE = 0.0051
#: The rule's windows (`espn_ownership_v1`): (earliest, latest) baseline age in hours.
_WINDOWS = {"rostered_change_1d": (18.0, 30.0), "rostered_change_7d": (156.0, 180.0)}
_SERIES_MAX_DAYS = 28.0
_HAS_VALUE = {"observed", "stale"}


def _fail(check_id: str, message: str, offenders: Sequence[str], expected: str) -> QualityCheck:
    return QualityCheck.fail(
        check_id,
        stage=_STAGE,
        message=message,
        observed="; ".join(offenders[:10]) + (" …" if len(offenders) > 10 else ""),
        expected=expected,
    )


def _instant(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def ownership_record_checks(
    records: Sequence[Mapping[str, Any]],
    stage: str,
    *,
    generated_at: datetime | None = None,
) -> list[QualityCheck]:
    """State/value agreement, change arithmetic and windows, and no future instant."""
    del stage
    nullness: list[str] = []
    arithmetic: list[str] = []
    windows: list[str] = []
    future: list[str] = []
    duplicates: list[str] = []
    seen: set[str] = set()
    limit = None if generated_at is None else generated_at + timedelta(minutes=10)
    for record in records:
        player = str(record.get("player_id"))
        if player in seen:
            duplicates.append(player)
        seen.add(player)
        state = record.get("reading_state")
        rostered = record.get("percent_rostered")
        if (state in _HAS_VALUE) != (rostered is not None):
            nullness.append(f"{player}: {state} with percent_rostered={rostered}")
        if state in _HAS_VALUE and record.get("observed_at_utc") is None:
            nullness.append(f"{player}: {state} without observed_at_utc")
        if state in {"no_espn_id"} and record.get("espn_id") is not None:
            nullness.append(f"{player}: no_espn_id but espn_id={record.get('espn_id')}")
        start_state = record.get("start_state")
        started = record.get("percent_started")
        if (start_state == "observed") != (started is not None):
            nullness.append(f"{player}: start {start_state} with percent_started={started}")
        if state not in _HAS_VALUE | {"invalid", "not_published"} and start_state != "no_reading":
            nullness.append(f"{player}: start {start_state} for a {state} reading")
        for name, (earliest, latest) in _WINDOWS.items():
            change = record.get(name) or {}
            change_state = change.get("state")
            delta = change.get("change_pp")
            if (change_state == "measured") != (delta is not None):
                nullness.append(f"{player}/{name}: {change_state} with change_pp={delta}")
            if change_state != "measured":
                if change_state in {"no_current_reading", "insufficient_history"} and (
                    change.get("baseline_percent_rostered") is not None
                ):
                    nullness.append(f"{player}/{name}: {change_state} carries a baseline value")
                if change_state != "no_current_reading" and state not in _HAS_VALUE:
                    nullness.append(f"{player}/{name}: {change_state} without a current reading")
                continue
            if state not in _HAS_VALUE or rostered is None:
                nullness.append(f"{player}/{name}: measured without a current reading")
                continue
            base = change.get("baseline_percent_rostered")
            if (
                base is None
                or delta is None
                or abs(float(rostered) - float(base) - float(delta)) > _PP_TOLERANCE
            ):
                arithmetic.append(f"{player}/{name}: {rostered} - {base} != {delta}")
            span = change.get("span_hours")
            baseline_at = _instant(change.get("baseline_observed_at_utc"))
            current_at = _instant(record.get("observed_at_utc"))
            if span is None or not (earliest - 0.01 <= float(span) <= latest + 0.01):
                windows.append(f"{player}/{name}: span {span} h outside [{earliest}, {latest}]")
            elif baseline_at is None or current_at is None:
                windows.append(f"{player}/{name}: span without both instants")
            elif abs((current_at - baseline_at).total_seconds() / 3600.0 - float(span)) > 0.01:
                windows.append(f"{player}/{name}: span {span} h disagrees with its instants")
        if limit is not None:
            for name in ("observed_at_utc", "espn_updated_at_utc"):
                moment = _instant(record.get(name))
                if moment is not None and moment > limit:
                    future.append(f"{player}: {name}={record.get(name)}")

    checks: list[QualityCheck] = []
    if duplicates:
        checks.append(
            _fail(
                "espn_ownership.duplicate_player",
                "one record per player: ESPN publishes one population-wide figure",
                sorted(set(duplicates)),
                "unique player_id",
            ),
        )
    if nullness:
        checks.append(
            _fail(
                "espn_ownership.state_disagrees_with_values",
                "a reading's state and its values must agree; an absent reading is never 0%",
                nullness,
                "values present exactly when their state says a value exists",
            ),
        )
    if arithmetic:
        checks.append(
            _fail(
                "espn_ownership.change_is_not_the_difference",
                "a published change is the current percentage minus its baseline, in points",
                arithmetic,
                "change_pp == percent_rostered - baseline_percent_rostered",
            ),
        )
    if windows:
        checks.append(
            _fail(
                "espn_ownership.change_outside_its_window",
                "a change's baseline must sit inside the rule's window and match its instants",
                windows,
                "1d: 18-30 h; 7d: 156-180 h",
            ),
        )
    if future:
        checks.append(
            _fail(
                "espn_ownership.instant_in_future",
                "no reading can postdate the build that published it",
                future,
                "observed and ESPN update instants at or before generated_at",
            ),
        )
    if not checks and records:
        observed = sum(1 for record in records if record.get("reading_state") == "observed")
        checks.append(
            QualityCheck.ok(
                "espn_ownership.records_well_formed",
                stage=_STAGE,
                message=(
                    "every reading's state agrees with its values, and every published change "
                    "is the difference inside its window"
                ),
                observed=f"{len(records)} player(s), {observed} observed",
            ),
        )
    return checks


def ownership_series_checks(
    records: Sequence[Mapping[str, Any]],
    stage: str,
    *,
    generated_at: datetime | None = None,
) -> list[QualityCheck]:
    """Ascending unique instants, counts that match, a span inside the window."""
    del stage
    problems: list[str] = []
    limit = None if generated_at is None else generated_at + timedelta(minutes=10)
    for record in records:
        player = str(record.get("player_id"))
        points = list(record.get("points") or ())
        instants = [_instant(point.get("observed_at_utc")) for point in points]
        if any(moment is None for moment in instants):
            problems.append(f"{player}: unreadable instant")
            continue
        ordered = [moment for moment in instants if moment is not None]
        if any(later <= earlier for earlier, later in zip(ordered, ordered[1:], strict=False)):
            problems.append(f"{player}: points do not strictly ascend")
        if record.get("observations") != len(points):
            problems.append(f"{player}: observations={record.get('observations')} != {len(points)}")
        captures = record.get("captures_in_window")
        if isinstance(captures, int) and captures < len(points):
            problems.append(f"{player}: {len(points)} points in {captures} captures")
        if ordered:
            span = (ordered[-1] - ordered[0]).total_seconds() / 3600.0
            if abs(span - float(record.get("span_hours") or 0.0)) > 0.01:
                problems.append(f"{player}: span_hours={record.get('span_hours')} != {span:.2f}")
            if span > _SERIES_MAX_DAYS * 24.0 + 0.01:
                problems.append(f"{player}: series spans {span / 24.0:.2f} days")
            if limit is not None and ordered[-1] > limit:
                problems.append(f"{player}: newest point postdates the build")
    if problems:
        return [
            _fail(
                "espn_ownership_series.malformed",
                "a series is one point per retained capture, ascending, inside 28 days",
                problems,
                "strictly ascending instants, counts and span that match the points",
            ),
        ]
    if not records:
        return []
    return [
        QualityCheck.ok(
            "espn_ownership_series.series_well_formed",
            stage=_STAGE,
            message="every series ascends, counts its own points and stays inside 28 days",
            observed=f"{len(records)} series",
        ),
    ]


def ownership_cross_checks(envelopes: Mapping[str, Mapping[str, Any]]) -> list[QualityCheck]:
    """The summary, the series and the Opportunity Board must describe the same players."""
    latest = envelopes.get("espn_ownership")
    series = envelopes.get("espn_ownership_series")
    opportunity = envelopes.get("inseason_opportunity")
    checks: list[QualityCheck] = []
    if latest is None:
        if series is not None:
            checks.append(
                _fail(
                    "cross_artifact.espn_series_without_summary",
                    "the series is published only beside the latest summary",
                    ["espn_ownership_series.json present, espn_ownership.json absent"],
                    "both or neither",
                ),
            )
        return checks
    summary = {str(r.get("player_id")): r for r in latest.get("records", ())}
    if opportunity is not None:
        board = {str(r.get("player_id")) for r in opportunity.get("records", ())}
        orphans = sorted(set(summary) - board)
        missing = sorted(board - set(summary))
        if orphans or missing:
            checks.append(
                _fail(
                    "cross_artifact.espn_players_disagree_with_board",
                    "every Opportunity Board player has exactly one ESPN record, and no other "
                    "player does: ESPN never adds a player to the board",
                    [f"not on board: {p}" for p in orphans] + [f"no record: {p}" for p in missing],
                    "espn_ownership players == inseason_opportunity players",
                ),
            )
    if series is not None:
        disagree: list[str] = []
        for record in series.get("records", ()):
            player = str(record.get("player_id"))
            row = summary.get(player)
            if row is None:
                disagree.append(f"{player}: series without a summary record")
                continue
            if row.get("espn_id") != record.get("espn_id"):
                disagree.append(
                    f"{player}: espn_id {row.get('espn_id')} != {record.get('espn_id')}"
                )
            points = list(record.get("points") or ())
            newest = points[-1] if points else None
            if (
                newest is not None
                and row.get("reading_state") in _HAS_VALUE
                and newest.get("observed_at_utc") == row.get("observed_at_utc")
            ):
                for field in ("percent_rostered", "percent_started"):
                    drawn = newest.get(field)
                    published = row.get(field)
                    if field == "percent_started" and row.get("start_state") != "observed":
                        continue
                    if drawn != published:
                        disagree.append(f"{player}/{field}: summary={published} series={drawn}")
            if row.get("reading_state") in _HAS_VALUE and (
                newest is None or newest.get("observed_at_utc") != row.get("observed_at_utc")
            ):
                disagree.append(f"{player}: series' newest point is not the summary's capture")
        if disagree:
            checks.append(
                _fail(
                    "cross_artifact.espn_series_disagrees_with_summary",
                    "the series' newest point and the summary come from the same capture",
                    disagree,
                    "same capture, same values",
                ),
            )
    if not checks:
        checks.append(
            QualityCheck.ok(
                "cross_artifact.espn_ownership_agrees",
                stage=_STAGE,
                message=(
                    "ESPN records match the board's players, and each series ends on its summary"
                ),
                observed=f"{len(summary)} player(s)",
            ),
        )
    return checks
