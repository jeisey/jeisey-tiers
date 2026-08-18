"""nflverse adapters (via ``nflreadpy``).

nflverse is the intrinsic spine: rosters supply the canonical player set and the id
crosswalk, depth charts supply role context. `config/source-registry.yaml` marks it
``production_allowed`` and ``critical``, so an empty payload here is a build-stopping
failure rather than a degraded mode (`docs/DATA_SOURCES.md` section 10).

Three measured facts from Phase 0 shape this module:

* rosters carry ``espn_id`` and ``sleeper_id`` directly, which is why the primary market
  bridge and the Sleeper join are both nflverse-native (ADR-019);
* ``load_ff_playerids`` comes from the dynastyprocess mirror, which publishes no licence,
  so it is the *secondary* bridge and never the only evidence for a production join;
* depth charts changed schema at 2025 and the two eras are normalized separately, because
  a single schema assumption silently produces nulls (ADR-015).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

import polars as pl

from ffdraft.contracts import (
    DEPTH_CHART_CONTRACT,
    PLAYER_IDS_CONTRACT,
    ROSTER_CONTRACT,
    DepthChartEra,
    QualityCheck,
    SourceBatch,
)
from ffdraft.contracts.enums import Severity
from ffdraft.identity.ids import IdNamespace, NormalizedId, normalize_id
from ffdraft.sources.base import BaseSourceAdapter, RawRecords, SourceConfig, as_rows
from ffdraft.timeutil import parse_utc, utc_now

__all__ = [
    "NFLVERSE_SOURCE_ID",
    "FlagCounter",
    "NflverseDepthChartAdapter",
    "NflversePlayerIdsAdapter",
    "NflverseRosterAdapter",
]

NFLVERSE_SOURCE_ID = "nflreadpy"

# Recorded in the registry as "nflverse data broadly CC-BY-4.0; FTN subsets CC-BY-SA-4.0".
_NFLVERSE_LICENSE = "nflverse-cc-by-4.0/2026-08-17"


class FlagCounter:
    """Accumulates per-row id-hygiene findings into batch-level warning codes.

    Per-row flags would drown a 3,000-row roster in noise. What a build actually needs to
    know is *how many* ids were malformed and of which kind, so the counts land in the
    source metadata's ``detail`` and the kinds become warning codes.
    """

    def __init__(self) -> None:
        self.counts: Counter[str] = Counter()

    def take(self, normalized: NormalizedId) -> str | None:
        if normalized.reason:
            self.counts[normalized.reason] += 1
        return normalized.value

    def note(self, code: str, amount: int = 1) -> None:
        if amount:
            self.counts[code] += amount

    @property
    def codes(self) -> tuple[str, ...]:
        return tuple(sorted(self.counts))

    @property
    def detail(self) -> dict[str, str]:
        return {code: str(count) for code, count in sorted(self.counts.items())}


def _text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _int(value: object) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return None


def _date(value: object) -> Any:
    """Pass a date through; parse an ISO date string. Anything else becomes ``None``."""
    if value is None or isinstance(value, datetime):
        return value.date() if isinstance(value, datetime) else None
    if hasattr(value, "isoformat") and not isinstance(value, str):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text[:10]).date()
    except ValueError:
        return None


class NflverseRosterAdapter(BaseSourceAdapter):
    """``load_rosters(season)`` -> the canonical player spine for one season."""

    source_id = NFLVERSE_SOURCE_ID
    resource = "load_rosters"
    adapter_version = "1.0"
    contract = ROSTER_CONTRACT
    recorded_schema_fixture = "nflverse_rosters_2026"
    license_policy_version = _NFLVERSE_LICENSE
    min_expected_records = 1
    required_source_columns = frozenset(
        {
            "season",
            "gsis_id",
            "full_name",
            "position",
            "team",
            "status",
            "depth_chart_position",
            "espn_id",
            "sleeper_id",
            "pfr_id",
            "sportradar_id",
            "yahoo_id",
            "birth_date",
            "years_exp",
            "rookie_year",
        },
    )

    def normalize(
        self,
        records: RawRecords,
        *,
        season: int,
        retrieved_at: datetime | None = None,
    ) -> SourceBatch:
        flags = FlagCounter()
        rows: list[dict[str, Any]] = []
        dropped_without_gsis = 0

        for record in as_rows(records):
            gsis = flags.take(normalize_id(IdNamespace.GSIS, record.get("gsis_id")))
            if gsis is None:
                # A roster row with no canonical id cannot join to anything downstream.
                # Dropping it is a normalization decision, so it is counted, not silent.
                dropped_without_gsis += 1
                continue
            rows.append(
                {
                    "season": _int(record.get("season")) or season,
                    "gsis_id": gsis,
                    "display_name": _text(record.get("full_name"))
                    or _text(record.get("football_name"))
                    or gsis,
                    "position": _text(record.get("position")) or "",
                    "team": _text(record.get("team")),
                    "status": _text(record.get("status")),
                    "depth_chart_position": _text(record.get("depth_chart_position")),
                    "espn_id": flags.take(normalize_id(IdNamespace.ESPN, record.get("espn_id"))),
                    "sleeper_id": flags.take(
                        normalize_id(IdNamespace.SLEEPER, record.get("sleeper_id")),
                    ),
                    "pfr_id": flags.take(normalize_id(IdNamespace.PFR, record.get("pfr_id"))),
                    "sportradar_id": flags.take(
                        normalize_id(IdNamespace.SPORTRADAR, record.get("sportradar_id")),
                    ),
                    "yahoo_id": flags.take(normalize_id(IdNamespace.YAHOO, record.get("yahoo_id"))),
                    "birth_date": _date(record.get("birth_date")),
                    "years_exp": _int(record.get("years_exp")),
                    "rookie_season": _int(record.get("rookie_year")),
                }
            )

        flags.note("roster_rows_without_gsis_id", dropped_without_gsis)
        return self.build_batch(
            self.contract.build(rows),
            retrieved_at=retrieved_at,
            warning_codes=flags.codes,
            detail={"season": str(season), **flags.detail},
        )

    def fetch(self, *, as_of: datetime, config: SourceConfig) -> SourceBatch:
        import nflreadpy

        frame = nflreadpy.load_rosters(seasons=[config.season])
        checks = self.check_source_schema(frame)
        batch = self.normalize(frame, season=config.season, retrieved_at=as_of or utc_now())
        blocking = [check.check_id for check in checks if check.blocking]
        if blocking:
            return self.build_batch(
                batch.frame,
                retrieved_at=batch.metadata.retrieved_at_utc,
                warning_codes=(*batch.metadata.warning_codes, *blocking),
                detail=dict(batch.metadata.detail),
            )
        return batch

    def semantic_checks(self, batch: SourceBatch) -> Sequence[QualityCheck]:
        """Rosters must be one season and must carry usable skill-position rows."""
        if batch.frame.is_empty():
            return ()
        seasons = batch.frame.get_column("season").unique().to_list()
        if len(seasons) > 1:
            return (
                QualityCheck.fail(
                    "nflverse_roster.mixed_seasons",
                    stage=self.source_id,
                    message="a roster batch must describe exactly one season",
                    observed=", ".join(str(season) for season in sorted(seasons)),
                    expected="1 season",
                ),
            )
        return ()


class NflversePlayerIdsAdapter(BaseSourceAdapter):
    """``load_ff_playerids()`` -> the secondary ``mfl_id`` bridge.

    This mirror publishes no licence (registry ``ff_playerids_unlicensed_mirror``), so it
    exists to cross-check the nflverse-native bridge, never to be the sole evidence behind
    a production join.
    """

    source_id = NFLVERSE_SOURCE_ID
    resource = "load_ff_playerids"
    adapter_version = "1.0"
    contract = PLAYER_IDS_CONTRACT
    recorded_schema_fixture = "nflverse_ff_playerids"
    license_policy_version = "dynastyprocess-mirror-unlicensed/2026-08-17"
    min_expected_records = 1
    required_source_columns = frozenset(
        {"mfl_id", "gsis_id", "espn_id", "sleeper_id", "pfr_id", "name", "position", "team"},
    )

    def normalize(
        self,
        records: RawRecords,
        *,
        retrieved_at: datetime | None = None,
    ) -> SourceBatch:
        flags = FlagCounter()
        rows: list[dict[str, Any]] = []
        dropped = 0

        for record in as_rows(records):
            mfl = flags.take(normalize_id(IdNamespace.MFL, record.get("mfl_id")))
            if mfl is None:
                dropped += 1
                continue
            rows.append(
                {
                    "mfl_id": mfl,
                    "gsis_id": flags.take(normalize_id(IdNamespace.GSIS, record.get("gsis_id"))),
                    "espn_id": flags.take(normalize_id(IdNamespace.ESPN, record.get("espn_id"))),
                    "sleeper_id": flags.take(
                        normalize_id(IdNamespace.SLEEPER, record.get("sleeper_id")),
                    ),
                    "pfr_id": flags.take(normalize_id(IdNamespace.PFR, record.get("pfr_id"))),
                    "sportradar_id": flags.take(
                        normalize_id(IdNamespace.SPORTRADAR, record.get("sportradar_id")),
                    ),
                    "yahoo_id": flags.take(normalize_id(IdNamespace.YAHOO, record.get("yahoo_id"))),
                    "name": _text(record.get("name")),
                    "position": _text(record.get("position")),
                    "team": _text(record.get("team")),
                }
            )

        flags.note("player_ids_rows_without_mfl_id", dropped)
        return self.build_batch(
            self.contract.build(rows),
            retrieved_at=retrieved_at,
            warning_codes=flags.codes,
            detail=flags.detail,
        )

    def fetch(self, *, as_of: datetime, config: SourceConfig) -> SourceBatch:
        import nflreadpy

        frame = nflreadpy.load_ff_playerids()
        self.check_source_schema(frame)
        return self.normalize(frame, retrieved_at=as_of or utc_now())


# Columns each depth-chart era supplies. Recorded from the Phase-0 fixtures, not guessed.
_WEEKLY_COLUMNS = frozenset(
    {"season", "club_code", "week", "depth_team", "gsis_id", "position", "depth_position"},
)
_SNAPSHOT_COLUMNS = frozenset({"dt", "team", "gsis_id", "espn_id", "pos_abb", "pos_rank"})


class NflverseDepthChartAdapter(BaseSourceAdapter):
    """``load_depth_charts(season)`` -> depth observations, normalized across both eras.

    The adapter is constructed per season because the era decides the upstream schema *and*
    whether the output can legitimately carry a point-in-time timestamp (ADR-015/ADR-018).
    """

    source_id = NFLVERSE_SOURCE_ID
    resource = "load_depth_charts"
    adapter_version = "1.0"
    contract = DEPTH_CHART_CONTRACT
    license_policy_version = _NFLVERSE_LICENSE
    min_expected_records = 1

    def __init__(self, *, season: int) -> None:
        self.season = season
        self.era = DepthChartEra.for_season(season)
        snapshot = self.era.supports_point_in_time_anchor
        self.required_source_columns = _SNAPSHOT_COLUMNS if snapshot else _WEEKLY_COLUMNS
        self.recorded_schema_fixture = (
            "nflverse_depth_charts_2025" if snapshot else "nflverse_depth_charts_2024"
        )

    def normalize(
        self,
        records: RawRecords,
        *,
        retrieved_at: datetime | None = None,
    ) -> SourceBatch:
        flags = FlagCounter()
        rows: list[dict[str, Any]] = []
        latest: datetime | None = None

        for record in as_rows(records):
            if self.era.supports_point_in_time_anchor:
                observed = self._snapshot_timestamp(record.get("dt"), flags)
                if observed is None:
                    continue
                latest = observed if latest is None else max(latest, observed)
                team = _text(record.get("team"))
                position = _text(record.get("pos_abb"))
                depth_rank = _int(record.get("pos_rank"))
                week = None
                name = _text(record.get("player_name"))
            else:
                observed = None
                team = _text(record.get("club_code"))
                # Pre-2025 rows carry both a roster position and a slot label; the slot
                # (`depth_position`, e.g. "RG") is the depth-chart meaning.
                position = _text(record.get("depth_position")) or _text(record.get("position"))
                depth_rank = _int(record.get("depth_team"))
                week = _int(record.get("week"))
                name = _text(record.get("full_name"))
            if team is None:
                flags.note("depth_row_without_team")
                continue
            rows.append(
                {
                    "source_id": self.source_id,
                    "season": self.season,
                    "era": str(self.era),
                    "team": team,
                    "position": position,
                    "depth_rank": depth_rank,
                    "gsis_id": flags.take(normalize_id(IdNamespace.GSIS, record.get("gsis_id"))),
                    "espn_id": flags.take(normalize_id(IdNamespace.ESPN, record.get("espn_id"))),
                    "player_name": name,
                    "observed_at_utc": observed,
                    "week": week,
                }
            )

        return self.build_batch(
            self.contract.build(rows),
            retrieved_at=retrieved_at,
            # The latest snapshot timestamp is a genuine data-as-of time. The weekly era has
            # none, and inventing one would fabricate point-in-time availability.
            source_as_of=latest,
            warning_codes=flags.codes,
            detail={"season": str(self.season), "era": str(self.era), **flags.detail},
        )

    def _snapshot_timestamp(self, raw: object, flags: FlagCounter) -> datetime | None:
        if isinstance(raw, datetime):
            return raw
        text = _text(raw)
        if text is None:
            flags.note("depth_snapshot_without_timestamp")
            return None
        try:
            return parse_utc(text)
        except ValueError:
            flags.note("depth_snapshot_unparseable_timestamp")
            return None

    def fetch(self, *, as_of: datetime, config: SourceConfig) -> SourceBatch:
        import nflreadpy

        if config.season != self.season:
            raise ValueError(
                f"adapter built for season {self.season} cannot fetch {config.season}: "
                "the era determines the upstream schema",
            )
        frame = nflreadpy.load_depth_charts(seasons=[self.season])
        self.check_source_schema(frame)
        return self.normalize(frame, retrieved_at=as_of or utc_now())

    def semantic_checks(self, batch: SourceBatch) -> Sequence[QualityCheck]:
        """The era invariant that ADR-018's leakage test depends on."""
        if batch.frame.is_empty():
            return ()
        checks: list[QualityCheck] = []
        timestamps = batch.frame.get_column("observed_at_utc")
        if self.era.supports_point_in_time_anchor:
            missing = int(timestamps.null_count())
            if missing:
                checks.append(
                    QualityCheck.fail(
                        "depth_chart.snapshot_missing_timestamp",
                        stage=self.source_id,
                        message="snapshot-era rows must carry an observation timestamp",
                        observed=f"{missing} row(s) without dt",
                        expected="0",
                    ),
                )
        else:
            stamped = batch.frame.height - int(timestamps.null_count())
            if stamped:
                checks.append(
                    QualityCheck.fail(
                        "depth_chart.weekly_era_timestamped",
                        stage=self.source_id,
                        message=(
                            "weekly-era rows must not carry a timestamp: it would imply a "
                            "point-in-time reading the source cannot support (ADR-018)"
                        ),
                        observed=f"{stamped} row(s)",
                        expected="0",
                    ),
                )
            checks.append(
                QualityCheck.fail(
                    "depth_chart.no_preseason_observation",
                    stage=self.source_id,
                    message=(
                        f"{self.season} depth charts begin at week 1, after a typical draft; "
                        "anchor depth must come from a prior-season role proxy (ADR-018)"
                    ),
                    observed=f"era={self.era}",
                    expected="snapshot era for point-in-time anchor depth",
                    severity=Severity.INFO,
                ),
            )
        return checks


def normalized_depth_is_anchor_safe(frame: pl.DataFrame, anchor: datetime) -> bool:
    """Whether every row in a normalized depth frame is usable at ``anchor``.

    Phase 2 owns anchor-depth feature construction; this predicate exists now so the rule
    lives beside the adapter that knows the eras, and so a Phase-1 test can pin it.
    """
    if frame.is_empty():
        return True
    weekly = frame.filter(pl.col("era") == str(DepthChartEra.WEEKLY_PRE_2025))
    if weekly.height:
        return False
    stamps = frame.get_column("observed_at_utc")
    if stamps.null_count():
        return False
    return bool(stamps.max() <= anchor)  # type: ignore[operator]


def merge_crosswalk_frames(
    roster: pl.DataFrame,
    player_ids: pl.DataFrame,
) -> Mapping[str, str]:
    """Map ``mfl_id -> gsis_id`` from the secondary bridge, restricted to known players.

    Restricting to gsis ids the roster already knows keeps the unlicensed mirror from
    introducing players nflverse does not have.
    """
    known = set(roster.get_column("gsis_id").drop_nulls().to_list())
    pairs = player_ids.select("mfl_id", "gsis_id").drop_nulls().iter_rows()
    return {mfl: gsis for mfl, gsis in pairs if gsis in known}
