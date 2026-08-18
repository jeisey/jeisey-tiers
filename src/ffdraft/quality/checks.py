"""Reusable data-quality checks.

These are the checks `docs/DATA_CONTRACTS.md` section 12 and `docs/ARCHITECTURE.md`
section 12 name explicitly. They are ordinary functions returning
:class:`~ffdraft.contracts.quality.QualityCheck` records so a caller can decide when to
collect and when to stop, and so each one is unit-testable in isolation.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime, timedelta
from typing import Any

from ffdraft.contracts import QualityCheck, Severity
from ffdraft.timeutil import ensure_utc

__all__ = [
    "check_duplicate_keys",
    "check_finite",
    "check_quantiles_monotonic",
    "check_range",
    "check_source_freshness",
    "check_unique_contiguous_tiers",
]

#: Quantile field groups, low to high. Ordering is the contract, not a suggestion.
QUANTILE_ORDER = ("p10", "p25", "p50", "p75", "p90")


def check_quantiles_monotonic(
    records: Sequence[Mapping[str, Any]],
    *,
    prefix: str,
    key: str = "player_id",
    stage: str = "artifacts",
) -> list[QualityCheck]:
    """Quantiles must be non-decreasing. `docs/DATA_CONTRACTS.md` calls violations critical."""
    fields = [f"{quantile}_{prefix}" for quantile in QUANTILE_ORDER]
    offenders: list[str] = []
    for record in records:
        values = [record.get(field) for field in fields]
        if any(value is None for value in values):
            offenders.append(f"{record.get(key)} (missing quantile)")
            continue
        numeric = [float(value) for value in values]  # type: ignore[arg-type]
        pairs = zip(numeric, numeric[1:], strict=False)
        if any(later < earlier for earlier, later in pairs):
            offenders.append(f"{record.get(key)} ({numeric})")
    if offenders:
        return [
            QualityCheck.fail(
                "artifact.non_monotonic_quantiles",
                stage=stage,
                message=f"{prefix} quantiles must be non-decreasing p10 -> p90",
                observed="; ".join(offenders[:10]),
                expected="p10 <= p25 <= p50 <= p75 <= p90",
            ),
        ]
    return [
        QualityCheck.ok(
            "artifact.quantiles_monotonic",
            stage=stage,
            message=f"{prefix} quantiles are monotonic",
            observed=f"{len(records)} record(s)",
        ),
    ]


def check_duplicate_keys(
    records: Sequence[Mapping[str, Any]],
    *,
    key_fields: Sequence[str],
    stage: str = "artifacts",
) -> list[QualityCheck]:
    """Duplicate canonical keys are a critical failure in model and public layers."""
    seen: dict[tuple[Any, ...], int] = {}
    for record in records:
        composite = tuple(record.get(field) for field in key_fields)
        seen[composite] = seen.get(composite, 0) + 1
    duplicates = {key: count for key, count in seen.items() if count > 1}
    if duplicates:
        rendered = "; ".join(
            f"{key} x{count}" for key, count in sorted(duplicates.items(), key=str)
        )
        return [
            QualityCheck.fail(
                "artifact.duplicate_keys",
                stage=stage,
                message=f"duplicate {'+'.join(key_fields)} in artifact records",
                observed=rendered[:400],
                expected="0 duplicates",
            ),
        ]
    return [
        QualityCheck.ok(
            "artifact.unique_keys",
            stage=stage,
            message=f"{'+'.join(key_fields)} is unique",
            observed=f"{len(records)} record(s)",
        ),
    ]


def check_finite(
    records: Sequence[Mapping[str, Any]],
    *,
    fields: Sequence[str],
    stage: str = "artifacts",
) -> list[QualityCheck]:
    """NaN and infinity must never reach a public metric."""
    offenders = [
        f"{record.get('player_id')}.{field}"
        for record in records
        for field in fields
        if isinstance(record.get(field), float) and not math.isfinite(float(record[field]))
    ]
    if offenders:
        return [
            QualityCheck.fail(
                "artifact.non_finite_value",
                stage=stage,
                message="public numeric fields must be finite",
                observed="; ".join(offenders[:10]),
                expected="finite values only",
            ),
        ]
    return [
        QualityCheck.ok(
            "artifact.finite_values",
            stage=stage,
            message="all audited numeric fields are finite",
            observed=f"{len(fields)} field(s) x {len(records)} record(s)",
        ),
    ]


def check_range(
    records: Sequence[Mapping[str, Any]],
    *,
    field: str,
    minimum: float | None = None,
    maximum: float | None = None,
    stage: str = "artifacts",
) -> list[QualityCheck]:
    """Bounded fields (ranks > 0, probabilities in [0,1], scores in [0,100])."""
    offenders = []
    for record in records:
        value = record.get(field)
        if value is None:
            continue
        numeric = float(value)
        if (minimum is not None and numeric < minimum) or (
            maximum is not None and numeric > maximum
        ):
            offenders.append(f"{record.get('player_id')}={numeric}")
    if offenders:
        return [
            QualityCheck.fail(
                "artifact.value_out_of_range",
                stage=stage,
                message=f"{field} is outside its documented range",
                observed="; ".join(offenders[:10]),
                expected=f"[{minimum}, {maximum}]",
            ),
        ]
    return [
        QualityCheck.ok(
            "artifact.value_in_range",
            stage=stage,
            message=f"{field} is within range",
            observed=f"{len(records)} record(s)",
        ),
    ]


def check_unique_contiguous_tiers(
    records: Sequence[Mapping[str, Any]],
    *,
    stage: str = "artifacts",
) -> list[QualityCheck]:
    """Tier semantics from `docs/DATA_CONTRACTS.md` section 8.

    Three rules, all structural rather than statistical: fair ranks are unique inside a
    preset, tier ordinals never decrease as fair rank grows, and every tier occupies one
    contiguous fair-rank interval. A tier that is not contiguous is not a tier.
    """
    checks: list[QualityCheck] = []
    grouped: dict[tuple[Any, Any], list[Mapping[str, Any]]] = {}
    for record in records:
        key = (record.get("league_preset_id"), record.get("scoring_preset"))
        grouped.setdefault(key, []).append(record)

    rank_offenders: list[str] = []
    order_offenders: list[str] = []
    gap_offenders: list[str] = []

    for (preset, scoring), group in sorted(grouped.items(), key=lambda item: str(item[0])):
        ranks = [int(record["fair_rank"]) for record in group]
        if len(set(ranks)) != len(ranks):
            rank_offenders.append(f"{preset}/{scoring}")
        ordered = sorted(group, key=lambda record: int(record["fair_rank"]))
        previous = None
        for record in ordered:
            ordinal = int(record["tier_ordinal"])
            if previous is not None and ordinal < previous:
                order_offenders.append(f"{preset}/{scoring}@rank{record['fair_rank']}")
            previous = ordinal
        spans: dict[int, list[int]] = {}
        for record in ordered:
            spans.setdefault(int(record["tier_ordinal"]), []).append(int(record["fair_rank"]))
        for ordinal, member_ranks in spans.items():
            span = max(member_ranks) - min(member_ranks) + 1
            if span != len(member_ranks):
                gap_offenders.append(f"{preset}/{scoring} tier {ordinal}")

    for offenders, check_id, message, expectation in (
        (
            rank_offenders,
            "tier.duplicate_fair_rank",
            "fair ranks must be unique in a preset",
            "unique",
        ),
        (
            order_offenders,
            "tier.ordinal_not_monotonic",
            "tier ordinals must not decrease as fair rank increases",
            "non-decreasing",
        ),
        (
            gap_offenders,
            "tier.not_contiguous",
            "every tier must occupy a contiguous fair-rank interval",
            "contiguous",
        ),
    ):
        if offenders:
            checks.append(
                QualityCheck.fail(
                    check_id,
                    stage=stage,
                    message=message,
                    observed="; ".join(sorted(set(offenders))[:10]),
                    expected=expectation,
                ),
            )
    if not checks:
        checks.append(
            QualityCheck.ok(
                "tier.semantics",
                stage=stage,
                message="fair ranks unique, tier ordinals monotonic, tiers contiguous",
                observed=f"{len(grouped)} preset group(s)",
            ),
        )
    return checks


def check_source_freshness(
    retrieved_at: datetime,
    *,
    now: datetime,
    max_age: timedelta,
    source_id: str,
    critical: bool = True,
    stage: str = "sources",
) -> list[QualityCheck]:
    """A stale critical source must block deploy (`docs/OPERATIONS.md` section 9)."""
    age = ensure_utc(now) - ensure_utc(retrieved_at)
    if age > max_age:
        return [
            QualityCheck.fail(
                "source.stale",
                stage=stage,
                message=f"{source_id} data is older than its freshness budget",
                observed=f"{age}",
                expected=f"<= {max_age}",
                severity=Severity.CRITICAL if critical else Severity.WARNING,
            ),
        ]
    return [
        QualityCheck.ok(
            "source.fresh",
            stage=stage,
            message=f"{source_id} is within its freshness budget",
            observed=f"{age}",
        ),
    ]


def collect(*groups: Iterable[QualityCheck]) -> list[QualityCheck]:
    """Flatten several check groups into one list."""
    return [check for group in groups for check in group]
