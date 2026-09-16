"""Where each published player's public portrait lives (ADR-087).

One row per canonical ``player_id``, carrying an ESPN athlete id and the address it resolves
to. The player card renders it; nothing else in the product reads it.

Three properties are the whole module.

**It mints no identity.** ``espn_id`` is already this project's *primary market identity
bridge* (ADR-019): ``ffdraft.identity.registry`` reads it off the nflverse roster, cross-checks
it against the ``ff_playerids`` mirror and rejects a row that disagrees, and
``ffdraft.identity.resolver`` joins MyFantasyLeague through it. So the crosswalk this artifact
publishes is one the build already computed and already fails closed on. There is no scrape, no
ESPN request in the pipeline, and no name match anywhere near it - which matters because
`AGENTS.md` section 6 forbids a production join that depends on a normalized name, and a
portrait attached to the wrong player is exactly the failure that rule exists to prevent.

**It cannot move a number.** No field here enters a feature matrix, a projection, a VORP, a
fair rank, a tier or an arbitrage score. It is decoration, in the same sense that
``player_status`` is annotation (ADR-043), and for the stronger reason: it carries no
measurement of the player at all.

**It is keyed once and scoped to the board.** A player appears in up to nine tier rows and
nine arbitrage rows; his portrait address is one string, so it is published once. The
population is the players the board actually names, for the same reason ``player_status``
uses it - a row nobody can open is payload the browser downloads for nothing.

A player with no ``espn_id`` simply has no row. That is the normal state for a practice-squad
arrival the roster feed has not bridged yet, and the card draws its monogram instead; an
absence here is never an error and never a gap in the board.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from ffdraft.artifacts import record_schema_version
from ffdraft.contracts import QualityCheck
from ffdraft.identity.ids import IdNamespace, value_of
from ffdraft.identity.registry import CanonicalRegistry
from ffdraft.quality import QualityGate

__all__ = [
    "HEADSHOT_HOST",
    "HEADSHOT_PROVIDER",
    "HEADSHOT_SOURCE_IDS",
    "HeadshotResult",
    "build_player_headshot_records",
    "crosswalk_from_registry",
    "headshot_url",
]

_HEADSHOT_SCHEMA = "player_headshot_record"

#: The one origin the browser is permitted to reach for a portrait. Declared here, asserted by
#: the record schema's own pattern, re-asserted by the artifact validator, and pinned by the
#: end-to-end request guard. Four places, one string, on purpose: this is the only third-party
#: host the site touches at all (`docs/ARCHITECTURE.md` section 3.2).
HEADSHOT_HOST = "a.espncdn.com"

#: The provider the schema's enum allows. Adding a second is a rights decision, not a config
#: change - see `docs/SECURITY_LICENSE.md` section 8.
HEADSHOT_PROVIDER = "espn"

#: The crosswalk this artifact is built from. nflverse publishes ``espn_id``; ESPN itself is
#: never called by the pipeline, which is why it is not a source in the registry sense.
HEADSHOT_SOURCE_IDS = ("nflreadpy",)

_URL_TEMPLATE = f"https://{HEADSHOT_HOST}/i/headshots/nfl/players/full/{{provider_id}}.png"


def headshot_url(provider_player_id: str) -> str:
    """The address a portrait for this provider id resolves to.

    One function so the pattern exists once. The schema pins the same shape independently, so
    a change here that drifted from the contract fails validation rather than shipping.
    """
    return _URL_TEMPLATE.format(provider_id=provider_player_id)


@dataclass
class HeadshotResult:
    """The records plus the coverage evidence the build metadata block wants."""

    build_id: str
    records: list[dict[str, Any]]
    published_players: int
    resolved: int
    unresolved: tuple[str, ...]

    @property
    def coverage(self) -> float:
        if self.published_players == 0:
            return 0.0
        return self.resolved / self.published_players

    def summary(self) -> dict[str, Any]:
        return {
            "provider": HEADSHOT_PROVIDER,
            "host": HEADSHOT_HOST,
            "source_ids": list(HEADSHOT_SOURCE_IDS),
            "published_players": self.published_players,
            "resolved": self.resolved,
            "coverage": round(self.coverage, 4),
        }


def build_player_headshot_records(
    *,
    crosswalk: Mapping[str, str | None],
    published: Iterable[str],
    build_id: str,
    gate: QualityGate | None = None,
) -> HeadshotResult:
    """Build the artifact rows for the players the board names.

    ``crosswalk`` maps canonical ``player_id`` to the provider's athlete id, exactly as the
    identity registry holds it. ``published`` is the distinct player set the board published;
    order is irrelevant because the serializer sorts, but duplicates are collapsed here so the
    coverage denominator counts players rather than rows.
    """
    wanted = _distinct(published)
    records: list[dict[str, Any]] = []
    unresolved: list[str] = []
    version = record_schema_version(_HEADSHOT_SCHEMA)

    for player_id in wanted:
        provider_id = value_of(IdNamespace.ESPN, crosswalk.get(player_id))
        if provider_id is None:
            # Not an error. The roster feed bridges most players and not all of them, and a
            # card without a portrait is a card, so this fails soft by construction.
            unresolved.append(player_id)
            continue
        records.append(
            {
                "schema_version": version,
                "build_id": build_id,
                "player_id": player_id,
                "provider": HEADSHOT_PROVIDER,
                "provider_player_id": provider_id,
                "image_url": headshot_url(provider_id),
            },
        )

    result = HeadshotResult(
        build_id=build_id,
        records=records,
        published_players=len(wanted),
        resolved=len(records),
        unresolved=tuple(unresolved),
    )
    if gate is not None:
        gate.extend(_coverage_checks(result))
    return result


def crosswalk_from_registry(registry: CanonicalRegistry) -> dict[str, str | None]:
    """``player_id -> espn_id`` straight off the canonical registry.

    The registry is the right place to read this and a roster frame is not: the registry has
    already merged the roster with the ``ff_playerids`` mirror, already **rejected** any mirror
    row that disagreed with nflverse about a shared id, and already failed closed on a colliding
    id (ADR-019). Reading the raw column instead would take the same numbers without any of
    those guarantees.
    """
    return {player_id: player.crosswalk.espn_id for player_id, player in registry.players.items()}


def _distinct(values: Iterable[str]) -> tuple[str, ...]:
    seen: dict[str, None] = {}
    for value in values:
        if value:
            seen.setdefault(str(value), None)
    return tuple(seen)


def _coverage_checks(result: HeadshotResult) -> Sequence[QualityCheck]:
    """Report coverage; never fail on it.

    There is deliberately no minimum. A portrait is decoration, so a thin crosswalk degrades
    the card and nothing else - and a gate that could stop a deploy over a missing picture
    would be able to take the whole board down for a cosmetic reason.
    """
    return (
        QualityCheck.ok(
            "headshots.coverage",
            stage="artifacts.headshots",
            message="published players with a portrait crosswalk entry",
            observed=(
                f"{result.resolved}/{result.published_players} "
                f"({result.coverage:.1%}) via {HEADSHOT_PROVIDER}"
            ),
        ),
    )
