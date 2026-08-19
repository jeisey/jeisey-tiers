"""The forbidden-feature guard.

AGENTS.md section 8 and ADR-002 forbid market and expert-rank signals from the intrinsic
model. `docs/TEST_STRATEGY.md` 2.5 requires that to be an automated test rather than a
review habit, because the failure is invisible: a model trained on ADP still produces
plausible tiers, and the arbitrage product silently becomes circular.

Two audits live here. The first inspects feature *names*; the second inspects source
*lineage*, which catches the case a naming convention would miss - a feature called
``prev1_value_score`` that was computed from a market column.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence

from ffdraft.config import SourceRegistry
from ffdraft.contracts import QualityCheck

__all__ = [
    "FORBIDDEN_LINEAGE_SOURCES",
    "FORBIDDEN_NAME_SUBSTRINGS",
    "FORBIDDEN_NAME_TOKENS",
    "audit_intrinsic_feature_names",
    "audit_intrinsic_source_lineage",
    "forbidden_reason",
]

#: Whole tokens (split on ``_``/``-``/``.``) that may never appear in an intrinsic feature.
FORBIDDEN_NAME_TOKENS = frozenset(
    {
        "adp",
        "ecr",
        "adp_sd",
        "consensus",
        "expert",
        "ranking",
        "marketrank",
        "auction",
        "keeptradecut",
        "ktc",
        "arbitrage",
        "surplus",
    },
)

#: Substrings distinctive enough that a partial match is conclusive.
FORBIDDEN_NAME_SUBSTRINGS = (
    "fantasypros",
    "fantasycalc",
    "market_value",
    "market_adp",
    "market_rank",
    "market_cost",
    "draft_cost",
    "expert_rank",
    "average_draft_position",
    "arbitrage",
)

#: Sources whose data may never feed the intrinsic model, whatever the column is called.
FORBIDDEN_LINEAGE_SOURCES = frozenset(
    {
        "myfantasyleague_adp",
        "fantasycalc",
        "fantasypros_ecr_via_dynastyprocess",
    },
)

_SEPARATORS = str.maketrans({"-": " ", ".": " ", "_": " "})


def forbidden_reason(feature_name: str) -> str | None:
    """Why ``feature_name`` is forbidden, or ``None`` if it is acceptable."""
    lowered = feature_name.lower()
    for needle in FORBIDDEN_NAME_SUBSTRINGS:
        if needle in lowered:
            return f"contains forbidden substring {needle!r}"
    tokens = set(lowered.translate(_SEPARATORS).split())
    hit = tokens & FORBIDDEN_NAME_TOKENS
    if hit:
        return f"contains forbidden token(s) {sorted(hit)}"
    return None


def audit_intrinsic_feature_names(
    feature_names: Iterable[str],
    *,
    stage: str = "intrinsic.features",
) -> list[QualityCheck]:
    """Reject any intrinsic feature whose name signals a market or expert input."""
    names = list(feature_names)
    offenders = {name: reason for name in names if (reason := forbidden_reason(name)) is not None}
    if offenders:
        return [
            QualityCheck.fail(
                "intrinsic.forbidden_feature_name",
                stage=stage,
                message="intrinsic features must not carry market or expert-rank signals",
                observed="; ".join(
                    f"{name} ({reason})" for name, reason in sorted(offenders.items())
                ),
                expected="no ADP/ECR/consensus/market-derived features",
            ),
        ]
    return [
        QualityCheck.ok(
            "intrinsic.forbidden_feature_name",
            stage=stage,
            message="no forbidden feature names present",
            observed=f"{len(names)} feature(s) audited",
        ),
    ]


def audit_intrinsic_source_lineage(
    lineage: Mapping[str, Sequence[str]],
    *,
    registry: SourceRegistry | None = None,
    stage: str = "intrinsic.features",
) -> list[QualityCheck]:
    """Reject intrinsic features whose lineage includes a market or benchmark-only source.

    ``lineage`` maps a feature name to the source ids that produced it. When a registry is
    supplied, its ``benchmark_only`` sources are added to the forbidden set, so approving a
    benchmark source (ADR-014) can never quietly make it an intrinsic input.
    """
    forbidden = set(FORBIDDEN_LINEAGE_SOURCES)
    if registry is not None:
        forbidden |= set(registry.benchmark_only_sources)
        forbidden |= {
            source_id
            for source_id, entry in registry.sources.items()
            if not entry.may_feed_intrinsic_model
        }

    offenders = {
        feature: sorted(set(sources) & forbidden)
        for feature, sources in lineage.items()
        if set(sources) & forbidden
    }
    if offenders:
        return [
            QualityCheck.fail(
                "intrinsic.forbidden_feature_lineage",
                stage=stage,
                message="an intrinsic feature was derived from a forbidden source",
                observed="; ".join(
                    f"{feature} <- {', '.join(sources)}"
                    for feature, sources in sorted(offenders.items())
                ),
                expected=f"no lineage through {sorted(forbidden)}",
            ),
        ]
    return [
        QualityCheck.ok(
            "intrinsic.forbidden_feature_lineage",
            stage=stage,
            message="no intrinsic feature is derived from a market or benchmark-only source",
            observed=f"{len(lineage)} feature lineage(s) audited",
        ),
    ]
