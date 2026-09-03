"""CSV projections for artifacts whose JSON records nest (Phase 10, ADR-065).

A CSV cell holds a scalar. Until Phase 10 every public record was flat, so the CSV was the
JSON with commas and `records_to_csv` could take its columns straight from the schema. The
multi-source arbitrage record is not flat: `markets` is an array of per-source comparisons,
`cross_market` and `expert_consensus` are objects.

Rendering those with `str()` would produce a cell containing a Python repr — technically a
CSV, useless to a spreadsheet, and impossible to diff. So an artifact may declare a
**flattener**: an explicit, ordered set of scalar columns and the function that fills them.

Two rules shape the arbitrage projection:

* **Source and signal are named in the column, not implied by position.** Roadmap 10.6 asks
  for "explicit source/signal names" in the export, and `ffc_adp` next to `mfl_adp` next to
  `fantasypros_ecr` is what stops a reader assuming three columns of one thing.
* **ECR keeps its own column names and never appears in an ADP column.** The same rule the
  JSON enforces structurally, restated in the one place where the structure is flattened
  away and a careless mapping could quietly undo it.

Columns are declared, not derived from the data. A projection whose shape depended on which
sources happened to be enabled today would change the header between builds, and a stable
header is what makes a committed golden CSV worth diffing.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

__all__ = [
    "ARBITRAGE_CSV_COLUMNS",
    "CSV_FLATTENERS",
    "flatten_arbitrage_record",
    "flattener_for",
]

#: The ADP sources a column set is reserved for. A source not named here still travels in
#: the JSON `markets` array; it simply has no dedicated CSV column until one is declared,
#: which is a deliberate cost of a stable header.
_ADP_SOURCES: tuple[tuple[str, str], ...] = (
    ("ffc", "fantasyfootballcalculator_adp"),
    ("mfl", "myfantasyleague_adp"),
    ("fantasypros", "fantasypros_adp"),
)

#: The consensus source. Separate from the tuple above so no loop can accidentally treat it
#: as a price.
_ECR_SOURCE = "fantasypros_ecr"


def _adp_columns() -> tuple[str, ...]:
    columns: list[str] = []
    for prefix, _ in _ADP_SOURCES:
        columns.extend(
            (
                f"{prefix}_adp",
                f"{prefix}_rank_gap",
                f"{prefix}_regional_value_gap",
                f"{prefix}_adp_sd",
                f"{prefix}_adp_low",
                f"{prefix}_adp_high",
                f"{prefix}_sample_size",
                f"{prefix}_aggregation_window",
                f"{prefix}_league_size",
            ),
        )
    return tuple(columns)


#: The arbitrage CSV, in order. The 1.1 scalar columns come first and unchanged, so a
#: Release 1 consumer reading by name still finds every column it read before.
ARBITRAGE_CSV_COLUMNS: tuple[str, ...] = (
    "schema_version",
    "build_id",
    "league_preset_id",
    "scoring_preset",
    "player_id",
    "display_name",
    "team",
    "position",
    "fair_rank",
    "market_adp",
    "market_rank",
    "rank_gap",
    "regional_value_gap",
    "arbitrage_mode",
    "arbitrage_score",
    "expected_surplus_vorp",
    "p_positive_surplus",
    "market_trend",
    "market_sample_size",
    "market_adp_sd",
    "market_adp_low",
    "market_adp_high",
    "market_source_id",
    "market_cohort_id",
    "market_cohort_detail",
    "market_snapshot_at_utc",
    "confidence",
    "quality_flags",
    *_adp_columns(),
    # The consensus columns. Named for what they are, and deliberately not adjacent to a
    # column called `_adp` (roadmap 10.4).
    "fantasypros_ecr",
    "fantasypros_ecr_gap",
    "fantasypros_ecr_expert_count",
    "fantasypros_ecr_rank_sd",
    # The ADP-only cross-market summary.
    "market_adp_min",
    "market_adp_max",
    "market_adp_median",
    "market_disagreement_range",
    "cheapest_market_source",
    "most_expensive_market_source",
    "sources_available",
    # Why this row is visible at all.
    "surface_reasons",
    "outside_tier_board",
)


def flatten_arbitrage_record(record: Mapping[str, Any]) -> dict[str, Any]:
    """Project one arbitrage record onto :data:`ARBITRAGE_CSV_COLUMNS`."""
    flat: dict[str, Any] = {
        column: record.get(column) for column in ARBITRAGE_CSV_COLUMNS if not _is_derived(column)
    }

    by_source = {
        str(entry.get("source_id")): entry
        for entry in record.get("markets") or ()
        if isinstance(entry, Mapping)
    }
    for prefix, source_id in _ADP_SOURCES:
        entry = by_source.get(source_id, {})
        flat[f"{prefix}_adp"] = entry.get("market_adp")
        flat[f"{prefix}_rank_gap"] = entry.get("rank_gap")
        flat[f"{prefix}_regional_value_gap"] = entry.get("regional_value_gap")
        flat[f"{prefix}_adp_sd"] = entry.get("market_adp_sd")
        flat[f"{prefix}_adp_low"] = entry.get("market_adp_low")
        flat[f"{prefix}_adp_high"] = entry.get("market_adp_high")
        flat[f"{prefix}_sample_size"] = entry.get("market_sample_size")
        flat[f"{prefix}_aggregation_window"] = entry.get("aggregation_window_type")
        flat[f"{prefix}_league_size"] = entry.get("league_size")

    # Read only from the declared consensus source. An `expert_consensus` block naming
    # something else is not projected into these columns: the CSV is where the JSON's
    # structural separation of price and ranking is flattened away, so the rule is
    # re-checked here rather than assumed to have survived.
    consensus = record.get("expert_consensus")
    consensus = (
        consensus
        if isinstance(consensus, Mapping) and str(consensus.get("source_id")) == _ECR_SOURCE
        else {}
    )
    flat["fantasypros_ecr"] = consensus.get("ecr")
    flat["fantasypros_ecr_gap"] = consensus.get("ecr_gap")
    flat["fantasypros_ecr_expert_count"] = consensus.get("expert_count")
    flat["fantasypros_ecr_rank_sd"] = consensus.get("consensus_rank_sd")

    cross = record.get("cross_market")
    cross = cross if isinstance(cross, Mapping) else {}
    for column in (
        "market_adp_min",
        "market_adp_max",
        "market_adp_median",
        "market_disagreement_range",
        "cheapest_market_source",
        "most_expensive_market_source",
        "sources_available",
    ):
        flat[column] = cross.get(column)

    flat["surface_reasons"] = record.get("surface_reasons")
    flat["outside_tier_board"] = record.get("outside_tier_board")
    return flat


#: Columns filled from a nested structure rather than copied from the record's top level.
_DERIVED_EXACT = frozenset(
    {
        "market_disagreement_range",
        "sources_available",
        "surface_reasons",
        "outside_tier_board",
    },
)
_DERIVED_PREFIXES = (
    *(f"{prefix}_" for prefix, _ in _ADP_SOURCES),
    "fantasypros_ecr",
    "market_adp_m",
    "cheapest_",
    "most_expensive_",
)


def _is_derived(column: str) -> bool:
    """Whether a column is filled from a nested structure rather than copied."""
    return column in _DERIVED_EXACT or column.startswith(_DERIVED_PREFIXES)


#: ``artifact -> (columns, flattener)``. An artifact absent from this map keeps the default
#: behaviour: columns from the record schema, values copied straight through.
CSV_FLATTENERS: Mapping[
    str,
    tuple[Sequence[str], Callable[[Mapping[str, Any]], Mapping[str, Any]]],
] = {
    "arbitrage": (ARBITRAGE_CSV_COLUMNS, flatten_arbitrage_record),
}


def flattener_for(
    artifact: str,
) -> tuple[Sequence[str], Callable[[Mapping[str, Any]], Mapping[str, Any]]] | None:
    return CSV_FLATTENERS.get(artifact)
