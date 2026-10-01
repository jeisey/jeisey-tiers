"""The versioned venue registry (``config/venues.yaml``) and how a game resolves to a venue.

A forecast is for a place, and the schedule does not reliably name the place:

* nflverse files a 2026 Jacksonville "home" game in London under ``JAX00`` while naming the
  stadium "Tottenham Hotspur Stadium";
* the same file calls the Melbourne Cricket Ground, the Stade de France and the Allianz Arena
  ``dome`` (all three are open to the sky) and gives the Bernabeu no roof at all;
* a stadium is renamed (Paul Brown -> Paycor) and a team moves into a new building (Buffalo,
  2026) without the id changing.

So a venue is a registry entry with a **stable id**, the schedule ids and stadium names that
resolve to it (``aliases``), its **coordinates** and its **fixed roof type** (``open``,
``retractable``, ``dome``, or ``unverified`` when the evidence does not establish it), each
with **provenance** (docs/DATA_SOURCES.md §20). A game
resolves by its stadium *name* first, because the name is what the 2026 file gets right when
the id is stale, then by id within the seasons an id was in use. A game that resolves to no
venue, or to two, gets no venue: its weather is unknown, never guessed.

**Venue type is not roof state.** A retractable roof's state for a game is recorded only after
kickoff; before it, the venue type is known and the state is not. Nothing here infers a state
from an earlier game.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from ffdraft.paths import repo_root

__all__ = [
    "ROOF_TYPES",
    "ROOF_TYPE_CODES",
    "Venue",
    "VenueRegistry",
    "load_venue_registry",
    "roof_type_code",
]

#: ``unverified``: the evidence does not establish whether weather reaches the field. It fails
#: closed exactly like an unresolved venue: no ``wx_roof_type`` and no weather.
ROOF_TYPES: tuple[str, ...] = ("open", "retractable", "dome", "unverified")

#: The model input ``wx_roof_type``. An ``unverified`` venue has none (``null``).
ROOF_TYPE_CODES: Mapping[str, float] = {"open": 0.0, "retractable": 1.0, "dome": 2.0}


def roof_type_code(venue: Venue | None) -> float | None:
    """``wx_roof_type`` for a venue: ``None`` when unresolved or unverified."""
    return None if venue is None else ROOF_TYPE_CODES.get(venue.roof_type)

DEFAULT_REGISTRY = Path("config/venues.yaml")


@dataclass(frozen=True)
class Venue:
    venue_id: str
    name: str
    country: str
    latitude: float
    longitude: float
    roof_type: str
    forecast_provider: str
    schedule_ids: tuple[str, ...]
    aliases: tuple[str, ...]
    first_season: int | None
    last_season: int | None
    provenance: Mapping[str, str]

    def in_use(self, season: int) -> bool:
        return (self.first_season is None or season >= self.first_season) and (
            self.last_season is None or season <= self.last_season
        )

    def public(self) -> dict[str, Any]:
        """What the published context carries about the venue."""
        return {
            "venue_id": self.venue_id,
            "name": self.name,
            "country": self.country,
            "roof_type": self.roof_type,
            "latitude": self.latitude,
            "longitude": self.longitude,
        }


def _normalise(name: str | None) -> str:
    return " ".join(str(name or "").replace("’", "'").lower().split())


@dataclass(frozen=True)
class VenueRegistry:
    version: str
    digest: str
    venues: tuple[Venue, ...]

    def by_id(self, venue_id: str) -> Venue | None:
        return next((venue for venue in self.venues if venue.venue_id == venue_id), None)

    def resolve(
        self,
        *,
        season: int,
        stadium_id: str | None,
        stadium: str | None,
    ) -> Venue | None:
        """The one venue a schedule row names, or ``None`` when that is not certain."""
        name = _normalise(stadium)
        if name:
            named = [
                venue
                for venue in self.venues
                if venue.in_use(season) and name in {_normalise(alias) for alias in venue.aliases}
            ]
            if len(named) == 1:
                return named[0]
            if len(named) > 1:
                return None
        if stadium_id:
            by_id = [
                venue
                for venue in self.venues
                if venue.in_use(season) and stadium_id in venue.schedule_ids
            ]
            if len(by_id) == 1:
                return by_id[0]
        return None


def load_venue_registry(path: Path | None = None) -> VenueRegistry:
    """Read and validate the registry. Raises ``ValueError`` on a malformed entry."""
    resolved = path or (repo_root() / DEFAULT_REGISTRY)
    raw_bytes = resolved.read_bytes()
    document = yaml.safe_load(raw_bytes)
    if not isinstance(document, Mapping):
        raise ValueError(f"{resolved} is not a mapping")
    venues: list[Venue] = []
    seen: set[str] = set()
    for entry in document.get("venues") or []:
        venue = _venue(entry)
        if venue.venue_id in seen:
            raise ValueError(f"duplicate venue id {venue.venue_id!r}")
        seen.add(venue.venue_id)
        venues.append(venue)
    return VenueRegistry(
        version=str(document.get("registry_version", "")),
        digest=hashlib.sha256(raw_bytes).hexdigest()[:16],
        venues=tuple(venues),
    )


def _strings(values: Sequence[Any] | None) -> tuple[str, ...]:
    return tuple(str(value) for value in values or ())


def _venue(entry: Mapping[str, Any]) -> Venue:
    roof = str(entry.get("roof_type"))
    if roof not in ROOF_TYPES:
        raise ValueError(f"{entry.get('venue_id')}: roof_type {roof!r} not in {ROOF_TYPES}")
    provider = str(entry.get("forecast_provider"))
    if provider not in {"nws", "open_meteo"}:
        raise ValueError(f"{entry.get('venue_id')}: forecast_provider {provider!r}")
    latitude = float(entry["latitude"])
    longitude = float(entry["longitude"])
    if not (-90.0 <= latitude <= 90.0 and -180.0 <= longitude <= 180.0):
        raise ValueError(f"{entry.get('venue_id')}: coordinates out of range")
    provenance = entry.get("provenance") or {}
    for key in ("coordinates", "roof_type"):
        if not provenance.get(key):
            raise ValueError(f"{entry.get('venue_id')}: provenance.{key} is required")
    seasons = entry.get("seasons") or [None, None]
    return Venue(
        venue_id=str(entry["venue_id"]),
        name=str(entry["name"]),
        country=str(entry["country"]),
        latitude=latitude,
        longitude=longitude,
        roof_type=roof,
        forecast_provider=provider,
        schedule_ids=_strings(entry.get("schedule_ids")),
        aliases=_strings(entry.get("aliases")),
        first_season=None if seasons[0] is None else int(seasons[0]),
        last_season=None if seasons[1] is None else int(seasons[1]),
        provenance={str(key): str(value) for key, value in provenance.items()},
    )


def venue_resolution(
    registry: VenueRegistry,
    games: Sequence[Mapping[str, Any]],
) -> dict[str, Venue | None]:
    """``game_id -> venue`` for schedule rows (``season``, ``stadium_id``, ``stadium``)."""
    return {
        str(game["game_id"]): registry.resolve(
            season=int(game["season"]),
            stadium_id=game.get("stadium_id"),
            stadium=game.get("stadium"),
        )
        for game in games
    }
