"""Reusable quality checks, the forbidden-feature guard and the deploy gate."""

from __future__ import annotations

from ffdraft.quality.checks import (
    check_duplicate_keys,
    check_finite,
    check_quantiles_monotonic,
    check_range,
    check_source_freshness,
    check_unique_contiguous_tiers,
    collect,
)
from ffdraft.quality.forbidden import (
    FORBIDDEN_LINEAGE_SOURCES,
    FORBIDDEN_NAME_SUBSTRINGS,
    FORBIDDEN_NAME_TOKENS,
    audit_intrinsic_feature_names,
    audit_intrinsic_source_lineage,
    forbidden_reason,
)
from ffdraft.quality.gate import QualityGate, QualityGateError

__all__ = [
    "FORBIDDEN_LINEAGE_SOURCES",
    "FORBIDDEN_NAME_SUBSTRINGS",
    "FORBIDDEN_NAME_TOKENS",
    "QualityGate",
    "QualityGateError",
    "audit_intrinsic_feature_names",
    "audit_intrinsic_source_lineage",
    "check_duplicate_keys",
    "check_finite",
    "check_quantiles_monotonic",
    "check_range",
    "check_source_freshness",
    "check_unique_contiguous_tiers",
    "collect",
    "forbidden_reason",
]
