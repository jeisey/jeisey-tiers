"""Loading the historical source frames.

This module is the only place in the historical pipeline that performs network I/O, and it
does nothing else: every frame it returns has already passed its adapter's schema check and
frame contract, and every finding is a :class:`~ffdraft.contracts.quality.QualityCheck` the
caller collects. Feature engineering happens in :mod:`ffdraft.features.build`, on frames,
with no idea where they came from - which is what makes the whole builder testable from
fixtures without a network (`docs/ARCHITECTURE.md` section 5).

The season windows follow from the feature dictionary rather than from a guess:

* **target seasons** are what the caller asked to build;
* **statistic seasons** extend back by the deepest declared lookback, so a target season's
  five-season prior window is complete;
* **roster seasons** are the target seasons minus one - the previous-season roster is the
  eligibility spine, and the target season's own roster is deliberately never loaded;
* **depth-chart seasons** are the target seasons themselves, because those are the only
  seasons whose pre-anchor snapshots can be filtered to ``observed_at <= anchor``.

Snap counts begin in 2013 upstream and ffopportunity's coverage starts earlier; a season
that returns nothing is recorded as an informational check rather than an error, because
absent history is a documented fact about the source, not a build failure.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

import polars as pl

from ffdraft.contracts import QualityCheck, SourceBatch, SourceMetadata, ValidationReport
from ffdraft.contracts.enums import DepthChartEra, Severity
from ffdraft.features.build import HistoricalSources
from ffdraft.features.dictionary import CAREER_LOOKBACK_SEASONS
from ffdraft.sources.base import RawRecords
from ffdraft.sources.nflverse import NflverseDepthChartAdapter, NflverseRosterAdapter
from ffdraft.sources.nflverse_history import (
    NflverseCombineAdapter,
    NflverseDraftPickAdapter,
    NflverseExpectedPointsAdapter,
    NflversePlayerMasterAdapter,
    NflverseScheduleAdapter,
    NflverseSnapCountAdapter,
    NflverseWeeklyStatsAdapter,
)
from ffdraft.timeutil import utc_now

__all__ = [
    "LoadedSources",
    "NormalizingAdapter",
    "SeasonWindows",
    "load_fixture_sources",
    "load_historical_sources",
    "season_windows",
]

#: Earliest season whose snap counts nflverse publishes with rows. 2012 exists as an empty
#: file, which is why the check below is on row count rather than on the call succeeding.
SNAP_COUNT_FIRST_SEASON = 2013


@dataclass(frozen=True, slots=True)
class SeasonWindows:
    """Which seasons each source has to be loaded for."""

    target: tuple[int, ...]
    statistics: tuple[int, ...]
    rosters: tuple[int, ...]
    depth_charts: tuple[int, ...]

    def describe(self) -> dict[str, list[int]]:
        return {
            "target": list(self.target),
            "statistics": list(self.statistics),
            "rosters": list(self.rosters),
            "depth_charts": list(self.depth_charts),
        }


@dataclass
class LoadedSources:
    """Normalized source frames plus the quality record of loading them."""

    sources: HistoricalSources
    windows: SeasonWindows
    checks: list[QualityCheck]
    metadata: list[SourceMetadata]

    def metadata_records(self) -> list[dict[str, Any]]:
        return [item.to_dict() for item in self.metadata]


def season_windows(
    target_seasons: Sequence[int],
    *,
    include_target_statistics: bool = True,
) -> SeasonWindows:
    """Derive every source's season window from the requested target seasons.

    A historical build needs the target season's own statistics, because that is where the
    labels come from. Current inference has no labels: the target season's statistics are
    either unpublished (it has not been played) or an outcome of the season being predicted,
    and both answers are "do not load them". ``include_target_statistics=False`` says so
    explicitly rather than leaving it to whether nflverse happens to have the file yet.
    """
    targets = tuple(sorted(set(int(season) for season in target_seasons)))
    if not targets:
        raise ValueError("at least one target season is required")
    deepest = max(CAREER_LOOKBACK_SEASONS)
    last_statistics_season = targets[-1] if include_target_statistics else targets[-1] - 1
    statistics = tuple(range(targets[0] - deepest, last_statistics_season + 1))
    rosters = tuple(season - 1 for season in targets)
    return SeasonWindows(
        target=targets,
        statistics=statistics,
        rosters=rosters,
        depth_charts=tuple(
            season
            for season in targets
            if DepthChartEra.for_season(season).supports_point_in_time_anchor
        ),
    )


class NormalizingAdapter(Protocol):
    """What :func:`_run` needs from an adapter.

    ``normalize`` is declared as an open callable because each adapter takes the extra
    arguments its source actually needs - the roster adapter needs a season, the depth-chart
    adapter carries its era on the instance. Pinning one signature here would force every
    adapter to accept parameters it has no use for.
    """

    source_id: str

    def check_source_schema(self, records: RawRecords) -> list[QualityCheck]: ...

    def validate_raw(self, batch: SourceBatch) -> ValidationReport: ...

    @property
    def normalize(self) -> Callable[..., SourceBatch]: ...


def _run(
    adapter: NormalizingAdapter,
    frame: RawRecords,
    checks: list[QualityCheck],
    metadata: list[SourceMetadata],
    *,
    as_of: datetime,
    **normalize_kwargs: Any,
) -> pl.DataFrame:
    """Schema-check, normalize and contract-validate one raw payload."""
    checks.extend(adapter.check_source_schema(frame))
    batch: SourceBatch = adapter.normalize(frame, retrieved_at=as_of, **normalize_kwargs)
    checks.extend(adapter.validate_raw(batch).checks)
    metadata.append(batch.metadata)
    return batch.frame


def load_historical_sources(
    *,
    target_seasons: Sequence[int],
    as_of: datetime | None = None,
    timeout_seconds: float = 60.0,
    include_target_statistics: bool = True,
) -> LoadedSources:
    """Fetch and normalize every source the historical build needs.

    Imports ``nflreadpy`` lazily so that importing this module - which the network-free
    tests do, for :func:`season_windows` - never pulls in the loader.
    """
    import nflreadpy

    retrieved_at = as_of or utc_now()
    windows = season_windows(
        target_seasons,
        include_target_statistics=include_target_statistics,
    )
    checks: list[QualityCheck] = []
    metadata: list[SourceMetadata] = []
    del timeout_seconds  # nflreadpy manages its own HTTP timeouts

    schedule = _run(
        NflverseScheduleAdapter(),
        nflreadpy.load_schedules(),
        checks,
        metadata,
        as_of=retrieved_at,
    )
    player_master = _run(
        NflversePlayerMasterAdapter(),
        nflreadpy.load_players(),
        checks,
        metadata,
        as_of=retrieved_at,
    )
    draft_picks = _run(
        NflverseDraftPickAdapter(),
        nflreadpy.load_draft_picks(),
        checks,
        metadata,
        as_of=retrieved_at,
    )
    combine = _run(
        NflverseCombineAdapter(),
        nflreadpy.load_combine(),
        checks,
        metadata,
        as_of=retrieved_at,
    )

    weekly_adapter = NflverseWeeklyStatsAdapter()
    snap_adapter = NflverseSnapCountAdapter()
    expected_adapter = NflverseExpectedPointsAdapter()

    weekly_frames: list[pl.DataFrame] = []
    snap_frames: list[pl.DataFrame] = []
    expected_frames: list[pl.DataFrame] = []

    for season in windows.statistics:
        weekly_frames.append(
            _run(
                weekly_adapter,
                nflreadpy.load_player_stats(seasons=[season], summary_level="week"),
                checks,
                metadata,
                as_of=retrieved_at,
            ),
        )
        if season >= SNAP_COUNT_FIRST_SEASON:
            snap_frame = _run(
                snap_adapter,
                nflreadpy.load_snap_counts(seasons=[season]),
                checks,
                metadata,
                as_of=retrieved_at,
            )
            if snap_frame.is_empty():
                checks.append(
                    QualityCheck.fail(
                        "source.snap_counts_empty",
                        stage="nflreadpy",
                        message=f"{season} snap counts returned no rows",
                        observed="0 rows",
                        expected="> 0",
                        severity=Severity.WARNING,
                    ),
                )
            snap_frames.append(snap_frame)
        expected_frames.append(
            _run(
                expected_adapter,
                nflreadpy.load_ff_opportunity(seasons=[season], stat_type="weekly"),
                checks,
                metadata,
                as_of=retrieved_at,
            ),
        )

    roster_adapter = NflverseRosterAdapter()
    rosters: dict[int, pl.DataFrame] = {}
    for season in windows.rosters:
        rosters[season] = _run(
            roster_adapter,
            nflreadpy.load_rosters(seasons=[season]),
            checks,
            metadata,
            as_of=retrieved_at,
            season=season,
        )

    depth_charts: dict[int, pl.DataFrame] = {}
    for season in windows.depth_charts:
        depth_charts[season] = _run(
            NflverseDepthChartAdapter(season=season),
            nflreadpy.load_depth_charts(seasons=[season]),
            checks,
            metadata,
            as_of=retrieved_at,
        )

    sources = HistoricalSources(
        weekly_stats=_concat(weekly_frames),
        schedule=schedule,
        rosters=rosters,
        depth_charts=depth_charts,
        snap_counts=_concat(snap_frames),
        expected_points=_concat(expected_frames),
        draft_picks=draft_picks,
        combine=combine,
        player_master=player_master,
    )
    return LoadedSources(sources=sources, windows=windows, checks=checks, metadata=metadata)


def _concat(frames: Sequence[pl.DataFrame]) -> pl.DataFrame:
    non_empty = [frame for frame in frames if not frame.is_empty()]
    if not non_empty:
        return frames[0] if frames else pl.DataFrame()
    return pl.concat(non_empty, how="vertical")


# --------------------------------------------------------------------------------------
# Fixture loading
# --------------------------------------------------------------------------------------


#: Fixture files the network-free historical tests read. Season-scoped sources are named
#: with their season so the loader cannot accidentally hand the builder a target-season
#: roster: the mapping is explicit, and a test asserts the target season's roster is absent.
_FIXTURE_ROSTER_SEASONS = (2023, 2024)
_FIXTURE_DEPTH_SEASONS = (2024, 2025)


def load_fixture_sources(directory: Path) -> LoadedSources:
    """Load the committed synthetic historical fixtures through the real adapters.

    The point of routing fixtures through ``normalize`` rather than constructing frames
    directly is that the integration test then exercises the adapters, the contracts and the
    builder together - the same path production takes, minus the network.
    """
    import json

    def read(name: str) -> list[dict[str, Any]]:
        payload = json.loads((directory / f"{name}.json").read_text(encoding="utf-8"))
        return [dict(record) for record in payload]

    retrieved_at = utc_now()
    checks: list[QualityCheck] = []
    metadata: list[SourceMetadata] = []

    schedule = _run(
        NflverseScheduleAdapter(),
        read("schedule"),
        checks,
        metadata,
        as_of=retrieved_at,
    )
    weekly = _run(
        NflverseWeeklyStatsAdapter(),
        read("weekly_stats"),
        checks,
        metadata,
        as_of=retrieved_at,
    )
    snaps = _run(
        NflverseSnapCountAdapter(),
        read("snap_counts"),
        checks,
        metadata,
        as_of=retrieved_at,
    )
    expected = _run(
        NflverseExpectedPointsAdapter(),
        read("expected_points"),
        checks,
        metadata,
        as_of=retrieved_at,
    )
    draft_picks = _run(
        NflverseDraftPickAdapter(),
        read("draft_picks"),
        checks,
        metadata,
        as_of=retrieved_at,
    )
    combine = _run(
        NflverseCombineAdapter(),
        read("combine"),
        checks,
        metadata,
        as_of=retrieved_at,
    )
    player_master = _run(
        NflversePlayerMasterAdapter(),
        read("players"),
        checks,
        metadata,
        as_of=retrieved_at,
    )

    roster_adapter = NflverseRosterAdapter()
    rosters = {
        season: _run(
            roster_adapter,
            read(f"rosters_{season}"),
            checks,
            metadata,
            as_of=retrieved_at,
            season=season,
        )
        for season in _FIXTURE_ROSTER_SEASONS
    }
    depth_charts = {
        season: _run(
            NflverseDepthChartAdapter(season=season),
            read(f"depth_charts_{season}"),
            checks,
            metadata,
            as_of=retrieved_at,
        )
        for season in _FIXTURE_DEPTH_SEASONS
    }

    sources = HistoricalSources(
        weekly_stats=weekly,
        schedule=schedule,
        rosters=rosters,
        depth_charts=depth_charts,
        snap_counts=snaps,
        expected_points=expected,
        draft_picks=draft_picks,
        combine=combine,
        player_master=player_master,
    )
    return LoadedSources(
        sources=sources,
        windows=season_windows(FIXTURE_TARGET_SEASONS),
        checks=checks,
        metadata=metadata,
    )


#: Target seasons the fixtures support: 2024 sits in the lagged-only era and 2025 in the
#: snapshot era, so one fixture build exercises both sides of the ADR-018 boundary.
FIXTURE_TARGET_SEASONS: tuple[int, ...] = (2024, 2025)
