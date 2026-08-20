"""Typed internal entities.

These are the objects that cross module boundaries: what a source adapter produces, what
the identity layer consumes and emits, and what the artifact serializer reads. They are
frozen dataclasses rather than dataframes so that a field rename is a type error instead of
a silent null column, which is the coupling `AGENTS.md` section 12 warns about.

Nothing here knows how to fetch, join or score. Behaviour lives in the subpackages.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from typing import Any

from ffdraft.contracts.enums import (
    DepthChartEra,
    EntityKind,
    Position,
    ResolutionStatus,
)
from ffdraft.timeutil import ensure_utc

__all__ = [
    "CanonicalPlayer",
    "DepthChartObservation",
    "MarketCohort",
    "MarketQuote",
    "PlayerCrosswalk",
    "PlayerStatusObservation",
    "ResolutionOutcome",
]


@dataclass(frozen=True, slots=True)
class PlayerCrosswalk:
    """External identifiers for one canonical player.

    Values are already trimmed and format-validated by :mod:`ffdraft.identity.ids`; a
    malformed id never reaches this type, it becomes ``None`` plus a quality record.
    """

    gsis_id: str | None = None
    espn_id: str | None = None
    sleeper_id: str | None = None
    mfl_id: str | None = None
    pfr_id: str | None = None
    sportradar_id: str | None = None
    yahoo_id: str | None = None

    def get(self, namespace: str) -> str | None:
        return getattr(self, f"{namespace}_id", None)

    def merge(self, other: PlayerCrosswalk) -> PlayerCrosswalk:
        """Fill this crosswalk's gaps from ``other``; existing values always win.

        First writer wins because the first writer is the higher-precedence source. The
        nflverse-native roster is loaded before the dynastyprocess crosswalk mirror
        precisely so that a mirror disagreement cannot overwrite nflverse's own id.
        """
        merged = {
            name: getattr(self, name) or getattr(other, name)
            for name in (
                "gsis_id",
                "espn_id",
                "sleeper_id",
                "mfl_id",
                "pfr_id",
                "sportradar_id",
                "yahoo_id",
            )
        }
        return PlayerCrosswalk(**merged)

    def to_dict(self) -> dict[str, str | None]:
        return {
            "gsis_id": self.gsis_id,
            "espn_id": self.espn_id,
            "sleeper_id": self.sleeper_id,
            "mfl_id": self.mfl_id,
            "pfr_id": self.pfr_id,
            "sportradar_id": self.sportradar_id,
            "yahoo_id": self.yahoo_id,
        }


@dataclass(frozen=True, slots=True)
class CanonicalPlayer:
    """One player in canonical form.

    ``player_id`` is namespaced (``gsis:00-0031234``, ``espn:4362628``). It is never a name
    and never a bare external id, so a key can always be traced to the namespace that
    minted it (ADR-019).
    """

    player_id: str
    display_name: str
    position: Position
    team: str | None = None
    crosswalk: PlayerCrosswalk = field(default_factory=PlayerCrosswalk)
    birth_date: date | None = None
    years_exp: int | None = None
    rookie_season: int | None = None
    status: str | None = None
    entity_kind: EntityKind = EntityKind.PLAYER
    source_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if ":" not in self.player_id:
            raise ValueError(
                f"player_id {self.player_id!r} is not namespaced; "
                "a bare id or name can never be a canonical key (ADR-005/ADR-019)",
            )
        if not self.display_name.strip():
            raise ValueError(f"{self.player_id}: empty display_name")

    @property
    def namespace(self) -> str:
        return self.player_id.split(":", 1)[0]

    @property
    def gsis_id(self) -> str | None:
        return self.crosswalk.gsis_id

    def with_crosswalk(self, other: PlayerCrosswalk) -> CanonicalPlayer:
        return replace(self, crosswalk=self.crosswalk.merge(other))


@dataclass(frozen=True, slots=True)
class MarketCohort:
    """One slice of the market, identified by the filters that define it.

    A cohort is a *request*, not a preset. Phase 1 conflated the two, which meant an
    unfiltered aggregate had to claim a scoring preset and a league size it did not
    describe. Phase 5 separates them: a cohort states what its filters actually constrain
    (``scoring_semantics`` / ``league_size_semantics``, either of which may be ``None`` for
    "unconstrained"), and :class:`~ffdraft.market.cohorts.CohortAssignment` records which
    cohort a given preset was served from and whether that was exact (ADR-039).

    ``filters`` records exactly what was sent, so nothing has to be reconstructed later.
    """

    cohort_id: str
    filters: Mapping[str, str] = field(default_factory=dict)
    label: str = ""
    #: The scoring preset this cohort's filters actually select, or ``None`` when the
    #: request does not constrain scoring. MFL exposes ``IS_PPR`` as a boolean, so HALF is
    #: never expressible here (ADR-039).
    scoring_semantics: str | None = None
    #: The league size this cohort's filters actually select, or ``None`` when unconstrained.
    league_size_semantics: int | None = None

    def __post_init__(self) -> None:
        if not self.cohort_id.strip():
            raise ValueError("a market cohort needs a non-empty cohort_id")
        object.__setattr__(self, "filters", dict(self.filters))

    @property
    def filter_query(self) -> str:
        """The filters as a stable ``KEY=value&KEY=value`` string, or ``"no filters"``."""
        rendered = "&".join(f"{key}={value}" for key, value in sorted(self.filters.items()))
        return rendered or "no filters"

    @property
    def specificity(self) -> int:
        """How many axes this cohort constrains. Higher is more specific (ADR-039)."""
        return int(self.scoring_semantics is not None) + int(
            self.league_size_semantics is not None,
        )

    def is_exact_for(self, scoring_preset: str, league_size: int) -> bool:
        """Whether this cohort exactly describes ``(scoring_preset, league_size)``.

        Both axes must be constrained *and* match. An unconstrained axis is never exact:
        "any league size" is not "twelve teams", and saying otherwise is the truthfulness
        failure ADR-012 exists to prevent.
        """
        return (
            self.scoring_semantics is not None
            and self.league_size_semantics is not None
            and self.scoring_semantics == scoring_preset
            and self.league_size_semantics == league_size
        )

    def source_format_detail(self, *, approximate: bool) -> str:
        """Human-readable filter record for ``market_snapshot.source_format_detail``."""
        return f"{self.filter_query} ({'approximate' if approximate else 'exact'} cohort)"


@dataclass(frozen=True, slots=True)
class MarketQuote:
    """A normalized market price for one external player id.

    Not yet joined to canonical identity - that is the resolver's job. Keeping the external
    id here means an unresolved quote stays inspectable instead of vanishing.
    """

    source_id: str
    season: int
    external_player_id: str
    average_pick: float
    retrieved_at_utc: datetime
    cohort_id: str
    market_rank: int | None = None
    min_pick: float | None = None
    max_pick: float | None = None
    sample_size: int | None = None
    selection_pct: float | None = None
    source_as_of_utc: datetime | None = None
    entity_kind: EntityKind = EntityKind.PLAYER
    raw_position: str | None = None
    quality_flags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.average_pick <= 0:
            raise ValueError(
                f"{self.source_id}:{self.external_player_id}: "
                f"average_pick must be > 0, got {self.average_pick}",
            )
        object.__setattr__(self, "retrieved_at_utc", ensure_utc(self.retrieved_at_utc))
        if self.source_as_of_utc is not None:
            object.__setattr__(self, "source_as_of_utc", ensure_utc(self.source_as_of_utc))


@dataclass(frozen=True, slots=True)
class PlayerStatusObservation:
    """Current-state status for one external player id (ADR-011)."""

    source_id: str
    external_player_id: str
    observed_at_utc: datetime
    team: str | None = None
    status: str | None = None
    injury_status: str | None = None
    injury_body_part: str | None = None
    #: Sleeper publishes these for some injured players and omits them for healthy ones.
    #: Nullable by design (ADR-043); never fabricated to satisfy a required field.
    injury_notes: str | None = None
    injury_start_date: str | None = None
    practice_participation: str | None = None
    practice_description: str | None = None
    depth_chart_position: str | None = None
    depth_chart_order: int | None = None
    #: Sleeper publishes ``gsis_id`` on only ~32% of records, so it is a cross-check, never
    #: a join key (ADR-011/ADR-019). Stored trimmed, or ``None`` when malformed.
    reported_gsis_id: str | None = None
    quality_flags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "observed_at_utc", ensure_utc(self.observed_at_utc))


@dataclass(frozen=True, slots=True)
class DepthChartObservation:
    """One depth-chart reading, normalized across the 2025 schema break (ADR-015).

    ``era`` is not decoration. ``observed_at_utc`` exists only in the snapshot era, so the
    ADR-018 leakage test can assert that a pre-2025 row never claims a point-in-time depth
    reading it cannot have.
    """

    source_id: str
    season: int
    era: DepthChartEra
    team: str
    position: str | None = None
    depth_rank: int | None = None
    gsis_id: str | None = None
    espn_id: str | None = None
    player_name: str | None = None
    observed_at_utc: datetime | None = None
    week: int | None = None

    def __post_init__(self) -> None:
        if self.era.supports_point_in_time_anchor:
            if self.observed_at_utc is None:
                raise ValueError(
                    f"{self.source_id} {self.season}: snapshot-era observation without a "
                    "timestamp cannot support a point-in-time anchor",
                )
            object.__setattr__(self, "observed_at_utc", ensure_utc(self.observed_at_utc))
        elif self.observed_at_utc is not None:
            raise ValueError(
                f"{self.source_id} {self.season}: weekly-era rows carry a week, not a "
                "timestamp; inventing one would fabricate point-in-time availability "
                "(ADR-015/ADR-018)",
            )

    @property
    def available_at_anchor(self) -> bool:
        """Whether this observation may be used as draft-time depth context.

        Weekly-era rows begin at week 1, which is published after final cuts and after a
        typical late-August draft, so they are never anchor-available (ADR-018).
        """
        return self.era.supports_point_in_time_anchor


@dataclass(frozen=True, slots=True)
class ResolutionOutcome:
    """What the identity resolver decided about one external record.

    Unresolved and ambiguous outcomes are first-class results, not errors. They carry a
    machine-readable ``reason`` so a data-quality report can distinguish "this is an MFL
    team-defence row we never model" from "two bridges disagreed and we refused to guess".
    """

    source_id: str
    external_player_id: str
    status: ResolutionStatus
    player_id: str | None = None
    reason: str = ""
    entity_kind: EntityKind = EntityKind.PLAYER
    bridges_agreed: tuple[str, ...] = ()
    bridges_disagreed: tuple[str, ...] = ()
    #: Diagnostics only. A name candidate never resolves a production record (ADR-005).
    name_candidates: tuple[str, ...] = ()
    quality_flags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.status.is_resolved and not self.player_id:
            raise ValueError(
                f"{self.source_id}:{self.external_player_id}: "
                f"status {self.status} without a player_id",
            )
        if not self.status.is_resolved and self.player_id:
            raise ValueError(
                f"{self.source_id}:{self.external_player_id}: "
                f"status {self.status} must not carry a player_id - it would invite callers "
                "to use a value the resolver refused to stand behind",
            )

    @property
    def resolved(self) -> bool:
        return self.status.is_resolved

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "external_player_id": self.external_player_id,
            "status": str(self.status),
            "player_id": self.player_id,
            "reason": self.reason,
            "entity_kind": str(self.entity_kind),
            "bridges_agreed": list(self.bridges_agreed),
            "bridges_disagreed": list(self.bridges_disagreed),
            "name_candidates": list(self.name_candidates),
            "quality_flags": list(self.quality_flags),
        }
