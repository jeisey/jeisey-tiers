"""Closed vocabularies shared across the pipeline.

Every value here also appears in a public JSON Schema, a registry file or a documented
contract, so these enums are the single place a spelling is decided.
"""

from __future__ import annotations

from enum import StrEnum

__all__ = [
    "CORE_POSITIONS",
    "ArbitrageMode",
    "CheckStatus",
    "Confidence",
    "DepthChartEra",
    "EntityKind",
    "Position",
    "ResolutionStatus",
    "Severity",
    "SourceStatus",
]


class Position(StrEnum):
    """Fantasy positions supported by the artifact schemas."""

    QB = "QB"
    RB = "RB"
    WR = "WR"
    TE = "TE"
    K = "K"
    DST = "DST"

    @classmethod
    def parse(cls, raw: str | None) -> Position | None:
        """Map a source position string to a :class:`Position`, or ``None``.

        Matching is exact against a small alias table, deliberately. MFL's export contains
        team aggregate rows such as ``TMWR``/``TMRB``; a prefix or substring match would
        route those into WR/RB player identity, which is precisely the silent corruption
        AGENTS.md section 6 forbids. Anything unrecognised returns ``None`` and the caller
        decides - it never guesses.
        """
        if raw is None:
            return None
        token = raw.strip().upper()
        return _POSITION_ALIASES.get(token)


# Exact aliases only. `Def` is MFL's team-defence position and maps to DST, which is a real
# position that is never QB/RB/WR/TE. `TMWR` and friends are absent on purpose.
_POSITION_ALIASES: dict[str, Position] = {
    "QB": Position.QB,
    "RB": Position.RB,
    "WR": Position.WR,
    "TE": Position.TE,
    "K": Position.K,
    "PK": Position.K,
    "DST": Position.DST,
    "DEF": Position.DST,
    "D/ST": Position.DST,
}

#: The positions V1 models. K and DST are a documented post-launch extension (PRD 4).
CORE_POSITIONS: frozenset[Position] = frozenset(
    {Position.QB, Position.RB, Position.WR, Position.TE},
)


class EntityKind(StrEnum):
    """What an external record actually describes."""

    PLAYER = "player"
    #: A team aggregate (MFL ``Def``/``TM*``, a D/ST unit). Never a player.
    TEAM_UNIT = "team_unit"
    UNKNOWN = "unknown"


class ResolutionStatus(StrEnum):
    """Identity resolver outcomes (`docs/DATA_CONTRACTS.md` section 2.3)."""

    RESOLVED_EXACT_ID = "resolved_exact_id"
    RESOLVED_CROSSWALK = "resolved_crosswalk"
    RESOLVED_REVIEWED_ALIAS = "resolved_reviewed_alias"
    AMBIGUOUS = "ambiguous"
    UNRESOLVED = "unresolved"

    @property
    def is_resolved(self) -> bool:
        return self in {
            ResolutionStatus.RESOLVED_EXACT_ID,
            ResolutionStatus.RESOLVED_CROSSWALK,
            ResolutionStatus.RESOLVED_REVIEWED_ALIAS,
        }

    @property
    def eligible_for_production(self) -> bool:
        """Ambiguous and unresolved records never reach model or public layers."""
        return self.is_resolved


class Severity(StrEnum):
    """Quality-check severity (`docs/ARCHITECTURE.md` section 12)."""

    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"


class CheckStatus(StrEnum):
    PASS = "pass"
    FAIL = "fail"


class SourceStatus(StrEnum):
    """Per-source status as serialized into ``build_metadata.json``."""

    PASS = "pass"
    WARNING = "warning"
    FAILED = "failed"
    DISABLED = "disabled"


class Confidence(StrEnum):
    """Arbitrage confidence vocabulary from ``arbitrage_record.schema.json``."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNKNOWN = "unknown"


class ArbitrageMode(StrEnum):
    """ADR-010 fixes V1 at ``baseline``."""

    BASELINE = "baseline"
    ML = "ml"


class DepthChartEra(StrEnum):
    """The two upstream depth-chart schemas (ADR-015).

    Keeping the era on every observation is what lets ADR-018's leakage test distinguish a
    genuine point-in-time depth reading from a week-indexed row that postdates the anchor.
    """

    #: <= 2024: one row per team/week/slot. Earliest observation is week 1, after the draft.
    WEEKLY_PRE_2025 = "weekly_pre_2025"
    #: >= 2025: timestamped snapshots, so `dt <= anchor` gives a true point-in-time reading.
    SNAPSHOT_2025_PLUS = "snapshot_2025_plus"

    @classmethod
    def for_season(cls, season: int) -> DepthChartEra:
        return cls.SNAPSHOT_2025_PLUS if season >= 2025 else cls.WEEKLY_PRE_2025

    @property
    def supports_point_in_time_anchor(self) -> bool:
        return self is DepthChartEra.SNAPSHOT_2025_PLUS
