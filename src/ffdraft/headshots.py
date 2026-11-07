"""Where each published player's public portrait lives (ADR-087), and for whom.

One row per canonical ``player_id``, carrying an ESPN athlete id and the address it resolves
to. The player card renders it (and Pick of the Week's highlight cards); nothing else in the
product reads it.

Four properties are the whole module.

**It mints no identity.** ``espn_id`` is already this project's *primary market identity
bridge* (ADR-019): the nflverse roster carries it, and the annotation-side registry
(``ffdraft.status.employment.build_identity_registry``: this season's roster plus last season's
as identity only, ADR-102) holds it on every canonical player. A gap there may be filled from
nflverse's own player master, keyed by the same GSIS id, and only when no other player claims
the id (:func:`crosswalk_from_registry`). There is no scrape, no ESPN request in the pipeline,
and no name match anywhere near it - which matters because `AGENTS.md` section 6 forbids a
production join that depends on a normalized name, and a portrait attached to the wrong player
is exactly the failure that rule exists to prevent. A provider id two players share is refused
for both: one picture under two names is the identity mistake this artifact must not make.

**It cannot move a number.** No field here enters a feature matrix, a projection, a VORP, a
fair rank, a tier or an arbitrage score. It is decoration, in the same sense that
``player_status`` is annotation (ADR-043), and for the stronger reason: it carries no
measurement of the player at all.

**It is keyed once and scoped to the cards a reader can open** (``portrait_population_v1``).
A player appears in up to nine tier rows and nine arbitrage rows; his portrait address is one
string, so it is published once. The population is every player a card surface names - the
draft boards, and in season the rest-of-season board, the Opportunity Board, the week's
projections, the season actuals and the Insights stories (:data:`PORTRAIT_SURFACES`) - and no
one else: a row nobody can open is payload the browser downloads for nothing, and a row for a
player outside every surface is an identity mistake, which the validator fails.

The population used to be the tier board alone. Every in-season view names players the draft
board never did - on 2026-11-06, 115 of the 729 players a card could be opened for, Kirk
Cousins among them - and each of those cards drew a monogram although the crosswalk knew the
player. Which build writes the artifact follows from that: the draft build when it is the last
to publish a card surface, the rest-of-season build when it runs (it reads the draft surfaces
it publishes beside), each describing the set it wrote in its own metadata.

A player with no usable id simply has no row, and the reason is counted rather than guessed
(:class:`PortraitGap`). The card draws its monogram instead; an absence here is never an error
and never a gap in a board, and coverage is reported, never gated.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

import polars as pl

from ffdraft.contracts import QualityCheck
from ffdraft.identity.ids import IdNamespace, make_player_id, normalize_id
from ffdraft.identity.registry import CanonicalRegistry
from ffdraft.quality import QualityGate

__all__ = [
    "HEADSHOT_HOST",
    "HEADSHOT_PROVIDER",
    "HEADSHOT_SOURCE_IDS",
    "PORTRAIT_POPULATION_RULE",
    "PORTRAIT_SURFACES",
    "PORTRAIT_SURFACE_ARTIFACTS",
    "HeadshotResult",
    "PortraitBridge",
    "PortraitCrosswalk",
    "PortraitGap",
    "PortraitPopulation",
    "PortraitSurface",
    "build_player_headshot_records",
    "crosswalk_from_registry",
    "headshot_url",
    "portrait_population",
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

#: The crosswalk this artifact is built from. nflverse publishes ``espn_id`` on its rosters and
#: its player master; ESPN itself is never called by the pipeline, which is why it is not a
#: source in the registry sense.
HEADSHOT_SOURCE_IDS = ("nflreadpy",)

#: The population rule. Published in both metadata blocks so a reader can tell which
#: denominator a coverage figure has: a block without it (before 2026-11-06) counted the tier
#: board's players only.
PORTRAIT_POPULATION_RULE = "portrait_population_v1"

_URL_TEMPLATE = f"https://{HEADSHOT_HOST}/i/headshots/nfl/players/full/{{provider_id}}.png"


def headshot_url(provider_player_id: str) -> str:
    """The address a portrait for this provider id resolves to.

    One function so the pattern exists once. The schema pins the same shape independently, so
    a change here that drifted from the contract fails validation rather than shipping.
    """
    return _URL_TEMPLATE.format(provider_id=provider_player_id)


# ------------------------------------------------------------------------------ population


@dataclass(frozen=True)
class PortraitSurface:
    """A published artifact whose rows open a player card, and the views that open them."""

    artifact: str
    views: tuple[str, ...]


#: Every published artifact a reader can open a player card from, read off the frontend
#: (`web/src/app/*View.tsx`, `boardSearch.ts`, `leagueUniverse.ts`, `StoryCard.tsx`). Order is
#: presentation order in the metadata block and nothing else.
#:
#: Deliberately absent: ``player_usage`` (a card section describing the Opportunity Board's
#: players, never a list of its own - 595 of 595 inside the board on 2026-11-06),
#: ``projections`` and ``player_status`` (card-only annotation, wider than any board),
#: ``recent_form`` (a column of the Opportunity Board), and an Insights chart's other names
#: (only a story's own player opens a card).
PORTRAIT_SURFACES: tuple[PortraitSurface, ...] = (
    PortraitSurface("tiers", ("Tiers", "Arbitrage (board search)")),
    PortraitSurface("arbitrage", ("Arbitrage",)),
    PortraitSurface("ros_tiers", ("Rest of season", "Trade", "My Leagues")),
    PortraitSurface(
        "inseason_opportunity",
        ("Opportunity (with Not projected)", "Pick of the Week", "My Leagues: Rising Stars, YOLO"),
    ),
    PortraitSurface("weekly_projections", ("Start/Sit", "My Leagues: lineup, Win My Matchup")),
    PortraitSurface("season_actuals", ("My Leagues: roster and slot search",)),
    PortraitSurface("insights", ("Insights",)),
)

#: The artifact names alone - what the validator recomputes the population from.
PORTRAIT_SURFACE_ARTIFACTS: tuple[str, ...] = tuple(
    surface.artifact for surface in PORTRAIT_SURFACES
)


@dataclass(frozen=True)
class PortraitPopulation:
    """The players a card can be opened for, with the surfaces that name each of them.

    ``surfaces`` holds only the surfaces the build *read*: an artifact the build did not have
    is absent, not empty, so the metadata can say which denominator a coverage figure has.
    """

    surfaces: Mapping[str, frozenset[str]]
    positions: Mapping[str, str] = field(default_factory=dict)
    rule_version: str = PORTRAIT_POPULATION_RULE

    @property
    def players(self) -> tuple[str, ...]:
        union: set[str] = set()
        for players in self.surfaces.values():
            union |= players
        return tuple(sorted(union))

    @property
    def surfaces_read(self) -> tuple[str, ...]:
        return tuple(self.surfaces)

    def membership(self, player_id: str) -> tuple[str, ...]:
        """The surfaces naming this player, in :data:`PORTRAIT_SURFACES` order."""
        return tuple(name for name, players in self.surfaces.items() if player_id in players)


def portrait_population(
    records: Mapping[str, Iterable[Mapping[str, Any]] | None],
) -> PortraitPopulation:
    """The portrait population over whichever published records a build holds.

    ``records`` maps an artifact name to its records, exactly as a pipeline holds them; keys
    that are not card surfaces are ignored, and a surface mapped to ``None`` (or missing) was
    not read. Players are counted once however many rows name them.
    """
    surfaces: dict[str, frozenset[str]] = {}
    positions: dict[str, str] = {}
    for surface in PORTRAIT_SURFACES:
        rows = records.get(surface.artifact)
        if rows is None:
            continue
        players: set[str] = set()
        for row in rows:
            player_id = row.get("player_id")
            if not player_id:
                continue
            players.add(str(player_id))
            position = row.get("position")
            if position:
                positions.setdefault(str(player_id), str(position))
        surfaces[surface.artifact] = frozenset(players)
    return PortraitPopulation(surfaces=surfaces, positions=positions)


# ------------------------------------------------------------------------------- crosswalk


class PortraitGap(StrEnum):
    """Why a population player has no portrait row. Counted, never inferred."""

    #: Neither this season's roster nor last season's names him, so nothing verifies who he is.
    NOT_IN_REGISTRY = "not_in_identity_registry"
    #: The registry knows him and no bridge carries an ESPN id for him.
    NO_PROVIDER_ID = "no_espn_id"
    #: An id was supplied and failed the ESPN id format; it is never rendered.
    INVALID_PROVIDER_ID = "invalid_espn_id"
    #: Another canonical player claims the same id. Refused for both (fail closed, ADR-005).
    AMBIGUOUS_PROVIDER_ID = "ambiguous_espn_id"


class PortraitBridge(StrEnum):
    """Which verified, nflverse-native bridge supplied a published id."""

    #: ``espn_id`` on the roster row the identity registry kept (ADR-019's primary bridge).
    ROSTER = "nflverse_roster"
    #: ``espn_id`` on nflverse's player master, same GSIS key, used only to fill a gap.
    PLAYER_MASTER = "nflverse_player_master"


@dataclass(frozen=True)
class PortraitCrosswalk:
    """Canonical ``player_id`` to a verified provider id, and the reason for every refusal."""

    ids: Mapping[str, str]
    bridges: Mapping[str, PortraitBridge] = field(default_factory=dict)
    gaps: Mapping[str, PortraitGap] = field(default_factory=dict)

    def resolve(self, player_id: str) -> tuple[str | None, PortraitGap | None]:
        provider_id = self.ids.get(player_id)
        if provider_id is not None:
            return provider_id, None
        return None, self.gaps.get(player_id, PortraitGap.NOT_IN_REGISTRY)

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, object]) -> PortraitCrosswalk:
        """A plain ``player_id -> raw id`` mapping, normalized and checked for shared ids.

        The same rules as the registry path: a sentinel is absent, a malformed id is refused,
        and an id two players claim is refused for both.
        """
        return _settle(
            {player_id: (raw, PortraitBridge.ROSTER) for player_id, raw in mapping.items()}
        )


def crosswalk_from_registry(
    registry: CanonicalRegistry,
    *,
    player_master: pl.DataFrame | None = None,
) -> PortraitCrosswalk:
    """``player_id -> espn_id`` off the canonical registry, failing closed.

    The registry is the right place to read this and a roster frame is not: it has already
    taken one row per GSIS id and refused a GSIS id a prior roster gives to two players
    (ADR-102), and it indexes every external id so a shared one is visible
    (``registry.collisions``). Every such id is refused here for *every* player claiming it -
    the registry's lookup would refuse it too, and a portrait is a lookup in the other
    direction.

    ``player_master`` (nflverse's ``load_players``, the same publisher and licence as the
    roster) may fill an id the roster leaves empty, for a player the registry already
    identifies, by exact GSIS key. Never a new player, never an override: the roster wins every
    disagreement, and a master id that any other player holds - on a roster or in the master -
    is refused. On 2026-11-06 the master agreed with the 2026 roster on 817 of the 818 skill
    players both carry an id for.
    """
    candidates: dict[str, tuple[object, PortraitBridge]] = {
        player_id: (player.crosswalk.espn_id, PortraitBridge.ROSTER)
        for player_id, player in registry.players.items()
    }
    # The registry's own collision index, honoured as well as recomputed: an id it has
    # poisoned stays poisoned even if normalization would have told the two apart.
    poisoned: set[str] = set()
    for value in registry.collisions.get(IdNamespace.ESPN, {}):
        normalized = normalize_id(IdNamespace.ESPN, value).value
        if normalized is not None:
            poisoned.add(normalized)
    return _settle(candidates, poisoned=poisoned, master=_master_ids(player_master))


def _master_ids(frame: pl.DataFrame | None) -> dict[str, str | None]:
    """``player_id -> raw espn_id`` from the player master; empty when it is unusable."""
    if frame is None or frame.is_empty() or not {"gsis_id", "espn_id"} <= set(frame.columns):
        return {}
    ids: dict[str, str | None] = {}
    repeated: set[str] = set()
    for gsis, espn in frame.select("gsis_id", "espn_id").iter_rows():
        gsis_id = normalize_id(IdNamespace.GSIS, gsis).value
        if gsis_id is None:
            continue
        player_id = make_player_id(IdNamespace.GSIS, gsis_id)
        if player_id in ids:
            repeated.add(player_id)
        ids[player_id] = None if espn is None else str(espn)
    # A GSIS id on two master rows says nothing reliable about either.
    for player_id in repeated:
        ids[player_id] = None
    return ids


def _settle(
    candidates: Mapping[str, tuple[object, PortraitBridge]],
    *,
    poisoned: set[str] | None = None,
    master: Mapping[str, str | None] | None = None,
) -> PortraitCrosswalk:
    """Normalize every candidate, then refuse every id more than one player holds."""
    gaps: dict[str, PortraitGap] = {}
    primary: dict[str, list[str]] = {}
    for player_id, (raw, _) in candidates.items():
        normalized = normalize_id(IdNamespace.ESPN, raw)
        if normalized.value is not None:
            primary.setdefault(normalized.value, []).append(player_id)
        elif normalized.malformed:
            gaps[player_id] = PortraitGap.INVALID_PROVIDER_ID
        else:
            gaps[player_id] = PortraitGap.NO_PROVIDER_ID

    ids: dict[str, str] = {}
    bridges: dict[str, PortraitBridge] = {}
    blocked = set(poisoned or ())
    for value, owners in primary.items():
        if len(owners) > 1 or value in blocked:
            for player_id in owners:
                gaps[player_id] = PortraitGap.AMBIGUOUS_PROVIDER_ID
            continue
        ids[owners[0]] = value
        bridges[owners[0]] = candidates[owners[0]][1]

    if master:
        # Every id the master gives anyone, so a fill cannot hand one player another's face.
        master_owners: dict[str, set[str]] = {}
        for player_id, raw in master.items():
            held = normalize_id(IdNamespace.ESPN, raw).value
            if held is not None:
                master_owners.setdefault(held, set()).add(player_id)
        for player_id, gap in list(gaps.items()):
            if gap is not PortraitGap.NO_PROVIDER_ID or player_id not in master:
                continue
            fill = normalize_id(IdNamespace.ESPN, master[player_id]).value
            if fill is None:
                continue
            if fill in primary or fill in blocked or master_owners.get(fill, set()) != {player_id}:
                gaps[player_id] = PortraitGap.AMBIGUOUS_PROVIDER_ID
                continue
            ids[player_id] = fill
            bridges[player_id] = PortraitBridge.PLAYER_MASTER
            del gaps[player_id]
    return PortraitCrosswalk(ids=ids, bridges=bridges, gaps=gaps)


# --------------------------------------------------------------------------------- records


@dataclass
class HeadshotResult:
    """The records plus the coverage evidence the metadata block publishes."""

    build_id: str
    records: list[dict[str, Any]]
    population: PortraitPopulation
    #: Population players with no row, and why.
    gaps: Mapping[str, PortraitGap]
    #: Published players, and which bridge supplied each id.
    bridges: Mapping[str, PortraitBridge]

    @property
    def published_players(self) -> int:
        """The denominator: distinct players named by any surface this build read."""
        return len(self.population.players)

    @property
    def resolved(self) -> int:
        return len(self.records)

    @property
    def unresolved(self) -> tuple[str, ...]:
        return tuple(sorted(self.gaps))

    @property
    def coverage(self) -> float:
        if self.published_players == 0:
            return 0.0
        return self.resolved / self.published_players

    def summary(self) -> dict[str, Any]:
        """The metadata block (``build_metadata`` or ``ros_build_metadata``)."""
        published = {str(record["player_id"]) for record in self.records}
        by_position: dict[str, dict[str, int]] = {}
        for player_id in self.population.players:
            position = self.population.positions.get(player_id, "unknown")
            cell = by_position.setdefault(position, {"players": 0, "resolved": 0})
            cell["players"] += 1
            cell["resolved"] += int(player_id in published)
        return {
            "provider": HEADSHOT_PROVIDER,
            "host": HEADSHOT_HOST,
            "source_ids": list(HEADSHOT_SOURCE_IDS),
            "population": {
                "rule_version": self.population.rule_version,
                "surfaces_read": list(self.population.surfaces_read),
                "players": self.published_players,
            },
            "published_players": self.published_players,
            "resolved": self.resolved,
            "coverage": round(self.coverage, 4),
            "by_surface": {
                name: {"players": len(players), "resolved": len(players & published)}
                for name, players in self.population.surfaces.items()
            },
            "by_position": dict(sorted(by_position.items())),
            "unresolved_reasons": {
                gap.value: sum(1 for reason in self.gaps.values() if reason is gap)
                for gap in PortraitGap
            },
            "bridges": {
                bridge.value: sum(1 for value in self.bridges.values() if value is bridge)
                for bridge in PortraitBridge
            },
        }


def build_player_headshot_records(
    *,
    crosswalk: PortraitCrosswalk | Mapping[str, object],
    population: PortraitPopulation,
    build_id: str,
    gate: QualityGate | None = None,
) -> HeadshotResult:
    """Build the artifact rows for the portrait population.

    ``crosswalk`` is :func:`crosswalk_from_registry`'s result (a plain mapping is normalized
    the same way). ``population`` is :func:`portrait_population` over the records the build
    publishes; the rows are exactly its players with a verified id, and nobody else.
    """
    resolved_crosswalk = (
        crosswalk
        if isinstance(crosswalk, PortraitCrosswalk)
        else PortraitCrosswalk.from_mapping(crosswalk)
    )
    # Imported here: `ffdraft.artifacts` imports the validator, which imports this module's
    # constants, so a module-level import made `import ffdraft.headshots` fail on its own.
    from ffdraft.artifacts import record_schema_version

    records: list[dict[str, Any]] = []
    gaps: dict[str, PortraitGap] = {}
    bridges: dict[str, PortraitBridge] = {}
    version = record_schema_version(_HEADSHOT_SCHEMA)

    for player_id in population.players:
        provider_id, gap = resolved_crosswalk.resolve(player_id)
        if provider_id is None:
            # Not an error. The bridges reach most players and not all of them, and a card
            # without a portrait is a card, so this fails soft by construction.
            gaps[player_id] = gap or PortraitGap.NOT_IN_REGISTRY
            continue
        bridges[player_id] = resolved_crosswalk.bridges.get(player_id, PortraitBridge.ROSTER)
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
        population=population,
        gaps=gaps,
        bridges=bridges,
    )
    if gate is not None:
        gate.extend(_coverage_checks(result))
    return result


def _coverage_checks(result: HeadshotResult) -> Sequence[QualityCheck]:
    """Report coverage; never fail on it.

    There is deliberately no minimum. A portrait is decoration, so a thin crosswalk degrades
    the card and nothing else - and a gate that could stop a deploy over a missing picture
    would be able to take the whole board down for a cosmetic reason.
    """
    summary = result.summary()
    surfaces = ", ".join(
        f"{name} {cell['resolved']}/{cell['players']}"
        for name, cell in summary["by_surface"].items()
    )
    reasons = ", ".join(
        f"{reason} {count}" for reason, count in summary["unresolved_reasons"].items() if count
    )
    bridges = ", ".join(
        f"{bridge} {count}" for bridge, count in summary["bridges"].items() if count
    )
    return (
        QualityCheck.ok(
            "headshots.coverage",
            stage="artifacts.headshots",
            message=(
                f"card-surface players with a portrait crosswalk entry ({PORTRAIT_POPULATION_RULE})"
            ),
            observed=(
                f"{result.resolved}/{result.published_players} ({result.coverage:.1%}) via "
                f"{HEADSHOT_PROVIDER}; {surfaces or 'no surface read'}; "
                f"unresolved: {reasons or 'none'}; bridges: {bridges or 'none'}"
            ),
        ),
    )
