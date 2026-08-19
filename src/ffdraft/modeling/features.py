"""The Phase-3 core model-feature set.

Phase 2 published 85 leakage-safe model inputs. Not every leakage-safe feature is a
defensible model input, and this module is where that distinction is written down.

The rule is *era stability*. A feature earns a place in the Phase-3 core set only if its
support is comparable across the development seasons the models are actually validated on.
Seven columns fail that test and are excluded with a recorded reason:

* two carry no development-era signal at all - they are non-null only in 2025, the sealed
  season, so no development fold could ever validate them;
* three are missingness indicators whose value is constant (or nearly constant) before 2025
  and therefore encode "this row is from the snapshot era" rather than anything about
  football;
* one is the fantasy horizon expressed as a lagged team-game count, constant within a
  season by construction;
* one is a calendar index already carried, relative to the target season, by another
  column.

Excluding them is not a claim they are useless. It is a claim that Phase 3 has no honest
way to measure them, because the only season that supports them is sealed. Re-admitting one
after seeing 2025 would change the production feature set *after* the final holdout, which
is the exact move that invalidates a holdout; a genuinely snapshot-era-only input needs a
new validation strategy and a future season, not hindsight.

The selection is versioned and hashed, and both the hash and the full included/excluded
lists are written into every experiment report.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import polars as pl

from ffdraft.contracts import QualityCheck, Severity
from ffdraft.features.dictionary import (
    FEATURE_SCHEMA_VERSION,
    dictionary_by_name,
    feature_schema_hash,
    intrinsic_feature_names,
)
from ffdraft.modeling.preprocessing import scalar_float

__all__ = [
    "CORE_FEATURE_SET_VERSION",
    "ExclusionReason",
    "ExcludedFeature",
    "FeatureSelection",
    "audit_era_stability",
    "core_feature_selection",
]

#: Bump when the core set's membership or the reasoning behind it changes. A model artifact
#: records it next to the Phase-2 feature-schema hash, so an inference-time mismatch on
#: either level is detectable.
CORE_FEATURE_SET_VERSION = "intrinsic_core_v1"

#: A feature must be non-null on at least this share of rows in at least one development
#: season to be admissible at all. Set just above zero: the point is to exclude columns with
#: *no* development support, not to prune sparse-but-real signals such as combine drills.
MINIMUM_DEVELOPMENT_COVERAGE = 0.01

#: A boolean or categorical column that never varies within the development era carries no
#: information there and can only act as an era flag once a later season turns it on.
MINIMUM_DEVELOPMENT_VARIATION = 0.01


class ExclusionReason(StrEnum):
    """Why a leakage-safe Phase-2 model input is not a Phase-3 core feature."""

    SNAPSHOT_ERA_ONLY = "snapshot_era_only"
    ERA_INDICATOR = "era_indicator"
    HORIZON_ERA_INDEX = "horizon_era_index"
    TIME_INDEX = "time_index"


@dataclass(frozen=True, slots=True)
class ExcludedFeature:
    name: str
    reason: ExclusionReason
    evidence: str
    disposition: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "reason": str(self.reason),
            "evidence": self.evidence,
            "disposition": self.disposition,
        }


#: Every exclusion states the measurement behind it. The numbers come from the Phase-2
#: dataset built for 2014-2025 and are re-checked by :func:`audit_era_stability` on every
#: experiment run, so a claim here that stops being true fails the run rather than ageing
#: quietly in a comment.
_EXCLUSIONS: tuple[ExcludedFeature, ...] = (
    ExcludedFeature(
        name="depth_rank_at_anchor",
        reason=ExclusionReason.SNAPSHOT_ERA_ONLY,
        evidence=(
            "non-null on 0.0% of rows in every season 2014-2024 and 49.8% of 2025 "
            "(ADR-015: only the 2025+ depth charts are timestamped snapshots)"
        ),
        disposition=(
            "deferred production candidate; re-evaluate when a second snapshot-era season "
            "exists to validate on"
        ),
    ),
    ExcludedFeature(
        name="depth_rank_observed",
        reason=ExclusionReason.ERA_INDICATOR,
        evidence="constant false in every development season; true on 49.8% of 2025",
        disposition="diagnostic context; it is the era, not a feature",
    ),
    ExcludedFeature(
        name="team_change_flag",
        reason=ExclusionReason.SNAPSHOT_ERA_ONLY,
        evidence=(
            "non-null on 0.0% of rows 2014-2024 and 36.9% of 2025; a pre-anchor team "
            "observation does not exist before the snapshot era"
        ),
        disposition=(
            "deferred production candidate; backfilling it from target-season teams would "
            "be hindsight, so it stays absent rather than invented"
        ),
    ),
    ExcludedFeature(
        name="team_change_known",
        reason=ExclusionReason.ERA_INDICATOR,
        evidence="constant false in every development season; true on 36.9% of 2025",
        disposition="diagnostic context",
    ),
    ExcludedFeature(
        name="team_at_anchor_known",
        reason=ExclusionReason.ERA_INDICATOR,
        evidence=(
            "true on 7.1-11.7% of rows per development season against 50.6% of 2025; the "
            "shift is the data era, not a change in football"
        ),
        disposition="diagnostic context",
    ),
    ExcludedFeature(
        name="prev1_team_games",
        reason=ExclusionReason.HORIZON_ERA_INDEX,
        evidence=(
            "mean 15.0 in every target season through 2021 and 16.0 from 2022, i.e. the "
            "previous season's fantasy horizon (weeks 1-16 or 1-17) minus the bye, constant "
            "within a season apart from the cancelled 2022 game"
        ),
        disposition=(
            "kept in the dataset as the denominator behind prev1_games_missed, which "
            "carries the player-level durability content"
        ),
    ),
    ExcludedFeature(
        name="draft_year",
        reason=ExclusionReason.TIME_INDEX,
        evidence=(
            "a calendar index whose training-fold range never covers the validation "
            "season's rookies; seasons_since_draft = season - draft_year carries the same "
            "information relative to the target season and is era-stable"
        ),
        disposition="retained as context; seasons_since_draft is the model input",
    ),
)


@dataclass(frozen=True, slots=True)
class FeatureSelection:
    """The versioned Phase-3 model input view."""

    version: str
    included: tuple[str, ...]
    excluded: tuple[ExcludedFeature, ...]
    source_schema_version: str
    source_schema_hash: str

    @property
    def numeric(self) -> tuple[str, ...]:
        """Included columns a model consumes as numbers, booleans cast to 0/1."""
        return self.included

    def fingerprint(self) -> str:
        """Stable hash of the selection, recorded in every experiment and model artifact."""
        import hashlib
        import json

        specs = dictionary_by_name()
        payload = json.dumps(
            {
                "version": self.version,
                "source_schema_version": self.source_schema_version,
                "source_schema_hash": self.source_schema_hash,
                "included": [
                    {"name": name, "dtype": str(specs[name].dtype)} for name in self.included
                ],
                "excluded": [item.to_dict() for item in self.excluded],
            },
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]

    def to_dict(self) -> dict[str, Any]:
        specs = dictionary_by_name()
        return {
            "feature_set_version": self.version,
            "feature_set_hash": self.fingerprint(),
            "source_schema_version": self.source_schema_version,
            "source_schema_hash": self.source_schema_hash,
            "included_count": len(self.included),
            "included": [
                {
                    "name": name,
                    "family": specs[name].family,
                    "dtype": str(specs[name].dtype),
                    "availability": str(specs[name].availability),
                }
                for name in self.included
            ],
            "excluded_count": len(self.excluded),
            "excluded": [item.to_dict() for item in self.excluded],
        }


def core_feature_selection() -> FeatureSelection:
    """The Phase-3 core feature set: every Phase-2 model input minus the recorded exclusions."""
    excluded_names = {item.name for item in _EXCLUSIONS}
    declared = intrinsic_feature_names()
    unknown = sorted(excluded_names - set(declared))
    if unknown:
        raise ValueError(
            f"exclusion list names columns that are not Phase-2 model inputs: {unknown}",
        )
    included = tuple(name for name in declared if name not in excluded_names)
    return FeatureSelection(
        version=CORE_FEATURE_SET_VERSION,
        included=included,
        excluded=_EXCLUSIONS,
        source_schema_version=FEATURE_SCHEMA_VERSION,
        source_schema_hash=feature_schema_hash(),
    )


def _coverage_and_variation(
    frame: pl.DataFrame,
    column: str,
) -> tuple[float, float]:
    """Non-null share and a crude variation measure for one column of one season."""
    height = frame.height
    if height == 0:
        return 0.0, 0.0
    series = frame.get_column(column)
    coverage = 1.0 - (series.null_count() / height)
    values = series.drop_nulls()
    if values.len() == 0:
        return coverage, 0.0
    if series.dtype == pl.Boolean:
        share = scalar_float(values.cast(pl.Float64).mean())
        return coverage, min(share, 1.0 - share)
    unique = values.n_unique()
    return coverage, 0.0 if unique <= 1 else 1.0


def audit_era_stability(
    features: pl.DataFrame,
    *,
    selection: FeatureSelection,
    development_seasons: Sequence[int],
    stage: str = "phase3_features",
) -> tuple[list[QualityCheck], dict[str, Any]]:
    """Prove the included features actually have development-era support.

    The exclusions above are claims about measured coverage. This re-measures them on the
    dataset in hand, so an included feature that turns out to have no development-era
    support - or an excluded one that turns out to be fine - is a failing check rather than
    a stale comment. It returns both the checks and a per-feature coverage table for the
    report.
    """
    checks: list[QualityCheck] = []
    seasons = sorted(development_seasons)
    development = features.filter(pl.col("season").is_in(seasons))
    per_feature: dict[str, Any] = {}

    for name in (*selection.included, *(item.name for item in selection.excluded)):
        if name not in development.columns:
            checks.append(
                QualityCheck.fail(
                    "phase3.feature_missing_from_dataset",
                    stage=stage,
                    message=f"{name} is declared in the Phase-3 selection but absent from the "
                    "feature table",
                    observed=name,
                ),
            )
            continue
        by_season: dict[int, dict[str, float]] = {}
        for season in seasons:
            coverage, variation = _coverage_and_variation(
                development.filter(pl.col("season") == season),
                name,
            )
            by_season[season] = {"coverage": round(coverage, 4), "variation": round(variation, 4)}
        per_feature[name] = {
            "included": name in selection.included,
            "max_development_coverage": max(v["coverage"] for v in by_season.values()),
            "min_development_coverage": min(v["coverage"] for v in by_season.values()),
            "max_development_variation": max(v["variation"] for v in by_season.values()),
            "by_season": by_season,
        }

    for name in selection.included:
        stats = per_feature.get(name)
        if stats is None:
            continue
        if stats["max_development_coverage"] < MINIMUM_DEVELOPMENT_COVERAGE:
            checks.append(
                QualityCheck.fail(
                    "phase3.included_feature_has_no_development_support",
                    stage=stage,
                    message=(
                        f"{name} is in the Phase-3 core set but is non-null on at most "
                        f"{stats['max_development_coverage']:.1%} of rows in any development "
                        "season; a feature only the sealed season supports cannot be validated"
                    ),
                    observed=f"{name}: max coverage {stats['max_development_coverage']:.4f}",
                    expected=f">= {MINIMUM_DEVELOPMENT_COVERAGE}",
                ),
            )
        if stats["max_development_variation"] < MINIMUM_DEVELOPMENT_VARIATION:
            checks.append(
                QualityCheck.fail(
                    "phase3.included_feature_is_constant_in_development",
                    stage=stage,
                    message=(
                        f"{name} never varies in any development season, so it can only act "
                        "as an era flag once a later season turns it on"
                    ),
                    observed=f"{name}: max variation {stats['max_development_variation']:.4f}",
                    expected=f">= {MINIMUM_DEVELOPMENT_VARIATION}",
                ),
            )

    if not any(check.status.value == "fail" for check in checks):
        checks.append(
            QualityCheck.ok(
                "phase3.feature_era_stability",
                stage=stage,
                message=(
                    f"all {len(selection.included)} core features have development-era "
                    "coverage and variation"
                ),
                observed=f"seasons {seasons[0]}-{seasons[-1]}",
            ),
        )

    for item in selection.excluded:
        stats = per_feature.get(item.name)
        if stats is None:
            continue
        still_unsupported = (
            stats["max_development_coverage"] < MINIMUM_DEVELOPMENT_COVERAGE
            or stats["max_development_variation"] < MINIMUM_DEVELOPMENT_VARIATION
        )
        if item.reason in {ExclusionReason.SNAPSHOT_ERA_ONLY, ExclusionReason.ERA_INDICATOR}:
            checks.append(
                QualityCheck.ok(
                    "phase3.exclusion_evidence_holds",
                    stage=stage,
                    message=f"{item.name} excluded as {item.reason}",
                    observed=(
                        f"max development coverage {stats['max_development_coverage']:.4f}, "
                        f"variation {stats['max_development_variation']:.4f}"
                    ),
                )
                if still_unsupported
                else QualityCheck.fail(
                    "phase3.exclusion_evidence_stale",
                    stage=stage,
                    message=(
                        f"{item.name} was excluded as {item.reason} but now has development-era "
                        "support; revisit the exclusion rather than leaving the reason stale"
                    ),
                    observed=(
                        f"max development coverage {stats['max_development_coverage']:.4f}, "
                        f"variation {stats['max_development_variation']:.4f}"
                    ),
                    severity=Severity.WARNING,
                ),
            )

    return checks, per_feature


def assert_no_forbidden_features(
    included: Iterable[str],
    *,
    lineage: Mapping[str, Sequence[str]] | None = None,
) -> None:
    """Belt and braces over ADR-002: the Phase-3 view may only narrow Phase 2's inputs."""
    declared = set(intrinsic_feature_names())
    extra = sorted(set(included) - declared)
    if extra:
        raise ValueError(
            "the Phase-3 core feature set may only select from the Phase-2 model inputs; "
            f"unknown columns: {extra}",
        )
    if lineage is not None:
        for name in included:
            if name not in lineage:
                raise ValueError(f"{name} has no declared source lineage")
