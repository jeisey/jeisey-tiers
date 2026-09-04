"""What each public artifact is: its files, its record schema, its keys and its sort order.

Sort order is part of the contract, not a convenience. `docs/ARCHITECTURE.md` section 13
requires reproducibility within deterministic tolerance, and an artifact whose row order
changes between identical builds produces a different file hash and a noisy diff for no
reason. Every artifact therefore has a total ordering with an id-based final tie-break.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

__all__ = ["ARTIFACT_SPECS", "ArtifactSpec", "spec_for"]


@dataclass(frozen=True, slots=True)
class ArtifactSpec:
    """One serialized public artifact."""

    artifact: str
    schema_name: str
    json_filename: str
    csv_filename: str | None
    key_fields: tuple[str, ...]
    sort_fields: tuple[str, ...]
    description: str = ""

    def sort_key(self, record: Mapping[str, Any]) -> tuple[Any, ...]:
        """A total ordering. ``player_id`` closes any remaining tie."""
        return tuple(_sortable(record.get(field)) for field in self.sort_fields)

    def sorted_records(
        self,
        records: Sequence[Mapping[str, Any]],
    ) -> list[Mapping[str, Any]]:
        return sorted(records, key=self.sort_key)


def _sortable(value: Any) -> tuple[int, Any]:
    """Sort ``None`` last without comparing ``None`` to a number."""
    if value is None:
        return (1, "")
    if isinstance(value, bool):
        return (0, int(value))
    if isinstance(value, int | float):
        return (0, float(value))
    return (0, str(value))


ARTIFACT_SPECS: Mapping[str, ArtifactSpec] = {
    "tiers": ArtifactSpec(
        artifact="tiers",
        schema_name="tier_record",
        json_filename="tiers.json",
        csv_filename="tiers.csv",
        key_fields=("build_id", "league_preset_id", "scoring_preset", "player_id"),
        sort_fields=("league_preset_id", "scoring_preset", "fair_rank", "player_id"),
        description="Intrinsic tier board: fair rank, tier and VORP distribution per preset",
    ),
    "arbitrage": ArtifactSpec(
        artifact="arbitrage",
        schema_name="arbitrage_record",
        json_filename="arbitrage.json",
        csv_filename="arbitrage.csv",
        key_fields=("build_id", "league_preset_id", "scoring_preset", "player_id"),
        sort_fields=("league_preset_id", "scoring_preset", "fair_rank", "player_id"),
        description="Market-vs-model gap per preset",
    ),
    "projections": ArtifactSpec(
        artifact="projections",
        schema_name="player_projection",
        json_filename="projections.json",
        csv_filename="projections.csv",
        key_fields=("build_id", "scoring_preset", "player_id"),
        sort_fields=("scoring_preset", "player_id"),
        description="Per-player point projections with quantiles",
    ),
    "market_trend_series": ArtifactSpec(
        artifact="market_trend_series",
        schema_name="market_trend_series",
        json_filename="market_trend_series.json",
        # No CSV. The record is a series, and a row per point would be a different artifact
        # from the one a reader asked to export; the scalar `market_trend` is already in the
        # arbitrage CSV, which is where a spreadsheet wants it.
        csv_filename=None,
        key_fields=(
            "build_id",
            "market_source_id",
            "league_preset_id",
            "scoring_preset",
            "player_id",
        ),
        sort_fields=("league_preset_id", "scoring_preset", "market_source_id", "player_id"),
        description="Retained per-player ADP history, so the trend chart needs no vendor call",
    ),
    "player_status": ArtifactSpec(
        artifact="player_status",
        schema_name="player_status",
        json_filename="player_status.json",
        csv_filename="player_status.csv",
        key_fields=("build_id", "player_id"),
        sort_fields=("player_id",),
        description=(
            "Current roster/injury/practice status, one row per canonical player. "
            "Annotation only: Phase 6 joins it by player_id and no field here can move a "
            "projection, a fair rank, a tier or an arbitrage score (ADR-043)."
        ),
    ),
    "ros_tiers": ArtifactSpec(
        artifact="ros_tiers",
        schema_name="ros_tier_record",
        json_filename="ros_tiers.json",
        csv_filename="ros_tiers.csv",
        key_fields=("build_id", "league_preset_id", "scoring_preset", "player_id"),
        sort_fields=("league_preset_id", "scoring_preset", "ros_fair_rank", "player_id"),
        description=(
            "Rest-of-season tier board at an explicit through-week cutoff: ros_fair_rank, "
            "ros_tier and the remaining-value distribution per preset"
        ),
    ),
    "inseason_opportunity": ArtifactSpec(
        artifact="inseason_opportunity",
        schema_name="inseason_opportunity_record",
        json_filename="inseason_opportunity.json",
        csv_filename="inseason_opportunity.csv",
        key_fields=("build_id", "league_preset_id", "scoring_preset", "player_id"),
        sort_fields=("league_preset_id", "scoring_preset", "ros_fair_rank", "player_id"),
        description=(
            "In-season opportunity board: intrinsic rest-of-season value beside documented "
            "add/drop behaviour, which is never a price and never a rank"
        ),
    ),
    "market_snapshot": ArtifactSpec(
        artifact="market_snapshot",
        schema_name="market_snapshot",
        json_filename="market_snapshot.json",
        csv_filename=None,
        key_fields=("source_id", "season", "scoring_preset", "league_size", "player_id"),
        sort_fields=("scoring_preset", "league_size", "market_adp", "player_id"),
        description=(
            "Point-in-time market prices. Phase 5 owns append-only retention (ADR-006); "
            "Phase 1 only proves the record contract round-trips."
        ),
    ),
}

#: ``build_metadata.json`` is a single object rather than an envelope of records, so it has
#: no :class:`ArtifactSpec`; it is serialized directly against its own schema.
BUILD_METADATA_FILENAME = "build_metadata.json"
BUILD_METADATA_SCHEMA = "build_metadata"


def spec_for(artifact: str) -> ArtifactSpec:
    try:
        return ARTIFACT_SPECS[artifact]
    except KeyError as exc:
        raise KeyError(f"unknown artifact {artifact!r}; known: {sorted(ARTIFACT_SPECS)}") from exc
