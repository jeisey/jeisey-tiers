"""The Phase-2 leakage suite.

`AGENTS.md` section 7 makes leakage a release blocker, so each of the ten required rules
gets two tests: one proving the built dataset satisfies it, and one proving the guard would
*fail* if the rule were broken. A guard nobody has seen fail is a guard nobody has tested.

Rules 1 and 6 - no target-season statistic anywhere in a feature - cannot be checked by
looking at the finished table, because a leaked number looks like any other number. They are
proved by construction instead: rebuild each season with its own statistics deleted and
assert the table is byte-identical.
"""

from __future__ import annotations

import polars as pl
import pytest

from ffdraft.anchors import DRAFT_ANCHOR_RULE_VERSION
from ffdraft.features.build import build_feature_table
from ffdraft.features.dictionary import HISTORICAL_FEATURE_CONTRACT
from ffdraft.features.eligibility import (
    DepthContextState,
    EligibilityBasis,
    TeamAtAnchorSource,
    UniverseEra,
)
from ffdraft.features.sources import FIXTURE_TARGET_SEASONS
from ffdraft.leakage import (
    audit_anchor_cutoff,
    audit_career_fields_at_anchor,
    audit_dictionary_agreement,
    audit_eligibility_basis,
    audit_forbidden_intrinsic_inputs,
    audit_historical_features,
    audit_lagged_source_seasons,
    audit_pre_2025_depth,
    audit_target_season_independence,
    audit_team_context,
    redact_target_season_statistics,
)


def blocking(checks) -> list[str]:
    return [check.check_id for check in checks if check.blocking]


@pytest.fixture(scope="module")
def features(historical_dataset):
    return historical_dataset.features


# --------------------------------------------------------------------------------------
# Rules 1 and 6 - no target-season outcome reaches any feature
# --------------------------------------------------------------------------------------


def test_rule_1_and_6_features_are_independent_of_target_season_statistics(
    historical_sources,
    app_config,
):
    checks = audit_target_season_independence(
        historical_sources.sources,
        config=app_config,
        seasons=FIXTURE_TARGET_SEASONS,
    )
    assert not blocking(checks), [check.observed for check in checks]
    assert len(checks) == len(FIXTURE_TARGET_SEASONS)


def test_deleting_a_target_seasons_statistics_changes_nothing(
    historical_sources,
    app_config,
):
    """The same proof, spelled out: identical frames, column by column."""
    season = 2025
    full = build_feature_table(
        historical_sources.sources,
        config=app_config,
        seasons=[season],
    ).features
    redacted = build_feature_table(
        redact_target_season_statistics(historical_sources.sources, season),
        config=app_config,
        seasons=[season],
    ).features
    assert full.equals(redacted)


def test_the_redaction_actually_removes_the_target_seasons_statistics(historical_sources):
    """A vacuous redaction would make the independence proof meaningless."""
    sources = historical_sources.sources
    redacted = redact_target_season_statistics(sources, 2025)
    assert redacted.weekly_stats.height < sources.weekly_stats.height
    assert redacted.weekly_stats.filter(pl.col("season") == 2025).is_empty()
    assert redacted.snap_counts.filter(pl.col("season") == 2025).is_empty()
    assert redacted.expected_points.filter(pl.col("season") == 2025).is_empty()
    # The schedule survives: the anchor is derived from a Week-1 date published in May,
    # which is preseason context rather than a season outcome.
    assert redacted.schedule.equals(sources.schedule)


def test_the_independence_guard_fails_when_a_feature_reads_the_target_season(
    historical_sources,
    app_config,
    monkeypatch,
):
    """A builder that consumes a target-season statistic must be caught.

    The sabotage adds one column computed from the season being predicted - the shape of
    every real leak, whether it arrives through a mis-specified lag or an accidental join.
    Deleting the target season's rows then changes that column, and the content hashes
    diverge.
    """
    from ffdraft import leakage as leakage_module

    original = leakage_module.build_feature_table

    def leaky(sources, *, config, seasons):
        result = original(sources, config=config, seasons=seasons)
        target_season_totals = (
            sources.weekly_stats.filter(pl.col("season").is_in(list(seasons)))
            .group_by("gsis_id")
            .agg(pl.col("targets").sum().alias("_leaked_target_season_targets"))
        )
        result.features = result.features.join(target_season_totals, on="gsis_id", how="left")
        return result

    monkeypatch.setattr(leakage_module, "build_feature_table", leaky)
    checks = audit_target_season_independence(
        historical_sources.sources,
        config=app_config,
        seasons=[2025],
    )
    assert "leakage.target_season_independence" in blocking(checks)
    assert "_leaked_target_season_targets" in checks[0].observed


# --------------------------------------------------------------------------------------
# Rule 2 - timestamped observations satisfy the anchor cutoff
# --------------------------------------------------------------------------------------


def test_rule_2_every_timestamped_observation_predates_its_anchor(features):
    assert not blocking(audit_anchor_cutoff(features))
    stamped = features.filter(pl.col("depth_observed_at_utc").is_not_null())
    assert stamped.height > 0, "the fixture must exercise the timestamped path"
    assert stamped.filter(
        pl.col("depth_observed_at_utc") > pl.col("anchor_at_utc"),
    ).is_empty()


def test_rule_2_guard_fails_on_a_post_anchor_observation(features):
    broken = features.with_columns(
        pl.when(pl.col("depth_observed_at_utc").is_not_null())
        .then(pl.col("anchor_at_utc").dt.offset_by("1d"))
        .otherwise(None)
        .alias("depth_observed_at_utc"),
    )
    assert "leakage.anchor_cutoff" in blocking(audit_anchor_cutoff(broken))


# --------------------------------------------------------------------------------------
# Rule 3 - lagged aggregates precede the target season
# --------------------------------------------------------------------------------------


def test_rule_3_every_lagged_source_season_precedes_its_target(features):
    assert not blocking(audit_lagged_source_seasons(features))
    lagged = features.filter(pl.col("max_lagged_source_season").is_not_null())
    assert lagged.height > 0
    assert lagged.filter(
        pl.col("max_lagged_source_season") >= pl.col("season"),
    ).is_empty()


def test_rule_3_guard_fails_when_a_lag_reaches_the_target_season(features):
    broken = features.with_columns(pl.col("season").alias("max_lagged_source_season"))
    assert "leakage.lagged_source_season" in blocking(audit_lagged_source_seasons(broken))


# --------------------------------------------------------------------------------------
# Rule 4 - no pre-2025 row consumes week-1 or other post-anchor depth (ADR-018)
# --------------------------------------------------------------------------------------


def test_rule_4_no_pre_2025_row_carries_a_depth_observation(features):
    assert not blocking(audit_pre_2025_depth(features))
    pre_2025 = features.filter(pl.col("season") < 2025)
    assert pre_2025.height > 0, "the fixture must include a lagged-only season"
    assert pre_2025.get_column("depth_rank_at_anchor").null_count() == pre_2025.height
    assert pre_2025.get_column("depth_observed_at_utc").null_count() == pre_2025.height
    assert str(DepthContextState.DEPTH_OBSERVED_AT_ANCHOR) not in set(
        pre_2025.get_column("depth_context_state").to_list(),
    )


def test_rule_4_pre_2025_rows_use_a_lagged_proxy_or_declare_nothing(features):
    states = set(
        features.filter(pl.col("season") < 2025).get_column("depth_context_state").to_list(),
    )
    assert states <= {
        str(DepthContextState.PRIOR_SEASON_ROLE_PROXY),
        str(DepthContextState.DEPTH_UNAVAILABLE),
    }


def test_rule_4_guard_fails_when_a_week_one_depth_rank_is_used(features):
    """Exactly the ADR-018 violation: a 2024 row given a depth rank."""
    broken = features.with_columns(
        pl.when(pl.col("season") < 2025)
        .then(pl.lit(1, dtype=pl.Int32))
        .otherwise(pl.col("depth_rank_at_anchor"))
        .alias("depth_rank_at_anchor"),
    )
    assert "leakage.pre_2025_depth" in blocking(audit_pre_2025_depth(broken))


def test_rule_4_guard_also_fails_on_a_forged_state(features):
    broken = features.with_columns(
        pl.lit(str(DepthContextState.DEPTH_OBSERVED_AT_ANCHOR)).alias("depth_context_state"),
    )
    assert "leakage.pre_2025_depth" in blocking(audit_pre_2025_depth(broken))


# --------------------------------------------------------------------------------------
# Rule 5 - eligibility rests only on documented pre-anchor evidence
# --------------------------------------------------------------------------------------


def test_rule_5_eligibility_uses_only_the_documented_bases(features):
    assert not blocking(audit_eligibility_basis(features))
    bases = {
        basis
        for value in features.get_column("eligibility_basis").to_list()
        for basis in str(value).split("|")
    }
    assert bases <= {str(basis) for basis in EligibilityBasis}


def test_rule_5_guard_fails_on_an_undocumented_basis(features):
    broken = features.with_columns(
        pl.lit("target_season_participation").alias("eligibility_basis"),
    )
    assert "leakage.eligibility_basis" in blocking(audit_eligibility_basis(broken))


def test_rule_5_guard_fails_when_a_lagged_season_claims_a_snapshot(features):
    broken = features.with_columns(
        pl.lit(str(EligibilityBasis.DEPTH_SNAPSHOT_PRE_ANCHOR)).alias("eligibility_basis"),
        pl.lit(str(UniverseEra.LAGGED_ONLY)).alias("universe_era"),
    )
    assert "leakage.eligibility_era" in blocking(audit_eligibility_basis(broken))


# --------------------------------------------------------------------------------------
# Rule 7 - no market, expert or arbitrage input
# --------------------------------------------------------------------------------------


def test_rule_7_no_market_or_expert_input_reaches_the_feature_matrix(features, app_config):
    checks = audit_forbidden_intrinsic_inputs(features, registry=app_config.registry)
    assert not blocking(checks), [check.observed for check in checks]


@pytest.mark.parametrize(
    "column",
    ["market_adp", "prev1_ecr", "consensus_rank", "fantasypros_tier", "arbitrage_score"],
)
def test_rule_7_guard_fails_on_a_market_column_added_to_the_table(features, app_config, column):
    broken = features.with_columns(pl.lit(1.0).alias(column))
    checks = audit_forbidden_intrinsic_inputs(broken, registry=app_config.registry)
    assert "intrinsic.forbidden_feature_name" in blocking(checks)


def test_rule_7_guard_fails_on_market_lineage_even_with_an_innocent_name(app_config):
    from ffdraft.quality import audit_intrinsic_source_lineage

    lineage = {"prev1_value_score": ("myfantasyleague_adp",)}
    checks = audit_intrinsic_source_lineage(lineage, registry=app_config.registry)
    assert "intrinsic.forbidden_feature_lineage" in blocking(checks)


def test_rule_7_a_benchmark_only_source_can_never_become_a_feature(app_config):
    """ADR-014 approved FantasyPros for internal comparison, not as an input."""
    from ffdraft.quality import audit_intrinsic_source_lineage

    benchmark = sorted(app_config.registry.benchmark_only_sources)
    assert benchmark, "the registry must still carry a benchmark-only source"
    checks = audit_intrinsic_source_lineage(
        {"prev1_something": (benchmark[0],)},
        registry=app_config.registry,
    )
    assert "intrinsic.forbidden_feature_lineage" in blocking(checks)


# --------------------------------------------------------------------------------------
# Rule 8 - age, experience and draft capital are anchor-computable
# --------------------------------------------------------------------------------------


def test_rule_8_career_fields_are_computable_at_the_anchor(features):
    assert not blocking(audit_career_fields_at_anchor(features))


def test_rule_8_guard_fails_on_a_draft_year_after_the_season(features):
    broken = features.with_columns((pl.col("season") + 1).alias("draft_year"))
    assert "leakage.career_fields_at_anchor" in blocking(audit_career_fields_at_anchor(broken))


def test_rule_8_guard_fails_when_seasons_since_draft_disagrees_with_the_draft_year(features):
    broken = features.with_columns(
        pl.when(pl.col("draft_year").is_not_null())
        .then(pl.lit(99, dtype=pl.Int32))
        .otherwise(None)
        .alias("seasons_since_draft"),
    )
    assert "leakage.career_fields_at_anchor" in blocking(audit_career_fields_at_anchor(broken))


# --------------------------------------------------------------------------------------
# Rule 9 - no future team assignment
# --------------------------------------------------------------------------------------


def test_rule_9_team_context_uses_only_pre_anchor_observations(features):
    assert not blocking(audit_team_context(features))


def test_rule_9_a_lagged_only_season_has_no_observed_anchor_team(features):
    """Free agency and trades are unobservable before the snapshot era.

    The only pre-2025 rows that may carry an anchor team are that season's draftees, whose
    drafting club is a genuine April observation.
    """
    pre_2025 = features.filter(pl.col("season") < 2025)
    sources = set(pre_2025.get_column("team_at_anchor_source").to_list())
    assert sources <= {
        str(TeamAtAnchorSource.DRAFT_TEAM),
        str(TeamAtAnchorSource.UNAVAILABLE),
    }


def test_rule_9_guard_fails_when_a_team_appears_without_a_source(features):
    broken = features.with_columns(
        pl.lit("AAA").alias("team_at_anchor"),
        pl.lit(str(TeamAtAnchorSource.UNAVAILABLE)).alias("team_at_anchor_source"),
    )
    assert "leakage.team_context" in blocking(audit_team_context(broken))


def test_rule_9_guard_fails_when_a_change_flag_is_set_without_both_teams(features):
    broken = features.with_columns(
        pl.lit(True).alias("team_change_flag"),
        pl.lit(False).alias("team_change_known"),
    )
    assert "leakage.team_context" in blocking(audit_team_context(broken))


def test_rule_9_guard_fails_on_a_snapshot_team_in_a_lagged_only_season(features):
    broken = features.with_columns(
        pl.lit(str(TeamAtAnchorSource.DEPTH_SNAPSHOT_PRE_ANCHOR)).alias("team_at_anchor_source"),
        pl.lit(str(UniverseEra.LAGGED_ONLY)).alias("universe_era"),
    )
    assert "leakage.team_context" in blocking(audit_team_context(broken))


# --------------------------------------------------------------------------------------
# Rule 10 - the dictionary describes the table that was built
# --------------------------------------------------------------------------------------


def test_rule_10_the_dictionary_matches_the_built_table(features):
    assert not blocking(audit_dictionary_agreement(features))
    assert list(features.columns) == list(HISTORICAL_FEATURE_CONTRACT.column_names)


def test_rule_10_guard_fails_on_an_undeclared_column(features):
    broken = features.with_columns(pl.lit(1.0).alias("prev1_undeclared_thing"))
    assert "leakage.dictionary_columns" in blocking(audit_dictionary_agreement(broken))


def test_rule_10_guard_fails_when_a_declared_non_null_column_is_null(features):
    broken = features.with_columns(pl.lit(None, dtype=pl.String).alias("position"))
    assert "leakage.dictionary_nullability" in blocking(audit_dictionary_agreement(broken))


def test_rule_10_guard_fails_on_a_foreign_anchor_rule_version(features):
    broken = features.with_columns(
        pl.lit("draft_anchor_v0_something_else").alias("feature_cutoff_rule_version"),
    )
    assert "leakage.anchor_rule_version" in blocking(audit_dictionary_agreement(broken))


def test_every_row_records_the_declared_anchor_rule(features):
    assert features.get_column("feature_cutoff_rule_version").unique().to_list() == [
        DRAFT_ANCHOR_RULE_VERSION,
    ]


# --------------------------------------------------------------------------------------
# The whole suite, as the build runs it
# --------------------------------------------------------------------------------------


def test_the_full_audit_passes_on_the_built_dataset(historical_dataset, app_config):
    checks = audit_historical_features(
        historical_dataset.features,
        registry=app_config.registry,
        anchors=historical_dataset.anchors,
    )
    assert not blocking(checks), [check.to_dict() for check in checks if check.blocking]
    covered = {check.check_id for check in checks}
    for rule in (
        "leakage.anchor_cutoff",
        "leakage.lagged_source_season",
        "leakage.pre_2025_depth",
        "leakage.eligibility_basis",
        "leakage.career_fields_at_anchor",
        "leakage.team_context",
        "leakage.anchor_agreement",
    ):
        assert rule in covered, f"{rule} did not run"


def test_the_audit_notices_an_anchor_that_disagrees_with_its_season(
    historical_dataset,
    app_config,
):
    broken = historical_dataset.features.with_columns(
        pl.col("anchor_at_utc").dt.offset_by("30d").alias("anchor_at_utc"),
    )
    checks = audit_historical_features(
        broken,
        registry=app_config.registry,
        anchors=historical_dataset.anchors,
    )
    assert "leakage.anchor_agreement" in blocking(checks)
