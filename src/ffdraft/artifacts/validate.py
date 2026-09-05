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

from ffdraft.artifacts.csv_flatten import flattener_for
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

#: The in-season bundle's own metadata file and schema. Separate from the draft bundle's
#: because the two are produced by different models at different cutoffs, carry different
#: build ids, and must be independently validatable (roadmap 12.5).
ROS_BUILD_METADATA_FILENAME = "ros_build_metadata.json"
ROS_BUILD_METADATA_SCHEMA = "ros_build_metadata"

#: Which artifacts belong to which bundle. A build id is compared inside a bundle and never
#: across one: a site legitimately holds a Tuesday draft board beside a Monday ROS board.
_IN_SEASON_ARTIFACTS = frozenset({"ros_tiers", "inseason_opportunity"})

#: How far two copies of the same intrinsic number may differ before the firewall check
#: fails. Zero, in effect: the opportunity board copies these values rather than computing
#: them, so any difference at all is a code path that recomputed one of them.
_INTRINSIC_COPY_TOLERANCE = 1e-9

#: The intrinsic fields the Opportunity Board copies from the rest-of-season board. Every one
#: of them is checked, because "behaviour never changes a value" is the phase's central claim
#: and a claim nobody tests is a comment.
#: The rest-of-season quantile columns, in order. Named explicitly rather than derived from
#: a prefix because the public vocabulary puts the quantile last (`ros_vorp_p10`) while the
#: preseason one puts it first (`p10_vorp`), and a shared helper that guessed would silently
#: check nothing.
_ROS_VORP_QUANTILES = (
    "ros_vorp_p10",
    "ros_vorp_p25",
    "ros_vorp_p50",
    "ros_vorp_p75",
    "ros_vorp_p90",
)
_ROS_POINT_QUANTILES = ("ros_points_p10", "ros_points_p50", "ros_points_p90")

_COPIED_INTRINSIC_FIELDS = (
    "ros_fair_rank",
    "ros_position_rank",
    "ros_expected_vorp",
    "ros_expected_points",
    "ros_expected_games",
    "ros_uncertainty",
    "ros_tier",
)


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
    gate.extend(_ros_metadata_checks(directory, envelopes))
    gate.extend(_cross_artifact_checks(envelopes))
    gate.extend(_in_season_cross_checks(envelopes))
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
        case "ros_tiers":
            return _ros_tier_checks(records, stage)
        case "inseason_opportunity":
            return _opportunity_checks(records, stage)
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
    # An artifact whose JSON record nests declares a CSV projection instead of inheriting
    # the schema's field order (ADR-065). The header is still fixed and still checked -
    # what changes is which declaration it is checked against.
    flattener = flattener_for(spec.artifact)
    expected_header = (
        list(flattener[0]) if flattener else list(record_field_order(spec.schema_name))
    )
    checks: list[QualityCheck] = []
    if rows[0] != expected_header:
        checks.append(
            QualityCheck.fail(
                "artifact.csv_header_mismatch",
                stage=stage,
                message=(
                    f"{path.name} columns must match its declared CSV projection"
                    if flattener
                    else f"{path.name} columns must match the record schema order"
                ),
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
    draft_envelopes = {
        artifact: envelope
        for artifact, envelope in envelopes.items()
        if artifact not in _IN_SEASON_ARTIFACTS
    }
    if not path.is_file():
        if not draft_envelopes:
            # An in-season-only directory is a legitimate shape: the two bundles are built by
            # different jobs and must validate independently (roadmap 12.5).
            return []
        return [
            QualityCheck.fail(
                "artifact.build_metadata_missing",
                stage=stage,
                message="build_metadata.json is required; the UI reads freshness from it",
                observed=str(path),
                expected=BUILD_METADATA_FILENAME,
            ),
        ]
    envelopes = draft_envelopes
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


def _monotonic_fields(
    records: Sequence[Mapping[str, Any]],
    fields: Sequence[str],
    *,
    label: str,
    stage: str,
) -> list[QualityCheck]:
    """Named quantile columns must be non-decreasing. Critical, as everywhere else."""
    offenders: list[str] = []
    for record in records:
        values = [record.get(field) for field in fields]
        if any(value is None for value in values):
            offenders.append(f"{record.get('player_id')} (missing quantile)")
            continue
        numeric = [float(value) for value in values]  # type: ignore[arg-type]
        if any(later < earlier for earlier, later in zip(numeric, numeric[1:], strict=False)):
            offenders.append(f"{record.get('player_id')} ({numeric})")
    if offenders:
        return [
            QualityCheck.fail(
                "artifact.non_monotonic_quantiles",
                stage=stage,
                message=f"{label} quantiles must be non-decreasing",
                observed="; ".join(offenders[:10]),
                expected=" <= ".join(fields),
            ),
        ]
    return [
        QualityCheck.ok(
            "artifact.non_monotonic_quantiles",
            stage=stage,
            message=f"{label} quantiles are non-decreasing on every row",
            observed=f"{len(records)} record(s)",
        ),
    ]


def _ros_tier_checks(
    records: Sequence[Mapping[str, Any]],
    stage: str,
) -> list[QualityCheck]:
    """Semantic rules a rest-of-season board must satisfy beyond its schema.

    The ADR-076 clauses are the ones worth stating plainly: the long-absence flag has to mean
    exactly what the ADR defines it to mean, and it has to be accompanied by the observable
    number that makes it checkable. A flag set on a player who has not played at all, or on
    one whose consecutive-miss count contradicts it, would be a different claim wearing the
    same name.
    """
    checks: list[QualityCheck] = [
        *_monotonic_fields(records, _ROS_VORP_QUANTILES, label="ros_vorp", stage=stage),
        *_monotonic_fields(records, _ROS_POINT_QUANTILES, label="ros_points", stage=stage),
        *check_finite(
            records,
            fields=("ros_expected_vorp", "ros_expected_points", "ros_uncertainty"),
            stage=stage,
        ),
        *check_range(records, field="ros_fair_rank", minimum=1, stage=stage),
        *check_range(records, field="ros_position_rank", minimum=1, stage=stage),
        *check_range(records, field="ros_uncertainty", minimum=0, stage=stage),
        *check_range(records, field="ros_expected_games", minimum=0, stage=stage),
        *check_range(records, field="through_week", minimum=1, stage=stage),
    ]

    mislabelled = [
        str(record.get("player_id"))
        for record in records
        if bool(record.get("long_absence"))
        and not (
            bool(record.get("has_played_this_season"))
            and float(record.get("consecutive_weeks_missed") or 0.0) >= 3.0
        )
    ]
    if mislabelled:
        checks.append(
            QualityCheck.fail(
                "ros.long_absence_definition",
                stage=stage,
                message=(
                    "long_absence must be set exactly when the player HAS played this season "
                    "and has missed three or more consecutive weeks (ADR-076)"
                ),
                observed="; ".join(mislabelled[:10]),
                expected="has_played_this_season and consecutive_weeks_missed >= 3",
            ),
        )
    missed = [
        str(record.get("player_id"))
        for record in records
        if not bool(record.get("long_absence"))
        and bool(record.get("has_played_this_season"))
        and float(record.get("consecutive_weeks_missed") or 0.0) >= 3.0
    ]
    if missed:
        checks.append(
            QualityCheck.fail(
                "ros.long_absence_unflagged",
                stage=stage,
                message=(
                    "a player meeting the long-absence condition is not flagged; the "
                    "disclosure contract is a property of the data, not of the renderer"
                ),
                observed="; ".join(missed[:10]),
                expected="every qualifying row carries long_absence",
            ),
        )
    if not mislabelled and not missed:
        flagged = sum(1 for record in records if record.get("long_absence"))
        checks.append(
            QualityCheck.ok(
                "ros.long_absence_definition",
                stage=stage,
                message=(
                    "the long-absence flag matches its ADR-076 definition on every row, and "
                    "weeks_since_last_game is published beside it"
                ),
                observed=f"{flagged} of {len(records)} row(s) flagged",
            ),
        )

    cutoffs = {int(record["through_week"]) for record in records if "through_week" in record}
    if len(cutoffs) > 1:
        checks.append(
            QualityCheck.fail(
                "ros.mixed_cutoffs",
                stage=stage,
                message="every row in one rest-of-season bundle must share the cutoff week",
                observed=", ".join(str(week) for week in sorted(cutoffs)),
                expected="one through_week",
            ),
        )
    return checks


def _opportunity_checks(
    records: Sequence[Mapping[str, Any]],
    stage: str,
) -> list[QualityCheck]:
    """Rules the Opportunity Board must satisfy, all about not inventing a quantity."""
    checks: list[QualityCheck] = [
        *check_range(records, field="ros_fair_rank", minimum=1, stage=stage),
        *check_range(records, field="add_count", minimum=0, stage=stage),
        *check_range(records, field="drop_count", minimum=0, stage=stage),
    ]

    inconsistent = [
        str(record.get("player_id"))
        for record in records
        if record.get("add_count") is not None
        and record.get("drop_count") is not None
        and record.get("net_add_count") is not None
        and int(record["net_add_count"]) != int(record["add_count"]) - int(record["drop_count"])
    ]
    if inconsistent:
        checks.append(
            QualityCheck.fail(
                "opportunity.net_add_arithmetic",
                stage=stage,
                message="net_add_count must equal add_count minus drop_count",
                observed="; ".join(inconsistent[:10]),
                expected="add_count - drop_count",
            ),
        )

    # A surfaced row is published *because* it is outside the tier depth, so it must not
    # carry a tier: a fabricated one is exactly the number the surface rule refuses to
    # invent (ADR-063).
    tiered_exceptions = [
        str(record.get("player_id"))
        for record in records
        if bool(record.get("outside_tier_board")) and record.get("ros_tier") is not None
    ]
    if tiered_exceptions:
        checks.append(
            QualityCheck.fail(
                "opportunity.surfaced_row_has_tier",
                stage=stage,
                message=(
                    "a player surfaced from beyond the tier depth must carry no tier; the "
                    "model never segmented him"
                ),
                observed="; ".join(tiered_exceptions[:10]),
                expected="null ros_tier",
            ),
        )
    unexplained = [
        str(record.get("player_id"))
        for record in records
        if bool(record.get("outside_tier_board")) and not record.get("surface_reasons")
    ]
    if unexplained:
        checks.append(
            QualityCheck.fail(
                "opportunity.surfaced_row_without_reason",
                stage=stage,
                message="a surfaced player must say why he is visible (ADR-063)",
                observed="; ".join(unexplained[:10]),
                expected="a non-empty surface_reasons list",
            ),
        )

    stale_behavior = [
        str(record.get("player_id"))
        for record in records
        if not bool(record.get("behavior_available"))
        and (record.get("add_count") is not None or record.get("drop_count") is not None)
    ]
    if stale_behavior:
        checks.append(
            QualityCheck.fail(
                "opportunity.counts_without_a_feed",
                stage=stage,
                message=(
                    "a row that declares no behaviour feed must publish no counts; a zero "
                    "and an absence are different claims"
                ),
                observed="; ".join(stale_behavior[:10]),
                expected="null add_count and drop_count",
            ),
        )
    if not (inconsistent or tiered_exceptions or unexplained or stale_behavior):
        surfaced = sum(1 for record in records if record.get("outside_tier_board"))
        checks.append(
            QualityCheck.ok(
                "opportunity.semantics",
                stage=stage,
                message=(
                    "behaviour counts are internally consistent, and every surfaced player "
                    "carries a reason and no invented tier"
                ),
                observed=f"{len(records)} row(s), {surfaced} surfaced beyond the tier depth",
            ),
        )
    return checks


def _ros_metadata_checks(
    directory: Path,
    envelopes: Mapping[str, Mapping[str, Any]],
) -> list[QualityCheck]:
    """Validate the in-season bundle's own metadata, and only when that bundle exists."""
    stage = "artifacts.ros_build_metadata"
    in_season = {
        artifact: envelope
        for artifact, envelope in envelopes.items()
        if artifact in _IN_SEASON_ARTIFACTS
    }
    path = directory / ROS_BUILD_METADATA_FILENAME
    if not in_season:
        return []
    if not path.is_file():
        return [
            QualityCheck.fail(
                "artifact.ros_build_metadata_missing",
                stage=stage,
                message=(
                    "ros_build_metadata.json is required beside a rest-of-season artifact: it "
                    "carries the cutoff week and the ADR-076 disclosures, and a board without "
                    "them may not be rendered"
                ),
                observed=str(path),
                expected=ROS_BUILD_METADATA_FILENAME,
            ),
        ]
    try:
        metadata: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [
            QualityCheck.fail(
                "artifact.ros_build_metadata_unreadable",
                stage=stage,
                message="could not read ros_build_metadata.json",
                observed=str(exc),
                expected="valid JSON",
            ),
        ]

    checks = list(validate_records(ROS_BUILD_METADATA_SCHEMA, [metadata], stage=stage))
    if any(check.blocking for check in checks):
        return checks

    for artifact, envelope in in_season.items():
        if envelope.get("build_id") != metadata.get("build_id"):
            checks.append(
                QualityCheck.fail(
                    "ros_build_metadata.build_id_mismatch",
                    stage=stage,
                    message=f"{artifact} carries a different build_id from ros_build_metadata",
                    observed=f"{artifact}={envelope.get('build_id')}",
                    expected=str(metadata.get("build_id")),
                ),
            )
        offenders = {
            int(record["through_week"])
            for record in envelope.get("records", ())
            if record.get("through_week") is not None
        } - {int(metadata.get("through_week", -1))}
        if offenders:
            checks.append(
                QualityCheck.fail(
                    "ros_build_metadata.cutoff_mismatch",
                    stage=stage,
                    message=f"{artifact} rows disagree with the bundle's declared cutoff week",
                    observed=", ".join(str(week) for week in sorted(offenders)),
                    expected=str(metadata.get("through_week")),
                ),
            )

    disclosures = metadata.get("disclosures", {})
    if disclosures.get("uses_injury_information") is not False:
        checks.append(
            QualityCheck.fail(
                "ros_build_metadata.injury_claim",
                stage=stage,
                message=(
                    "the rest-of-season model has no injury or practice-report feature "
                    "(ADR-070); the artifact must say so"
                ),
                observed=str(disclosures.get("uses_injury_information")),
                expected="false",
            ),
        )
    declared = int(disclosures.get("long_absence_players", -1))
    tiers = envelopes.get("ros_tiers")
    if tiers is not None and declared >= 0:
        actual = sum(1 for record in tiers.get("records", ()) if record.get("long_absence"))
        if actual != declared:
            checks.append(
                QualityCheck.fail(
                    "ros_build_metadata.long_absence_count",
                    stage=stage,
                    message=("the disclosed long-absence count disagrees with the published rows"),
                    observed=f"metadata {declared}, artifact {actual}",
                    expected="equal",
                ),
            )
    return checks


def _in_season_cross_checks(
    envelopes: Mapping[str, Mapping[str, Any]],
) -> list[QualityCheck]:
    """The market-firewall proof, run over the published bytes rather than over the code.

    Phase 12's central claim is that behaviour decides visibility and never value. The
    Opportunity Board copies its intrinsic columns from the rest-of-season board, so the
    claim is checkable by comparison: every player on both boards must carry identical
    intrinsic numbers. A single differing value means some code path recomputed one of them,
    which is precisely the thing that must not exist.
    """
    tiers = envelopes.get("ros_tiers")
    opportunity = envelopes.get("inseason_opportunity")
    if tiers is None or opportunity is None:
        return []

    published = {
        (
            record.get("league_preset_id"),
            record.get("scoring_preset"),
            record.get("player_id"),
        ): record
        for record in tiers.get("records", ())
    }
    mismatched: list[str] = []
    unexplained: list[str] = []
    compared = 0
    for record in opportunity.get("records", ()):
        key = (
            record.get("league_preset_id"),
            record.get("scoring_preset"),
            record.get("player_id"),
        )
        source = published.get(key)
        if source is None:
            # Absent from the tier board is exactly what a surfaced row is. It has to say so.
            if not (bool(record.get("outside_tier_board")) and record.get("surface_reasons")):
                unexplained.append(str(key))
            continue
        if bool(record.get("outside_tier_board")):
            unexplained.append(str(key))
            continue
        compared += 1
        for field in _COPIED_INTRINSIC_FIELDS:
            left, right = source.get(field), record.get(field)
            if left is None and right is None:
                continue
            if left is None or right is None:
                mismatched.append(f"{key}/{field}: {left!r} != {right!r}")
                continue
            if abs(float(left) - float(right)) > _INTRINSIC_COPY_TOLERANCE:
                mismatched.append(f"{key}/{field}: {left} != {right}")

    checks: list[QualityCheck] = []
    if mismatched:
        checks.append(
            QualityCheck.fail(
                "cross_artifact.intrinsic_value_modified",
                stage="artifacts",
                message=(
                    "an opportunity row's intrinsic value disagrees with the rest-of-season "
                    "board; behaviour may decide visibility and may never change a value"
                ),
                observed="; ".join(mismatched[:10]),
                expected="identical intrinsic columns on both boards",
            ),
        )
    if unexplained:
        checks.append(
            QualityCheck.fail(
                "cross_artifact.opportunity_row_not_in_ros_tiers",
                stage="artifacts",
                message=(
                    "an opportunity row is absent from the rest-of-season board without "
                    "declaring itself a surfaced exception, or declares itself one while the "
                    "board publishes him"
                ),
                observed="; ".join(unexplained[:10]),
                expected="outside_tier_board and surface_reasons on exactly the absent rows",
            ),
        )
    if not checks:
        checks.append(
            QualityCheck.ok(
                "cross_artifact.intrinsic_firewall",
                stage="artifacts",
                message=(
                    "every intrinsic value on the Opportunity Board is byte-identical to the "
                    "rest-of-season board's; behaviour changed visibility only"
                ),
                observed=(
                    f"{compared} player(s) compared across "
                    f"{len(_COPIED_INTRINSIC_FIELDS)} intrinsic field(s)"
                ),
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
    contradictory: list[str] = []
    rank_mismatch: list[str] = []
    for record in arbitrage.get("records", ()):
        key = (
            record.get("league_preset_id"),
            record.get("scoring_preset"),
            record.get("player_id"),
        )
        tier_record = tier_keys.get(key)
        # A surface exception is *supposed* to be absent from tiers: the market says he is
        # relevant, the model ranks him past the published tier depth, and ADR-063 publishes
        # him on the arbitrage board flagged as outside it. He is not a tier row and never
        # was, so requiring a subset relation here would forbid the rescue the whole surface
        # rule exists to perform. The exemption is narrow on purpose — the row has to *say*
        # it is an exception, in both fields — because the failure this check was written for
        # is an arbitrage row describing a player the board has no valuation for at all.
        surfaced = bool(record.get("outside_tier_board")) and bool(record.get("surface_reasons"))
        if tier_record is None:
            if not surfaced:
                missing.append(str(key))
        elif surfaced:
            contradictory.append(str(key))
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
    if contradictory:
        checks.append(
            QualityCheck.fail(
                "cross_artifact.surface_exception_is_on_the_board",
                stage="artifacts",
                message=(
                    "an arbitrage row claims to be surfaced from beyond the tier depth while "
                    "the tier artifact publishes him; one of the two is wrong"
                ),
                observed="; ".join(contradictory[:10]),
                expected="outside_tier_board is true only for players absent from tiers",
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
