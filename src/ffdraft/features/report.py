"""The Phase-2 data-quality report.

The report exists to make the dataset's *shape* arguable. A single aggregate number would
hide the two things that matter most about this dataset: it spans an era boundary at 2025,
where depth context changes from a lagged proxy to a real observation (ADR-018), and its
feature coverage differs sharply between rookies and veterans. So everything is reported by
season and position, and the era-sensitive slices are reported separately rather than
averaged together.

Output is deterministic - sorted keys, sorted rows, no wall clock except the timestamp the
caller passes in - so two builds of the same data produce byte-identical reports and a diff
means the data changed.

Both forms are produced: JSON for machines and a Markdown summary for a human to read
before signing off a phase gate.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import polars as pl

from ffdraft.anchors import DRAFT_ANCHOR_RULE_VERSION, SeasonAnchor
from ffdraft.config import AppConfig
from ffdraft.contracts import QualityCheck
from ffdraft.contracts.enums import NFLVERSE_TEAM_CODES, CheckStatus, Severity
from ffdraft.features.dictionary import (
    FEATURE_DICTIONARY,
    FEATURE_SCHEMA_VERSION,
    FeatureRole,
    feature_names_by_family,
    feature_schema_hash,
    to_records,
)
from ffdraft.features.eligibility import (
    DepthContextState,
    TeamAtAnchorSource,
    UniverseEra,
)
from ffdraft.quality import semantic
from ffdraft.quality.thresholds import HistoricalThresholds
from ffdraft.scoring.engine import SCORING_ENGINE_VERSION
from ffdraft.scoring.horizon import fantasy_horizon, regular_season_weeks
from ffdraft.timeutil import isoformat_utc

__all__ = ["HistoricalQualityReport", "build_quality_report", "threshold_table"]

_POSITIONS = ("QB", "RB", "TE", "WR")


def threshold_table(
    thresholds: HistoricalThresholds | None = None,
) -> list[dict[str, Any]]:
    """The declared Phase-2 thresholds with the reason each one is where it is."""
    limits = thresholds or HistoricalThresholds.production()
    return [
        {
            "name": "threshold_profile",
            "value": limits.profile,
            "justification": (
                "`production` uses the thresholds measured on the real 2014-2025 dataset. "
                "`fixture` is the deliberately looser set the synthetic fixtures run under; "
                "it never applies to a real build."
            ),
        },
        {
            "name": "canonical_key_coverage",
            "minimum": limits.canonical_key_minimum,
            "justification": (
                "The preseason universe is assembled only from GSIS-keyed sources, so a row "
                "without a canonical key is a construction bug, not a coverage shortfall."
            ),
        },
        {
            "name": "duplicate_feature_keys",
            "maximum": limits.duplicate_key_maximum,
            "justification": "Named explicitly by the Phase-2 exit gate.",
        },
        {
            "name": "age_at_anchor_coverage",
            "minimum": limits.age_coverage_minimum,
            "justification": (
                "Measured 0.967 over 2014-2025, worst season 0.925. The gap is 380 deep "
                "fringe roster entries for whom no nflverse source publishes a birth date, "
                "not a join failure. Set below the observed rate with headroom so a real "
                "collapse in birth-date publication trips it."
            ),
        },
        {
            "name": "snap_bridge_coverage",
            "minimum": limits.snap_bridge_minimum,
            "justification": (
                "Snap counts are keyed by pfr_id and must cross an id space to reach the "
                "canonical key. This is the identity join that can genuinely fail, so it "
                "carries the gate; the canonical key itself cannot."
            ),
        },
        {
            "name": "expected_points_coverage",
            "minimum": limits.expected_points_minimum,
            "justification": (
                "ffopportunity models only plays it can attribute, so some players with a "
                "stat line legitimately have no expected-points row. The threshold is set "
                "to catch a broken join rather than normal attribution gaps."
            ),
        },
        {
            "name": "label_coverage",
            "minimum": limits.label_coverage_minimum,
            "justification": (
                "Every eligible row must receive a label under every scoring and league "
                "preset. A missing label is a join failure, never a data gap: a player who "
                "did not play scores zero."
            ),
        },
        {
            "name": "row_count_tolerance",
            "maximum": limits.row_count_tolerance,
            "justification": (
                "Wide enough for the genuine 2025 era change, which adds undrafted rookies "
                "earlier universes cannot see; narrow enough to catch a season whose source "
                "returned a fraction of its rows."
            ),
        },
    ]


@dataclass
class HistoricalQualityReport:
    """The report payload plus the checks it generated."""

    payload: dict[str, Any]
    checks: list[QualityCheck] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(self.payload, indent=2, sort_keys=True) + "\n"

    def to_markdown(self) -> str:
        return _render_markdown(self.payload)


def _coverage(frame: pl.DataFrame, column: str) -> float:
    if frame.is_empty() or column not in frame.columns:
        return 0.0
    return round(1.0 - frame.get_column(column).null_count() / frame.height, 4)


def _family_missingness(frame: pl.DataFrame) -> dict[str, float]:
    """Mean null rate per feature family, over model-input columns only."""
    families = feature_names_by_family()
    inputs = {spec.name for spec in FEATURE_DICTIONARY if spec.role is FeatureRole.FEATURE}
    result: dict[str, float] = {}
    for family, names in families.items():
        columns = [name for name in names if name in inputs and name in frame.columns]
        if not columns or frame.is_empty():
            continue
        rates = [frame.get_column(name).null_count() / frame.height for name in columns]
        result[family] = round(sum(rates) / len(rates), 4)
    return result


def _counts(frame: pl.DataFrame, *by: str) -> dict[str, int]:
    if frame.is_empty():
        return {}
    grouped = frame.group_by(list(by)).agg(pl.len().alias("rows")).sort(list(by))
    return {
        "/".join(str(row[key]) for key in by): int(row["rows"])
        for row in grouped.iter_rows(named=True)
    }


def build_quality_report(
    *,
    features: pl.DataFrame,
    fantasy_labels: pl.DataFrame,
    vorp_labels: pl.DataFrame,
    anchors: Mapping[int, SeasonAnchor],
    exclusions: pl.DataFrame,
    config: AppConfig,
    generated_at: datetime,
    dataset_version: str,
    upstream_checks: Sequence[QualityCheck] = (),
    source_metadata: Sequence[Mapping[str, Any]] = (),
    thresholds: HistoricalThresholds | None = None,
) -> HistoricalQualityReport:
    """Assemble the report and the semantic checks that go with it."""
    limits = thresholds or HistoricalThresholds.production()
    checks: list[QualityCheck] = list(upstream_checks)
    checks.extend(_semantic_checks(features, fantasy_labels))

    seasons = sorted(int(season) for season in anchors)
    per_season: list[dict[str, Any]] = []
    for season in seasons:
        rows = features.filter(pl.col("season") == season)
        labels = fantasy_labels.filter(pl.col("season") == season)
        vorp = vorp_labels.filter(pl.col("season") == season)
        horizon = fantasy_horizon(season)
        per_position = []
        for position in _POSITIONS:
            slice_ = rows.filter(pl.col("position") == position)
            if slice_.is_empty():
                continue
            per_position.append(
                {
                    "position": position,
                    "eligible_rows": slice_.height,
                    "rookies": int(slice_.filter(pl.col("rookie_flag")).height),
                    "veterans": int(slice_.filter(~pl.col("rookie_flag")).height),
                    "with_prior_season_stats": int(
                        slice_.filter(pl.col("has_prior_season_stats")).height,
                    ),
                    "coverage": {
                        "age_at_anchor": _coverage(slice_, "age_at_anchor"),
                        "prev1_games": _coverage(slice_, "prev1_games"),
                        "prev1_snap_share": _coverage(slice_, "prev1_snap_share"),
                        "prev1_xfp_pg": _coverage(slice_, "prev1_xfp_pg"),
                        "draft_round": _coverage(slice_, "draft_round"),
                        "combine_forty": _coverage(slice_, "combine_forty"),
                        "depth_rank_at_anchor": _coverage(slice_, "depth_rank_at_anchor"),
                        "prior_season_role_rank": _coverage(slice_, "prior_season_role_rank"),
                        "team_at_anchor": _coverage(slice_, "team_at_anchor"),
                    },
                    "missingness_by_family": _family_missingness(slice_),
                    "depth_context_state": _counts(slice_, "depth_context_state"),
                },
            )
        anchor = anchors[season]
        per_season.append(
            {
                "season": season,
                "anchor_at_utc": isoformat_utc(anchor.anchor_at_utc),
                "anchor_local": anchor.anchor_local.isoformat(),
                "first_kickoff_utc": isoformat_utc(anchor.first_kickoff_utc),
                "first_kickoff_game_id": anchor.first_kickoff_game_id,
                "days_before_kickoff": round(anchor.days_before_kickoff, 3),
                "fantasy_horizon": horizon.describe(),
                "universe_era": (
                    sorted(rows.get_column("universe_era").unique().to_list())
                    if not rows.is_empty()
                    else []
                ),
                "eligible_rows": rows.height,
                "duplicate_keys": int(rows.height - rows.select("season", "player_id").n_unique()),
                "rookies": (
                    int(rows.filter(pl.col("rookie_flag")).height) if not rows.is_empty() else 0
                ),
                "by_position": per_position,
                "depth_context_state": _counts(rows, "depth_context_state"),
                "eligibility_basis": _counts(rows, "eligibility_basis"),
                "team_at_anchor_source": _counts(rows, "team_at_anchor_source"),
                "fantasy_label_rows": labels.height,
                "fantasy_label_coverage": _label_coverage(rows, labels, config),
                "vorp_label_rows": vorp.height,
                "vorp_label_coverage": _vorp_coverage(rows, vorp, config),
                "zero_point_share_ppr": _zero_share(labels),
                "excluded": _counts(
                    exclusions.filter(pl.col("season") == season),
                    "reason",
                ),
            },
        )

    identity = _identity_metrics(features)
    payload: dict[str, Any] = {
        "report_version": "historical_quality_v1",
        "generated_at_utc": isoformat_utc(generated_at),
        "dataset": {
            "dataset_version": dataset_version,
            "feature_schema_version": FEATURE_SCHEMA_VERSION,
            "feature_schema_hash": feature_schema_hash(),
            "scoring_engine_version": SCORING_ENGINE_VERSION,
            "feature_cutoff_rule_version": DRAFT_ANCHOR_RULE_VERSION,
            "league_config_version": config.league.schema_version,
            "source_registry_version": config.registry.schema_version,
            "seasons": seasons,
            "feature_rows": features.height,
            "feature_columns": len(features.columns),
            "fantasy_label_rows": fantasy_labels.height,
            "vorp_label_rows": vorp_labels.height,
            "league_presets": sorted(
                vorp_labels.get_column("league_preset_id").unique().to_list(),
            )
            if not vorp_labels.is_empty()
            else [],
            "scoring_presets": sorted(
                fantasy_labels.get_column("scoring_preset").unique().to_list(),
            )
            if not fantasy_labels.is_empty()
            else [],
        },
        "identity": identity,
        "thresholds": threshold_table(limits),
        "seasons": per_season,
        "exclusions_by_reason": _counts(exclusions, "reason"),
        "source_metadata": [dict(record) for record in source_metadata],
        "feature_dictionary": to_records(),
        "checks": [check.to_dict() for check in checks],
        "check_summary": {
            "total": len(checks),
            "critical_failures": len([c for c in checks if c.blocking]),
            "warnings": len(
                [
                    c
                    for c in checks
                    if c.status is CheckStatus.FAIL and c.severity is Severity.WARNING
                ],
            ),
        },
    }
    checks.extend(_threshold_checks(identity, features, limits))
    payload["checks"] = [check.to_dict() for check in checks]
    payload["check_summary"] = {
        "total": len(checks),
        "critical_failures": len([c for c in checks if c.blocking]),
        "warnings": len(
            [c for c in checks if c.status is CheckStatus.FAIL and c.severity is Severity.WARNING],
        ),
    }
    return HistoricalQualityReport(payload=payload, checks=checks)


def _label_coverage(
    rows: pl.DataFrame,
    labels: pl.DataFrame,
    config: AppConfig,
) -> float:
    expected = rows.height * len(config.league.scoring)
    if expected == 0:
        return 0.0
    return round(labels.height / expected, 4)


def _vorp_coverage(rows: pl.DataFrame, vorp: pl.DataFrame, config: AppConfig) -> float:
    if vorp.is_empty():
        return 0.0
    presets = vorp.get_column("league_preset_id").n_unique()
    expected = rows.height * len(config.league.scoring) * presets
    if expected == 0:
        return 0.0
    return round(vorp.height / expected, 4)


def _zero_share(labels: pl.DataFrame) -> float:
    ppr = labels.filter(pl.col("scoring_preset") == "PPR")
    if ppr.is_empty():
        return 0.0
    return round(float(ppr.filter(pl.col("actual_fantasy_points") <= 0.0).height) / ppr.height, 4)


def _identity_metrics(features: pl.DataFrame) -> dict[str, Any]:
    if features.is_empty():
        return {
            "canonical_key_coverage": 0.0,
            "duplicate_feature_keys": 0,
            "age_at_anchor_coverage": 0.0,
            "snap_bridge_coverage": 0.0,
            "expected_points_coverage": 0.0,
            "rows_with_prior_season_stats": 0,
        }
    veterans = features.filter(pl.col("has_prior_season_stats"))
    return {
        "canonical_key_coverage": round(
            float(features.filter(pl.col("player_id").str.starts_with("gsis:")).height)
            / features.height,
            4,
        ),
        "duplicate_feature_keys": int(
            features.height - features.select("season", "player_id").n_unique(),
        ),
        "age_at_anchor_coverage": _coverage(features, "age_at_anchor"),
        "snap_bridge_coverage": _coverage(veterans, "prev1_snap_share"),
        "expected_points_coverage": _coverage(veterans, "prev1_xfp_pg"),
        "rows_with_prior_season_stats": veterans.height,
    }


def _threshold_checks(
    identity: Mapping[str, Any],
    features: pl.DataFrame,
    limits: HistoricalThresholds,
) -> list[QualityCheck]:
    checks: list[QualityCheck] = []
    for metric, minimum, severity in (
        ("canonical_key_coverage", limits.canonical_key_minimum, Severity.CRITICAL),
        ("age_at_anchor_coverage", limits.age_coverage_minimum, Severity.CRITICAL),
        ("snap_bridge_coverage", limits.snap_bridge_minimum, Severity.CRITICAL),
        ("expected_points_coverage", limits.expected_points_minimum, Severity.WARNING),
    ):
        observed = float(identity.get(metric, 0.0))
        if observed < minimum:
            checks.append(
                QualityCheck.fail(
                    f"historical.{metric}",
                    stage="historical",
                    message=f"{metric} is below its declared threshold",
                    observed=f"{observed:.4f}",
                    expected=f">= {minimum}",
                    severity=severity,
                ),
            )
        else:
            checks.append(
                QualityCheck.ok(
                    f"historical.{metric}",
                    stage="historical",
                    message=f"{metric} meets its declared threshold",
                    observed=f"{observed:.4f} >= {minimum}",
                ),
            )
    duplicates = int(identity.get("duplicate_feature_keys", 0))
    if duplicates > limits.duplicate_key_maximum:
        checks.append(
            QualityCheck.fail(
                "historical.duplicate_feature_keys",
                stage="historical",
                message="the feature table has duplicate (season, player_id) keys",
                observed=str(duplicates),
                expected=f"<= {limits.duplicate_key_maximum}",
            ),
        )
    else:
        checks.append(
            QualityCheck.ok(
                "historical.duplicate_feature_keys",
                stage="historical",
                message="(season, player_id) is unique across the feature table",
                observed=f"{features.height} row(s)",
            ),
        )
    checks.extend(
        semantic.check_row_count_stability(
            {
                int(row["season"]): int(row["rows"])
                for row in features.group_by("season")
                .agg(pl.len().alias("rows"))
                .sort("season")
                .iter_rows(named=True)
            },
            stage="historical",
            tolerance=limits.row_count_tolerance,
        ),
    )
    return checks


def _semantic_checks(features: pl.DataFrame, labels: pl.DataFrame) -> list[QualityCheck]:
    """Domain checks over the finished historical tables."""
    stage = "historical"
    checks: list[QualityCheck] = []
    if features.is_empty():
        return checks

    checks.extend(
        semantic.check_categorical_domain(
            features,
            column="position",
            allowed=_POSITIONS,
            stage=stage,
        ),
    )
    checks.extend(
        semantic.check_categorical_domain(
            features,
            column="depth_context_state",
            allowed=[str(state) for state in DepthContextState],
            stage=stage,
        ),
    )
    checks.extend(
        semantic.check_categorical_domain(
            features,
            column="feature_cutoff_rule_version",
            allowed=[DRAFT_ANCHOR_RULE_VERSION],
            stage=stage,
        ),
    )
    for column in ("team_at_anchor", "prev1_team"):
        checks.extend(
            semantic.check_categorical_domain(
                features,
                column=column,
                allowed=NFLVERSE_TEAM_CODES,
                stage=stage,
                allow_null=True,
            ),
        )
    checks.extend(
        semantic.check_categorical_domain(
            features,
            column="team_at_anchor_source",
            allowed=[str(source) for source in TeamAtAnchorSource],
            stage=stage,
        ),
    )
    checks.extend(
        semantic.check_categorical_domain(
            features,
            column="universe_era",
            allowed=[str(era) for era in UniverseEra],
            stage=stage,
        ),
    )
    checks.extend(
        semantic.check_bounded_share(
            features,
            columns=(
                "prev1_target_share",
                "prev1_rush_share",
                "prev1_snap_share",
                "prev1_catch_rate",
                "prev1_completion_pct",
                "prev1_rush_td_rate",
                "prev1_rec_td_rate",
                "prev1_pass_td_rate",
                "prev1_interception_rate",
            ),
            stage=stage,
        ),
    )
    checks.extend(
        semantic.check_non_negative(
            features,
            columns=(
                "prev1_games",
                "prev1_team_games",
                "prev1_games_missed",
                "prior5_games",
                "prior5_seasons",
                "experience_years",
                "prev1_carries_pg",
                "prev1_targets_pg",
                "prev1_receptions_pg",
                "depth_rank_at_anchor",
                "prior_season_role_rank",
                "draft_round",
                "draft_overall",
            ),
            stage=stage,
        ),
    )
    checks.extend(semantic.check_age_experience_draft_consistency(features, stage=stage))
    checks.extend(
        semantic.check_numeric_bounds(
            features,
            column="draft_round",
            minimum=1,
            maximum=12,
            stage=stage,
        ),
    )
    checks.extend(
        semantic.check_numeric_bounds(
            features,
            column="combine_forty",
            minimum=4.0,
            maximum=6.5,
            stage=stage,
        ),
    )
    checks.extend(
        semantic.check_numeric_bounds(
            features,
            column="depth_rank_at_anchor",
            minimum=1,
            maximum=20,
            stage=stage,
        ),
    )
    for ratio, denominator, minimum in (
        ("prev1_yards_per_carry", "prev1_carries_pg", 0.0),
        ("prev1_yards_per_target", "prev1_targets_pg", 0.0),
    ):
        checks.extend(
            semantic.check_ratio_denominator(
                features,
                ratio=ratio,
                denominator=denominator,
                minimum=minimum,
                stage=stage,
            ),
        )
    for column, budget in (
        ("age_at_anchor", 0.05),
        ("prev1_games", 0.60),
        ("draft_round", 0.60),
    ):
        checks.extend(
            semantic.check_missingness(
                features,
                column=column,
                max_null_rate=budget,
                stage=stage,
            ),
        )
    checks.extend(
        semantic.describe_distribution(
            features,
            column="prev1_fantasy_ppg_ppr",
            by=("season", "position"),
            stage=stage,
        ),
    )
    checks.extend(
        semantic.describe_distribution(
            features,
            column="age_at_anchor",
            by=("season", "position"),
            stage=stage,
        ),
    )
    if not labels.is_empty():
        checks.extend(
            semantic.check_season_week_consistency(
                labels.select(
                    "season",
                    pl.col("horizon_last_week").alias("week"),
                ),
                stage=stage,
                max_week_by_season={
                    int(season): regular_season_weeks(int(season))
                    for season in labels.get_column("season").unique().to_list()
                },
            ),
        )
        checks.extend(
            semantic.check_categorical_domain(
                labels,
                column="scoring_preset",
                allowed=("STD", "HALF", "PPR"),
                stage=stage,
            ),
        )
        checks.extend(
            semantic.check_non_negative(
                labels,
                columns=("actual_games_played", "actual_positional_rank"),
                stage=stage,
            ),
        )
    return checks


def _season_span(seasons: Sequence[int]) -> str:
    if not seasons:
        return "no seasons"
    return f"{seasons[0]}-{seasons[-1]}"


def _render_markdown(payload: Mapping[str, Any]) -> str:
    dataset = payload["dataset"]
    lines: list[str] = [
        "# Historical dataset quality report",
        "",
        f"Generated {payload['generated_at_utc']} · dataset `{dataset['dataset_version']}` · "
        f"feature schema `{dataset['feature_schema_version']}` "
        f"(`{dataset['feature_schema_hash']}`) · scoring `{dataset['scoring_engine_version']}` · "
        f"anchor rule `{dataset['feature_cutoff_rule_version']}`",
        "",
        f"{dataset['feature_rows']:,} feature rows across {len(dataset['seasons'])} seasons "
        f"({_season_span(dataset['seasons'])}), {dataset['feature_columns']} columns; "
        f"{dataset['fantasy_label_rows']:,} fantasy labels; "
        f"{dataset['vorp_label_rows']:,} VORP labels.",
        "",
        "## Gate summary",
        "",
        "| Check | Result |",
        "| --- | --- |",
        f"| critical failures | {payload['check_summary']['critical_failures']} |",
        f"| warnings | {payload['check_summary']['warnings']} |",
        f"| total checks | {payload['check_summary']['total']} |",
        "",
        "## Identity and coverage",
        "",
        "| Metric | Observed |",
        "| --- | ---: |",
    ]
    for key, value in sorted(payload["identity"].items()):
        lines.append(f"| {key} | {value} |")
    lines.extend(
        [
            "",
            "## Declared thresholds",
            "",
            "| Threshold | Bound | Justification |",
            "| --- | ---: | --- |",
        ],
    )
    for row in payload["thresholds"]:
        bound = row.get("minimum", row.get("maximum"))
        lines.append(f"| {row['name']} | {bound} | {row['justification']} |")

    lines.extend(
        [
            "",
            "## By season",
            "",
            "| Season | Anchor (UTC) | Lead (d) | Horizon | Rows | Rookies | Dupes | "
            "Observed depth | Role proxy | No depth | Zero-point share (PPR) |",
            "| --- | --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ],
    )
    for season in payload["seasons"]:
        states = season["depth_context_state"]
        lines.append(
            f"| {season['season']} | {season['anchor_at_utc']} | "
            f"{season['days_before_kickoff']} | {season['fantasy_horizon']} | "
            f"{season['eligible_rows']} | {season['rookies']} | {season['duplicate_keys']} | "
            f"{states.get(str(DepthContextState.DEPTH_OBSERVED_AT_ANCHOR), 0)} | "
            f"{states.get(str(DepthContextState.PRIOR_SEASON_ROLE_PROXY), 0)} | "
            f"{states.get(str(DepthContextState.DEPTH_UNAVAILABLE), 0)} | "
            f"{season['zero_point_share_ppr']:.1%} |",
        )

    lines.extend(
        [
            "",
            "## By season and position",
            "",
            "| Season | Pos | Rows | Rookies | Prior stats | age | prev1_games | snap share | "
            "xFP | draft | combine | depth rank | role rank |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"
            " ---: | ---: |",
        ],
    )
    for season in payload["seasons"]:
        for row in season["by_position"]:
            coverage = row["coverage"]
            lines.append(
                f"| {season['season']} | {row['position']} | {row['eligible_rows']} | "
                f"{row['rookies']} | {row['with_prior_season_stats']} | "
                f"{coverage['age_at_anchor']:.2f} | {coverage['prev1_games']:.2f} | "
                f"{coverage['prev1_snap_share']:.2f} | {coverage['prev1_xfp_pg']:.2f} | "
                f"{coverage['draft_round']:.2f} | {coverage['combine_forty']:.2f} | "
                f"{coverage['depth_rank_at_anchor']:.2f} | "
                f"{coverage['prior_season_role_rank']:.2f} |",
            )

    failures = [check for check in payload["checks"] if check["status"] == "fail"]
    lines.extend(["", "## Failing checks", ""])
    if not failures:
        lines.append("None.")
    else:
        lines.extend(["| Severity | Check | Observed | Expected |", "| --- | --- | --- | --- |"])
        for check in failures:
            lines.append(
                f"| {check['severity']} | `{check['check_id']}` | "
                f"{check['observed'][:180]} | {check['expected'][:120]} |",
            )

    lines.extend(["", "## Excluded candidates", "", "| Reason | Rows |", "| --- | ---: |"])
    for reason, count in sorted(payload["exclusions_by_reason"].items()):
        lines.append(f"| {reason} | {count} |")
    lines.append("")
    return "\n".join(lines)
