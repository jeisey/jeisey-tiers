"""NFL Next Gen Stats via nflverse (``load_nextgen_stats``), for the Skill Tree only (ADR-107).

Three files, one per ``stat_type`` (passing, rushing, receiving), each one row per player ×
week, where **week 0 is the regular-season summary** — to date while a season is in progress
(the nflreadr loader documentation: "Regular season summary is given for `week == 0`").
Weekly rows exist only for weeks a player met NGS's display threshold (observed: 15 attempts,
10 rushes, 5 targets), so they are never summed into a season figure: the Skill Tree reads the
summary row alone, and only after checking it covers exactly the board's window
(:func:`ffdraft.signals.skilltree.ngs_season_readings`).

**Published context, never a feature.** No model reads this frame. Licensing: nflverse's data
is broadly CC-BY 4.0 with the NFL as the underlying owner, as for every NFL-originated statistic
the site publishes; there is no NGS-specific licence. Only per-player season aggregates are
published, attributed "NFL Next Gen Stats via nflverse" (registry: nflreadpy
``nextgen_stats_publication``).

Each adapter follows the house split: a pure ``normalize`` the fixture tests drive, and a
``fetch`` only the opt-in live tests touch.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import polars as pl

from ffdraft.contracts import NEXTGEN_STATS_CONTRACT, SourceBatch
from ffdraft.identity.ids import IdNamespace, normalize_id
from ffdraft.sources.base import BaseSourceAdapter, RawRecords, SourceConfig, as_rows
from ffdraft.sources.nflverse import NFLVERSE_SOURCE_ID, FlagCounter
from ffdraft.sources.nflverse_http import nflverse_loaders
from ffdraft.timeutil import utc_now

__all__ = [
    "NEXTGEN_STAT_TYPES",
    "NflverseNextGenPassingAdapter",
    "NflverseNextGenReceivingAdapter",
    "NflverseNextGenRushingAdapter",
    "load_nextgen_frames",
]

NEXTGEN_STAT_TYPES: tuple[str, ...] = ("passing", "rushing", "receiving")

_NFLVERSE_LICENSE = "nflverse-cc-by-4.0/2026-08-17"


def _number(value: object) -> float | None:
    if value is None or value == "":
        return None
    try:
        parsed = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return None if parsed != parsed else parsed


def _integer(value: object) -> int | None:
    parsed = _number(value)
    return None if parsed is None else int(parsed)


class _NextGenAdapter(BaseSourceAdapter):
    source_id = NFLVERSE_SOURCE_ID
    adapter_version = "1.0"
    contract = NEXTGEN_STATS_CONTRACT
    license_policy_version = _NFLVERSE_LICENSE
    min_expected_records = 1
    stat_type: str = ""
    #: The upstream volume column this stat type counts in.
    volume_column: str = ""
    #: Upstream column -> normalized column, for the readings this stat type carries.
    readings: dict[str, str] = {}

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
            gsis = flags.take(normalize_id(IdNamespace.GSIS, record.get("player_gsis_id")))
            season = _integer(record.get("season"))
            week = _integer(record.get("week"))
            season_type = record.get("season_type")
            if gsis is None or season is None or week is None or season_type is None:
                dropped += 1
                continue
            row: dict[str, Any] = {
                "season": season,
                "season_type": str(season_type),
                "week": week,
                "stat_type": self.stat_type,
                "gsis_id": gsis,
                "position": record.get("player_position"),
                "volume": _number(record.get(self.volume_column)),
                "receptions": (
                    _number(record.get("receptions")) if self.stat_type == "receiving" else None
                ),
            }
            for upstream, column in self.readings.items():
                row[column] = _number(record.get(upstream))
            rows.append(row)
        flags.note("nextgen_rows_without_key", dropped)
        return self.build_batch(
            self.contract.build(rows),
            retrieved_at=retrieved_at,
            warning_codes=flags.codes,
            detail=flags.detail,
        )

    def fetch(self, *, as_of: datetime, config: SourceConfig) -> SourceBatch:
        nflreadpy = nflverse_loaders()
        frame = nflreadpy.load_nextgen_stats(seasons=[config.season], stat_type=self.stat_type)
        self.check_source_schema(frame)
        return self.normalize(frame, retrieved_at=as_of or utc_now())


_KEY_COLUMNS = frozenset({"season", "season_type", "week", "player_gsis_id", "player_position"})


class NflverseNextGenPassingAdapter(_NextGenAdapter):
    resource = "load_nextgen_stats(stat_type='passing')"
    recorded_schema_fixture = "nflverse_nextgen_passing_2026"
    stat_type = "passing"
    volume_column = "attempts"
    readings = {"avg_time_to_throw": "avg_time_to_throw"}
    required_source_columns = _KEY_COLUMNS | {"attempts", "avg_time_to_throw"}


class NflverseNextGenRushingAdapter(_NextGenAdapter):
    resource = "load_nextgen_stats(stat_type='rushing')"
    recorded_schema_fixture = "nflverse_nextgen_rushing_2026"
    stat_type = "rushing"
    volume_column = "rush_attempts"
    readings = {"rush_yards_over_expected_per_att": "rush_yards_over_expected_per_att"}
    required_source_columns = _KEY_COLUMNS | {
        "rush_attempts",
        "rush_yards_over_expected_per_att",
    }


class NflverseNextGenReceivingAdapter(_NextGenAdapter):
    resource = "load_nextgen_stats(stat_type='receiving')"
    recorded_schema_fixture = "nflverse_nextgen_receiving_2026"
    stat_type = "receiving"
    volume_column = "targets"
    readings = {
        "avg_separation": "avg_separation",
        "avg_cushion": "avg_cushion",
        "avg_yac_above_expectation": "avg_yac_above_expectation",
    }
    required_source_columns = _KEY_COLUMNS | {
        "targets",
        "receptions",
        "avg_separation",
        "avg_cushion",
        "avg_yac_above_expectation",
    }


_ADAPTERS: dict[str, type[_NextGenAdapter]] = {
    "passing": NflverseNextGenPassingAdapter,
    "rushing": NflverseNextGenRushingAdapter,
    "receiving": NflverseNextGenReceivingAdapter,
}


def load_nextgen_frames(season: int) -> dict[str, pl.DataFrame]:
    """The three normalized frames for ``season``, through the retrying nflverse loader.

    Raises when a file cannot be read or has lost a column the adapter reads: the caller
    (an optional enrichment) turns that into "unavailable" for this build.
    """
    loaders = nflverse_loaders()
    frames: dict[str, pl.DataFrame] = {}
    for stat_type, adapter_type in _ADAPTERS.items():
        adapter = adapter_type()
        raw = loaders.load_nextgen_stats(seasons=[season], stat_type=stat_type)
        raw_frame = raw if isinstance(raw, pl.DataFrame) else pl.DataFrame(raw)
        for check in adapter.check_source_schema(raw_frame):
            if check.check_id == "source_schema.missing_columns":
                raise ValueError(f"{adapter.resource} lost columns: {check.observed}")
        frames[stat_type] = adapter.normalize(raw_frame).frame
    return frames
