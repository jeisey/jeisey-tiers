"""Typed internal entities, enums and frame contracts.

Import from here rather than from the submodules; the split is an implementation detail.
"""

from __future__ import annotations

from ffdraft.contracts.entities import (
    CanonicalPlayer,
    DepthChartObservation,
    MarketCohort,
    MarketQuote,
    PlayerCrosswalk,
    PlayerStatusObservation,
    ResolutionOutcome,
)
from ffdraft.contracts.enums import (
    CORE_POSITIONS,
    ArbitrageMode,
    CheckStatus,
    Confidence,
    DepthChartEra,
    EntityKind,
    Position,
    ResolutionStatus,
    Severity,
    SourceStatus,
)
from ffdraft.contracts.frames import ColumnSpec, FrameContract
from ffdraft.contracts.normalized import (
    CANONICAL_PLAYER_CONTRACT,
    DEPTH_CHART_CONTRACT,
    MARKET_QUOTE_CONTRACT,
    MFL_PLAYER_CONTRACT,
    PLAYER_IDS_CONTRACT,
    PLAYER_STATUS_CONTRACT,
    RESOLUTION_CONTRACT,
    ROSTER_CONTRACT,
)
from ffdraft.contracts.quality import (
    QualityCheck,
    critical_failures,
    failures,
    passed,
)
from ffdraft.contracts.source import (
    SourceBatch,
    SourceMetadata,
    ValidationReport,
    frame_content_hash,
)

__all__ = [
    "CANONICAL_PLAYER_CONTRACT",
    "CORE_POSITIONS",
    "DEPTH_CHART_CONTRACT",
    "MARKET_QUOTE_CONTRACT",
    "MFL_PLAYER_CONTRACT",
    "PLAYER_IDS_CONTRACT",
    "PLAYER_STATUS_CONTRACT",
    "RESOLUTION_CONTRACT",
    "ROSTER_CONTRACT",
    "ArbitrageMode",
    "CanonicalPlayer",
    "CheckStatus",
    "ColumnSpec",
    "Confidence",
    "DepthChartEra",
    "DepthChartObservation",
    "EntityKind",
    "FrameContract",
    "MarketCohort",
    "MarketQuote",
    "PlayerCrosswalk",
    "PlayerStatusObservation",
    "Position",
    "QualityCheck",
    "ResolutionOutcome",
    "ResolutionStatus",
    "Severity",
    "SourceBatch",
    "SourceMetadata",
    "SourceStatus",
    "ValidationReport",
    "critical_failures",
    "failures",
    "frame_content_hash",
    "passed",
]
