"""ESPN roster/start readings keyed to canonical players, with honest changes (`espn_ownership_v1`).

**Boundary module.** Reads the retained ``ownership/`` window and the annotation-side identity
registry; writes two public record lists. It reads no board value and no board reads it: the
in-season build calls it after every board exists, and nothing it returns can reach a
feature, a projection, a replacement level, a rank or a tier (ADR-112).

**The join direction is ADR-011's.** Iteration runs over the canonical players the Opportunity
Board publishes, through each one's verified ``espn_id`` in the registry. ESPN never adds a
player, never names one (its name is diagnostics in the private store), and an ``espn_id`` two
canonical players claim is poisoned in the registry and resolves to nobody.

**What a change is.** ``current − baseline`` in *percentage points*, where the baseline is a
retained capture taken close to the stated span before the latest one:

==========  ===========  ===========  ===================================
change      target       tolerance    a capture qualifies when its age is
==========  ===========  ===========  ===================================
``1d``      24 h         ± 6 h        18 h to 30 h before the latest
``7d``      168 h        ± 12 h       156 h to 180 h before the latest
==========  ===========  ===========  ===================================

The qualifying capture nearest the target is used (the earlier one on a tie), and its time,
its value and the actual span are published beside the change. Nothing is interpolated,
backfilled or carried forward: no qualifying capture means ``insufficient_history``; a
qualifying capture that did not carry the player means ``no_baseline_reading``.

**No start-percentage change is published.** ESPN states neither the denominator of
``percentStarted`` nor which week's lineups it counts, and lineups are set in a weekly rhythm
(byes, Thursday locks, Sunday mornings) that would read as a trend between any two captures.
The start history is published as points with ESPN's reported scoring period on each, so a
week boundary is visible, and no start-change metric exists in v1.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from ffdraft.identity.ids import IdNamespace
from ffdraft.identity.registry import CanonicalRegistry, LookupStatus
from ffdraft.ownership.capture import (
    OWNERSHIP_PREFIX,
    OwnershipCapture,
    read_ownership_capture,
)
from ffdraft.retention import UNREADABLE_SNAPSHOT_ERRORS, SnapshotStore, parse_snapshot_key
from ffdraft.sources.espn import ESPN_SOURCE_ID
from ffdraft.timeutil import isoformat_utc

__all__ = [
    "OWNERSHIP_RULE",
    "OWNERSHIP_RULE_VERSION",
    "OwnershipBuild",
    "OwnershipRule",
    "build_ownership",
    "load_ownership_window",
]

OWNERSHIP_RULE_VERSION = "espn_ownership_v1"

#: Reading states. Every published player carries exactly one.
OBSERVED = "observed"
STALE = "stale"
NOT_PUBLISHED = "not_published"
INVALID = "invalid"
NO_ESPN_ID = "no_espn_id"
AMBIGUOUS_ESPN_ID = "ambiguous_espn_id"
READING_STATES = (OBSERVED, STALE, NOT_PUBLISHED, INVALID, NO_ESPN_ID, AMBIGUOUS_ESPN_ID)

#: Start-reading states, independent of the roster reading's.
NO_READING = "no_reading"
START_STATES = (OBSERVED, NOT_PUBLISHED, INVALID, NO_READING)

#: Change states.
MEASURED = "measured"
NO_CURRENT_READING = "no_current_reading"
INSUFFICIENT_HISTORY = "insufficient_history"
NO_BASELINE_READING = "no_baseline_reading"
INCOMPARABLE = "incomparable"
CHANGE_STATES = (
    MEASURED,
    NO_CURRENT_READING,
    INSUFFICIENT_HISTORY,
    NO_BASELINE_READING,
    INCOMPARABLE,
)


@dataclass(frozen=True, slots=True)
class ChangeWindow:
    name: str
    target_hours: float
    tolerance_hours: float

    @property
    def earliest_hours(self) -> float:
        return self.target_hours + self.tolerance_hours

    @property
    def latest_hours(self) -> float:
        return self.target_hours - self.tolerance_hours

    def to_dict(self) -> dict[str, object]:
        return {
            "target_hours": self.target_hours,
            "tolerance_hours": self.tolerance_hours,
            "baseline_age_hours": [self.latest_hours, self.earliest_hours],
        }


@dataclass(frozen=True, slots=True)
class OwnershipRule:
    """The frozen definition. A change here is a new version with its own ADR."""

    version: str = OWNERSHIP_RULE_VERSION
    #: The trailing window the public series is cut from.
    series_window_days: float = 28.0
    #: A latest capture older than this when the build runs is published as ``stale``.
    stale_after_hours: float = 36.0
    change_1d: ChangeWindow = ChangeWindow("1d", 24.0, 6.0)
    change_7d: ChangeWindow = ChangeWindow("7d", 168.0, 12.0)

    def to_dict(self) -> dict[str, object]:
        return {
            "rule_version": self.version,
            "series_window_days": self.series_window_days,
            "stale_after_hours": self.stale_after_hours,
            "change_1d": self.change_1d.to_dict(),
            "change_7d": self.change_7d.to_dict(),
            "change_unit": "percentage points: current minus baseline, never relative growth",
            "baseline_rule": (
                "the retained capture whose age before the latest capture is inside the "
                "window and nearest the target (earlier on a tie); never interpolated, "
                "backfilled or carried forward"
            ),
            "started_change": (
                "not published: ESPN states neither percentStarted's denominator nor the "
                "week it counts, and lineup-setting cadence would read as a trend"
            ),
            "absence_is_not_zero": (
                "a player ESPN published no ownership for has no reading, never 0%"
            ),
        }


OWNERSHIP_RULE = OwnershipRule()


def load_ownership_window(
    store: SnapshotStore | Path,
    *,
    season: int,
    now: datetime,
    source_id: str = ESPN_SOURCE_ID,
    window_days: float = OWNERSHIP_RULE.series_window_days,
) -> tuple[list[OwnershipCapture], list[str]]:
    """Retained captures with retrieval inside ``[now - window, now]``, oldest first.

    Every capture is re-hashed on the way in. One that cannot be read is skipped and named
    (the second return value) — a history missing a day is a shorter history, not an outage.
    Reading only the window keeps a build's cost flat as the season's store grows.
    """
    root = store.root if isinstance(store, SnapshotStore) else store
    ownership_store = SnapshotStore(root=root, prefix=OWNERSHIP_PREFIX)
    horizon = now - timedelta(days=window_days)
    captures: list[OwnershipCapture] = []
    skipped: list[str] = []
    for key in ownership_store.keys(source_id, season):
        try:
            moment = parse_snapshot_key(key)
        except ValueError:
            continue
        if not (horizon <= moment <= now):
            continue
        try:
            capture = read_ownership_capture(
                ownership_store,
                season=season,
                source_id=source_id,
                key=key,
            )
        except UNREADABLE_SNAPSHOT_ERRORS as exc:  # noqa: PERF203
            skipped.append(f"{key}: {exc}")
            continue
        if capture is not None and capture.season == season:
            captures.append(capture)
    captures.sort(key=lambda capture: capture.observed_at_utc)
    return captures, skipped


@dataclass(frozen=True)
class OwnershipBuild:
    """The two public record lists and the counts the metadata block reports."""

    latest: tuple[dict[str, Any], ...] = ()
    series: tuple[dict[str, Any], ...] = ()
    summary: Mapping[str, Any] = field(default_factory=dict)


def _hours(later: datetime, earlier: datetime) -> float:
    return (later - earlier).total_seconds() / 3600.0


def _baseline(
    captures: Sequence[OwnershipCapture],
    latest: OwnershipCapture,
    window: ChangeWindow,
) -> OwnershipCapture | None:
    """The qualifying capture nearest the target age (earlier on a tie), or ``None``."""
    best: tuple[float, float, OwnershipCapture] | None = None
    for capture in captures:
        if capture is latest:
            continue
        age = _hours(latest.observed_at_utc, capture.observed_at_utc)
        if not (window.latest_hours <= age <= window.earliest_hours):
            continue
        ranked = (abs(age - window.target_hours), -age, capture)
        if best is None or ranked[:2] < best[:2]:
            best = ranked
    return None if best is None else best[2]


def _round_pp(value: float) -> float:
    """Percentages arrive with two decimals, so their difference is exact at two."""
    return round(value + 0.0, 2)


def _change(
    *,
    current_row: Mapping[str, Any] | None,
    current_ok: bool,
    latest: OwnershipCapture,
    baseline: OwnershipCapture | None,
    espn_id: str | None,
) -> dict[str, Any]:
    empty = {
        "state": NO_CURRENT_READING,
        "change_pp": None,
        "baseline_percent_rostered": None,
        "baseline_observed_at_utc": None,
        "span_hours": None,
    }
    if not current_ok or current_row is None or espn_id is None:
        return empty
    if baseline is None:
        return {**empty, "state": INSUFFICIENT_HISTORY}
    span = round(_hours(latest.observed_at_utc, baseline.observed_at_utc), 2)
    prior = baseline.readings().get(espn_id)
    stamped = {
        "baseline_observed_at_utc": isoformat_utc(baseline.observed_at_utc),
        "span_hours": span,
    }
    if prior is None or prior.get("percent_rostered") is None:
        return {**empty, **stamped, "state": NO_BASELINE_READING}
    if prior.get("league_type") != current_row.get("league_type"):
        return {**empty, **stamped, "state": INCOMPARABLE}
    current = float(current_row["percent_rostered"])
    before = float(prior["percent_rostered"])
    return {
        "state": MEASURED,
        "change_pp": _round_pp(current - before),
        "baseline_percent_rostered": before,
        **stamped,
    }


def espn_lookup(registry: CanonicalRegistry, player_id: str) -> tuple[str | None, str | None]:
    """``(espn_id, failure_state)`` for one canonical player, through the registry only."""
    player = registry.players.get(player_id)
    espn_id = None if player is None else player.crosswalk.espn_id
    if not espn_id:
        return None, NO_ESPN_ID
    result = registry.lookup(IdNamespace.ESPN, espn_id)
    if result.status is LookupStatus.AMBIGUOUS or (result.found and result.player_id != player_id):
        return str(espn_id), AMBIGUOUS_ESPN_ID
    return str(espn_id), None


def build_ownership(
    captures: Sequence[OwnershipCapture],
    *,
    registry: CanonicalRegistry,
    players: Iterable[tuple[str, str]],
    build_id: str,
    season: int,
    through_week: int,
    generated_at: datetime,
    schema_versions: Mapping[str, str],
    rule: OwnershipRule = OWNERSHIP_RULE,
) -> OwnershipBuild:
    """Both artifacts' records for ``players`` (``(player_id, position)`` pairs).

    ``generated_at`` decides staleness only. Changes and the series are anchored on the
    newest retained capture, so rebuilding from the same bytes later reproduces them.
    """
    window = tuple(sorted(captures, key=lambda capture: capture.observed_at_utc))
    wanted = sorted(dict(players).items())
    if not window:
        return OwnershipBuild(summary={"captures_in_window": 0})
    latest = window[-1]
    age_hours = round(max(0.0, _hours(generated_at, latest.observed_at_utc)), 2)
    stale = age_hours > rule.stale_after_hours
    readings = latest.readings()
    base_1d = _baseline(window, latest, rule.change_1d)
    base_7d = _baseline(window, latest, rule.change_7d)
    series_start = latest.observed_at_utc - timedelta(days=rule.series_window_days)
    series_captures = [c for c in window if c.observed_at_utc >= series_start]
    indexed = [(capture, capture.readings()) for capture in series_captures]

    latest_records: list[dict[str, Any]] = []
    series_records: list[dict[str, Any]] = []
    counts: dict[str, int] = {state: 0 for state in READING_STATES}
    start_counts: dict[str, int] = {state: 0 for state in START_STATES}
    change_counts: dict[str, dict[str, int]] = {
        name: {state: 0 for state in CHANGE_STATES} for name in ("1d", "7d")
    }
    matched_ids: set[str] = set()

    for player_id, position in wanted:
        espn_id, failure = espn_lookup(registry, player_id)
        row = readings.get(espn_id) if espn_id is not None and failure is None else None
        if failure is not None:
            state = failure
        elif row is None:
            state = NOT_PUBLISHED
        elif row.get("percent_rostered") is None:
            state = INVALID
        else:
            state = STALE if stale else OBSERVED
        if row is not None and espn_id is not None:
            matched_ids.add(espn_id)
        has_reading = state in {OBSERVED, STALE}
        if row is None or state in {NO_ESPN_ID, AMBIGUOUS_ESPN_ID}:
            start_state = NO_READING
        elif row.get("percent_started") is not None:
            start_state = OBSERVED
        elif "invalid_percent_started" in str(row.get("quality_flags") or ""):
            start_state = INVALID
        else:
            start_state = NOT_PUBLISHED
        counts[state] += 1
        start_counts[start_state] += 1
        changes = {
            name: _change(
                current_row=row,
                current_ok=has_reading,
                latest=latest,
                baseline=baseline,
                espn_id=espn_id if failure is None else None,
            )
            for name, baseline in (("1d", base_1d), ("7d", base_7d))
        }
        for name, change in changes.items():
            change_counts[name][change["state"]] += 1
        started_value = row.get("percent_started") if row is not None else None
        latest_records.append(
            {
                "schema_version": schema_versions["espn_ownership"],
                "build_id": build_id,
                "season": season,
                "through_week": through_week,
                "source_id": latest.source_id,
                "player_id": player_id,
                "position": position,
                "espn_id": espn_id,
                "reading_state": state,
                "observed_at_utc": isoformat_utc(latest.observed_at_utc)
                if row is not None
                else None,
                "espn_updated_at_utc": row.get("source_updated_at_utc")
                if row is not None
                else None,
                "espn_current_period": latest.espn_current_period if row is not None else None,
                "percent_rostered": row.get("percent_rostered") if row is not None else None,
                "start_state": start_state,
                "percent_started": started_value if start_state == OBSERVED else None,
                "rostered_change_1d": changes["1d"],
                "rostered_change_7d": changes["7d"],
            },
        )

        if failure is not None or espn_id is None:
            continue
        points: list[dict[str, Any]] = []
        moments: list[datetime] = []
        for capture, captured in indexed:
            point = captured.get(espn_id)
            if point is None:
                continue
            moments.append(capture.observed_at_utc)
            points.append(
                {
                    "observed_at_utc": isoformat_utc(capture.observed_at_utc),
                    "espn_updated_at_utc": point.get("source_updated_at_utc"),
                    "espn_current_period": capture.espn_current_period,
                    "percent_rostered": point.get("percent_rostered"),
                    "percent_started": point.get("percent_started"),
                },
            )
        if not points:
            continue
        first, last = moments[0], moments[-1]
        series_records.append(
            {
                "schema_version": schema_versions["espn_ownership_series"],
                "build_id": build_id,
                "season": season,
                "through_week": through_week,
                "source_id": latest.source_id,
                "player_id": player_id,
                "position": position,
                "espn_id": espn_id,
                "window_days": rule.series_window_days,
                "captures_in_window": len(series_captures),
                "observations": len(points),
                "span_hours": round(_hours(last, first), 2),
                "points": points,
            },
        )

    unmatched = sorted(set(readings) - matched_ids)
    summary = {
        "captures_in_window": len(series_captures),
        "capture_times_utc": [isoformat_utc(c.observed_at_utc) for c in series_captures],
        "latest_snapshot_key": latest.snapshot_key,
        "latest_observed_at_utc": isoformat_utc(latest.observed_at_utc),
        "latest_age_hours": age_hours,
        "stale": stale,
        "espn_current_period": latest.espn_current_period,
        "espn_universe_rows": len(readings),
        "espn_rows_matched": len(matched_ids),
        "espn_rows_not_on_board": len(unmatched),
        "players": len(wanted),
        "reading_states": counts,
        "start_states": start_counts,
        "change_states": change_counts,
        "baseline_1d_observed_at_utc": (
            isoformat_utc(base_1d.observed_at_utc) if base_1d is not None else None
        ),
        "baseline_7d_observed_at_utc": (
            isoformat_utc(base_7d.observed_at_utc) if base_7d is not None else None
        ),
        "series_players": len(series_records),
    }
    return OwnershipBuild(
        latest=tuple(latest_records),
        series=tuple(series_records),
        summary=summary,
    )
