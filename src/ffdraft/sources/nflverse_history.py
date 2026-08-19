"""nflverse adapters for the historical modelling dataset.

Phase 1's adapters cover the *current* state - rosters, depth charts, the id crosswalk.
Phase 2 needs history: weekly production, snap counts, the schedule that anchors each
season, draft capital, combine measurements, the biographical player master, and
ffopportunity's expected points.

Each adapter follows the Phase-1 split exactly (`ffdraft.sources.base`): a pure
``normalize`` that every fixture test drives, and an I/O ``fetch`` that only the opt-in
live tests touch. Each declares ``required_source_columns`` and the recorded schema fixture
it was written against, so a renamed upstream column becomes a critical quality record at
the boundary instead of a column of nulls in a 2016 feature row.

Two normalization decisions carry temporal meaning and are made here rather than downstream:

* **Draft picks lose their career-outcome columns.** ``load_draft_picks`` publishes games,
  approximate value, Pro Bowls and career statistics next to round and pick. Those are
  knowledge from after the draft. The contract excludes them, so no later ``select`` can
  readmit them by accident (:data:`~ffdraft.contracts.DRAFT_PICK_CONTRACT`).
* **The player master keeps only biography.** ``status``, ``latest_team``, ``last_season``
  and ``years_of_experience`` describe a player today, not at a historical anchor, so they
  never enter the normalized frame.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime
from typing import Any, cast

import polars as pl

from ffdraft.contracts import (
    COMBINE_CONTRACT,
    DRAFT_PICK_CONTRACT,
    EXPECTED_POINTS_CONTRACT,
    PLAYER_MASTER_CONTRACT,
    SCHEDULE_CONTRACT,
    SNAP_COUNTS_CONTRACT,
    WEEKLY_STATS_CONTRACT,
    QualityCheck,
    SourceBatch,
)
from ffdraft.contracts.enums import normalize_team_code
from ffdraft.identity.ids import IdNamespace, normalize_id
from ffdraft.scoring.horizon import regular_season_weeks
from ffdraft.sources.base import BaseSourceAdapter, RawRecords, SourceConfig, as_rows
from ffdraft.sources.nflverse import NFLVERSE_SOURCE_ID, FlagCounter
from ffdraft.timeutil import utc_now

__all__ = [
    "FFOPPORTUNITY_SOURCE_ID",
    "NflverseCombineAdapter",
    "NflverseDraftPickAdapter",
    "NflverseExpectedPointsAdapter",
    "NflversePlayerMasterAdapter",
    "NflverseScheduleAdapter",
    "NflverseSnapCountAdapter",
    "NflverseWeeklyStatsAdapter",
]

_NFLVERSE_LICENSE = "nflverse-cc-by-4.0/2026-08-17"

#: ffopportunity is a separate ffverse project with its own share-alike licence, so it gets
#: its own source id rather than being folded into ``nflreadpy``.
FFOPPORTUNITY_SOURCE_ID = "ffopportunity"
_FFOPPORTUNITY_LICENSE = "ffopportunity-cc-by-sa-4.0/2026-08-17"

_INCHES_PER_FOOT = 12


def _text(value: object) -> str | None:
    if value is None:
        return None
    rendered = str(value).strip()
    return rendered or None


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


def _zero(value: object) -> float:
    parsed = _number(value)
    return 0.0 if parsed is None else parsed


def _sum(record: dict[str, Any], *names: str) -> float:
    return sum(_zero(record.get(name)) for name in names)


def _as_date(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = _text(value)
    if text is None:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _height_to_inches(value: object) -> float | None:
    """Accept ``"6-2"``, ``"6'2"`` and a plain inch count; anything else is missing."""
    if value is None:
        return None
    if isinstance(value, int | float):
        return float(value)
    text = str(value).strip().replace("'", "-").replace('"', "")
    if not text:
        return None
    if "-" in text:
        feet, _, inches = text.partition("-")
        try:
            return float(int(feet) * _INCHES_PER_FOOT + int(inches or 0))
        except ValueError:
            return None
    return _number(text)


class NflverseWeeklyStatsAdapter(BaseSourceAdapter):
    """``load_player_stats(summary_level="week")`` -> scorable weekly production.

    The weekly grain is not a preference. `docs/MODELING.md` section 3 excludes the final
    NFL week from every fantasy label, and the season-level loader has already summed it in,
    so weekly rows are the only source from which the project's own label can be built.
    """

    source_id = NFLVERSE_SOURCE_ID
    resource = "load_player_stats(summary_level='week')"
    adapter_version = "1.0"
    contract = WEEKLY_STATS_CONTRACT
    recorded_schema_fixture = "nflverse_player_stats_weekly_2024"
    license_policy_version = _NFLVERSE_LICENSE
    min_expected_records = 1
    required_source_columns = frozenset(
        {
            "season",
            "week",
            "season_type",
            "player_id",
            "player_display_name",
            "position",
            "team",
            "opponent_team",
            "attempts",
            "completions",
            "passing_yards",
            "passing_tds",
            "passing_interceptions",
            "passing_air_yards",
            "passing_2pt_conversions",
            "carries",
            "rushing_yards",
            "rushing_tds",
            "rushing_2pt_conversions",
            "targets",
            "receptions",
            "receiving_yards",
            "receiving_tds",
            "receiving_air_yards",
            "receiving_2pt_conversions",
            "rushing_fumbles_lost",
            "receiving_fumbles_lost",
            "sack_fumbles_lost",
            "fumbles_lost_total",
            "special_teams_tds",
            "fantasy_points",
            "fantasy_points_ppr",
        },
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
            gsis = flags.take(normalize_id(IdNamespace.GSIS, record.get("player_id")))
            season = _integer(record.get("season"))
            week = _integer(record.get("week"))
            if gsis is None or season is None or week is None:
                dropped += 1
                continue
            rows.append(
                {
                    "season": season,
                    "week": week,
                    "season_type": _text(record.get("season_type")) or "REG",
                    "gsis_id": gsis,
                    "display_name": _text(record.get("player_display_name")),
                    "position": _text(record.get("position")),
                    "team": _text(record.get("team")),
                    "opponent_team": _text(record.get("opponent_team")),
                    "pass_attempts": _zero(record.get("attempts")),
                    "completions": _zero(record.get("completions")),
                    "passing_yards": _zero(record.get("passing_yards")),
                    "passing_tds": _zero(record.get("passing_tds")),
                    "interceptions": _zero(record.get("passing_interceptions")),
                    "passing_air_yards": _zero(record.get("passing_air_yards")),
                    "carries": _zero(record.get("carries")),
                    "rushing_yards": _zero(record.get("rushing_yards")),
                    "rushing_tds": _zero(record.get("rushing_tds")),
                    "targets": _zero(record.get("targets")),
                    "receptions": _zero(record.get("receptions")),
                    "receiving_yards": _zero(record.get("receiving_yards")),
                    "receiving_tds": _zero(record.get("receiving_tds")),
                    "receiving_air_yards": _zero(record.get("receiving_air_yards")),
                    # Offensive fumbles only. Special-teams and defensive recoveries are not
                    # part of the QB/RB/WR/TE scoring contract in league-defaults.yaml.
                    "fumbles_lost": _sum(
                        record,
                        "rushing_fumbles_lost",
                        "receiving_fumbles_lost",
                        "sack_fumbles_lost",
                    ),
                    "two_point_conversions": _sum(
                        record,
                        "passing_2pt_conversions",
                        "rushing_2pt_conversions",
                        "receiving_2pt_conversions",
                    ),
                    "upstream_fantasy_points_std": _number(record.get("fantasy_points")),
                    "upstream_fantasy_points_ppr": _number(record.get("fantasy_points_ppr")),
                    "upstream_fumbles_lost_total": _number(record.get("fumbles_lost_total")),
                    "upstream_special_teams_tds": _zero(record.get("special_teams_tds")),
                },
            )
        flags.note("weekly_rows_without_key", dropped)
        return self.build_batch(
            self.contract.build(rows),
            retrieved_at=retrieved_at,
            warning_codes=flags.codes,
            detail=flags.detail,
        )

    def fetch(self, *, as_of: datetime, config: SourceConfig) -> SourceBatch:
        import nflreadpy

        frame = nflreadpy.load_player_stats(seasons=[config.season], summary_level="week")
        self.check_source_schema(frame)
        return self.normalize(frame, retrieved_at=as_of or utc_now())

    def semantic_checks(self, batch: SourceBatch) -> Sequence[QualityCheck]:
        """Weeks must sit inside the season's real regular-season/postseason range."""
        if batch.frame.is_empty():
            return ()
        checks: list[QualityCheck] = []
        for season in batch.frame.get_column("season").unique().to_list():
            rows = batch.frame.filter(
                (pl.col("season") == season) & (pl.col("season_type") == "REG"),
            )
            if rows.is_empty():
                continue
            observed = cast(int, rows.get_column("week").max() or 0)
            allowed = regular_season_weeks(int(season))
            if observed > allowed:
                checks.append(
                    QualityCheck.fail(
                        "weekly_stats.week_out_of_range",
                        stage=self.source_id,
                        message="a regular-season week exceeds the season's week count",
                        observed=f"season {season} max REG week {observed}",
                        expected=f"<= {allowed}",
                    ),
                )
        return checks


class NflverseSnapCountAdapter(BaseSourceAdapter):
    """``load_snap_counts(season)`` -> per-game offensive snap participation.

    Keyed by ``pfr_player_id``: this dataset is scraped from Pro Football Reference and
    carries no GSIS id, so the historical builder resolves it through the roster/player
    master ``pfr_id`` bridge and reports the join coverage rather than assuming it.
    """

    source_id = NFLVERSE_SOURCE_ID
    resource = "load_snap_counts"
    adapter_version = "1.0"
    contract = SNAP_COUNTS_CONTRACT
    recorded_schema_fixture = "nflverse_snap_counts_2024"
    license_policy_version = _NFLVERSE_LICENSE
    min_expected_records = 0
    required_source_columns = frozenset(
        {
            "season",
            "week",
            "game_type",
            "pfr_player_id",
            "player",
            "position",
            "team",
            "offense_snaps",
            "offense_pct",
        },
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
            pfr = flags.take(normalize_id(IdNamespace.PFR, record.get("pfr_player_id")))
            season = _integer(record.get("season"))
            week = _integer(record.get("week"))
            if pfr is None or season is None or week is None:
                dropped += 1
                continue
            rows.append(
                {
                    "season": season,
                    "week": week,
                    "game_type": _text(record.get("game_type")) or "REG",
                    "pfr_player_id": pfr,
                    "player_name": _text(record.get("player")),
                    "position": _text(record.get("position")),
                    "team": _text(record.get("team")),
                    "offense_snaps": _number(record.get("offense_snaps")),
                    "offense_pct": _number(record.get("offense_pct")),
                },
            )
        flags.note("snap_rows_without_key", dropped)
        return self.build_batch(
            self.contract.build(rows),
            retrieved_at=retrieved_at,
            warning_codes=flags.codes,
            detail=flags.detail,
        )

    def fetch(self, *, as_of: datetime, config: SourceConfig) -> SourceBatch:
        import nflreadpy

        frame = nflreadpy.load_snap_counts(seasons=[config.season])
        self.check_source_schema(frame)
        return self.normalize(frame, retrieved_at=as_of or utc_now())


class NflverseScheduleAdapter(BaseSourceAdapter):
    """``load_schedules()`` -> the game calendar the draft anchor is derived from.

    Only the calendar columns are normalized. The loader also publishes scores, betting
    lines and weather; none of that is preseason-known, and none of it is needed to answer
    "when does week 1 kick off".
    """

    source_id = NFLVERSE_SOURCE_ID
    resource = "load_schedules"
    adapter_version = "1.0"
    contract = SCHEDULE_CONTRACT
    recorded_schema_fixture = "nflverse_schedules"
    license_policy_version = _NFLVERSE_LICENSE
    min_expected_records = 1
    required_source_columns = frozenset(
        {"game_id", "season", "game_type", "week", "gameday", "gametime", "away_team", "home_team"},
    )

    def normalize(
        self,
        records: RawRecords,
        *,
        retrieved_at: datetime | None = None,
    ) -> SourceBatch:
        rows: list[dict[str, Any]] = []
        flags = FlagCounter()
        for record in as_rows(records):
            season = _integer(record.get("season"))
            week = _integer(record.get("week"))
            game_id = _text(record.get("game_id"))
            if season is None or week is None or game_id is None:
                flags.note("schedule_rows_without_key")
                continue
            gameday = _as_date(record.get("gameday"))
            if gameday is None:
                flags.note("schedule_rows_without_gameday")
            rows.append(
                {
                    "game_id": game_id,
                    "season": season,
                    "game_type": _text(record.get("game_type")) or "REG",
                    "week": week,
                    "gameday": gameday,
                    "gametime": _text(record.get("gametime")),
                    "away_team": _text(record.get("away_team")),
                    "home_team": _text(record.get("home_team")),
                },
            )
        return self.build_batch(
            self.contract.build(rows),
            retrieved_at=retrieved_at,
            warning_codes=flags.codes,
            detail=flags.detail,
        )

    def fetch(self, *, as_of: datetime, config: SourceConfig) -> SourceBatch:
        import nflreadpy

        frame = nflreadpy.load_schedules()
        self.check_source_schema(frame)
        return self.normalize(frame, retrieved_at=as_of or utc_now())


class NflverseDraftPickAdapter(BaseSourceAdapter):
    """``load_draft_picks()`` -> draft capital, and only draft capital."""

    source_id = NFLVERSE_SOURCE_ID
    resource = "load_draft_picks"
    adapter_version = "1.0"
    contract = DRAFT_PICK_CONTRACT
    recorded_schema_fixture = "nflverse_draft_picks"
    license_policy_version = _NFLVERSE_LICENSE
    min_expected_records = 1
    required_source_columns = frozenset(
        {
            "season",
            "round",
            "pick",
            "gsis_id",
            "pfr_player_id",
            "pfr_player_name",
            "position",
            "team",
            "college",
        },
    )

    #: Career outcomes published alongside draft capital. Named explicitly so the exclusion
    #: is a documented decision the tests can assert, not an accident of which columns the
    #: normalizer happened to copy.
    POST_DRAFT_OUTCOME_COLUMNS = frozenset(
        {
            "age",
            "allpro",
            "car_av",
            "def_ints",
            "def_sacks",
            "def_solo_tackles",
            "dr_av",
            "games",
            "hof",
            "pass_attempts",
            "pass_completions",
            "pass_ints",
            "pass_tds",
            "pass_yards",
            "probowls",
            "rec_tds",
            "rec_yards",
            "receptions",
            "rush_atts",
            "rush_tds",
            "rush_yards",
            "seasons_started",
            "to",
            "w_av",
        },
    )

    def normalize(
        self,
        records: RawRecords,
        *,
        retrieved_at: datetime | None = None,
    ) -> SourceBatch:
        flags = FlagCounter()
        rows: list[dict[str, Any]] = []
        for record in as_rows(records):
            draft_year = _integer(record.get("season"))
            if draft_year is None:
                flags.note("draft_rows_without_year")
                continue
            gsis = flags.take(normalize_id(IdNamespace.GSIS, record.get("gsis_id")))
            pfr = flags.take(normalize_id(IdNamespace.PFR, record.get("pfr_player_id")))
            if gsis is None and pfr is None:
                flags.note("draft_rows_without_any_id")
                continue
            rows.append(
                {
                    "draft_year": draft_year,
                    "draft_round": _integer(record.get("round")),
                    "draft_overall": _integer(record.get("pick")),
                    "gsis_id": gsis,
                    "pfr_id": pfr,
                    "player_name": _text(record.get("pfr_player_name")),
                    "position": _text(record.get("position")),
                    # Draft picks arrive with Pro Football Reference abbreviations; the
                    # rest of the pipeline speaks nflverse's.
                    "draft_team": normalize_team_code(_text(record.get("team"))),
                    "college": _text(record.get("college")),
                },
            )
        return self.build_batch(
            self.contract.build(rows),
            retrieved_at=retrieved_at,
            warning_codes=flags.codes,
            detail=flags.detail,
        )

    def fetch(self, *, as_of: datetime, config: SourceConfig) -> SourceBatch:
        import nflreadpy

        frame = nflreadpy.load_draft_picks()
        self.check_source_schema(frame)
        return self.normalize(frame, retrieved_at=as_of or utc_now())

    def semantic_checks(self, batch: SourceBatch) -> Sequence[QualityCheck]:
        """No post-draft outcome column may survive normalization."""
        leaked = sorted(self.POST_DRAFT_OUTCOME_COLUMNS & set(batch.frame.columns))
        if leaked:
            return (
                QualityCheck.fail(
                    "draft_picks.post_draft_outcome_column",
                    stage=self.source_id,
                    message="career-outcome columns must not survive draft-capital normalization",
                    observed=", ".join(leaked),
                    expected="draft-time facts only",
                ),
            )
        return ()


class NflverseCombineAdapter(BaseSourceAdapter):
    """``load_combine()`` -> athletic measurements, keyed by ``pfr_id``."""

    source_id = NFLVERSE_SOURCE_ID
    resource = "load_combine"
    adapter_version = "1.0"
    contract = COMBINE_CONTRACT
    recorded_schema_fixture = "nflverse_combine"
    license_policy_version = _NFLVERSE_LICENSE
    min_expected_records = 1
    required_source_columns = frozenset(
        {
            "season",
            "pfr_id",
            "player_name",
            "pos",
            "ht",
            "wt",
            "forty",
            "bench",
            "vertical",
            "broad_jump",
            "cone",
            "shuttle",
        },
    )

    def normalize(
        self,
        records: RawRecords,
        *,
        retrieved_at: datetime | None = None,
    ) -> SourceBatch:
        flags = FlagCounter()
        rows: list[dict[str, Any]] = []
        for record in as_rows(records):
            pfr = flags.take(normalize_id(IdNamespace.PFR, record.get("pfr_id")))
            year = _integer(record.get("season"))
            if pfr is None or year is None:
                # A combine row without a durable id cannot be joined to a player. Name
                # matching is barred from production joins (ADR-005), so it is dropped.
                flags.note("combine_rows_without_key")
                continue
            rows.append(
                {
                    "combine_year": year,
                    "pfr_id": pfr,
                    "player_name": _text(record.get("player_name")),
                    "position": _text(record.get("pos")),
                    "height_in": _height_to_inches(record.get("ht")),
                    "weight_lb": _number(record.get("wt")),
                    "forty": _number(record.get("forty")),
                    "bench": _number(record.get("bench")),
                    "vertical": _number(record.get("vertical")),
                    "broad_jump": _number(record.get("broad_jump")),
                    "cone": _number(record.get("cone")),
                    "shuttle": _number(record.get("shuttle")),
                },
            )
        return self.build_batch(
            self.contract.build(rows),
            retrieved_at=retrieved_at,
            warning_codes=flags.codes,
            detail=flags.detail,
        )

    def fetch(self, *, as_of: datetime, config: SourceConfig) -> SourceBatch:
        import nflreadpy

        frame = nflreadpy.load_combine()
        self.check_source_schema(frame)
        return self.normalize(frame, retrieved_at=as_of or utc_now())


class NflversePlayerMasterAdapter(BaseSourceAdapter):
    """``load_players()`` -> biographical facts that do not change with time."""

    source_id = NFLVERSE_SOURCE_ID
    resource = "load_players"
    adapter_version = "1.0"
    contract = PLAYER_MASTER_CONTRACT
    recorded_schema_fixture = "nflverse_players"
    license_policy_version = _NFLVERSE_LICENSE
    min_expected_records = 1
    required_source_columns = frozenset(
        {
            "gsis_id",
            "display_name",
            "position",
            "birth_date",
            "height",
            "weight",
            "pfr_id",
            "espn_id",
            "college_name",
        },
    )

    #: Current-snapshot columns that describe a player *now*. They are never normalized, so
    #: a 2016 feature row cannot acquire 2026 knowledge through this source.
    CURRENT_STATE_COLUMNS = frozenset(
        {"status", "latest_team", "last_season", "years_of_experience", "rookie_season"},
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
            gsis = flags.take(normalize_id(IdNamespace.GSIS, record.get("gsis_id")))
            if gsis is None:
                dropped += 1
                continue
            rows.append(
                {
                    "gsis_id": gsis,
                    "display_name": _text(record.get("display_name")),
                    "position": _text(record.get("position")),
                    "birth_date": _as_date(record.get("birth_date")),
                    "height_in": _height_to_inches(record.get("height")),
                    "weight_lb": _number(record.get("weight")),
                    "pfr_id": flags.take(normalize_id(IdNamespace.PFR, record.get("pfr_id"))),
                    "espn_id": flags.take(normalize_id(IdNamespace.ESPN, record.get("espn_id"))),
                    "college_name": _text(record.get("college_name")),
                },
            )
        flags.note("player_master_rows_without_gsis_id", dropped)
        return self.build_batch(
            self.contract.build(rows),
            retrieved_at=retrieved_at,
            warning_codes=flags.codes,
            detail=flags.detail,
        )

    def fetch(self, *, as_of: datetime, config: SourceConfig) -> SourceBatch:
        import nflreadpy

        frame = nflreadpy.load_players()
        self.check_source_schema(frame)
        return self.normalize(frame, retrieved_at=as_of or utc_now())

    def semantic_checks(self, batch: SourceBatch) -> Sequence[QualityCheck]:
        leaked = sorted(self.CURRENT_STATE_COLUMNS & set(batch.frame.columns))
        if leaked:
            return (
                QualityCheck.fail(
                    "player_master.current_state_column",
                    stage=self.source_id,
                    message="current-snapshot columns must not enter the biographical contract",
                    observed=", ".join(leaked),
                    expected="biographical facts only",
                ),
            )
        return ()


class NflverseExpectedPointsAdapter(BaseSourceAdapter):
    """``load_ff_opportunity(stat_type="weekly")`` -> expected fantasy points per game.

    ffopportunity scores expected points on its own internal convention, which is not one of
    this project's presets. That is fine for the use it is put to - a lagged *opportunity*
    measure - and the feature dictionary says so explicitly. It is never a label.
    """

    source_id = FFOPPORTUNITY_SOURCE_ID
    resource = "load_ff_opportunity(stat_type='weekly')"
    adapter_version = "1.0"
    contract = EXPECTED_POINTS_CONTRACT
    recorded_schema_fixture = "nflverse_ff_opportunity_2024"
    license_policy_version = _FFOPPORTUNITY_LICENSE
    min_expected_records = 0
    required_source_columns = frozenset(
        {
            "season",
            "week",
            "player_id",
            "position",
            "posteam",
            "total_fantasy_points_exp",
            "pass_fantasy_points_exp",
            "rush_fantasy_points_exp",
            "rec_fantasy_points_exp",
            "receptions_exp",
            "total_fantasy_points",
            "total_fantasy_points_diff",
        },
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
            gsis = flags.take(normalize_id(IdNamespace.GSIS, record.get("player_id")))
            season = _integer(record.get("season"))
            week = _integer(record.get("week"))
            if gsis is None or season is None or week is None:
                dropped += 1
                continue
            rows.append(
                {
                    "season": season,
                    "week": week,
                    "gsis_id": gsis,
                    "position": _text(record.get("position")),
                    "team": _text(record.get("posteam")),
                    "expected_points": _number(record.get("total_fantasy_points_exp")),
                    "expected_pass_points": _number(record.get("pass_fantasy_points_exp")),
                    "expected_rush_points": _number(record.get("rush_fantasy_points_exp")),
                    "expected_rec_points": _number(record.get("rec_fantasy_points_exp")),
                    "expected_receptions": _number(record.get("receptions_exp")),
                    "actual_points": _number(record.get("total_fantasy_points")),
                    "points_over_expected": _number(record.get("total_fantasy_points_diff")),
                },
            )
        flags.note("expected_points_rows_without_key", dropped)
        return self.build_batch(
            self.contract.build(rows),
            retrieved_at=retrieved_at,
            warning_codes=flags.codes,
            detail=flags.detail,
        )

    def fetch(self, *, as_of: datetime, config: SourceConfig) -> SourceBatch:
        import nflreadpy

        frame = nflreadpy.load_ff_opportunity(seasons=[config.season], stat_type="weekly")
        self.check_source_schema(frame)
        return self.normalize(frame, retrieved_at=as_of or utc_now())
