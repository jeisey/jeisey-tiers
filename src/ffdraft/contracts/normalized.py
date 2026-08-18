"""Concrete frame contracts for every normalized source dataset.

Centralising the column names here is what `AGENTS.md` section 12 means by avoiding
"stringly typed" coupling: an adapter, a test and a downstream stage all refer to the same
constant, so a rename is one edit rather than a hunt through string literals.

Bump a contract's ``version`` whenever its output shape changes, and update the adapter
that produces it in the same change (AGENTS.md section 18).
"""

from __future__ import annotations

import polars as pl

from ffdraft.contracts.frames import ColumnSpec, FrameContract

__all__ = [
    "CANONICAL_PLAYER_CONTRACT",
    "DEPTH_CHART_CONTRACT",
    "MARKET_QUOTE_CONTRACT",
    "MFL_PLAYER_CONTRACT",
    "PLAYER_IDS_CONTRACT",
    "PLAYER_STATUS_CONTRACT",
    "RESOLUTION_CONTRACT",
    "ROSTER_CONTRACT",
]

_UTC = pl.Datetime(time_unit="us", time_zone="UTC")


ROSTER_CONTRACT = FrameContract(
    contract_id="nflverse_roster",
    version="1.0",
    primary_key=("season", "gsis_id"),
    columns=(
        ColumnSpec("season", pl.Int32, nullable=False, description="Roster season"),
        ColumnSpec("gsis_id", pl.String, nullable=False, description="Canonical nflverse id"),
        ColumnSpec("display_name", pl.String, nullable=False),
        ColumnSpec("position", pl.String, nullable=False, description="Raw source position"),
        ColumnSpec("team", pl.String),
        ColumnSpec("status", pl.String, description="ACT/RES/CUT/... as published"),
        ColumnSpec("depth_chart_position", pl.String),
        ColumnSpec("espn_id", pl.String, description="Primary market bridge (ADR-019)"),
        ColumnSpec("sleeper_id", pl.String, description="Join direction: nflverse -> Sleeper"),
        ColumnSpec("pfr_id", pl.String),
        ColumnSpec("sportradar_id", pl.String),
        ColumnSpec("yahoo_id", pl.String),
        ColumnSpec("birth_date", pl.Date),
        ColumnSpec("years_exp", pl.Int32),
        ColumnSpec("rookie_season", pl.Int32),
    ),
)


# The dynastyprocess crosswalk mirror. `mfl_id` is the only column Phase 0 measured at 100%
# coverage, which is why it is the key and why this source is the *secondary* market bridge:
# the mirror publishes no licence, so nflverse-native ids are preferred where both exist.
PLAYER_IDS_CONTRACT = FrameContract(
    contract_id="nflverse_ff_playerids",
    version="1.0",
    primary_key=("mfl_id",),
    columns=(
        ColumnSpec("mfl_id", pl.String, nullable=False),
        ColumnSpec("gsis_id", pl.String),
        ColumnSpec("espn_id", pl.String),
        ColumnSpec("sleeper_id", pl.String),
        ColumnSpec("pfr_id", pl.String),
        ColumnSpec("sportradar_id", pl.String),
        ColumnSpec("yahoo_id", pl.String),
        ColumnSpec("name", pl.String),
        ColumnSpec("position", pl.String),
        ColumnSpec("team", pl.String),
    ),
)


CANONICAL_PLAYER_CONTRACT = FrameContract(
    contract_id="canonical_player",
    version="1.0",
    primary_key=("player_id",),
    columns=(
        ColumnSpec("player_id", pl.String, nullable=False, description="Namespaced canonical key"),
        ColumnSpec("display_name", pl.String, nullable=False),
        ColumnSpec("position", pl.String, nullable=False),
        ColumnSpec("team", pl.String),
        ColumnSpec("status", pl.String),
        ColumnSpec("entity_kind", pl.String, nullable=False),
        ColumnSpec("gsis_id", pl.String),
        ColumnSpec("espn_id", pl.String),
        ColumnSpec("sleeper_id", pl.String),
        ColumnSpec("mfl_id", pl.String),
        ColumnSpec("pfr_id", pl.String),
        ColumnSpec("sportradar_id", pl.String),
        ColumnSpec("yahoo_id", pl.String),
        ColumnSpec("birth_date", pl.Date),
        ColumnSpec("years_exp", pl.Int32),
        ColumnSpec("rookie_season", pl.Int32),
        ColumnSpec("source_ids", pl.String, description="Comma-joined contributing sources"),
    ),
)


PLAYER_STATUS_CONTRACT = FrameContract(
    contract_id="sleeper_player_status",
    version="1.0",
    primary_key=("source_id", "external_player_id"),
    columns=(
        ColumnSpec("source_id", pl.String, nullable=False),
        ColumnSpec("external_player_id", pl.String, nullable=False),
        ColumnSpec("observed_at_utc", _UTC, nullable=False),
        ColumnSpec("team", pl.String),
        ColumnSpec("status", pl.String),
        ColumnSpec("injury_status", pl.String),
        ColumnSpec("injury_body_part", pl.String),
        ColumnSpec("practice_participation", pl.String),
        ColumnSpec("depth_chart_position", pl.String),
        ColumnSpec("depth_chart_order", pl.Int32),
        ColumnSpec("reported_gsis_id", pl.String, description="Cross-check only, never a key"),
        ColumnSpec("quality_flags", pl.String),
    ),
)


DEPTH_CHART_CONTRACT = FrameContract(
    contract_id="nflverse_depth_chart",
    version="1.0",
    columns=(
        ColumnSpec("source_id", pl.String, nullable=False),
        ColumnSpec("season", pl.Int32, nullable=False),
        ColumnSpec("era", pl.String, nullable=False, description="ADR-015 schema era"),
        ColumnSpec("team", pl.String, nullable=False),
        ColumnSpec("position", pl.String),
        ColumnSpec("depth_rank", pl.Int32),
        ColumnSpec("gsis_id", pl.String),
        ColumnSpec("espn_id", pl.String),
        ColumnSpec("player_name", pl.String),
        ColumnSpec("observed_at_utc", _UTC, description="Snapshot era only"),
        ColumnSpec("week", pl.Int32, description="Weekly era only"),
    ),
)


MARKET_QUOTE_CONTRACT = FrameContract(
    contract_id="market_quote",
    version="1.0",
    primary_key=("source_id", "season", "external_player_id"),
    columns=(
        ColumnSpec("source_id", pl.String, nullable=False),
        ColumnSpec("season", pl.Int32, nullable=False),
        ColumnSpec("external_player_id", pl.String, nullable=False),
        ColumnSpec("average_pick", pl.Float64, nullable=False),
        ColumnSpec("market_rank", pl.Int32),
        ColumnSpec("min_pick", pl.Float64),
        ColumnSpec("max_pick", pl.Float64),
        ColumnSpec("sample_size", pl.Int32),
        ColumnSpec("selection_pct", pl.Float64),
        ColumnSpec("retrieved_at_utc", _UTC, nullable=False),
        ColumnSpec("source_as_of_utc", _UTC, description="Null for MFL: no data-as-of time"),
        ColumnSpec("entity_kind", pl.String, nullable=False),
        ColumnSpec("raw_position", pl.String),
        ColumnSpec("scoring_preset", pl.String, nullable=False),
        ColumnSpec("league_size", pl.Int32, nullable=False),
        ColumnSpec("cohort_approximate", pl.Boolean, nullable=False),
        ColumnSpec("source_format_detail", pl.String, nullable=False),
        ColumnSpec("quality_flags", pl.String),
    ),
)


# MFL's player database. It carries no `gsis_id` at all (Phase 0: 0% coverage), which is why
# `espn_id` is the bridge and why every row's entity kind has to be classified here: the
# export mixes real players with team aggregates such as `TMWR` and `Def`.
MFL_PLAYER_CONTRACT = FrameContract(
    contract_id="mfl_player_directory",
    version="1.0",
    primary_key=("mfl_id",),
    columns=(
        ColumnSpec("mfl_id", pl.String, nullable=False),
        ColumnSpec("name", pl.String),
        ColumnSpec("raw_position", pl.String),
        ColumnSpec("team", pl.String),
        ColumnSpec("espn_id", pl.String, description="Primary market bridge"),
        ColumnSpec("entity_kind", pl.String, nullable=False),
    ),
)


RESOLUTION_CONTRACT = FrameContract(
    contract_id="identity_resolution",
    version="1.0",
    primary_key=("source_id", "external_player_id"),
    columns=(
        ColumnSpec("source_id", pl.String, nullable=False),
        ColumnSpec("external_player_id", pl.String, nullable=False),
        ColumnSpec("status", pl.String, nullable=False),
        ColumnSpec("player_id", pl.String),
        ColumnSpec("reason", pl.String, nullable=False),
        ColumnSpec("entity_kind", pl.String, nullable=False),
        ColumnSpec("bridges_agreed", pl.String),
        ColumnSpec("bridges_disagreed", pl.String),
        ColumnSpec("name_candidates", pl.String),
        ColumnSpec("quality_flags", pl.String),
    ),
)
