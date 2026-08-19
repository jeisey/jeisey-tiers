"""Feature-dictionary tests.

The dictionary is the document the entire leakage argument is written against, so these
tests treat it as a contract rather than as documentation: the built table must match it,
the committed Markdown must match it, and nothing market-derived may be declarable in it.
"""

from __future__ import annotations

import polars as pl
import pytest

from ffdraft.config import load_source_registry
from ffdraft.features.dictionary import (
    ALL_CORE_POSITIONS,
    CAREER_LOOKBACK_SEASONS,
    FANTASY_LABEL_CONTRACT,
    FEATURE_DICTIONARY,
    FEATURE_SCHEMA_VERSION,
    HISTORICAL_FEATURE_CONTRACT,
    VORP_LABEL_CONTRACT,
    Availability,
    FeatureRole,
    FeatureSpec,
    dictionary_markdown,
    feature_lineage,
    feature_schema_hash,
    intrinsic_feature_names,
    lagged_feature_names,
    spec_for,
    timestamped_feature_names,
    to_records,
)
from ffdraft.quality import audit_intrinsic_feature_names, audit_intrinsic_source_lineage


def test_the_dictionary_is_not_empty_and_has_unique_names():
    names = [spec.name for spec in FEATURE_DICTIONARY]
    assert len(names) > 50
    assert len(names) == len(set(names))


def test_the_frame_contract_is_built_from_the_dictionary():
    assert HISTORICAL_FEATURE_CONTRACT.column_names == tuple(
        spec.name for spec in FEATURE_DICTIONARY
    )
    assert HISTORICAL_FEATURE_CONTRACT.primary_key == ("season", "player_id")
    for spec in FEATURE_DICTIONARY:
        assert HISTORICAL_FEATURE_CONTRACT.spec(spec.name).dtype == spec.dtype


def test_every_declared_missingness_indicator_exists_and_is_boolean():
    for spec in FEATURE_DICTIONARY:
        if spec.missingness_indicator is None:
            continue
        indicator = spec_for(spec.missingness_indicator)
        assert indicator.dtype == pl.Boolean
        assert indicator.role is FeatureRole.INDICATOR
        assert indicator.nullable is False, "an indicator that can be null states nothing"


def test_a_lagged_feature_must_declare_a_lookback():
    with pytest.raises(ValueError, match="must declare a lookback"):
        FeatureSpec(
            name="prev1_bogus",
            dtype=pl.Float64,
            unit="unit",
            definition="",
            availability=Availability.SEASON_LAGGED,
            family="test",
        )


def test_a_lookback_of_zero_is_the_target_season_and_is_rejected():
    with pytest.raises(ValueError, match="offset 0 would be the"):
        FeatureSpec(
            name="prev0_bogus",
            dtype=pl.Float64,
            unit="unit",
            definition="",
            availability=Availability.SEASON_LAGGED,
            family="test",
            lookback_seasons=(0,),
        )


def test_a_column_barred_from_the_intrinsic_model_cannot_be_a_model_input():
    with pytest.raises(ValueError, match="cannot be a model input"):
        FeatureSpec(
            name="market_flavoured",
            dtype=pl.Float64,
            unit="unit",
            definition="",
            availability=Availability.STATIC_BIOGRAPHICAL,
            family="test",
            allowed_in_intrinsic=False,
        )


def test_every_lagged_lookback_is_at_least_one_season():
    for name in lagged_feature_names():
        spec = spec_for(name)
        assert spec.lookback_seasons
        assert min(spec.lookback_seasons) >= 1


def test_the_only_timestamped_features_are_depth_and_team_context():
    assert set(timestamped_feature_names()) >= {
        "depth_rank_at_anchor",
        "depth_observed_at_utc",
    }
    for name in timestamped_feature_names():
        assert spec_for(name).family in {"depth", "team_context"}


def test_the_career_window_is_fixed_and_declared():
    assert CAREER_LOOKBACK_SEASONS == (1, 2, 3, 4, 5)
    assert spec_for("prior5_games").lookback_seasons == CAREER_LOOKBACK_SEASONS


def test_no_declared_model_input_carries_a_market_or_expert_name():
    checks = audit_intrinsic_feature_names(intrinsic_feature_names())
    assert not any(check.blocking for check in checks), [c.observed for c in checks]


def test_no_declared_model_input_has_market_lineage():
    checks = audit_intrinsic_source_lineage(feature_lineage(), registry=load_source_registry())
    assert not any(check.blocking for check in checks), [c.observed for c in checks]


def test_only_nflverse_and_ffopportunity_supply_features():
    sources = {source for spec in FEATURE_DICTIONARY for source in spec.sources}
    assert sources <= {"nflreadpy", "ffopportunity"}


def test_position_restrictions_use_the_core_vocabulary():
    for spec in FEATURE_DICTIONARY:
        assert set(spec.positions) <= set(ALL_CORE_POSITIONS)
        assert spec.positions, f"{spec.name} applies to no position"


def test_the_schema_hash_is_stable_across_calls():
    assert feature_schema_hash() == feature_schema_hash()
    assert len(feature_schema_hash()) == 16


def test_records_render_every_documented_field():
    record = to_records()[0]
    for field in (
        "name",
        "family",
        "role",
        "dtype",
        "unit",
        "definition",
        "sources",
        "positions",
        "availability",
        "lookback_seasons",
        "missing_semantics",
        "missingness_indicator",
        "allowed_in_intrinsic",
    ):
        assert field in record


def test_the_committed_markdown_dictionary_matches_the_code(repo_root):
    """`docs/FEATURE_DICTIONARY.md` is generated, so a stale copy is a documentation bug.

    AGENTS.md section 18 makes code and its documented contract a source-of-truth pair. This
    is the pair for the feature table.
    """
    path = repo_root / "docs" / "FEATURE_DICTIONARY.md"
    text = path.read_text(encoding="utf-8")
    assert FEATURE_SCHEMA_VERSION in text
    assert feature_schema_hash() in text, (
        "docs/FEATURE_DICTIONARY.md is stale; regenerate it from "
        "`uv run ffdraft feature-dictionary`"
    )
    assert dictionary_markdown() in text


def test_the_label_contracts_key_on_the_documented_grains():
    assert FANTASY_LABEL_CONTRACT.primary_key == ("season", "player_id", "scoring_preset")
    assert VORP_LABEL_CONTRACT.primary_key == (
        "season",
        "player_id",
        "scoring_preset",
        "league_preset_id",
    )


def test_the_feature_table_is_scoring_independent():
    """No feature column may be specific to one scoring preset beyond the documented pair.

    Scoring-dependent quantities live in the label tables. Prior fantasy production is the
    deliberate exception: the columns are named for the presets they encode, and half-PPR
    follows arithmetically, so the table serves all three presets without carrying three
    copies of every football feature.
    """
    scoring_specific = sorted(
        spec.name
        for spec in FEATURE_DICTIONARY
        if spec.role.is_model_input
        and any(token in spec.name for token in ("_std", "_ppr", "_half"))
    )
    assert all(name.endswith(("_std", "_ppr", "_ppr_w")) for name in scoring_specific)
    assert all("fantasy" in name for name in scoring_specific), scoring_specific
