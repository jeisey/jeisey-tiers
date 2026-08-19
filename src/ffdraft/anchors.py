"""Draft-time anchors.

Every historical training row is a claim about what was knowable at one instant, so that
instant has to be defined before anything else in Phase 2 (`docs/DATA_CONTRACTS.md`
section 3). The rule is fixed by ADR-021 and versioned in
:data:`DRAFT_ANCHOR_RULE_VERSION`:

    For a target season, the anchor is 23:59:59 America/New_York on the Tuesday
    immediately preceding the earliest Week-1 regular-season kickoff, persisted as UTC.

Three properties matter more than the specific choice of day:

* **It is explicit about time zone.** Machine-local time would make a build's leakage
  boundary depend on where it ran, which is the same class of bug as a naive datetime.
* **It uses only preseason-known context.** A season's Week-1 schedule is published in May;
  it is not an outcome of the season it opens. Reading the kickoff *date* from the schedule
  is therefore not leakage, and nothing else about the schedule is consulted.
* **It is strictly before the first kickoff.** That is asserted, not assumed, so a season
  with an unusual opening weekday cannot silently produce an anchor after football started.

The rule version travels on every feature row. Changing the rule means a new version and a
new ADR (AGENTS.md section 8), not an edit here.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import polars as pl

from ffdraft.contracts import QualityCheck
from ffdraft.contracts.enums import Severity

__all__ = [
    "ANCHOR_LOCAL_TIME",
    "ANCHOR_TIMEZONE",
    "ANCHOR_WEEKDAY",
    "DRAFT_ANCHOR_RULE_VERSION",
    "AnchorError",
    "Kickoff",
    "SeasonAnchor",
    "anchor_for_kickoff",
    "build_season_anchors",
    "check_anchor_precedes_kickoff",
    "first_week1_kickoff",
]

#: The versioned rule identifier persisted in ``feature_cutoff_rule_version``.
DRAFT_ANCHOR_RULE_VERSION = "draft_anchor_v1_tuesday_eod_pre_week1"

#: Anchors are defined in the league's own time zone, never in machine-local time.
ANCHOR_TIMEZONE = "America/New_York"

#: ``date.weekday()`` numbering: Monday is 0, so Tuesday is 1.
ANCHOR_WEEKDAY = 1

#: End of the anchor day, local. Second precision matches the artifact timestamp contract.
ANCHOR_LOCAL_TIME = time(23, 59, 59)

_EASTERN = ZoneInfo(ANCHOR_TIMEZONE)

#: Used when a Week-1 row carries a date but no kickoff time. Treating an unknown time as
#: midnight makes the derived kickoff *earlier* than reality, which can only move the anchor
#: earlier - the safe direction. The count is still reported as a quality warning.
_MISSING_TIME_FALLBACK = time(0, 0, 0)

_REGULAR_SEASON = "REG"
_OPENING_WEEK = 1


class AnchorError(ValueError):
    """Raised when an anchor cannot be derived, or would not precede kickoff."""


@dataclass(frozen=True, slots=True)
class Kickoff:
    """The earliest Week-1 regular-season kickoff of one season."""

    season: int
    game_id: str
    kickoff_local: datetime
    time_was_missing: bool = False

    @property
    def kickoff_utc(self) -> datetime:
        return self.kickoff_local.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class SeasonAnchor:
    """The draft-time anchor for one target season."""

    season: int
    anchor_at_utc: datetime
    anchor_local: datetime
    rule_version: str
    first_kickoff_utc: datetime
    first_kickoff_game_id: str

    def __post_init__(self) -> None:
        if self.anchor_at_utc >= self.first_kickoff_utc:
            raise AnchorError(
                f"{self.season}: anchor {self.anchor_at_utc.isoformat()} does not precede "
                f"the first kickoff {self.first_kickoff_utc.isoformat()}",
            )
        if self.anchor_local.tzinfo is None or self.anchor_at_utc.tzinfo is None:
            raise AnchorError(f"{self.season}: anchors must be timezone-aware")

    @property
    def anchor_date_local(self) -> date:
        return self.anchor_local.date()

    @property
    def days_before_kickoff(self) -> float:
        return (self.first_kickoff_utc - self.anchor_at_utc).total_seconds() / 86400.0

    def covers(self, observed_at: datetime) -> bool:
        """Whether an observation timestamp is available at this anchor."""
        return observed_at.astimezone(UTC) <= self.anchor_at_utc


def anchor_for_kickoff(kickoff: Kickoff) -> SeasonAnchor:
    """Derive the anchor for ``kickoff`` by the ADR-021 rule.

    The Tuesday is found by date arithmetic and only then combined with the local time,
    because subtracting a ``timedelta`` from an aware datetime does wall-clock arithmetic
    and can land on a local time that does not exist. Dates have no such hazard.
    """
    kickoff_local = kickoff.kickoff_local
    if kickoff_local.tzinfo is None:
        raise AnchorError(f"{kickoff.season}: kickoff must be timezone-aware")
    local = kickoff_local.astimezone(_EASTERN)

    days_since_tuesday = (local.date().weekday() - ANCHOR_WEEKDAY) % 7
    anchor_date = local.date() - timedelta(days=days_since_tuesday)
    anchor_local = datetime.combine(anchor_date, ANCHOR_LOCAL_TIME, tzinfo=_EASTERN)
    if anchor_local >= local:
        # The opener falls on a Tuesday before 23:59:59. Step back a full week rather than
        # trimming the time, so the rule stays "Tuesday end of day" in every season.
        anchor_local = datetime.combine(
            anchor_date - timedelta(days=7),
            ANCHOR_LOCAL_TIME,
            tzinfo=_EASTERN,
        )

    return SeasonAnchor(
        season=kickoff.season,
        anchor_at_utc=anchor_local.astimezone(UTC),
        anchor_local=anchor_local,
        rule_version=DRAFT_ANCHOR_RULE_VERSION,
        first_kickoff_utc=kickoff.kickoff_utc,
        first_kickoff_game_id=kickoff.game_id,
    )


def first_week1_kickoff(schedule: pl.DataFrame, season: int) -> Kickoff:
    """The earliest Week-1 regular-season kickoff in ``schedule`` for ``season``.

    ``gameday``/``gametime`` are nflverse's published schedule columns; ``gametime`` is
    documented as Eastern regardless of where the game is played, which is why the anchor
    time zone and the kickoff time zone are the same one.
    """
    rows = schedule.filter(
        (pl.col("season") == season)
        & (pl.col("game_type") == _REGULAR_SEASON)
        & (pl.col("week") == _OPENING_WEEK),
    )
    if rows.is_empty():
        raise AnchorError(f"{season}: schedule has no week-1 regular-season games")

    best: Kickoff | None = None
    for record in rows.iter_rows(named=True):
        gameday = record.get("gameday")
        if gameday is None:
            continue
        day = gameday if isinstance(gameday, date) else _parse_date(str(gameday))
        if day is None:
            continue
        raw_time = record.get("gametime")
        parsed_time = _parse_time(raw_time)
        kickoff = Kickoff(
            season=season,
            game_id=str(record.get("game_id") or f"{season}_01"),
            kickoff_local=datetime.combine(
                day,
                parsed_time or _MISSING_TIME_FALLBACK,
                tzinfo=_EASTERN,
            ),
            time_was_missing=parsed_time is None,
        )
        if best is None or (kickoff.kickoff_local, kickoff.game_id) < (
            best.kickoff_local,
            best.game_id,
        ):
            best = kickoff

    if best is None:
        raise AnchorError(f"{season}: no week-1 game carries a usable date")
    return best


def build_season_anchors(
    schedule: pl.DataFrame,
    seasons: Iterable[int],
) -> dict[int, SeasonAnchor]:
    """Derive one anchor per requested season. Raises on any season that cannot be anchored."""
    return {
        season: anchor_for_kickoff(first_week1_kickoff(schedule, season))
        for season in sorted(set(seasons))
    }


def check_anchor_precedes_kickoff(
    anchors: Mapping[int, SeasonAnchor],
    *,
    stage: str = "anchors",
) -> list[QualityCheck]:
    """Record the invariant the type already enforces, so a build reports it.

    :class:`SeasonAnchor` refuses to exist if the anchor is not strictly before kickoff, so
    this can only ever pass - which is the point. The quality report should say the rule was
    checked rather than leaving a reader to trust the constructor.
    """
    if not anchors:
        return [
            QualityCheck.fail(
                "anchor.none_derived",
                stage=stage,
                message="no draft anchors were derived",
                observed="0 season(s)",
                expected=">= 1",
            ),
        ]
    spans = [anchor.days_before_kickoff for anchor in anchors.values()]
    checks = [
        QualityCheck.ok(
            "anchor.precedes_first_kickoff",
            stage=stage,
            message=(
                f"every anchor uses rule {DRAFT_ANCHOR_RULE_VERSION} and precedes "
                "its season's first regular-season kickoff"
            ),
            observed=(
                f"{len(anchors)} season(s); lead time {min(spans):.2f}-{max(spans):.2f} day(s)"
            ),
        ),
    ]
    # A Tuesday-before-Wednesday opener is one day of lead time; a Tuesday-before-Thursday
    # opener is two. Anything much larger means the opener moved and the rule stepped back a
    # week, which is legal but worth surfacing rather than absorbing.
    outliers = [season for season, anchor in anchors.items() if anchor.days_before_kickoff > 3.0]
    if outliers:
        checks.append(
            QualityCheck.fail(
                "anchor.unusual_lead_time",
                stage=stage,
                message="anchor sits more than three days before kickoff; check the opener",
                observed=", ".join(str(season) for season in sorted(outliers)),
                expected="<= 3 days",
                severity=Severity.WARNING,
            ),
        )
    return checks


def anchors_to_frame(anchors: Mapping[int, SeasonAnchor]) -> pl.DataFrame:
    """Render anchors as a frame for the quality report and the manifest."""
    rows = [
        {
            "season": anchor.season,
            "anchor_at_utc": anchor.anchor_at_utc,
            "anchor_local_date": anchor.anchor_date_local,
            "feature_cutoff_rule_version": anchor.rule_version,
            "first_kickoff_utc": anchor.first_kickoff_utc,
            "first_kickoff_game_id": anchor.first_kickoff_game_id,
        }
        for anchor in sorted(anchors.values(), key=lambda item: item.season)
    ]
    schema: dict[str, pl.DataType | type[pl.DataType]] = {
        "season": pl.Int32,
        "anchor_at_utc": pl.Datetime(time_unit="us", time_zone="UTC"),
        "anchor_local_date": pl.Date,
        "feature_cutoff_rule_version": pl.String,
        "first_kickoff_utc": pl.Datetime(time_unit="us", time_zone="UTC"),
        "first_kickoff_game_id": pl.String,
    }
    if not rows:
        return pl.DataFrame(schema=schema)
    return pl.DataFrame(rows, schema=schema, orient="row")


def _parse_date(text: str) -> date | None:
    try:
        return date.fromisoformat(text.strip()[:10])
    except ValueError:
        return None


def _parse_time(raw: object) -> time | None:
    if isinstance(raw, time):
        return raw
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    parts = text.split(":")
    if len(parts) < 2:
        return None
    try:
        hour, minute = int(parts[0]), int(parts[1])
        second = int(parts[2]) if len(parts) > 2 else 0
    except ValueError:
        return None
    if not (0 <= hour < 24 and 0 <= minute < 60 and 0 <= second < 60):
        return None
    return time(hour, minute, second)


def season_range(first: int, last: int) -> Sequence[int]:
    """Inclusive season range helper used by the CLI and the build config."""
    if last < first:
        raise AnchorError(f"season range {first}-{last} is empty")
    return tuple(range(first, last + 1))
