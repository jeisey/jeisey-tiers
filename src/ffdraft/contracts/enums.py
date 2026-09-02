"""Closed vocabularies shared across the pipeline.

Every value here also appears in a public JSON Schema, a registry file or a documented
contract, so these enums are the single place a spelling is decided.
"""

from __future__ import annotations

from enum import StrEnum

__all__ = [
    "CORE_POSITIONS",
    "NFLVERSE_TEAM_CODES",
    "PFR_TEAM_ALIASES",
    "AggregationWindow",
    "ArbitrageMode",
    "BehaviorType",
    "CheckStatus",
    "Confidence",
    "DepthChartEra",
    "EntityKind",
    "MarketSignalType",
    "Position",
    "ResolutionStatus",
    "Severity",
    "SourceStatus",
    "SurfaceReason",
    "normalize_team_code",
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


#: The 32 current franchise abbreviations nflverse uses across rosters, statistics and depth
#: charts. nflverse standardises relocated franchises onto their present code, so a 2015
#: St. Louis roster row reads ``LA``; keeping to that convention is what lets
#: ``team_at_anchor`` and ``prev1_team`` be compared at all.
NFLVERSE_TEAM_CODES: frozenset[str] = frozenset(
    {
        "ARI",
        "ATL",
        "BAL",
        "BUF",
        "CAR",
        "CHI",
        "CIN",
        "CLE",
        "DAL",
        "DEN",
        "DET",
        "GB",
        "HOU",
        "IND",
        "JAX",
        "KC",
        "LA",
        "LAC",
        "LV",
        "MIA",
        "MIN",
        "NE",
        "NO",
        "NYG",
        "NYJ",
        "PHI",
        "PIT",
        "SEA",
        "SF",
        "TB",
        "TEN",
        "WAS",
    },
)

#: Pro Football Reference abbreviations, which arrive through the draft-pick and combine
#: tables, mapped onto the nflverse codes everything else uses. Relocated franchises map to
#: their current code for the same reason nflverse does it: a franchise that moved is the
#: same franchise, and two vocabularies in one column is a semantic drift waiting to happen.
PFR_TEAM_ALIASES: dict[str, str] = {
    "GNB": "GB",
    "KAN": "KC",
    "LAR": "LA",
    "LVR": "LV",
    "NOR": "NO",
    "NWE": "NE",
    "OAK": "LV",
    "SDG": "LAC",
    "SFO": "SF",
    "STL": "LA",
    "TAM": "TB",
    "RAI": "LV",
    "RAM": "LA",
    "SD": "LAC",
    "JAC": "JAX",
    "WSH": "WAS",
}


def normalize_team_code(raw: str | None) -> str | None:
    """Map a team abbreviation onto the nflverse vocabulary, or return it unchanged.

    An unrecognised code is passed through rather than dropped: the domain check in the
    quality report is what should notice a genuinely new abbreviation, and silently blanking
    it would hide exactly the source change worth seeing.
    """
    if raw is None:
        return None
    code = str(raw).strip().upper()
    if not code:
        return None
    return PFR_TEAM_ALIASES.get(code, code)


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


class MarketSignalType(StrEnum):
    """What a market quote actually measures (Phase 10, ADR-062).

    The distinction is the load-bearing one in the whole multi-source layer. An **ADP** is
    an observed draft price: people spent picks. An **ECR** is an expert consensus ranking:
    people expressed an opinion. They answer different questions, they move for different
    reasons, and averaging one into the other produces a number that describes neither.

    `docs/RELEASE2_ROADMAP.md` 10.3 states the rule this enum exists to make enforceable:
    *ECR must never masquerade as ADP*, and cross-market ADP aggregates exclude ECR. A
    boolean or a free-text label would have let a caller forget; a closed vocabulary on
    every quote row means the aggregate can filter on it and a test can assert it.
    """

    ADP = "adp"
    ECR = "ecr"


class AggregationWindow(StrEnum):
    """How a source aggregates the drafts behind a price (Phase 10, ADR-062).

    MyFantasyLeague publishes a season-cumulative aggregate: every draft since the export
    year opened. Fantasy Football Calculator publishes a bounded recent window. Both are
    called "ADP" and they are not the same measurement — a cumulative number moves slowly
    because it is anchored by months of old drafts, a recent one reacts to this week.

    Presenting them as interchangeable would be the "opaque consensus" Release 2's
    guardrail 2.3 forbids, so the window travels on the quote and reaches the UI.
    """

    #: A bounded recent window. ``aggregation_window_days`` says how bounded, when known.
    ROLLING = "rolling"
    #: Every draft in the source's season to date.
    SEASON_CUMULATIVE = "season_cumulative"
    #: A ranking with no draft window at all (ECR). Not "unknown" — structurally absent.
    NOT_APPLICABLE = "not_applicable"
    #: The source publishes a price but documents no window. Never guessed at.
    UNKNOWN = "unknown"


class BehaviorType(StrEnum):
    """Waiver-wire behaviour, which is not a draft price (Phase 10, ADR-062).

    Sleeper's trending feeds count adds and drops. Roadmap 10.3 is explicit that these must
    not be overloaded onto an ADP/ECR quote record: a count of adds is not a pick number and
    a schema that let it sit in ``market_adp`` would eventually see it charted as one.
    """

    ADD = "add"
    DROP = "drop"


class SurfaceReason(StrEnum):
    """Why a player is publicly visible (Phase 10, ADR-063).

    Visibility and valuation are separated deliberately. A market signal may decide *whether
    a player is surfaced*; it may never touch his intrinsic projection, VORP, fair rank or
    tier. Every surfaced player therefore carries the reasons he qualified, and a reader (or
    a test) can see that the reason was market relevance rather than a changed model.

    Not every member is active in draft mode; the vocabulary is shared with Phase 12 so the
    in-season surface does not need a second, subtly different contract.
    """

    #: Inside the versioned tier-segmentation depth. The ordinary case.
    INTRINSIC_TOP_TIER_DEPTH = "intrinsic_top_tier_depth"
    MARKET_TOP300_FFC_ADP = "market_top300_ffc_adp"
    MARKET_TOP300_FANTASYPROS_ADP = "market_top300_fantasypros_adp"
    MARKET_TOP300_FANTASYPROS_ECR = "market_top300_fantasypros_ecr"
    MARKET_TOP300_MFL_ADP = "market_top300_mfl_adp"
    #: Phase 12 members. Declared now so the contract does not change shape mid-season.
    CURRENT_ROSTER_RELEVANT = "current_roster_relevant"
    SLEEPER_TRENDING_ADD = "sleeper_trending_add"
    SLEEPER_TRENDING_DROP = "sleeper_trending_drop"
    CURRENT_DEPTH_PROMOTION = "current_depth_promotion"


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
