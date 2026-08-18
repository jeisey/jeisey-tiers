"""Validation of a generated artifact directory.

Schema validity is necessary and nowhere near sufficient. A tier artifact can satisfy every
type constraint while numbering two players fair rank 4, splitting a tier across a gap, or
reporting a ``rank_gap`` with the wrong sign - and each of those would be visibly wrong on
the draft sheet. `docs/DATA_CONTRACTS.md` sections 8 and 12 list the semantic rules; this
module enforces them, plus the cross-artifact agreement no single schema can express.

Used by ``ffdraft validate-artifacts`` and by the Phase-1 fixture pipeline test.
"""

from __future__ import annotations

import csv
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from ffdraft.artifacts.schemas import (
    record_field_order,
    validate_envelope,
    validate_records,
)
from ffdraft.artifacts.spec import (
    ARTIFACT_SPECS,
    BUILD_METADATA_FILENAME,
    BUILD_METADATA_SCHEMA,
    spec_for,
)
from ffdraft.contracts import QualityCheck
from ffdraft.contracts.enums import Severity
from ffdraft.quality import (
    QualityGate,
    check_duplicate_keys,
    check_finite,
    check_quantiles_monotonic,
    check_range,
    check_unique_contiguous_tiers,
)

__all__ = ["validate_artifact_directory"]

#: ``rank_gap = market_adp - fair_rank`` (docs/DATA_CONTRACTS.md section 10). Positive means
#: the model would take the player earlier than the market does.
_RANK_GAP_TOLERANCE = 1e-6


def validate_artifact_directory(directory: Path) -> QualityGate:
    """Validate every artifact present in ``directory``.

    A missing optional artifact is not an error - a build may legitimately emit tiers
    without arbitrage when the market source failed (`docs/DATA_SOURCES.md` section 10).
    A missing ``build_metadata.json`` *is* an error: the frontend reads freshness from it.
    """
    gate = QualityGate()
    if not directory.is_dir():
        return gate.add(
            QualityCheck.fail(
                "artifact.directory_missing",
                stage="artifacts",
                message="artifact directory does not exist",
                observed=str(directory),
                expected="a directory of generated artifacts",
            ),
        )

    envelopes: dict[str, Mapping[str, Any]] = {}
    for artifact, spec in ARTIFACT_SPECS.items():
        path = directory / spec.json_filename
        if not path.is_file():
            continue
        payload = _load_json(path, gate)
        if payload is None:
            continue
        envelopes[artifact] = payload
        stage = f"artifacts.{artifact}"
        gate.extend(validate_envelope(payload, stage=stage))
        records = list(payload.get("records", ()))
        gate.extend(validate_records(spec.schema_name, records, stage=stage))
        gate.extend(check_duplicate_keys(records, key_fields=spec.key_fields, stage=stage))
        gate.extend(_semantic_checks(artifact, records, payload, stage))
        if spec.csv_filename:
            gate.extend(_csv_agreement(directory / spec.csv_filename, artifact, records, stage))

    gate.extend(_build_metadata_checks(directory, envelopes))
    gate.extend(_cross_artifact_checks(envelopes))
    if not envelopes:
        gate.add(
            QualityCheck.fail(
                "artifact.none_found",
                stage="artifacts",
                message="no known artifact files were found",
                observed=str(directory),
                expected=", ".join(spec.json_filename for spec in ARTIFACT_SPECS.values()),
            ),
        )
    return gate


def _load_json(path: Path, gate: QualityGate) -> Mapping[str, Any] | None:
    try:
        loaded: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        gate.add(
            QualityCheck.fail(
                "artifact.unreadable",
                stage="artifacts",
                message=f"could not read {path.name}",
                observed=str(exc),
                expected="valid UTF-8 JSON",
            ),
        )
        return None
    if not isinstance(loaded, Mapping):
        gate.add(
            QualityCheck.fail(
                "artifact.not_an_object",
                stage="artifacts",
                message=f"{path.name} must be a JSON object",
                observed=type(loaded).__name__,
                expected="object",
            ),
        )
        return None
    return loaded


def _semantic_checks(
    artifact: str,
    records: Sequence[Mapping[str, Any]],
    envelope: Mapping[str, Any],
    stage: str,
) -> list[QualityCheck]:
    match artifact:
        case "tiers":
            return [
                *check_unique_contiguous_tiers(records, stage=stage),
                *check_quantiles_monotonic(records, prefix="vorp", stage=stage),
                *check_finite(
                    records,
                    fields=("expected_vorp", "expected_points", "uncertainty"),
                    stage=stage,
                ),
                *check_range(records, field="fair_rank", minimum=1, stage=stage),
                *check_range(records, field="position_rank", minimum=1, stage=stage),
                *check_range(records, field="uncertainty", minimum=0, stage=stage),
            ]
        case "projections":
            return [
                *check_quantiles_monotonic(records, prefix="points", stage=stage),
                *check_finite(
                    records,
                    fields=("expected_points", "uncertainty_points"),
                    stage=stage,
                ),
                *check_range(records, field="uncertainty_points", minimum=0, stage=stage),
            ]
        case "arbitrage":
            return _arbitrage_checks(records, envelope, stage)
        case "market_snapshot":
            return [
                *check_range(records, field="market_adp", minimum=1e-9, stage=stage),
                *check_range(records, field="league_size", minimum=4, maximum=32, stage=stage),
                *_market_dispersion_checks(records, stage),
            ]
    return []


def _arbitrage_checks(
    records: Sequence[Mapping[str, Any]],
    envelope: Mapping[str, Any],
    stage: str,
) -> list[QualityCheck]:
    checks: list[QualityCheck] = [
        *check_range(records, field="arbitrage_score", minimum=0, maximum=100, stage=stage),
        *check_range(records, field="market_adp", minimum=1e-9, stage=stage),
        *check_range(records, field="p_positive_surplus", minimum=0, maximum=1, stage=stage),
    ]

    sign_offenders = [
        f"{record.get('player_id')}: {record.get('rank_gap')}"
        for record in records
        if abs(
            float(record.get("rank_gap", 0.0))
            - (float(record.get("market_adp", 0.0)) - float(record.get("fair_rank", 0.0)))
        )
        > _RANK_GAP_TOLERANCE
    ]
    if sign_offenders:
        checks.append(
            QualityCheck.fail(
                "arbitrage.rank_gap_convention",
                stage=stage,
                message="rank_gap must equal market_adp - fair_rank (positive = bargain)",
                observed="; ".join(sign_offenders[:10]),
                expected="market_adp - fair_rank",
            ),
        )
    else:
        checks.append(
            QualityCheck.ok(
                "arbitrage.rank_gap_convention",
                stage=stage,
                message="rank_gap follows the documented sign convention",
                observed=f"{len(records)} record(s)",
            ),
        )

    modes = {str(record.get("arbitrage_mode")) for record in records}
    declared = envelope.get("arbitrage_mode")
    if declared is not None and modes and modes != {str(declared)}:
        checks.append(
            QualityCheck.fail(
                "arbitrage.mode_mismatch",
                stage=stage,
                message="record arbitrage_mode disagrees with the envelope",
                observed=f"records {sorted(modes)}, envelope {declared}",
                expected="identical",
            ),
        )
    leaked = [
        str(record.get("player_id"))
        for record in records
        if str(record.get("arbitrage_mode")) == "baseline"
        and (
            record.get("expected_surplus_vorp") is not None
            or record.get("p_positive_surplus") is not None
        )
    ]
    if leaked:
        # ADR-010: baseline mode must not publish learned-model fields. Populating them
        # would claim a model that was never trained.
        checks.append(
            QualityCheck.fail(
                "arbitrage.baseline_mode_ml_fields",
                stage=stage,
                message="baseline-mode records must leave learned-model fields null (ADR-010)",
                observed="; ".join(leaked[:10]),
                expected="null expected_surplus_vorp and p_positive_surplus",
            ),
        )
    return checks


def _market_dispersion_checks(
    records: Sequence[Mapping[str, Any]],
    stage: str,
) -> list[QualityCheck]:
    offenders = [
        str(record.get("player_id"))
        for record in records
        if record.get("adp_low") is not None
        and record.get("adp_high") is not None
        and float(record["adp_low"]) > float(record["adp_high"])
    ]
    if offenders:
        return [
            QualityCheck.fail(
                "market.inverted_dispersion",
                stage=stage,
                message="adp_low must not exceed adp_high",
                observed="; ".join(offenders[:10]),
                expected="adp_low <= adp_high",
            ),
        ]
    return []


def _csv_agreement(
    path: Path,
    artifact: str,
    records: Sequence[Mapping[str, Any]],
    stage: str,
) -> list[QualityCheck]:
    """The CSV export must carry the same rows and columns as the JSON."""
    spec = spec_for(artifact)
    if not path.is_file():
        return [
            QualityCheck.fail(
                "artifact.csv_missing",
                stage=stage,
                message=f"{spec.json_filename} has no matching CSV export",
                observed=str(path),
                expected=spec.csv_filename or "",
            ),
        ]
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.reader(handle))
    if not rows:
        return [
            QualityCheck.fail(
                "artifact.csv_empty",
                stage=stage,
                message=f"{path.name} has no header row",
                observed="0 rows",
                expected="header + one row per record",
            ),
        ]
    expected_header = list(record_field_order(spec.schema_name))
    checks: list[QualityCheck] = []
    if rows[0] != expected_header:
        checks.append(
            QualityCheck.fail(
                "artifact.csv_header_mismatch",
                stage=stage,
                message=f"{path.name} columns must match the record schema order",
                observed=", ".join(rows[0]),
                expected=", ".join(expected_header),
            ),
        )
    if len(rows) - 1 != len(records):
        checks.append(
            QualityCheck.fail(
                "artifact.csv_row_count_mismatch",
                stage=stage,
                message=f"{path.name} row count disagrees with the JSON artifact",
                observed=f"{len(rows) - 1} data row(s)",
                expected=f"{len(records)}",
            ),
        )
    if not checks:
        checks.append(
            QualityCheck.ok(
                "artifact.csv_agrees",
                stage=stage,
                message=f"{path.name} agrees with {spec.json_filename}",
                observed=f"{len(rows) - 1} row(s)",
            ),
        )
    return checks


def _build_metadata_checks(
    directory: Path,
    envelopes: Mapping[str, Mapping[str, Any]],
) -> list[QualityCheck]:
    path = directory / BUILD_METADATA_FILENAME
    stage = "artifacts.build_metadata"
    if not path.is_file():
        return [
            QualityCheck.fail(
                "artifact.build_metadata_missing",
                stage=stage,
                message="build_metadata.json is required; the UI reads freshness from it",
                observed=str(path),
                expected=BUILD_METADATA_FILENAME,
            ),
        ]
    try:
        metadata: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [
            QualityCheck.fail(
                "artifact.build_metadata_unreadable",
                stage=stage,
                message="could not read build_metadata.json",
                observed=str(exc),
                expected="valid JSON",
            ),
        ]

    checks = list(validate_records(BUILD_METADATA_SCHEMA, [metadata], stage=stage))
    if any(check.blocking for check in checks):
        return checks

    gate = metadata.get("quality_gate", {})
    if gate.get("status") == "pass" and gate.get("critical_failures", 0):
        checks.append(
            QualityCheck.fail(
                "build_metadata.gate_inconsistent",
                stage=stage,
                message="quality_gate claims pass while reporting critical failures",
                observed=json.dumps(gate),
                expected="status=fail when critical_failures > 0",
            ),
        )
    supported = set(metadata.get("supported_presets", ()))
    for artifact, envelope in envelopes.items():
        if envelope.get("build_id") != metadata.get("build_id"):
            checks.append(
                QualityCheck.fail(
                    "build_metadata.build_id_mismatch",
                    stage=stage,
                    message=f"{artifact} carries a different build_id from build_metadata",
                    observed=f"{artifact}={envelope.get('build_id')}",
                    expected=str(metadata.get("build_id")),
                ),
            )
        presets = {
            str(record.get("league_preset_id"))
            for record in envelope.get("records", ())
            if record.get("league_preset_id") is not None
        }
        unknown = presets - supported
        if unknown:
            checks.append(
                QualityCheck.fail(
                    "build_metadata.unsupported_preset",
                    stage=stage,
                    message=f"{artifact} references presets absent from supported_presets",
                    observed=", ".join(sorted(unknown)),
                    expected=", ".join(sorted(supported)),
                ),
            )
    return checks


def _cross_artifact_checks(envelopes: Mapping[str, Mapping[str, Any]]) -> list[QualityCheck]:
    """Agreement no single artifact schema can express."""
    tiers = envelopes.get("tiers")
    arbitrage = envelopes.get("arbitrage")
    if tiers is None or arbitrage is None:
        return []

    tier_keys = {
        (
            record.get("league_preset_id"),
            record.get("scoring_preset"),
            record.get("player_id"),
        ): record
        for record in tiers.get("records", ())
    }
    missing: list[str] = []
    rank_mismatch: list[str] = []
    for record in arbitrage.get("records", ()):
        key = (
            record.get("league_preset_id"),
            record.get("scoring_preset"),
            record.get("player_id"),
        )
        tier_record = tier_keys.get(key)
        if tier_record is None:
            missing.append(str(key))
        elif int(tier_record["fair_rank"]) != int(record["fair_rank"]):
            rank_mismatch.append(
                f"{key}: tiers={tier_record['fair_rank']} arbitrage={record['fair_rank']}",
            )

    checks: list[QualityCheck] = []
    if missing:
        checks.append(
            QualityCheck.fail(
                "cross_artifact.arbitrage_player_not_in_tiers",
                stage="artifacts",
                message="every arbitrage row must describe a player present in tiers",
                observed="; ".join(missing[:10]),
                expected="arbitrage players are a subset of tier players",
            ),
        )
    if rank_mismatch:
        checks.append(
            QualityCheck.fail(
                "cross_artifact.fair_rank_disagreement",
                stage="artifacts",
                message="fair_rank must be identical in tiers and arbitrage",
                observed="; ".join(rank_mismatch[:10]),
                expected="identical fair_rank",
            ),
        )
    if not checks:
        checks.append(
            QualityCheck.ok(
                "cross_artifact.agreement",
                stage="artifacts",
                message="tiers and arbitrage agree on players and fair ranks",
                observed=f"{len(arbitrage.get('records', ()))} arbitrage record(s)",
            ),
        )

    metadata_presets = {str(record.get("league_preset_id")) for record in tiers.get("records", ())}
    if len(metadata_presets) == 0:
        checks.append(
            QualityCheck.fail(
                "cross_artifact.no_presets",
                stage="artifacts",
                message="tier artifact carries no league preset",
                observed="0",
                expected=">= 1",
                severity=Severity.WARNING,
            ),
        )
    return checks
