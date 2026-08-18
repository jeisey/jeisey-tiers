"""Canonical player identity: crosswalk construction and fail-closed resolution.

The rules this package implements come from ADR-005 and ADR-019, and they are absolute:
ids resolve records, names only propose candidates, and any ambiguity - a bridge
disagreement, a poisoned crosswalk index, a failed cross-check - fails closed rather than
picking a winner.
"""

from __future__ import annotations

from ffdraft.identity.aliases import AliasEntry, AliasMap, load_alias_map
from ffdraft.identity.ids import (
    IdNamespace,
    NormalizedId,
    is_team_code,
    make_player_id,
    normalize_id,
    parse_player_id,
    value_of,
)
from ffdraft.identity.names import name_key, normalize_name
from ffdraft.identity.registry import (
    CanonicalRegistry,
    LookupResult,
    LookupStatus,
    build_registry,
)
from ffdraft.identity.resolver import (
    PRIMARY_MARKET_BRIDGE,
    SECONDARY_MARKET_BRIDGE,
    ResolutionSummary,
    coverage_checks,
    outcomes_to_frame,
    resolve_market_quotes,
    resolve_sleeper_status,
    summarize,
)

__all__ = [
    "PRIMARY_MARKET_BRIDGE",
    "SECONDARY_MARKET_BRIDGE",
    "AliasEntry",
    "AliasMap",
    "CanonicalRegistry",
    "IdNamespace",
    "LookupResult",
    "LookupStatus",
    "NormalizedId",
    "ResolutionSummary",
    "build_registry",
    "coverage_checks",
    "is_team_code",
    "load_alias_map",
    "make_player_id",
    "name_key",
    "normalize_id",
    "normalize_name",
    "outcomes_to_frame",
    "parse_player_id",
    "resolve_market_quotes",
    "resolve_sleeper_status",
    "summarize",
    "value_of",
]
