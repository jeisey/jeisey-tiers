"""Fail-closed identity resolution.

Two joins matter in Phase 1, and Phase 0 measured both, so neither is guesswork:

**Market -> canonical.** Two independent bridges. The primary is nflverse-native: MFL's
``espn_id`` against ``load_rosters().espn_id``. The secondary runs ``mfl_id`` through
``load_ff_playerids()``, which lives in an unlicensed mirror and therefore cross-checks
rather than decides. Phase 0 saw 331 rows resolve on both bridges with **zero**
disagreements, so treating a disagreement as fatal costs essentially nothing and catches
exactly the silent-corruption class ADR-005 exists to prevent.

**nflverse -> Sleeper.** Always in that direction, on ``sleeper_id``. Sleeper publishes
``gsis_id`` on only 31.9% of records, so using it as a key would drop two thirds of the
map; it is used solely as a cross-check, and a mismatch fails the record closed.

Every refusal is a first-class result with a machine-readable ``reason``, never an
exception and never a silently dropped row.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

import polars as pl

from ffdraft.contracts import (
    RESOLUTION_CONTRACT,
    EntityKind,
    Position,
    QualityCheck,
    ResolutionOutcome,
    ResolutionStatus,
)
from ffdraft.contracts.enums import Severity
from ffdraft.identity.aliases import AliasEntry, AliasMap
from ffdraft.identity.ids import IdNamespace, normalize_id
from ffdraft.identity.registry import CanonicalRegistry, LookupStatus

__all__ = [
    "PRIMARY_MARKET_BRIDGE",
    "SECONDARY_MARKET_BRIDGE",
    "ResolutionSummary",
    "coverage_checks",
    "outcomes_to_frame",
    "resolve_market_quotes",
    "resolve_sleeper_status",
    "summarize",
]

#: Bridge names as recorded in ``config/source-registry.yaml``'s
#: ``decisions.market_identity_bridges``.
PRIMARY_MARKET_BRIDGE = "espn_id_via_nflverse_rosters"
SECONDARY_MARKET_BRIDGE = "mfl_id_via_ff_playerids"

# Machine-readable refusal reasons. Downstream reporting keys off these exact strings.
REASON_RESOLVED_BOTH = "both_bridges_agree"
REASON_RESOLVED_PRIMARY = "primary_bridge_only"
REASON_RESOLVED_SECONDARY = "secondary_bridge_only"
REASON_BRIDGE_DISAGREEMENT = "bridge_disagreement"
REASON_COLLIDING_INDEX = "colliding_crosswalk_index"
REASON_NON_PLAYER_ENTITY = "non_player_entity"
REASON_NO_BRIDGE = "no_bridge_resolved"
REASON_MALFORMED_EXTERNAL_ID = "malformed_external_id"
REASON_ALIAS_REVIEWED = "reviewed_alias"
REASON_ALIAS_TARGET_UNKNOWN = "alias_target_unknown"
REASON_ALIAS_CONFLICT = "alias_conflicts_with_bridge"
REASON_SLEEPER_MATCHED = "sleeper_id_from_nflverse_roster"
REASON_SLEEPER_MISSING = "sleeper_record_missing"
REASON_SLEEPER_GSIS_MISMATCH = "sleeper_gsis_cross_check_failed"

FLAG_SECONDARY_ONLY = "secondary_bridge_only"
FLAG_NAME_CANDIDATES_ONLY = "name_candidates_not_used"


# --------------------------------------------------------------------------------------
# Market -> canonical
# --------------------------------------------------------------------------------------


def resolve_market_quotes(
    quotes: pl.DataFrame,
    *,
    registry: CanonicalRegistry,
    espn_by_mfl_id: Mapping[str, str],
    gsis_by_mfl_id: Mapping[str, str],
    names_by_mfl_id: Mapping[str, str] | None = None,
    aliases: AliasMap | None = None,
    source_id: str = "myfantasyleague_adp",
) -> list[ResolutionOutcome]:
    """Resolve normalized market quotes to canonical players.

    ``espn_by_mfl_id`` comes from the MFL player directory (the primary bridge's input) and
    ``gsis_by_mfl_id`` from ``load_ff_playerids`` (the secondary bridge). Passing them in
    rather than fetching keeps this function pure and fixture-testable.
    """
    alias_map = aliases or AliasMap.empty()
    names = names_by_mfl_id or {}
    outcomes: list[ResolutionOutcome] = []

    for row in quotes.iter_rows(named=True):
        raw_external = row.get("external_player_id")
        declared_kind = _entity_kind(row.get("entity_kind"))
        external = normalize_id(IdNamespace.MFL, raw_external)

        if external.value is None:
            outcomes.append(
                ResolutionOutcome(
                    source_id=source_id,
                    external_player_id=str(raw_external or ""),
                    status=ResolutionStatus.UNRESOLVED,
                    reason=REASON_MALFORMED_EXTERNAL_ID,
                    entity_kind=declared_kind,
                    quality_flags=external.quality_flags,
                ),
            )
            continue

        external_id = external.value
        if declared_kind is EntityKind.TEAM_UNIT:
            # A documented non-player entity contract, not an identity failure. Team units
            # must never enter QB/RB/WR/TE identity (AGENTS.md section 6).
            outcomes.append(
                ResolutionOutcome(
                    source_id=source_id,
                    external_player_id=external_id,
                    status=ResolutionStatus.UNRESOLVED,
                    reason=REASON_NON_PLAYER_ENTITY,
                    entity_kind=EntityKind.TEAM_UNIT,
                ),
            )
            continue

        outcomes.append(
            _resolve_one_quote(
                external_id=external_id,
                declared_kind=declared_kind,
                registry=registry,
                espn_by_mfl_id=espn_by_mfl_id,
                gsis_by_mfl_id=gsis_by_mfl_id,
                display_name=names.get(external_id),
                alias=alias_map.get(source_id, external_id),
                source_id=source_id,
                extra_flags=external.quality_flags,
            ),
        )
    return outcomes


def _resolve_one_quote(
    *,
    external_id: str,
    declared_kind: EntityKind,
    registry: CanonicalRegistry,
    espn_by_mfl_id: Mapping[str, str],
    gsis_by_mfl_id: Mapping[str, str],
    display_name: str | None,
    alias: AliasEntry | None,
    source_id: str,
    extra_flags: Sequence[str],
) -> ResolutionOutcome:
    primary = registry.lookup(IdNamespace.ESPN, espn_by_mfl_id.get(external_id))
    secondary = registry.lookup(IdNamespace.GSIS, gsis_by_mfl_id.get(external_id))

    def outcome(
        status: ResolutionStatus,
        *,
        player_id: str | None = None,
        reason: str,
        agreed: tuple[str, ...] = (),
        disagreed: tuple[str, ...] = (),
        flags: tuple[str, ...] = (),
        candidates: tuple[str, ...] = (),
    ) -> ResolutionOutcome:
        return ResolutionOutcome(
            source_id=source_id,
            external_player_id=external_id,
            status=status,
            player_id=player_id,
            reason=reason,
            entity_kind=declared_kind,
            bridges_agreed=agreed,
            bridges_disagreed=disagreed,
            name_candidates=candidates,
            quality_flags=tuple(dict.fromkeys((*extra_flags, *flags))),
        )

    # A poisoned index means two canonical players claim one external id. Refuse.
    colliding = [
        name
        for name, result in (
            (PRIMARY_MARKET_BRIDGE, primary),
            (SECONDARY_MARKET_BRIDGE, secondary),
        )
        if result.status is LookupStatus.AMBIGUOUS
    ]
    if colliding:
        return outcome(
            ResolutionStatus.AMBIGUOUS,
            reason=REASON_COLLIDING_INDEX,
            disagreed=tuple(colliding),
        )

    resolved_by: tuple[str, ...]
    if primary.found and secondary.found:
        if primary.player_id != secondary.player_id:
            return outcome(
                ResolutionStatus.AMBIGUOUS,
                reason=REASON_BRIDGE_DISAGREEMENT,
                disagreed=(PRIMARY_MARKET_BRIDGE, SECONDARY_MARKET_BRIDGE),
            )
        player_id = primary.player_id
        reason = REASON_RESOLVED_BOTH
        resolved_by = (PRIMARY_MARKET_BRIDGE, SECONDARY_MARKET_BRIDGE)
        flags: tuple[str, ...] = ()
    elif primary.found:
        player_id, reason, resolved_by, flags = (
            primary.player_id,
            REASON_RESOLVED_PRIMARY,
            (PRIMARY_MARKET_BRIDGE,),
            (),
        )
    elif secondary.found:
        # Usable, but the only evidence comes from the unlicensed mirror, so it is flagged.
        player_id, reason, resolved_by, flags = (
            secondary.player_id,
            REASON_RESOLVED_SECONDARY,
            (SECONDARY_MARKET_BRIDGE,),
            (FLAG_SECONDARY_ONLY,),
        )
    else:
        player_id, reason, resolved_by, flags = None, REASON_NO_BRIDGE, (), ()

    alias_player = alias.player_id if alias is not None else None

    if player_id is not None:
        if alias_player and alias_player != player_id:
            # A reviewed alias that contradicts live id evidence is a conflict to surface,
            # not a preference to apply.
            return outcome(
                ResolutionStatus.AMBIGUOUS,
                reason=REASON_ALIAS_CONFLICT,
                disagreed=(*resolved_by, "reviewed_alias"),
            )
        return outcome(
            ResolutionStatus.RESOLVED_CROSSWALK,
            player_id=player_id,
            reason=reason,
            agreed=resolved_by,
            flags=flags,
        )

    if alias_player:
        if registry.get(alias_player) is None:
            return outcome(
                ResolutionStatus.UNRESOLVED,
                reason=REASON_ALIAS_TARGET_UNKNOWN,
                flags=(REASON_ALIAS_TARGET_UNKNOWN,),
            )
        return outcome(
            ResolutionStatus.RESOLVED_REVIEWED_ALIAS,
            player_id=alias_player,
            reason=REASON_ALIAS_REVIEWED,
            agreed=("reviewed_alias",),
        )

    # No bridge, no alias. Name candidates are attached as diagnostics so a human can see
    # what a match *would* have been - they are never acted on (ADR-005).
    candidates = registry.name_candidates(display_name)
    return outcome(
        ResolutionStatus.UNRESOLVED,
        reason=REASON_NO_BRIDGE,
        candidates=candidates,
        flags=(FLAG_NAME_CANDIDATES_ONLY,) if candidates else (),
    )


# --------------------------------------------------------------------------------------
# nflverse -> Sleeper
# --------------------------------------------------------------------------------------


def resolve_sleeper_status(
    status: pl.DataFrame,
    *,
    registry: CanonicalRegistry,
    source_id: str = "sleeper",
    positions: Iterable[Position] | None = None,
) -> list[ResolutionOutcome]:
    """Match Sleeper status rows to canonical players, nflverse-first.

    Iteration runs over canonical players that carry a ``sleeper_id``, never over the
    Sleeper map, so the join direction is structural rather than a convention someone has
    to remember (ADR-011).
    """
    by_external: dict[str, dict[str, object]] = {}
    duplicates: set[str] = set()
    for row in status.iter_rows(named=True):
        key = str(row.get("external_player_id"))
        if key in by_external:
            duplicates.add(key)
        by_external[key] = row

    wanted = set(positions) if positions is not None else None
    outcomes: list[ResolutionOutcome] = []

    for player_id in sorted(registry.players):
        player = registry.players[player_id]
        if wanted is not None and player.position not in wanted:
            continue
        sleeper_id = player.crosswalk.sleeper_id
        if not sleeper_id:
            continue

        record = by_external.get(sleeper_id)
        if record is None:
            outcomes.append(
                ResolutionOutcome(
                    source_id=source_id,
                    external_player_id=sleeper_id,
                    status=ResolutionStatus.UNRESOLVED,
                    reason=REASON_SLEEPER_MISSING,
                ),
            )
            continue

        if sleeper_id in duplicates:
            outcomes.append(
                ResolutionOutcome(
                    source_id=source_id,
                    external_player_id=sleeper_id,
                    status=ResolutionStatus.AMBIGUOUS,
                    reason=REASON_COLLIDING_INDEX,
                    bridges_disagreed=("sleeper_player_id",),
                ),
            )
            continue

        reported = record.get("reported_gsis_id")
        if reported and player.gsis_id and str(reported) != player.gsis_id:
            # Sleeper's gsis_id is a cross-check, and a failed cross-check is fatal for the
            # record rather than something to average over.
            outcomes.append(
                ResolutionOutcome(
                    source_id=source_id,
                    external_player_id=sleeper_id,
                    status=ResolutionStatus.AMBIGUOUS,
                    reason=REASON_SLEEPER_GSIS_MISMATCH,
                    bridges_disagreed=(
                        "sleeper_id_from_nflverse_roster",
                        "sleeper_reported_gsis_id",
                    ),
                ),
            )
            continue

        outcomes.append(
            ResolutionOutcome(
                source_id=source_id,
                external_player_id=sleeper_id,
                status=ResolutionStatus.RESOLVED_EXACT_ID,
                player_id=player_id,
                reason=REASON_SLEEPER_MATCHED,
                bridges_agreed=("sleeper_id_from_nflverse_roster",),
            ),
        )
    return outcomes


# --------------------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ResolutionSummary:
    """Counts a data-quality report and ``build_metadata.json`` can consume directly."""

    source_id: str
    total: int
    resolved: int
    ambiguous: int
    unresolved: int
    non_player_entities: int

    @property
    def resolvable_total(self) -> int:
        """Records that *should* resolve - team units are excluded, not counted as misses."""
        return self.total - self.non_player_entities

    @property
    def coverage(self) -> float:
        return self.resolved / self.resolvable_total if self.resolvable_total else 1.0


def summarize(outcomes: Sequence[ResolutionOutcome], *, source_id: str) -> ResolutionSummary:
    non_player = sum(1 for o in outcomes if o.entity_kind is EntityKind.TEAM_UNIT)
    return ResolutionSummary(
        source_id=source_id,
        total=len(outcomes),
        resolved=sum(1 for o in outcomes if o.resolved),
        ambiguous=sum(1 for o in outcomes if o.status is ResolutionStatus.AMBIGUOUS),
        unresolved=sum(
            1
            for o in outcomes
            if o.status is ResolutionStatus.UNRESOLVED and o.entity_kind is not EntityKind.TEAM_UNIT
        ),
        non_player_entities=non_player,
    )


def outcomes_to_frame(outcomes: Sequence[ResolutionOutcome]) -> pl.DataFrame:
    """Serialize outcomes to the resolution frame contract."""
    return RESOLUTION_CONTRACT.build(
        [
            {
                "source_id": outcome.source_id,
                "external_player_id": outcome.external_player_id,
                "status": str(outcome.status),
                "player_id": outcome.player_id,
                "reason": outcome.reason,
                "entity_kind": str(outcome.entity_kind),
                "bridges_agreed": ",".join(outcome.bridges_agreed),
                "bridges_disagreed": ",".join(outcome.bridges_disagreed),
                "name_candidates": ",".join(outcome.name_candidates),
                "quality_flags": ",".join(outcome.quality_flags),
            }
            for outcome in outcomes
        ],
    )


def coverage_checks(
    summary: ResolutionSummary,
    *,
    minimum_coverage: float,
    stage: str,
    ambiguous_severity: Severity = Severity.CRITICAL,
) -> list[QualityCheck]:
    """Threshold checks from `docs/DATA_CONTRACTS.md` section 12.

    ``ambiguous_severity`` exists because the contract's rule is "zero ambiguous identities
    **in public output**". Producing an ambiguous outcome is the resolver working correctly
    on conflicting evidence, so at the resolution stage a caller may record it as a warning;
    it becomes critical at the point of publication, where a separate check enforces that
    no ambiguous record was serialized.
    """
    checks: list[QualityCheck] = []
    if summary.ambiguous:
        checks.append(
            QualityCheck.fail(
                "identity.ambiguous_records",
                stage=stage,
                message="ambiguous identities must never reach model or public layers",
                observed=f"{summary.ambiguous} ambiguous record(s)",
                expected="0",
                severity=ambiguous_severity,
            ),
        )
    if summary.coverage < minimum_coverage:
        checks.append(
            QualityCheck.fail(
                "identity.coverage_below_threshold",
                stage=stage,
                message=f"{summary.source_id} identity coverage is below the launch threshold",
                observed=f"{summary.coverage:.1%} of {summary.resolvable_total}",
                expected=f">= {minimum_coverage:.0%}",
            ),
        )
    else:
        checks.append(
            QualityCheck.ok(
                "identity.coverage",
                stage=stage,
                message=f"{summary.source_id} identity coverage meets the threshold",
                observed=f"{summary.coverage:.1%} of {summary.resolvable_total}",
            ),
        )
    if summary.non_player_entities:
        checks.append(
            QualityCheck.ok(
                "identity.non_player_entities_excluded",
                stage=stage,
                message="team units were classified as non-player entities, not identity misses",
                observed=f"{summary.non_player_entities} row(s)",
            ),
        )
    if summary.unresolved:
        checks.append(
            QualityCheck.fail(
                "identity.unresolved_records",
                stage=stage,
                message="records that could not be resolved are excluded from production",
                observed=f"{summary.unresolved} record(s)",
                expected="0 for public output",
                severity=Severity.WARNING,
            ),
        )
    return checks


def _entity_kind(value: object) -> EntityKind:
    try:
        return EntityKind(str(value))
    except ValueError:
        return EntityKind.UNKNOWN
