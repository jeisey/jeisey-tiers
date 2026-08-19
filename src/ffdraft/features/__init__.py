"""Historical feature engineering: the dictionary, eligibility, lagged aggregates, assembly."""

from __future__ import annotations

from ffdraft.features.build import (
    FeatureBuildResult,
    HistoricalSources,
    build_feature_table,
    pfr_to_gsis_bridge,
)
from ffdraft.features.dictionary import (
    FANTASY_LABEL_CONTRACT,
    FEATURE_DICTIONARY,
    FEATURE_SCHEMA_VERSION,
    HISTORICAL_FEATURE_CONTRACT,
    VORP_LABEL_CONTRACT,
    Availability,
    FeatureRole,
    FeatureSpec,
    feature_lineage,
    feature_schema_hash,
    intrinsic_feature_names,
)
from ffdraft.features.eligibility import (
    DepthContextState,
    EligibilityBasis,
    ExclusionReason,
    PreseasonUniverse,
    TeamAtAnchorSource,
    UniverseEra,
    build_preseason_universe,
)

__all__ = [
    "FANTASY_LABEL_CONTRACT",
    "FEATURE_DICTIONARY",
    "FEATURE_SCHEMA_VERSION",
    "HISTORICAL_FEATURE_CONTRACT",
    "VORP_LABEL_CONTRACT",
    "Availability",
    "DepthContextState",
    "EligibilityBasis",
    "ExclusionReason",
    "FeatureBuildResult",
    "FeatureRole",
    "FeatureSpec",
    "HistoricalSources",
    "PreseasonUniverse",
    "TeamAtAnchorSource",
    "UniverseEra",
    "build_feature_table",
    "build_preseason_universe",
    "feature_lineage",
    "feature_schema_hash",
    "intrinsic_feature_names",
    "pfr_to_gsis_bridge",
]
