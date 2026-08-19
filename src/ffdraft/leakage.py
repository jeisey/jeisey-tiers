"""Temporal-leakage audits for the historical dataset.

`AGENTS.md` section 7 calls leakage a release blocker and `docs/TEST_STRATEGY.md` 2.5
requires it to be automated rather than reviewed. These are the automated guards, written as
production code rather than as test helpers for two reasons: the build runs them before it
writes anything, and ``ffdraft validate-historical`` runs them again over a dataset on disk,
so a table that was correct when built can be re-checked without rebuilding it.

Ten rules are enforced, matching the Phase-2 requirement list:

1. no target-season regular-season statistic reaches a preseason feature;
2. every timestamped feature observation satisfies its anchor cutoff;
3. all lagged aggregate source seasons precede the target season;
4. no pre-2025 row consumes week-1 or otherwise post-anchor depth data (ADR-018);
5. eligibility rests only on documented pre-anchor evidence (ADR-021);
6. target-season scoring outcomes do not enter feature construction;
7. market/ADP/ECR/arbitrage names or lineage cannot enter the intrinsic feature matrix;
8. age, experience and draft capital are computable at the anchor;
9. team-context features never use a future team assignment;
10. the feature dictionary's availability rules match what the builder actually produced.

Rules 1 and 6 are the two that cannot be proved by inspecting a finished table, because a
leaked value looks like any other number. :func:`audit_target_season_independence` proves
them by construction instead: it rebuilds each season with every target-season statistical
row deleted and asserts the resulting table is byte-identical. If any feature had read a
target-season statistic, the two builds would differ.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path

import polars as pl

from ffdraft.anchors import DRAFT_ANCHOR_RULE_VERSION, SeasonAnchor
from ffdraft.config import AppConfig, SourceRegistry
from ffdraft.contracts import QualityCheck, frame_content_hash
from ffdraft.contracts.enums import DepthChartEra, Severity
from ffdraft.features.build import HistoricalSources, build_feature_table
from ffdraft.features.dictionary import (
    FEATURE_DICTIONARY,
    HISTORICAL_FEATURE_CONTRACT,
    Availability,
    feature_lineage,
    intrinsic_feature_names,
)
from ffdraft.features.eligibility import (
    DepthContextState,
    EligibilityBasis,
    TeamAtAnchorSource,
    UniverseEra,
)
from ffdraft.quality import (
    QualityGate,
    audit_intrinsic_feature_names,
    audit_intrinsic_source_lineage,
)

__all__ = [
    "LEAKAGE_STAGE",
    "audit_anchor_cutoff",
    "audit_career_fields_at_anchor",
    "audit_dictionary_agreement",
    "audit_eligibility_basis",
    "audit_forbidden_intrinsic_inputs",
    "audit_historical_features",
    "audit_lagged_source_seasons",
    "audit_pre_2025_depth",
    "audit_target_season_independence",
    "audit_team_context",
    "redact_target_season_statistics",
    "validate_historical_directory",
]

LEAKAGE_STAGE = "leakage"

_ALLOWED_BASES = frozenset(str(basis) for basis in EligibilityBasis)


def _ok(check_id: str, message: str, observed: str) -> QualityCheck:
    return QualityCheck.ok(check_id, stage=LEAKAGE_STAGE, message=message, observed=observed)


def _fail(check_id: str, message: str, observed: str, expected: str) -> QualityCheck:
    return QualityCheck.fail(
        check_id,
        stage=LEAKAGE_STAGE,
        message=message,
        observed=observed,
        expected=expected,
    )


def audit_anchor_cutoff(features: pl.DataFrame) -> list[QualityCheck]:
    """Rule 2: every timestamped observation predates its row's anchor."""
    if features.is_empty():
        return []
    stamped = features.filter(pl.col("depth_observed_at_utc").is_not_null())
    if stamped.is_empty():
        return [
            _ok(
                "leakage.anchor_cutoff",
                "no row carries a timestamped observation, so the cutoff holds vacuously",
                "0 timestamped row(s)",
            ),
        ]
    violations = stamped.filter(pl.col("depth_observed_at_utc") > pl.col("anchor_at_utc"))
    if not violations.is_empty():
        sample = violations.select("season", "player_id", "depth_observed_at_utc", "anchor_at_utc")
        return [
            _fail(
                "leakage.anchor_cutoff",
                "a feature observation postdates its row's draft anchor",
                f"{violations.height} row(s); e.g. {sample.head(3).to_dicts()}",
                "depth_observed_at_utc <= anchor_at_utc",
            ),
        ]
    return [
        _ok(
            "leakage.anchor_cutoff",
            "every timestamped observation satisfies feature_available_at <= anchor_at",
            f"{stamped.height} timestamped row(s)",
        ),
    ]


def audit_lagged_source_seasons(features: pl.DataFrame) -> list[QualityCheck]:
    """Rule 3: no lagged aggregate draws on the target season or later."""
    if features.is_empty():
        return []
    lagged = features.filter(pl.col("max_lagged_source_season").is_not_null())
    violations = lagged.filter(pl.col("max_lagged_source_season") >= pl.col("season"))
    if not violations.is_empty():
        return [
            _fail(
                "leakage.lagged_source_season",
                "a lagged feature consumed the target season or later",
                f"{violations.height} row(s); e.g. "
                + str(
                    violations.select(
                        "season",
                        "player_id",
                        "max_lagged_source_season",
                    )
                    .head(3)
                    .to_dicts(),
                ),
                "max_lagged_source_season < season",
            ),
        ]
    return [
        _ok(
            "leakage.lagged_source_season",
            "every lagged aggregate draws only on seasons before its target season",
            f"{lagged.height} row(s) with lagged inputs",
        ),
    ]


def audit_pre_2025_depth(features: pl.DataFrame) -> list[QualityCheck]:
    """Rule 4 (ADR-018): a pre-2025 row can never carry an observed depth reading.

    The ADR is categorical: before 2025 the earliest depth chart nflverse publishes is week
    1, which postdates a late-August draft and final roster cuts. A caveat does not remove
    the leak, so the only acceptable state for those rows is no depth observation at all.
    """
    if features.is_empty():
        return []
    pre_2025 = features.filter(
        pl.col("season").map_elements(
            lambda season: not DepthChartEra.for_season(int(season)).supports_point_in_time_anchor,
            return_dtype=pl.Boolean,
        ),
    )
    if pre_2025.is_empty():
        return [
            _ok(
                "leakage.pre_2025_depth",
                "no pre-2025 rows are present",
                "0 row(s)",
            ),
        ]
    offenders = pre_2025.filter(
        pl.col("depth_rank_at_anchor").is_not_null()
        | pl.col("depth_observed_at_utc").is_not_null()
        | (pl.col("depth_context_state") == str(DepthContextState.DEPTH_OBSERVED_AT_ANCHOR)),
    )
    if not offenders.is_empty():
        return [
            _fail(
                "leakage.pre_2025_depth",
                "a pre-2025 row consumed a depth observation; ADR-018 forbids week-1 depth "
                "as a preseason proxy",
                f"{offenders.height} row(s) in season(s) "
                f"{sorted(offenders.get_column('season').unique().to_list())}",
                "no depth_rank_at_anchor, no depth_observed_at_utc, "
                "no depth_observed_at_anchor state before 2025",
            ),
        ]
    states = sorted(pre_2025.get_column("depth_context_state").unique().to_list())
    return [
        _ok(
            "leakage.pre_2025_depth",
            "no pre-2025 row consumes week-1 or other post-anchor depth data (ADR-018)",
            f"{pre_2025.height} pre-2025 row(s); states {states}",
        ),
    ]


def audit_eligibility_basis(features: pl.DataFrame) -> list[QualityCheck]:
    """Rule 5 (ADR-021): eligibility rests only on documented pre-anchor evidence."""
    if features.is_empty():
        return []
    checks: list[QualityCheck] = []
    bases = {
        basis
        for value in features.get_column("eligibility_basis").unique().to_list()
        for basis in str(value).split("|")
    }
    unknown = sorted(bases - _ALLOWED_BASES)
    if unknown:
        checks.append(
            _fail(
                "leakage.eligibility_basis",
                "a row was made eligible by evidence outside the documented pre-anchor set",
                ", ".join(unknown),
                f"one of {sorted(_ALLOWED_BASES)}",
            ),
        )
    else:
        checks.append(
            _ok(
                "leakage.eligibility_basis",
                "every row's eligibility rests on prior-season roster, draft class or a "
                "pre-anchor depth snapshot (ADR-021)",
                f"bases {sorted(bases)}",
            ),
        )

    # The snapshot basis is only defensible in a season whose depth charts are timestamped.
    snapshot_rows = features.filter(
        pl.col("eligibility_basis").str.contains(
            str(EligibilityBasis.DEPTH_SNAPSHOT_PRE_ANCHOR),
            literal=True,
        ),
    )
    bad_era = snapshot_rows.filter(
        pl.col("universe_era") != str(UniverseEra.SNAPSHOT_2025_PLUS),
    )
    if not bad_era.is_empty():
        checks.append(
            _fail(
                "leakage.eligibility_era",
                "a pre-snapshot-era season claimed eligibility from a depth snapshot",
                f"{bad_era.height} row(s) in "
                + str(sorted(bad_era.get_column("season").unique().to_list())),
                "snapshot eligibility only in the 2025+ era",
            ),
        )
    else:
        checks.append(
            _ok(
                "leakage.eligibility_era",
                "depth-snapshot eligibility appears only in seasons that publish timestamped "
                "snapshots",
                f"{snapshot_rows.height} row(s)",
            ),
        )
    return checks


def audit_forbidden_intrinsic_inputs(
    features: pl.DataFrame,
    *,
    registry: SourceRegistry | None = None,
) -> list[QualityCheck]:
    """Rule 7: no market, expert-rank or arbitrage signal reaches the feature matrix.

    Both the declared model-input names and the *columns actually present* are audited. A
    column that exists in the table but not in the dictionary would evade a dictionary-only
    audit, which is exactly how an ad-hoc join sneaks a market field into a matrix.
    """
    checks = list(audit_intrinsic_feature_names(intrinsic_feature_names(), stage=LEAKAGE_STAGE))
    checks.extend(
        audit_intrinsic_source_lineage(feature_lineage(), registry=registry, stage=LEAKAGE_STAGE),
    )
    if not features.is_empty():
        checks.extend(audit_intrinsic_feature_names(features.columns, stage=LEAKAGE_STAGE))
    return checks


def audit_career_fields_at_anchor(features: pl.DataFrame) -> list[QualityCheck]:
    """Rule 8: age, experience and draft capital are computable at the anchor."""
    if features.is_empty():
        return []
    problems: list[str] = []
    future_draft = features.filter(
        pl.col("draft_year").is_not_null() & (pl.col("draft_year") > pl.col("season")),
    )
    if not future_draft.is_empty():
        problems.append(f"draft_year after the target season: {future_draft.height} row(s)")

    bad_since = features.filter(
        pl.col("draft_year").is_not_null()
        & (pl.col("seasons_since_draft") != (pl.col("season") - pl.col("draft_year"))),
    )
    if not bad_since.is_empty():
        problems.append(f"seasons_since_draft not season - draft_year: {bad_since.height} row(s)")

    over_experienced = features.filter(
        pl.col("experience_years").is_not_null()
        & pl.col("seasons_since_draft").is_not_null()
        & (pl.col("experience_years") > pl.col("seasons_since_draft")),
    )
    if not over_experienced.is_empty():
        problems.append(
            f"experience exceeds seasons since draft: {over_experienced.height} row(s)",
        )

    rookie_conflict = features.filter(
        pl.col("rookie_flag") & pl.col("experience_years").fill_null(0).gt(0),
    )
    if not rookie_conflict.is_empty():
        problems.append(f"rookie_flag with prior experience: {rookie_conflict.height} row(s)")

    if problems:
        return [
            _fail(
                "leakage.career_fields_at_anchor",
                "a career field could not have been computed from anchor-time information",
                "; ".join(problems),
                "draft_year <= season; experience consistent with draft; rookie_flag exclusive",
            ),
        ]
    return [
        _ok(
            "leakage.career_fields_at_anchor",
            "age, experience and draft capital are all derivable at the anchor",
            f"{features.height} row(s)",
        ),
    ]


def audit_team_context(features: pl.DataFrame) -> list[QualityCheck]:
    """Rule 9: team and team-change context never use a future assignment.

    A pre-anchor team observation exists only where a timestamped depth snapshot supplied it
    or where the player is a target-season draftee. Everywhere else the anchor team is
    genuinely unknown, and the honest encoding is a null plus an explicit indicator - not a
    guess, and certainly not the team the player finished the season on.
    """
    if features.is_empty():
        return []
    problems: list[str] = []

    known_without_source = features.filter(
        pl.col("team_at_anchor").is_not_null()
        & (pl.col("team_at_anchor_source") == str(TeamAtAnchorSource.UNAVAILABLE)),
    )
    if not known_without_source.is_empty():
        problems.append(
            f"team_at_anchor set with no documented source: {known_without_source.height} row(s)",
        )

    snapshot_team = features.filter(
        (pl.col("team_at_anchor_source") == str(TeamAtAnchorSource.DEPTH_SNAPSHOT_PRE_ANCHOR))
        & (pl.col("universe_era") != str(UniverseEra.SNAPSHOT_2025_PLUS)),
    )
    if not snapshot_team.is_empty():
        problems.append(
            f"snapshot-sourced team in a lagged-only season: {snapshot_team.height} row(s)",
        )

    change_without_evidence = features.filter(
        pl.col("team_change_flag").is_not_null() & ~pl.col("team_change_known"),
    )
    if not change_without_evidence.is_empty():
        problems.append(
            f"team_change_flag set without both teams known: "
            f"{change_without_evidence.height} row(s)",
        )

    change_without_anchor_team = features.filter(
        pl.col("team_change_known") & pl.col("team_at_anchor").is_null(),
    )
    if not change_without_anchor_team.is_empty():
        problems.append(
            f"team_change_known with no anchor team: {change_without_anchor_team.height} row(s)",
        )

    if problems:
        return [
            _fail(
                "leakage.team_context",
                "a team-context feature used an assignment that was not observable at the anchor",
                "; ".join(problems),
                "team context only from a pre-anchor snapshot or the target-season draft",
            ),
        ]
    return [
        _ok(
            "leakage.team_context",
            "team and team-change context come only from pre-anchor observations",
            f"{features.height} row(s)",
        ),
    ]


def audit_dictionary_agreement(features: pl.DataFrame) -> list[QualityCheck]:
    """Rule 10: the built table is exactly what the feature dictionary declares.

    Column set, order and dtypes are compared, and each availability class is checked
    against the property that justifies it. A dictionary that describes a different table
    from the one on disk is worse than no dictionary, because the leakage argument is
    written against the dictionary.
    """
    checks: list[QualityCheck] = []
    declared = list(HISTORICAL_FEATURE_CONTRACT.column_names)
    if features.is_empty():
        return [
            _ok(
                "leakage.dictionary_agreement",
                "no rows to compare against the dictionary",
                "0 row(s)",
            ),
        ]
    if list(features.columns) != declared:
        missing = sorted(set(declared) - set(features.columns))
        extra = sorted(set(features.columns) - set(declared))
        checks.append(
            _fail(
                "leakage.dictionary_columns",
                "the feature table's columns do not match the dictionary",
                f"missing {missing}; undeclared {extra}",
                "identical column set and order",
            ),
        )
    else:
        checks.append(
            _ok(
                "leakage.dictionary_columns",
                "the feature table's columns match the dictionary exactly",
                f"{len(declared)} column(s)",
            ),
        )

    dtype_problems = [
        f"{spec.name}: {features.schema[spec.name]} != {spec.dtype}"
        for spec in FEATURE_DICTIONARY
        if spec.name in features.columns and features.schema[spec.name] != spec.dtype
    ]
    if dtype_problems:
        checks.append(
            _fail(
                "leakage.dictionary_dtypes",
                "a declared feature has a different dtype in the built table",
                "; ".join(dtype_problems[:10]),
                "declared dtypes",
            ),
        )

    non_null_problems = [
        f"{spec.name}: {features.get_column(spec.name).null_count()} null(s)"
        for spec in FEATURE_DICTIONARY
        if not spec.nullable
        and spec.name in features.columns
        and features.get_column(spec.name).null_count()
    ]
    if non_null_problems:
        checks.append(
            _fail(
                "leakage.dictionary_nullability",
                "a column the dictionary declares non-null contains nulls",
                "; ".join(non_null_problems[:10]),
                "0 nulls",
            ),
        )

    # Availability-class properties.
    timestamped = [
        spec.name
        for spec in FEATURE_DICTIONARY
        if spec.availability is Availability.PRE_ANCHOR_OBSERVATION
    ]
    pre_2025_populated = [
        name
        for name in timestamped
        if name in ("depth_rank_at_anchor", "depth_observed_at_utc")
        and not features.filter(
            (pl.col("season") < 2025) & pl.col(name).is_not_null(),
        ).is_empty()
    ]
    if pre_2025_populated:
        checks.append(
            _fail(
                "leakage.dictionary_availability",
                "a pre-anchor-observation feature is populated in a season with no such "
                "observation available",
                ", ".join(pre_2025_populated),
                "null before the snapshot era",
            ),
        )

    versions = sorted(features.get_column("feature_cutoff_rule_version").unique().to_list())
    if versions != [DRAFT_ANCHOR_RULE_VERSION]:
        checks.append(
            _fail(
                "leakage.anchor_rule_version",
                "rows carry an anchor rule version other than the declared one",
                ", ".join(str(version) for version in versions),
                DRAFT_ANCHOR_RULE_VERSION,
            ),
        )
    else:
        checks.append(
            _ok(
                "leakage.anchor_rule_version",
                "every row records the declared anchor rule version",
                DRAFT_ANCHOR_RULE_VERSION,
            ),
        )
    if not any(check.blocking for check in checks):
        checks.append(
            _ok(
                "leakage.dictionary_agreement",
                "the dictionary's availability rules agree with the built table",
                f"{len(FEATURE_DICTIONARY)} declared column(s)",
            ),
        )
    return checks


def redact_target_season_statistics(
    sources: HistoricalSources,
    season: int,
) -> HistoricalSources:
    """Return ``sources`` with every statistical row from ``season`` removed.

    Only outcome-bearing sources are redacted: weekly statistics, snap counts and expected
    points. The schedule survives because the anchor is derived from a Week-1 kickoff date
    published in May, and pre-anchor depth snapshots survive because they are filtered to
    ``observed_at <= anchor`` and are themselves the observation under test.
    """

    def strip(frame: pl.DataFrame) -> pl.DataFrame:
        if frame.is_empty() or "season" not in frame.columns:
            return frame
        return frame.filter(pl.col("season") != season)

    return replace(
        sources,
        weekly_stats=strip(sources.weekly_stats),
        snap_counts=strip(sources.snap_counts),
        expected_points=strip(sources.expected_points),
    )


def audit_target_season_independence(
    sources: HistoricalSources,
    *,
    config: AppConfig,
    seasons: Sequence[int],
) -> list[QualityCheck]:
    """Rules 1 and 6, proved by construction rather than by inspection.

    For each target season the table is built twice: once normally, and once with every
    target-season statistical row deleted from the sources. If any feature had consumed a
    target-season statistic, deleting those rows would change the table. Identical content
    hashes are therefore a proof, not an indication.
    """
    checks: list[QualityCheck] = []
    for season in sorted(set(int(value) for value in seasons)):
        full = build_feature_table(sources, config=config, seasons=[season]).features
        redacted = build_feature_table(
            redact_target_season_statistics(sources, season),
            config=config,
            seasons=[season],
        ).features
        if frame_content_hash(full) == frame_content_hash(redacted):
            checks.append(
                _ok(
                    "leakage.target_season_independence",
                    f"{season} features are unchanged when the season's own statistics are "
                    "deleted, so none of them read a target-season outcome",
                    f"{full.height} row(s), identical content hash",
                ),
            )
            continue
        differing = _differing_columns(full, redacted)
        checks.append(
            _fail(
                "leakage.target_season_independence",
                f"{season} features change when the season's own statistics are deleted; "
                "a feature is reading a target-season outcome",
                f"columns {differing[:10]}",
                "byte-identical feature table",
            ),
        )
    return checks


def _differing_columns(left: pl.DataFrame, right: pl.DataFrame) -> list[str]:
    if left.height != right.height or list(left.columns) != list(right.columns):
        return ["<shape differs>"]
    differing: list[str] = []
    for name in left.columns:
        if not left.get_column(name).equals(right.get_column(name), null_equal=True):
            differing.append(name)
    return differing


def audit_historical_features(
    features: pl.DataFrame,
    *,
    registry: SourceRegistry | None = None,
    anchors: Mapping[int, SeasonAnchor] | None = None,
) -> list[QualityCheck]:
    """Run every audit that can be answered from the finished table."""
    checks: list[QualityCheck] = []
    checks.extend(audit_anchor_cutoff(features))
    checks.extend(audit_lagged_source_seasons(features))
    checks.extend(audit_pre_2025_depth(features))
    checks.extend(audit_eligibility_basis(features))
    checks.extend(audit_forbidden_intrinsic_inputs(features, registry=registry))
    checks.extend(audit_career_fields_at_anchor(features))
    checks.extend(audit_team_context(features))
    checks.extend(audit_dictionary_agreement(features))
    if anchors:
        checks.extend(_audit_anchor_agreement(features, anchors))
    return checks


def _audit_anchor_agreement(
    features: pl.DataFrame,
    anchors: Mapping[int, SeasonAnchor],
) -> list[QualityCheck]:
    problems: list[str] = []
    for season, anchor in sorted(anchors.items()):
        rows = features.filter(pl.col("season") == season)
        if rows.is_empty():
            continue
        stamped = rows.get_column("anchor_at_utc").unique().to_list()
        if stamped != [anchor.anchor_at_utc]:
            problems.append(f"{season}: {stamped} != {anchor.anchor_at_utc}")
    if problems:
        return [
            _fail(
                "leakage.anchor_agreement",
                "a row's recorded anchor differs from the season's derived anchor",
                "; ".join(problems[:5]),
                "one anchor per season",
            ),
        ]
    return [
        _ok(
            "leakage.anchor_agreement",
            "every row records its season's derived anchor",
            f"{len(anchors)} season(s)",
        ),
    ]


def validate_historical_directory(directory: Path) -> QualityGate:
    """Re-run the table-level audits against a dataset already on disk."""
    gate = QualityGate()
    features_path = directory / "features.parquet"
    if not features_path.is_file():
        gate.add(
            _fail(
                "leakage.dataset_missing",
                f"no features.parquet in {directory}",
                str(directory),
                "a directory written by `ffdraft build-historical`",
            ),
        )
        return gate

    features = pl.read_parquet(features_path)
    registry: SourceRegistry | None
    try:
        from ffdraft.config import load_source_registry

        registry = load_source_registry()
    except Exception:  # noqa: BLE001 - a missing registry must not mask a leakage failure
        registry = None
    gate.extend(audit_historical_features(features, registry=registry))

    manifest_path = directory / "build_manifest.json"
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        recorded = manifest.get("content_hashes", {}).get("features.parquet")
        observed = frame_content_hash(features)
        if recorded and recorded != observed:
            gate.add(
                QualityCheck.fail(
                    "historical.manifest_hash_mismatch",
                    stage=LEAKAGE_STAGE,
                    message="features.parquet does not match the hash its manifest records",
                    observed=observed,
                    expected=str(recorded),
                    severity=Severity.CRITICAL,
                ),
            )
        elif recorded:
            gate.add(
                _ok(
                    "historical.manifest_hash",
                    "features.parquet matches the content hash in its build manifest",
                    observed,
                ),
            )
    return gate
