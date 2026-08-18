"""The canonical player registry.

The registry is the only place that decides what a canonical player *is*. It is built from
the nflverse roster - the licensed, nflverse-native spine - and then enriched with the
dynastyprocess crosswalk mirror, which may fill gaps but may never introduce players or
overwrite an nflverse id.

Its central behaviour is the poisoned index. If two canonical players end up sharing an
external id, every lookup through that id fails closed as ambiguous instead of returning
whichever row happened to be inserted last. That single rule is what makes ADR-005's
"never silently choose among ambiguous players" true in practice rather than in principle.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum

import polars as pl

from ffdraft.contracts import (
    CANONICAL_PLAYER_CONTRACT,
    CanonicalPlayer,
    EntityKind,
    PlayerCrosswalk,
    Position,
    QualityCheck,
)
from ffdraft.contracts.enums import Severity
from ffdraft.identity.ids import REGISTRY_NAMESPACES, IdNamespace, make_player_id
from ffdraft.identity.names import name_key

__all__ = ["CanonicalRegistry", "LookupStatus", "LookupResult", "build_registry"]


class LookupStatus(StrEnum):
    FOUND = "found"
    ABSENT = "absent"
    #: The id maps to more than one canonical player. Never resolved, always failed closed.
    AMBIGUOUS = "ambiguous"


@dataclass(frozen=True, slots=True)
class LookupResult:
    status: LookupStatus
    player_id: str | None = None
    colliding: tuple[str, ...] = ()

    @property
    def found(self) -> bool:
        return self.status is LookupStatus.FOUND


_AMBIGUOUS = "\x00ambiguous"


@dataclass(frozen=True)
class CanonicalRegistry:
    """Canonical players plus fail-closed crosswalk indexes."""

    players: Mapping[str, CanonicalPlayer]
    indexes: Mapping[IdNamespace, Mapping[str, str]]
    collisions: Mapping[IdNamespace, Mapping[str, tuple[str, ...]]]
    name_index: Mapping[str, tuple[str, ...]]
    checks: tuple[QualityCheck, ...] = ()

    def __len__(self) -> int:
        return len(self.players)

    def get(self, player_id: str) -> CanonicalPlayer | None:
        return self.players.get(player_id)

    def lookup(self, namespace: IdNamespace | str, value: str | None) -> LookupResult:
        """Resolve one external id to a canonical player id, or fail closed."""
        if not value:
            return LookupResult(LookupStatus.ABSENT)
        space = IdNamespace(namespace)
        index = self.indexes.get(space, {})
        found = index.get(value)
        if found is None:
            return LookupResult(LookupStatus.ABSENT)
        if found == _AMBIGUOUS:
            return LookupResult(
                LookupStatus.AMBIGUOUS,
                colliding=self.collisions.get(space, {}).get(value, ()),
            )
        return LookupResult(LookupStatus.FOUND, player_id=found)

    def name_candidates(self, display_name: str | None) -> tuple[str, ...]:
        """Canonical ids sharing a normalized name. **Diagnostics only** (ADR-005)."""
        return self.name_index.get(name_key(display_name), ())

    def eligible_players(self, positions: Iterable[Position] | None = None) -> tuple[str, ...]:
        """Player ids for real players at the given positions, sorted for determinism."""
        wanted = set(positions) if positions is not None else None
        return tuple(
            sorted(
                player_id
                for player_id, player in self.players.items()
                if player.entity_kind is EntityKind.PLAYER
                and (wanted is None or player.position in wanted)
            ),
        )

    def to_frame(self) -> pl.DataFrame:
        """Serialize to the canonical player frame contract."""
        rows = []
        for player_id in sorted(self.players):
            player = self.players[player_id]
            crosswalk = player.crosswalk.to_dict()
            rows.append(
                {
                    "player_id": player.player_id,
                    "display_name": player.display_name,
                    "position": str(player.position),
                    "team": player.team,
                    "status": player.status,
                    "entity_kind": str(player.entity_kind),
                    **crosswalk,
                    "birth_date": player.birth_date,
                    "years_exp": player.years_exp,
                    "rookie_season": player.rookie_season,
                    "source_ids": ",".join(player.source_ids),
                }
            )
        return CANONICAL_PLAYER_CONTRACT.build(rows)


@dataclass
class _IndexBuilder:
    index: dict[str, str] = field(default_factory=dict)
    collisions: dict[str, list[str]] = field(default_factory=dict)

    def add(self, value: str | None, player_id: str) -> None:
        if not value:
            return
        current = self.index.get(value)
        if current is None:
            self.index[value] = player_id
            return
        if current == player_id:
            return
        # Two distinct canonical players claim the same external id. Neither wins.
        self.index[value] = _AMBIGUOUS
        bucket = self.collisions.setdefault(value, [current] if current != _AMBIGUOUS else [])
        if player_id not in bucket:
            bucket.append(player_id)


def build_registry(
    roster: pl.DataFrame,
    *,
    player_ids: pl.DataFrame | None = None,
    source_id: str = "nflreadpy",
) -> CanonicalRegistry:
    """Build the registry from a normalized roster, optionally enriched by the crosswalk.

    ``player_ids`` (the dynastyprocess mirror) may only *add* ids to players the roster
    already knows. A mirror row whose ``gsis_id`` is unknown here is ignored: an unlicensed
    mirror must not be able to expand the canonical player set (registry known-issue
    ``ff_playerids_unlicensed_mirror``).
    """
    players: dict[str, CanonicalPlayer] = {}
    checks: list[QualityCheck] = []
    duplicate_gsis = 0
    unparsed_positions: set[str] = set()

    for row in roster.iter_rows(named=True):
        gsis = row.get("gsis_id")
        if not gsis:
            continue
        player_id = make_player_id(IdNamespace.GSIS, str(gsis))
        if player_id in players:
            duplicate_gsis += 1
            continue
        raw_position = row.get("position")
        position = Position.parse(raw_position)
        if position is None:
            # A roster row we cannot position (OL, DB, LS, ...) is not modelled in V1, but
            # it still belongs in the registry so its ids cannot be reassigned elsewhere.
            if raw_position:
                unparsed_positions.add(str(raw_position))
            continue
        players[player_id] = CanonicalPlayer(
            player_id=player_id,
            display_name=str(row.get("display_name") or gsis),
            position=position,
            team=row.get("team"),
            crosswalk=PlayerCrosswalk(
                gsis_id=str(gsis),
                espn_id=row.get("espn_id"),
                sleeper_id=row.get("sleeper_id"),
                pfr_id=row.get("pfr_id"),
                sportradar_id=row.get("sportradar_id"),
                yahoo_id=row.get("yahoo_id"),
            ),
            birth_date=row.get("birth_date"),
            years_exp=row.get("years_exp"),
            rookie_season=row.get("rookie_season"),
            status=row.get("status"),
            entity_kind=EntityKind.PLAYER,
            source_ids=(source_id,),
        )

    if duplicate_gsis:
        checks.append(
            QualityCheck.fail(
                "identity.duplicate_roster_gsis",
                stage="identity.registry",
                message="roster supplied the same gsis_id more than once",
                observed=f"{duplicate_gsis} duplicate row(s)",
                expected="0",
            ),
        )
    if unparsed_positions:
        checks.append(
            QualityCheck.ok(
                "identity.non_modelled_positions_skipped",
                stage="identity.registry",
                message="roster rows outside the fantasy position vocabulary were skipped",
                observed=", ".join(sorted(unparsed_positions)),
            ),
        )

    if player_ids is not None:
        players, enrichment_checks = _enrich_from_crosswalk(players, player_ids)
        checks.extend(enrichment_checks)

    indexes, collisions, collision_checks = _build_indexes(players)
    checks.extend(collision_checks)

    name_index: dict[str, list[str]] = defaultdict(list)
    for player_id, player in players.items():
        key = name_key(player.display_name)
        if key:
            name_index[key].append(player_id)

    return CanonicalRegistry(
        players=players,
        indexes=indexes,
        collisions=collisions,
        name_index={key: tuple(sorted(ids)) for key, ids in name_index.items()},
        checks=tuple(checks),
    )


def _enrich_from_crosswalk(
    players: dict[str, CanonicalPlayer],
    player_ids: pl.DataFrame,
) -> tuple[dict[str, CanonicalPlayer], list[QualityCheck]]:
    by_gsis = {
        player.crosswalk.gsis_id: player_id
        for player_id, player in players.items()
        if player.crosswalk.gsis_id
    }
    checks: list[QualityCheck] = []
    conflicts = 0
    enriched = 0
    ignored = 0
    rejected = 0

    for row in player_ids.iter_rows(named=True):
        gsis = row.get("gsis_id")
        player_id = by_gsis.get(gsis) if gsis else None
        if player_id is None:
            ignored += 1
            continue
        player = players[player_id]
        incoming = PlayerCrosswalk(
            mfl_id=row.get("mfl_id"),
            espn_id=row.get("espn_id"),
            sleeper_id=row.get("sleeper_id"),
            pfr_id=row.get("pfr_id"),
            sportradar_id=row.get("sportradar_id"),
            yahoo_id=row.get("yahoo_id"),
        )
        disagreements = [
            namespace
            for namespace in (IdNamespace.ESPN, IdNamespace.SLEEPER)
            if (mine := player.crosswalk.get(namespace))
            and (theirs := incoming.get(namespace))
            and mine != theirs
        ]
        if disagreements:
            # A mirror row that contradicts nflverse on a shared id is untrustworthy as a
            # whole, not just in the conflicting field: merging its *other* ids would let a
            # mis-keyed row donate someone else's mfl_id. Reject the row and record it.
            conflicts += len(disagreements)
            rejected += 1
            continue
        players[player_id] = player.with_crosswalk(incoming)
        enriched += 1

    checks.append(
        QualityCheck.ok(
            "identity.crosswalk_enrichment",
            stage="identity.registry",
            message="secondary crosswalk merged into known players only",
            observed=(
                f"{enriched} enriched, {ignored} mirror row(s) ignored as unknown, "
                f"{rejected} rejected for contradicting an nflverse id"
            ),
        ),
    )
    if conflicts:
        checks.append(
            QualityCheck.fail(
                "identity.crosswalk_id_conflict",
                stage="identity.registry",
                message=(
                    "the secondary crosswalk disagrees with an nflverse-native id; the "
                    "whole mirror row is rejected and the disagreement recorded"
                ),
                observed=f"{conflicts} conflicting field(s) across {rejected} row(s)",
                expected="0",
                severity=Severity.WARNING,
            ),
        )
    return players, checks


def _build_indexes(
    players: Mapping[str, CanonicalPlayer],
) -> tuple[
    dict[IdNamespace, dict[str, str]],
    dict[IdNamespace, dict[str, tuple[str, ...]]],
    list[QualityCheck],
]:
    builders = {namespace: _IndexBuilder() for namespace in REGISTRY_NAMESPACES}
    for player_id, player in players.items():
        for namespace in REGISTRY_NAMESPACES:
            builders[namespace].add(player.crosswalk.get(namespace), player_id)

    indexes: dict[IdNamespace, dict[str, str]] = {}
    collisions: dict[IdNamespace, dict[str, tuple[str, ...]]] = {}
    checks: list[QualityCheck] = []
    for namespace, builder in builders.items():
        indexes[namespace] = builder.index
        collisions[namespace] = {
            value: tuple(sorted(ids)) for value, ids in builder.collisions.items()
        }
        if builder.collisions:
            checks.append(
                QualityCheck.fail(
                    "identity.crosswalk_collision",
                    stage="identity.registry",
                    message=(
                        f"{namespace}_id maps to multiple canonical players; every lookup "
                        "through those ids now fails closed"
                    ),
                    observed=", ".join(sorted(builder.collisions)),
                    expected="each external id maps to at most one player",
                ),
            )
    return indexes, collisions, checks
